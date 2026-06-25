---
name: iff
description: Use when an external `goal` command drives batch implementation of Flutter frontend from a design-spec sheet (CSV/Excel). `iFF` = implement Flutter Flow. 读表 → 并行扇出每行一个 subagent 实现各自 feature → 串行扇入集成(依赖/资产/路由/codegen/analyze)→ 回写。落地到当前 Flutter 工程, 触发于 "iFF"批处理设计稿表格。
---

<role>
iFF 在 MAIN session 运行,是**编排者**:被外部 `goal` 指令调起(goal 设目标 + 验收标准),读取设计稿表格,**并行扇出**——每个未处理行一个 subagent 实现其对应 feature——再**串行扇入**集成共享改动(依赖/资产/路由/codegen/analyze),最后逐行回写结果。落地到 iFF 运行时的当前 Flutter 工程,遵循其架构/规范。取代旧 fc。
</role>

<context>
## 调用与分层(已确认)
- `goal` 是**外部指令**(非本仓库 skill):设定目标 + 最终验收标准,调起 iFF。iFF 不实现 goal,只被它驱动。
- iFF 自身是编排者,内部用**并行 subagent(Codex multi_agent_v1 扇出/扇入)** 处理全表;不再是"外部喂一行"的单行 worker。
- Codex 工具适配:每行 worker 用 `multi_agent_v1.spawn_agent(agent_type: "worker")` 创建;用 `multi_agent_v1.wait_agent` 收结果;需要补充输入时用 `multi_agent_v1.send_input`;完成后 `multi_agent_v1.close_agent`。主会话只汇总结果并执行串行扇入。
- 子 agent 不会天然继承 main session 已加载的 skill 正文。每个 worker 的 spawn prompt 必须由 `make_worker_prompt.py` 生成,并强制 worker 先读 `iff/SKILL.md` 与 `iff/test_rules.md`;worker 必须写 `worker_compliance.json`,main 扇入前用 `check_worker_compliance.py` 校验。禁止手写短 prompt 直接 spawn worker。

## 输入:设计稿表格(CSV/Excel)
- goal 指向一张表;**iFF 读表**挑未处理行(此前曾设想外层读,现并入 iFF)。
- 每行字段:
  - `title` 标题 / `design_url` 蓝湖地址 / `ui_notes` UI补充 / `interaction` 交互 / `api` 接口 —— 实现输入
  - `status` —— **控制列 / 工作队列状态**:**空 = 未处理(仅选这种)** → `doing`(选中即刻标记,认领/防重/可断点续)→ `done`(成功)/ `error`(失败,详情写 `error` 列)。iFF 读写。
  - `error` —— 控制列(失败时回写错误详情)
  - `spec_dir` —— 缓存列(取稿产物目录;iFF 回写,命中且内含 `reference.png`、`scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`interaction_contract.json`、`interaction_test_plan.json` 才可跳过取稿/交互编译)
  - `visual_report` / `actual_screenshot` / `visual_manifest` —— 可选缓存列(视觉 QA 报告、最终运行截图、证据来源 manifest 路径;iFF 有列则回写)

## 执行架构:扇出实现 + 扇入集成(已确认)
**并行硬约束**:工程共享改动点(`pubspec.yaml` 依赖/资产、路由/导航表、DI、主题、l10n、`build_runner`、`flutter analyze`)**不能并行写**,否则互相踩踏。故:
- **扇出(并行,先定每批 2 个互不影响的功能;一行一个 subagent)**:
  - 取设计稿与编译交互:只允许调用 `~/.agents/skills/iff/scripts/` 下脚本,得 `spec_dir`(`reference.png`+`scene.json`+`groups.json`+`tokens.json`+`assets_manifest.json`+`interaction_contract.json`+`interaction_test_plan.json`+`visual_manifest.json`+`spec.md`+`raw.json`+`assets/`);`reference.png` 优先用 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 下载完整 `FigmaCover*.png`,不得只用 export slice;`spec_dir` 缓存命中但缺机器可读视觉/交互产物仍视为失败,不得进入实现。
  - **规则注入 + TDD + 视觉编译实现**(见下「单行实现:TDD」):main 先生成 worker prompt 并 spawn;worker 先产出 `worker_compliance.json` → 按 `interaction_test_plan.json` 写测试证明 red → 以 `scene.json`/`groups.json`/`tokens.json`/`assets_manifest.json` 为主输入实现到 green → 重构;只写**自己那个 feature 文件夹**(文件不相交、无需 worktree),**不动任何共享文件**。
  - **视觉 QA(P0 硬门)**:green 后运行目标页面/Widget,按目标 viewport 截图并写 `visual_manifest.json`;截图与 `reference.png` 对比,产出 `visual_report.md`,修正到无 P0/P1 视觉问题后才能返回成功。`actual_source=generated_from_reference` 是无效 actual 证据,不得返回成功。
  - 返回:本 feature 需要的「依赖 / 资产清单 / 要注册的路由·DI」+ `spec_dir` + `worker_compliance` + `interaction_test_evidence` + `visual_report` + `actual_screenshot` + `visual_manifest` + 成功/失败。
- **扇入(串行,一次性)**:汇总去重 → `pub add` 依赖 → 拷贝资产并注册到 `pubspec.yaml` → 注册所有路由/DI → `build_runner` → `flutter analyze` → **主会话真实设备最终视觉验收**。
- **回写**:逐行把 `status`/`error`/`spec_dir` 写回表格;若有 `visual_report`/`actual_screenshot`/`visual_manifest` 列也写回。

## 规则资产(复用 fc)
- `~/.agents/skills/fc/development_rules.md`(`DEV-*`,高优先级项目规则)
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
3. **扇出(Codex multi_agent_v1 并行,先定每批 2 个互不影响的行)**:每行一个 subagent,按序 —— make_worker_prompt → spawn worker → worker 读取 iFF 规则并写 compliance → classify_design → fetch_reference_and_scene → generate_layout_contract → generate_visual_fixture → parse_interactions → generate_interaction_tests_plan → implement_from_scene_tree → map_design_nodes_to_widgets → run_widget_tests → 返回依赖/资产/路由清单 + `spec_dir` + worker compliance + layout/fixture/交互覆盖/视觉证据 + 结果。模型负责补全业务逻辑和工程接入,视觉实现必须由机器产物和 diff 驱动。
4. **扇入(串行集成)**:去重汇总 → `pub add` 依赖 → 资产拷贝 + pubspec 注册 → 注册路由/DI → `build_runner` → `flutter analyze` → 启动 emulator/simulator → `flutter run` → `adb screencap` 或 `xcrun simctl io booted screenshot` 获取最终 `actual.png` → crop 到 app viewport → 与 `reference.png` 尺寸对齐 → `run_visual_diff` 输出 `diff_report.json` → `patch_by_diff_until_threshold` → 最终运行截图验收。
5. **回写(完成)**:逐行把 status `doing`→`done`(成功)或 `error`(失败,详情写 `error` 列),并写 `spec_dir`;若表中已有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,写入最终视觉证据路径。
6. **验收**:对照 goal 的验收标准核对(`analyze` 无 error、各行达标、最终视觉验收无 P0/P1 问题)。
</instructions>

<pipeline>
## 固定流水线(P0)
iFF 是设计稿编译器 + 模型补全业务逻辑 + 真机截图 diff 循环。模型不直接“看图写 UI”;模型只读 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json` 来写和修代码。
所有确定性环节必须由本 skill 目录脚本保证,脚本唯一合法目录是 `~/.agents/skills/iff/scripts/`;禁止引用 `fd/scripts`、项目本地 `scripts/` 或临时脚本。确定性环节包括:worker prompt 生成/合规校验、设计获取/cover 下载、分类、scene/tokens/assets_manifest 导出、布局分组、layout contract、render plan、fixture 生成、interaction contract/test plan、交互覆盖审计、资产复制/pubspec 注册、真机截图/manifest、视觉 diff、manifest/fixture/render plan 审计。

### 脚本预检
命令:
```bash
python3 ~/.agents/skills/iff/scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff
```
输出: 确认流水线脚本全部存在于 `~/.agents/skills/iff/scripts/`。
硬门: 任一脚本缺失或引用本 skill 外脚本,立即 `error`,不得进入实现。

### Worker 启动合同
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_worker_prompt.py --row-json spec_dir/row.json --spec-dir spec_dir --project-root . --out spec_dir/worker_prompt.md
multi_agent_v1.spawn_agent(agent_type: "worker", prompt: "$(cat spec_dir/worker_prompt.md)")
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.agents/skills/iff
```
输出: `worker_prompt.md`、`worker_compliance.json`。
硬门: main 不得手写短 prompt 直接 spawn worker;worker 未证明读取当前 `iff/SKILL.md`、`iff/test_rules.md`、未通过 pipeline scripts 预检、或 hash 与当前 skill 不一致时,该 worker 结果作废并重跑;不得进入扇入。

### 0. 设计分类
命令:
```bash
python3 ~/.agents/skills/iff/scripts/classify_design.py --raw spec_dir/raw.json --reference spec_dir/reference.png --out spec_dir/design_classification.json
```
输出: `design_classification.json` 包含 `type`(`screen`/`variant_board`/`component_sheet`/`flow_board`)、`artboard`、`viewport`、`states`、`reason`。
硬门: `screen` 按单页面实现;`variant_board` 必须实现同一组状态 fixture;`component_sheet` 不能直接当 App 首页;分类不确定时不能编码。

### 1. 获取完整设计稿
命令:
```bash
python3 ~/.agents/skills/iff/scripts/fetch.py --url "$DESIGN_URL" --parent-dir lanhu/specs
python3 ~/.agents/skills/iff/scripts/write.py --input spec_dir/raw.json --output spec_dir/spec.md
python3 ~/.agents/skills/iff/scripts/download_cover.py --url "$DESIGN_URL" --out spec_dir/reference.png
```
输出: `raw.json`、`spec.md`、完整 artboard `reference.png`。
硬门: `download_cover.py` 必须从 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 取完整 cover;`reference.png` 尺寸必须等于 artboard;不能用 export slice 冒充完整 reference。

### 2. 导出 scene/tokens/assets_manifest
命令:
```bash
python3 ~/.agents/skills/iff/scripts/export_scene.py --raw spec_dir/raw.json --assets spec_dir/assets/manifest.json --out spec_dir/scene.json
python3 ~/.agents/skills/iff/scripts/export_tokens.py --scene spec_dir/scene.json --out spec_dir/tokens.json
python3 ~/.agents/skills/iff/scripts/export_assets_manifest.py --scene spec_dir/scene.json --out spec_dir/assets_manifest.json
```
输出: `scene.json`、`tokens.json`、`assets_manifest.json`;每个主节点必须含 `id/name/type/bbox/z/fills/radius/border/shadow/children`;文字节点还必须含 `text/fontSize/weight/lineHeight`;图片/图标节点必须有 asset 映射。
硬门: 主视觉节点没有 bbox、颜色、文字或 asset 映射时不能实现;worker 不能只读 `spec.md`;颜色、字号、圆角、阴影、资产清单必须来自机器产物,不得凭感觉补。

### 3. 自动分组 groups.json
命令:
```bash
python3 ~/.agents/skills/iff/scripts/group_layout.py --scene spec_dir/scene.json --out spec_dir/groups.json
```
输出: `groups.json`,包含 `header`、`loan_card`、`list`、`tab`、`support_section`、`bottom_tabs` 等结构和 bbox/state。
硬门: 重复卡片数量必须和 reference 一致;`variant_board` 下所有状态必须被识别出来。

### 4. 生成 layout_contract/render_plan
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_layout_contract.py --scene spec_dir/scene.json --groups spec_dir/groups.json --out spec_dir/layout_contract.json
python3 ~/.agents/skills/iff/scripts/make_render_plan.py --scene spec_dir/scene.json --assets spec_dir/assets_manifest.json --layout spec_dir/layout_contract.json --out spec_dir/render_plan.json
```
输出: `layout_contract.json`、`render_plan.json`;记录每个组件的设计节点、bbox、children bbox、scale、主要 node -> widget 预期映射,并规定每个节点用 `asset`/`text`/`shape`/`image`/`interactive_hit_area` 哪种方式实现。
硬门: 主要文字、按钮、图片、装饰角没有 widget mapping 时不能编码;每个 widget 必须能追溯到设计节点 id;`render_plan` 不得出现整张 reference/artboard 背景;交互热区只能覆盖真实视觉节点,不能替代视觉实现。

### 5. 生成同源 visual fixture
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_visual_fixture.py --classification spec_dir/design_classification.json --api-contract apifox_contract.json --out lib/src/features/home/data/home_visual_fixture.dart
```
输出: `visual_fixture.dart` 或 `visual_fixture.json`。
硬门: App、widget test、visual test、preview/mock repository 都只能 import 同一份 fixture;测试里自己造数据失败;App shell 只返回一个默认状态失败;设计稿有 9 张卡片而 runtime fixture 少于 9 张失败。

### 6. 编译 interaction 列
命令:
```bash
printf '%s' "$ROW_INTERACTION" > spec_dir/interaction.txt
python3 ~/.agents/skills/iff/scripts/parse_interactions.py --input spec_dir/interaction.txt --out spec_dir/interaction_contract.json
python3 ~/.agents/skills/iff/scripts/make_interaction_tests_plan.py --contract spec_dir/interaction_contract.json --api-contract apifox_contract.json --out spec_dir/interaction_test_plan.json
```
输出: `interaction_contract.json`、`interaction_test_plan.json`;每条交互规则都有稳定 `INT-xxx` id,每条规则生成 `HAPPY`/`BOUNDARY`/`FAILURE` 三类测试 case id。
硬门: `interaction` 非空但无法解析触发动作或期望结果时,该行 `status=error`;不得让 worker 自由解释。生成的 case id 必须进入测试名或测试注释,否则 done 前覆盖审计失败。

### 7. 第一版实现用坐标编译
TDD 固定输入:先按 `interaction_test_plan.json` 写 widget/integration 测试,每个 case id 必须字面出现在测试名或注释里;先跑出 red,保存 `spec_dir/interaction_test_evidence.json`,再实现到 green。
固定实现方式:根节点固定 artboard 宽高;外层用 `FittedBox` 或固定 artboard canvas 做响应式适配,避免 `Transform.scale` 造成 widget test 命中异常;主要节点按设计 bbox 生成 `Positioned` + 固定 `SizedBox`;背景、输入框、按钮等节点必须按 bbox 填满,不得依赖子组件 intrinsic size;文字使用 `fontSize/weight/lineHeight/color`;shape 使用 tokens 中的颜色、圆角、边框、阴影;装饰、图标、图片使用真实独立 asset;第一版允许在卡片内部用 `Stack` 精确还原,后续再重构 Row/Column。
硬门: 交互测试不得 skip/弱断言/只测存在;red evidence 必须 exit_code 非 0,green evidence 必须 exit_code = 0;不能用 Material 默认 icon 替代设计 asset;不能用“差不多”的间距;不能凭感觉写颜色、圆角、阴影;禁止把完整设计稿或 reference 派生图当可见层,但允许使用设计稿导出的独立背景、卡片、图标等真实资产。

### 8. 资产注册
命令:
```bash
python3 ~/.agents/skills/iff/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/lanhu/home/
python3 ~/.agents/skills/iff/scripts/update_pubspec_assets.py --pubspec pubspec.yaml --asset assets/lanhu/home/
```
输出: 已复制资产和更新后的 `pubspec.yaml` 资产注册清单。
硬门: 资产优先级 `webP > png`;简单矢量使用 svg;复杂渐变、遮罩、复杂阴影、多层组合使用 webP;缺 asset 标 `error`;不能画近似图标代替;不能用占位色块代替;所有 exportable asset 必须注册并使用;禁止整张设计稿作为背景资产。

### 9. 真实运行截图
命令(Android):
```bash
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py --platform android --device emulator-5554 --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
命令(iOS):
```bash
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py --platform ios --device "$SIM_ID" --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
输出: `actual.png` 和 `visual_manifest.json`(`actual_source=simulator_screenshot`,`device_id`,`capture_command`,`timestamp`)。
硬门: 推荐视觉专用 emulator profile,宽度直接设为 artboard 宽度(例如 750),density 固定 160,隐藏 debug banner,固定时间和系统 UI;截图只允许真实 `adb screencap`/`simctl screenshot`;不得 resize actual,如必须裁剪只能做确定性 top-crop,禁止 center-crop;`actual_source != simulator_screenshot` 不能 `done`;`actual.png` 不能由 reference 派生。

### 10. 自动 diff
命令:
```bash
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
```
输出: `diff_report.json` 和 `diff_heatmap.png`,至少包含 `ssim`、`pixelMismatch`、`viewportIssues`、node-level `bboxIssues`、`textIssues`、`assetIssues`、`shapeIssues`、颜色 delta、字号/行高差异、缺失 asset 区域、按影响面积排序的 `topP0`。
硬门: actual/reference 尺寸不一致、SSIM < 0.99、非透明像素差异 > 1%、主节点 bbox 偏移 > 2 logical px、主色 RGB 差 > 3、字号误差 > 1px、圆角误差 > 1px、OCR 文案不一致、缺 asset,都必须继续修。

### 11. diff 驱动修复循环
固定循环:读 `diff_report.json` → 先修截图尺寸/裁剪/viewport → 再修节点位置和尺寸 → 再修资产缺失 → 再修文字字号/行高/weight → 再修颜色/圆角/阴影 → 最后修细节间距 → rerun app → capture screenshot → rerun diff → repeat。
硬门: 每轮只能根据 `diff_report.json` 的最大 P0 区域改实现;禁止不看 diff 直接重写;禁止只改测试;禁止用 reference 图当背景;禁止 CSV 标 done 后再补。

### 12. done 前审计
命令:
```bash
flutter test
flutter analyze
python3 ~/.agents/skills/iff/scripts/check_visual_manifest.py spec_dir/visual_manifest.json
python3 ~/.agents/skills/iff/scripts/check_fixture_source.py
python3 ~/.agents/skills/iff/scripts/check_render_plan.py spec_dir/render_plan.json
python3 ~/.agents/skills/iff/scripts/check_interaction_coverage.py --plan spec_dir/interaction_test_plan.json --test-root test --evidence spec_dir/interaction_test_evidence.json
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.agents/skills/iff
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
```
硬门: CSV 行仍是 `doing`;worker 已加载当前 iFF 规则且 compliance 校验通过;reference 是完整 artboard;actual 是真实模拟器截图;fixture 同源;交互 case 覆盖和 red/green 证据通过;多状态数量一致;`render_plan` 未使用整图冒充;页面结构由真实组件、文本、按钮、卡片、输入框、状态区域组成;diff 达到阈值;test/analyze 通过。全部满足后才写 `status=done`、`actual_screenshot`、`visual_manifest`、`visual_report`。
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
- 每行 green 后必须用运行时 `actual.png` 对比 `reference.png`;没有有效运行截图不得 `done`;发现不一致时必须先修改实现并重新截图,不得只写报告或直接失败。
- 视觉报告至少检查:首屏主要模块位置/尺寸/层级、资产使用、颜色、字号、圆角、间距、文案、横竖布局结构、debug banner。
- 设计稿已有切图或导出资产时,不得用 Material 默认图标、占位盒子、近似卡片替代。
- 卡片/分区结构不得从设计稿的横向或分区布局变成居中竖排;首屏层级明显不一致时必须继续修。
- 文案必须与设计稿/表格补充一致;debug banner 不得出现在验收截图。
- worker 视觉 QA 通过后,主会话扇入还必须启动真实 app,按最终入口/路由/资产注册和同源 runtime fixture 在真实设备尺寸重新截图,保存 `reference.png`、`actual.png`、`compare/notes.md`;若发现新差异,必须回到实现/集成代码修正并重新截图,直到确认无 P0/P1 视觉问题后才允许写 `done`。
- 每行 `done` 前必须强校验:CSV 原 status 还不是 `done`;`worker_compliance.json` 证明 worker 加载了当前 iFF 规则;`reference.png` 是完整 artboard;最终 `actual.png` 来自真实运行截图;manifest provenance 有效;测试 fixture 与 app runtime fixture 同源;`interaction_test_plan.json` 的每个 case id 都映射到测试且有 red/green evidence;多状态设计稿的运行截图呈现同一组状态;`render_plan.json` 通过整图冒充审计;页面结构不是整图铺底;`diff_report.json` 达到 99% 阈值;`flutter test` 通过;`flutter analyze` 通过。
- 最小 CSV 回写:只有缺 `reference.png`、无法生成 `actual.png`、或已按报告修正后仍无法消除 P0/P1 视觉问题时,才写 `status=error`, `error=视觉不一致: ...`;若表格有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,同步写入对应路径。
</visual_gate>

<success_criteria>
- iFF 被 goal 调起后:读表 → 每行按 `<pipeline>` 固定命令产出机器视觉产物 → 并行实现各未处理行 feature(互不踩踏)→ 串行集成(依赖/资产/路由/codegen/analyze 一次性)→ 真机截图 diff 循环 → 回写 `status/error/spec_dir`。
- `flutter test` 与 `flutter analyze` 无 error;每个已处理行的 worker 都有当前 iFF 规则 compliance;每个 feature 落地且符合 `reference.png` + `scene.json` + `groups.json` + `tokens.json` + `assets_manifest.json` + `layout_contract.json` + `render_plan.json` + `interaction_contract.json` + `interaction_test_plan.json`;页面由真实 Flutter 组件逐层渲染,不是整图铺底;交互 case 覆盖和 red/green evidence 通过;测试 fixture 与 app runtime fixture 同源;多状态设计稿在真实 app shell 中呈现同一组状态;最终真实设备 `actual.png`、`visual_manifest.json`、`diff_report.json` 达到 99% 阈值。
</success_criteria>

<final_reminders>
P0 — 固定流水线:worker 必须按 `<pipeline>` 的 0-12 步执行,每步固定输入/输出/命令/硬门;不得跳步、合并步骤、凭经验替代脚本产物,或在缺输出时继续实现。
P0 — worker 规则注入:main 必须用 `make_worker_prompt.py` 生成 spawn prompt;worker 必须先读取当前 `iff/SKILL.md` 和 `iff/test_rules.md`,写 `worker_compliance.json`;main 用 `check_worker_compliance.py` 通过后才接收该 worker 结果。子 agent 不会天然继承 main 已加载的 skill,禁止假设会自动继承。
P0 — 确定性必须脚本化:worker prompt/合规校验、分类、取稿、cover 下载、scene/tokens/assets_manifest 导出、分组、contract、render plan、fixture、interaction contract/test plan、交互覆盖审计、资产注册、真机截图、manifest、diff、审计都必须由 `~/.agents/skills/iff/scripts/` 下脚本完成;禁止调用 `fd/scripts`、项目本地 `scripts/`、临时脚本或让 worker 手工判断。
P0 — 非确定性只留给模型:模型只能做项目约定适配、业务逻辑补全、组件组织和按 `diff_report.json` 修代码;不能替代脚本生成 JSON、统计数量、判定阈值、比对截图或审计 provenance。
P0 — 99% 还原靠设计稿编译器,不是模型看图想象 UI:视觉实现主输入是 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`;`spec.md` 只能补充解释。
P0 — 第一版坐标编译:固定 artboard 根节点,用 `FittedBox` 或固定 artboard canvas 做适配,按 bbox/contract/render_plan 映射节点到 Widget,用真实 tokens/assets;先做到像,再谈工程优雅。
P0 — diff 量化门:SSIM >= 0.99、非透明像素差异 <= 1%、主节点 bbox 偏移 <= 2 logical px、主色 RGB 差 <= 3、字号/圆角误差 <= 1px、OCR 文案 100% 命中、首屏主模块无缺失 asset。
P0 — 视觉一致性门:每行 green 后必须用完整设计 `reference.png` 与运行时 `actual.png` 对比;没有 `reference.png` 不得实现,没有真实设备 `actual.png` 不得 `done`;“截图一致”验收只认 emulator/simulator 运行截图,任何从 reference 派生出来的 actual 都是无效证据;主要布局、资产、颜色、字号、圆角、间距、首屏层级明显不一致时,必须根据对比报告修改实现并重新截图,循环到与设计稿一致;不得用 Material 默认图标、占位盒子、近似卡片替代设计稿已导出的资产;main 扇入后必须重新截图验收,发现差异也要先修正实现,通过后才允许 CSV 写 `done`。
P0 — 并行扇出只写各自 feature 文件夹,**绝不并行改共享文件**(pubspec/路由/DI/codegen/analyze 一律留到串行扇入一次性做)。
P0 — 单行 **TDD**:先写测试跑出 red 再实现;测试源 = UI 理解 + `interaction_test_plan.json`;**交互描述每条都要覆盖 HAPPY/BOUNDARY/FAILURE**,case id 必须写进测试名或注释;测试只落本 feature test 目录;`interaction_test_evidence.json` 必须记录 red/green 命令和 exit_code。
P0 — iFF 只定**流程**,不定实现细节:架构/目录/命名/资产·路由·状态·接口口径,一律由 subagent **读当前工程(目录+相关代码+工程规则文件)后随项目实现**,绝不自创或硬编码某套架构。
P0 — 视觉实现红线:无论目标是否写“截图一致”,都禁止把设计稿截图、完整 artboard、reference 派生图作为组件可见层、背景图、`Image.asset`、`DecorationImage`、整图铺底或透明热区覆盖;交互热区可以叠加在真实视觉节点上,但不能替代视觉节点;验收只看真实 Flutter 页面/组件渲染结果与设计稿的一致性,必须组件逐层实现并截图比对迭代。
P0 — 视觉 provenance:每个 `reference.png`/`actual.png` 旁必须有 `visual_manifest.json`;最终 `actual_source` 必须是 `simulator_screenshot`,不得是 `widget_golden` 或 `generated_from_reference`。
P0 — runtime 数据同源:视觉测试 fixture、widget preview、app shell/mock repository 必须使用同一份 fixture/provider;多状态长图必须在 app runtime 返回同一组状态数据,禁止测试多状态但最终 app 只注入默认单状态。
P1 — 扇出并发先定为**每批 2 个互不影响的功能**。
P1 — iFF 读表 + 回写 `status/error/spec_dir`;`goal` 是外部指令,iFF 不实现它。
P1 — 工作队列:**只选 status 为空**的行,每批 N(默认 2);选中**即刻标 `doing`**(认领/防重/可续),完成标 `done` 或 `error`。
P1 — 单行顺序:确认视觉策略 → 本 skill 脚本取稿/下载完整 cover → **Apifox 读契约(运行时依赖,须配 Apifox MCP)** → 生成 scene/tokens/assets_manifest/groups/layout_contract/render_plan/fixture/interaction_contract/interaction_test_plan → 读项目 → 按交互测试计划设计测试(接口用例用真实契约 mock)→ 坐标编译实现 UI → 接口接入+mock 渲染 → 真实设备截图 diff 循环 → 交互覆盖/视觉/manifest 自检。
P1 — 运行时外部依赖:**Apifox MCP**(读接口契约)、Lanhu 网络/API 访问、Flutter 设备/模拟器;真跑/测试前需在目标环境就绪。
P2 — `spec_dir` 缓存命中且包含 `reference.png` 才跳过取稿(幂等)。
</final_reminders>
