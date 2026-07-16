#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "用法: run.sh <code|explore|test|review> \"任务描述\" [工作目录]" >&2
}

MODE="${1:-}"
TASK="${2:-}"
WORKDIR="${3:-$PWD}"

case "$MODE" in
  code|explore|test|review) ;;
  *) usage; exit 2 ;;
esac

[[ -n "$TASK" ]] || { usage; exit 2; }
[[ -d "$WORKDIR" ]] || { echo "错误: 工作目录不存在: $WORKDIR" >&2; exit 2; }
WORKDIR="$(cd "$WORKDIR" && pwd -P)"

API_KEY="${MOONSHOT_API_KEY:-${KIMI_API_KEY:-}}"
[[ -n "$API_KEY" ]] || {
  echo "错误: 缺少 MOONSHOT_API_KEY（也接受 KIMI_API_KEY）。" >&2
  exit 2
}

CLAUDE_BIN="${KIMI_WORKER_CLAUDE:-${WORKER_CLAUDE:-claude}}"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || {
  echo "错误: 找不到 Claude Code: $CLAUDE_BIN" >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  echo "错误: 找不到 python3，无法格式化 worker 输出。" >&2
  exit 2
}

case "$MODE" in
  code)
    MODE_GUIDANCE="执行已经批准的实现方案。允许编辑任务边界内的文件。不要扩大范围；完成后报告改动文件、验证命令和未解决问题。"
    PERMISSION_ARGS=(--permission-mode acceptEdits)
    ;;
  explore)
    MODE_GUIDANCE="只做探索。禁止修改任何项目文件，也禁止通过 Bash 间接写文件。结论必须提供具体 file:line 证据。"
    PERMISSION_ARGS=(--permission-mode default --disallowedTools Edit,Write,NotebookEdit)
    ;;
  test)
    MODE_GUIDANCE="只运行测试和诊断命令。禁止修改项目文件或实现修复。报告完整命令、退出码和关键失败。"
    PERMISSION_ARGS=(--permission-mode default --disallowedTools Edit,Write,NotebookEdit)
    ;;
  review)
    MODE_GUIDANCE="只审查现有代码或 diff。禁止修改项目文件。只报告可操作问题，并提供具体 file:line、影响和理由。"
    PERMISSION_ARGS=(--permission-mode default --disallowedTools Edit,Write,NotebookEdit)
    ;;
esac

PROMPT="$MODE_GUIDANCE

任务:
$TASK"

USER_HOME="${HOME:?HOME 未设置}"
WORKER_CONFIG="$USER_HOME/.claude-worker-kimi"
mkdir -p "$WORKER_CONFIG"
chmod 700 "$WORKER_CONFIG"
if [[ ! -f "$WORKER_CONFIG/.claude.json" ]]; then
  cat > "$WORKER_CONFIG/.claude.json" <<'JSON'
{
  "hasCompletedOnboarding": true,
  "penguinModeOrgEnabled": true,
  "bypassPermissionsModeAccepted": true
}
JSON
  chmod 600 "$WORKER_CONFIG/.claude.json"
fi

LOG_DIR="${LLM_WORKER_LOG_DIR:-/tmp/codex-llm-logs}"
if [[ -e "$LOG_DIR" || -L "$LOG_DIR" ]]; then
  [[ ! -L "$LOG_DIR" ]] || { echo "错误: 日志目录是软链: $LOG_DIR" >&2; exit 2; }
  [[ -d "$LOG_DIR" ]] || { echo "错误: 日志路径不是目录: $LOG_DIR" >&2; exit 2; }
  [[ -O "$LOG_DIR" ]] || { echo "错误: 日志目录不属于当前用户: $LOG_DIR" >&2; exit 2; }
else
  mkdir -m 700 -p "$LOG_DIR"
fi
chmod 700 "$LOG_DIR"
LATEST_LOG="$LOG_DIR/kimi-latest.log"
touch "$LATEST_LOG"
chmod 600 "$LATEST_LOG"

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WENV=(
  "ANTHROPIC_BASE_URL=${KIMI_BASE_URL:-https://api.kimi.com/coding/}"
  "ANTHROPIC_API_KEY=$API_KEY"
)
CLAUDE_ARGS=()
if [[ -n "${KIMI_MODEL:-}" ]]; then
  WENV+=("ANTHROPIC_MODEL=$KIMI_MODEL" "CLAUDE_CODE_SUBAGENT_MODEL=$KIMI_MODEL")
  CLAUDE_ARGS+=(--model "$KIMI_MODEL")
fi
if [[ -n "${KIMI_THINKING_TOKENS:-}" ]]; then
  WENV+=("MAX_THINKING_TOKENS=$KIMI_THINKING_TOKENS")
fi
CLAUDE_ARGS+=(
  "${PERMISSION_ARGS[@]}"
  --add-dir "$WORKDIR"
  -p "$PROMPT"
  --output-format stream-json
  --verbose
)

cd "$WORKDIR"
echo "[worker] provider=kimi mode=$MODE log=$LATEST_LOG" >&2
set +e
env -i \
  HOME="$USER_HOME" \
  PATH="$PATH" \
  USER="${USER:-}" \
  TERM="${TERM:-xterm-256color}" \
  LANG="${LANG:-en_US.UTF-8}" \
  CLAUDE_CONFIG_DIR="$WORKER_CONFIG" \
  DISABLE_AUTOUPDATER=1 \
  ENABLE_TOOL_SEARCH=0 \
  CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 \
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  API_TIMEOUT_MS=3000000 \
  "${WENV[@]}" \
  "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" \
  | python3 "$SELF_DIR/fmt.py" "$LATEST_LOG" "kimi:$MODE" "$$"
rc=${PIPESTATUS[0]}
set -e
exit "$rc"
