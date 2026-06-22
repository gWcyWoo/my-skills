#!/usr/bin/env bash
# dpt / edge / nginx / deploy_config —— 部署加固 nginx.conf + include 片段 + 自签证书 + 占位 vhost + fail2ban jails。
# 运营 cert + sudo(无 root)。用法: deploy_config.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: deploy_config.sh <profile>}"
export DPT_BOOT=sudo
C="$ROOT/edge/conf"

# ship <本地文件> <远端路径> <mode> —— 经 sudo tee 写到服务器,再 chmod。
ship() {
  show "部署 $2" "tee $2  ← $(printf '%s' "$1" | sed "s#$ROOT/##")"
  if rexec_in "tee '$2' >/dev/null" < "$1" && rexec "chmod $3 '$2'" >/dev/null 2>&1; then printf '  → done\n'
  else fail "部署 $2 失败"; fi
}

section "部署 nginx 边缘配置"
run "建配置目录 + 删 nginx.org 默认 vhost" rexec "
  install -d -m755 /etc/nginx/snippets /etc/nginx/modsec /etc/nginx/conf.d /etc/nginx/ssl /var/www/html
  rm -f /etc/nginx/conf.d/default.conf"

ship "$C/nginx.conf"                     /etc/nginx/nginx.conf                     644
ship "$C/snippets/tls.conf"              /etc/nginx/snippets/tls.conf              644
ship "$C/snippets/security-headers.conf" /etc/nginx/snippets/security-headers.conf 644
ship "$C/snippets/ratelimit.conf"        /etc/nginx/snippets/ratelimit.conf        644
ship "$C/snippets/fastcgi-php.conf"      /etc/nginx/snippets/fastcgi-php.conf      644
ship "$C/snippets/static-cache.conf"     /etc/nginx/snippets/static-cache.conf     644
ship "$C/snippets/deny-dotfiles.conf"    /etc/nginx/snippets/deny-dotfiles.conf    644
ship "$C/snippets/modsec.conf"           /etc/nginx/snippets/modsec.conf           644
ship "$C/modsec/main.conf"               /etc/nginx/modsec/main.conf               644
ship "$C/conf.d/000-placeholder.conf"    /etc/nginx/conf.d/000-placeholder.conf    644

run "生成自签证书占位(幂等;域名就绪后 certbot 换真证书)" rexec "
  [ -f /etc/nginx/ssl/selfsigned.crt ] || openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout /etc/nginx/ssl/selfsigned.key -out /etc/nginx/ssl/selfsigned.crt \
    -subj '/CN=dpt-edge-placeholder' >/dev/null 2>&1
  chmod 600 /etc/nginx/ssl/selfsigned.key; chmod 644 /etc/nginx/ssl/selfsigned.crt"

run "部署 fail2ban nginx jails" rexec "cat > /etc/fail2ban/jail.d/dpt-nginx.conf <<'CONF'
[nginx-http-auth]
enabled = true
logpath = /var/log/nginx/error.log
[nginx-botsearch]
enabled = true
logpath = /var/log/nginx/access.log
[nginx-limit-req]
enabled = true
logpath = /var/log/nginx/error.log
CONF
  systemctl reload fail2ban 2>/dev/null || systemctl restart fail2ban 2>/dev/null || true"

run "nginx -t 校验" rexec "nginx -t"
run "启动/重载 nginx" rexec "systemctl restart nginx"

section "nginx 边缘配置完成"
