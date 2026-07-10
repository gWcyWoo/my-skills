#!/usr/bin/env bash
# dDP / deploy / up —— 起容器:自检自愈 → 确保 dpt-net → compose up -d → 等 healthy。rootless(rexec_user)。
# 自愈:删 unhealthy/退出的残留容器;仅当 runtime 卷为空(首跑残留)才删→copy-up 重建为 33:33,非空卷绝不删。
# 空 src 也应 healthy(php-fpm 自身答 /ping)。用法: up.sh <profile> <name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: up.sh <profile> <name>}"
NAME="${2:?缺 name}"
APP='$HOME/dpt-docker-framework/apps/'"$NAME"

section "起容器 $NAME(rootless)"
run "确保共享网络 dpt-net" rexec_user "docker network inspect dpt-net >/dev/null 2>&1 || docker network create dpt-net >/dev/null"

# 自检/自愈(选项 a):删 unhealthy/退出的残留容器;仅空 runtime 卷(首跑残留)才删→copy-up 重建 33:33,非空保留。
# 卷判空走"容器内视角"(rootless userns 下宿主读不了 subuid 文件)。失败均 ||-守卫,不阻断后续 up。
show "自检:清理失败残留(unhealthy 容器 / 空 runtime 卷)" "docker rm 残留容器;空 runtime 卷则删,非空保留"
rexec_user "
  cd $APP || exit 0
  img=\"\$(grep -E '^[[:space:]]*image:' compose.yaml | head -1 | sed -e 's/.*image:[[:space:]]*//' -e 's/[[:space:]]*\$//')\"
  cname='$NAME-php'; vol='$NAME-runtime'
  if docker inspect \"\$cname\" >/dev/null 2>&1; then
    state=\"\$(docker inspect -f '{{.State.Status}}' \"\$cname\" 2>/dev/null)\"
    health=\"\$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \"\$cname\" 2>/dev/null)\"
    if [ \"\$state\" != running ] || { [ \"\$health\" != healthy ] && [ \"\$health\" != none ]; }; then
      echo \"↺ 删残留容器 \$cname (state=\$state health=\$health)\"
      docker rm -f \"\$cname\" >/dev/null 2>&1
    fi
  fi
  if docker volume inspect \"\$vol\" >/dev/null 2>&1 && [ -n \"\$img\" ]; then
    out=\"\$(docker run --rm -v \"\$vol\":/v --entrypoint sh \"\$img\" -c 'ls -A /v' 2>/dev/null)\"
    if [ -z \"\$out\" ]; then
      docker volume rm \"\$vol\" >/dev/null 2>&1 && echo \"↺ 删空 runtime 卷 \$vol(copy-up 重建为 33:33)\" || echo \"ⓘ 卷 \$vol 占用中,跳过(健康容器在用)\"
    else
      echo \"ⓘ runtime 卷 \$vol 非空,保留(运行态数据)\"
    fi
  fi
  true
" 2>&1 | sed 's/^/  /'

run "compose up -d"        rexec_user "cd $APP && docker compose up -d"

printf '等待容器健康(轮询)...'
st=""; ok=0
for i in $(seq 1 20); do
  st="$(rexec_user "docker inspect -f '{{.State.Health.Status}}' $NAME-php 2>/dev/null")"
  [ "$st" = "healthy" ] && { ok=1; break; }
  sleep 3
done
printf ' %s\n' "${st:-未知}"

if [ "$ok" = 1 ]; then
  printf '\n容器 %s-php 健康 ✅(127.0.0.1 端口已映射;代码待 CI 交付)\n' "$NAME"
else
  printf '\n容器 %s-php 未达 healthy ❌(状态 %s)—— 末尾日志:\n' "$NAME" "${st:-未知}"
  rexec_user "docker logs --tail 40 $NAME-php 2>&1" | sed 's/^/  /'
  exit 1
fi
