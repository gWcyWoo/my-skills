#!/usr/bin/env bash
# cFP Phase 1 / 步骤2:只读检测环境(brew / fvm / flutter 全局 / dart / fvm 已缓存版本)。
# 严格只读 —— 不安装、不修改任何状态。逐行打印 "标签... 版本|NOT FOUND"。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/lib/common.sh"

if command -v brew >/dev/null 2>&1; then
  info "brew... $(brew --version 2>&1 | head -1)"
else
  info "brew... NOT FOUND"
fi

FVM="$(fvm_bin)"
if [ -n "$FVM" ]; then
  info "fvm... $("$FVM" --version 2>&1 | head -1)"
else
  info "fvm... NOT FOUND"
fi

if command -v flutter >/dev/null 2>&1; then
  info "flutter(全局)... $(flutter --version 2>&1 | head -1)"
else
  info "flutter(全局)... NOT FOUND"
fi

# Dart 随 Flutter 自带(B:1):仅展示当前 PATH 上的 dart 版本,不单独管理。
if command -v dart >/dev/null 2>&1; then
  info "dart(全局/Flutter 内置)... $(dart --version 2>&1 | head -1)"
else
  info "dart(全局/Flutter 内置)... NOT FOUND"
fi

if [ -n "$FVM" ]; then
  info "fvm 已缓存版本:"
  "$FVM" list 2>&1 | sed 's/^/    /'
fi
