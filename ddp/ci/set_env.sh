#!/usr/bin/env bash
# dDP / ci / set_env —— 子动作:配置某 app 的 src/.env。
#   给了 <本地.env路径> → 【真执行】:把本地 .env 管道直传写入服务器 + 触发 reload + 验证,每步回显。
#   没给路径          → 只【打印】方式 A/B 命令,由用户自己跑。
# 安全边界:.env 内容【管道直传】本地→服务器,绝不打印、绝不进对话;脚本只读 .env 的属主元数据。
# 用法: set_env.sh <profile> <name> [本地.env路径]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: set_env.sh <profile> <name> [本地.env路径]}"
NAME="${2:?缺 name}"
LOCAL="${3:-}"

# ---- 解析服务器目标 + 属主(只读元数据)----
HOME_DIR="$(rexec_user 'printf %s "$HOME"')"; [ -n "$HOME_DIR" ] || fail "无法解析运营用户家目录"
DEST="$HOME_DIR/dpt-docker-framework/apps/$NAME/src/.env"
TRIG="$HOME_DIR/dpt-docker-framework/apps/$NAME/src/.reload-trigger"
own="$(rexec "stat -c '%u:%g' '$DEST' 2>/dev/null")"
if [ -z "$own" ]; then
  base="$(rexec "grep '^$DPT_USER:' /etc/subuid | head -1 | cut -d: -f2")"
  if [ -n "$base" ]; then own="$(( base + 32 )):$(( base + 32 ))"; else own="100032:100032"; fi
fi
uid="${own%:*}"; gid="${own#*:}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -i "$DPT_KEY" -p "$DPT_PORT")

# ============ 只打印模式(无本地路径)============
if [ -z "$LOCAL" ]; then
  section "配置 $NAME 的 .env(未给本地路径 → 只打印命令,你自己跑)"
  cat <<EOF
目标: $DEST  属主 $uid:$gid / 0400(容器可读;opt/CI 读不到)
方式 A(推本地文件):
  cat /路径/你的.env | ssh -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST \\
    'sudo install -o $uid -g $gid -m 0400 /dev/stdin "$DEST" && touch "$TRIG" && echo done'
方式 B(服务器上编辑): ssh 登录后 nano 写入 → sudo install -o $uid -g $gid -m 0400 ~/.env.tmp "$DEST" → touch "$TRIG"
提示:给本脚本第3参数(本地 .env 路径)即可改为自动执行。
EOF
  exit 0
fi

# ============ 真执行模式(给了本地路径)============
section "配置 $NAME 的 .env(真执行;内容管道直传、不进对话)"

printf '[1/5] 校验本地 .env\n'
[ -f "$LOCAL" ] || fail "本地文件不存在: $LOCAL"
sz="$(wc -c < "$LOCAL" | tr -d ' ')"
[ "${sz:-0}" -gt 0 ] || fail "本地 .env 为空(0 字节): $LOCAL"
printf '  → %s(%s 字节)✓\n' "$LOCAL" "$sz"

printf '[2/5] 解析服务器目标 + 属主\n'
printf '  → %s  属主 %s:%s / 0400 ✓\n' "$DEST" "$uid" "$gid"

printf '[3/5] 备份服务器当前 .env(sudo;属主非 opt)\n'
ts="$(rexec 'date +%Y%m%d%H%M%S')"
oldsz="$(rexec "stat -c %s '$DEST' 2>/dev/null || echo NA")"
# 备份放 src 外(app 目录):src 里的 .env.bak.* 会让 CI 的 rsync 备份步 Permission denied(code 23)——此坑已踩。
BAK="${DEST%/src/.env}/.env.bak.$ts"
rexec "cp -a '$DEST' '$BAK' 2>/dev/null || true" >/dev/null 2>&1
printf '  → 原大小 %s 字节;备份 → %s ✓\n' "$oldsz" "$BAK"

printf '[4/5] 写入 .env(本地内容管道直传服务器,不显示)+ 触发优雅 reload\n'
if cat "$LOCAL" | ssh "${SSH_OPTS[@]}" "$DPT_USER@$DPT_HOST" \
     "sudo install -o $uid -g $gid -m 0400 /dev/stdin '$DEST' && touch '$TRIG'"; then
  printf '  → 已写入 + 触发 reload(USR2)✓\n'
else
  fail "[4/5] 写入失败(检查 sudo NOPASSWD / 路径 / 网络)"
fi

printf '[5/5] 验证\n'
sleep 4   # 等 reload 落地
newsz="$(rexec "stat -c %s '$DEST' 2>/dev/null || echo 0")"
newown="$(rexec "stat -c '%u:%g' '$DEST' 2>/dev/null")"
health="$(rexec_user "docker inspect -f '{{.State.Health.Status}}' $NAME-php 2>/dev/null")"
code="$(rexec "dom=\$(sed -n 's/^[[:space:]]*server_name[[:space:]]\{1,\}\([^;]*\);.*/\1/p' /etc/nginx/conf.d/$NAME.conf 2>/dev/null | awk '{print \$1}' | head -1); curl -sk -o /dev/null -w '%{http_code}' -H \"Host: \$dom\" https://127.0.0.1/ 2>/dev/null")"
printf '  → 服务器 .env = %s 字节(原 %s),属主 %s\n' "$newsz" "$oldsz" "$newown"
printf '  → 容器健康 = %s;站点 HTTP = %s\n' "${health:-未知}" "${code:-未知}"
if [ "${newsz:-0}" -gt 0 ]; then
  printf '\n✅ 完成 —— %s 的 .env 已就位(内容全程未进对话)。回滚:服务器上 sudo cp -a %s %s\n' "$NAME" "$BAK" "$DEST"
else
  fail "服务器 .env 仍为 0 字节,写入异常"
fi
