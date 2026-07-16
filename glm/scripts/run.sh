#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "用法: $0 <code|explore|test|review> <任务描述> [工作目录]" >&2
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
"$SCRIPT_DIR/preflight.sh" --ensure >/dev/null

case "$MODE" in
  code)
    SANDBOX="workspace-write"
    MODE_GUIDANCE="执行已经批准的实现方案。只编辑任务边界内的文件，保留无关改动，完成后运行要求的验证并报告改动文件。"
    ;;
  explore)
    SANDBOX="read-only"
    MODE_GUIDANCE="只做探索。禁止修改文件；结论必须提供具体绝对路径和行号证据。"
    ;;
  test)
    SANDBOX="workspace-write"
    MODE_GUIDANCE="只运行测试和诊断命令。禁止修改源文件或实现修复；报告完整命令、退出码和关键失败。"
    ;;
  review)
    SANDBOX="read-only"
    MODE_GUIDANCE="只审查现有代码或 diff。禁止修改文件；只报告有证据的可操作问题。"
    ;;
esac

PROMPT="你是由 GLM 模型驱动的 Codex 子会话。直接使用本会话的 Codex 工具完成任务，不要启动 Claude、Kimi、OpenCode、其他 Codex 子进程或任何外部 agent runtime。

$MODE_GUIDANCE

任务:
$TASK"

LOG_DIR="${GLM_LOG_DIR:-/Users/oklik/.codex/log/glm}"
mkdir -p "$LOG_DIR"
LOG_PATH="$LOG_DIR/$(date '+%Y%m%d-%H%M%S')-$MODE.log"

set +e
codex exec --json --ephemeral --skip-git-repo-check \
  -C "$WORKDIR" \
  -s "$SANDBOX" \
  -m "glm-5.2" \
  -c 'model_provider="glm-local"' \
  -c 'model_catalog_json="/Users/oklik/.mimo2codex/models.json"' \
  -c 'approval_policy="never"' \
  "$PROMPT" 2>>"$LOG_PATH" | python3 "$SCRIPT_DIR/fmt.py" "$LOG_PATH" "glm:$MODE" "$$"
STATUS=${PIPESTATUS[0]}
set -e
exit "$STATUS"
