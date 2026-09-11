---
name: ddc
description: Audit a dDLN/dDP server read-only through an existing SSH profile and save a local report.
---

# dDC

通过已有 dDLN/dDP SSH profile 对服务器做完整只读巡检，产出本地审计日志。

- 服务器只读：不创建或修改远端文件，不安装、不修复、不改服务或容器状态。只读检查需 sudo 而权限不足时如实记失败。
- 仅运营用户证书登录，不用 root 或密码。复用 `~/.ssh/<profile>/`，不创建 profile、不读取密钥内容。
- 用户已指定 profile 时直接验证并复用；否则运行 `bash ~/.agents/skills/ddc/lib/list_profiles.sh`，让用户明确目标。没有 profile 时报告需先准备服务器。
- 在目标项目根运行 `bash ~/.agents/skills/ddc/dDC.sh <profile>`。全套 SSH、用户、系统、Docker、PHP、nginx、可用性检查是本技能的审计范围，不裁剪成抽查。
- 脚本将逐项证据写到本地 `./audit/check/<profile>_<date>.log`；本地日志不受远端只读边界限制。
- 交付通过/失败计数、所有失败项及原因、日志路径。报告修复归属，未经修复授权不转入 dDP/dDLN 修改服务器。
