#!/usr/bin/env bash
# dpt / account / test_login —— 探运营用户证书登录。退出 0=通 / 1=不通。
# 失败时吐 ssh 客户端关键错误行,供 skill 判断。用法: test_login.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: test_login.sh <profile>}"

ERR="$(mktemp 2>/dev/null || echo /tmp/dpt_login_err.$$)"
show "测试证书登录 ($DPT_USER@$DPT_HOST:$DPT_PORT)" "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST true"
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
