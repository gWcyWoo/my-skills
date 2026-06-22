#!/usr/bin/env bash
# dpt / account / harden —— SSH 安全加固(确定性协议)。
# 套规则 → 单一 drop-in → sshd -t → reload → 全新连接验证 → 失败回滚(防锁死)。
# root 引导连接全程不断,作回滚生命线。用法: harden.sh <profile> [new-port]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: harden.sh <profile> [new-port]}"
NEWPORT="${2:-}"
export DPT_BOOT=root

section "SSH 安全加固(CIS 5.2 + Mozilla)"
EFFPORT="$DPT_PORT"

run "初始化加固 drop-in(可整体回滚)" rexec "
     install -m600 -o root -g root /dev/null '$DPT_DROPIN'
     printf '# dpt hardening (managed). Remove this file to roll back.\n' > '$DPT_DROPIN'"

if [ -n "$NEWPORT" ]; then
  run "写入新端口 $NEWPORT" rexec "echo 'Port $NEWPORT' >> '$DPT_DROPIN'"
  open_firewall "$NEWPORT"
  EFFPORT="$NEWPORT"
fi

printf '\n## 加固规则(逐条 check → stage 进 drop-in)\n'
bash "$ROOT/lib/run_checks.sh" --fix "$ROOT/account/rule/ssh_hardening.rules" || fail "加固规则执行失败"

printf '\n## 生效与验证\n'
run "校验 sshd 配置 (sshd -t)" rexec "sshd -t"
run "reload sshd(不断现有会话)" rexec "systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload"

show "验证加固后证书登录(端口 $EFFPORT)" "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i $DPT_KEY -p $EFFPORT $DPT_USER@$DPT_HOST true"
if VERR="$(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -i "$DPT_KEY" -p "$EFFPORT" "$DPT_USER@$DPT_HOST" true 2>&1)"; then
  printf '  → done\n'
else
  printf '  → FAILED\n'
  [ -n "$VERR" ] && printf '%s\n' "$VERR" | sed 's/^/  └─ /'
  rexec "rm -f '$DPT_DROPIN'; systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload 2>/dev/null" >/dev/null 2>&1
  printf '  └─ 加固后新连接失败,已回滚 drop-in 并 reload。\n'
  printf '  └─ 常见原因:云安全组未放行端口 %s,或 AllowUsers 把 %s 排除了。\n' "$EFFPORT" "$DPT_USER"
  exit 1
fi

# 端口若变了,更新 conf 供后续脚本/收尾使用
if [ "$EFFPORT" != "$DPT_PORT" ]; then
  sed -i.bak "s/^export DPT_PORT=.*/export DPT_PORT='$EFFPORT'/" "$DPT_DIR/dpt.conf" && rm -f "$DPT_DIR/dpt.conf.bak"
  note "端口已更新到配置:$EFFPORT"
fi

section "加固完成"
printf '生效端口: %s\n' "$EFFPORT"
