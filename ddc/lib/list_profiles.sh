#!/usr/bin/env bash
# dDC / list_profiles —— 枚举已存在的 profile(~/.ssh/*/dpt.conf),打印非密字段。
# dDC 复用 dDLN/dDP 同一套 profile(~/.ssh/<profile>/),只【选择】要检查的服务器,绝不创建/修改。
# 供 SKILL.md「列出并选择已存在 profile」做编号菜单(只能选,不能新建)。
# 每行输出: <profile>\t<host>\t<user>\t<port>;一个都没有时打印单行 NONE。
# 只读非密字段(host/user/port),绝不碰 key / *.sudo。在「你的本机」执行。
set -uo pipefail
shopt -s nullglob

found=0
for conf in "$HOME"/.ssh/*/dpt.conf; do
  d="$(basename "$(dirname "$conf")")"
  line="$(
    . "$conf" 2>/dev/null || exit 0
    printf '%s\t%s\t%s\t%s\n' "$d" "${DPT_HOST:-?}" "${DPT_USER:-?}" "${DPT_PORT:-?}"
  )" || continue
  [ -n "$line" ] || continue
  printf '%s\n' "$line"
  found=1
done

[ "$found" = 1 ] || printf 'NONE\n'
