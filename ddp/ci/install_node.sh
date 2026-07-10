#!/usr/bin/env bash
# dDP / ci / install_node —— 前端工具链:宿主装 Node(NodeSource)。runner 无 docker,
# 不能像特权机那样在 node 容器里 build,故 Vue/Vite 构建直接跑宿主 node/npm。
# rexec(cert+sudo)。跨境长操作 → systemd-run 脱离 + 轮询。一次性、幂等。
# 用法: install_node.sh <profile> <major>   例: install_node.sh negira_home 20
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: install_node.sh <profile> <major>}"
MAJOR="${2:?缺 node 主版本(如 20)}"
UNIT="dpt-ci-node"

section "安装前端工具链(node$MAJOR,detached)"

# 已装且主版本符合 → 幂等跳过
CUR="$(rexec "command -v node >/dev/null 2>&1 && node -v || true" | tr -d 'v' | cut -d. -f1)"
if [ "$CUR" = "$MAJOR" ]; then
  show "node 已装" "node -v"
  printf '  → 实际 v%s ✓(跳过安装)\n' "$(rexec 'node -v' | tr -d 'v')"
  exit 0
fi

run "加 NodeSource 源(node$MAJOR)" rexec "
  set -e
  install -d -m755 /etc/apt/keyrings
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates gnupg >/dev/null 2>&1
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
  echo \"deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${MAJOR}.x nodistro main\" > /etc/apt/sources.list.d/nodesource.list
  test -s /etc/apt/sources.list.d/nodesource.list && grep -q nodesource /etc/apt/sources.list.d/nodesource.list
"

run "启动安装(脱离会话,nodejs $MAJOR.x)" rexec "
  systemctl reset-failed $UNIT 2>/dev/null || true
  systemctl stop $UNIT 2>/dev/null || true
  systemd-run --unit=$UNIT --collect --no-block /bin/bash -c 'exec >/var/log/dpt-ci-node.log 2>&1
    set -e
    DEBIAN_FRONTEND=noninteractive apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs'
"

printf '等待安装完成(轮询 %s,最多 ~12min)...' "$UNIT"
for i in $(seq 1 144); do
  st="$(rexec "systemctl show -p ActiveState --value $UNIT 2>/dev/null")"
  case "$st" in inactive|failed) break ;; esac
  sleep 5
done
printf ' done\n'

res="$(rexec "systemctl show -p Result --value $UNIT 2>/dev/null")"
show "安装结果" "systemctl show -p Result $UNIT"
if [ "$res" = success ]; then
  printf '  → 实际 %s ✓\n' "$res"
else
  printf '  → 实际 %s ❌\n  └─ 末尾日志:\n' "${res:-未知}"
  rexec "tail -30 /var/log/dpt-ci-node.log 2>/dev/null" | sed 's/^/     /'
  exit 1
fi

run "校验 node/npm" rexec "node -v && npm -v"

printf '\n前端工具链安装完成 ✅(node %s)\n' "$(rexec 'node -v' 2>/dev/null | tr -d '\n')"
