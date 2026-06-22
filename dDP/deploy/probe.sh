#!/usr/bin/env bash
# dDP / deploy / probe —— 探测「下一个空闲 127.0.0.1 端口(9000-9099)」+「按内存建议的 pm.max_children」。
# 只读、不改。供 SKILL 展示给用户确认后再 scaffold。末行 `PROBE port=.. max_children=..` 供解析。
# 用法: probe.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: probe.sh <profile>}"

section "探测部署参数(只读)"

# 已占端口:本机监听中的 + 已有 app compose 映射的(都取 127.0.0.1: 后的首个端口号)
taken="$(rexec_user 'ss -ltnH 2>/dev/null | grep -oE "127\.0\.0\.1:[0-9]+"; grep -rhoE "127\.0\.0\.1:[0-9]+:9000" "$HOME"/dpt-docker-framework/apps/*/compose.yaml 2>/dev/null')"
takenports="$(printf '%s\n' "$taken" | sed -n 's/^127\.0\.0\.1:\([0-9][0-9]*\).*/\1/p' | sort -un)"
port=""
for p in $(seq 9000 9099); do
  printf '%s\n' "$takenports" | grep -qx "$p" || { port="$p"; break; }
done
show "下一个空闲端口(9000-9099)" "ss -ltn + 扫 apps/*/compose.yaml"
printf '  → %s\n' "${port:-无空闲}"

# 建议资源:按物理内存自洽推导「容器内存上限 + pm.max_children」(算法见 lib/common.sh)。
# 新建 app,不排除任何已有 app —— 它们的内存承诺都计入 COMMITTED。
calc="$(dpt_calc_resources)"
mem="$(printf '%s\n' "$calc" | sed -n 's/.* mem=\([0-9]*m\) .*/\1/p')"
mc="$(printf '%s\n' "$calc" | sed -n 's/.* max_children=\([0-9]*\).*/\1/p')"
show "建议容器内存 / pm.max_children" "MemTotal 扣预留与其它 app 承诺 → 一个预算驱动两者(不会 OOM)"
printf '  → %s\n' "$calc"

printf '\nPROBE port=%s mem=%s max_children=%s\n' "${port:-}" "${mem}" "${mc}"
