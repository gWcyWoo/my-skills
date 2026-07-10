#!/usr/bin/env bash
# dDP / deploy / retune —— 硬件(尤其物理内存)变更后,按【当前实际内存】重算并重部署一个已部署 app。
# Docker 内存上限只接受绝对值、不会自己读宿主内存,故"按物理内存定"只能在此重新渲染:
#   重算(复用 lib/common.sh 的 dpt_calc_resources,与 probe 同一算法、同一不变式)
#   → 定点改 compose 的 memory + www.conf 的 pm.*(只改数值,其余不动)
#   → 仅当 pm.max_children 变化才重建镜像(www.conf 烤进镜像);否则只 compose 重建即生效新内存上限
#   → 复用 up.sh 重建容器并等 healthy。
# 只改本 app;算 COMMITTED 时排除自身。幂等:无变化则跳过。全程 rootless cert(不 root、不输密码)。
# 末行打印 `RETUNE ...` 摘要(before→after)供调用方写入审计日志(skill 不假定项目审计路径)。
# 用法: retune.sh <profile> <name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: retune.sh <profile> <name>}"
NAME="${2:?缺 name}"
APP='$HOME/dpt-docker-framework/apps/'"$NAME"

section "retune $NAME(按当前物理内存重算容器资源)"

# 0) app 必须已部署
if ! rexec_user "test -f $APP/compose.yaml && test -f $APP/deploy/www.conf"; then
  fail "app $NAME 未部署(缺 compose.yaml / deploy/www.conf)—— 请先走部署流程,再 retune。"
fi

# 1) 当前【运行态】值(before)—— 读容器实际生效值,而非文件:防"文件已改但没重部署"被误判无变化。
#    内存取 docker inspect 的字节数 → 换算 MiB;max_children 取镜像内已烤的 www.conf。容器不在则留空(=需部署)。
CN="$NAME-php"
cur_mem="$(rexec_user "
  b=\$(docker inspect -f '{{.HostConfig.Memory}}' $CN 2>/dev/null)
  case \"\$b\" in ''|0|'<no value>') : ;; *) printf '%sm' \$(( b / 1048576 ));; esac
")"
cur_mc="$(rexec_user "docker exec $CN grep -oE '^pm.max_children = [0-9]+' /usr/local/etc/php-fpm.d/www.conf 2>/dev/null | grep -oE '[0-9]+' | head -1")"

# 2) 重算(after)—— 排除自身,避免把当前限额计进 COMMITTED
calc="$(dpt_calc_resources "$NAME")"
new_mem="$(printf '%s\n' "$calc" | sed -n 's/.* mem=\([0-9]*m\) .*/\1/p')"
new_mc="$(printf '%s\n' "$calc" | sed -n 's/.* max_children=\([0-9]*\).*/\1/p')"
show "重算" "$calc"
[ -n "$new_mem" ] && [ -n "$new_mc" ] || fail "重算失败:$calc"
printf '  → before: mem=%s max_children=%s\n  → after : mem=%s max_children=%s\n' \
  "${cur_mem:-?}" "${cur_mc:-?}" "$new_mem" "$new_mc"

# 幂等:无变化不动
if [ "$cur_mem" = "$new_mem" ] && [ "$cur_mc" = "$new_mc" ]; then
  printf '\n无变化 —— 跳过重部署。\n'
  printf '\nRETUNE name=%s changed=no mem=%s max_children=%s\n' "$NAME" "$cur_mem" "$cur_mc"
  exit 0
fi

# 3) 备份 + 定点改写(pm 衍生值由 max_children 推,与 scaffold 同公式)
START=$(( new_mc / 4 )); [ "$START" -lt 2 ] && START=2
MINSP=$(( new_mc / 8 )); [ "$MINSP" -lt 1 ] && MINSP=1
MAXSP=$(( new_mc / 2 )); [ "$MAXSP" -lt 4 ] && MAXSP=4
TS="$(rexec_user 'date +%Y%m%d%H%M%S')"
run "备份 compose.yaml / www.conf(.bak.$TS)" rexec_user \
  "cp -a $APP/compose.yaml $APP/compose.yaml.bak.$TS && cp -a $APP/deploy/www.conf $APP/deploy/www.conf.bak.$TS"
run "改写 compose 内存上限 → $new_mem" rexec_user \
  "sed -i 's/\\(memory: *\\)[0-9]\\+[mg]/\\1$new_mem/' $APP/compose.yaml"
run "改写 www.conf pm.*(max_children=$new_mc start=$START min_spare=$MINSP max_spare=$MAXSP)" rexec_user "
  sed -i \
    -e 's/^pm.max_children = .*/pm.max_children = $new_mc/' \
    -e 's/^pm.start_servers = .*/pm.start_servers = $START/' \
    -e 's/^pm.min_spare_servers = .*/pm.min_spare_servers = $MINSP/' \
    -e 's/^pm.max_spare_servers = .*/pm.max_spare_servers = $MAXSP/' \
    $APP/deploy/www.conf
"

# 4) max_children 变了才重建镜像(www.conf 在 Dockerfile 中 COPY 进镜像);否则只 compose 重建即生效新内存
if [ "$cur_mc" != "$new_mc" ]; then
  note "pm.max_children ${cur_mc:-?} → ${new_mc} → 重建镜像(www.conf 烤进镜像;有层缓存,通常很快)"
  bash "$ROOT/deploy/build_image.sh" "$DPT_PROFILE" "$NAME" || fail "镜像重建失败"
else
  note "pm.max_children 未变 → 跳过镜像重建,仅 compose 重建生效新内存上限"
fi

# 5) 重建容器(复用 up.sh:确保 dpt-net + 自愈 + compose up -d + 等 healthy)
bash "$ROOT/deploy/up.sh" "$DPT_PROFILE" "$NAME" || fail "容器重建 / 健康检查失败"

printf '\nretune 完成 ✅ —— %s: mem %s→%s, max_children %s→%s(备份 .bak.%s,回滚:cp -a 备份回原名 + up.sh)\n' \
  "$NAME" "${cur_mem:-?}" "$new_mem" "${cur_mc:-?}" "$new_mc" "$TS"
printf '\nRETUNE name=%s changed=yes mem_before=%s mem_after=%s mc_before=%s mc_after=%s backup_ts=%s\n' \
  "$NAME" "${cur_mem:-?}" "$new_mem" "${cur_mc:-?}" "$new_mc" "$TS"
