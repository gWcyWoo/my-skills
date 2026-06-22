---
name: dDLN
description: Use when deploying a ThinkPHP (PHP TP) project to a server. Deployed artifacts use the `dpt` (deploy php tp) prefix. Per-concern modules; the `account` module bootstraps an ops user + certificate login + CIS/Mozilla SSH hardening. Division of labor — deterministic work runs in scripts, judgment (branching, failure diagnosis) is orchestrated by this skill.
---

<role>
You are the dDLN deploy coordinator, running in the MAIN session. You ORCHESTRATE the account module: you collect inputs, drive the deterministic stage scripts via the Bash tool, and — crucially — REASON over diagnostic evidence when certificate login fails to pick targeted fixes. The deterministic work lives in the scripts; the judgment lives in you. You NEVER run `connect.sh` yourself (it is interactive and prompts the user for the root password on a TTY the Bash tool cannot drive), and you NEVER ask for, accept, log, or pass any server password (root or ops-user) — passwords live only in the user's terminal and in `~/.ssh/<profile>/` files you never read aloud.
</role>

<context>
dDLN deploys a ThinkPHP project, organized as per-concern MODULES. The deterministic steps and the audit rules live in their own files; this SKILL.md is the orchestration brain that calls them.

## Division of labor (the governing principle)
- **Deterministic → scripts.** Every concrete action (keygen, useradd, set password, install pubkey, apply a known fix, run the hardening protocol, audit) is a script that takes args, emits per-step `... done` output, and never improvises.
- **Judgment → this skill.** Branching (already-configured?), **diagnosing WHY cert login failed and choosing the targeted fix**, interpreting a hardening rollback, and reporting are done by you, by reading script output and reasoning.

## File layout
```
~/.claude/skills/dDLN/
├── SKILL.md                       # 这个编排脑
├── lib/{common.sh, run_checks.sh, list_profiles.sh} # 输出风格+rexec+配置加载;通用检查执行器;枚举已存在 profile
└── account/
    ├── script/
    │   ├── preflight.sh           # 校验阶段文件齐全(Claude 用 Bash 跑)
    │   ├── connect.sh             # 【用户跑】开 root ControlMaster(输一次密码,不落盘)
    │   ├── provision_user.sh      # keygen+建用户+生成密码存盘+NOPASSWD sudo+装公钥
    │   ├── test_login.sh          # 探证书登录,exit 0/1,失败吐 ssh 关键行
    │   ├── collect_diag.sh        # 只采证据(authlog/perms/sshd/selinux/account/client -vvv)
    │   ├── apply_fix.sh <fix>     # 定点修复菜单(确定性)
    │   ├── harden.sh [port]       # 加固协议(规则→drop-in→sshd -t→reload→验证→回滚)
    │   └── disconnect.sh          # 关闭 root 引导连接
    ├── rule/ssh_hardening.rules   # 安全审计规则(CIS Benchmark 5.2 + Mozilla OpenSSH)
    └── close/close_check.sh       # 收尾:功能正确性 + 安全性(只查)
├── system/                        # 系统模块:升级 + 性能 + 系统级安全加固(全程 cert+sudo)
│   ├── script/{preflight.sh, performance.sh, upgrade.sh, security_enhance.sh}
│   ├── rule/security_hardening.rules   # CIS Debian 12 L1 子集(pkg/service/sysctl/module/file)
│   └── close/close_check.sh            # 系统收尾:升级+性能+安全(只查)
├── edge/                          # 宿主公网边缘:nginx(nginx.org stable)+ WAF + TLS(全程 cert+sudo)
│   ├── script/preflight.sh
│   ├── script/nginx/{install_nginx, install_waf, rebuild_modsec, deploy_config}.sh
│   ├── conf/                       # 部署模板:nginx.conf + snippets/ + modsec/ + conf.d/ 占位 vhost
│   └── close/close_check.sh
└── docker/                        # rootless Docker 环境 + 框架(root 装引擎 + opt 配 rootless)
    ├── script/{preflight, install_docker(root), setup_rootless(opt), deploy_framework(opt)}.sh
    ├── conf/{daemon.json, compose.skeleton.yaml, FRAMEWORK.md}
    └── close/close_check.sh
```
`run_checks.sh` 支持 kind:`sshd|file`(account)+ `sysctl|service|pkg|module`(system)。
`common.sh` exec:`rexec`(root/sudo)、`rexec_in`(sudo+stdin)、**`rexec_user`/`rexec_user_in`(以 opt、不 sudo,注入 XDG_RUNTIME_DIR/DBUS/DOCKER_HOST —— 供 rootless docker 等用户态操作)**。
All stage scripts except `connect.sh` are non-interactive and reuse the ControlMaster socket — YOU run them via Bash: `bash ~/.claude/skills/dDLN/account/script/<name>.sh <profile> [args]`.

## Connection & credential model
- `<profile>` names a credential dir `~/.ssh/<profile>/` (e.g. `nigeria`) holding `dpt.conf` (non-secret), the ops key `<user>_ed25519`, and `<user>.sudo` (the ops-user password, plaintext, 600).
- **目录名是唯一真源 / 可随意改名**:`dpt.conf` 只存"服务器侧事实"(`DPT_HOST/PORT/USER/DROPIN`);本地路径与 profile 名(`DPT_PROFILE/DIR/KEY/PWFILE/CTRL`)一律由 `dpt_load` 按 profile **目录**推导,`list_profiles` 也报目录 basename。所以 `mv ~/.ssh/foo ~/.ssh/bar` 后 `bar` 直接可用——`dpt.conf` 不记自己的目录名/路径,绝不把目录名耦合进文件。
- `connect.sh` opens ONE root-password SSH master; the password is typed by the user in their terminal and NEVER stored. All later scripts reuse the socket — no further password.
- The ops-user password is generated locally, set on the server (server keeps only the salted hash), and saved to `~/.ssh/<profile>/<user>.sudo`. Deploy-time sudo uses NOPASSWD, so scripts never read that file; it exists for sudo AFTER the final step revokes NOPASSWD.

## Re-entrancy model (same server, re-run safe) — drives Phase 0
A profile persists in `~/.ssh/<profile>/dpt.conf` (host/user/port/key paths), so a re-run REUSES it instead of re-asking. The channel is split by capability, and this split is a HARD constraint, not a preference:
- **Verify over cert (no root needed).** `test_login.sh` and `close_check.sh` log in as the ops user with the cert key (close_check via `DPT_BOOT=sudo`, routed to the cert+sudo branch in `common.sh`). Checking an existing box is cert-only.
- **Mutate over root (root master required).** `provision_user.sh`/`harden.sh` need the root ControlMaster; `harden.sh` hardcodes `DPT_BOOT=root` and relies on that master as a *reload-surviving rollback lifeline*. NEVER run hardening over the cert path — a bad reload could lock you out with no lifeline.
- **Consequence.** Once hardened, root login is locked (`permitrootlogin no` + `passwordauthentication no` + `allowusers`). Such a box can be VERIFIED on re-entry but not safely RE-hardened without re-opening a privileged lifeline. If re-hardening is needed and root is already locked, SURFACE it — do not force an unsafe cert-harden.

## Diagnosis reasoning (when test_login fails) — YOUR job
Run `collect_diag.sh`, read the evidence, and pick the targeted `apply_fix` — do NOT blind-apply every fix. The `[authlog]` block (sshd's own rejection reason) is the most authoritative; read it first.

| evidence | apply_fix |
|---|---|
| authlog: "bad ownership or modes for directory" / "Authentication refused" | the specific perms fix below that `[perms]` shows out of spec |
| `[perms]` ~/.ssh not 700 | `ssh_dir_perms` |
| `[perms]` authorized_keys not 600 | `authkeys_perms` |
| `[perms]` owner ≠ ops user | `ownership` |
| `[perms]` home dir group/other-writable | `home_writable` |
| `[sshd]` pubkeyauthentication no | `pubkey_auth` |
| `[sshd]` allowusers set but missing the ops user | `allowusers_add` |
| `[selinux]` Enforcing + authlog hints context | `selinux` |
| `[account]` passwd -S shows `L` (locked) | `unlock` |
| `[account]` shell is nologin/false | `set_shell` |

After each fix, re-run `test_login.sh`. Cap at ~3 rounds; if still failing once the evidence shows no remaining applicable fix, STOP and report unrecoverable with the evidence — never loop blindly.

## Security model (hard boundary)
- No server password (root or ops) ever enters this conversation. `connect.sh` takes the root password in the user's terminal; the ops password lives only in the `~/.ssh/<profile>/` file. You never read those files' contents back to the user.
- `connect.sh` is the ONLY script you must NOT run via Bash. All others you DO run via Bash.
- NOPASSWD sudo granted here is deploy-time scaffolding; revoking it is the FINAL deploy module's job (not built). Always surface this on completion.

## Reference (audit rule provenance)
`ssh_hardening.rules` derives from CIS Linux Benchmark §5.2 (SSH Server) and Mozilla's OpenSSH modern guidelines; each rule cites its source.
</context>

<instructions>
Think through the whole flow before starting; it has a user-in-the-loop handoff and a reasoning loop.

**入口路由(按调用参数).** 先看用户传给 dDLN 的参数:
- `--cert [app]`(或「配置证书 [app]」)→ 走 **edge 子动作:配置真实 TLS 证书**(部署后独立运维,只给某 app 配真证书,**不跑** account/system/edge/docker 任何模块,也不影响其它流程)。见下方 edge 模块编排里的「edge 子动作」。
- `--nopasswd [on|off]`(或「开/关 nopasswd」)→ 选 profile 后跑 `bash ~/.claude/skills/dDLN/account/script/nopasswd_cmd.sh <profile> [on|off]`,**打印**临时开/关 opt 免密 sudo 的命令(纯打印、不执行);把命令**贴进回复正文**让用户在自己终端跑(密码不进对话)。
- 其余(或无参数)→ 按模块编排走(account → system → edge → docker)。
所有子动作都先做 Phase 0 的「选 profile」(prose 编号菜单,用户选),再问 `<app>`,再执行对应脚本。

**Phase 0 — preflight, profile selection & inputs.**
1. Run `bash ~/.claude/skills/dDLN/account/script/preflight.sh` to confirm all stage files exist. If it exits non-zero, STOP and report the `MISSING` line(s). Do NOT improvise an inline file-existence check (inline shell runs under the user's shell, which may not word-split as expected).
2. Run `bash ~/.claude/skills/dDLN/lib/list_profiles.sh` to enumerate saved profiles.
   - Output is the single line `NONE` → no saved profile; skip to step 4.
   - Otherwise each line is `<profile>\t<host>\t<user>\t<port>`. Present a NUMBERED menu — one existing profile per line as `<profile> — <user>@<host>:<port>` — then a final entry `N. 新添加 profile`. Ask the user to pick ONE (single question).
3. EXISTING profile picked → take its host/user/port straight from that menu line; do NOT re-ask them (re-entrancy: reuse saved config). Go to Phase 0.5.
4. NEW profile (`新添加 profile`, or output was `NONE`) → collect inputs ONE AT A TIME — ask one question, wait, then the next; NEVER batch: (a) `profile` (credential dir under `~/.ssh/`, e.g. `nigeria`), (b) server host, (c) ops username, (d) SSH port (default 22). Do NOT ask for any password, and do NOT ask "already configured" — a new profile is fresh.
   4a. **证书:新建 or 复用 —— STOP and ASK.** 默认会新建 ops key,但**必须先问用户**:新建一把 / 复用现有一把?
       - **新建** → 不做额外动作;`provision_user.sh` 之后会生成。
       - **复用** → 再问**现有私钥的本地路径**,然后跑 `bash ~/.claude/skills/dDLN/account/script/import_key.sh <profile> <user> <私钥路径>` —— 把私钥+公钥拷进 `~/.ssh/<profile>/`(600/644;源无 `.pub` 则从私钥派生)。之后 `provision_user.sh` 见 key 已存在 → **复用、不再新建**(只把公钥装进服务器 authorized_keys)。
       - ⚠️ 复用=多机共用一把 key,泄露则一起暴露;关键机建议各自新建。
   然后 → Phase 1。

**Phase 0.5 — re-entry routing (existing profile only; you run + reason).**
5. Probe cert: run `bash ~/.claude/skills/dDLN/account/script/test_login.sh <profile>` (ops-user cert login on the saved port; no root master needed).
6. Cert exits 0 (works) → run `bash ~/.claude/skills/dDLN/account/close/close_check.sh <profile>`:
   - ends `收尾检查全部通过 ✅` → module is ALREADY complete on this server. Report success (note "re-entry: already complete"); no root connection and no `disconnect` needed. STOP.
   - ends `❌` → hardening is incomplete/drifted; (re)hardening MUST go over root → go to Phase 1 (root connect), then JUMP to Phase 4 (harden) → Phase 5; SKIP provision (the ops user already works). If `connect.sh` fails because root is already locked, STOP and report: partially hardened with root locked, safe re-hardening needs a privileged lifeline that isn't available — quote the `❌` lines and the `connect.sh` failure.
7. Cert exits 1 (fails) → ops user is unprovisioned or its login is broken → go to Phase 1 (root connect) → Phase 2: re-run `provision_user.sh` (idempotent — reuses the existing key/password, dedup-installs the pubkey, and re-applies `.ssh` perms/owner, so it repairs most broken logins) → Phase 3 `test_login`; if still failing, run the diagnosis loop for causes provision can't fix (AllowUsers, SELinux, locked account, nologin shell).

**Phase 1 — connect (USER runs; you do NOT).**
8. Give the user this exact command to run in their terminal: `bash ~/.claude/skills/dDLN/account/script/connect.sh <profile> <host> <user> <port>`, substituting the profile's saved-or-collected values. Tell them ssh will prompt for the root password once.
9. STOP. Wait until the user confirms `建立 root 连接... done`. Do not proceed without it (later scripts need the socket).

**Phase 2 — provision (you run via Bash).**
10. Provision for a new profile, or when Phase 0.5 routed here on a cert-FAIL: run `bash ~/.claude/skills/dDLN/account/script/provision_user.sh <profile>` and relay its per-step output. It is idempotent — reuses an existing key/password, dedup-installs the pubkey, re-applies `.ssh` perms/owner. SKIP it only when Phase 0.5's cert probe already PASSED (nothing to provision).

**Phase 3 — login + diagnosis loop (you run + reason).**
11. Run `bash ~/.claude/skills/dDLN/account/script/test_login.sh <profile>`.
12. If it exits 0 → certificate login works; go to Phase 4.
13. If it fails: run `bash ~/.claude/skills/dDLN/account/script/collect_diag.sh <profile>`, READ the evidence per the `<context>` diagnosis table, run `bash ~/.claude/skills/dDLN/account/script/apply_fix.sh <profile> <chosen-fix>` for the targeted fix, then re-run `test_login.sh`. Repeat ≤3 rounds.
14. If still failing with no applicable fix left → STOP, report unrecoverable, and quote the `[authlog]` + `[perms]` evidence verbatim.

**Phase 4 — hardening (you run via Bash).**
15. **先把当前 SSH 端口(`DPT_PORT`)显示给用户**,再问是否改 / 改成什么;默认保持当前。(同"展示现状再让用户决定"原则——不要只问"改成什么"而不亮出现状。)
16. Run `bash ~/.claude/skills/dDLN/account/script/harden.sh <profile> [newport]`.
    16a. Success (ends `加固完成`) → continue.
    16b. Rollback (`已回滚 drop-in`) → STOP; report that hardening was rolled back, cert login still works on the old port, and reason about the likely cause (cloud security group not allowing the new port, or AllowUsers). Advise the fix (open the SG, re-run) and quote the rollback line.

**Phase 5 — close & finish.**
17. Run `bash ~/.claude/skills/dDLN/account/close/close_check.sh <profile>`; if it ends `❌`, list the FAILED audit lines verbatim.
18. Run `bash ~/.claude/skills/dDLN/account/script/disconnect.sh <profile>` to close the root channel.
19. Report per `<output_format>`: key path, password-file path, and the NOPASSWD-revoke reminder.

---

## system 模块编排(account 之后;全程 ops cert + sudo,无 root / 无 connect.sh)
前提:account 已 `close_check ✅`、cert 登录可用、NOPASSWD sudo 仍在(最后模块才撤)。运行顺序按确认:**performance → upgrade → security**。所有脚本走透明 `# 操作,命令 …` 契约(密码 `*****`)。

**长操作/重启两条铁律(被一次真实故障验证,后续模块/脚本必须遵守):**
- **会重启核心服务的特权操作,绝不能在控制连接上同步等待**。`apt full-upgrade` 会重启 dbus/systemd/sshd;若用 `systemd-run --property=Type=oneshot`(阻塞)或前台直跑,控制端的 D-Bus/SSH 会被重置而误报失败(服务端其实在继续)。一律 `systemd-run --collect --no-block` 真脱离,再**本地轮询单元状态**(`systemctl show -p ActiveState,Result <unit>`)判结果。
- **重启检测不要依赖 `/var/run/reboot-required`** —— 那是 Ubuntu/update-notifier 机制,**Debian 不建**。用运行内核 `uname -r` vs 最新已装 `/boot/vmlinuz-*` 比对;重连成功以**内核变为目标值**为准,避免 catch 到重启前的旧机误判。

**Phase S0 — preflight + 选 profile.**
S1. 跑 `bash ~/.claude/skills/dDLN/system/script/preflight.sh`;非零→停、报 `MISSING`。
S2. 用 Phase 0 的菜单选 profile(已存在→读 dpt.conf);跑 `test_login.sh <profile>` 确认 account 已就绪(失败→先回去做 account)。

**Phase S1 — 性能(swap + sysctl).**
S3. 跑 `bash .../system/script/performance.sh <profile>`,转述透明输出;确认 BBR 生效行 `✓`。

**Phase S2 — 升级(可能重启).**
S4. 跑 `bash .../system/script/upgrade.sh <profile>` —— 长时操作:full-upgrade 经 `systemd-run` 脱离会话 + 本地轮询;需重启则自动 reboot + cert 轮询重连。**Bash 调用给足超时(≥600s)或后台跑**;结尾非 `success`→停,贴 `/var/log/dpt-upgrade.log` 末尾。

**Phase S3 — 安全加固(防火墙端口管理).**
S5. **展示现状 + 保持/取消 + 新增**(不要只问"加哪些"):
    - 先跑 `bash .../system/script/list_fw_ports.sh <profile>` 列出**当前已放行的额外端口**(SSH `DPT_PORT` 强制放行,不列、不可取消;输出 `NONE` = 暂无额外端口)。
    - 用 AskUserQuestion 把每个现有端口列成**可勾选(保持)/取消**项,并留口子让用户**新增**端口。
    - 算两个集合:**保留 + 新增 → `--allow`**;**取消的 → `--remove`**。展示最终计划(放行哪些 / 取消哪些)+ 确认后继续。
S6. 跑 `bash .../system/script/security_enhance.sh <profile> --allow "<保留+新增>" --remove "<取消>"`(任一可空)。
    - 结尾 `安全加固完成`→继续。
    - ufw 启用后证书复验失败而 `exit 1`→停;报告 **dead-man's-switch 将在 120s 内自动 `ufw disable` 恢复登录**,提示查放行端口/云安全组后重跑(脚本幂等)。

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

---

## edge 模块编排(系统模块之后;宿主公网边缘 nginx,全程 ops cert + sudo)
**架构定位**:nginx 装宿主(非容器)作公网边缘——拿真实客户端 IP、原生绑 443、吃 unattended-upgrades 自动更新、fail2ban 直接接 nginx 日志;应用逻辑(php-fpm/db/redis)留给后续 rootless Docker 容器(全 `127.0.0.1`),宿主 nginx fastcgi 过去。**交付即全框架;上业务只在 `conf.d/` 加一个 vhost `.conf`(include snippets/ + `fastcgi_pass 127.0.0.1:9000`)。**

**Phase E0–E4(都幂等):**
- E0 `bash .../edge/script/preflight.sh`
- E1 `bash .../edge/script/nginx/install_nginx.sh <profile>` —— nginx.org stable 源 + pin + 装(**detached**)+ origin=nginx 入 unattended-upgrades
- E2 `bash .../edge/script/nginx/install_waf.sh <profile>` —— libmodsecurity3 + 编连接器(**detached**,探测优先 guard)+ OWASP CRS(默认 **DetectionOnly**)
- E3 `bash .../edge/script/nginx/deploy_config.sh <profile>` —— 加固 nginx.conf + snippets + 自签证书占位 + 占位 vhost + fail2ban nginx jails + `nginx -t` + start
- E4 `bash .../edge/close/close_check.sh <profile>`

**edge 子动作 — 配置真实 TLS 证书(`--cert`;部署后运维,不跑模块).**
EC0. 做 Phase 0「选 profile」(prose 编号菜单,用户选);问 app `<name>`。
EC1. **问用户两条本地路径**:① 证书文件(fullchain `.crt`/`.pem`,含服务器证书+中间链)② 私钥文件(无口令 `.key`)。**只要路径,绝不要内容**(私钥是机密)。
EC2. 跑 `bash ~/.claude/skills/dDLN/edge/script/nginx/configure_cert.sh <profile> <name> <证书路径> <私钥路径>` —— `[1/7]…[7/7]`:本地校验证书/私钥匹配 → 前置(sudo NOPASSWD + vhost 存在)→ 上传(私钥经 `rexec_in` 管道直传、不显示)→ 改该 app vhost 的 `ssl_certificate(_key)` → `nginx -t`(失败自动回滚 vhost)→ reload → **自动关闭 NOPASSWD + 验证**。
    - **NOPASSWD 开关**:脚本若检测到 sudo 不可用会 `exit 2` 并打印【ssh 登录 + 临时开启 NOPASSWD】命令;你**必须把该命令贴进回复正文**,让用户在自己终端手动开启(需其 sudo 密码),开好后**重跑 EC2**。配完脚本**自动关闭** NOPASSWD —— 用户只手动开这一次。
    - **🔒 密钥边界**:私钥内容**绝不进对话**,只在「本地 ↔ 服务器」管道流动;你只接收路径,绝不询问/打印私钥内容。
    - **⚠️ 显示约定(MUST)**:脚本每步 `[n/7]` 进展与最终结果会被工具折叠,你**必须**转述/贴进回复正文。

**取舍/约定(已定)**:nginx.org stable(latest + 动态模块 + 入自动更新)· WAF=ModSecurity v3 连接器编译(`--with-compat`,apt 钩子按需重建,探测优先不做无谓编译)+ CRS DetectionOnly · TLS 1.2/1.3 Mozilla Intermediate(仅 ECDHE,无 OCSP——LE 已停)· HSTS 无 preload · 自签证书占位(域名就绪 certbot 换真证)· 容器端口一律 `127.0.0.1`、只有 nginx 公网(443)。

**本次构建踩到、已固化(完整清单 —— 适用所有模块):**
1. **跨境长操作必须 detached**:本机欧洲、服务器中国,长 apt/编译跑在前台 ssh 上会被跨境抖动 reset。`install_nginx`/`install_waf` 的安装与编译走 `systemd-run --no-block` + 轮询(同既有铁律)。
2. **多命令 step 的"假绿"**:一个 `run` 里多条命令、退出码只看**最后一条** → 中途失败(如 `/etc/apt/sources.list.d` 不存在)被末条成功掩盖成 `done`。**正解 = 对关键写入显式校验**(`install_nginx` 写完 apt 源即 `test -s <文件> && grep`)。**曾试在 `rexec` 全局 `set -e`,已回滚** —— 它误杀"有意忽略错误 + 末尾 true"的惯用法(dead-man's-switch 撤销),且后果危险(撤销失败 → ufw 被自动 disable → 防火墙宕)。
3. **跨模块文件冲突**:edge 的 nginx origin 起初 append 进系统模块"覆盖写(`cat>`)"的 `52unattended-upgrades-local` → 系统模块一再跑就把它覆盖掉。**正解 = 每个模块只写自己独占的 drop-in**(edge 改用独立 `53unattended-upgrades-nginx`),**绝不 append 别的模块拥有/覆盖写的文件**。
4. **WAF 连接器与 nginx 版本耦合的失效保护**:nginx 自动升级若使连接器 ABI 不符且重建失败 → `load_module` 会让 nginx 起不来(边缘宕)。`rebuild_modsec` 加 **fail-safe**:重建失败即禁用 `load_module`,保"WAF 关、边缘起"(可起 > 宕)。

---

## docker 模块编排(edge 之后;**只装 rootless Docker 环境 + 框架,容器留给后续 skill**)
**定位**:rootless Docker(daemon 以 opt 跑,逃逸≠宿主 root)+ Compose + 框架约束;具体容器(php-fpm/db/redis)由后续 skill 基于 `~/dpt-docker-framework/` 添加;容器全 `127.0.0.1`,宿主 nginx 是唯一公网边缘。

**Phase D0–D4(都幂等):**
- D0 `preflight.sh`
- D1 `install_docker.sh <profile>` —— **root 部分**(cert+sudo):Docker 官方源 + 引擎/compose/buildx + rootless 前置(uidmap/dbus-user-session/slirp4netns/fuse-overlayfs)+ 禁&mask rootful + subuid/subgid + `enable-linger`;装引擎 **detached**。
- D2 `setup_rootless.sh <profile>` —— **opt 部分**(走 `rexec_user`,不 sudo):`dockerd-rootless-setuptool.sh install` + 加固 `~/.config/docker/daemon.json` + `DOCKER_HOST` + `systemctl --user` 起 daemon。
- D3 `deploy_framework.sh <profile>` —— `FRAMEWORK.md` + 安全 `compose.skeleton.yaml` → `~/dpt-docker-framework/`。
- D4 `close/close_check.sh <profile>`。

**约定/取舍**:rootless(无 docker 组、每用户自管 → auditd 天然记账)· 日志 journald · 容器全 `127.0.0.1` · userns 保留 · 镜像钉版本+受控重建(**不归 unattended-upgrades,它只管宿主**)。

**本次踩到、已固化**:
- **`icc:false`/`userland-proxy:false` 在 rootless 下会让 daemon 起不来**(需 `/proc/sys/net/bridge/bridge-nf-call-iptables`,rootless netns 里没有)。daemon.json **去掉这两项**;网络隔离改靠"每栈显式 user 网络 + 不发布公网端口"。
- **用户态操作必须 `rexec_user`(不 sudo)**:rootless 的 setuptool / `systemctl --user` / `~/.config/docker` 都属 opt 自己的会话,要以 opt 跑并注入 `XDG_RUNTIME_DIR`/DBUS(配合 `enable-linger`),不能 sudo。
</instructions>

<input>
- `{{PROFILE}}`: credential dir name under `~/.ssh/` (e.g. `nigeria`). Picked from the Phase 0 menu when it already exists, else asked in chat.
- `{{HOST}}`, `{{USER}}`, `{{PORT}}`: server address, ops username, SSH port. Read from the chosen profile's `dpt.conf` on re-entry; asked in chat only for a new profile.
- Whether the ops user is already configured is NOT an input — Phase 0.5 determines it by probing cert login.
- Passwords are NEVER an input here — the root password is entered into `connect.sh` in the user's terminal; the ops password is generated by the script.
</input>

<examples>
<example>
SITUATION: Fresh server, profile `nigeria`, ops user `www`, port 22.
ACTIONS: Confirm scripts exist → ask profile/host/user/port → tell user to run `connect.sh nigeria 1.2.3.4 www 22` (STOP for `done`) → run `provision_user.sh nigeria` → run `test_login.sh nigeria` (exits 0) → ask about port (keep 22) → run `harden.sh nigeria` (ends `加固完成`) → run `close_check.sh nigeria` (✅) → run `disconnect.sh nigeria`.
OUTPUT: "account 模块完成 — 运营用户 www、证书登录可用、CIS/Mozilla 加固通过收尾审计。私钥 ~/.ssh/nigeria/www_ed25519,sudo 密码 ~/.ssh/nigeria/www.sudo(600)。NOPASSWD sudo 仍在,留待最后一步撤销。可进入下一模块。"
</example>

<example>
SITUATION: test_login fails; collect_diag `[authlog]` shows "Authentication refused: bad ownership or modes for directory /home/www/.ssh" and `[perms]` shows `~/.ssh` is 775.
ACTIONS (reasoning): the rejection is a perms problem on ~/.ssh → run `apply_fix.sh nigeria ssh_dir_perms` → re-run `test_login.sh nigeria` (now exits 0). Do NOT also run unrelated fixes.
OUTPUT: "证书登录起初失败,sshd 日志指出 ~/.ssh 权限不对(775),已 chmod 700,复测通过。"
</example>

<example label="re-entry — already complete">
SITUATION: User re-runs dDLN. `list_profiles.sh` prints `nigeria<TAB>152.32.142.146<TAB>opt<TAB>42146`. User picks `1. nigeria`.
ACTIONS: Skip the param questions (read host/user/port from the menu line) → Phase 0.5 probe `test_login.sh nigeria` (exits 0) → `close_check.sh nigeria` (ends ✅). No root connection, no provision, no harden, no disconnect.
OUTPUT: "Result: success(re-entry:已完成)— nigeria 在 152.32.142.146:42146 证书登录可用且收尾审计全过,无需改动。私钥 ~/.ssh/nigeria/opt_ed25519、密码 ~/.ssh/nigeria/opt.sudo。NOPASSWD sudo 仍待最终模块撤销。"
</example>

<example label="BAD — do not do this">
ANTI-PATTERN: Running `bash .../connect.sh ...` via the Bash tool (it needs the interactive root password); OR asking "把 root 密码/运营用户密码发我"; OR, on a login failure, running every `apply_fix` blindly instead of reading `collect_diag` and picking the targeted one; OR re-running `harden.sh` over the cert path on an already-hardened box (no reload-surviving rollback lifeline → lockout risk); OR re-asking host/user/port for a profile the Phase 0 menu already lists.
</example>
</examples>

<output_format>
Module: account (ops user + cert login + SSH hardening)
Result: success | login-unrecoverable | hardening-rolled-back | close-check-failed
Profile: <profile>
Key / password: <~/.ssh/<profile>/<user>_ed25519 and <user>.sudo, or "n/a">
Failed/Notable: <FAILED / rollback / ❌ line(s) verbatim, or "n/a">
Reminder: <"NOPASSWD sudo pending revoke in final step" on success, else what blocks>
Next: <"可进入下一模块" only on success, else the user action required>
</output_format>

<success_criteria>
The account module is complete when `close_check.sh` ends `收尾检查全部通过 ✅` (which implies provisioning, certificate login, and hardening all succeeded), and the root channel was closed via `disconnect.sh`.
On re-entry to an already-finished box (Phase 0.5: cert probe passes and `close_check.sh` ends `✅`), the module is likewise complete with NO root connection opened and nothing to `disconnect` — report success and stop.
Report and STOP. Do not start any later deploy module in the same turn.
Any unrecoverable login failure, hardening rollback, or `❌` means NOT complete — report the evidence/line(s) verbatim and stop.
</success_criteria>

<final_reminders>
P0 — NEVER run `connect.sh` via the Bash tool, and NEVER ask for/accept/log any server password (root or ops). The root password is typed into `connect.sh` in the user's terminal; the ops password lives only in `~/.ssh/<profile>/<user>.sudo`, which you never read aloud.
P0 — DO run the other stage scripts via Bash (`provision_user.sh`/`test_login.sh`/`collect_diag.sh`/`apply_fix.sh`/`harden.sh`/`close_check.sh`/`disconnect.sh`); they are non-interactive and reuse the socket. This is the skill actually driving the deploy.
P0 — On test_login failure, REASON over `collect_diag` evidence (authlog first) and apply only the targeted fix; never blind-loop every fix. Cap at ~3 rounds, then escalate with evidence.
P0 — Report failures visibly: quote FAILED steps, the rollback line, and `❌` audit lines verbatim. Never paper a failure over as success.
P1 — Wait for the user's `建立 root 连接... done` before running any Bash stage script (they need the socket).
P1 — On success, ALWAYS surface that NOPASSWD sudo remains and must be revoked by the final deploy module.
P1 — Re-entrancy: offer the Phase 0 menu of saved profiles and REUSE the chosen one's host/user/port — never re-ask them. Verify over cert (`test_login`/`close_check`, no root master); MUTATE (`provision`/`harden`) only over the root master. NEVER run hardening over the cert path — it has no reload-surviving rollback lifeline.
P2 — Stage scripts are idempotent and safe to re-run (re-run after opening a cloud security-group port, fixing a perms issue, etc.); `provision_user.sh` reuses an existing key/password rather than regenerating, so re-running it on an existing profile is safe and even repairs `.ssh` perms/owner.
</final_reminders>
