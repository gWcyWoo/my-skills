---
name: ddc
description: Use when AUDITING (read-only) a Docker-project server prepared by dDLN and deployed by dDP. `dDC` = deploy docker check. Runs the full security/performance/availability check suite over ssh/user/system/log/firewall/docker/container/php/nginx/availability, prints each item as `检查项(检查目的)-----success|fail`(fail 附原因), and records everything to `./audit/check/<profile>_<date>.log`. STRICTLY READ-ONLY — never modifies/creates/deletes anything on the audited server (no exemptions). Connection is cert-only, never root; it REUSES an existing `~/.ssh/<profile>/` profile and can only SELECT one, never create one.
---

<role>
You are the dDC check coordinator, running in the MAIN session. dDC 对一台「dDLN 已准备 + dDP 已部署」的服务器做**只读**安全/性能/可用性巡检,逐项打印并落审计日志。连接全程 **cert-only,绝不用 root、绝不输密码**,复用已有 profile。你 NEVER 创建 profile、NEVER 修改服务器任何状态。
</role>

<context>
## 硬边界(无豁免)
- dDC **对被审服务器只读**:仅发送读取/查询/校验/GET 类命令(cat/grep/test/awk/`sshd -T`/`nginx -t`/`sysctl -n`/`docker inspect|ps|info`/只读 `docker exec` grep/cat/`curl` GET)。
- **绝不**:sudo 写、远端 `tee`/`sed -i`/`cp`/`mkdir`/`rm`、`docker run`/`build`/`up`/`create`/`rm`、改 systemd 状态、写任何远端文件。发现问题只**报告**,不修复(修复是 dDP/dDLN 的事)。
- **需求冲突的显式裁决**:「严禁创建」与「写审计日志」字面矛盾。裁决:只读边界约束的是**被审服务器**;审计日志是**本地**规定产物(`./audit/check/<profile>_<date>.log`),由 dDC.sh 在你的本机创建,**不**属于对目标的修改。这是唯一自洽解,已固化在脚本里。

## 连接模型(复用 dDLN/dDP profile,cert-only)
- `~/.ssh/<profile>/dpt.conf` 存 `DPT_HOST/PORT/USER`,旁边是 ops key `<user>_ed25519`。dDC 只「列出 + 选择」已存在 profile,**不能新建**(新建/准备服务器是 dDLN 的职责)。
- sudo 仅用于**读取** root 文件(依赖 dDLN 暂留的 NOPASSWD;若已撤,sudo 类只读检查会失败并如实报 fail)。

## 检查覆盖(本次审计的产品化)
SSH、用户/提权、防火墙/网络、系统/内核/日志/更新、Docker 守护(rootless)、容器(每 app:安全 + 资源 + 内存/max_children 自洽)、容器内 PHP(每 app)、nginx 边缘、可用性(每 app 端到端 GET)。
</context>

<instructions>
**Phase 0 — 列出并选择已存在 profile(不能新建).**
1. 跑 `bash ~/.agents/skills/ddc/lib/list_profiles.sh` 枚举已存在 profile。
   - 输出单行 `NONE` → 没有任何 profile。dDC 不能创建。STOP,提示先用 **dDLN** 准备服务器。
   - 否则每行是 `<profile>\t<host>\t<user>\t<port>`。在对话里呈现一个 **prose 编号菜单**(一行一个:`1. <profile> — <user>@<host>:<port>`)。**选择权始终在用户:即使只有一个 profile 也必须由用户回复编号选定,绝不自动选中。** 不要调用 `request_user_input` 或其他选择题工具(单 profile 时不适用)。等用户回复编号。
2. 用户选中后回显 `已选 profile: <profile> — <user>@<host>:<port>`,进入 Phase 1。

**Phase 1 — 跑只读检查并落审计日志.**
3. **在项目根目录下**(使 `./audit/` 指向该项目)跑:`bash ~/.agents/skills/ddc/dDC.sh <profile>`。
   - 脚本会:复用 cert 连接 → 逐项检查 → 每项打印 `检查项(检查目的)-----success|fail`(fail 缩进附原因)→ 整体 `tee` 进 `./audit/check/<profile>_<date>.log` → 末尾打印汇总(通过/失败计数)。
   - 全程只读;无 app 时自动跳过容器/PHP/可用性段。
4. 转述结果:先报汇总(通过 X / 失败 Y),再逐条列出**所有 fail 项及其原因**;指出日志路径。**dDC 不修复**——失败项指向 dDP(部署/容器/资源,如 `retune`)或 dDLN(系统/边缘加固)去处理。
</instructions>

<success_criteria>
Phase 0 = 列出已存在 profile、用户从中选一个(不能新建)、回显所选;无 profile 时正确 STOP 指向 dDLN。
Phase 1 = 跑满全部检查项,每项以 `检查项(检查目的)-----success|fail` 打印且 fail 附原因,整体记入 `./audit/check/<profile>_<date>.log`;末尾给出通过/失败汇总。
全程 cert-only、不输密码、不用 root;**对被审服务器零修改/创建/删除**(无豁免),唯一写动作为本地审计日志。
</success_criteria>
