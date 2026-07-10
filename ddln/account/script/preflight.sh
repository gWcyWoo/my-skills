#!/usr/bin/env bash
# dpt / account / preflight —— 校验 account 模块所有阶段文件齐全。退出 0=齐 / 1=缺。
# 由 skill 通过终端命令工具跑(bash shebang,不受调用方 shell 的 word-splitting 影响)。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

section "Preflight —— 阶段文件校验"
miss=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  step "$f"
  if [ -f "$ROOT/$f" ]; then ok; else printf 'MISSING\n'; miss=1; fi
done <<'EOF'
lib/common.sh
lib/run_checks.sh
lib/list_profiles.sh
account/script/connect.sh
account/script/import_key.sh
account/script/provision_user.sh
account/script/test_login.sh
account/script/collect_diag.sh
account/script/apply_fix.sh
account/script/harden.sh
account/script/nopasswd_cmd.sh
account/script/disconnect.sh
account/close/close_check.sh
account/rule/ssh_hardening.rules
EOF

if [ "$miss" = 0 ]; then
  printf '\nPreflight OK —— 全部就位\n'; exit 0
else
  printf '\nPreflight FAILED —— 有文件缺失(见上面 MISSING)\n'; exit 1
fi
