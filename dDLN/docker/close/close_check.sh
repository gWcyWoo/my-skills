#!/usr/bin/env bash
# dpt / docker / close —— rootless Docker 环境收尾审计(只查)。
# 混合:root 检查走 rexec(sudo),用户态检查走 rexec_user(以 opt)。用法: close_check.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: close_check.sh <profile>}"
export DPT_BOOT=sudo

FAILED=0
ynr() { show "$1" "[root] $2"; if rexec      "$2" >/dev/null 2>&1; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi; }
ynu() { show "$1" "[opt]  $2"; if rexec_user "$2" >/dev/null 2>&1; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi; }

section "Docker rootless 环境收尾检查"

printf '## 安装与隔离形态\n'
ynu "docker CLI 可用(以 opt)" "command -v docker >/dev/null"
ynu "rootless daemon 运行(docker info)" "docker info >/dev/null 2>&1"
ynu "确为 rootless" "docker info 2>/dev/null | grep -qi rootless"
ynr "rootful 守护已禁/mask" "systemctl is-enabled docker.service 2>/dev/null | grep -qE 'masked|disabled' || ! systemctl is-active docker.service >/dev/null 2>&1"
ynr "lingering 已开" "loginctl show-user $DPT_USER -p Linger --value 2>/dev/null | grep -q yes"
ynr "subuid 含 $DPT_USER" "grep -q '^$DPT_USER:' /etc/subuid"
ynr "subgid 含 $DPT_USER" "grep -q '^$DPT_USER:' /etc/subgid"
ynr "userns 可用(rootless 依赖)" "v=\$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || echo 1); [ \"\$v\" = 1 ]"

printf '\n## compose / 加固 daemon.json\n'
ynu "docker compose v2 可用" "docker compose version >/dev/null 2>&1"
ynu "daemon.json journald 日志" "grep -q 'journald' \$HOME/.config/docker/daemon.json"
ynu "daemon.json no-new-privileges" "grep -q 'no-new-privileges' \$HOME/.config/docker/daemon.json"

printf '\n## 框架交付物\n'
ynu "FRAMEWORK.md 在位" "test -f \$HOME/dpt-docker-framework/FRAMEWORK.md"
ynu "compose 骨架在位" "test -f \$HOME/dpt-docker-framework/compose.skeleton.yaml"

printf '\n'
if [ "$FAILED" -eq 0 ]; then printf 'Docker 环境收尾检查全部通过 ✅\n'; exit 0
else printf 'Docker 环境收尾检查存在未通过项 ❌(见上面 FAILED)\n'; exit 1; fi
