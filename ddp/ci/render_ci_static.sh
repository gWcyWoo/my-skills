#!/usr/bin/env bash
# dDP / ci / render_ci_static —— 渲染【静态前端仓库】的 .gitlab-ci.yml,写到本地文件供你复制。
# 模型:宿主 node 直编(npm ci + vite build,runner 无 docker)→ rsync dist(即时生效,无 reload)
#      → 健康检查(前端 / + 同源 api 前缀探后端)→ 失败回滚上一版 dist。
# 健康 URL / api 前缀自动从该 profile 服务器的 SPA vhost(conf.d/<fe>.conf)探测。
# 用法: render_ci_static.sh <profile> <fe_name> <branch> [tag] [build_script]
#   build_script 默认按分支推导:master/main→build:prod、test→build:test、其余→build
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: render_ci_static.sh <profile> <fe_name> <branch> [tag] [build_script]}"
FE="${2:?缺 fe_name}"; BRANCH="${3:?缺 branch}"

case "$BRANCH" in
  master|main|prod|production) ENV=prod;    MODE=production; BS_DEF=build:prod;;
  test|testing)                ENV=test;    MODE=test;       BS_DEF=build:test;;
  stag*|uat)                   ENV=staging; MODE=staging;    BS_DEF=build;;
  dev|develop|development)     ENV=dev;     MODE=development;BS_DEF=build;;
  *)                           ENV="$BRANCH"; MODE="$BRANCH"; BS_DEF=build;;
esac
TAG="${4:-${FE}-${ENV}-deploy}"
BS="${5:-$BS_DEF}"

HOME_DIR="$(rexec_user 'printf %s "$HOME"')"; [ -n "$HOME_DIR" ] || fail "无法解析家目录"
APP_DIR="$HOME_DIR/dpt-docker-framework/apps/$FE"

# 从 SPA vhost 探测 listen 端口/scheme/api 前缀
VCONF="/etc/nginx/conf.d/$FE.conf"
LISTEN_LINE="$(rexec "grep -m1 -E '^[[:space:]]*listen[[:space:]]+[0-9]' $VCONF 2>/dev/null")"
LPORT="$(printf '%s' "$LISTEN_LINE" | sed -n 's/.*listen[[:space:]]\{1,\}\([0-9]\{1,\}\).*/\1/p')"
[ -n "$LPORT" ] || fail "无法从 $VCONF 探测 listen 端口(先跑 spa_vhost.sh)"
if printf '%s' "$LISTEN_LINE" | grep -q ssl; then SCHEME=https; else SCHEME=http; fi
HEALTH_URL="$SCHEME://127.0.0.1:$LPORT/"
PREFIX="$(rexec "grep -m1 -oE '^[[:space:]]*location [^ ]+/ \{' $VCONF 2>/dev/null | grep -v ' / ' | sed 's/[[:space:]]*location //; s|/ {||'")"
[ -n "$PREFIX" ] || PREFIX=/api

JOB="$(printf '%s' "$BRANCH" | tr -c 'A-Za-z0-9_' '_')"
OUTDIR="./audit/ci"; OUT="$OUTDIR/$FE.gitlab-ci.yml"; mkdir -p "$OUTDIR"

section "渲染前端 .gitlab-ci.yml($FE,分支 $BRANCH,健康 $HEALTH_URL + $PREFIX/,构建 npm run $BS,tag $TAG)"
sed -e "s|__NAME__|$FE|g" -e "s|__BRANCH__|$BRANCH|g" -e "s|__JOB__|$JOB|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__TAG__|$TAG|g" -e "s|__MODE__|$MODE|g" \
    -e "s|__BUILD_CMD__|npm run $BS|g" -e "s|__HEALTH_URL__|$HEALTH_URL|g" \
    -e "s|__API_PREFIX__|$PREFIX|g" \
    "$ROOT/ci/templates/gitlab-ci.static.tmpl" > "$OUT"

ABS="$(cd "$OUTDIR" && pwd)/$FE.gitlab-ci.yml"
printf '\n已生成前端 CI 到:\n  %s\n共 %s 行,分支 %s,runner tag %s\n' "$ABS" "$(wc -l < "$OUT" | tr -d ' ')" "$BRANCH" "$TAG"
printf '下一步:整段复制进【前端仓库】根 .gitlab-ci.yml 提交;GitLab 给前端仓库建 runner(tag=%s,取消 untagged)。\n' "$TAG"
