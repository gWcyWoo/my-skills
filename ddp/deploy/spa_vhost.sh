#!/usr/bin/env bash
# dDP / deploy / spa_vhost —— SPA+API 合并 vhost:/ → 前端 dist,<api_prefix>/ → 剥前缀 → 后端 fpm。
# 会【替换】后端原独立 vhost(同端口冲突):先备份再删,nginx -t 失败自动还原旧 vhost、删本 vhost。
# cert + sudo。用法: spa_vhost.sh <profile> <fe_name> <be_name> <fpm_port> <listen> [api_prefix=/api]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: spa_vhost.sh <profile> <fe_name> <be_name> <fpm_port> <listen> [api_prefix]}"
FE="${2:?缺 fe_name}"; BE="${3:?缺 be_name}"; PORT="${4:?缺 fpm_port}"; LISTEN="${5:?缺 listen}"; PREFIX="${6:-/api}"
TPL="$ROOT/deploy/templates/vhost-spa.conf.tmpl"

HOME_DIR="$(rexec_user 'printf %s "$HOME"')"
[ -n "$HOME_DIR" ] || fail "无法解析运营用户家目录"
FE_ROOT="$HOME_DIR/dpt-docker-framework/apps/$FE/dist"
VHOST="/etc/nginx/conf.d/$FE.conf"
OLD="/etc/nginx/conf.d/$BE.conf"
BAK="/etc/nginx/conf.d/.$BE.conf.replaced-by-$FE"

section "SPA+API 合并 vhost: $FE + $BE(:$LISTEN → / 静态 + $PREFIX/ → 127.0.0.1:$PORT)"

show "备份并移除后端原 vhost(同端口让位)" "mv $OLD → $BAK(不存在则跳过)"
rexec "[ -f '$OLD' ] && mv '$OLD' '$BAK' || true" >/dev/null 2>&1
printf '  → done\n'

show "写 $VHOST" "sudo tee $VHOST(root=$FE_ROOT)"
if sed -e "s|__FE_ROOT__|$FE_ROOT|g" -e "s|__BE_NAME__|$BE|g" -e "s|__PORT__|$PORT|g" \
       -e "s|__LISTEN__|$LISTEN|g" -e "s|__API_PREFIX__|$PREFIX|g" "$TPL" \
     | rexec_in "tee $VHOST >/dev/null"; then printf '  → done\n'; else fail "写 vhost 失败"; fi

show "nginx -t 校验" "nginx -t"
if rexec "nginx -t" >/dev/null 2>&1; then
  printf '  → done\n'
else
  printf '  → FAILED\n'
  rexec "nginx -t" 2>&1 | sed 's/^/  └─ /'
  show "回滚:删本 vhost + 还原后端原 vhost" "rm $VHOST; mv $BAK → $OLD"
  rexec "rm -f '$VHOST'; [ -f '$BAK' ] && mv '$BAK' '$OLD' || true" >/dev/null 2>&1
  printf '  → 已回滚(配置无效,未 reload)\n'
  exit 1
fi

run "reload nginx" rexec "systemctl reload nginx"
printf '\nSPA vhost 部署完成 ✅ —— :%s / → %s(SPA),%s/ → 127.0.0.1:%s(%s);旧 vhost 备份于 %s\n' \
  "$LISTEN" "$FE_ROOT" "$PREFIX" "$PORT" "$BE" "$BAK"
