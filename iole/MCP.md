# IOLE MCP 安装

IOLE 只安装它实际调用的外部 MCP。来源适配、设计取数和本机执行工具分开处理。

## 依赖清单

| MCP | 何时需要 | IOLE / ICP 使用的工具 |
|---|---|---|
| `google-sheets` | 入口或递归子节点是 Google Sheets | `get_sheet_data`、`list_sheets`、`update_cells`、`batch_update_cells` |
| `apifox-new-mcp` | 行数据含接口描述，Stage 2 需要取得真实接口契约 | `listAccessibleProjects`、`getStructureInfo`、`readEntityDetails` |

以下能力不加入外部 MCP 安装清单：

- 周期执行使用 Codex Desktop 内置的 `mcp__codex_app__automation_update`，无需安装。
- 蓝湖设计数据由 `icp/extract/scripts/lanhu_fetch.py` 获取，不经蓝湖 MCP。
- 本地 JSON 来源由 `icpl` 读取，不需要 MCP。
- Git 提交、推送和 MR 交付不是 IOLE 取数 MCP。
- Android 运行和视觉验证不是 IOLE 取数 MCP。
- `icpd`、`icpf` 尚未提供时，不提前安装或虚构钉钉、飞书 MCP；对应来源启用时再补适配器和安装说明。

## Google Sheets

前置条件：

1. 安装 `uv`。
2. 准备 Google Service Account JSON。
3. 把目标表格共享给该 Service Account 的邮箱，并授予编辑权限。

安装：

```sh
codex mcp add google-sheets \
  --env SERVICE_ACCOUNT_PATH=/absolute/path/to/service-account.json \
  --env ENABLED_TOOLS=get_sheet_data,update_cells,batch_update_cells,list_sheets \
  -- uv run --script /absolute/path/to/.agents/skills/icps/scripts/icps_google_sheets_mcp.py
```

必须使用仓库内的 `icps_google_sheets_mcp.py`：它固定上游版本，并对失效连接做有限重试。不要直接安装另一个同名 Google Sheets MCP 替代它。

## Apifox

令牌只通过环境变量传入，不把令牌明文写进仓库：

```sh
export APIFOX_ACCESS_TOKEN='<token>'
codex mcp add apifox-new-mcp \
  --url https://api.apifox.com/mcp \
  --bearer-token-env-var APIFOX_ACCESS_TOKEN
```

在 `~/.codex/config.toml` 的同一服务配置中保留 API 版本头：

```toml
[mcp_servers.apifox-new-mcp]
url = "https://api.apifox.com/mcp"
bearer_token_env_var = "APIFOX_ACCESS_TOKEN"
http_headers = { "X-Apifox-Api-Version" = "2025-09-01" }
```

## 验证

```sh
codex mcp list
```

配置完成后重启 Codex Desktop。新会话中还必须确认以下工具真实可见：

- `mcp__google_sheets__get_sheet_data`
- `mcp__google_sheets__batch_update_cells`
- `mcp__apifox_new_mcp__listAccessibleProjects`
- `mcp__apifox_new_mcp__getStructureInfo`
- `mcp__apifox_new_mcp__readEntityDetails`

`codex mcp list` 只能证明配置存在；实际读取一张已授权表格、列出一次 Apifox 项目，才能证明连接和凭据可用。
