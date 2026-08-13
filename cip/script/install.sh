#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"

TOOL="${1:-}"
case "$TOOL" in
  xcodegen|swiftlint) ;;
  *) die '安装参数校验' '用法: install.sh <xcodegen|swiftlint>' ;;
esac

[ "$(uname -s)" = "Darwin" ] || die '系统校验' '仅支持 macOS'
command -v brew >/dev/null 2>&1 || die 'Homebrew 检测' 'brew NOT FOUND；请手动安装所需工具后重试'

if command -v "$TOOL" >/dev/null 2>&1; then
  done_step "$TOOL 已安装"
else
  run_step "安装 $TOOL" brew install "$TOOL" || exit 1
fi

if [ "$TOOL" = "xcodegen" ]; then
  run_step "验证 $TOOL" xcodegen --version || exit 1
else
  run_step "验证 $TOOL" swiftlint version || exit 1
fi
printf '\n安装结果汇总\n'
printf '工具: %s\n' "$TOOL"
print_counts
