#!/usr/bin/env bash
# dDP / list_profiles —— 枚举已存在的 profile(~/.ssh/*/dpt.conf),打印非密字段。
# dDP 复用 dDLN 建好的同一套 profile(~/.ssh/<profile>/),只部署、**不创建**。
# 供 SKILL.md Phase 0「列出并选择已存在 profile」:读出每个 profile 的已存参数做菜单(只能选,不能新建)。
# 每行输出: <profile>\t<host>\t<user>\t<port>;一个都没有时打印单行 NONE。
# 只读非密字段(host/user/port),绝不碰 key / *.sudo。在「你的本机」执行。
set -uo pipefail
shopt -s nullglob

found=0
for conf in "$HOME"/.ssh/*/dpt.conf; do
  # profile 名 = 目录 basename(唯一真源),不读文件里写死的 DPT_PROFILE(改名后会过时)。
  d="$(basename "$(dirname "$conf")")"
  # 子 shell 隔离 source,避免变量在多个 profile 之间串味
  line="$(
    . "$conf" 2>/dev/null || exit 0
    printf '%s\t%s\t%s\t%s\n' \
      "$d" "${DPT_HOST:-?}" "${DPT_USER:-?}" "${DPT_PORT:-?}"
  )" || continue
  [ -n "$line" ] || continue
  printf '%s\n' "$line"
  found=1
done

[ "$found" = 1 ] || printf 'NONE\n'
