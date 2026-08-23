# icp 输入契约

icp 不依赖 iole 的行格式（`iole-item.row`）。调用方（iole 或人）负责将数据映射到本契约，icp 内部只认这个结构。

## 输入结构

```json
{
  "title": "登录",
  "route": "signin",

  "design_image": "path/to/design.png",
  "design_json": "path/to/sketch.json",
  "ui_description": "结构分为4部份...",

  "slices_json": "path/to/slices.json",
  "cover_image": "path/to/cover.png",

  "interaction_description": "点击验证码输入框...",
  "api_description": "/auth/otp-requests POST ...",

  "ut": "",
  "it": "",
  "e2e": ""
}
```

## 字段说明

| 字段 | 阶段 | 必填 | 说明 |
|---|---|---|---|
| `title` | 全局 | 是 | 页面标题，全树唯一标识 |
| `route` | 全局 | 是 | 路由名，代码中的路径标识 |
| `design_image` | Stage 1 | 是 | 设计图图片路径（供模型视觉理解） |
| `design_json` | Stage 1 | 是 | 蓝湖 sketch JSON 路径（节点树 + 设计数据） |
| `ui_description` | Stage 1 | 否 | UI 补充描述（可空，辅助模型语义分组） |
| `slices_json` | Stage 1 | 是 | 蓝湖切片数据 JSON 路径（多倍率 URL） |
| `cover_image` | Stage 1 | 是 | 整页截图路径（裁切图标用） |
| `interaction_description` | Stage 2 | 否 | 交互描述（自然语言，含跳转/弹窗/API 触发；空则 Stage 2 退化为纯 UI） |
| `api_description` | Stage 2 | 否 | 接口描述（端点 + 参数 + 响应；空则 `apis: []`） |
| `ut` / `it` / `e2e` | Stage 3 | 否 | 测试要求 |

## 映射规则

调用方的第一步是将自己的数据映射到本结构：

- `design_json` / `slices_json` / `cover_image` 由 `extract/scripts/lanhu_fetch.py` 一条命令产出，见下方「取数」
- `ui_description` 为空时传 `null` 或空串，Stage 1 正常工作
- 字段为空归一为 `null`，不用空串

## 取数

`design_json` / `slices_json` / `cover_image` 不需要调用方自己攒，一条命令产出：

```
python3 extract/scripts/lanhu_fetch.py --url "<含 image_id 的蓝湖 URL>" --out-dir <dir>
```

产出直接就是各字段的值：

| 产物 | 对应字段 | 去向 |
|---|---|---|
| `<dir>/design.json` | `design_json` | `bind.py prepare/bind/enrich/crop --design-json` |
| `<dir>/slices.json` | `slices_json` | `bind.py enrich --slices-json` |
| `<dir>/cover.png` | `cover_image` | `bind.py crop --cover-image` |
| `<dir>/assets/*` | — | 设计师导出的真实切图(png+svg)，优于 crop 裁切 |

stdout 只有一行 summary JSON（含 `node_count` / `slices_downloaded` / `artboard_frame`），
大 JSON 一律落盘不进 stdout。

**鉴权**：`$LANHU_COOKIE`，或 `~/.codex/mcp/lanhu-mcp/.env` 里的 `LANHU_COOKIE=…`。

**不经 lanhu MCP**：走蓝湖静态版本数据（`/api/project/image` → `versions[0].json_url`），
不碰 DDS 服务端渲染（`store_schema_revise`）。切图就在设计 JSON 里
（`hasExportImage` + `image.imageUrl/svgUrl`），无需单独接口。
URL 缺 `tid` 不影响——cookie 已确定团队。

**失败即停**：cookie 缺失、URL 缺 `image_id`/`pid`、接口报错、
以及 artboard 节点数 ≤1（版本数据异常，继续走会让 bind 静默绑定 0 节点）
都直接以 `{"ok": false, "errors": [...]}` 退出。

`design_image`（供模型视觉理解的整页图）就用 `cover.png`。
