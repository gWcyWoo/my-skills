# GLM provider

- Required secret: `ZHIPU_API_KEY`; `GLM_API_KEY` is accepted as a fallback.
- Default endpoint: `https://open.bigmodel.cn/api/anthropic`.
- Default model: `GLM-5.2`.
- Optional overrides: `GLM_BASE_URL`, `GLM_MODEL`, `GLM_SMALL_MODEL`, `GLM_WORKER_CLAUDE`, `LLM_WORKER_LOG_DIR`.
- Do not append `[1m]` to the model ID passed to the worker endpoint.
- The runner uses Anthropic-compatible environment variables because the execution harness is Claude Code, not a Codex native model provider.
- The isolated worker state remains under `~/.claude-worker-glm`.
