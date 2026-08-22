---
name: icp
description: 设计稿到代码的三阶段管线(Claude版)。根据 iole 传入的数据,按目标平台最佳实践实现代码;UI 完整实现设计稿,交互完整按描述实现(行为交互+数据交互)。
---

# ICP(Claude 版)

三阶段管线。模型做语义判断,脚本裁决确定性事实。

## 输入契约

icp 不依赖调用方的数据格式。调用方（iole 或人）第一步将数据映射到 icp 自己的输入结构，见 `INPUT.md`。

## 阶段边界

| 阶段 | 输入 | 输出 | 状态 |
|---|---|---|---|
| 1 extract | ui_description + design.json + 设计图 + 切片 | component-spec.json | **已实现** `extract/` |
| 2 交互分析 | component-spec + 交互描述 + API 契约 | 交互绑定 | 规范 `component-design/STAGE.md` |
| 3 代码实现 | Stage 1-2 全部产物 | 代码 + 测试验证 | 规范 `implementation/STAGE.md` |

跨阶段禁令:Stage 2 不得改动语义分组(发现错误→回 Stage 1 重跑);Stage 3 不得新增交互(发现缺失→回 Stage 2)。

## Stage 1 — extract

```
python3 extract/scripts/bind.py <cmd> ...
```

流程:prepare → 模型语义分组 → bind(完备性循环) → clean → enrich → crop。
详见 `extract/STAGE.md`。
