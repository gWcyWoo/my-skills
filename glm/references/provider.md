# GLM provider

- Codex provider: `glm-local`.
- Local Responses endpoint: `http://127.0.0.1:8042/v1`.
- Upstream Chat Completions endpoint: `https://open.bigmodel.cn/api/coding/paas/v4`.
- Default model: `glm-5.2`.
- Preferred secret: `ZHIPU_API_KEY`; `GLM_API_KEY` remains an accepted alias.
- Put the secret in `~/.mimo2codex/.env`; the file must remain mode `600`.
- Proxy configuration: `~/.mimo2codex/providers.json`.
- Codex model metadata: `~/.mimo2codex/models.json`.
- LaunchAgent: `com.oklik.codex.glm-kimi-proxy`.
- The main Codex model is unaffected because only GLM custom agents and the fallback runner select `glm-local`.
- Do not use Anthropic variables, Claude state directories, or a Claude executable.
