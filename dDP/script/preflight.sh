#!/usr/bin/env bash
# dDP / preflight —— 校验阶段文件齐全(Claude 用 Bash 跑)。在「你的本机」执行。
# 阶段文件随后续步骤增长;当前只实现「列出并选择 profile」这一步。
# 用法: preflight.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

printf '# Preflight —— dDP 阶段文件校验\n'
miss=0
for f in \
  lib/common.sh \
  lib/list_profiles.sh \
  check/login.sh \
  check/nginx.sh \
  check/docker.sh \
  deploy/probe.sh \
  deploy/scaffold_app.sh \
  deploy/build_image.sh \
  deploy/up.sh \
  deploy/nginx_vhost.sh \
  deploy/templates/Dockerfile.tmpl \
  deploy/templates/php.ini \
  deploy/templates/www.conf.tmpl \
  deploy/templates/compose.yaml.tmpl \
  deploy/templates/vhost.conf.tmpl \
  ci/install_toolchain.sh \
  ci/provision_runner.sh \
  ci/cage_app.sh \
  ci/render_ci.sh \
  ci/register_cmd.sh \
  ci/set_env.sh \
  ci/templates/gitlab-ci.header.tmpl \
  ci/templates/gitlab-ci.branch.tmpl \
  ci/templates/reload-on-trigger.sh \
  ci/templates/reload-listener.path.tmpl \
  ci/templates/reload-listener.service.tmpl \
; do
  if [ -f "$ROOT/$f" ]; then
    printf '%s... done\n' "$f"
  else
    printf '%s... MISSING\n' "$f"
    miss=1
  fi
done

if [ "$miss" = 1 ]; then
  printf '\nPreflight FAILED —— 有缺失文件\n'
  exit 1
fi
printf '\nPreflight OK —— dDP 全部就位\n'
