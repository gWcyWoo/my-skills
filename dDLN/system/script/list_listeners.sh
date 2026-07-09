#!/usr/bin/env bash
# dpt / system / list_listeners —— 列出所有"对外监听"(非 loopback 绑定)的 TCP 端口,减去允许集
# (SSH 端口 + ufw 已放行端口),输出不在允许集里的【意外对外监听项】,供 Phase S3 逐项问用户是否关闭。
# 输出每行 port|bind|process;无则 NONE。运营 cert + sudo,全只读(ss -tlnp / ufw status)。
# 用法: list_listeners.sh <profile>
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: list_listeners.sh <profile>}"
export DPT_BOOT=sudo

# 允许端口集 = SSH 端口 + ufw 放行端口(仅端口号);逗号连成单行(awk -v 不接受含换行的值)
allowed="$( { rexec "ufw status 2>/dev/null | awk '/ALLOW/{print \$1}'" | sed -E 's#/.*##'; printf '%s\n' "$DPT_PORT"; } | grep -E '^[0-9]+$' | sort -u | paste -sd, -)"

# 原始 TCP 监听(带进程),本地解析(避开远端 awk 转义地狱)
ss_raw="$(rexec "ss -tlnpH 2>/dev/null")"

out="$(printf '%s\n' "$ss_raw" | awk -v allowed="$allowed" '
BEGIN { na=split(allowed, arr, ","); for (i=1;i<=na;i++) if (arr[i]!="") ok[arr[i]]=1 }
{
  la=$4; n=split(la,a,":"); port=a[n];
  bind=la; sub(/:[0-9]+$/,"",bind);
  if (bind ~ /^127\./ || bind=="[::1]") next;     # 127.0.0.0/8 + ::1 环回,只听本机,安全,跳过
  if (port in ok) next;                            # 在允许集(SSH/ufw 放行),跳过
  np=split($0, parts, "\""); proc=(np>=2)?parts[2]:"?";
  print port "|" bind "|" proc;
}' | sort -u)"

if [ -n "$out" ]; then printf '%s\n' "$out"; else echo NONE; fi
