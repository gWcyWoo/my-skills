#!/usr/bin/env bash
# dDP / deploy / scaffold_app —— 生成 apps/<name>/{src, deploy/{Dockerfile,php.ini,www.conf}, compose.yaml}。
# 全程 rexec_user(运营用户,不 sudo)。容器内安全+性能配置在此(先于 nginx)。幂等:重跑覆盖配置、保留 src。
# 用法: scaffold_app.sh <profile> <name> <phpver> <port> <max_children> <mem_limit>
#   <mem_limit> 形如 2680m —— 与 <max_children> 由 probe 的同一内存预算自洽得出(见 lib/common.sh)。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: scaffold_app.sh <profile> <name> <phpver> <port> <max_children> <mem_limit>}"
NAME="${2:?缺 name}"; VER="${3:?缺 phpver}"; PORT="${4:?缺 port}"; MC="${5:?缺 max_children}"; MEM="${6:?缺 mem_limit}"
TPL="$ROOT/deploy/templates"

# php 基础镜像 suite:7.x → bullseye(7.4 仅 bullseye),8.x+ → bookworm
case "$VER" in
  7.*) SUITE=bullseye ;;
  *)   SUITE=bookworm ;;
esac
VERTAG="$(printf '%s' "$VER" | tr -d '.')"      # 7.4 → 74(镜像 tag 用)
# pm 衍生值(由 max_children 推)
START=$(( MC / 4 )); [ "$START" -lt 2 ] && START=2
MINSP=$(( MC / 8 )); [ "$MINSP" -lt 1 ] && MINSP=1
MAXSP=$(( MC / 2 )); [ "$MAXSP" -lt 4 ] && MAXSP=4

render() {
  sed -e "s|__NAME__|$NAME|g" -e "s|__PHP_VER__|$VER|g" -e "s|__PHP_VERTAG__|$VERTAG|g" \
      -e "s|__SUITE__|$SUITE|g" -e "s|__PORT__|$PORT|g" -e "s|__MEM_LIMIT__|$MEM|g" \
      -e "s|__MAX_CHILDREN__|$MC|g" -e "s|__START_SERVERS__|$START|g" \
      -e "s|__MIN_SPARE__|$MINSP|g" -e "s|__MAX_SPARE__|$MAXSP|g" "$1"
}

APP='$HOME/dpt-docker-framework/apps/'"$NAME"   # $HOME 远端展开

section "scaffold apps/$NAME(php $VER/$SUITE,端口 $PORT,内存 $MEM,pm.max_children $MC)"
# 增建 src/runtime:只读 src 绑定需先有此目录,runtime 卷才能叠挂其上(仅作挂载点,被卷遮蔽)。
run "建目录 src/runtime deploy/" rexec_user "mkdir -p $APP/src/runtime $APP/deploy"

# put <模板文件名> <APP 下相对路径>
put() {
  show "写 $2" "cat > $APP/$2"
  if render "$TPL/$1" | rexec_user_in "cat > $APP/$2"; then printf '  → done\n'; else fail "写 $2 失败"; fi
}
put Dockerfile.tmpl    deploy/Dockerfile
put php.ini            deploy/php.ini
put www.conf.tmpl      deploy/www.conf
put compose.yaml.tmpl  compose.yaml

printf '\nscaffold 完成 ✅ —— apps/%s 就绪(src 空,待 CI 交付代码)\n' "$NAME"
