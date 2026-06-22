#!/usr/bin/env bash
# dpt / docker / preflight —— 校验 docker 模块所有阶段文件齐全。退出 0=齐 / 1=缺。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

section "Preflight —— docker 阶段文件校验"
miss=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  step "$f"
  if [ -f "$ROOT/$f" ]; then ok; else printf 'MISSING\n'; miss=1; fi
done <<'EOF'
lib/common.sh
docker/script/install_docker.sh
docker/script/setup_rootless.sh
docker/script/deploy_framework.sh
docker/conf/daemon.json
docker/conf/compose.skeleton.yaml
docker/conf/FRAMEWORK.md
docker/close/close_check.sh
EOF

if [ "$miss" = 0 ]; then
  printf '\nPreflight OK —— docker 全部就位\n'; exit 0
else
  printf '\nPreflight FAILED —— 有文件缺失(见上面 MISSING)\n'; exit 1
fi
