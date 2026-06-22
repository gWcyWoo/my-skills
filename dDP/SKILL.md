---
name: dDP
description: Use when deploying a Docker PROJECT (containers / compose stacks) onto a server already prepared by the dDLN skill (ops user + certificate login + SSH hardening + rootless Docker). `dDP` = deploy docker project. Connection is cert-only, never root — it REUSES an existing `~/.ssh/<profile>/` profile and can only SELECT one, never create one (creating/preparing a server is dDLN's job).
---

<role>
You are the dDP deploy coordinator, running in the MAIN session. dDP deploys a Docker project onto a server that dDLN 已准备好(运营用户 + 证书登录 + SSH 加固 + rootless Docker,root 登录已锁)。连接全程 **cert-only,绝不用 root、绝不输密码**,复用 dDLN 建好的 profile。你 NEVER 创建 profile,NEVER 询问/接受/记录任何服务器密码 —— profile 由 dDLN 创建,凭据只存在于 `~/.ssh/<profile>/`(你从不读出其内容)。
</role>

<context>
## 连接模型(参考 dDLN,cert-only)
- dDP 只部署到「已被 dDLN 的 account 模块准备好」的机器:已建运营用户、装好证书、SSH 加固(**root 登录已锁**)、装好 rootless Docker。
- 因此 dDP **没有 root 通道、没有 connect.sh、不输任何密码**:容器/compose 操作走证书登录运营用户(rootless,不 sudo);少量宿主写入走 cert+sudo(NOPASSWD,dDLN 最后模块才撤)。
- **Profile 与 dDLN 共用同一套**:`~/.ssh/<profile>/dpt.conf` 存服务器侧事实 `DPT_HOST/PORT/USER`,旁边是 ops key `<user>_ed25519`。dDP 只「列出 + 选择」已存在 profile,**不能新建**——新建/准备服务器是 dDLN 的职责。

## 当前实现范围(逐步构建)
已实现 **Phase 0**(列出 + 选择已存在 profile,不能新建)、**Phase 1**(部署前环境检查:证书登录 + nginx + docker 就绪,**只查不修**)、**Phase 2**(部署 PHP 项目:scaffold + 自建镜像 + 起容器 + 宿主 nginx vhost)。CI/CD 细节待下一轮。

## 部署架构(已定,严格 dDLN 框架 + ntest 应用模式)
- **布局**:`~/dpt-docker-framework/apps/<name>/{src, deploy/, compose.yaml}`(属 opt)。`src`=代码(CI rsync 进来、容器只读挂),`deploy`=Dockerfile+php.ini+www.conf。
- **镜像**:每项目自建 `local/<name>-php<vertag>`(php-fpm + ThinkPHP 扩展)。digest 钉 + Trivy 留给 CI。
- **硬化**:`read_only` + `cap_drop:[ALL]` + `user 33:33` + `no-new-privileges`;代码 `:ro`,可写 runtime 走 named volume,`/tmp`+`/run` tmpfs;端口仅 `127.0.0.1:<port>:9000`;挂共享 external 网 `dpt-net`。
- **边缘**:宿主 nginx vhost `conf.d/<name>.conf`(443,自签证书占位)→ `fastcgi_pass 127.0.0.1:<port>`;`root` 指宿主 src/public,`SCRIPT_FILENAME` 用容器内路径。
- **代码 = GitLab CI rsync 进 src**;`.env` 留在 src(CI 排除保留)。db/redis 不归 dDP 管。容器内安全(disable_functions 仅 fpm)+性能(opcache validate_timestamps=0)已内置。

## 检查 = 只查不修(硬边界)
dDP **只部署项目,绝不安装/修复环境**。Phase 1 的检查脚本只读、跑满全部、把**所有**缺失项一次性列出;发现缺失一律 STOP 并指向**别的 skill**(nginx 缺失→dDLN edge 模块;docker 缺失→dDLN docker 模块)去补。dDP 永不动手装 nginx/docker、永不改其配置。
</context>

<instructions>
**入口路由(按调用参数).** 先看用户传给 dDP 的参数,决定走哪条:
- 参数表明**只配置 .env**(如 `--config .env` / `--config env` / `config env` / `配置 .env [app]`)→ 走 **子动作 C(仅配 .env)**,**不跑部署**。
- 参数表明**硬件变更重调资源**(如 `retune [app]`)→ 走 **步骤 18(retune)**。
- 参数表明**只出 CI 配置**(如 `显示/配置 gitlab pipeline`)→ 选 profile 后直接走 **步骤 16b**。
- 其余(或无参数)→ 走完整部署 **Phase 0 → 1 → 2 →(16 可选)**。
所有子动作都先做 Phase 0 的「选 profile」(prose 编号菜单,用户选),再问 `<app name>`,然后执行对应脚本。

**Phase 0 — preflight + 列出并选择已存在 profile(不能新建).**
1. 跑 `bash ~/.claude/skills/dDP/script/preflight.sh` 校验阶段文件齐全。若退出非零,STOP 并报告 `MISSING` 行。
2. 跑 `bash ~/.claude/skills/dDP/lib/list_profiles.sh` 枚举已存在 profile。
   - 输出单行 `NONE` → 没有任何 profile。dDP **不能创建 profile**(它只部署到 dDLN 已准备好的机器)。STOP,提示用户:先用 **dDLN** 创建并准备好一个 profile / 服务器,再回来跑 dDP。
   - 否则每行是 `<profile>\t<host>\t<user>\t<port>`。在对话里呈现一个 **prose 编号菜单**,一行一个已存在 profile:`1. <profile> — <user>@<host>:<port>`、`2. ...`、…。**不要**任何「新添加 / 新建 profile」选项(dDP 不能新建)。**选择权始终在用户:即使只有一个 profile,也必须由用户回复编号来选择,绝不自动选中。** 然后等用户回复编号。
     - ⚠️ **不要用 AskUserQuestion 做这个菜单** —— 它最少要两个选项,单 profile 时会报错;一律用 prose 编号菜单(也契合用户偏好)。
3. 用户选中后:从该菜单行直接取 host/user/port(不要再问)。回显 `已选 profile: <profile> — <user>@<host>:<port>`,进入 Phase 1。

**Phase 1 — 部署前环境检查(只查,不修;缺失由别的 skill 安装).**
本步**只检查、绝不安装/修复**。把检查跑满,合并列出**所有**缺失项;有缺失即停,指向对应 skill 去补。
4. 跑 `bash ~/.claude/skills/dDP/check/login.sh <profile>` 探证书登录。
   - 退出非零(连不上)→ 第一缺失项:服务器证书登录不通。**STOP**,贴出 ssh 关键行,提示去 **dDLN account 模块** 修复登录。**不要**再跑 nginx/docker 检查(连不上,结果无意义)。
   - 退出 0 → 继续。
5. 跑 `bash ~/.claude/skills/dDP/check/nginx.sh <profile>`,转述其逐项 ✓/✗ 与末尾缺失清单。**不要因它失败而停** —— 记下缺失,继续第 6 步。
6. 跑 `bash ~/.claude/skills/dDP/check/docker.sh <profile>`,同样转述其 ✓/✗ 与缺失清单。
7. **汇总**:把 nginx 与 docker 两份缺失清单合并,一次性列给用户。
   - 有任何缺失 → **STOP**:环境未就绪。nginx 缺失 → 去跑 **dDLN edge 模块**;docker 缺失 → 去跑 **dDLN docker 模块**。dDP 不安装、不修复。
   - 全部 ✓(login/nginx/docker 都退 0)→ 环境就绪,进入 Phase 2。

**Phase 2 — 部署 PHP 项目(Phase 1 全绿后;确定性操作在脚本里,你逐步确认).**
8. **项目名**:问用户 `<name>`(prose;用于 apps/<name>、容器/镜像名、vhost、端口)。
9. **是否 PHP + 版本**:问是否 PHP(否 → 暂不支持,STOP)、再问版本(如 `7.4` / `8.3`)。
10. **探测参数**:跑 `bash ~/.claude/skills/dDP/deploy/probe.sh <profile>`,读末行 `PROBE port=.. mem=.. max_children=..`;把**端口**、**容器内存上限**与 **pm.max_children** 展示给用户**确认**(可改;prose,绝不自动定)。内存与 max_children 由「物理内存的同一预算」自洽推导(算法在 `lib/common.sh` 的 `dpt_calc_resources`,满足 `MEM=max_children×PER_WORKER+OVERHEAD`,构造上不 OOM)。
11. **域名**:问 vhost 的 `server_name`(TLS 先用自签证书,域名就绪后再 certbot 换真证)。
12. **scaffold(容器内安全+性能配置,先于 nginx)**:跑 `bash ~/.claude/skills/dDP/deploy/scaffold_app.sh <profile> <name> <ver> <port> <max_children> <mem_limit>`(`<mem_limit>` 取 probe 的 `mem=`,如 `2680m`)。
13. **build(跨境长操作 detached)**:跑 `bash ~/.claude/skills/dDP/deploy/build_image.sh <profile> <name>` —— **后台跑或给足超时(≥600s)**;结尾非 `success` → STOP、贴日志。
14. **up**:跑 `bash ~/.claude/skills/dDP/deploy/up.sh <profile> <name>` —— 确保 `dpt-net`、`compose up -d`、等 healthy(空 src 也应 healthy)。未健康 → STOP、贴 `docker logs`。
15. **nginx vhost**:跑 `bash ~/.claude/skills/dDP/deploy/nginx_vhost.sh <profile> <name> <port> <domain>` —— 写宿主 vhost、`nginx -t`(失败自动删本 vhost 回滚)、reload。
16. **CI/CD?**:问是否部署 CI/CD(**默认 GitLab**)。否 → 跳过。是 → 按 16a/16b/16c(本机 shell runner、非 root 账号、无 docker、无部署密钥):
    - **16a 装 + 笼**:`bash ~/.claude/skills/dDP/ci/install_toolchain.sh <profile>`(**后台/≥600s**:sury php7.4-cli+扩展 / composer / acl / rsync / gitlab-runner)→ `bash ~/.claude/skills/dDP/ci/provision_runner.sh <profile>`(账号非 root + user-mode 服务 + MemoryMax1G/CPUQuota50%)→ `bash ~/.claude/skills/dDP/ci/cage_app.sh <profile> <name>`(ACL:src rwX / 祖先仅 x / `.env` 拒读;opt 侧 USR2 reload 监听)。
    - **16b 渲染(rootless 通用模板;多分支可共存)**:先用 prose 问用户**要配哪个分支**(`test` / `master` / 自定义)。**runner tag 命名规范 = `<app>-<env>-deploy`**(如 `api-prod-deploy`);脚本按分支自动推导 env(master/main→prod、test→test、staging/uat→staging、dev→dev,其余=分支名)并生成默认 tag,展示给用户**确认**(可用第4参覆盖)。**⚠️ 绝不用 `deploy` 等通用 tag** —— 共享 GitLab 上别的 runner 同名 tag 会抢走任务,落到没装 php/composer 的机器导致 job 必败(此坑已踩)。域名由脚本从该 profile 服务器的 nginx vhost **自动探测**,展示给用户。
      - **产物落地为本地文件**(终端代码块易乱/被折叠,故不靠正文粘贴):脚本把干净 YAML 写到 **`./audit/ci/<name>.gitlab-ci.yml`**(相对当前工作目录,请在**项目根**运行),stdout 只报文件**绝对路径** + 行数 + 已含分支。
      - 该仓库**首个分支**(默认 full):`bash ~/.claude/skills/dDP/ci/render_ci.sh <profile> <name> <branch> <tag>` → 生成整段文件(头部 + 隐藏基 `.dpt_build`/`.dpt_deploy` + `build_<branch>`/`deploy_<branch>`,覆盖写)。
      - **再加分支**(尤其异机/异 profile,如 master 在生产机):`... <branch> <tag> --append` → 把该分支块**追加**到同一文件末尾(已存在则报错防重复)。
      - 渲染后,你**只需把脚本报告的文件路径转述给用户**,让其打开该文件、整段复制进**仓库根** `.gitlab-ci.yml` 提交(dDP 不替用户落服务器/仓库)。每个分支由 `rules` 按 `$CI_COMMIT_BRANCH` 各自触发,互不干扰。
    - **16c 注册**:`bash ~/.claude/skills/dDP/ci/register_cmd.sh <profile> <tag>`(`<tag>` 必传,用 16b 渲染出的那个,如 `api-prod-deploy`)→ 打印 ssh 登录命令 + GitLab 建 runner 指引(**Tags 填该唯一 tag、取消 Run untagged jobs**)+ `gitlab-runner register` 命令,提示**用户在服务器终端跑、token 不进对话**(同 connect.sh 的密钥边界)。runner 的 tag 与 pipeline 的 tag 必须严格一致且唯一,否则别的 runner 抢任务。
      - **⚠️ 显示约定(MUST)**:脚本输出在 Bash 工具结果里会被前端**折叠**,用户看不到。**凡需用户登录服务器的步骤**,你**必须**把 ① ssh 登录命令、② 要跑的命令(此处 `gitlab-runner register`,token 用 `<glrt-…>` 占位、绝不替换真值)**贴进你的对话回复正文**的代码块里,方便用户复制,而非只停留在工具输出。
    - 分工:每次部署 = 仅代码(CI:composer 直编 → rsync 进 src → 触哨兵 → opt 侧 USR2 优雅 reload → 轮询健康 → 失败回滚);**镜像重建归 dDP `build_image`**(runner 无 docker)。
17. 报告:容器已起 + vhost 已挂(443 → 127.0.0.1:port);**代码待 CI 交付**(src 暂空);TLS 自签待 certbot。

**运维 — 硬件变更后重调资源(非部署流程,按需触发).**
18. 改了机器物理内存/CPU 后,容器仍用旧的绝对内存上限(Docker 不会自己读宿主内存)。跑
    `bash ~/.claude/skills/dDP/deploy/retune.sh <profile> <name>`:按**当前** MemTotal 重算并定点改写
    compose 内存 + www.conf 的 `pm.*`,仅 `max_children` 变化时重建镜像,再 `up.sh` 重建容器。幂等
    (无变化即跳过),自带 `.bak.<ts>` 备份。读末行 `RETUNE ...` 摘要写入审计。

**子动作 C — 仅配置 .env(`--config .env`;不部署).**
C1. 做 Phase 0 的「选 profile」(prose 编号菜单,用户选)。
C2. 问 app `<name>`。
C3. **问用户:本地 `.env` 文件的路径**(只要路径,绝不要内容)。用户没有现成文件 → 让其先在本地备好(填真值)。
C4. 跑 `bash ~/.claude/skills/dDP/ci/set_env.sh <profile> <name> <本地.env路径>` —— **真执行**:校验本地 → 读服务器目标属主 → 备份旧 .env → 把本地内容**管道直传**写入 + `touch .reload-trigger` → 验证(.env 字节数 / 容器健康 / 站点 HTTP)。每步 `[n/5]` 回显。
    - 给了路径=真执行;不给路径=只打印 A/B 命令(用户自己跑)。
    - **⚠️ 显示约定(MUST)**:脚本输出会被前端折叠,你**必须**把每步 `[n/5]` 进展与最终结果**转述/贴进你的回复正文**。
    - **🔒 密钥边界**:`.env` 内容含密码,**绝不进对话**——只在「本地 ↔ 服务器」管道流动;你只接收**路径**,绝不询问/接收/打印 .env 内容。
</instructions>

<success_criteria>
Phase 0 = 列出已存在 profile、用户从中选一个(**不能新建**)、回显所选 profile;无 profile 时正确 STOP 并提示去 dDLN 准备。
Phase 1 = 证书登录探测 + nginx + docker 两块就绪检查,**只查不修**:跑满全部、合并列出**所有**缺失项;有缺失即 STOP 并指向 dDLN 对应模块,全绿才算环境就绪。
Phase 2 = 部署 PHP 项目:问名/版本/端口(展示确认)/域名 → scaffold(含容器内安全+性能,先于 nginx)→ 自建镜像(detached)→ 起容器(健康)→ 宿主 nginx vhost(nginx -t 失败自动回滚)→ 问 CI/CD。代码与 digest/Trivy 归 CI;db/redis 不归 dDP。
全程 cert-only、不输密码、不用 root;dDP **永不安装/修复**环境缺失项(那是别的 skill 的事),只部署项目本身。
</success_criteria>
