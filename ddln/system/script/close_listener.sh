#!/usr/bin/env bash
# dpt / system / close_listener —— 关闭一个"意外对外监听"服务(Phase S3 用户逐项确认后由技能执行)。
# 运营 cert + sudo。用法: close_listener.sh <profile> <mode> [arg]
#   postfix-loopback     : Postfix 绑 loopback-only(仍能发件、不再对外监听) + restart
#   stop-unit <unit>     : systemctl disable --now <unit>(彻底停该服务)
#   resolved-llmnr-off   : systemd-resolved 关 LLMNR + MulticastDNS(drop-in)+ restart
# 复核由 SKILL 重跑 list_listeners.sh 判"该项已消失"。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: close_listener.sh <profile> <mode> [arg]}"
MODE="${2:?缺 mode(postfix-loopback|stop-unit|resolved-llmnr-off)}"
ARG="${3:-}"
export DPT_BOOT=sudo

section "关闭对外监听: $MODE ${ARG:+($ARG)}"

case "$MODE" in
  postfix-loopback)
    run "Postfix 绑 loopback-only(仍发件,不再对外)" rexec "postconf -e 'inet_interfaces = loopback-only'"
    run "重启 postfix" rexec "systemctl restart postfix"
    run "确认 postfix 存活" rexec "systemctl is-active postfix >/dev/null"
    ;;
  stop-unit)
    [ -n "$ARG" ] || fail "stop-unit 需要 <unit> 参数"
    run "停用 + 禁用 $ARG" rexec "systemctl disable --now '$ARG'"
    run "确认 $ARG 已停" rexec "! systemctl is-active '$ARG' >/dev/null 2>&1"
    ;;
  resolved-llmnr-off)
    run "写 drop-in:LLMNR=no / MulticastDNS=no" rexec "install -d -m755 /etc/systemd/resolved.conf.d && printf '[Resolve]\nLLMNR=no\nMulticastDNS=no\n' > /etc/systemd/resolved.conf.d/50-dpt-no-llmnr.conf && grep -q LLMNR /etc/systemd/resolved.conf.d/50-dpt-no-llmnr.conf"
    run "重启 systemd-resolved" rexec "systemctl restart systemd-resolved"
    ;;
  *) fail "未知 mode: $MODE(支持 postfix-loopback | stop-unit <unit> | resolved-llmnr-off)";;
esac

section "关闭动作已执行 —— 请重跑 list_listeners.sh <profile> 复核该端口已从对外监听消失"
