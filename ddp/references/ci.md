# CI/CD

仅在用户请求 CI/CD 时执行（默认 GitLab），按 16a/16b/16c(本机 shell runner、非 root 账号、无 docker、无部署密钥):
    - **16a 装 + 笼**:`bash ~/.agents/skills/ddp/ci/install_toolchain.sh <profile>`(**后台执行并读取状态**:sury php7.4-cli+扩展 / composer / acl / rsync / gitlab-runner)→ `bash ~/.agents/skills/ddp/ci/provision_runner.sh <profile>`(账号非 root + user-mode 服务 + MemoryMax1G/CPUQuota50%)→ `bash ~/.agents/skills/ddp/ci/cage_app.sh <profile> <name>`(ACL:src rwX / 祖先仅 x / `.env` 拒读;opt 侧 USR2 reload 监听)。
    - **16b 渲染(rootless 通用模板;多分支可共存)**:先用 prose 问用户**要配哪个分支**(`test` / `master` / 自定义)。**runner tag 命名规范 = `<app>-<env>-deploy`**(如 `api-prod-deploy`);脚本按分支自动推导 env(master/main→prod、test→test、staging/uat→staging、dev→dev,其余=分支名)并生成默认 tag,展示给用户**确认**(可用第4参覆盖)。**⚠️ 绝不用 `deploy` 等通用 tag** —— 共享 GitLab 上别的 runner 同名 tag 会抢走任务,落到没装 php/composer 的机器导致 job 必败(此坑已踩)。域名由脚本从该 profile 服务器的 nginx vhost **自动探测**,展示给用户。
      - **产物落地为本地文件**(终端代码块易乱/被折叠,故不靠正文粘贴):脚本把干净 YAML 写到 **`./audit/ci/<name>.gitlab-ci.yml`**(相对当前工作目录,请在**项目根**运行),stdout 只报文件**绝对路径** + 行数 + 已含分支。
      - 该仓库**首个分支**(默认 full):`bash ~/.agents/skills/ddp/ci/render_ci.sh <profile> <name> <branch> <tag>` → 生成整段文件(头部 + 隐藏基 `.dpt_build`/`.dpt_deploy` + `build_<branch>`/`deploy_<branch>`,覆盖写)。
      - **再加分支**(尤其异机/异 profile,如 master 在生产机):`... <branch> <tag> --append` → 把该分支块**追加**到同一文件末尾(已存在则报错防重复)。
      - 渲染后,你**只需把脚本报告的文件路径转述给用户**,让其打开该文件、整段复制进**仓库根** `.gitlab-ci.yml` 提交(dDP 不替用户落服务器/仓库)。每个分支由 `rules` 按 `$CI_COMMIT_BRANCH` 各自触发,互不干扰。
    - **16c 注册**:`bash ~/.agents/skills/ddp/ci/register_cmd.sh <profile> <tag>`(`<tag>` 必传,用 16b 渲染出的那个,如 `api-prod-deploy`)→ 打印 ssh 登录命令 + GitLab 建 runner 指引(**Tags 填该唯一 tag、取消 Run untagged jobs**)+ `gitlab-runner register` 命令,提示**用户在服务器终端跑、token 不进对话**(同 connect.sh 的密钥边界)。runner 的 tag 与 pipeline 的 tag 必须严格一致且唯一,否则别的 runner 抢任务。
      - **⚠️ 显示约定(MUST)**:脚本输出在终端命令工具结果里会被前端**折叠**,用户看不到。**凡需用户登录服务器的步骤**,你**必须**把 ① ssh 登录命令、② 要跑的命令(此处 `gitlab-runner register`,token 用 `<glrt-…>` 占位、绝不替换真值)**贴进你的对话回复正文**的代码块里,方便用户复制,而非只停留在工具输出。
    - 分工:每次部署 = 仅代码(CI:composer 直编 → rsync 进 src → 触哨兵 → opt 侧 USR2 优雅 reload → 轮询健康 → 失败回滚);**镜像重建归 dDP `build_image`**(runner 无 docker)。
