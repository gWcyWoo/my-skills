#!/usr/bin/env bash
# dDC / checks —— 全部检查项(本次审计的产品化)。每个远端测试:合规静默退0,不合规 echo 原因 + exit1。
# 全部【只读】:cat/grep/test/awk/sshd -T/nginx -t/sysctl -n/docker inspect|ps|info/docker exec 只读/curl GET。
# 被 dDC.sh source;依赖 lib/common.sh 的 chk / rexec / rexec_user。

# ---------- SSH ----------
dDC_ssh() {
  section "SSH"
  chk r "SSH 仅公钥认证" "防密码暴破/凭证泄露" \
    'v=$(sshd -T 2>/dev/null | awk "/^passwordauthentication /{print \$2}"); [ "$v" = no ] || { echo "passwordauthentication=$v(期望 no)"; exit 1; }'
  chk r "SSH 禁 root 登录" "杜绝直接 root 远程登录" \
    'v=$(sshd -T 2>/dev/null | awk "/^permitrootlogin /{print \$2}"); [ "$v" = no ] || { echo "permitrootlogin=$v(期望 no)"; exit 1; }'
  chk r "SSH 仅 publickey 方法" "排除其它认证途径" \
    'v=$(sshd -T 2>/dev/null | awk "/^authenticationmethods /{print \$2}"); [ "$v" = publickey ] || { echo "authenticationmethods=$v(期望 publickey)"; exit 1; }'
  chk r "SSH 限定 AllowUsers" "最小化可登录账户" \
    'v=$(sshd -T 2>/dev/null | awk "/^allowusers /{\$1=\"\";print}"); [ -n "$(echo $v)" ] || { echo "未设置 allowusers(任意系统用户可尝试登录)"; exit 1; }'
  chk r "SSH MaxAuthTries ≤ 4" "限制单连接试错次数" \
    'v=$(sshd -T 2>/dev/null | awk "/^maxauthtries /{print \$2}"); { [ -n "$v" ] && [ "$v" -le 4 ]; } || { echo "maxauthtries=$v(期望 ≤4)"; exit 1; }'
  chk r "SSH 关闭 X11Forwarding" "减少转发攻击面" \
    'v=$(sshd -T 2>/dev/null | awk "/^x11forwarding /{print \$2}"); [ "$v" = no ] || { echo "x11forwarding=$v(期望 no)"; exit 1; }'
  chk r "SSH 关闭 TCP 转发" "防端口转发滥用" \
    'v=$(sshd -T 2>/dev/null | awk "/^allowtcpforwarding /{print \$2}"); [ "$v" = no ] || { echo "allowtcpforwarding=$v(期望 no)"; exit 1; }'
  chk r "SSH 非默认端口(非22)" "降低自动化扫描噪声" \
    'v=$(sshd -T 2>/dev/null | awk "/^port /{print \$2}"); { [ -n "$v" ] && [ "$v" != 22 ]; } || { echo "port=$v(仍为默认22)"; exit 1; }'
  chk r "SSH 日志 VERBOSE" "登录行为可审计" \
    'v=$(sshd -T 2>/dev/null | awk "/^loglevel /{print \$2}"); [ "$v" = VERBOSE ] || { echo "loglevel=$v(期望 VERBOSE)"; exit 1; }'
}

# ---------- 用户 / 提权 ----------
dDC_user() {
  section "用户 / 提权"
  chk r "无 root 以外的 uid=0 账户" "防隐藏超级用户" \
    'b=$(awk -F: "\$3==0 && \$1!=\"root\"{print \$1}" /etc/passwd); [ -z "$b" ] || { echo "发现 uid=0 账户:$b"; exit 1; }'
  chk r "无空口令账户" "杜绝空密码登录" \
    'b=$(awk -F: "(\$2==\"\"){print \$1}" /etc/shadow 2>/dev/null); [ -z "$b" ] || { echo "空口令账户:$b"; exit 1; }'
  chk r "无普通用户 NOPASSWD:ALL" "限制免密提权面" \
    'b=$(grep -rhE "NOPASSWD:[[:space:]]*ALL" /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -vE "^[[:space:]]*#" | grep -vE "^root\b"); [ -z "$b" ] || { echo "存在免密全量 sudo(若为部署期 dDLN 暂留,完成后应撤):$b"; exit 1; }'
  chk r "人类用户(uid≥1000)数量受控(≤2)" "无多余可登录账户" \
    'n=$(awk -F: "\$3>=1000 && \$3<65534{print \$1}" /etc/passwd); c=$(echo "$n" | grep -c .); [ "$c" -le 2 ] || { echo "uid≥1000 用户共 $c 个:$(echo $n)"; exit 1; }'
}

# ---------- 防火墙 / 网络 ----------
dDC_firewall() {
  section "防火墙 / 网络"
  chk r "ufw 已启用" "主机级入站过滤生效" \
    'ufw status 2>/dev/null | grep -qi "Status: active" || { echo "ufw 未 active"; exit 1; }'
  chk r "ufw 默认拒绝入站" "默认收敛,白名单放行" \
    'ufw status verbose 2>/dev/null | grep -qiE "deny \(incoming\)" || { echo "默认入站策略非 deny:$(ufw status verbose 2>/dev/null | grep -i Default)"; exit 1; }'
  chk r "无意外对外监听端口" "仅暴露必要端口(ssh/443)" \
    'p=$(ss -tlnH 2>/dev/null | awk "{print \$4}" | grep -vE "127\.0\.0\.1|\[::1\]|127\.0\.0\.5" | grep -oE "[0-9]+\$" | sort -un | grep -vE "^(443|80|'"$DPT_PORT"'|5355)\$"); [ -z "$p" ] || { echo "对外监听到非预期端口:$(echo $p)"; exit 1; }'
}

# ---------- 系统 / 内核 / 日志 ----------
dDC_system() {
  section "系统 / 内核 / 日志 / 更新"
  chk r "内核安全 sysctl 基线" "系统层加固(ASLR/kptr/dmesg/rp_filter/redirects/syncookies/ptrace/protected)" '
    f="";
    cv(){ v=$(sysctl -n "$1" 2>/dev/null); [ "$v" = "$2" ] || f="$f $1=$v(want $2)"; }
    cv kernel.randomize_va_space 2; cv kernel.kptr_restrict 2; cv kernel.dmesg_restrict 1
    cv net.ipv4.conf.all.rp_filter 1; cv net.ipv4.tcp_syncookies 1
    cv net.ipv4.conf.all.accept_redirects 0; cv net.ipv4.conf.all.accept_source_route 0
    cv fs.protected_symlinks 1; cv fs.protected_hardlinks 1; cv kernel.yama.ptrace_scope 1
    [ -z "$f" ] || { echo "不合规:$f"; exit 1; }'
  chk r "网络性能 sysctl(BBR + fq + swappiness)" "当前硬件吞吐/延迟最优" '
    cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null); qd=$(sysctl -n net.core.default_qdisc 2>/dev/null); sw=$(sysctl -n vm.swappiness 2>/dev/null)
    { [ "$cc" = bbr ] && [ "$qd" = fq ] && [ "${sw:-100}" -le 20 ]; } || { echo "congestion=$cc(want bbr) qdisc=$qd(want fq) swappiness=$sw(want ≤20)"; exit 1; }'
  chk r "journald 持久化" "重启后日志不丢,可追溯" \
    'test -d /var/log/journal || { echo "无 /var/log/journal(日志仅 volatile)"; exit 1; }'
  chk r "自动安全更新已启用" "及时修补已知漏洞" \
    'systemctl is-active unattended-upgrades >/dev/null 2>&1 || { echo "unattended-upgrades 未 active"; exit 1; }'
  chk r "无待装安全更新" "无已知未修补 CVE" \
    'n=$(apt-get -s upgrade 2>/dev/null | grep -ciE "^Inst.*(security|Debian-Security)"); [ "${n:-0}" -eq 0 ] || { echo "待装安全更新 $n 个(apt-get -s upgrade)"; exit 1; }'
  chk r "无待重启(reboot-required)" "内核/库更新已生效" \
    'test ! -f /var/run/reboot-required || { echo "存在 reboot-required:$(cat /var/run/reboot-required 2>/dev/null)"; exit 1; }'
  chk r "fail2ban 运行且含 sshd jail" "暴破自动封禁" \
    'systemctl is-active fail2ban >/dev/null 2>&1 || { echo "fail2ban 未 active"; exit 1; }; fail2ban-client status sshd >/dev/null 2>&1 || { echo "无 sshd jail"; exit 1; }'
}

# ---------- Docker 守护 / rootless ----------
dDC_docker() {
  section "Docker 守护 / rootless"
  chk u "Docker 为 rootless" "降权运行,缩小逃逸影响" \
    'docker info 2>/dev/null | grep -qi rootless || { echo "docker info 未见 rootless"; exit 1; }'
  chk r "rootful docker.service 已禁用/不活动" "避免特权守护并存" \
    'systemctl is-enabled docker.service 2>/dev/null | grep -qE "masked|disabled" || ! systemctl is-active docker.service >/dev/null 2>&1 || { echo "rootful docker.service 处于 enabled+active"; exit 1; }'
  chk r "运营用户 lingering 已开" "rootless 守护随机启动/常驻" \
    'loginctl show-user '"$DPT_USER"' -p Linger --value 2>/dev/null | grep -q yes || { echo "lingering 未开(rootless 守护可能不随开机)"; exit 1; }'
  chk u "daemon.json 启用 no-new-privileges" "默认阻断容器提权" \
    'grep -q "no-new-privileges" "$HOME/.config/docker/daemon.json" 2>/dev/null || { echo "daemon.json 未设 no-new-privileges"; exit 1; }'
  chk u "daemon.json 日志走 journald" "日志集中、可审计、防写满" \
    'grep -q "journald" "$HOME/.config/docker/daemon.json" 2>/dev/null || { echo "daemon.json 未设 journald 日志驱动"; exit 1; }'
}

# ---------- 容器(每 app)安全 + 资源 ----------
dDC_container() {
  local n="$1" c="$1-php"
  section "容器 $c — 安全 + 资源"
  chk u "$c 只读根文件系统" "防容器内被篡改/落马" \
    'v=$(docker inspect -f "{{.HostConfig.ReadonlyRootfs}}" '"$c"' 2>/dev/null); [ "$v" = true ] || { echo "ReadonlyRootfs=$v(期望 true)"; exit 1; }'
  chk u "$c 丢弃所有 capabilities" "最小权限" \
    'v=$(docker inspect -f "{{.HostConfig.CapDrop}}" '"$c"' 2>/dev/null); echo "$v" | grep -q ALL || { echo "CapDrop=$v(期望含 ALL)"; exit 1; }'
  chk u "$c no-new-privileges" "阻断 setuid 提权" \
    'v=$(docker inspect -f "{{.HostConfig.SecurityOpt}}" '"$c"' 2>/dev/null); echo "$v" | grep -q no-new-privileges || { echo "SecurityOpt=$v(期望含 no-new-privileges)"; exit 1; }'
  chk u "$c 非 root 运行" "降低逃逸危害" \
    'v=$(docker inspect -f "{{.Config.User}}" '"$c"' 2>/dev/null); case "$v" in ""|0|root|0:*) echo "User=$v(期望非 root,如 33:33)"; exit 1;; esac'
  chk u "$c 非特权容器" "无特权设备/能力" \
    'v=$(docker inspect -f "{{.HostConfig.Privileged}}" '"$c"' 2>/dev/null); [ "$v" = false ] || { echo "Privileged=$v(期望 false)"; exit 1; }'
  chk u "$c 端口仅绑 127.0.0.1" "fpm 不直接对外暴露" \
    'b=$(docker inspect -f "{{range \$p,\$v:=.HostConfig.PortBindings}}{{range \$v}}{{.HostIp}} {{end}}{{end}}" '"$c"' 2>/dev/null); echo "$b" | grep -qE "0\.0\.0\.0|::|^[[:space:]]*\$" && { echo "存在非 127.0.0.1 绑定:[$b]"; exit 1; }; echo "$b" | grep -qv "127.0.0.1" && { echo "绑定含非本地:[$b]"; exit 1; }; true'
  chk u "$c 设内存上限" "防单容器吃满宿主内存" \
    'm=$(docker inspect -f "{{.HostConfig.Memory}}" '"$c"' 2>/dev/null); { [ -n "$m" ] && [ "$m" -gt 0 ]; } || { echo "未设内存上限(Memory=$m)"; exit 1; }'
  chk u "$c 设 pids 上限" "防 fork-bomb" \
    'p=$(docker inspect -f "{{.HostConfig.PidsLimit}}" '"$c"' 2>/dev/null); { [ -n "$p" ] && [ "$p" != "<nil>" ] && [ "$p" -gt 0 ] 2>/dev/null; } || { echo "未设 pids 上限(PidsLimit=$p)"; exit 1; }'
  chk u "$c 健康(healthy)" "运行态正常" \
    'h=$(docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" '"$c"' 2>/dev/null); [ "$h" = healthy ] || { echo "健康状态=$h(期望 healthy)"; exit 1; }'
  chk u "$c 内存上限与 max_children 自洽" "满载不触发容器 OOM" '
    m=$(docker inspect -f "{{.HostConfig.Memory}}" '"$c"' 2>/dev/null)
    mc=$(docker exec '"$c"' grep -oE "^pm.max_children = [0-9]+" /usr/local/etc/php-fpm.d/www.conf 2>/dev/null | grep -oE "[0-9]+" | head -1)
    [ -n "$m" ] && [ -n "$mc" ] || { echo "无法读取 Memory=$m / max_children=$mc"; exit 1; }
    need=$(( mc * 80 * 1048576 ))
    [ "$m" -ge "$need" ] || { echo "内存上限 $((m/1048576))MiB < max_children($mc)×80MiB=$((need/1048576))MiB,满载可能 OOM"; exit 1; }'
}

# ---------- 容器内 PHP(每 app,读镜像内生效配置)----------
dDC_php() {
  local c="$1-php" ini='/usr/local/etc/php/conf.d/99-dpt.ini' pool='/usr/local/etc/php-fpm.d/www.conf'
  section "PHP(容器 $c 内)"
  chk u "expose_php Off" "不泄露 PHP 版本" \
    'docker exec '"$c"' grep -qiE "^expose_php[[:space:]]*=[[:space:]]*Off" '"$ini"' || { echo "expose_php 非 Off"; exit 1; }'
  chk u "display_errors Off" "不向用户暴露报错细节" \
    'docker exec '"$c"' grep -qiE "^display_errors[[:space:]]*=[[:space:]]*Off" '"$ini"' || { echo "display_errors 非 Off"; exit 1; }'
  chk u "cgi.fix_pathinfo=0" "防路径解析型上传执行" \
    'docker exec '"$c"' grep -qE "^cgi.fix_pathinfo[[:space:]]*=[[:space:]]*0" '"$ini"' || { echo "cgi.fix_pathinfo 非 0"; exit 1; }'
  chk u "opcache 开启且 validate_timestamps=0" "性能最优(生产钉缓存)" \
    'docker exec '"$c"' sh -c "grep -qE \"^opcache.enable[[:space:]]*=[[:space:]]*1\" '"$ini"' && grep -qE \"^opcache.validate_timestamps[[:space:]]*=[[:space:]]*0\" '"$ini"'" || { echo "opcache.enable!=1 或 validate_timestamps!=0"; exit 1; }'
  chk u "session cookie 加固" "httponly+secure+samesite+strict_mode" \
    'docker exec '"$c"' sh -c "grep -qiE \"^session.cookie_httponly[[:space:]]*=[[:space:]]*On\" '"$ini"' && grep -qiE \"^session.cookie_secure[[:space:]]*=[[:space:]]*On\" '"$ini"' && grep -qiE \"^session.use_strict_mode[[:space:]]*=[[:space:]]*On\" '"$ini"'" || { echo "session cookie 加固项缺失"; exit 1; }'
  chk u "fpm 禁危险函数" "削减 RCE 面(exec/system/...)" \
    'docker exec '"$c"' grep -qE "disable_functions.*(system|exec|shell_exec|proc_open)" '"$pool"' || { echo "www.conf 未见 disable_functions 危险函数"; exit 1; }'
  chk u "fpm 仅允许 .php 扩展" "防非 php 文件被当脚本执行" \
    'docker exec '"$c"' grep -qE "^security.limit_extensions[[:space:]]*=[[:space:]]*.php" '"$pool"' || { echo "security.limit_extensions 非 .php"; exit 1; }'
  chk u "fpm clear_env=yes" "不向脚本泄露宿主环境变量" \
    'docker exec '"$c"' grep -qE "^clear_env[[:space:]]*=[[:space:]]*yes" '"$pool"' || { echo "clear_env 非 yes"; exit 1; }'
}

# ---------- nginx 边缘 ----------
dDC_nginx() {
  section "nginx 边缘"
  chk r "nginx -t 通过" "配置语法/引用有效" \
    'nginx -t >/dev/null 2>&1 || { echo "nginx -t 失败:$(nginx -t 2>&1 | tail -2)"; exit 1; }'
  chk r "server_tokens off" "不泄露 nginx 版本" \
    'grep -qE "^[[:space:]]*server_tokens[[:space:]]+off" /etc/nginx/nginx.conf || { echo "nginx.conf 未关 server_tokens"; exit 1; }'
  chk r "TLS 仅 1.2/1.3" "禁用不安全旧协议" \
    'f=/etc/nginx/snippets/tls.conf; grep -q "TLSv1.3" "$f" 2>/dev/null && ! grep -qE "TLSv1[^.]|TLSv1\.1|TLSv1 " "$f" 2>/dev/null || { echo "tls.conf 未含 1.3 或含 1.0/1.1:$(grep ssl_protocols $f 2>/dev/null)"; exit 1; }'
  chk r "HSTS 安全头" "强制 HTTPS" \
    'grep -qi "Strict-Transport-Security" /etc/nginx/snippets/security-headers.conf 2>/dev/null || { echo "缺 HSTS 头"; exit 1; }'
  chk r "X-Content-Type-Options / X-Frame-Options" "防 MIME 嗅探 / 点击劫持" \
    'f=/etc/nginx/snippets/security-headers.conf; grep -qi "X-Content-Type-Options" "$f" && grep -qi "X-Frame-Options" "$f" || { echo "安全响应头缺失"; exit 1; }'
  chk r "限速 zone 已定义" "缓解 CC/暴破" \
    'grep -qE "limit_req_zone" /etc/nginx/nginx.conf 2>/dev/null || { echo "nginx.conf 未定义 limit_req_zone"; exit 1; }'
  chk r "未知 Host(HTTP)返回 444" "挡裸 IP 扫描、不泄露" \
    'grep -rqE "return[[:space:]]+444" /etc/nginx/conf.d/000-placeholder.conf 2>/dev/null || { echo "占位 vhost 未对未知 Host 444"; exit 1; }'
  chk r "WAF(ModSecurity)模块已加载" "应用层攻击检测" \
    'grep -rq ngx_http_modsecurity_module /etc/nginx/modules-enabled/ 2>/dev/null || { echo "未加载 modsecurity 模块"; exit 1; }'
}

# ---------- 可用性(每 app,端到端 GET)----------
dDC_availability() {
  local n="$1"
  section "可用性 — $n 站点(端到端)"
  chk r "$n 站点 HTTPS 可访问(非 5xx/非空入口)" "php web 站点真实可用" '
    vh=$(ls /etc/nginx/conf.d/'"$n"'.conf 2>/dev/null || grep -rl "apps/'"$n"'/src/public" /etc/nginx/conf.d/ 2>/dev/null | head -1)
    [ -n "$vh" ] || { echo "未找到 '"$n"' 的 nginx vhost"; exit 1; }
    sn=$(awk "/server_name/{print \$2}" "$vh" | head -1 | tr -d ";")
    [ -n "$sn" ] || { echo "vhost 无 server_name"; exit 1; }
    body=$(curl -sk -H "Host: $sn" --max-time 8 https://127.0.0.1/ 2>/dev/null)
    code=$(curl -sk -H "Host: $sn" -o /dev/null -w "%{http_code}" --max-time 8 https://127.0.0.1/ 2>/dev/null)
    echo "$body" | grep -qi "No input file specified" && { echo "$sn → 入口缺失(public/index.php 未部署,No input file specified);代码待 CI 交付"; exit 1; }
    case "$code" in 5??|000|"") echo "$sn → HTTP ${code:-无响应}(5xx/无响应=应用不可用)"; exit 1;; *) : ;; esac   # 2xx/3xx/4xx=应用在响应(API 的 401/403/404 算存活,与 dDP 部署健康门一致)'
}
