#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/rule/architectures.sh"

ARCH="${1:-}"
if ! NAME="$(architecture_name "$ARCH")"; then
  printf '用法: bash %s <1|2|3|4>\n' "$0" >&2
  exit 2
fi

printf '架构: %s\n' "$NAME"
architecture_tree "$ARCH"
