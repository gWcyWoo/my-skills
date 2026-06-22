#!/usr/bin/env bash
# dpt / edge / close —— 宿主 nginx 边缘收尾审计(只查)。运营 cert + sudo。
# 用法: close_check.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: close_check.sh <profile>}"
export DPT_BOOT=sudo

FAILED=0
yn() { show "$1" "$2"; if rexec "$2" >/dev/null 2>&1; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi; }

section "边缘(nginx)收尾检查"

printf '## 安装与来源\n'
yn "nginx 已装" "command -v nginx >/dev/null"
yn "来自 nginx.org" "nginx -V 2>&1 | grep -qi 'built by\\|nginx.org' || nginx -v 2>&1 | grep -q nginx/"
yn "纳入自动更新(origin=nginx)" "grep -rq 'origin=nginx' /etc/apt/apt.conf.d/"
yn "nginx 运行中" "systemctl is-active nginx >/dev/null 2>&1"
yn "监听 443" "ss -ltn | grep -q ':443'"
yn "配置校验 nginx -t" "nginx -t"

printf '\n## 安全配置\n'
yn "server_tokens off" "grep -q 'server_tokens off' /etc/nginx/nginx.conf"
yn "TLS 片段(1.2/1.3)" "grep -q 'TLSv1.3' /etc/nginx/snippets/tls.conf"
yn "安全头片段(HSTS)" "grep -q 'Strict-Transport-Security' /etc/nginx/snippets/security-headers.conf"
yn "限速片段" "test -f /etc/nginx/snippets/ratelimit.conf"
yn "封点文件片段" "test -f /etc/nginx/snippets/deny-dotfiles.conf"
yn "自签证书占位" "test -f /etc/nginx/ssl/selfsigned.crt"
yn "未知 Host 占位 444" "grep -q 'return 444' /etc/nginx/conf.d/000-placeholder.conf"

printf '\n## WAF(ModSecurity + CRS)\n'
yn "连接器 .so 在位" "test -f /etc/nginx/modules/ngx_http_modsecurity_module.so"
yn "load_module 已注册" "grep -rq ngx_http_modsecurity_module /etc/nginx/modules-enabled/"
yn "WAF DetectionOnly" "grep -qE '^SecRuleEngine[[:space:]]+DetectionOnly' /etc/nginx/modsec/modsecurity.conf"
yn "OWASP CRS 在位" "test -f /etc/nginx/modsec/crs/crs-setup.conf"
yn "重建器(探测优先)在位" "test -x /usr/local/sbin/dpt-modsec-rebuild"
yn "apt 钩子已注册" "grep -rq 'dpt-modsec-rebuild' /etc/apt/apt.conf.d/"

printf '\n## fail2ban 边缘 jail\n'
yn "nginx-http-auth jail 运行" "fail2ban-client status nginx-http-auth >/dev/null 2>&1"
yn "nginx-botsearch jail 运行" "fail2ban-client status nginx-botsearch >/dev/null 2>&1"

printf '\n'
if [ "$FAILED" -eq 0 ]; then printf '边缘收尾检查全部通过 ✅\n'; exit 0
else printf '边缘收尾检查存在未通过项 ❌(见上面 FAILED)\n'; exit 1; fi
