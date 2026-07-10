#!/usr/bin/env bash
# dDP / deploy / scaffold_static —— 静态前端 app 脚手架:apps/<fe>/{dist,.env}。
# .env 存服务器侧构建时事实(VITE_API_BASE_URL=同源 api 前缀),CI 构建前拷进 checkout(仿 ntest 模式)。
# dist 先放占位 index.html(nginx/健康检查可用,真身待 CI 交付)。rexec_user(opt,不 sudo)。幂等。
# 用法: scaffold_static.sh <profile> <fe_name> [api_prefix=/api]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: scaffold_static.sh <profile> <fe_name> [api_prefix]}"
FE="${2:?缺 fe_name}"; PREFIX="${3:-/api}"
APP='$HOME/dpt-docker-framework/apps/'"$FE"

section "scaffold 静态前端 apps/$FE(VITE_API_BASE_URL=$PREFIX)"

run "建 dist/ 目录" rexec_user "mkdir -p $APP/dist"

show "写 .env(构建时注入,已存在则保留)" "cat > $APP/.env(VITE_API_BASE_URL=$PREFIX)"
if rexec_user "[ -f $APP/.env ] || printf 'VITE_API_BASE_URL=%s\nVITE_PUBLIC_PATH=/\n' '$PREFIX' > $APP/.env; grep -q VITE_API_BASE_URL $APP/.env"; then
  printf '  → done(%s)\n' "$(rexec_user "grep ^VITE_API_BASE_URL= $APP/.env")"
else fail "写 .env 失败"; fi

show "占位 index.html(dist 空时才写)" "cat > $APP/dist/index.html"
if rexec_user "[ -f $APP/dist/index.html ] || printf '<!doctype html><title>$FE</title><p>$FE placeholder — awaiting CI delivery</p>\n' > $APP/dist/index.html"; then
  printf '  → done\n'
else fail "写占位 index.html 失败"; fi

printf '\nscaffold 完成 ✅ —— apps/%s 就绪(dist 占位,待 CI 交付;.env 供 CI 构建时拷入)\n' "$FE"
