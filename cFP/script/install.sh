#!/usr/bin/env bash
# cFP Phase 1 / 步骤4:经 FVM 安装并纳管所选 Flutter 版本。
# 入参 TARGET = 具体版本号(如 3.41.9)或 "stable"(最新稳定)。
# 流程:① 无 fvm 则按确定性分支安装(有 brew→brew,否则官方脚本);② fvm install <TARGET>;③ 回读纳管版本。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/lib/common.sh"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "用法: install.sh <flutter版本号|stable>" >&2
  exit 2
fi

# 1) 确保 fvm 已安装(确定性分支)。
FVM="$(fvm_bin)"
if [ -n "$FVM" ]; then
  info "FVM 已安装... $("$FVM" --version 2>&1 | head -1)"
else
  if command -v brew >/dev/null 2>&1; then
    step "安装 FVM(brew)" brew install fvm || exit 1
  else
    step "安装 FVM(官方脚本)" bash -c 'curl -fsSL https://fvm.app/install.sh | bash' || exit 1
  fi
  FVM="$(fvm_bin)"
  if [ -z "$FVM" ]; then
    echo "安装 FVM(定位)... FAILED"
    echo "    fvm 安装后仍无法定位(检查 PATH 或 ~/fvm/bin)"
    exit 1
  fi
fi

# 2) 经 FVM 安装/纳管目标版本(stable=最新稳定;install 默认会跑 setup)。
step "安装 Flutter [$TARGET](经 FVM)" "$FVM" install "$TARGET" || exit 1

# 3) 回读已纳管版本(含各版本内置 Dart 版本)。
info "已纳管版本(Flutter / Dart):"
"$FVM" list 2>&1 | sed 's/^/    /'
