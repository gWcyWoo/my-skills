#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"

if [ -n "${1:-}" ]; then
  export DEVELOPER_DIR="$1"
fi

if [ "$(uname -s)" = "Darwin" ]; then
  info "macOS... $(sw_vers -productVersion 2>/dev/null || printf 'UNKNOWN')"
else
  info "macOS... NOT FOUND (当前系统: $(uname -s))"
fi

if command -v brew >/dev/null 2>&1; then
  info "brew... $(brew --version 2>&1 | sed -n '1p')"
else
  info 'brew... NOT FOUND'
fi

if command -v xcode-select >/dev/null 2>&1; then
  ACTIVE_DIR="$(xcode-select -p 2>/dev/null || true)"
  info "active developer dir... ${ACTIVE_DIR:-NOT FOUND}"
else
  info 'active developer dir... NOT FOUND'
fi

if command -v xcodebuild >/dev/null 2>&1; then
  XCODE_VERSION="$(xcodebuild -version 2>&1 || true)"
  if [ -n "$XCODE_VERSION" ]; then
    info 'xcodebuild...'
    printf '%s\n' "$XCODE_VERSION" | sed 's/^/    /'
  else
    info 'xcodebuild... NOT FOUND'
  fi
else
  info 'xcodebuild... NOT FOUND'
fi

if command -v swift >/dev/null 2>&1; then
  info "swift... $(swift --version 2>&1 | sed -n '1p')"
else
  info 'swift... NOT FOUND'
fi

if command -v xcodegen >/dev/null 2>&1; then
  info "xcodegen... $(xcodegen --version 2>&1 | sed -n '1p')"
else
  info 'xcodegen... NOT FOUND'
fi

if command -v swiftlint >/dev/null 2>&1; then
  info "swiftlint... $(swiftlint version 2>&1 | sed -n '1p')"
else
  info 'swiftlint... NOT FOUND'
fi

XCODE_APPS="$(find /Applications -maxdepth 1 -type d -name 'Xcode*.app' -print 2>/dev/null | sort)"
if [ -n "$XCODE_APPS" ]; then
  info 'installed Xcode.app...'
  printf '%s\n' "$XCODE_APPS" | sed 's/^/    /'
else
  info 'installed Xcode.app... NOT FOUND'
fi
