# dDP 部署与配置说明(每条 + 为什么)

dDP = deploy docker project。把 Docker 项目部署到 **dDLN 已准备好**的机器(运营用户 + 证书登录 + SSH 加固 + rootless Docker,root 登录已锁)。本文逐条列出 dDP 怎么部署/配置,并说明每条的理由。

---

## 0. 总体模型(根决定,影响一切)

- **cert-only,绝不用 root 通道。** `rexec`=证书登录运营用户 + sudo(宿主侧);`rexec_user`=证书 + rootless(容器侧,不 sudo)。
  *为什么*:目标机 root 已被 dDLN 锁死,没有 root 通道可用;且最小权限——部署不该开 root 引导连接。
- **复用 dDLN 的 profile。** 读同一套 `~/.ssh/<profile>/dpt.conf`(host/port/user)+ ops key。
  *为什么*:连接事实由 dDLN 建立,dDP 不重复造、也无权造(不能新建 profile)。
- **架构 = 严格 dDLN 硬化 + ntest 应用布局。** 安全照 dDLN(宿主 nginx 边缘 + 127.0.0.1 硬化容器),应用组织照 ntest(`apps/<name>/{src,deploy}` + 自建镜像 + 代码经 CI rsync)。
  *为什么*:ntest 是低安全测试环境不可作安全参照,但其应用/CI 模式实战验证过;两者取长。

## 1. 目录布局 `~/dpt-docker-framework/apps/<name>/`

`src/`(代码,CI rsync 进来,容器**只读**挂)· `deploy/{Dockerfile,php.ini,www.conf}`(镜像构建上下文)· `compose.yaml` · `src/runtime/`(挂载点占位)。
*为什么放 `~/dpt-docker-framework/`*:dDLN 已把框架建在这、属 opt;dDP 全程 cert-as-opt 不用 root 就能写。用 `/srv/...` 得 root 先 mkdir+chown,超出 dDP 权限边界。

## 2. Phase 0 — 列出并选择 profile(不能新建)

prose 编号菜单,用户回编号选;**即使只有一个也由用户选,绝不自动选中**。
*为什么不能新建*:建/备服务器是 dDLN 的职责;dDP 只往已就绪的机器放项目。
*为什么 prose 不用 `request_user_input` 或其他选择题工具*:单 profile 时不适用;且偏好 prose 对话。

## 3. Phase 1 — 环境检查(只查不修)

`login`(证书)→ `nginx`(装/配/安全 21 项)→ `docker`(装/配/安全 13 项);跑满全部、合并列出**所有**缺失,有缺失即停并指向 dDLN(nginx→edge,docker→docker 模块)。
*为什么只查不修*:dDP 只部署项目,环境缺啥由对应 skill 装(职责单一);一次列全缺失,免得修一个发现下一个。

## 4. Phase 2 — 部署

### 4.1 镜像 `deploy/Dockerfile`
- `FROM php:<ver>-fpm-<suite>`,7.x→bullseye / 8.x→bookworm。
  *为什么*:php 7.4 官方镜像只到 bullseye,8.x 才有 bookworm。
- 扩展 `pdo_mysql mysqli mbstring zip bcmath intl gd(freetype+jpeg) opcache` + `redis`(pecl)。
  *为什么*:ThinkPHP 实际依赖(DB/缓存/多字节/图形/国际化);基础镜像不带,故自建。
- `COPY composer` · `COPY php.ini→conf.d/99-dpt.ini` · `COPY www.conf`。
  *为什么 99- 前缀*:让我们的 ini 最后加载、覆盖默认。
- `RUN mkdir -p .../runtime && chown 33:33 .../runtime`。
  *为什么*:配 `read_only`+命名卷——命名卷首挂时从镜像层 **copy-up 继承属主**,build 期(root)chown 成 33:33,运行期容器内 www-data 才写得动 runtime,且运行期零新增权限(契合 `no-new-privileges`)。
- digest 钉 + Trivy 扫**留给 CI**(持续 build 归 CI)。

### 4.2 `php.ini`(安全 + 性能;全局 conf.d,作用于 fpm 与 cli)
安全:
- `expose_php=Off` —— 不泄露 PHP 版本。
- `display_errors=Off` + `display_startup_errors=Off` + `log_errors=On`(→`/proc/self/fd/2`)—— 错误不回客户端,只进容器日志(journald)。
- `cgi.fix_pathinfo=0` —— 经典 php-fpm 防护:杜绝把 `x.jpg/foo.php` 误当 PHP 执行。
- `session.cookie_httponly/secure/samesite=Lax` + `use_strict_mode=On` —— 防 XSS 偷 cookie、强制 HTTPS、防 CSRF、防会话固定。

性能:
- `opcache.enable=1` + `memory_consumption=128` / `interned_strings=16` / `max_accelerated_files=20000` —— 字节码缓存;ThinkPHP 文件多,加速明显。
- **`opcache.validate_timestamps=0`** —— 不每请求 stat 文件,性能最优。*为什么敢设 0*:每次 CI 部署都 USR2 reload/重建容器 → opcache 全新;一次部署内代码不变,stat 纯浪费。
- `enable_cli=0` —— CLI(composer)不需要 opcache。
- `realpath_cache 4096k/600s` —— 减少路径解析 syscall。
- `memory_limit=256M` · `max_execution_time=30` · `post/upload=20M`(与 nginx `client_max_body_size` 对齐,避免不一致截断)。
- **disable_functions 不在这** —— 放 www.conf(仅 fpm)。*为什么*:若放全局 ini,CI 里跑 composer 的 **CLI php** 会被禁 `proc_open` 而失败。

### 4.3 `www.conf`(php-fpm pool;仅作用于 fpm worker)
- **不设 user/group** —— 容器已以 33:33 非 root 跑,master 已非 root,设了反而告警。
- `listen 0.0.0.0:9000`(容器内)· `pm=dynamic` + `max_children/start/spare`(由内存探测推导)· `max_requests=500`(回收 worker、防泄漏累积)。
- `request_terminate_timeout=60s` —— 杀卡死请求。
- `security.limit_extensions=.php` —— 只执行 .php,防执行伪装的上传文件。
- `clear_env=yes` —— worker 不继承容器进程环境变量。*为什么*:配置走 `.env` 文件,进程环境无需透传,更隔离。
- **`php_admin_value[disable_functions]=exec,passthru,shell_exec,system,popen,proc_open,show_source`** —— 禁 RCE 高危函数;用 `php_admin_value`(不可被 ini_set 覆盖)且**仅 fpm**(不卡 CLI composer)。
- `ping.path=/ping` + `status_path=/status` —— 供容器 healthcheck 用 cgi-fcgi 探活。

### 4.4 `compose.yaml`(严格硬化)
- `read_only: true` —— 根 FS 只读。*为什么*:被入侵也改不了系统/代码;可写处仅显式开。
- `./src:/var/www/<name>:ro` —— 代码只读挂。*为什么*:CI 在宿主侧 rsync 改码即可,容器对代码无写权(防篡改);宿主改动经 bind 实时可见。
- `<name>-runtime` 命名卷 → `runtime/` + `tmpfs:/tmp,/run` —— 仅这几处可写。*为什么*:ThinkPHP 写 runtime(缓存/日志/session),php-fpm 写 /tmp、/run;精确开放,其余只读。
- `cap_drop:[ALL]` —— 丢所有 capability。*为什么*:php-fpm 监听高端口,不需要任何特权能力。
- `user: "33:33"`(www-data,非 root)+ `security_opt:[no-new-privileges:true]`。*为什么*:纵深防御,逃逸也只是无能力的非 root。
- `ports: ["127.0.0.1:<port>:9000"]` —— **只绑环回**。*为什么*:容器绝不上公网,唯一入口是宿主 nginx;`<port>` 为探测的空闲口,内部访问。
- `networks: dpt-net(external)` —— 共享外部网,dDP 首次 `network create`,各 app compose 独立。*为什么*:多项目/未来同栈走同一用户网络,互不耦合。
- `memory: 512m` 上限 · `restart: unless-stopped` · `logging: journald`。*为什么*:防单容器吃光内存;崩溃自拉起;日志并入已限额的宿主 journald,杜绝撑盘。
- healthcheck `cgi-fcgi … /ping | grep pong`。*为什么*:直连 fpm 探活,比 TCP 更真;空 src 也能过(fpm 自身答 /ping),故代码到位前容器即 healthy。

### 4.5 nginx vhost `/etc/nginx/conf.d/<name>.conf`(宿主,经 cert+sudo 写)
- `listen 443 ssl + http2`,自签证书占位,include `tls/security-headers/deny-dotfiles` 片段。*为什么*:复用 dDLN 边缘的 TLS/安全头/封点文件基线;证书先自签,域名就绪后 certbot 换真证。
- `server_name <域名>`,**不抢 default_server**。*为什么*:占位 vhost 仍兜未知 Host(444);本站只按域名匹配,多站共存。
- `root <宿主 src/public>` + `try_files … @thinkphp`。*为什么*:静态/try_files 由宿主 nginx 直接读宿主上的 src(bind 源在宿主 fs),不必进容器。
- `fastcgi_pass 127.0.0.1:<port>`;`SCRIPT_FILENAME=/var/www/<name>/public/index.php`(**容器内路径**);`PATH_INFO=$uri`。
  *为什么这是关键点*:nginx 在宿主、php-fpm 在容器,fastcgi 只传路径字符串,php-fpm 按**自己容器内**文件系统解析 SCRIPT_FILENAME——故必须是容器内路径;而 `root`(给静态用)是宿主路径,两者**故意不同**。PATH_INFO 给 ThinkPHP pathinfo 路由。
- `fastcgi_param HTTPS on / X-Forwarded-Proto` · `fastcgi_hide_header X-Powered-By` · `client_max_body_size 20m`。*为什么*:让容器知道是 HTTPS、透传协议、隐藏 PHP 标识、与 php 上传上限对齐。
- 写完 `nginx -t`,失败**自动删本 vhost 回滚**再报错。*为什么*:坏配置绝不进 reload,保住边缘不宕。

### 4.6 部署时序(空 src 先起)
scaffold → build_image(detached)→ up(空 src 也 healthy)→ nginx vhost。
*为什么空 src 先起*:代码由 CI 交付;先把容器骨架起好(fpm 答 /ping 即 healthy),CI 随后 rsync 代码 + reload。

## 5. Step 16 — CI/CD(GitLab,本机 runner)

- **本机 shell runner + 专用非 root 账号 `gitlab-runner`,只出站连 gitlab.oklik.com。** *为什么*:pull 式、无 inbound 部署密钥(消除一类泄密面);shell executor 因为宿主直编、runner 无 docker。
- **权限笼(ACL)**:`src` rwX、祖先链仅 x(不可枚举别的 app)、`.env` 拒读、无 docker/无 sudo。*为什么*:runner 是最易被供应链/流水线攻击的点,收到"只够改这一个 app 的代码、连别 app 名都列不出、读不到密钥"。
- **资源 slice `MemoryMax=1G/CPUQuota=50%`**。*为什么*:编译/composer 不能压垮 3.3G 生产机。
- **宿主直编(option2)+ 装匹配扩展**(`php7.4-{mysql,mbstring,zip,bcmath,intl,gd,redis,curl,xml,opcache}`,与容器 Dockerfile 同源)。*为什么装匹配扩展*:host composer 平台校验查 ext-*,缺了 `composer install` 失败;装齐才与容器一致、保真。
- **优雅 reload = 哨兵 + USR2**:CI rsync 完 `touch src/.reload-trigger`(dotfile,被 deny-dotfiles 拒露)→ **opt 侧** systemd --user path 监听 → `docker kill -s USR2 <name>-php`。*为什么*:runner 无 docker 没法自己 reload,解耦给有 docker 的 opt;USR2 = php-fpm 优雅重启 master(清 opcache、近零停机),配合 `validate_timestamps=0` 让新代码生效;不用 `--force-recreate` 避免停机。
- **每次部署 = 仅代码**(clone→composer→test→prod install→rsync 进 src[`--exclude runtime .env .git --delay-updates`]→触哨兵→轮询健康→失败回滚);**镜像重建归 dDP `build_image`**(runner 无 docker)。*为什么*:日常只换代码不重建镜像(快、稳);改 Dockerfile/PHP 版本才重建;`.env`/`runtime` 排除 rsync 保运行态,`--delay-updates` 准原子切换,失败回滚保上一版。
- **register 你在终端跑、token 不进对话**。*为什么*:注册令牌是密钥,同 connect.sh 边界。
- `.gitlab-ci.yml` dDP **只渲染打印、不落服务器/不进仓库**。*为什么*:它属于你的代码仓库,由你 copy 进去并版本管理,dDP 不越界写仓库。

## 6. 幂等 / 自愈

- 全脚本幂等(`mkdir -p` / 覆盖写 / 守卫 create / `setfacl` 声明式 / `systemd reset-failed`)。*为什么*:重跑安全是部署脚本的基本要求(网络抖动、开端口后重试)。
- `up.sh` 起前**自愈**:删 unhealthy/退出的残留容器;仅**空且无占用**的 runtime 卷才删(copy-up 重建 33:33),非空/在用卷绝不删。*为什么*:首跑失败会留属主错的空卷,命名卷已存在就不再 copy-up,普通重跑修不好——故主动清空残留;但绝不碰含 session/cache 的非空卷(生产数据)。

非自动化的非幂等点(文档化):scaffold 重跑覆盖会冲服务器手改的 config;`.env` 删-重建丢 deny ACL(就地编辑或重跑 cage_app);重建镜像留 dangling 层。

## 7. 安全边界(贯穿)

- 无 root 通道、无 connect.sh、不输任何密码;root 口令 / 注册 token 只在你终端;`.env` / ops 密码 dDP 从不读出。
- dDP 只部署项目;环境缺失指向别的 skill;唯一"装东西"的例外是 CI 工具链(它是 CI 的必需环境,已确认归 dDP)。

---

## 阶段流程速查

| Phase | 脚本 | 通道 | 性质 |
|---|---|---|---|
| 0 选 profile | `lib/list_profiles.sh` `script/preflight.sh` | 本机 | 只读 |
| 1 环境检查 | `check/{login,nginx,docker}.sh` | cert | 只查不修 |
| 2 部署 | `deploy/{probe,scaffold_app,build_image,up,nginx_vhost}.sh` | cert+sudo / cert+rootless | mutating(幂等/自愈) |
| 16 CI/CD | `ci/{install_toolchain,provision_runner,cage_app,render_ci,register_cmd}.sh` | cert+sudo / cert+rootless | mutating(install_toolchain/provision_runner/cage_app 需 live 测) |
