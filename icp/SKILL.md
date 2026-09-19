---
name: icp
description: 设计稿到代码的三阶段管线(Codex版)。根据 iole 传入的数据,按目标平台最佳实践实现代码;UI 完整实现设计稿,交互完整按描述实现(行为交互+数据交互)。
---

# ICP(Codex 版)

三阶段管线。模型做语义判断,脚本裁决确定性事实。

icp 每次只处理一个页面；跨页任务的上下文交接遵循 [IOLE 页面执行上下文](../iole/SKILL.md#页面执行上下文)。沿用项目环境、构建缓存与有效共享调查，iole 负责页面调度与共享资源协调。

## 输入契约

icp 不依赖调用方的数据格式。调用方（iole 或人）第一步将数据映射到 icp 自己的输入结构，见 `INPUT.md`。

## 阶段边界

| 阶段 | 输入 | 输出 | 状态 |
|---|---|---|---|
| 1 extract | ui_description + design.json + 设计图 + 切片 | component-spec.json | **已实现** `extract/` |
| 2 交互分析 | component-spec + 交互描述 + API 契约 | component-binding.json | **已实现** `component-design/` |
| 3 代码实现 | Stage 1-2 全部产物 | 代码 + 测试验证 | 规范 `implementation/STAGE.md` |

跨阶段禁令:Stage 2 不得改动语义分组(发现错误→回 Stage 1 重跑);Stage 3 不得新增交互(发现缺失→回 Stage 2)。

## 执行原则

- 所有目标平台使用同一验收标准、证据要求和状态语义；平台适配只决定构建、操作与观测方式。实现阶段按 `implementation/STAGE.md` 执行，不将某个平台的宿主或视图树 API 当成通用要求。
- 优化只做能修正已证实问题的最小完整改动，优先复用现有输入、脚本与记录；不因一次失败增加通用框架、重复台账或审批层级。确定性事实由工具计算，语义覆盖由模型结合实际证据核对，不能以新增勾选项代替质量保证。
- 只读当前阶段所需引用；已冻结的设计、正式 API 合同与共享组件调查按来源版本复用。输入、实现或依赖变化时才更新受影响部分，不能仅凭文件存在认定证据仍有效。恢复上下文或重载时按标题定位当前阶段与变更段；需完整阅读的文档控制单次输出量，不拼接多份长文档超过工具返回上限。输出截断只补读缺失段，不重复整批内容。
- 接口功能须先读取并核实 Apifox 的正式 shape，再实现请求、解析和页面行为；真实地址未就绪只影响联调，不允许凭设计稿推断接口或自动降级为 mock 完成。具体提取与缺口处理见 [API 解析](component-design/STAGE.md#api-解析apifox-为准)。
- 业务数据必须经接口模型绑定到真实页面。默认按 [接口数据渲染与数据源切换](implementation/STAGE.md#接口数据渲染与数据源切换) 实现：已核实正式合同但未配置地址时使用正式 shape 的模拟响应，配置后自动走真实接口，复用同一解析与渲染链；只有用户明确排除此能力时才省略，不以源表未写或未再次提出为由漏掉。
- 固定顺序：先依据 Stage 1/2 一次性完整实现 UI，UI 不做单元/集成测试；再按源交互描述拆解用例，实现行为、接口、埋点及对应代码测试；全部完成后编译、渲染并与设计稿比对。代码用例全部通过且 UI 比对通过后，最后才集中启动一次真实页面操作验收，不按每个用例反复启动。交互实现阶段的代码测试禁止使用模拟器、真机或 UI 自动化；TDD 已选定时遵守 `../tdd/SKILL.md` 的代码测试要求，不提前执行页面操作验收。设计稿比对最多 5 轮，每轮完整检查所有组件和页面级差异，记录全部差异后集中修复；上限不代表验收通过。模拟器/设备只用于后段渲染比对及最后的真实页面操作。具体执行见 [Stage 3](implementation/STAGE.md)。
- 一个页面任务由一个负责人持续推进。写测试、运行、实现是逻辑阶段，不默认拆成多个 worker；采用外部 worker 时遵守项目角色边界。
- 连续的确定性命令在同一执行段完成，失败即停并保留结果；编译、测试和日志提取直接用工具执行，不为每条命令另启模型。没有可并行的实际工作时，按下方 [Waiting for local commands](#waiting-for-local-commands) 对齐内外层原生等待；保留最终退出码与实际执行数量，轮询只读新增摘要。
- 每页使用下方 30 分钟检查点；超限触发复盘优化，不表示验收通过、终止页面或自动降级为 partial。
- 原始日志与大产物落盘。交接只提供当前用例、变更文件、真实测试结果、证据路径和待决策问题；已验收且输入未变的部分不重复探索或追加一轮独立审查。

## Waiting for local commands

When waiting is the only useful next action, use completion-sensitive native
waits. These durations are upper bounds: completion returns immediately.
Preserve the command's existing timeout, cancellation and result checks.

With `exec_command` / `write_stdin` inside `functions.exec`, keep the wrapper's
wait longer than the inner operation. Start a command once:

```javascript
// @exec: {"yield_time_ms": 60000, "max_output_tokens": 2000}
text(await tools.exec_command({cmd: "<command>", yield_time_ms: 30000, max_output_tokens: 2000}));
```

After that wrapper completes, if the command returned a `session_id`, continue
the same process without sending input:

```javascript
// @exec: {"yield_time_ms": 60000, "max_output_tokens": 2000}
text(await tools.write_stdin({session_id: SESSION_ID, chars: "", yield_time_ms: 45000, max_output_tokens: 2000}));
```

If the **wrapper** instead returns `Script running with cell ID ...`, use
`functions.wait` with that `cell_id` and `yield_time_ms: 60000` until the wrapper
completes. A cell ID is not a process session ID. Do not issue another
`write_stdin`, status probe or log read for that same command while its wrapper
is still waiting. Do not omit the outer wait duration or replace it with a
one-second poll, fixed sleep or a command restart.

Respect the exposed host limits and any nearer control deadline. A shorter wait
needs an actual deadline or independent action to perform; unchanged output is
not a reason. Required progress updates reuse available output without launching
another status query. After completion, retain the exit code and actual
executed/passed/failed/skipped counts; silence alone is not success.

## 时间预算与项目经验

只设时间预算，不设 token 预算或额外 token 统计门槛。质量是硬约束：不得为赶时间删减需求、删除有效测试、弱化断言、跳过必要验收或把未完成标成完成；优化只减少重复执行、无效观测和调度开销。执行步骤：

1. 页面开始时在现有 checklist 记录起始时间与 30 分钟检查点；恢复任务沿用原记录，不通过换 worker、阶段或重启会话重新计时。读取项目 `AGENTS.md` 中相关的已有优化约定。
2. 30 分钟尚未完成时，先暂停扩展工作，保留正在运行的有效任务及证据，不随意终止构建。根据命令起止、运行结果和调度记录区分主要时间花在实现、构建/执行、排队、夹具/工具诊断还是重复调度；无数据的占比不估报。
3. 在该页 checklist 简记已完成/缺口、主要耗时及证据、可取消的重复工作、具体优化与需保留的验收。立即实施当前授权范围内的优化并继续原任务；若确有外部阻塞，记录缺失前提，继续独立可做部分。此后每 30 分钟检查一次；一次复盘不新建 worker、不重读整条历史，不演变成长篇审计。
4. 将经证据确认、验证有效且可复用的项目做法精简写入目标项目的 `AGENTS.md`，让后续页面直接复用。写清适用条件、正确入口/方法和必须保留的验收，详细证据只留路径；合并或修订已有条目，不逐次追加日志。假设与待验证方案先留 checklist，不固化为规则；不修改全局 AGENTS、共享 skill 或持久记忆。若项目文件有明确保护门禁则遵守并记录限制，不绕过。

上述检查点由执行者结合原生等待和阶段结果落实，现有脚本不自动计时、复盘或写入项目约定。最终仍按证据完成任务，时间缩短本身不证明质量。

## 过程文件

工作目录: `{project}/.codex/icp/{title}/`

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
Step 5: render_ok, render_time_ms, render_view_nodes
Step 6: struct_texts_matched, struct_components_matched, struct_hierarchy_ok
Step 6: visual_pass, visual_issues, attribution_rounds, attribution_breakdown
Step 7: behavior_passed, behavior_failed

详见 `implementation/STAGE.md`。

### 验证

阶段检查可在同一执行段顺序运行 `python3 component-design/scripts/check.py <checklist> --step N`，未通过不进入依赖它的阶段；不为每个勾选项单独调用模型。

check.py 只验证记录的勾选与非空值，不证明编译、测试或视觉通过。行为证据必须来自真实执行；规则局限及替代证据按 Stage 3 记录，不能伪造脚本 PASS。

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
