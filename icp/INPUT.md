# icp 输入契约

icp 不依赖 iole 的行格式（`iole-item.row`）。调用方（iole 或人）负责将数据映射到本契约，icp 内部只认这个结构。

## 输入结构

```json
{
  "title": "登录",
  "route": "signin",

  "design_image": "path/to/design.png",
  "design_json": "path/to/design.json",
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
| `design_json` | Stage 1 | 是 | 统一设计数据 JSON 路径（蓝湖 sketch 结构：节点树 + 设计数据；各平台适配器都产出这个结构） |
| `ui_description` | Stage 1 | 否 | UI 补充描述（可空，辅助模型语义分组） |
| `slices_json` | Stage 1+3 | 是 | 切片数据 JSON 路径（多倍率 URL / 本地文件） |
| `cover_image` | Stage 1 | 是 | 整页截图路径（裁切图标用） |
| `interaction_description` | Stage 2 | 否 | 交互描述（自然语言，含跳转/弹窗/API 触发；空则 Stage 2 退化为纯 UI） |
| `api_description` | Stage 2 | 否 | 接口描述（端点 + 参数 + 响应；空则 `apis: []`） |
| `ut` / `it` / `e2e` | Stage 3 | 否 | 测试要求 |

## 映射规则

调用方的第一步是将自己的数据映射到本结构：

- `design_json` / `slices_json` / `cover_image` 由 `extract/scripts/design_fetch.py fetch` 一条命令产出，见下方「取数」
- `ui_description` 为空时传 `null` 或空串，Stage 1 正常工作
- 字段为空归一为 `null`，不用空串
- 源表不是唯一需求来源。调用方将当前已确认的用户补充要求合并到相应的 `ui_description`、`interaction_description`、`api_description` 或 `ut` / `it` / `e2e`，标明补充来源与适用范围，保留原始行数据；不新增另一份需求台账。任务中要求变化时更新现有 `input.json` 及受影响的验收映射，不能只修改共享 skill 后继续使用旧输入。
- 跨任务通知中，重新加载 skill 只更新执行规则，不等于接收了另一任务中的项目要求。经授权同步项目要求时须显式传递其内容与来源；以执行任务的输入及用例映射已更新为生效证据，不能以通知已发送或回复“已理解”代替。

## 取数

`design_json` / `slices_json` / `cover_image` 不需要调用方自己攒，一条命令产出：

```
python3 extract/scripts/design_fetch.py fetch --ref "<设计稿引用>" --out-dir <dir>
```

`design_fetch.py` 按引用开头的平台地址查登记表 `DESIGNS`，分流到对应适配器；
调用方不传平台参数。`check --ref` 只做离线格式校验（不联网），供 iole 领取后、派发 ICP 前提前报错。

| 平台 | 引用格式 | 适配器 | 鉴权 |
|---|---|---|---|
| 蓝湖（老平台） | `https://lanhuapp.com/...pid=…&image_id=…`（原链接，须以 `https://lanhuapp.com/` 开头） | `lanhu_fetch.py` | `$LANHU_COOKIE`，或 `~/.codex/mcp/lanhu-mcp/.env` 里的 `LANHU_COOKIE=…` |
| 自建平台 | `https://47.84.143.250.sslip.io/?project={项目 id}&design={设计图 id}`（平台里打开设计图时地址栏的链接） | `selfhost_fetch.py` | `$SELFHOST_COOKIE`，或 `~/.config/icp/selfhost.env` 里的 `SELFHOST_COOKIE=…` |

两个平台都可用 `--cookie` 覆盖，优先级 `--cookie` → 环境变量 → 文件。新增平台只加 `DESIGNS` 一行 +
一个实现 `parse_ref` / `fetch` 的适配器模块，产物契约不变。

Cookie 要放在**实际跑 iole/icp 的进程**能读到的地方：在另一个终端里 `export` 的变量，
Claude Code / Codex 的会话与无头 runner 都读不到，所以自建平台推荐用文件。取法：浏览器登录平台 →
开发者工具 Network → 刷新 → 点 `projects` 请求 → Request Headers 里 `cookie` 右键 Copy value，然后在终端（zsh）运行：

```bash
mkdir -p ~/.config/icp && read -rs "c?粘贴 Cookie 后回车: " && echo && printf 'SELFHOST_COOKIE=%s\n' "$c" > ~/.config/icp/selfhost.env && chmod 600 ~/.config/icp/selfhost.env && unset c
```

会话过期后取数报 `cookie_rejected`，按同样步骤重新写入即可。

产出直接就是各字段的值：

| 产物 | 对应字段 | 去向 |
|---|---|---|
| `<dir>/design.json` | `design_json` | `bind.py prepare/bind/enrich/crop --design-json` |
| `<dir>/slices.json` | `slices_json` | `bind.py enrich --slices-json` |
| `<dir>/cover.png` | `cover_image` | `bind.py crop --cover-image` |
| `<dir>/assets/*` | — | 设计师导出的真实切图，优于 crop 裁切 |

stdout 只有一行 summary JSON（`ok` / `design_json` / `slices_json` / `cover_image` /
`slices_downloaded`，可选 `warnings`；各适配器另有自己的统计字段），大 JSON 一律落盘不进 stdout。
cover 下载失败只记 warning，`cover_image` 为 `null`。

**蓝湖**：不经 lanhu MCP，走静态版本数据（`/api/project/image` → `versions[0].json_url`），
不碰 DDS 服务端渲染（`store_schema_revise`）。切图就在设计 JSON 里
（`hasExportImage` + `image.imageUrl/svgUrl`），无需单独接口。
URL 缺 `tid` 不影响——cookie 已确定团队。

**自建平台**：取链接里 `design` 指的那一次上传，与在平台里点开链接看到的一致（同一画板重传会生成新的
`design` id，旧链接仍取旧版）；安卓/iOS 跟随该图（缺省按安卓），设计稿名取图名（去掉插件加的 `Figma · ` 前缀）。
扁平图层按 `parentId` 还原成蓝湖结构的节点树（类型、圆角、颜色、文字度量换成蓝湖单位），
切图按名称 + 位置尺寸归组、按位置尺寸（同名优先）挂到图层上，只把最大倍率下载到 `assets/`
（远端需要 cookie，下游只用本地 `local_png`，`download_url`/`scale_urls` 为 `null`）；
以画板名命名的整画板导出就是 cover，不算切图；挂上切图的图层像蓝湖一样带 `hasExportImage` + `image`
（其中 URL 为 `null`）；
挂不上图层（或多张切图对到同一图层）的切图 `id` 为 `null` 并记 warning。

**失败即停**：以下情况都直接以 `{"ok": false, "errors": [{"type": …}]}` 退出，且不落任何产物：

| type | 含义 |
|---|---|
| `unknown_design` | 引用开头不是登记过的平台地址 |
| `bad_ref` | 引用格式不对（蓝湖缺 `pid`/`image_id`；自建平台不是 `/?project=…&design=…` 链接，或 `project`/`design` 缺失、重复、不是正整数） |
| `no_cookie` | 缺登录 cookie（不发任何请求） |
| `cookie_rejected` | 自建平台返回 401：Cookie 无效或已过期 |
| `project_not_found` | 自建平台当前账号看不到链接里的项目（id 不对或无权限） |
| `design_not_found` | 自建平台项目里没有链接里的 UI 设计图（id 不对、已删除或不是 UI 设计图） |
| `bad_design_data` | 自建平台设计稿没有图层、画板根节点不唯一或有图层挂不到根节点（需用新版插件重传），或接口数据结构不符合预期 |
| `request_failed` | 自建平台接口报错 |

`no_cookie` / `cookie_rejected` 是登录环境问题、不是本页输入问题：不要把页面记为失败，
停下按上文更新 cookie 后重跑（无头 job 返回 `blocked`）。

蓝湖适配器另有：`image_meta_failed` / `design_json_failed`（接口报错）、
`empty_artboard`（artboard 节点数 ≤1，版本数据异常——继续走会让 bind 静默绑定 0 节点）。

`design_image`（供模型视觉理解的整页图）就用 `cover.png`。
