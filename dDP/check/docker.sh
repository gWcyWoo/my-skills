#!/usr/bin/env bash
# dDP / check / docker —— 部署前 rootless Docker 环境就绪检查(**只查,不修**)。
# 混合:宿主侧 [root] 走 rexec(sudo),用户态 [opt] 走 rexec_user(以运营用户、不 sudo)。
# 跑满全部检查、不短路;末尾列出所有缺失项。退出 0=全就绪 / 1=有缺失。
# 缺失须由 dDLN docker 模块补齐;dDP 不安装。用法: docker.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: docker.sh <profile>}"

MISS=()
chk_r() { show "$1" "[root] $2"; if rexec      "$2" >/dev/null 2>&1; then printf '  → ✓\n'; else printf '  → ✗ 缺失\n'; MISS+=("$1"); fi; }
chk_u() { show "$1" "[opt]  $2"; if rexec_user "$2" >/dev/null 2>&1; then printf '  → ✓\n'; else printf '  → ✗ 缺失\n'; MISS+=("$1"); fi; }

section "rootless Docker 环境就绪检查(只查)"

printf '## 安装与隔离形态\n'
chk_u "docker CLI 可用(以 opt)"           "command -v docker >/dev/null"
chk_u "rootless daemon 运行(docker info)"  "docker info >/dev/null 2>&1"
chk_u "确为 rootless"                       "docker info 2>/dev/null | grep -qi rootless"
chk_r "rootful 守护已禁/mask"               "systemctl is-enabled docker.service 2>/dev/null | grep -qE 'masked|disabled' || ! systemctl is-active docker.service >/dev/null 2>&1"
chk_r "lingering 已开"                      "loginctl show-user $DPT_USER -p Linger --value 2>/dev/null | grep -q yes"
chk_r "subuid 含 $DPT_USER"                 "grep -q '^$DPT_USER:' /etc/subuid"
chk_r "subgid 含 $DPT_USER"                 "grep -q '^$DPT_USER:' /etc/subgid"
chk_r "userns 可用(rootless 依赖)"         "v=\$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || echo 1); [ \"\$v\" = 1 ]"

printf '\n## compose / 加固 daemon.json\n'
chk_u "docker compose v2 可用"              "docker compose version >/dev/null 2>&1"
chk_u "daemon.json journald 日志"           "grep -q 'journald' \$HOME/.config/docker/daemon.json"
chk_u "daemon.json no-new-privileges"       "grep -q 'no-new-privileges' \$HOME/.config/docker/daemon.json"

printf '\n## 框架交付物\n'
chk_u "FRAMEWORK.md 在位"                    "test -f \$HOME/dpt-docker-framework/FRAMEWORK.md"
chk_u "compose 骨架在位"                     "test -f \$HOME/dpt-docker-framework/compose.skeleton.yaml"

printf '\n'
if [ "${#MISS[@]}" -eq 0 ]; then
  printf 'docker 环境就绪 ✅ —— 全部检查通过\n'
  exit 0
else
  printf 'docker 环境未就绪 ❌ —— 缺失/不合规 %d 项(须由 dDLN docker 模块补齐):\n' "${#MISS[@]}"
  for m in "${MISS[@]}"; do printf '  - %s\n' "$m"; done
  exit 1
fi
