---
name: iFF
description: Use when an external `goal` command drives batch implementation of Flutter frontend from a design-spec sheet (CSV/Excel). `iFF` = implement Flutter Flow. 读表 → 并行扇出每行一个 subagent 实现各自 feature → 串行扇入集成(依赖/资产/路由/codegen/analyze)→ 回写。落地到当前 Flutter 工程, 触发于 "iFF"批处理设计稿表格。
---

<role>
iFF 在 MAIN session 运行,是**编排者**:被外部 `goal` 指令调起(goal 设目标 + 验收标准),读取设计稿表格,**并行扇出**——每个未处理行一个 subagent 实现其对应 feature——再**串行扇入**集成共享改动(依赖/资产/路由/codegen/analyze),最后逐行回写结果。落地到 iFF 运行时的当前 Flutter 工程,遵循其架构/规范。取代旧 fc。
</role>

<context>
## 调用与分层(已确认)
- `goal` 是**外部指令**(非本仓库 skill):设定目标 + 最终验收标准,调起 iFF。iFF 不实现 goal,只被它驱动。
- iFF 自身是编排者,内部用**并行 subagent(Claude Code Agent 工具扇出/扇入)** 处理全表;不再是"外部喂一行"的单行 worker。
- 工具适配(Claude Code):每行 worker 用 `Agent` 工具创建(`subagent_type: "general-purpose"`,`prompt` 传入 `worker_prompt.md` 全文);并行扇出 = 在同一条消息里发起多个 `Agent` 调用;`Agent` 调用返回即收到该 worker 结果(无需显式 wait/close);需要补充输入时用 `SendMessage` 发给该 agent。主会话只汇总结果并执行串行扇入。
- 子 agent 不会天然继承 main session 已加载的 skill 正文。每个 worker 的 spawn prompt 必须由 `make_worker_prompt.py` 生成,并强制 worker 先读 `iFF/SKILL.md` 与 `iFF/test_rules.md`;worker 必须写 `worker_compliance.json`,main 扇入前用 `check_worker_compliance.py` 校验。禁止手写短 prompt 直接 spawn worker。

## 输入:设计稿表格(CSV/Excel)
- goal 指向一张表;**iFF 读表**挑未处理行(此前曾设想外层读,现并入 iFF)。
- 每行字段:
  - `title` 标题 / `design_url` 蓝湖地址 / `ui_notes` UI补充 / `interaction` 交互 / `api` 接口 —— 实现输入
  - `status` —— **控制列 / 工作队列状态**:**空 = 未处理(仅选这种)** → `doing`(选中即刻标记,认领/防重/可断点续)→ `done`(成功)/ `error`(失败,详情写 `error` 列)。iFF 读写。
  - `error` —— 控制列(失败时回写错误详情)
	  - `spec_dir` —— 缓存列(取稿产物目录;iFF 回写,命中且内含 `reference.png`、`scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`、`interaction_contract.json`、`interaction_test_plan.json` 才可跳过取稿/交互编译)
  - `visual_report` / `actual_screenshot` / `visual_manifest` —— 可选缓存列(视觉 QA 报告、最终运行截图、证据来源 manifest 路径;iFF 有列则回写)

## 执行架构:扇出实现 + 扇入集成(已确认)
**并行硬约束**:工程共享改动点(`pubspec.yaml` 依赖/资产、路由/导航表、DI、主题、l10n、`build_runner`、`flutter analyze`)**不能并行写**,否则互相踩踏。故:
- **扇出(并行,先定每批 2 个互不影响的功能;一行一个 subagent)**:
  - 取设计稿与编译交互:只允许调用 `~/.claude/skills/iFF/scripts/` 下脚本,得 `spec_dir`(`reference.png`+`scene.json`+`groups.json`+`tokens.json`+`assets_manifest.json`+`interaction_contract.json`+`interaction_test_plan.json`+`visual_manifest.json`+`spec.md`+`raw.json`+`assets/`);`reference.png` 优先用 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 下载完整 `FigmaCover*.png`,不得只用 export slice;`spec_dir` 缓存命中但缺机器可读视觉/交互产物仍视为失败,不得进入实现。
  - **规则注入 + TDD + 视觉编译实现**(见下「单行实现:TDD」):main 先生成 worker prompt 并 spawn;worker 先产出 `worker_compliance.json` → 按 `interaction_test_plan.json` 写测试证明 red → 以 `scene.json`/`groups.json`/`tokens.json`/`assets_manifest.json` 为主输入实现到 green → 重构;只写**自己那个 feature 文件夹**(文件不相交、无需 worktree),**不动任何共享文件**。
  - **视觉 QA(P0 硬门,单次修复预算)**:green 后运行目标页面/Widget,按目标 viewport 截图并写 `visual_manifest.json`;截图与 `reference.png` 对比,产出 `visual_report.md` 和 `repair_plan.json`;只允许按 `repair_plan.json` 修改一次并重新截图/复验。复验无 P0/P1 才返回成功;复验仍有 P0/P1 时返回失败摘要,该行写 `error` 后进入下一需求。`actual_source=generated_from_reference` 是无效 actual 证据,不得返回成功。
  - 返回:本 feature 需要的「依赖 / 资产清单 / 要注册的路由·DI」+ `spec_dir` + `worker_compliance` + `interaction_test_evidence` + `visual_report` + `actual_screenshot` + `visual_manifest` + 成功/失败。
- **扇入(串行,一次性)**:汇总去重 → `pub add` 依赖 → 拷贝资产并注册到 `pubspec.yaml` → 注册所有路由/DI → `build_runner` → `flutter analyze` → **主会话真实设备最终视觉验收**。
- **回写**:逐行把 `status`/`error`/`spec_dir` 写回表格;若有 `visual_report`/`actual_screenshot`/`visual_manifest` 列也写回。

## 规则资产(复用 fc)
- `~/.claude/skills/fc/development_rules.md`(`DEV-*`,高优先级项目规则)
- `~/.code/shared-rules/frontend/flutter-widget.md`(`FW-*`,按 ID 精确查,勿整读)
- 冲突时 `development_rules.md` 优先;复用 fc 的"按 ID 精确查询、限量阅读"纪律。

## 单行实现:TDD +「读项目、随项目」(已确认)
**iFF 只定流程,不定实现细节。** 架构、目录结构、命名、资产/路由/状态/接口接入口径 —— **一律不由 iFF 规定**,由 subagent 在实现时**充分阅读当前工程**后**与既有约定保持一致**(随项目,不自创、不硬编码某套架构)。

每个 subagent 对自己这一行,必须逐步执行 `<pipeline>`。不得跳步、合并步骤、只读自然语言 `spec.md`、凭截图自由发挥,或在缺少任一固定输出时继续实现。若本段与 `<pipeline>` 冲突,以 `<pipeline>` 为准。

- **全自主**:无用户 gate/STOP;以"测试确实先 red 过"为硬证据自证。
- **选行**:每批读 **N 行**(默认 N=2)**status 为空**的行;选中后**立即把这几行 status 改为 `doing`**(认领、防重、可断点续);文件层面已隔离,无需功能依赖分析。
</context>

<instructions>
1. **接收 goal**:从外部 `goal` 指令拿到目标 + 验收标准 + 目标表格路径。
2. **读表 + 认领**:解析 CSV/Excel,挑 **status 为空**的行,每批取 **N 行(默认 2)**;**立即回写这几行 status=`doing`**(认领,防重复处理 / 支持断点续跑)。
3. **扇出(Claude Code Agent 工具并行,先定每批 2 个互不影响的行)**:每行一个 subagent,按序 —— make_worker_prompt → spawn worker → worker 读取 iFF 规则并写 compliance → classify_design → fetch_reference_and_scene → generate_layout_contract → generate_visual_fixture → parse_interactions → generate_interaction_tests_plan → write_implementation_plan → implement_from_scene_tree → map_design_nodes_to_widgets → run_widget_tests → 返回依赖/资产/路由清单 + `spec_dir` + worker compliance + implementation_plan + layout/fixture/交互覆盖/视觉证据 + 结果。模型负责补全业务逻辑和工程接入,视觉实现必须由机器产物和 diff 驱动。
4. **扇入(串行集成)**:去重汇总 → `pub add` 依赖 → 资产拷贝 + pubspec 注册 → 注册路由/DI → `build_runner` → `flutter analyze` → 启动 emulator/simulator → `flutter run` → `adb screencap` 或 `xcrun simctl io booted screenshot` 获取最终 `actual.png` → crop 到 app viewport → 与 `reference.png` 尺寸对齐 → `run_visual_diff` 输出 `diff_report.json` → `make_repair_plan` 输出 `repair_plan.json` → 按 `repair_plan.json` 修改一次 → 重新截图/重新 diff → 最终运行截图验收。每行最多一次 repair,不得循环打磨;单次 repair 后仍不达标则该行 `status=error`,继续下一需求。
5. **回写(完成)**:逐行把 status `doing`→`done`(成功)或 `error`(失败,详情写 `error` 列),并写 `spec_dir`;若表中已有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,写入最终视觉证据路径。
6. **验收**:对照 goal 的验收标准核对(`analyze` 无 error、各行达标、最终视觉验收无 P0/P1 问题)。
</instructions>

<pipeline>
## 固定流水线(P0)
iFF 是设计稿编译器 + 模型补全业务逻辑 + 真机截图 diff + 单次 repair 复验。模型不直接“看图写 UI”;模型只读 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`、`repair_plan.json` 来写和修代码。
当前 `raw.json` 的主数据是 `figma_json.artboard`;一律走 Figma JSON 专用编译器 `export_figma_scene.py` / `group_figma_layout.py` / `make_figma_layout_contract.py`,不得用 generic JSON walk + bbox/name 启发式。
	所有确定性环节必须由本 skill 目录脚本保证,脚本唯一合法目录是 `~/.claude/skills/iFF/scripts/`;禁止引用 `fd/scripts`、项目本地 `scripts/` 或临时脚本。确定性环节包括:worker prompt 生成/合规校验、设计获取/cover 下载、分类、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、设计产物总审计、fixture 生成、interaction contract/test plan、交互覆盖审计、资产复制/pubspec 注册、真机截图/manifest、视觉 diff、repair plan、manifest/fixture/render plan 审计。

### 脚本预检
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/verify_pipeline_scripts.py --skill-dir ~/.claude/skills/iFF
```
输出: 确认流水线脚本全部存在于 `~/.claude/skills/iFF/scripts/`。
硬门: 任一脚本缺失或引用本 skill 外脚本,立即 `error`,不得进入实现。

### Worker 启动合同
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/make_worker_prompt.py --row-json spec_dir/row.json --spec-dir spec_dir --project-root . --out spec_dir/worker_prompt.md
# Claude Code 编排者用 Agent 工具发起 worker(并行扇出时在同一条消息内多次 Agent 调用):
# Agent(subagent_type="general-purpose", prompt="$(cat spec_dir/worker_prompt.md)")
python3 ~/.claude/skills/iFF/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.claude/skills/iFF
```
输出: `worker_prompt.md`、`worker_compliance.json`。
硬门: main 不得手写短 prompt 直接 spawn worker;worker 未证明读取当前 `iFF/SKILL.md`、`iFF/test_rules.md`、未通过 pipeline scripts 预检、或 hash 与当前 skill 不一致时,该 worker 结果作废并重跑;不得进入扇入。

### 0a. 归属判定(Track B 入口,新页面 / 状态变体 / 复用)
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/reconcile_feature.py --lib-root lib --title "$ROW_TITLE" --out spec_dir/reconcile_decision.json
```
输出: `reconcile_decision.json`(现有 feature 清单 + 候选匹配 + 待模型填的 `decision`)。
硬门: 写任何组件前必须先定归属。脚本只做确定性清单;**模型必须读懂业务是否相同**再设 `decision` 为 `new` / `extend:<feature>` / `variant:<feature>`。同一屏不同状态的多张设计稿应作为既有 feature 的**变体**(加一态 + 一张 golden),不得复制成新页面。

### 0. 设计分类
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/classify_design.py --raw spec_dir/raw.json --reference spec_dir/reference.png --out spec_dir/design_classification.json
```
输出: `design_classification.json` 包含 `type`(`screen`/`variant_board`/`component_sheet`/`flow_board`)、`artboard`、`viewport`、`states`、`reason`。
硬门: `screen` 按单页面实现;`variant_board` 必须实现同一组状态 fixture;`component_sheet` 不能直接当 App 首页;分类不确定时不能编码。

### 1. 获取完整设计稿
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/fetch.py --url "$DESIGN_URL" --parent-dir lanhu/specs
python3 ~/.claude/skills/iFF/scripts/write.py --input spec_dir/raw.json --output spec_dir/spec.md
python3 ~/.claude/skills/iFF/scripts/download_cover.py --url "$DESIGN_URL" --out spec_dir/reference.png
```
输出: `raw.json`、`spec.md`、完整 artboard `reference.png`。
硬门: `raw.json` 必须包含 `figma_json.artboard`;`download_cover.py` 必须从 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 取完整 cover;`reference.png` 尺寸必须等于 artboard;不能用 export slice 冒充完整 reference。

### 2. 导出 Figma scene/tokens/assets_manifest
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/export_figma_scene.py --raw spec_dir/raw.json --assets spec_dir/assets/manifest.json --out spec_dir/scene.json
python3 ~/.claude/skills/iFF/scripts/check_figma_scene.py --scene spec_dir/scene.json
python3 ~/.claude/skills/iFF/scripts/export_tokens.py --scene spec_dir/scene.json --out spec_dir/tokens.json
python3 ~/.claude/skills/iFF/scripts/export_assets_manifest.py --scene spec_dir/scene.json --out spec_dir/assets_manifest.json
```
输出: `scene.json`、`tokens.json`、`assets_manifest.json`;每个节点必须从 `figma_json.artboard.layers` 编译,保留真实 `id/path/parent/children/type/figmaType/bbox/z/depth/visible/effectiveVisible/opacity/blendMode/fills/rawFills/solidFills/gradientFills/imageFills/border/radius/shadow/effects/blur/mask/maskType/clipsContent/constraints/layout/exportSettings/componentId/componentProperties/variantProperties/isInstance/absoluteTransform/relativeTransform/exportable/asset`;文字节点还必须含 `text/fontSize/weight/lineHeight/paragraphSpacing/textStyle/textRuns`;图片/图标节点必须有 asset 映射。
硬门: `scene.sourceSchema` 必须是 `lanhu_figma_json`;主视觉节点没有 bbox、颜色、文字或 asset 映射时不能实现;worker 不能只读 `spec.md`;颜色、字号、圆角、阴影、资产清单必须来自机器产物,不得凭感觉补。

### 3. 自动分组 groups.json
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/group_figma_layout.py --scene spec_dir/scene.json --out spec_dir/groups.json
```
输出: `groups.json`,优先来自 Figma hierarchy,每个 group 保留 `node/path/parent/children/bbox/depth/source=figma_hierarchy`,并分类为 `header`、`loan_card`、`list`、`form`、`button_group`、`support_section`、`bottom_tabs`、`repeated_region`、`region`。
硬门: 分组必须先尊重 Figma group/component/layer hierarchy,只能用 bbox/name 作为辅助;重复卡片数量必须和 reference 一致;`variant_board` 下所有状态必须被识别出来。

### 4. 生成 layout_contract/render_plan
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/make_figma_layout_contract.py --scene spec_dir/scene.json --groups spec_dir/groups.json --out spec_dir/layout_contract.json
python3 ~/.claude/skills/iFF/scripts/make_render_plan.py --scene spec_dir/scene.json --assets spec_dir/assets_manifest.json --layout spec_dir/layout_contract.json --out spec_dir/render_plan.json
python3 ~/.claude/skills/iFF/scripts/check_design_artifacts.py --spec-dir spec_dir
```
输出: `layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`;`layout_contract` 必须来自 Figma hierarchy,记录每个组件的设计节点、path、bbox、children/descendants relative bbox、主要 node -> widget 预期映射;`render_plan` 规定每个节点用 `image_png`/`image_webp`/`svg`/`asset`/`text`/`shape`/`oval_shape`/`gradient_shape`/`image_fill`/`vector_shape`/`shape_container`/`interactive_hit_area`/`clip_group`/`mask_group`/`covered_by_asset`/`covered_by_text`/`hidden` 哪种方式实现。
硬门: 主要文字、按钮、图片、装饰角没有 widget mapping 时不能编码;每个 widget 必须能追溯到设计节点 id;`render_plan` 不得出现整张 reference/artboard 背景;交互热区只能覆盖真实视觉节点,不能替代视觉实现。`check_design_artifacts.py` 必须确认 reference/raw/scene/classification artboard 尺寸一致,groups/layout/render/assets 的 node id 都能回溯到 `scene.json`,variant_board 状态/分组数量足够,required render node 都有 layout widget mapping;失败时不得写 `implementation_plan.json`。
语义: `image|image_png|image_webp|svg|asset` 是独立导出资产,必须作为原子可见层渲染,其 descendants 不再单独画;`image_fill` 必须按 Figma image fill 处理,不得用纯色占位;`gradient_shape` 必须保留渐变方向/stop,不得降级成单色;`vector_shape`/`shape_container` 必须按 Figma bbox、fill、border、radius、shadow/effects 实现;`clip_group`/`mask_group` 是裁剪/遮罩语义,不能随意扁平成普通 Container;`covered_by_asset` 和 `covered_by_text` 不是可见 widget;`text` 必须渲染 scene/render data 的真实字符串和样式,禁止黑色矩形占位;`oval_shape` 必须按椭圆绘制,禁止用 bbox 矩形代替。

### 5. 生成同源 visual fixture
命令:
```bash
# 同源设计 fixture:内容=设计稿展示值(消费 6.7 generate_canvas 各状态产出的 <canvas>.dart.slots.json
# 种子),**故须在 6.7 各可见状态画布生成之后运行**;feature-agnostic,一状态一个 --slots。
python3 ~/.claude/skills/iFF/scripts/make_visual_fixture.py --feature <feature> \
  --slots <state>=lib/<feature>/presentation/<state>_canvas.dart.slots.json \
  [--slots <state2>=...] --out lib/<feature>/data/<feature>_visual_fixture.dart
```
输出: `visual_fixture.dart` 或 `visual_fixture.json`。
硬门: App、widget test、visual test、preview/mock repository 都只能 import 同一份 fixture;测试里自己造数据失败;App shell 只返回一个默认状态失败;设计稿有 9 张卡片而 runtime fixture 少于 9 张失败。

### 6. 编译 interaction 列
命令:
```bash
printf '%s' "$ROW_INTERACTION" > spec_dir/interaction.txt
python3 ~/.claude/skills/iFF/scripts/parse_interactions.py --input spec_dir/interaction.txt --out spec_dir/interaction_contract.json
# 契约完整性门(不变量④:每条交互规则都要覆盖):被丢进 ignoredItems 里、却带"触发+效果"信号的句子
# 必须被提取成规则,或显式登记到契约的 acknowledgedNonRules——否则 100% 覆盖只是"残缺清单的 100%"。
python3 ~/.claude/skills/iFF/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_completeness_report.json
python3 ~/.claude/skills/iFF/scripts/make_interaction_tests_plan.py --contract spec_dir/interaction_contract.json --api-contract apifox_contract.json --out spec_dir/interaction_test_plan.json
```
输出: `interaction_contract.json`、`interaction_test_plan.json`、`interaction_completeness_report.json`;每条交互规则都有稳定 `INT-xxx` id,每条规则生成 `HAPPY`/`BOUNDARY`/`FAILURE` 三类测试 case id。
硬门: `interaction` 非空但无法解析触发动作或期望结果时,该行 `status=error`;不得让 worker 自由解释。**`check_interaction_completeness` 必须通过**(无未提取的规则状句子);生成的 case id 必须进入测试名或测试注释,否则 done 前覆盖审计失败。

### 6.5 计划阶段:对齐设计稿与当前工程
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
```
输出: `spec_dir/implementation_plan.json`。
硬门: 写任何测试或生产代码前必须先产出计划。计划必须来自当前工程和机器产物,不得凭自然语言猜。最少包含:
- `artifactInventory`: `design_classification.json`、`scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`、`interaction_contract.json`、`interaction_test_plan.json` 的存在性、顶层 schema key、节点/分组/资产/测试用例数量。
- `designAlignment`: `sourceSchema=lanhu_figma_json`、artboard/viewport 尺寸、`screen|variant_board|component_sheet|flow_board` 分类、每个 Figma hierarchy layout region/state 的 bbox、node→widget 预期映射、`requiredVisibleNodeCount`、`textNodeCount`、`imageNodeCount`、`shapeNodeCount`、`assetAtomicNodes`、`coveredNodes`、`renderImplementationTypes`,以及 `coordinateRenderStrategy`:以 `render_plan` bbox 为唯一可见层坐标源的固定 artboard Stack。
- `nodeCoveragePlan` 或 `regionNodeCoverage`: 每个 region 内 required visible render node(`shape`/`oval_shape`/`gradient_shape`/`vector_shape`/`shape_container`/`image_png`/`image_webp`/`image_fill`/`svg`/`asset`/`text`) 的数量、必须实现节点清单、允许合并/跳过理由、每类节点的绝对定位渲染方式。只列 region bbox、不列节点覆盖的计划无效。
- `projectAlignment`: 当前工程入口、App shell、已存在/缺失的 feature 目录、worker 扇出允许写的文件、必须留给串行扇入的共享文件(pubspec/路由/DI/codegen)。
- `fixtureAlignment`: runtime、widget test、preview/mock repository 共同使用的 fixture 来源;`variant_board` 必须列出所有状态及卡片数量,少状态计划无效。
- `traceAndRepair`: `implementation_map.json` 与 `actual_layout_trace.json` 的生成策略,截图/diff/repair plan 命令,`singleRepairBudget=1`,以及单次 repair 后的 `post_repair_diff_report.json` 记录策略。
- `forbiddenShortcuts`: 禁止整图铺底、reference 派生 actual、Material 默认图标/占位图替代、测试自造数据、并行改共享文件。
若表格指定的路径在当前工程不存在,计划必须明确缺口并给出最小随项目脚手架;不得假装已有结构存在。若机器产物实际 schema 与本说明文字不一致,以实际 schema 为准并在计划中记录差异。

### 6.6 注入项目实现规范到 CLAUDE.md(确定性,P0)
落地工程前必须把实现规范注入目标工程 `CLAUDE.md`,让所有 agent(含本 worker)统一遵守:
```bash
python3 ~/.claude/skills/iFF/scripts/sync_project_rules.py --rules ~/.claude/skills/iFF/implementation_rules.md --project-root .
```
worker 必须**先加载 `iFF/implementation_rules.md`(权威源)**并在 `worker_compliance.json` 记录,所有可见层实现按 `IMPL-*` 规则执行。

### 6.7 脚本生成响应式画布 + 颜色 token + 字体(确定性,P0)
可见层生成是**确定性的,必须脚本化**——禁止模型手写。`generate_canvas.py` 走**关系换算**:每个尺寸/位置都是「设计像素 × u」,`u = LayoutBuilder.maxWidth / 设计宽度`(`IMPL-LAYOUT-1`),设计宽度下 1:1 还原(供视觉 QA),真机按比例自适应;颜色全抽到 `app_colors.dart`(`IMPL-TOKEN`),不写死宽高/`scale`(`IMPL-LAYOUT-2`),不加 `TextStyle.height`(`IMPL-LAYOUT-4`),按区域拆 widget(`IMPL-COMP-1`),中文注释(`IMPL-DOC`)。
命令:
```bash
# 1) 编译可见层 + 颜色 token(响应式;资产前缀走 assets/images/,IMPL-ASSET-2)
# 先产组件清单(只需 render_plan + classification),供 generate_canvas 标记动态文本槽:
python3 ~/.claude/skills/iFF/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.claude/skills/iFF/scripts/generate_canvas.py --render-plan spec_dir/render_plan.json \
  --classification spec_dir/design_classification.json --component-manifest spec_dir/component_manifest.json \
  --out lib/<feature>/presentation/home_artboard_canvas.dart --colors-import app_colors.dart --asset-prefix assets/images/
# 产物含:可见层 dart(动态槽 = Text(slotText['<id>'] ?? '设计值'))、<out>.expected.json(保真基准)、
# <out>.slots.json(设计种子 fixture:槽节点id->设计展示值,不变量⑦)。上层页面/同源 fixture 用 slots.json 初始化。
# 2) 资产复制到 assets/images/ 并在 pubspec 注册(IMPL-ASSET-2)
python3 ~/.claude/skills/iFF/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/images/
# 3) 设计字体真打包(否则 Android 回退 Roboto,文字逐像素全错);SF Pro 用本机 SFNS.ttf
cp /System/Library/Fonts/SFNS.ttf fonts/SFProText.ttf   # 注册 family "SF Pro Text" 到 pubspec fonts:
```
`generate_canvas.py` 已内建:文字 `fontFamily`/`align`/`verticalAlignment`/多色 `textRuns`(RichText);list 形 `border`(描边)、operand 继承圆角、渐变、椭圆;`absoluteTransform` 翻转节点重算真实位置(切图不二次旋转);boolean `Subtract` 用 `PunchedRect`(圆角矩形挖椭圆洞露出底层 leaf);跳过 boolean operand 与 covered/hidden;无 asset 的 `Star*` 画真星形。要新增渲染语义就改这个脚本,不在 dart 里手补。
硬门: 生成的 dart 顶部必须是 `// GENERATED by iFF generate_canvas.py`;无内联 `Color(0x..)`、无 `TextStyle.height`、无写死设计稿宽高;字体未打包不得进入截图。

### 7. 坐标编译产出**上线页可见层本体**(数据驱动 + 可 trace)
**定位(不变量①③⑥)**:`6.7` 的 `generate_canvas.py` 产出的、每个可见节点挂 `ValueKey('iff:<节点id>')` 的坐标画布**就是上线页的可见层本体**——几何/颜色/圆角/字号/间距全部由脚本从 `render_plan.json`/`tokens.json` 喂入,**模型禁止手写 `Positioned` 或靠眼睛调样式;调不对=脚本没把该确定性值喂进去,改 `generate_canvas.py` 不改 app**。它同时产出 `<out>.dart.expected.json`(每节点归一化几何 + 设计样式),作为 `check_render_fidelity.py` 的**设计期望基准**(源自 render_plan = 设计真值,不是 golden 图)。**不再产出独立"golden"静态画布、不再做 golden-vs-golden 像素比对**。上线页 = 这层可见画布 +(动态文本/金额槽由**同源 fixture** 填充,槽位来自 `data_slot_bindings.json`)+ 透明交互热区(事件由页面层编排)。**严禁把可见层做成与数据无关的静态展示、严禁用 `Offstage` 把数据驱动组件藏起来充数**;可见层必须真实挂在 app 对应路由/首屏并随数据变化。保真由 `check_render_fidelity.py` 对**真实渲染 trace** 逐组件保证(步骤 12 PASS 门)。
TDD 固定输入:先按 `interaction_test_plan.json` 写 widget/integration 测试,每个 case id 必须字面出现在测试名或注释里;先跑出 red,保存 `spec_dir/interaction_test_evidence.json`,再实现到 green。
固定实现方式:可见层由 `6.7` 的 `generate_canvas.py` 产出,**不得手写**;外层用 `FittedBox` 或固定 artboard canvas 做响应式适配,避免 `Transform.scale` 造成 widget test 命中异常;每个 visible render node 按 `render_plan` bbox 生成 `Positioned` + 固定 `SizedBox`;背景、输入框、按钮等节点必须按 bbox 填满,不得依赖子组件 intrinsic size;文字使用 `fontSize/weight/lineHeight/color` + 打包的设计字体;shape 使用 tokens 中的颜色、圆角、边框、阴影;装饰、图标、图片使用真实独立 asset;语义组件、业务按钮和命中区域只能透明覆盖在坐标画布上,不得参与可见像素布局。
硬门: 交互测试不得 skip/弱断言/只测存在;red evidence 必须 exit_code 非 0,green evidence 必须 exit_code = 0;不能用 Material 默认 icon 替代设计 asset;不能用“差不多”的间距;不能凭感觉写颜色、圆角、阴影;禁止把完整设计稿或 reference 派生图当可见层,但允许使用设计稿导出的独立背景、卡片、图标等真实资产。禁止用 Row/Column/Flex、region/card shell 或业务语义模板生成可见像素来替代 render_plan 中的 visible nodes;禁止把 textlayer wrapper 或文字节点画成黑色矩形;禁止在已渲染原子资产后重复渲染其子节点;`implementation_map.json` 必须覆盖 `render_plan.json` 中至少 98% 的 required visible node,且全部 image/text node 必须映射;每个 visible node mapping 必须包含 `bbox`、`implementation`、`widget` 和 `renderMode:"absolute_positioned"` 或等价坐标模式。

### 8. 资产注册
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/lanhu/home/
python3 ~/.claude/skills/iFF/scripts/update_pubspec_assets.py --pubspec pubspec.yaml --asset assets/lanhu/home/
```
输出: 已复制资产和更新后的 `pubspec.yaml` 资产注册清单。
硬门: 资产优先级 `webP > png`;简单矢量使用 svg;复杂渐变、遮罩、复杂阴影、多层组合使用 webP;缺 asset 标 `error`;不能画近似图标代替;不能用占位色块代替;所有 exportable asset 必须注册并使用;禁止整张设计稿作为背景资产。

### 8.1 真接口契约 + DTO codegen(Track B)
命令:
```bash
# worker 先调 Apifox MCP 工具存 OAS:mcp__apifox-new-mcp__read_project_oas -> spec_dir/oas.json
python3 ~/.claude/skills/iFF/scripts/normalize_api_contract.py --oas spec_dir/oas.json --out spec_dir/api_contract.json
# 再按 OAS codegen DTO(json_serializable / openapi 生成器),禁手搓与后端漂移
```
输出: `api_contract.json`(真字段/类型/枚举)+ 生成的 DTO 模型。
硬门: 真实运行必须用 Apifox 真契约,不得用推导契约糊弄;DTO 字段以 OAS 为准;无 `oas.json` 时脚本失败,worker 必须先调 Apifox MCP 工具。

### 8.2 组件清单 + 数据槽绑定(Track B)
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.claude/skills/iFF/scripts/bind_data_slots.py --manifest spec_dir/component_manifest.json --api-contract spec_dir/api_contract.json --interaction-contract spec_dir/interaction_contract.json --out spec_dir/data_slot_bindings.json
```
输出: `component_manifest.json`(组件树:header / loan_card 变体 / bottom,静态/动态槽)+ `data_slot_bindings.json`(动态槽↔字段↔变换)。
硬门: 组件由清单驱动拆分;`bind_data_slots` 高置信绑定可直接用,`needsModelBinding` 每条**模型必须按交互规则确认**(如 INT-010 `level_money`→`max_money` 回退),`confirmedByModel=true` 才算定;动态槽**先钉死设计宽度**(IMPL-DATA)。

### 8.3 数据接入 + 交互接线 + 状态选择(Track B,上线页业务层)
固定方式(可见像素由脚本钉死,业务/数据/交互由模型写,门兜底):
- **可见层不由模型重建**:像素就是步骤 7 `generate_canvas.py` 产出的带 key 坐标画布(几何/样式脚本喂入)。模型只在其上做三件事:① 把动态文本/金额槽接到**同源 fixture/DTO**(槽位来自 `data_slot_bindings.json`,默认值=设计展示值);② 按 `apply_status` 等状态选择要渲染的态;③ 把 `interaction_contract` 的 intent 接到透明热区事件 + 页面编排 + 导航/风控链。**不用 Row/Column 重排可见像素,不手写 `Positioned`/颜色/圆角/字号**(要改像素就改 `generate_canvas.py`)。
- **领域逻辑必须被运行时调用,不能只被测试引用**。
- Repository 真 HTTP + mock **同接口同源**(同 DTO 形,可注入互换);loading/error/empty/轮询/禁截图按交互规则接;切 mock⇄API(同值)可见层零变化、切不同值可见文本必须变化(数据驱动证据)。
硬门: 上线页可见层是步骤 7 的带 key 数据驱动画布(非静态 golden、非 Offstage 充数);`check_render_fidelity.py` 通过(真实 trace 逐组件达标);`check_interaction_wiring.py` 必须通过(每条交互逻辑运行时可达);`check_api_integration.py` 必须通过(每端点有 repo 调用点);fixture 同源且取值源自设计稿。

### 9. 真实运行截图
命令(Android):
```bash
# 非首屏的 feature 页加 --route /<feature-route> 直接启到该页,**不要改 main.dart 的 initialRoute**。
python3 ~/.claude/skills/iFF/scripts/capture_runtime_screenshot.py --platform android --device emulator-5554 --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
命令(iOS):
```bash
python3 ~/.claude/skills/iFF/scripts/capture_runtime_screenshot.py --platform ios --device "$SIM_ID" --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
输出: `actual.png`(**组件上线页**截图,真机像素诊断用)和 `visual_manifest.json`(`actual_source=simulator_screenshot`,`device_id`,`capture_command`,`timestamp`)。结构化逐组件保真门用的是 `check_render_fidelity.py`(真实渲染 trace,步骤 12),不再抓 golden.png 做像素比对。
硬门: 推荐视觉专用 emulator profile,宽度直接设为 artboard 宽度(例如 750),density 固定 160,隐藏 debug banner,固定时间和系统 UI;截图只允许真实 `adb screencap`/`simctl screenshot`;不得 resize actual,如必须裁剪只能做确定性 top-crop,禁止 center-crop;`actual_source != simulator_screenshot` 不能 `done`;`actual.png` 不能由 reference 派生。

### 10. 自动 diff
命令:
```bash
python3 ~/.claude/skills/iFF/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.claude/skills/iFF/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json
```
输出: `diff_report.json`、`diff_heatmap.png` 和 `repair_plan.json`;`diff_report.json` 至少包含 `ssim`、`pixelMismatch`、`viewportIssues`、node-level `bboxIssues`、`textIssues`、`assetIssues`、`shapeIssues`、颜色 delta、字号/行高差异、缺失 asset 区域、按影响面积排序的 `topP0`;`repair_plan.json` 必须去重合并同一 bbox/score 的设计节点 alias,保留 `rawActionCount` 与 dedup 后 `actionCount`,把差异按 `viewport` → `layout_region` → `asset_region` → `text_region` → `shape_region` → `fine_pixels` 排序,并给出每项的组件、node、role、score、expected、observed、structuralDelta、diagnostic、repairAction、sourceNodes。若存在 `implementation_map.json` 或 `actual_layout_trace.json`,必须合并到 `implementationHints` 和 `actualTrace`;若不存在,必须在 `diagnosticWarnings` 中说明边界,不得凭空编造文件、widget 位置或真实 bbox/font 差异。
硬门: actual/reference 尺寸不一致、SSIM < 0.99、非透明像素差异 > 1%、主节点 bbox 偏移 > 2 logical px、主色 RGB 差 > 3、字号误差 > 1px、圆角误差 > 1px、OCR 文案不一致、缺 asset,都必须进入单次 repair。单次 repair 复验后仍不达标时不得继续循环修,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求。

### 11. diff 驱动单次修复
固定单次流程:读 `repair_plan.json` 的 `topAction` 和 `actions` → 只处理 dedup 后最大 P0 类别和第一批同类 action → 按优先级修截图尺寸/裁剪/viewport、节点位置尺寸、资产缺失、文字字号/行高/weight、颜色/圆角/阴影、细节间距中的命中项 → rerun app → capture screenshot → rerun diff → 记录 `post_repair_diff_report.json` 和 `visual_report.md` → 进入下一需求。
硬门: 每个页面/每行最多执行一次 repair;禁止 repeat/while/until threshold 式循环打磨;禁止不看 repair plan 直接重写;禁止只改测试;禁止用 reference 图当背景;禁止 CSV 标 done 后再补。`diff_report.json` 是测量结果,`repair_plan.json` 是唯一修复输入;模型不得跳过 repair plan 直接凭热图或肉眼改。若 `diagnostic.kind=component_region_pixels` 且没有 `actualTrace`,不得直接声称是 bbox 错,必须先补 trace 或按设计 contract 检查该组件的 shape/text/asset 实现。单次 repair 复验达标才可 `done`;复验仍有 P0/P1 或阈值不达标时写 `error` 并继续下一需求。

### 12. done 前审计
命令:
```bash
flutter test
flutter analyze
python3 ~/.claude/skills/iFF/scripts/check_visual_manifest.py spec_dir/visual_manifest.json
python3 ~/.claude/skills/iFF/scripts/check_fixture_source.py --root .  # 自动探测 *VisualFixture 符号:test 与运行时须引用同一份(同源)
python3 ~/.claude/skills/iFF/scripts/check_render_plan.py spec_dir/render_plan.json
python3 ~/.claude/skills/iFF/scripts/check_design_artifacts.py --spec-dir spec_dir
python3 ~/.claude/skills/iFF/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
python3 ~/.claude/skills/iFF/scripts/check_implementation_map.py --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json
python3 ~/.claude/skills/iFF/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_completeness_report.json
python3 ~/.claude/skills/iFF/scripts/check_interaction_coverage.py --plan spec_dir/interaction_test_plan.json --test-root test --evidence spec_dir/interaction_test_evidence.json
python3 ~/.claude/skills/iFF/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.claude/skills/iFF
python3 ~/.claude/skills/iFF/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.claude/skills/iFF/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json
# Track B 新门:
python3 ~/.claude/skills/iFF/scripts/check_interaction_wiring.py --lib-root lib --test-root test --entry lib/main.dart --pubspec pubspec.yaml --contract spec_dir/interaction_contract.json --out spec_dir/wiring_report.json
python3 ~/.claude/skills/iFF/scripts/check_api_integration.py --api-contract spec_dir/api_contract.json --lib-root lib --out spec_dir/api_integration_report.json
# 结构化逐组件保真门(替代 golden-vs-golden;不变量③⑥):trace **真实上线页** vs render_plan 期望。
# --page-type/--page-expr 必须是真实页面(注入**同源设计 fixture** 的构造),**不是孤立画布**——
# 这样 SafeArea/Stack 坍塌等页面级包裹 bug(见 memory)才会被 getRect 抓到;--extra-imports 传 repo/fixture。
# 多状态特性:每个状态各跑一次(--page-expr 注入该状态数据 + 对应 <canvas>.expected.json)。
python3 ~/.claude/skills/iFF/scripts/gen_layout_trace_test.py --expected lib/<feature>/presentation/<canvas>.dart.expected.json --page-import package:<pkg>/<feature>/presentation/<online_page>.dart --extra-imports package:<pkg>/<feature>/data/<repo_or_fixture>.dart --page-type <OnlinePageWidget> --page-expr "<OnlinePageWidget(repository: Mock<Feature>Repository.design())>" --trace-out spec_dir/actual_layout_trace.json --out test/<feature>/<feature>_layout_trace_test.dart
flutter test test/<feature>/<feature>_layout_trace_test.dart   # 泵到异步数据落位后,写出真实页渲染 trace
python3 ~/.claude/skills/iFF/scripts/check_render_fidelity.py --trace spec_dir/actual_layout_trace.json --expected lib/<feature>/presentation/<canvas>.dart.expected.json --tokens spec_dir/tokens.json --out spec_dir/render_fidelity_report.json
```
硬门: CSV 行仍是 `doing`;worker 已加载当前 iFF 规则且 compliance 校验通过;reference 是完整 artboard;actual 是真实模拟器截图(**组件上线页**,非 golden 静态画布);fixture 同源且取值源自设计稿展示值;交互 case 覆盖和 red/green 证据通过;多状态数量一致;`render_plan` 未使用整图冒充;页面结构由真实组件、文本、按钮、卡片、输入框、状态区域组成;**`check_render_fidelity` 通过(真实上线页逐组件:每节点 bbox≤2px、主色 RGB≤3、字号/圆角≤1px、文案 100%、token 100%;缺节点=Offstage/坍塌判失败)= 视觉验收的 PASS 门**;`visual_diff` 的像素 `ssim/pixelMismatch` 只作诊断,**不作 done 阻断**(跨引擎抗锯齿天花板,见 final_reminders);`repair_plan.json` 必须**存在**(像素诊断产物),但其 `summary.p0Count` **不作 done 阻断**——它由像素 diff 派生,p0 多为跨引擎字形 AA / 被排除的系统状态栏切图,属天花板;视觉是否达标只看 `check_render_fidelity`(若 `repair_plan` 出现**平坦区真实缺陷**类 p0,才回到单次 repair,但 AA/状态栏类 p0 一律不算);**`check_interaction_wiring` 通过(无 tested-but-unwired)**;**`check_api_integration` 通过(每端点有 repo 调用)**;test/analyze 通过。全部满足后才写 `status=done`、`actual_screenshot`、`visual_manifest`、`visual_report`。
</pipeline>

<visual_gate>
## P0 — 视觉一致性门
- `spec_dir/reference.png` 是完整设计 artboard 截图;优先从 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 下载完整 `FigmaCover*.png`;没有完整 reference 不得实现,该行直接 `status=error`, `error=缺少完整设计 reference.png`。
- 每个视觉文件旁必须有 `visual_manifest.json`,至少包含 `reference_source`、`actual_source`、`device_id`、`capture_command`、`timestamp`。缺 manifest 或字段缺失时不得 `done`。
- “截图一致”验收只认设备真实截图:最终 `actual.png` 必须来自 emulator/simulator 运行后的 `adb screencap` 或 `xcrun simctl io booted screenshot`;`actual_source` 必须是 `simulator_screenshot`。`widget_golden` 可用于 worker 中间 QA,但不能作为最终 done 证据。
- `actual_source=generated_from_reference` 一律不能标 `done`,只能用于设计稿基准图。禁止把 reference 缩放后当 actual、把设计稿截图直接当运行截图、只看测试通过不看模拟器截图、只检查文件存在。
- 红线:验收必须是真实代码页面/组件渲染结果与设计稿结果保持一致;禁止将设计稿截图、完整 artboard、reference 派生图作为组件可见层、背景图、`Image.asset`、`DecorationImage` 或整图铺底来冒充实现。
- 测试 fixture 与 app runtime fixture 必须同源:widget 测试、preview、app shell/mock repository 必须读取同一份 fixture/provider。禁止测试里覆盖多状态数据、运行 app 时只注入一个默认产品或默认状态。
- 如果设计稿是多状态长图,app shell 的 preview/mock repository 必须返回同一组状态数据,最终模拟器截图必须呈现这组状态;少状态、默认单状态或与测试 fixture 不同源时不得 `done`。
- 每行 green 后必须用运行时 `actual.png` 对比 `reference.png`;没有有效运行截图不得 `done`;发现不一致时必须按 `repair_plan.json` 只修改一次并重新截图,不得只写报告或直接失败。
- 视觉报告至少检查:首屏主要模块位置/尺寸/层级、资产使用、颜色、字号、圆角、间距、文案、横竖布局结构、debug banner。
- 设计稿已有切图或导出资产时,不得用 Material 默认图标、占位盒子、近似卡片替代。
- 卡片/分区结构不得从设计稿的横向或分区布局变成居中竖排;首屏层级明显不一致时必须进入单次 repair,复验仍明显不一致则写 `error` 后进入下一需求。
- 文案必须与设计稿/表格补充一致;debug banner 不得出现在验收截图。
- worker 视觉 QA 通过后,主会话扇入还必须启动真实 app,按最终入口/路由/资产注册和同源 runtime fixture 在真实设备尺寸重新截图,保存 `reference.png`、`actual.png`、`compare/notes.md`;若发现新差异,只能按最终 `repair_plan.json` 修一次并重新截图/复验,不得循环到无差异。
- 每行 `done` 前必须强校验:CSV 原 status 还不是 `done`;`worker_compliance.json` 证明 worker 加载了当前 iFF 规则;`reference.png` 是完整 artboard;最终 `actual.png` 来自真实运行截图;manifest provenance 有效;测试 fixture 与 app runtime fixture 同源;`interaction_test_plan.json` 的每个 case id 都映射到测试且有 red/green evidence;多状态设计稿的运行截图呈现同一组状态;`render_plan.json` 通过整图冒充审计;页面结构不是整图铺底;`check_render_fidelity.py` 对真实上线页 trace 逐组件达标(bbox≤2px/色≤3/字号·圆角≤1px/文案·token 100%/无缺节点)= 视觉 PASS 门;像素 `diff_report.json` 的 `ssim/pixelMismatch` 只作诊断,受跨引擎天花板限制,不作 done 阻断;`repair_plan.json` 存在且没有 P0 action;`flutter test` 通过;`flutter analyze` 通过。
- 最小 CSV 回写:缺 `reference.png`、无法生成 `actual.png`、或单次 repair 复验后仍无法消除 P0/P1 视觉问题时,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求;若表格有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,同步写入对应路径。
</visual_gate>

<success_criteria>
- iFF 被 goal 调起后:读表 → 每行按 `<pipeline>` 固定命令产出机器视觉产物 → 并行实现各未处理行 feature(互不踩踏)→ 串行集成(依赖/资产/路由/codegen/analyze 一次性)→ 真机截图 diff → 单次 repair 复验 → 回写 `status/error/spec_dir`。
- `flutter test` 与 `flutter analyze` 无 error;每个已处理行的 worker 都有当前 iFF 规则 compliance;每个 feature 落地且符合 `reference.png` + `scene.json` + `groups.json` + `tokens.json` + `assets_manifest.json` + `layout_contract.json` + `render_plan.json` + `interaction_contract.json` + `interaction_test_plan.json` + `repair_plan.json`;页面由真实 Flutter 组件逐层渲染,不是整图铺底;交互 case 覆盖和 red/green evidence 通过;测试 fixture 与 app runtime fixture 同源;多状态设计稿在真实 app shell 中呈现同一组状态;真实上线页 `check_render_fidelity.py` 逐组件达标(结构化 PASS 门,非裸像素 SSIM)+ 真实设备 `actual.png`/`visual_manifest.json` 留作诊断 + `repair_plan.json` 无 P0 action。
</success_criteria>

<final_reminders>
P0 — 坐标画布脚本化:可见层 dart 由 `generate_canvas.py`(步骤 6.7)产出,**禁止模型手写 `Positioned`**;设计字体必须真打包(SF Pro 用本机 `SFNS.ttf`),否则文字逐像素全错。新增渲染语义改 `generate_canvas.py`,不要在生成的 dart 里手补。
P0 — 跨引擎像素天花板(现实约束,已证明,勿白追):Flutter(Impeller)与 Figma/Lanhu 光栅化的字形/边缘抗锯齿必然不同,**即使填充逐像素一致、字体已打包**,仅边缘抗锯齿在 `delta>3` 下就约占 4.9% 像素(边缘像素 55% 翻转)。`visual_diff.py` 已修为标准度量(`ssim_windowed` 8x8 + pixelmatch YIQ 抗锯齿剔除,`--aa-threshold` 默认 0.1;report 含 `ssimWindowed/ssimGlobalLegacy/pixelMismatchRealDefect/pixelMismatchStrictLegacy`),**阈值未动**且已回归验证(注入平移/改色/色块都仍 fail,只放过真抗锯齿与亚感知差)。即便如此,含文字设计忠实渲染仍 ~**0.87 窗口SSIM / ~3% 真实差异**,仍 `<0.99 / >1%`——窗口 SSIM ~0.87 是文字密集设计的**地板**(SSIM 惩罚每个含字窗口的抗锯齿结构)。故 `SSIM>=0.99 且 mismatch<=1%` 对含文字/矢量设计**跨引擎物理不可达**。诊断只看 `pixelMismatchRealDefect`(平坦区真实缺陷)定位可修项;**严禁为过门放宽阈值/delta/aa-threshold**;真实缺陷修完仍 P0 时据实写 `error` 说明天花板,勿把抗锯齿残差当 bug 反复打磨。
P0 — 固定流水线:worker 必须按 `<pipeline>` 的 0-12 步执行,每步固定输入/输出/命令/硬门;不得跳步、合并步骤、凭经验替代脚本产物,或在缺输出时继续实现。
P0 — worker 规则注入:main 必须用 `make_worker_prompt.py` 生成 spawn prompt;worker 必须先读取当前 `iFF/SKILL.md` 和 `iFF/test_rules.md`,写 `worker_compliance.json`;main 用 `check_worker_compliance.py` 通过后才接收该 worker 结果。子 agent 不会天然继承 main 已加载的 skill,禁止假设会自动继承。
P0 — 确定性必须脚本化:worker prompt/合规校验、分类、取稿、cover 下载、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、fixture、interaction contract/test plan、交互覆盖审计、资产注册、真机截图、manifest、diff、repair plan、审计都必须由 `~/.claude/skills/iFF/scripts/` 下脚本完成;禁止调用 `fd/scripts`、项目本地 `scripts/`、临时脚本或让 worker 手工判断。
P0 — 非确定性只留给模型:模型只能做项目约定适配、业务逻辑补全、组件组织和按 `repair_plan.json` 修代码;不能替代脚本生成 JSON、统计数量、判定阈值、比对截图、排序修复项或审计 provenance。
P0 — 99% 还原靠设计稿编译器,不是模型看图想象 UI:视觉实现主输入是 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`、`repair_plan.json`;`spec.md` 只能补充解释。
P0 — 第一版坐标编译:固定 artboard 根节点,用 `FittedBox` 或固定 artboard canvas 做适配,按 Figma `path/parent/children/bbox` + contract/render_plan 映射节点到 Widget,用真实 tokens/assets;先做到像,再谈工程优雅。
P0 — 保真量化门(结构化,不靠裸像素 SSIM,不变量③⑤):PASS 门 = `check_render_fidelity.py` 对**真实上线页渲染 trace** 逐组件达标——每可见节点 bbox 偏移 ≤ 2 logical px、主色 RGB 差 ≤ 3、字号/圆角误差 ≤ 1px、文案 100% 命中、token 100% 命中、无缺失(Offstage/坍塌)节点。像素 `SSIM`/`pixelMismatch`(`visual_diff.py`)**只作诊断**,受跨引擎抗锯齿天花板(~0.87 窗口SSIM / ~3% 真实差异,见下条)限制,**不作 done 阻断、严禁为过门放宽阈值**;真实缺陷修完仍有像素残差属天花板,据实记录。
P0 — 视觉一致性门:每行 green 后必须用完整设计 `reference.png` 与运行时 `actual.png` 对比;没有 `reference.png` 不得实现,没有真实设备 `actual.png` 不得 `done`;“截图一致”验收只认 emulator/simulator 运行截图,任何从 reference 派生出来的 actual 都是无效证据;主要布局、资产、颜色、字号、圆角、间距、首屏层级明显不一致时,必须根据 `repair_plan.json` 修改一次并重新截图复验;复验达标才允许 CSV 写 `done`,复验仍不达标写 `error` 并进入下一需求;不得用 Material 默认图标、占位盒子、近似卡片替代设计稿已导出的资产;main 扇入后必须重新截图验收,发现差异也只能单次修正实现。
P0 — 并行扇出只写各自 feature 文件夹,**绝不并行改共享文件**(pubspec/路由/DI/codegen/analyze 一律留到串行扇入一次性做)。
P0 — 单行 **TDD**:先写测试跑出 red 再实现;测试源 = UI 理解 + `interaction_test_plan.json`;**交互描述每条都要覆盖 HAPPY/BOUNDARY/FAILURE**,case id 必须写进测试名或注释;测试只落本 feature test 目录;`interaction_test_evidence.json` 必须记录 red/green 命令和 exit_code。
P0 — iFF 只定**流程**,不定实现细节:架构/目录/命名/资产·路由·状态·接口口径,一律由 subagent **读当前工程(目录+相关代码+工程规则文件)后随项目实现**,绝不自创或硬编码某套架构。
P0 — 视觉实现红线:无论目标是否写“截图一致”,都禁止把设计稿截图、完整 artboard、reference 派生图作为组件可见层、背景图、`Image.asset`、`DecorationImage`、整图铺底或透明热区覆盖;交互热区可以叠加在真实视觉节点上,但不能替代视觉节点;验收只看真实 Flutter 页面/组件渲染结果与设计稿的一致性,必须组件逐层实现、截图比对、按 `repair_plan.json` 单次修复并复验。
P0 — 视觉 provenance:每个 `reference.png`/`actual.png` 旁必须有 `visual_manifest.json`;最终 `actual_source` 必须是 `simulator_screenshot`,不得是 `widget_golden` 或 `generated_from_reference`。
P0 — runtime 数据同源:视觉测试 fixture、widget preview、app shell/mock repository 必须使用同一份 fixture/provider;多状态长图必须在 app runtime 返回同一组状态数据,禁止测试多状态但最终 app 只注入默认单状态。
P1 — 扇出并发先定为**每批 2 个互不影响的功能**。
P1 — iFF 读表 + 回写 `status/error/spec_dir`;`goal` 是外部指令,iFF 不实现它。
P1 — 工作队列:**只选 status 为空**的行,每批 N(默认 2);选中**即刻标 `doing`**(认领/防重/可续),完成标 `done` 或 `error`。
P1 — 单行顺序:确认视觉策略 → 本 skill 脚本取稿/下载完整 cover → **Apifox 读契约(运行时依赖,须配 Apifox MCP)** → 生成 scene/tokens/assets_manifest/groups/layout_contract/render_plan/fixture/interaction_contract/interaction_test_plan → 读项目 → 按交互测试计划设计测试(接口用例用真实契约 mock)→ 坐标编译实现 UI → 接口接入+mock 渲染 → 真实设备截图 diff → 单次 repair 复验 → 交互覆盖/视觉/manifest 自检。
P1 — 运行时外部依赖:**Apifox MCP**(读接口契约)、Lanhu 网络/API 访问、Flutter 设备/模拟器;真跑/测试前需在目标环境就绪。
P2 — `spec_dir` 缓存命中且包含 `reference.png` 才跳过取稿(幂等)。
P1 — 可见层工具链回归自测(改完即跑):任何对 `generate_canvas.py` / `gen_layout_trace_test.py` /
`check_render_fidelity.py` 的改动,改完**必须**跑 `python3 ~/.claude/skills/iFF/scripts/selftest_canvas.py
--project <flutter工程>`——它用 `iFF/selftest/` 的合成 reference 走完整链(生成画布 → flutter analyze 干净
→ 生成 trace 测试 → flutter test → check_render_fidelity 逐节点过),覆盖 text/金额/圆角 shape/渐变/
瘦高 Vector→'<'、矮宽 Vector→'v' chevron/输入值文本等易回归节点类型。绿了才提交。这是为根除"改一处编译/
运行回归被下一轮 worker 撞上"(曾致 R5/R7 训练)而固化的纪律。
