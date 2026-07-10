#!/usr/bin/env bash
# dpt / account / import_key —— 复用现有 ops 证书(私钥):拷进 profile 目录,供 provision 复用(不再新建)。
# 在 Phase 0 选「复用」后、connect 之前由 skill 通过终端命令工具跑(纯本地操作,不连服务器)。
# 用法: import_key.sh <profile> <user> <src-私钥路径>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

PROFILE="${1:?用法: import_key.sh <profile> <user> <src-私钥路径>}"
USER_="${2:?缺少 user}"
SRC="${3:?缺少源私钥路径}"
DIR="$HOME/.ssh/$PROFILE"
DEST="$DIR/${USER_}_ed25519"

section "复用证书 → profile $PROFILE"
[ -f "$SRC" ] || fail "源私钥不存在: $SRC"

run "建 profile 目录(700)" install -d -m700 "$DIR"
run "拷私钥(600)" install -m600 "$SRC" "$DEST"
if [ -f "$SRC.pub" ]; then
  run "拷公钥(644)" install -m644 "$SRC.pub" "$DEST.pub"
else
  show "源无 .pub,从私钥派生公钥" "ssh-keygen -y -f $SRC > $DEST.pub"
  if ssh-keygen -y -f "$SRC" > "$DEST.pub" 2>/dev/null; then chmod 644 "$DEST.pub"; printf '  → done\n'
  else fail "派生公钥失败(私钥可能带口令?请同时提供 $SRC.pub)"; fi
fi
run "校验落盘" test -f "$DEST" -a -f "$DEST.pub"

section "证书已复用到 $DEST —— connect 后 provision 将复用,不再新建"
