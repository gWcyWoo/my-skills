#!/usr/bin/env bash
# dDP / deploy / build_image —— docker compose build(rootless)。跨境 detached(systemd --user)+ 本地轮询。
# 用法: build_image.sh <profile> <name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: build_image.sh <profile> <name>}"
NAME="${2:?缺 name}"
UNIT="dpt-build-$NAME"

section "构建镜像 $NAME(rootless,systemd --user detached)"
# $UNIT/$NAME 本机展开;\$DOCKER_HOST 用会话内值(rexec_user 已 export);\$HOME 由 bash -lc 远端展开。
run "启动构建(脱离会话)" rexec_user "
  systemctl --user reset-failed $UNIT 2>/dev/null || true
  systemctl --user stop $UNIT 2>/dev/null || true
  systemd-run --user --unit=$UNIT --collect --setenv=DOCKER_HOST=\$DOCKER_HOST \
    bash -lc 'cd \$HOME/dpt-docker-framework/apps/$NAME && docker compose build'
"

printf '等待构建完成(轮询 %s,最多 ~12min)...' "$UNIT"
for i in $(seq 1 144); do
  st="$(rexec_user "systemctl --user show -p ActiveState --value $UNIT 2>/dev/null")"
  case "$st" in inactive|failed) break ;; esac
  sleep 5
done
printf ' done\n'

res="$(rexec_user "systemctl --user show -p Result --value $UNIT 2>/dev/null")"
show "构建结果" "systemctl --user show -p Result $UNIT"
if [ "$res" = "success" ]; then
  printf '  → 实际 %s ✓\n\n构建完成 ✅\n' "$res"
else
  printf '  → 实际 %s ❌\n  └─ 末尾日志:\n' "${res:-未知}"
  rexec_user "journalctl --user -u $UNIT --no-pager -n 40 2>/dev/null" | sed 's/^/     /'
  exit 1
fi
