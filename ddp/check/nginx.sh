#!/usr/bin/env bash
# dDP / check / nginx —— 部署前 nginx 边缘就绪检查(**只查,不修**)。运营 cert + sudo。
# 跑满全部检查、不在首个失败处停;末尾列出所有缺失/不合规项。退出 0=全就绪 / 1=有缺失。
# 缺失 = 环境没准备好;dDP 不安装,须由 dDLN edge 模块补齐。用法: nginx.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: nginx.sh <profile>}"

MISS=()
# chk "标签" "远端测试命令" —— cert+sudo 跑;通过 → ✓,不通 → ✗ 并记入缺失。不短路。
chk() {
  show "$1" "$2"
  if rexec "$2" >/dev/null 2>&1; then printf '  → ✓\n'; else printf '  → ✗ 缺失\n'; MISS+=("$1"); fi
}

section "nginx 边缘就绪检查(只查)"

printf '## 安装与来源\n'
chk "nginx 已装"                 "command -v nginx >/dev/null"
chk "来自 nginx.org"             "nginx -V 2>&1 | grep -qi 'built by\\|nginx.org' || nginx -v 2>&1 | grep -q nginx/"
chk "nginx 运行中"               "systemctl is-active nginx >/dev/null 2>&1"
chk "监听 443"                   "ss -ltn | grep -q ':443'"
chk "纳入自动更新(origin=nginx)" "grep -rq 'origin=nginx' /etc/apt/apt.conf.d/"

printf '\n## 配置(可加业务 vhost)\n'
chk "nginx -t 通过"              "nginx -t"
chk "conf.d 目录在"              "test -d /etc/nginx/conf.d"
chk "TLS 片段"                   "test -f /etc/nginx/snippets/tls.conf"
chk "安全头片段"                 "test -f /etc/nginx/snippets/security-headers.conf"
chk "限速片段"                   "test -f /etc/nginx/snippets/ratelimit.conf"
chk "封点文件片段"               "test -f /etc/nginx/snippets/deny-dotfiles.conf"
chk "fastcgi-php 片段"           "test -f /etc/nginx/snippets/fastcgi-php.conf"
chk "占位 vhost(未知 Host 444)" "grep -q 'return 444' /etc/nginx/conf.d/000-placeholder.conf"

printf '\n## 安全\n'
chk "server_tokens off"          "grep -q 'server_tokens off' /etc/nginx/nginx.conf"
chk "TLS 1.3 启用"               "grep -q 'TLSv1.3' /etc/nginx/snippets/tls.conf"
chk "HSTS 安全头"                "grep -q 'Strict-Transport-Security' /etc/nginx/snippets/security-headers.conf"
chk "自签证书占位"               "test -f /etc/nginx/ssl/selfsigned.crt"
chk "WAF 连接器 .so 在位"        "test -f /etc/nginx/modules/ngx_http_modsecurity_module.so"
chk "WAF load_module 已注册"     "grep -rq ngx_http_modsecurity_module /etc/nginx/modules-enabled/"
chk "WAF DetectionOnly"          "grep -qE '^SecRuleEngine[[:space:]]+DetectionOnly' /etc/nginx/modsec/modsecurity.conf"
chk "OWASP CRS 在位"             "test -f /etc/nginx/modsec/crs/crs-setup.conf"
chk "fail2ban nginx-http-auth"   "fail2ban-client status nginx-http-auth >/dev/null 2>&1"
chk "fail2ban nginx-botsearch"   "fail2ban-client status nginx-botsearch >/dev/null 2>&1"

printf '\n'
if [ "${#MISS[@]}" -eq 0 ]; then
  printf 'nginx 就绪 ✅ —— 全部检查通过\n'
  exit 0
else
  printf 'nginx 未就绪 ❌ —— 缺失/不合规 %d 项(须由 dDLN edge 模块补齐):\n' "${#MISS[@]}"
  for m in "${MISS[@]}"; do printf '  - %s\n' "$m"; done
  exit 1
fi
