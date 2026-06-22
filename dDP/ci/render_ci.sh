#!/usr/bin/env bash
# dDP / ci / render_ci —— 16b:渲染 rootless .gitlab-ci.yml,写到【本地文件】供你打开复制(dDP 不落服务器、不进仓库)。
# 终端代码块易乱/被折叠,故产物落地为本地文件:./audit/ci/<name>.gitlab-ci.yml(相对当前工作目录;请在项目根运行)。
# 模型:runner 无 docker/无 sudo;composer 宿主直编 → rsync 进 src(留 .env/runtime)→ USR2 优雅 reload → 轮询健康 → 失败回滚。
#       镜像重建不在 CI(由 dDP build_image,因 runner 无 docker)。
# 多分支:每分支一组 build_<branch>/deploy_<branch>(共用隐藏基),共存于同一文件。
#   - 首个分支(默认 full):生成整段文件(头部 + 隐藏基 + 该分支块),覆盖写。
#   - 再加分支(--append):把该分支块【追加】到同一文件末尾(异机/异 profile 也用它)。
# 域名自动从该 profile 服务器的 nginx vhost 探测;runner tag 区分不同服务器(test/prod)。
# 用法: render_ci.sh <profile> <name> <branch> [tag] [--append]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: render_ci.sh <profile> <name> <branch> [tag] [--append]}"
NAME="${2:?缺 name}"; BRANCH="${3:?缺 branch}"; MODE="${5:-full}"
# env 从分支推导(可被第4参显式 tag 覆盖):master/main→prod、test→test、staging/uat→staging、dev→dev,其余=分支名。
case "$BRANCH" in
  master|main|prod|production) ENV=prod;;
  test|testing)                ENV=test;;
  stag*|uat)                   ENV=staging;;
  dev|develop|development)     ENV=dev;;
  *)                           ENV="$BRANCH";;
esac
# 默认 tag = <app>-<env>-deploy(唯一命名规范):共享 GitLab 上用通用 tag(如 deploy)会被别的 runner 抢走任务。
DEFAULT_TAG="${NAME}-${ENV}-deploy"
TAG="${4:-$DEFAULT_TAG}"
case "$TAG" in --append) TAG="$DEFAULT_TAG"; MODE=--append;; esac   # 省略 tag 直接给 --append

HOME_DIR="$(rexec_user 'printf %s "$HOME"')"; [ -n "$HOME_DIR" ] || fail "无法解析家目录"
APP_SRC="$HOME_DIR/dpt-docker-framework/apps/$NAME/src"
DOMAIN="$(rexec "sed -n 's/^[[:space:]]*server_name[[:space:]]\{1,\}\([^;]*\);.*/\1/p' /etc/nginx/conf.d/$NAME.conf 2>/dev/null | awk '{print \$1}' | head -1")"
[ -n "$DOMAIN" ] || DOMAIN="<your-domain>"
JOB="$(printf '%s' "$BRANCH" | tr -c 'A-Za-z0-9_' '_')"       # 分支名 → 合法 job 名(release/1.0 → release_1_0)

OUTDIR="./audit/ci"
OUT="$OUTDIR/$NAME.gitlab-ci.yml"
mkdir -p "$OUTDIR"                                            # 本地产物目录(非服务器、非仓库)

render_branch() {
  sed -e "s|__NAME__|$NAME|g" -e "s|__BRANCH__|$BRANCH|g" -e "s|__JOB__|$JOB|g" \
      -e "s|__APP_SRC__|$APP_SRC|g" -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__TAG__|$TAG|g" \
      "$ROOT/ci/templates/gitlab-ci.branch.tmpl"
}

section "渲染 .gitlab-ci.yml($NAME,分支 $BRANCH → $DOMAIN,runner tag $TAG,模式 $MODE)"
if [ "$MODE" = --append ]; then
  [ -f "$OUT" ] || fail "追加失败:$OUT 不存在。请先不带 --append 跑一次,生成整段文件,再追加分支。"
  grep -qE "^build_$JOB:" "$OUT" && fail "分支 $BRANCH 的块(build_$JOB)已在 $OUT 中,勿重复追加(需更新请删旧块或重跑 full)。"
  render_branch >> "$OUT"
  VERB="已追加分支块 build_$JOB/deploy_$JOB 到"
else
  { cat "$ROOT/ci/templates/gitlab-ci.header.tmpl"; render_branch; } > "$OUT"
  VERB="已生成整段文件(头部 + 分支 $BRANCH)到"
fi

ABS="$(cd "$OUTDIR" && pwd)/$NAME.gitlab-ci.yml"
printf '\n%s:\n  %s\n' "$VERB" "$ABS"
printf '共 %s 行,含分支:%s\n' "$(wc -l < "$OUT" | tr -d ' ')" "$(grep -oE '^build_[A-Za-z0-9_]+:' "$OUT" | sed 's/^build_//; s/:$//' | paste -sd, -)"
printf '下一步:打开该文件,整段复制进你的 GitLab 仓库根的 .gitlab-ci.yml 并提交(dDP 不替你落服务器/仓库)。\n'
