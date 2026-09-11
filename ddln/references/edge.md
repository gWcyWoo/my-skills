## edge 模块编排(系统模块之后;宿主公网边缘 nginx,全程 ops cert + sudo)
**架构定位**:nginx 装宿主(非容器)作公网边缘——拿真实客户端 IP、原生绑 443、吃 unattended-upgrades 自动更新、fail2ban 直接接 nginx 日志;应用逻辑(php-fpm/db/redis)留给后续 rootless Docker 容器(全 `127.0.0.1`),宿主 nginx fastcgi 过去。**交付即全框架;上业务只在 `conf.d/` 加一个 vhost `.conf`(include snippets/ + `fastcgi_pass 127.0.0.1:9000`)。**

**Phase E0–E4(都幂等):**
- E0 `bash .../edge/script/preflight.sh`
- E1 `bash .../edge/script/nginx/install_nginx.sh <profile>` —— nginx.org stable 源 + pin + 装(**detached**)+ origin=nginx 入 unattended-upgrades
- E2 `bash .../edge/script/nginx/install_waf.sh <profile>` —— libmodsecurity3 + 编连接器(**detached**,探测优先 guard)+ OWASP CRS(默认 **DetectionOnly**)
- E3 `bash .../edge/script/nginx/deploy_config.sh <profile>` —— 加固 nginx.conf + snippets + 自签证书占位 + 占位 vhost + fail2ban nginx jails + `nginx -t` + start
- E4 `bash .../edge/close/close_check.sh <profile>`

**edge 子动作 — 配置真实 TLS 证书(`--cert`;部署后运维,不跑模块).**
EC0. 复用已明确的 profile 和 app；仅询问缺项。
EC1. **问用户两条本地路径**:① 证书文件(fullchain `.crt`/`.pem`,含服务器证书+中间链)② 私钥文件(无口令 `.key`)。**只要路径,绝不要内容**(私钥是机密)。
EC2. 跑 `bash ~/.agents/skills/ddln/edge/script/nginx/configure_cert.sh <profile> <name> <证书路径> <私钥路径>` —— `[1/7]…[7/7]`:本地校验证书/私钥匹配 → 前置(sudo NOPASSWD + vhost 存在)→ 上传(私钥经 `rexec_in` 管道直传、不显示)→ 改该 app vhost 的 `ssl_certificate(_key)` → `nginx -t`(失败自动回滚 vhost)→ reload → **自动关闭 NOPASSWD + 验证**。
    - **NOPASSWD 开关**:脚本若检测到 sudo 不可用会 `exit 2` 并打印【ssh 登录 + 临时开启 NOPASSWD】命令;你**必须把该命令贴进回复正文**,让用户在自己终端手动开启(需其 sudo 密码),开好后**重跑 EC2**。配完脚本**自动关闭** NOPASSWD —— 用户只手动开这一次。
    - **🔒 密钥边界**:私钥内容**绝不进对话**,只在「本地 ↔ 服务器」管道流动;你只接收路径,绝不询问/打印私钥内容。
    - **⚠️ 显示约定(MUST)**:脚本每步 `[n/7]` 进展与最终结果会被工具折叠,对话报告关键进展、失败原因和最终结果，无需逐行复述。

**取舍/约定(已定)**:nginx.org stable(latest + 动态模块 + 入自动更新)· WAF=ModSecurity v3 连接器编译(`--with-compat`,apt 钩子按需重建,探测优先不做无谓编译)+ CRS DetectionOnly · TLS 1.2/1.3 Mozilla Intermediate(仅 ECDHE,无 OCSP——LE 已停)· HSTS 无 preload · 自签证书占位(域名就绪 certbot 换真证)· 容器端口一律 `127.0.0.1`、只有 nginx 公网(443)。

**本次构建踩到、已固化(完整清单 —— 适用所有模块):**
1. **跨境长操作必须 detached**:本机欧洲、服务器中国,长 apt/编译跑在前台 ssh 上会被跨境抖动 reset。`install_nginx`/`install_waf` 的安装与编译走 `systemd-run --no-block` + 轮询(同既有铁律)。
2. **多命令 step 的"假绿"**:一个 `run` 里多条命令、退出码只看**最后一条** → 中途失败(如 `/etc/apt/sources.list.d` 不存在)被末条成功掩盖成 `done`。**正解 = 对关键写入显式校验**(`install_nginx` 写完 apt 源即 `test -s <文件> && grep`)。**曾试在 `rexec` 全局 `set -e`,已回滚** —— 它误杀"有意忽略错误 + 末尾 true"的惯用法(dead-man's-switch 撤销),且后果危险(撤销失败 → ufw 被自动 disable → 防火墙宕)。
3. **跨模块文件冲突**:edge 的 nginx origin 起初 append 进系统模块"覆盖写(`cat>`)"的 `52unattended-upgrades-local` → 系统模块一再跑就把它覆盖掉。**正解 = 每个模块只写自己独占的 drop-in**(edge 改用独立 `53unattended-upgrades-nginx`),**绝不 append 别的模块拥有/覆盖写的文件**。
4. **WAF 连接器与 nginx 版本耦合的失效保护**:nginx 自动升级若使连接器 ABI 不符且重建失败 → `load_module` 会让 nginx 起不来(边缘宕)。`rebuild_modsec` 加 **fail-safe**:重建失败即禁用 `load_module`,保"WAF 关、边缘起"(可起 > 宕)。
