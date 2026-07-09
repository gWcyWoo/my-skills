#!/usr/bin/env bash
# dpt / system / preflight —— 校验 system 模块所有阶段文件齐全。退出 0=齐 / 1=缺。
# 由 skill 用 Bash 跑(bash shebang,不受调用方 shell 的 word-splitting 影响)。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

section "Preflight —— system 阶段文件校验"
miss=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  step "$f"
  if [ -f "$ROOT/$f" ]; then ok; else printf 'MISSING\n'; miss=1; fi
done <<'EOF'
lib/common.sh
lib/run_checks.sh
system/script/list_fw_ports.sh
system/script/list_listeners.sh
system/script/close_listener.sh
system/script/performance.sh
system/script/upgrade.sh
system/script/security_enhance.sh
system/rule/security_hardening.rules
system/close/close_check.sh
EOF

if [ "$miss" = 0 ]; then
  printf '\nPreflight OK —— system 全部就位\n'; exit 0
else
  printf '\nPreflight FAILED —— 有文件缺失(见上面 MISSING)\n'; exit 1
fi
