# Google Sheets 适配

## 发现工具与定位

优先使用当前可调用的 `mcp__google_sheets__list_sheets`、`get_sheet_data`、`batch_update_cells`，调用前检查当前工具 schema。不修改连接器配置，不执行业务 API。

解析 `/spreadsheets/d/{id}` 的文档 ID、query/fragment 中的 `gid`、`range` 等选择信息。query 与 fragment 对同一参数冲突时报 ambiguous_selector。单行 range 可以选择入口 item；多行选择不擅自变成一个标题。

注意：当前 `list_sheets` 只返回名称列表，不能提供 gid → 名称映射。不得认为 gid 是 tab 序号，不能把 gid=0 猜成 Sheet1。使用支持元数据的已授权工具/API（只请求 sheetId/title）、可访问的浏览器 tab 信息，或用户明确给出的工作表名核实映射。未指定 gid 且仅有一个工作表时可唯一选定；有 gid 却无法核实时说明缺少映射，让用户指定工作表名称。不要仅为取映射暴露凭据。

## 读取

```json
{"spreadsheet_id":"document-id"}
```

传给 `list_sheets`。确定 sheet 后：

```json
{"spreadsheet_id":"document-id","sheet":"Sheet1","include_grid_data":false}
```

传给 `get_sheet_data`，不传 range 取全表。大表可分块，但必须保留每块 A1 起始行列和完整覆盖，不能把片段第一行误认成表头。默认先核实第1行为表头；若不是，定位唯一的标题/交互描述表头行，歧义时停止写入。

CallToolResult 优先读取 structuredContent；否则解析 text JSON。`isError`、API error、无 values、空表是不同结果，明确报告。保留完整原始响应到运行目录；不截断或凭模型重抄多行单元格。归一时带上真实文档/工作表身份。不得用其他表格的成功快照替代失败读取。

## 写回

先执行 sources.md 的比较规则。按新表头计算列号（零基 → A1：0=A、25=Z、26=AA），按重定位后的行号组装范围。默认只发单页交互正文：

```json
{
  "spreadsheet_id":"document-id",
  "sheet":"Sheet1",
  "ranges":{"E8":[["1.页面进入……\n2.点击提交……"]]}
}
```

传给 `batch_update_cells`；E8 仅示例，禁止照抄定位。请求为结构化对象，保持真实换行，不通过 shell 拼接正文。生成文本以编号或文字开头，不将任意来源内容作为电子表格公式写入。

回读已修改单元格及对应标题验证；结果中若有规范化或解析差异，检查真实单元格值，不以屏幕换行差异判失败。超过来源单元格限制时保留完整草稿并报过长，不截断、不扩列。

缺写工具时报告 writer_unavailable，保留 draft；读取成功不证明写权限。权限失败报告原始状态及失败操作，不擅自换账号或更改共享权限。
