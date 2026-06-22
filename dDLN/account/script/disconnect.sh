#!/usr/bin/env bash
# dpt / account / disconnect —— 关闭 root 引导 ControlMaster 连接。用法: disconnect.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: disconnect.sh <profile>}"

step "关闭 root 引导连接"
ssh -O exit -o ControlPath="$DPT_CTRL" "root@$DPT_HOST" 2>/dev/null
ok
