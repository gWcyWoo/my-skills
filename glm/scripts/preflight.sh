#!/usr/bin/env bash
set -euo pipefail

rc=0
CLAUDE_BIN="${GLM_WORKER_CLAUDE:-${WORKER_CLAUDE:-claude}}"
if command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "claude=present ($("$CLAUDE_BIN" --version 2>/dev/null || echo unknown))"
else
  echo "claude=missing"
  rc=2
fi

if command -v python3 >/dev/null 2>&1; then
  echo "python3=present"
else
  echo "python3=missing"
  rc=2
fi

if [[ -n "${ZHIPU_API_KEY:-${GLM_API_KEY:-}}" ]]; then
  echo "glm_api_key=present"
else
  echo "glm_api_key=missing"
  rc=2
fi

exit "$rc"
