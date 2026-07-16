# Kimi provider

- Codex provider: `kimi-local`.
- Local Responses endpoint: `http://127.0.0.1:8042/v1`.
- Upstream Chat Completions endpoint: `https://api.kimi.com/coding/v1`.
- Default model: `kimi-for-coding`; optional high-speed model: `kimi-for-coding-highspeed`.
- Preferred secret: `KIMI_API_KEY`; `MOONSHOT_API_KEY` remains an accepted alias.
- Put the secret in `~/.mimo2codex/.env`; the file must remain mode `600`.
- Proxy configuration: `~/.mimo2codex/providers.json`.
- Codex model metadata: `~/.mimo2codex/models.json`.
- LaunchAgent: `com.oklik.codex.glm-kimi-proxy`.
- The main Codex model is unaffected because only Kimi custom agents and the fallback runner select `kimi-local`.
- Do not use Anthropic variables, Claude state directories, or a Claude executable.
