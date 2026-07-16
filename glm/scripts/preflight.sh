#!/usr/bin/env bash
set -euo pipefail

ENSURE="${1:-}"
DATA_DIR="${MIMO2CODEX_DATA_DIR:-/Users/oklik/.mimo2codex}"
ENV_FILE="$DATA_DIR/.env"
LABEL="com.oklik.codex.glm-kimi-proxy"
PLIST="/Users/oklik/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

command -v codex >/dev/null 2>&1 || { echo "codex=missing"; exit 1; }
if ! command -v mimo2codex >/dev/null 2>&1 && [[ ! -x /Users/oklik/.nvm/versions/node/v24.14.1/bin/mimo2codex ]]; then
  echo "mimo2codex=missing (install mimo2codex@0.5.29)"
  exit 1
fi
[[ -f "$ENV_FILE" ]] || { echo "env=missing ($ENV_FILE)"; exit 1; }

ENV_ZHIPU_API_KEY="${ZHIPU_API_KEY:-}"
ENV_GLM_API_KEY="${GLM_API_KEY:-}"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
GLM_KEY="${ENV_ZHIPU_API_KEY:-${ZHIPU_API_KEY:-${ENV_GLM_API_KEY:-${GLM_API_KEY:-}}}}"
[[ -n "$GLM_KEY" ]] || { echo "glm_key=missing (set ZHIPU_API_KEY in $ENV_FILE)"; exit 1; }

[[ -f "$PLIST" ]] || { echo "launch_agent=missing ($PLIST)"; exit 1; }
rg -q -F -e '[model_providers.glm-local]' /Users/oklik/.codex/config.toml || { echo "codex_provider=missing (glm-local)"; exit 1; }
rg -q -F -e 'model_provider = "glm-local"' /Users/oklik/.codex/agents/glm-coder.toml || { echo "custom_agent=invalid (glm-coder)"; exit 1; }

if [[ "$ENSURE" == "--ensure" ]]; then
  if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl bootstrap "$DOMAIN" "$PLIST"
  fi
  launchctl kickstart -k "$DOMAIN/$LABEL"
  for _ in {1..40}; do
    if curl -fsS --max-time 1 http://127.0.0.1:8042/healthz >/dev/null 2>&1; then
      echo "glm=ready endpoint=http://127.0.0.1:8042/v1 model=glm-5.2"
      exit 0
    fi
    sleep 0.25
  done
  echo "proxy=not-ready (see /Users/oklik/Library/Logs/mimo2codex/proxy.err.log)" >&2
  exit 1
fi

if curl -fsS --max-time 1 http://127.0.0.1:8042/healthz >/dev/null 2>&1; then
  echo "glm=ready endpoint=http://127.0.0.1:8042/v1 model=glm-5.2"
else
  echo "glm=configured proxy=stopped (run $0 --ensure)"
fi
