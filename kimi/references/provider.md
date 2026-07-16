# Kimi provider

- Required secret: `MOONSHOT_API_KEY`; `KIMI_API_KEY` is accepted as a fallback.
- Default coding endpoint: `https://api.kimi.com/coding/`.
- Leave `KIMI_MODEL` unset to let the coding endpoint route the model.
- Optional overrides: `KIMI_BASE_URL`, `KIMI_MODEL`, `KIMI_THINKING_TOKENS`, `KIMI_WORKER_CLAUDE`, `LLM_WORKER_LOG_DIR`.
- The Kimi coding-plan key and the Moonshot open-platform key belong to separate systems. Override both endpoint and model when using the open platform.
- The runner uses `ANTHROPIC_API_KEY` because the execution harness is Claude Code.
- The isolated worker state remains under `~/.claude-worker-kimi`.
