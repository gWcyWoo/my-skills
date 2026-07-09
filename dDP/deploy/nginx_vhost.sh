#!/usr/bin/env bash
# dDP / deploy / nginx_vhost —— 写宿主 nginx vhost → nginx -t(失败自动删本 vhost 回滚)→ reload。
# cert + sudo。root 指宿主上的 src/public,fastcgi 到 127.0.0.1:<port>。
# 用法: nginx_vhost.sh <profile> <name> <port> <domain> [listen_port]
#   listen_port 省略/443 → 标准 443+TLS+域名(server_name=<domain>);
#   listen_port 为自定义端口(如 32101)→ 纯 HTTP、该端口 default_server、server_name _(IP 直连)。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: nginx_vhost.sh <profile> <name> <port> <domain> [listen_port]}"
NAME="${2:?缺 name}"; PORT="${3:?缺 port}"; DOMAIN="${4:?缺 domain}"; LISTEN="${5:-443}"
TPL="$ROOT/deploy/templates"

# 解析运营用户家目录(vhost root 需宿主绝对路径)
HOME_DIR="$(rexec_user 'printf %s "$HOME"')"
[ -n "$HOME_DIR" ] || fail "无法解析运营用户家目录"
APPROOT="$HOME_DIR/dpt-docker-framework/apps/$NAME/src/public"
VHOST="/etc/nginx/conf.d/$NAME.conf"

# 选模板:443 → 标准 TLS+域名;自定义端口 → 纯 HTTP + default_server + IP 直连
if [ "$LISTEN" = "443" ]; then
  TPL_FILE="$TPL/vhost.conf.tmpl";      EDGE_DESC="$DOMAIN 经 443(TLS 自签)"
else
  TPL_FILE="$TPL/vhost-http.conf.tmpl"; EDGE_DESC="IP:$LISTEN(纯 HTTP)"
fi

section "宿主 nginx vhost: $NAME($EDGE_DESC → 127.0.0.1:$PORT)"

show "写 $VHOST" "sudo tee $VHOST(root=$APPROOT)"
if sed -e "s|__NAME__|$NAME|g" -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__PORT__|$PORT|g" -e "s|__LISTEN__|$LISTEN|g" -e "s|__ROOT__|$APPROOT|g" "$TPL_FILE" \
     | rexec_in "tee $VHOST >/dev/null"; then printf '  → done\n'; else fail "写 vhost 失败"; fi

show "nginx -t 校验" "nginx -t"
if rexec "nginx -t" >/dev/null 2>&1; then
  printf '  → done\n'
else
  printf '  → FAILED\n'
  rexec "nginx -t" 2>&1 | sed 's/^/  └─ /'
  show "回滚:删除本 vhost" "rm -f $VHOST"
  rexec "rm -f '$VHOST'" >/dev/null 2>&1
  printf '  → 已删除 %s(配置无效,未 reload)\n' "$VHOST"
  exit 1
fi

run "reload nginx" rexec "systemctl reload nginx"
printf '\nvhost 部署完成 ✅ —— %s → 127.0.0.1:%s\n' "$EDGE_DESC" "$PORT"
