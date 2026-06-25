#!/usr/bin/env bash
# cFP Phase 2 / Q5:展示指定架构(编号 1-7)的 lib/ 分层结构,供用户浏览选择。
# 只读 —— 不创建任何目录。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/rule/architectures.sh"

id="${1:-}"
name="$(arch_name "$id")" || { echo "无效编号: '$id'(应为 1-7)" >&2; exit 2; }

echo "【${id}】${name}"
echo "  说明:$(arch_note "$id")"
echo "  lib/ 结构:"
arch_dirs "$id" | sed 's#^#    lib/#; s#$#/#'
