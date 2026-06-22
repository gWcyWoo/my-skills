#!/usr/bin/env bash
# dpt / account / close —— 收尾检查:功能正确性 + 安全性(只查不改)。
# 用运营用户证书 + sudo 复连(顺带验证「证书 + sudo」这条功能路径)。用法: close_check.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: close_check.sh <profile>}"
export DPT_BOOT=sudo

section "收尾检查(功能正确性 + 安全性)"
FAILED=0
chk() {
  local l="$1"; shift
  show "$l" "$*"                                  # 回显被检命令(脱敏),失败可审计
  local out
  if out="$("$@" 2>&1)"; then printf '  → done\n'
  else printf '  → FAILED\n'; [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/  └─ /'; FAILED=1; fi
}

printf '## 功能正确性\n'
chk "证书登录可用" ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" true
chk "NOPASSWD sudo 可用" rexec "true"
chk "运营用户存在" rexec "id -u '$DPT_USER'"
show "本地私钥存在" "test -f $DPT_KEY"; if [ -f "$DPT_KEY" ]; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi
show "本地密码文件存在 (600)" "test -f $DPT_PWFILE"; if [ -f "$DPT_PWFILE" ]; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi

printf '\n## 安全性(CIS 5.2 + Mozilla,逐条只查)\n'
bash "$ROOT/lib/run_checks.sh" --check "$ROOT/account/rule/ssh_hardening.rules" || FAILED=1

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf '收尾检查全部通过 ✅\n'; exit 0
else
  printf '收尾检查存在未通过项 ❌(见上面 FAILED 行)\n'; exit 1
fi
