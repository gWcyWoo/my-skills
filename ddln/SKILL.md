---
name: ddln
description: Prepare a server through the bundled account, system, nginx/TLS, and rootless Docker modules.
---

# dDLN

通过既有脚本准备服务器：account → system → edge → docker。只执行用户要求的模块；已授权整套准备时，在必要检查通过后继续，不在每个模块结束时机械停下。

## 目标与安全边界

- 用 `lib/list_profiles.sh` 列出已有 profile；复用用户已指定的目标和 host/user/port。目标不明确时才询问；新 profile 收集缺失的名称、host、运营用户名和 SSH port，可合并提问。
- 凭据目录为 `~/.ssh/<profile>/`；`dpt.conf` 存服务器事实，本地路径由目录名推导。密码和私钥内容不进入对话、日志或模型上下文，只使用路径与脚本。
- `account/script/connect.sh` 必须由用户在自己的终端执行并输入 root 密码；模型不代输。确认连接建立后才运行依赖该 socket 的步骤。
- 验证已有服务器走运营用户证书。provision/harden 依赖 root ControlMaster 作为回滚通道；root 已锁且无安全回滚通道时，不强行通过证书连接重新加固。
- 保留脚本的配置校验、回滚、证书复验和模块 close check。新的 SSH/防火墙暴露范围、关闭服务、重启或特权变更超出已有授权时，先展示具体目标和影响再确认。
- 长操作使用既有 detached 脚本并读取状态；无需在对话中复述每条成功日志。需要用户执行的命令必须放到回复中，秘密用占位符。
- 交付已完成模块、失败证据与待处理项。说明 NOPASSWD 的实际状态；不能把尚未实现的最终撤销模块当作已执行。

## 按需读取

- 账户准备/证书登录/SSH 加固：[account.md](references/account.md)。保留有证据的定点修复及最多三轮诊断，不盲试所有 fix。
- swap、升级、系统安全与防火墙：[system.md](references/system.md)。保留升级脱离控制连接、重启后核验目标内核、dead-man 回滚和服务关闭授权。
- nginx/WAF/TLS 或 `--cert <app>`：[edge.md](references/edge.md)。`--cert` 只执行该应用证书子动作，不重跑其他模块。
- rootless Docker 环境：[docker.md](references/docker.md)。用户态命令使用 `rexec_user`，不以 sudo 代替。
- `--nopasswd [on|off]`：对已选 profile 运行 `account/script/nopasswd_cmd.sh`，把打印的命令交给用户执行，不处理密码，不自动切换权限。

脚本路径均相对于本技能目录。选中模块运行其 preflight；依赖缺失时报告具体文件或前置模块，不伪造完成结果。
