#!/usr/bin/env bash

CIP_OK=${CIP_OK:-0}
CIP_FAILED=${CIP_FAILED:-0}

info() {
  printf '%s\n' "$*"
}

done_step() {
  printf '%s... done\n' "$1"
  CIP_OK=$((CIP_OK + 1))
}

fail_step() {
  printf '%s... FAILED\n' "$1"
  [ -z "${2:-}" ] || printf '%s\n' "$2" | sed 's/^/    /'
  CIP_FAILED=$((CIP_FAILED + 1))
}

run_step() {
  local label="$1"
  shift
  local output rc
  if output="$("$@" 2>&1)"; then
    done_step "$label"
    return 0
  else
    rc=$?
    fail_step "$label" "$output"
    return "$rc"
  fi
}

die() {
  fail_step "$1" "${2:-}"
  exit 1
}

print_counts() {
  printf '成功步骤: %s\n失败步骤: %s\n' "$CIP_OK" "$CIP_FAILED"
}
