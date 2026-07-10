#!/usr/bin/env bash
# dDP / check / login —— 探运营用户证书登录(部署前置门)。退出 0=通 / 1=不通。
# 不通 = 连不上服务器,后续 nginx/docker 检查无意义 → 由 SKILL.md 据此停(指向 dDLN account)。
# 失败时吐 ssh 客户端关键行。只查、不改。用法: login.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: login.sh <profile>}"

ERR="$(mktemp 2>/dev/null || echo /tmp/ddp_login_err.$$)"
show "证书登录探测 ($DPT_USER@$DPT_HOST:$DPT_PORT)" "ssh -o BatchMode=yes -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST true"
if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
       -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" true 2>"$ERR"; then
  printf '  → done\n'
  rm -f "$ERR"
  exit 0
else
  printf '  → FAILED\n'
  tail -5 "$ERR" | sed 's/^/  └─ /'
  rm -f "$ERR"
  exit 1
fi
