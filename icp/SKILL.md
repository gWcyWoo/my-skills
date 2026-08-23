---
name: icp
description: 设计稿到代码的三阶段管线(Claude版)。根据 iole 传入的数据,按目标平台最佳实践实现代码;UI 完整实现设计稿,交互完整按描述实现(行为交互+数据交互)。
---

# ICP(Claude 版)

三阶段管线。模型做语义判断,脚本裁决确定性事实。

icp 每次只处理一个页面。并行化由 iole 编排多个 agent 实现,不得将多个页面传给同一个 icp 批处理。

## 输入契约

icp 不依赖调用方的数据格式。调用方（iole 或人）第一步将数据映射到 icp 自己的输入结构，见 `INPUT.md`。

## 阶段边界

| 阶段 | 输入 | 输出 | 状态 |
|---|---|---|---|
| 1 extract | ui_description + design.json + 设计图 + 切片 | component-spec.json | **已实现** `extract/` |
| 2 交互分析 | component-spec + 交互描述 + API 契约 | component-binding.json | **已实现** `component-design/` |
| 3 代码实现 | Stage 1-2 全部产物 | 代码 + 测试验证 | 规范 `implementation/STAGE.md` |

跨阶段禁令:Stage 2 不得改动语义分组(发现错误→回 Stage 1 重跑);Stage 3 不得新增交互(发现缺失→回 Stage 2)。

## 过程文件

工作目录: `{project}/.claude/icp/{title}/`

每次运行在此目录记录过程数据，用于收敛验证和事后复盘优化。

### 文件

| 文件 | 产出阶段 | 说明 |
|---|---|---|
| stage1-checklist.md | Stage 1 | Stage 1 流程验证 + 复盘 |
| stage2-checklist.md | Stage 2 | Stage 2 流程验证 + 复盘 |
| stage3-checklist.md | Stage 3 | Stage 3 流程验证 + 复盘 |
| component-spec.json | Stage 1 | 语义分组输出 |
| component-binding.json | Stage 2 | 组件绑定 + 交互输出 |

各阶段 checklist 独立文件，check.py 分别验证，互不干扰。

### checklist 各阶段记录项

**Stage 1** (extract):

| 项 | 内容 |
|---|---|
| pages_loaded | 加载的设计页面数 |
| groups_extracted | 语义分组数量 |
| bind_rounds | completeness 收敛轮数 |
| members_complete | 所有 group 成员绑定完整 |

**Stage 2** (component-design):

Step 1: platform, scanned_dirs, shared_components
Step 2: groups_bound, new_reuse_scan, extract_shared_scan, affected_complete, check_binding
Step 3: apis_parsed, interactions_decomposed, coverage_verified, flow_traced, fields_verified, check_interactions

详见 `component-design/STAGE.md`。

**Stage 3** (implementation):

Step 1: blueprint_components, blueprint_texts, blueprint_assets, blueprint_layouts
Step 2: contract_apis, contract_interactions, contract_components
Step 3: gen_files, gen_platform, gen_unit_strategy, gen_route_registered
Step 4: compile_rounds, compile_errors, compile_time_ms
Step 5: render_ok, render_navigation, render_time_ms, render_view_nodes
Step 6: struct_texts_matched, struct_components_matched, struct_hierarchy_ok
Step 7: visual_pass, visual_issues
Step 6-7 loop: attribution_rounds, attribution_breakdown
Step 8: behavior_passed, behavior_failed

详见 `implementation/STAGE.md`。

### 验证

每步完成后: `python3 component-design/scripts/check.py <checklist> --step N`，未通过不放行。

check.py 是通用 markdown checklist 验证器，各阶段共用。当前位于 `component-design/scripts/`，后续阶段实现时按需上提到 `scripts/`。

### 复盘数据点

| 指标 | 来源 | 优化信号 |
|---|---|---|
| 收敛轮数 | check_binding / check_interactions / bind_rounds | 高轮数 → 指令或约束需改进 |
| 组件复用率 | shared_components + extract_shared_scan | 低 → 项目组件化不足或扫描不充分 |
| 覆盖完整性 | coverage_verified | 漏覆盖 → 交互描述质量 |
| 跨阶段回退 | 阶段间回退记录 | 频繁 → 上游输出质量问题 |
| 编译修复轮数 | step4.compile_rounds | 高 → 代码生成 prompt 需改进 |
| 文案覆盖率 | step6.matched/expected | 低 → 蓝图提取或代码生成遗漏 |
| 归因分布 | step8.attributions | semantic 多 → 上游质量; codegen 多 → 生成能力 |
| 行为通过率 | step9.passed/total | 低 → 交互实现或接口契约质量 |
| 单页总耗时 | stage3-metrics.json | 基线,跨页面对比 |

## Stage 1 — extract

```
python3 extract/scripts/bind.py <cmd> ...
```

流程:prepare → 模型语义分组 → bind(完备性循环) → clean → enrich → crop。
详见 `extract/STAGE.md`。

## Stage 2 — 组件化 + 交互绑定

```
python3 component-design/scripts/validate.py <cmd> ...
python3 component-design/scripts/check.py <checklist> [--step N]
```

流程:识别平台+扫描组件 → 组件匹配+check-binding收敛 → 交互拆解+check-interactions收敛。每步完成填 checklist，check.py 验证放行。
详见 `component-design/STAGE.md`。
