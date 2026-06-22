#!/usr/bin/env bash
# dDC —— Docker 项目服务器【只读】安全/性能/可用性检查。复用 dDLN/dDP 的 profile(cert-only,绝不 root/密码)。
# 【硬边界·无豁免】对被审服务器只发只读命令,绝不修改/创建/删除。唯一写动作=本地审计日志(规定产物)。
# 每项打印  检查项(检查目的)-----success|fail(fail 附原因),并整体记入 ./audit/check/<profile>_<date>.log。
# 用法(在【项目根目录】下运行,以便日志落到该项目的 ./audit/check/): dDC.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/lib/checks.sh"
dpt_load "${1:?用法: dDC.sh <profile>(在项目根目录运行;日志写 ./audit/check/<profile>_<date>.log)}"

DATE="$(date +%Y%m%d)"
LOGDIR="./audit/check"
mkdir -p "$LOGDIR"                       # 本地审计产物(需求3);非对被审服务器的修改 → 不违反"只读"边界
LOG="$LOGDIR/${DPT_PROFILE}_${DATE}.log"

run_all() {
  printf 'dDC 只读检查 —— profile=%s  目标=%s@%s:%s  时间=%s\n' \
    "$DPT_PROFILE" "$DPT_USER" "$DPT_HOST" "$DPT_PORT" "$(date '+%F %T')"
  printf '边界:仅对服务器发只读命令(读取/查询/校验/GET),绝不修改/创建/删除(无豁免)。\n'

  dDC_ssh
  dDC_user
  dDC_firewall
  dDC_system
  dDC_docker

  apps="$(dDC_apps)"
  if [ -z "$apps" ]; then
    section "应用"
    printf '未发现已部署 app(~/dpt-docker-framework/apps 为空)—— 跳过容器/PHP/可用性检查。\n'
  else
    for app in $apps; do
      dDC_container  "$app"
      dDC_php        "$app"
      dDC_availability "$app"
    done
  fi
  dDC_nginx

  printf '\n========== 汇总 ==========\n'
  printf '通过 %s,失败 %s,共 %s 项\n' "$DDC_PASS" "$DDC_FAIL" "$((DDC_PASS + DDC_FAIL))"
  if [ "$DDC_FAIL" -eq 0 ]; then
    printf '结论:全部通过 ✅\n'
  else
    printf '结论:%s 项需关注(见上各 fail 原因)❗\n' "$DDC_FAIL"
  fi
}

run_all 2>&1 | tee "$LOG"
printf '\n[dDC] 审计日志已写入: %s\n' "$LOG"
