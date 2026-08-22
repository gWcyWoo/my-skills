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
| `interaction_description` | Stage 2 | 是 | 交互描述（自然语言，含跳转/弹窗/API 触发） |
| `api_description` | Stage 2 | 是 | 接口描述（端点 + 参数 + 响应） |
| `ut` / `it` / `e2e` | Stage 3 | 否 | 测试要求 |

## 映射规则

调用方的第一步是将自己的数据映射到本结构：

- `design_image` / `design_json` / `slices_json` / `cover_image` 是运行时路径，由调用方在调 icp 之前准备好（下载设计稿、调蓝湖 API 取切片、截图）
- `ui_description` 为空时传 `null` 或空串，Stage 1 正常工作
- 字段为空归一为 `null`，不用空串
