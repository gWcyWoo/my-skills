# 统一行格式 `iole-item.row`

任何后端(Google Sheets / 钉钉 icpd / 飞书 icpf / 本地 JSON)都必须返回这个形状。
iole 与 icp 只认这个形状,后端切换时两者零改动。

```json
{
  "row_id": "r8",
  "title": "登录",
  "payload": {
    "route": "signin",
    "design_urls": ["https://lanhuapp.com/..."],
    "ui_description": "结构分为4部份...",
    "interaction_description": "4.1 ... \"toggle: 客服弹窗\" ...",
    "ut": "", "it": "", "e2e": "",
    "api_description": "/auth/otp-requests",
    "prn_id": ""
  },
  "roles": {
    "frontend": {"status","pr","reviews","last_error","lease_token","lease_until"},
    "backend":  {"status","pr","reviews","last_error","lease_token","lease_until"}
  }
}
```

- `title` 是**交互引用的唯一键**:`toggle:/redirect:/reference:` 按 title 查行,故 title 必须全表唯一(重复即报 `duplicate_title` 停机)。
- `design_urls` 是数组:一行可挂多张设计稿(如"权限声明"有 2 张)。非 http(s) 内容(如"无")丢弃。
- 角色字段值为空时归一为 `null`,不是空串——`status=null` 表示该角色此行不可领取。
- `row_id` = `r<表格行号>`,始终能指回原表格行。

## Google Sheets 列映射

表头**按名字**匹配,不按位置(生产表中 frontend/backend 的 status/pr/reviews 与
last_error/lease_* 并不连续,按位置映射会静默错位)。缺列即停机 `missing_column`。

| 表头 | 字段 |
|---|---|
| 标题 | title |
| Route | payload.route |
| 设计稿地址 | payload.design_urls |
| UI补充描述 | payload.ui_description |
| 交互描述 | payload.interaction_description |
| UT / IT / E2E | payload.ut / it / e2e |
| 接口描述 | payload.api_description |
| PRN ID | payload.prn_id |
| `<role> status/pr/reviews/last_error/lease_token/lease_until` | roles.`<role>`.* |

角色取值:`frontend`、`backend`。
