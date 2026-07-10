#!/usr/bin/env bash
# dpt / edge / preflight —— 校验 edge 模块所有阶段文件齐全。退出 0=齐 / 1=缺。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

section "Preflight —— edge 阶段文件校验"
miss=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  step "$f"
  if [ -f "$ROOT/$f" ]; then ok; else printf 'MISSING\n'; miss=1; fi
done <<'EOF'
lib/common.sh
edge/script/nginx/install_nginx.sh
edge/script/nginx/install_waf.sh
edge/script/nginx/rebuild_modsec.sh
edge/script/nginx/deploy_config.sh
edge/script/nginx/configure_cert.sh
edge/conf/nginx.conf
edge/conf/conf.d/000-placeholder.conf
edge/conf/modsec/main.conf
edge/close/close_check.sh
EOF

if [ "$miss" = 0 ]; then
  printf '\nPreflight OK —— edge 全部就位\n'; exit 0
else
  printf '\nPreflight FAILED —— 有文件缺失(见上面 MISSING)\n'; exit 1
fi
