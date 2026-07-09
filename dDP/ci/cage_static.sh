#!/usr/bin/env bash
# dDP / ci / cage_static —— 静态前端权限笼:gitlab-runner 只能写 apps/<fe>/dist、只读 apps/<fe>/.env
# (CI 构建前拷 .env 进 checkout 注入 VITE_*,非机密级别但仍最小权限)。祖先仅 x(可穿不可枚举)。
# 静态文件 nginx 直读磁盘,rsync 即生效 → 无 USR2/reload 监听。rexec(cert+sudo)。幂等。
# 用法: cage_static.sh <profile> <fe_name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: cage_static.sh <profile> <fe_name>}"
FE="${2:?缺 fe_name}"

HOME_DIR="$(rexec_user 'printf %s "$HOME"')"
[ -n "$HOME_DIR" ] || fail "无法解析运营用户家目录"
APP="$HOME_DIR/dpt-docker-framework/apps/$FE"

section "静态前端权限笼: $FE"

run "祖先链仅 x(可穿不可枚举)" rexec "
  set -e
  setfacl -m u:gitlab-runner:x '$HOME_DIR' '$HOME_DIR/dpt-docker-framework' '$HOME_DIR/dpt-docker-framework/apps' '$APP'
"

run "dist 给 gitlab-runner rwX(含默认 ACL)" rexec "
  set -e
  setfacl -R -m  u:gitlab-runner:rwX '$APP/dist'
  setfacl -R -d -m u:gitlab-runner:rwX '$APP/dist'
"

run ".env 给 gitlab-runner 只读(构建时拷入注入 VITE_*)" rexec "
  set -e
  test -f '$APP/.env'
  setfacl -m u:gitlab-runner:r-- '$APP/.env'
"

run "校验:runner 可读 .env、可写 dist" rexec "
  sudo -u gitlab-runner test -r '$APP/.env'
  sudo -u gitlab-runner touch '$APP/dist/.acl-probe' && sudo -u gitlab-runner rm '$APP/dist/.acl-probe'
"

printf '\n权限笼完成 ✅(runner:dist 可写、.env 只读、祖先仅穿行;无 reload 监听——静态即时生效)\n'
