#!/usr/bin/env bash
# dpt / system / list_fw_ports —— 列当前 ufw 放行的"额外"端口(去掉强制放行的 SSH 端口),
# 供 Phase S3 给用户做"保持/取消"选择。输出每行一个 spec(如 443/tcp);无额外端口时打印 NONE。
# 运营 cert + sudo。用法: list_fw_ports.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: list_fw_ports.sh <profile>}"
export DPT_BOOT=sudo

cur="$(rexec "ufw status 2>/dev/null | awk '/ALLOW/{print \$1}' | sort -u")"
res="$(printf '%s\n' "$cur" | grep -vE "^${DPT_PORT}(/|\$)" | grep -vE '^$' || true)"
if [ -n "$res" ]; then printf '%s\n' "$res"; else echo NONE; fi
