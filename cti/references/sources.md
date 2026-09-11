# 来源路由及统一读写约定

用标准 URL 解析器（如 Python `urllib.parse`）检查 scheme、hostname 和 path；不能按字符串包含域名匹配。拒绝伪装子域名、URL 用户信息、无法解释的文档路径。相对本地路径针对用户指定 cwd 解析。

| 链接 | 来源 | 处理文档 |
|---|---|---|
| https://docs.google.com/spreadsheets/d/{id}/... | google-sheet | [Google Sheets](google-sheets.md) |
| 本地 .json 路径 | local-json | [本地 JSON](local-json.md) |
| https://alidocs.dingtalk.com/... | dingtalk | 识别来源，当前无内置读写适配；报告 adapter_unavailable |
| https://feishu.cn/sheets/...、*.feishu.cn/sheets/...、对应 larksuite.com 域名 | feishu-sheet | 识别来源，当前无内置读写适配；报告 adapter_unavailable |
| 其他 | unknown | 报告 unknown_source；不以 Google Sheets 方法试写 |

不因识别到飞书/钉钉链接就假定已有连接器。用户要求接入新来源时，发现当前可用工具并实现下面的映射、读写和验证约定后，新增一个适配文档及此表的一项。只增加域名规则不算实现适配。读写能力分别声明，只有读取能力也可以完成 draft。

## 统一快照

每个适配器将来源转成以下业务结构；兼容 ICP 字段名，不要求 ICPS 的角色和租约列：

```json
{
  "source": {"kind": "google-sheet", "document_id": "document-id", "sheet_id": "0", "sheet_name": "Sheet1"},
  "headers": ["标题", "Route", "交互描述"],
  "rows": [{
    "locator": {"row_number": 8},
    "title": "登录",
    "payload": {
      "route": "signin",
      "ui_description": "",
      "interaction_description": "原始多行文本",
      "api_description": null
    }
  }]
}
```

必需表头只有「标题」「交互描述」，Route、UI补充描述、设计稿地址、接口描述均可缺省。缺 Route 时靠内容和调用链定位。缺必需列或重名列时阻止该表写回，不自动建列。

保留原始值用于比较，不 trim 交互正文。标题查找可用去掉首尾空白的索引，但写回保留原始标题；规范化后重复也属于歧义。

接口操作由模型通过当前暴露的连接器执行，行列计算、重复检测、JSON 序列化、SHA-256 和值比较用 JS/Python 标准库等确定性工具完成，避免人工估算行数或列字母。无需复制 ICPS 的状态迁移脚本。

## 变更记录与一致性

每个 patch 记录 source、title、字段名、当前 locator、生成时原值、拟写新值、代码指纹和状态。只有 `ready` 项可以进入写回。

1. 写前读取新快照，确认文档/工作表身份及标题唯一性；重新按标题、表头定位，不沿用旧行号。
2. 定位后的旧正文必须与原值完全一致；Route/UI/其他参与匹配的输入发生变化时也要重新分析。发现冲突不覆盖。
3. 写前核对相关代码文件指纹；分析后已变化则重新提取。
4. 当前值已等于拟写值时记录 verified/no-op；无需重复写。否则只写授权字段。
5. 写后回读目标标题和单元格，按实际值逐项标 verified 或 failed。工具成功响应不替代回读。
6. 网络超时等结果不明时先读：等于新值则 verified；等于旧值时可重新定位后有限重试一次；等于其他内容则 conflict。禁止盲重放整批。

无服务端条件更新能力时，写前比较只能缩小并发窗口，不能声称 CAS 或远程原子锁。失败不能标整批成功。原文快照是恢复依据，不自动回滚覆盖用户后续编辑。
