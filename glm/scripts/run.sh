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

API_KEY="${ZHIPU_API_KEY:-${GLM_API_KEY:-}}"
[[ -n "$API_KEY" ]] || {
  echo "错误: 缺少 ZHIPU_API_KEY（也接受 GLM_API_KEY）。" >&2
  exit 2
}

CLAUDE_BIN="${GLM_WORKER_CLAUDE:-${WORKER_CLAUDE:-claude}}"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || {
  echo "错误: 找不到 Claude Code: $CLAUDE_BIN" >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  echo "错误: 找不到 python3，无法格式化 worker 输出。" >&2
  exit 2
}

MODEL="${GLM_MODEL:-GLM-5.2}"
SMALL_MODEL="${GLM_SMALL_MODEL:-$MODEL}"
if [[ "$MODEL" == *"[1m]"* ]]; then
  echo "错误: GLM 模型 id 不要带 [1m] 后缀。" >&2
  exit 2
fi

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
WORKER_CONFIG="$USER_HOME/.claude-worker-glm"
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
LATEST_LOG="$LOG_DIR/glm-latest.log"
touch "$LATEST_LOG"
chmod 600 "$LATEST_LOG"

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WENV=(
  "ANTHROPIC_BASE_URL=${GLM_BASE_URL:-https://open.bigmodel.cn/api/anthropic}"
  "ANTHROPIC_AUTH_TOKEN=$API_KEY"
  "ANTHROPIC_MODEL=$MODEL"
  "ANTHROPIC_SMALL_FAST_MODEL=$SMALL_MODEL"
  "CLAUDE_CODE_SUBAGENT_MODEL=$MODEL"
  "ANTHROPIC_DEFAULT_OPUS_MODEL=$MODEL"
  "ANTHROPIC_DEFAULT_SONNET_MODEL=$MODEL"
  "ANTHROPIC_DEFAULT_HAIKU_MODEL=$SMALL_MODEL"
)

cd "$WORKDIR"
echo "[worker] provider=glm mode=$MODE log=$LATEST_LOG" >&2
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
  "$CLAUDE_BIN" \
    --model "$MODEL" \
    "${PERMISSION_ARGS[@]}" \
    --add-dir "$WORKDIR" \
    -p "$PROMPT" \
    --output-format stream-json \
    --verbose \
  | python3 "$SELF_DIR/fmt.py" "$LATEST_LOG" "glm:$MODE" "$$"
rc=${PIPESTATUS[0]}
set -e
exit "$rc"
