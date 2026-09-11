## system 模块编排(account 之后;全程 ops cert + sudo,无 root / 无 connect.sh)
前提:account 已 `close_check ✅`、cert 登录可用、NOPASSWD sudo 仍在(最后模块才撤)。运行顺序按确认:**performance → upgrade → security**。所有脚本走透明 `# 操作,命令 …` 契约(密码 `*****`)。

**长操作/重启两条铁律(被一次真实故障验证,后续模块/脚本必须遵守):**
- **会重启核心服务的特权操作,绝不能在控制连接上同步等待**。`apt full-upgrade` 会重启 dbus/systemd/sshd;若用 `systemd-run --property=Type=oneshot`(阻塞)或前台直跑,控制端的 D-Bus/SSH 会被重置而误报失败(服务端其实在继续)。一律 `systemd-run --collect --no-block` 真脱离,再**本地轮询单元状态**(`systemctl show -p ActiveState,Result <unit>`)判结果。
- **重启检测不要依赖 `/var/run/reboot-required`** —— 那是 Ubuntu/update-notifier 机制,**Debian 不建**。用运行内核 `uname -r` vs 最新已装 `/boot/vmlinuz-*` 比对;重连成功以**内核变为目标值**为准,避免 catch 到重启前的旧机误判。

**Phase S0 — preflight + 选 profile.**
S1. 跑 `bash ~/.agents/skills/ddln/system/script/preflight.sh`;非零→停、报 `MISSING`。
S2. 复用已明确的 profile;跑 `test_login.sh <profile>` 确认 account 已就绪(失败→先回去做 account)。

**Phase S1 — 性能(swap + sysctl).**
S3. 跑 `bash .../system/script/performance.sh <profile>`,转述透明输出;确认 BBR 生效行 `✓`。

**Phase S2 — 升级(可能重启).**
S4. 跑 `bash .../system/script/upgrade.sh <profile>` —— 长时操作:full-upgrade 经 `systemd-run` 脱离会话 + 本地轮询;需重启则自动 reboot + cert 轮询重连。**后台执行并通过运行状态与日志等待完成，不阻塞对话长时间等待**;结尾非 `success`→停,贴 `/var/log/dpt-upgrade.log` 末尾。

**Phase S3 — 安全加固(防火墙端口管理).**
S5. **展示现状 + 保持/取消 + 新增**(不要只问"加哪些"):
    - 先跑 `bash .../system/script/list_fw_ports.sh <profile>` 列出**当前已放行的额外端口**(SSH `DPT_PORT` 强制放行,不列、不可取消;输出 `NONE` = 暂无额外端口)。
    - 在对话中把每个现有端口列成编号清单,让用户明确回复**保持/取消**项,并允许用户**新增**端口;不要调用 `request_user_input` 或其他只能单选的选择题工具。
    - 算两个集合:**保留 + 新增 → `--allow`**;**取消的 → `--remove`**。展示最终计划(放行哪些 / 取消哪些)+ 确认后继续。
S6. 跑 `bash .../system/script/security_enhance.sh <profile> --allow "<保留+新增>" --remove "<取消>"`(任一可空)。
    - 结尾 `安全加固完成`→继续。
    - ufw 启用后证书复验失败而 `exit 1`→停;报告 **dead-man's-switch 将在 120s 内自动 `ufw disable` 恢复登录**,提示查放行端口/云安全组后重跑(脚本幂等)。

**S6b–S6d — 对外监听审计(不能静默留着开;ufw 只管"放行清单",本步查"谁在监听").**
本步把实际在 **非 loopback**(0.0.0.0/::/公网 IP)监听、却**不在允许集**(SSH + ufw 放行端口)的服务全捞出来,逐项问用户是否关闭 —— 绝不静默留着一个对外监听。
S6b. 跑 `bash .../system/script/list_listeners.sh <profile>`(只读)→ 每行 `port|bind|process`;输出 `NONE`=无意外对外监听,跳过本步。
S6c. **逐项**把意外对外监听项(端口/绑定/进程)列给用户,在对话中逐项问**每一项**是否关闭 + 方式(展示现状让用户定,绝不替用户默认关关键服务):
    - **MTA**(postfix/exim,如 `25|0.0.0.0|master`)→ `postfix-loopback`(绑 loopback,仍能发件、不再对外收)。
    - **systemd-resolve 的 LLMNR/mDNS**(如 `5355|...|systemd-resolve`)→ `resolved-llmnr-off`(通常无用,可关)。
    - **其它服务** → `stop-unit <unit>`(彻底停用禁用),或**保留**(如 nginx:80 作 HTTP→HTTPS 跳转、ufw 已挡外部时)。
S6d. 对用户选"关闭"的每一项跑 `bash .../system/script/close_listener.sh <profile> <mode> [unit]` 执行;全部处理完**重跑 `list_listeners.sh`** 复核并转述结果(理想:只剩用户明确保留的项)。

**Phase S4 — 收尾.**
S7. 跑 `bash .../system/close/close_check.sh <profile>`;`❌`→逐条列出 FAILED 行。
S8. 报告:升级结果、swap/BBR、加固通过项;提醒 NOPASSWD sudo 仍待最后模块撤销。system 模块无 root 通道,无需 `disconnect`。

**日志管理 + 本地副本(`security_enhance.sh` 的 I/J 段,全幂等):**
- **本机基线**:journald 持久化+限额(`SystemMaxUse=500M`、保留 30 天、压缩)、装 logrotate、auditd 封顶(50M×5 ROTATE)、`/var/log/*.log` 去全局可读。
- **本地日志副本(障眼法,= 用户选的 A+B)**:`systemd` 定时器每天把 journald+auditd 导出到运营用户家目录 `~/.cck/*.cck`(目录 700,`.cck` 后缀避开 `*.log` 扫描)。**机制故意起不显眼名:timer/service/script 都叫 `sys-cache-maint`(`/usr/local/lib/sys-cache-maint`)—— 它的真身就是日志备份,别被自己的伪装骗了。**
- **定位(诚实)**:`.cck` 只防"懒/自动清痕";拿到 root 仍可 `find -name '*.cck'` 找到删掉。**真防篡改 = 异地 append-only(方案 C,尚未做)。** 保留 30 天自动 prune,空间峰值 ≈1–1.5G,79G 盘绰绰有余。

**进阶系统安全(本轮补进 `security_enhance.sh` / 规则文件,全幂等):**
- **进阶内核 sysctl**(进 `security_hardening.rules`,run_checks 应用+审计):`kernel.yama.ptrace_scope=1`、`net.core.bpf_jit_harden=2`、`kernel.kexec_load_disabled=1`、`fs.protected_fifos=2`、`dev.tty.ldisc_autoload=0`;另 `unprivileged_bpf_disabled=2`/`fs.protected_regular=2`/`perf_event_paranoid=3` 已达标只验证。**取值先探测,绝不下调更强的默认。**
- **故意不设 `kernel.unprivileged_userns_clone`** —— 留给 Docker(要部署容器);设 0 会破坏非特权容器/沙箱。
- **rootkit 检测**:rkhunter(每日扫 + `APT_AUTOGEN` apt 后自动更基线 + `--propupd` 初始化)、chkrootkit(每日扫);结果经 `sys-cache-maint` 落 `~/.cck/rkhunter-*.cck`。
- **日志摘要**:logwatch 每日摘要由 `sys-cache-maint` 写入 `~/.cck/logwatch-*.cck`(无 MTA → 停默认邮件 cron)。
- **未采纳 `ufw limit` SSH 限速**:与部署连接模式冲突(每轮几十个 rexec 会自伤),且 fail2ban 已防爆破;要上须先给系统模块加 ControlMaster。
