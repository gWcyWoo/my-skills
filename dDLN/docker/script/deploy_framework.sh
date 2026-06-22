#!/usr/bin/env bash
# dpt / docker / deploy_framework —— 把框架约束文档 + 安全 compose 骨架放到 opt 家目录,供后续容器 skill 套用。
# 运营 cert(不 sudo,走 rexec_user)。用法: deploy_framework.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: deploy_framework.sh <profile>}"

section "部署 Docker 框架(约束 + compose 骨架 → ~/dpt-docker-framework/)"

run "建框架目录" rexec_user "install -d -m755 \$HOME/dpt-docker-framework"
for f in FRAMEWORK.md compose.skeleton.yaml; do
  show "部署 ~/dpt-docker-framework/$f" "cat > dpt-docker-framework/$f ← docker/conf/$f"
  if rexec_user_in "cat > dpt-docker-framework/$f" < "$ROOT/docker/conf/$f"; then printf '  → done\n'
  else fail "部署 $f 失败"; fi
done

section "Docker 框架部署完成(后续容器 skill 基于 ~/dpt-docker-framework/ 加业务)"
