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
  - **一行 = 一个 feature(页面);`design_url` 可含多个 URL**(分号/全角分号/换行分隔),每个 URL = 该页的一张**状态画板**(board)。解析用确定性拆分(`re.split(r'[;;\n]+')`),禁止只取第一个。spec 布局固化为 `lanhu/specs/<feature>/<board>/`(R1 实测已自然形成此结构,就此定契约)。
  - `status` —— **控制列 / 工作队列状态**:**空 = 未处理(仅选这种)** → `doing`(选中即刻标记,认领/防重/可断点续)→ `done`(成功)/ `error`(失败,详情写 `error` 列)。iFF 读写。
  - `error` —— 控制列(失败时回写错误详情)
	  - `spec_dir` —— 缓存列(取稿产物目录;iFF 回写,命中且内含 `reference.png`、`scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`、`interaction_contract.json`、`interaction_test_plan.json` 才可跳过取稿/交互编译)
  - `visual_report` / `actual_screenshot` / `visual_manifest` —— 可选缓存列(视觉 QA 报告、最终运行截图、证据来源 manifest 路径;iFF 有列则回写)

## 执行架构:扇出实现 + 扇入集成(已确认)
**并行硬约束**:工程共享改动点(`pubspec.yaml` 依赖/资产、路由/导航表、DI、主题、l10n、`build_runner`、`flutter analyze`)**不能并行写**,否则互相踩踏。故:
- **公共组件(串行解析,扇出前)**:跨行共享的导航头/底部 tab 等区域,由 main 在扇出前统一解析(检测 → 查注册表 → 缺失则并行实现 + 串行收口登记,见 instructions 2.5);worker 对公共组件**只读复用**(挂载已登记 widget),严禁在扇出中创建/修改公共组件文件;公共组件区域的视觉缺陷不占 worker 单次修复预算,记录后留到串行扇入统一处理。
- **扇出(画板级三段式;R1 实测教训:行级扇出让 1 个 worker 串行磨 8-11 张板,54min/页)**:
  - **①fetch-worker(每行一个,行间并行)**:对本行每张板依次跑固定流水线 0-3 步脚本(取稿/scene/tokens/assets_manifest/groups → `lanhu/specs/<feature>/<board>/`),纯脚本执行、不读产物、不做判断;返回每板取稿成败。之后 main 跑 detect/建缺失公共组件(串行)/重跑 detect/预拉 OAS(见 instructions 2.5)。
  - **②board-worker(每板一个,全部并行;视觉编译单元)**:输入 = 本板 spec_dir + 公共组件 local 文件;产出 = 本板 `<state>_canvas.dart(+expected/slots)`、trace 测试文件、`artifact_digest.json`、本板 implementation_map 片段、本板保真准备。**只写本板专属文件**(R1 产物已证明各板 canvas/expected/slots/trace 天然不相交);禁写 page/selector/fixture/路由/pubspec;**不跑任何 `flutter test`**(测试调用预算全部归 assembly)。
  - **②'contract-worker(每 feature 一个,与 board-worker 同批并行)**:输入 = interaction 文本 + `.iff/board_index.json` + 各板 specs + 预拉 `oas.json`(全部在 2.5 末尾就绪,与画板产物零依赖);产出 = 步骤 6 系列全部契约(interaction_contract/完整性门/状态机/锚定/api_contract/test plan,`--check` 已过)。只写 feature 级 spec_dir 契约文件;禁碰 lib/test/板产物/共享文件;不跑任何 flutter 命令。
  - **③assembly-worker(每 feature 一个,板 worker 与 contract worker 全部返回后串行)**:selector/page/colors/同源 fixture/slot mapper → **消费 contract-worker 的步骤 6 产物**(验存在与 --check 通过,不重算)→ TDD(red 一次/green 一次)→ 8.x 数据接入 → 设备窗口(9-11,持锁)截图+diff+单次 repair → 12 审计(含 trace,feature 级一次)→ 汇总 `check_done_gate` 所需全部证据。只有它写 feature 共享文件(此时板 worker 已退场,无并行冲突)。
  - 视觉 QA 硬门、单次修复预算、`actual_source` 证据规则不变(由 assembly 执行)。
  - 返回:依赖/资产/路由·DI 清单 + 各板 spec_dir + compliance + evidence + 视觉证据 + 成败。
- **扇入(串行,一次性)**:汇总去重 → `pub add` 依赖 → 拷贝资产并注册到 `pubspec.yaml` → 注册所有路由/DI → `build_runner` → `flutter analyze` → flow 图合并+新边路由校验 → **主会话真实设备最终视觉验收**。
- **main 瘦身(P0;R1 实测教训:main 包办 12 张板取稿编译 + 通读产物 → context 爆掉中断 1.8h)**:main 只允许 ①读写表格 ②跑 `.iff`/skill 脚本并读其 **stdout 摘要** ③`make_worker_prompt.py` 生成 prompt 并 spawn ④汇总 worker 返回摘要。**禁止**:亲读任何 spec 产物文件(scene/render_plan/digest 都不行——digest 也是给 worker 的)、亲自执行流水线 0-12 步、手搓 worker prompt(R1 手搓丢了公共组件注入与守门)。
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
2.5. **预取稿 + 批内公共组件解析(扇出前)**:main 用 `make_worker_prompt.py --mode fetch` 给每个选中行 spawn 一个 **fetch-worker**(行间并行),它对本行每张板跑固定流水线 0-3 步脚本(main 自己**不跑取稿、不读产物**)→ 全部返回后 main 跑 `detect_shared_components.py --spec-dirs <各行spec_dir> --registry <工程>/.iff/shared_components.json --out <工程>/.iff/batch_shared_components.json`(同时写各行 `spec_dir/shared_components.local.json`)→ 对 `status=missing` 的公共组件分两段:**实现并行**——每组件 spawn 一个专用 shared-component worker(同一条消息全部发起),以 `best_asset_source` 行的机器产物 + `pooled_assets`(跨行资产池化:A 页缺切图的 icon 可用 B 页同位置切图)实现该组件到工程共享 widget 目录;实现阶段各 worker **只写自家 widget dart + 组件测试文件 + 拷自家资产文件,禁碰 pubspec/注册表、禁跑 `flutter analyze`/`flutter test`**(analyze/test 编译整个 lib 树,兄弟组件半成品文件会造成假红);组件**可见层必须由 `generate_canvas.py` 从源行该 group 子树生成**(key=源行 node id,产出组件自己的 `*.expected.json`——这是消费页逐页校验的基准)。**收口串行**——全部 worker 返回后 main 在一致的树上验门:逐个 `update_pubspec_assets.py` 注册资产 → **一次** `flutter analyze` 干净 + **一次** `flutter test`(覆盖本批全部共享组件 widget 测试)→ 逐个 `register_shared_component.py` 登记,**必须带** `--from-batch`(存源行 canonical 节点序)与 `--component-expected <组件expected.json>`(存组件 keyed 期望节点),`assets_incomplete` 时必须带 `--assets-incomplete` 显式记录,禁止静默近似;任一组件验门失败只登记通过的、失败组件按 missing 上报 → **重跑 detect 刷新 local 文件**(候选全部转 `reuse`)后才生成 worker prompt 并扇出。本步骤同时**预拉各行 OAS**(main 调 Apifox MCP 存 `spec_dir/oas.json`,worker 缓存命中即免拉,省 worker 内 1.5-3 分钟网络等待)并跑 `make_board_index.py --specs-dir lanhu/specs --out .iff/board_index.json`(交互锚定的确定性索引)。无公共组件候选时仅预取稿+预拉 OAS+建索引后直接扇出。
3. **扇出(画板级,Claude Code Agent 工具)**:**必须真并行——同一条消息一次性发起全部 `Agent` 调用;严禁串行等待(R1 实测行级串行 54min/页)。唯一互斥资源是设备窗口(9-11),由 `device_lock.py` 串行化。**
   - **3a. board-worker + contract-worker 全并行**(同一条消息发起:board 每板一个 `--mode board`,contract 每 feature 一个 `--mode contract`):board = compliance → digest → 本板 canvas/expected/slots(6.7)→ trace 测试文件生成 → 本板 implementation_map 片段,只写本板专属文件,不跑 flutter test;contract = 步骤 6 系列(交互契约+完整性门+状态机+锚定+api_contract+test plan,含模型填边/锚定确认),只写 feature 级契约文件,不跑任何 flutter 命令。
   - **3b. assembly-worker 每 feature 一个**(该 feature 的板 worker 与 contract worker 全部返回后,`--mode assembly`):selector/page/fixture/slot 绑定 → 消费步骤 6 产物(验 --check 通过,不重算)→ prefill 计划+填 modelFields → TDD red 一次/green 一次 → 数据接入(8.x)→ 持锁截图+diff+单次 repair(9-11)→ 审计(12,trace,feature 级一次)。多 feature 的 assembly 之间并行(共享文件按 feature 隔离,工程级共享仍留扇入)。
   - 模型负责业务逻辑与工程接入,视觉实现必须由机器产物和 diff 驱动。
4. **扇入(串行集成)**:去重汇总 → `pub add` 依赖 → 资产拷贝 + pubspec 注册 → 注册路由/DI → **flow 图合并与轻验**(assembly 返回的跨页边 → `update_flow_graph.py --graph .iff/flow_graph.json add --edges <edges.json>`;路由注册完后导出路由清单跑 `update_flow_graph.py check --routes <routes.txt>`——新边的目标路由必须已注册,pending_route 只报告不阻断)→ `build_runner` → `flutter analyze` → **`flutter test`(全仓回归,本批唯一一次全量调用;红了先归因到肇事 feature——文件隔离下通常是扇入集成或跨 feature 共享改动引入——修复或把该行改 `error`;全绿是步骤 5 写 `done` 的前置)** → 启动 emulator/simulator → `flutter run` → `adb screencap` 或 `xcrun simctl io booted screenshot` 获取最终 `actual.png` → crop 到 app viewport → 与 `reference.png` 尺寸对齐 → `run_visual_diff` 输出 `diff_report.json` → `make_repair_plan` 输出 `repair_plan.json` → 按 `repair_plan.json` 修改一次 → 重新截图/重新 diff → 最终运行截图验收。每行最多一次 repair,不得循环打磨;单次 repair 后仍不达标则该行 `status=error`,继续下一需求。扇出中被 defer 的**公共组件区域缺陷**在此串行处理:修组件本体一次并复验所有受影响页(组件改一处、各页共享);本批登记过新公共组件时,`.iff/shared_components.json` 属工程资产随工程提交;`assets_incomplete` 的组件必须在扇入总结中显式上报(icon 无任何切图来源,需设计侧补标切图)。
5. **回写(完成)**:写 `done` 有两个前置:**扇入的全仓 `flutter test` 回归已全绿(步骤 4)**,且**必须先过确定性总门** `check_done_gate.py --spec-root lanhu/specs/<feature>`(聚合校验:每板 fidelity ok+assetShape 通道已跑、digest/prefill 已执行、公共组件无 missing、red/green 证据、wiring ok、api 全接、最终像素诊断存在且平坦区无 asset/text 真缺陷、manifest 真机来源、compliance)——**exit 非 0 一律不得写 `done`**(实测 R1 曾在 wiring ok=false 时手写 done,此门即为此而设)。过门后逐行把 status `doing`→`done`(成功)或 `error`(失败,详情写 `error` 列),并写 `spec_dir`;若表中已有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,写入最终视觉证据路径。
5.5. **自我进化(每张设计完即触发,异步,不阻塞当前批)**:对刚跑完的每张设计,收集该 worker 的失败记录(`{blockers[], manual_judgements[], 命中的 CASE-id, gate 结果}`)→ `make_evolution_prompt.py --skill-dir ~/.claude/skills/iFF --design-name <名> --failure-record <记录>` 生成 prompt → 用 `Agent` 工具 spawn 一个 **evolution 子 agent**(在 **skill 仓的 git worktree** 里干活,**不碰当前任务/被测工程/`main`**)。它按 `SELF_IMPROVE.md` 路由 A/B/C,产出**一个 PR**(A 改脚本+红前绿后 fixture / B 写案例记忆+毕业 / C 升级人),host 自适应提交(`open_pr.py`),人审合入才生效。详见 `iFF/SELF_IMPROVE.md`。
6. **验收**:对照 goal 的验收标准核对(`analyze` 无 error、各行达标、最终视觉验收无 P0/P1 问题)。**全部行 done 后**:`make_journey_map.py --graph .iff/flow_graph.json --out .iff/journey_map.md` 生成用户故事地图(mermaid)+ E2E 回放清单,按清单在真机逐条走通 journey(跨页交互的统一终验;`pending_route` 是后续行的工作清单,不算失败)。
</instructions>

<pipeline>
## 固定流水线(P0)
iFF 是设计稿编译器 + 模型补全业务逻辑 + 真机截图 diff + 单次 repair 复验。模型不直接“看图写 UI”。**阅读纪律(P0,token 预算属于正确性)**:模型先读 `artifact_digest.json`(`summarize_spec_artifacts.py` 产出,含所有产物的 schema key/计数/case id/端点/公共组件);**大 JSON(`scene.json`/`render_plan.json`/`layout_contract.json`/`repair_plan.json`/`diff_report.json`/`oas.json`/`raw.json`)禁止整读**——它们由脚本消费(可见层由 `generate_canvas.py` 生成,模型不需要逐节点数据),需要单个节点数据时按 node id 窗口查;小文件(`tokens.json`/`groups.json`/`design_classification.json`/`api_contract.json`/`component_manifest.json`/`data_slot_bindings.json`/`interaction_test_plan.json`)可整读。
当前 `raw.json` 的主数据是 `figma_json.artboard`;一律走 Figma JSON 专用编译器 `export_figma_scene.py` / `group_figma_layout.py` / `make_figma_layout_contract.py`,不得用 generic JSON walk + bbox/name 启发式。
	所有确定性环节必须由本 skill 目录脚本保证,脚本唯一合法目录是 `~/.claude/skills/iFF/scripts/`;禁止引用 `fd/scripts`、项目本地 `scripts/` 或临时脚本。确定性环节包括:worker prompt 生成/合规校验、设计获取/cover 下载、分类、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、设计产物总审计、fixture 生成、interaction contract/test plan、交互覆盖审计、资产复制/pubspec 注册、真机截图/manifest、视觉 diff、repair plan、manifest/fixture/render plan 审计、公共组件检测/注册表登记。

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

### 批内公共组件解析(main 侧,扇出前;实现并行、收口串行;行 worker 不执行本节)
命令:
```bash
# 各选中行先按步骤 1→3 产出 scene/groups(spec_dir 缓存,worker 后续命中即跳过),然后:
python3 ~/.claude/skills/iFF/scripts/detect_shared_components.py --spec-dirs <row1_spec_dir> <row2_spec_dir> --registry .iff/shared_components.json --out .iff/batch_shared_components.json
# 对 status=missing 的组件:并行实现(best_asset_source 行产物 + pooled_assets;各 worker 只写自家文件,
# 禁碰 pubspec/注册表、禁跑 analyze/test)→ 全部返回后串行收口:pubspec 资产注册 + 一次 analyze +
# 一次 flutter test(全部组件 widget 测试)在一致的树上通过后,逐个登记:
python3 ~/.claude/skills/iFF/scripts/register_shared_component.py --registry .iff/shared_components.json --signature <sig> --name <WidgetClass> --widget-path lib/<共享widget目录>/<file>.dart --asset <已注册资产路径> --source-spec-dir <best_asset_source> --from-batch .iff/batch_shared_components.json --component-expected lib/<共享widget目录>/<canvas>.dart.expected.json
# 登记后重跑 detect 刷新各行 spec_dir/shared_components.local.json(候选全部 reuse)再生成 worker prompt
```
输出: `.iff/shared_components.json`(工程级注册表:signature → widget/资产,随工程提交)、`.iff/batch_shared_components.json`(本批解析:reuse/missing、`best_asset_source`、`pooled_assets`、`assets_incomplete`)、各行 `spec_dir/shared_components.local.json`(步骤 4 `--shared` 的输入)。
硬门: 公共组件的创建/修改只允许发生在本步骤或串行扇入,扇出中的行 worker 对公共组件只读;**并行实现阶段的组件 worker 禁碰 pubspec/注册表、禁跑 analyze/test——这些全部属串行收口**(在一致的树上验门,避免半成品互踩假红);同一 signature 不得对应两个不同 widget(`register_shared_component.py` 冲突即报错);`assets_incomplete`(icon 在任何行都无切图)必须显式登记并在扇入总结上报,禁止用 Material 默认图标或近似图形静默顶替;`make_worker_prompt.py` 必须在本步骤之后运行(否则 local 文件不会注入 worker prompt);组件 signature 匹配只认 `detect_shared_components.py`(componentId 优先,结构哈希兜底),禁止模型凭名字/截图判断"是同一个组件"。

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
# spec_dir/shared_components.local.json 存在且非空时,上面命令必须追加:--shared spec_dir/shared_components.local.json
python3 ~/.claude/skills/iFF/scripts/check_design_artifacts.py --spec-dir spec_dir
```
输出: `layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`;`layout_contract` 必须来自 Figma hierarchy,记录每个组件的设计节点、path、bbox、children/descendants relative bbox、主要 node -> widget 预期映射;`render_plan` 规定每个节点用 `image_png`/`image_webp`/`svg`/`asset`/`text`/`shape`/`oval_shape`/`gradient_shape`/`image_fill`/`vector_shape`/`shape_container`/`interactive_hit_area`/`clip_group`/`mask_group`/`covered_by_asset`/`covered_by_text`/`hidden` 哪种方式实现。
硬门: 主要文字、按钮、图片、装饰角没有 widget mapping 时不能编码;每个 widget 必须能追溯到设计节点 id;`render_plan` 不得出现整张 reference/artboard 背景;交互热区只能覆盖真实视觉节点,不能替代视觉实现。`check_design_artifacts.py` 必须确认 reference/raw/scene/classification artboard 尺寸一致,groups/layout/render/assets 的 node id 都能回溯到 `scene.json`,variant_board 状态/分组数量足够,required render node 都有 layout widget mapping;失败时不得写 `implementation_plan.json`。
语义: `image|image_png|image_webp|svg|asset` 是独立导出资产,必须作为原子可见层渲染,其 descendants 不再单独画;`image_fill` 必须按 Figma image fill 处理,不得用纯色占位;`gradient_shape` 必须保留渐变方向/stop,不得降级成单色;`vector_shape`/`shape_container` 必须按 Figma bbox、fill、border、radius、shadow/effects 实现;`clip_group`/`mask_group` 是裁剪/遮罩语义,不能随意扁平成普通 Container;`covered_by_asset` 和 `covered_by_text` 不是可见 widget;`covered_by_shared_component` 也不是画布可见节点——该 group 子树由已登记的公共组件 widget 按 group bbox 挂载渲染(render_plan 顶层 `sharedComponents` 列出挂载点),画布不得重画,其节点不计入 required 覆盖;`text` 必须渲染 scene/render data 的真实字符串和样式,禁止黑色矩形占位;`oval_shape` 必须按椭圆绘制,禁止用 bbox 矩形代替。

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
**执行者:contract-worker(与 board-worker 同批并行;输入只依赖 2.5 产物,与画板产物零依赖)。assembly 只消费本节产物并验 `--check` 通过,不重算。**
命令:
```bash
printf '%s' "$ROW_INTERACTION" > spec_dir/interaction.txt
python3 ~/.claude/skills/iFF/scripts/parse_interactions.py --input spec_dir/interaction.txt --out spec_dir/interaction_contract.json
# 契约完整性门(不变量④:每条交互规则都要覆盖):被丢进 ignoredItems 里、却带"触发+效果"信号的句子
# 必须被提取成规则,或显式登记到契约的 acknowledgedNonRules——否则 100% 覆盖只是"残缺清单的 100%"。
python3 ~/.claude/skills/iFF/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_completeness_report.json
# 状态机(P0,多状态 feature):板=节点,迁移=交互。骨架确定性生成,模型只填每条边的 trigger/condition
# (依据 交互描述+板语义+案例记忆);每条边追加为 contract 的 INT-SM-xxx 规则(享受 HAPPY/BOUNDARY/FAILURE
# 全覆盖);占位残留或零迁移无理由则 --check 失败,不得进入测试计划。
python3 ~/.claude/skills/iFF/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json
# (模型填 nodes[*].meaning 与 edges,把边写进 interaction_contract.json 的 rules)
python3 ~/.claude/skills/iFF/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json --check
python3 ~/.claude/skills/iFF/scripts/make_interaction_tests_plan.py --contract spec_dir/interaction_contract.json --api-contract apifox_contract.json --out spec_dir/interaction_test_plan.json
# 交互视觉锚定(P0):交互文字里的视觉引用(带引号的 UI 文案 / 无引号的页面·画板提及)先做确定性检索,
# 唯一命中自动绑定;多候选由模型在候选内确认(judgment,不是搜索);零命中必须标 pending_route(跨行目标,
# 测试断言导航 intent 对 mock)。--check 不过不得进入测试设计。索引由 main 在 2.5 末尾产出(.iff/board_index.json)。
python3 ~/.claude/skills/iFF/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json
# (模型编辑 anchors:ambiguous 填 confirmed,unresolved 填 pending_route)
python3 ~/.claude/skills/iFF/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json --check
```
输出: `interaction_contract.json`、`interaction_test_plan.json`、`interaction_completeness_report.json`;每条交互规则都有稳定 `INT-xxx` id,每条规则生成 `HAPPY`/`BOUNDARY`/`FAILURE` 三类测试 case id。
硬门: `interaction` 非空但无法解析触发动作或期望结果时,该行 `status=error`;不得让 worker 自由解释。**`check_interaction_completeness` 必须通过**(无未提取的规则状句子);生成的 case id 必须进入测试名或测试注释,否则 done 前覆盖审计失败。

### 6.5 计划阶段:对齐设计稿与当前工程
命令(固定顺序:digest → 机器预填 → 模型只填判断字段 → 校验):
```bash
python3 ~/.claude/skills/iFF/scripts/summarize_spec_artifacts.py --spec-dir spec_dir            # 产 artifact_digest.json,模型读它,不读大 JSON
python3 ~/.claude/skills/iFF/scripts/prefill_implementation_plan.py --spec-dir spec_dir          # 确定性字段全部机器预填
# 模型只把 modelFields 列出的 __MODEL__ 占位字段填完(projectAlignment/fixture 来源/合并理由),不改机器字段
python3 ~/.claude/skills/iFF/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
```
输出: `spec_dir/artifact_digest.json`、`spec_dir/implementation_plan.json`。
硬门: 写任何测试或生产代码前必须先产出计划;**计数/清单/inventory 一律由 `prefill_implementation_plan.py` 机器预填,模型禁止手工复述**(实测每页省 4-8 分钟);任何 `__MODEL__` 占位残留则 `check_implementation_plan` 失败。计划必须来自当前工程和机器产物,不得凭自然语言猜。最少包含:
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
python3 ~/.claude/skills/iFF/scripts/sync_project_rules.py --rules ~/.claude/skills/iFF/implementation_rules.md --memory ~/.claude/skills/iFF/evolution/case_memory.md --project-root .
```
worker 必须**先加载 `iFF/implementation_rules.md`(权威源)**并在 `worker_compliance.json` 记录,所有可见层实现按 `IMPL-*` 规则执行。
注入会把 `evolution/case_memory.md`(B 类判断先例)一并写进 CLAUDE.md;worker 在 归属/⑥交互绑定/⑦数据绑定 前**必须先读案例记忆**,命中 signature 就按其 decision 做(看 why 判适用性),并在产物里记录命中的 CASE-id(供 evolution 子 agent 累计 `seen`)。

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
固定实现方式:可见层由 `6.7` 的 `generate_canvas.py` 产出,**不得手写**;外层用 `FittedBox` 或固定 artboard canvas 做响应式适配,避免 `Transform.scale` 造成 widget test 命中异常;每个 visible render node 按 `render_plan` bbox 生成 `Positioned` + 固定 `SizedBox`;背景、输入框、按钮等节点必须按 bbox 填满,不得依赖子组件 intrinsic size;文字使用 `fontSize/weight/lineHeight/color` + 打包的设计字体;shape 使用 tokens 中的颜色、圆角、边框、阴影;装饰、图标、图片使用真实独立 asset;语义组件、业务按钮和命中区域只能透明覆盖在坐标画布上,不得参与可见像素布局。**唯一例外**:`render_plan.sharedComponents` 列出的已登记公共组件,按 group bbox 以 `Positioned` 挂载为该区域的可见层(组件本体在串行阶段已验证;不算"语义模板替代")。
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
# spec_dir/oas.json 已由 main 在 2.5 预拉(缓存命中直接用);缺失时 worker 才调 Apifox MCP:
# mcp__apifox-new-mcp__read_project_oas -> spec_dir/oas.json
python3 ~/.claude/skills/iFF/scripts/normalize_api_contract.py --oas spec_dir/oas.json --out spec_dir/api_contract.json
# 再按 OAS codegen DTO(json_serializable / openapi 生成器),禁手搓与后端漂移;
# worker 内 build_runner 必须 --build-filter 限定本 feature(全量 codegen 1-3 分钟且撞共享产物):
# dart run build_runner build --build-filter="lib/<feature>/**" --delete-conflicting-outputs
```
输出: `api_contract.json`(真字段/类型/枚举)+ 生成的 DTO 模型。
硬门: 真实运行必须用 Apifox 真契约,不得用推导契约糊弄;DTO 字段以 OAS 为准;无 `oas.json` 时脚本失败,worker 必须先调 Apifox MCP 工具;**模型读 `api_contract.json`(~4KB),`oas.json`(~92KB)禁整读**;worker 内禁跑全量 `build_runner`(无 `--build-filter` 即违规,全量 codegen 留给串行扇入)。

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
# 设备窗口互斥(并行 worker 共享一台 emulator/simulator):安装/启动/截图前必须持锁,
# 锁窗口 = 本步骤起,至步骤 11 复验截图结束;成功、失败、error 任何退出路径都必须 release。
python3 ~/.claude/skills/iFF/scripts/device_lock.py acquire --lock .iff/device.lock --label "$ROW_TITLE" --timeout 900
# 非首屏的 feature 页加 --route /<feature-route> 直接启到该页,**不要改 main.dart 的 initialRoute**。
python3 ~/.claude/skills/iFF/scripts/capture_runtime_screenshot.py --platform android --device emulator-5554 --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
# 无需 repair 时立即释放;需 repair 则持锁跑完步骤 11 的 rerun/复验截图后释放:
python3 ~/.claude/skills/iFF/scripts/device_lock.py release --lock .iff/device.lock
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
python3 ~/.claude/skills/iFF/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
```
输出: `diff_report.json`、`diff_heatmap.png` 和 `repair_plan.json`;`diff_report.json` 至少包含 `ssim`、`pixelMismatch`、`viewportIssues`、node-level `bboxIssues`、`textIssues`、`assetIssues`、`shapeIssues`、颜色 delta、字号/行高差异、缺失 asset 区域、按影响面积排序的 `topP0`;`repair_plan.json` 必须去重合并同一 bbox/score 的设计节点 alias,保留 `rawActionCount` 与 dedup 后 `actionCount`,把差异按 `viewport` → `layout_region` → `asset_region` → `text_region` → `shape_region` → `fine_pixels` 排序,并给出每项的组件、node、role、score、expected、observed、structuralDelta、diagnostic、repairAction、sourceNodes。若存在 `implementation_map.json` 或 `actual_layout_trace.json`,必须合并到 `implementationHints` 和 `actualTrace`;若不存在,必须在 `diagnosticWarnings` 中说明边界,不得凭空编造文件、widget 位置或真实 bbox/font 差异。
硬门: actual/reference 尺寸不一致、SSIM < 0.99、非透明像素差异 > 1%、主节点 bbox 偏移 > 2 logical px、主色 RGB 差 > 3、字号误差 > 1px、圆角误差 > 1px、OCR 文案不一致、缺 asset,都必须进入单次 repair。单次 repair 复验后仍不达标时不得继续循环修,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求。

### 11. diff 驱动单次修复
固定单次流程:**模型只读 `repair_plan_top.json`**(summary+topAction+首批同类 action;完整 `repair_plan.json` 可达 177KB,属脚本产物禁整读)→ 只处理 dedup 后最大 P0 类别和第一批同类 action → 按优先级修截图尺寸/裁剪/viewport、节点位置尺寸、资产缺失、文字字号/行高/weight、颜色/圆角/阴影、细节间距中的命中项 → rerun app → capture screenshot → rerun diff → 记录 `post_repair_diff_report.json` 和 `visual_report.md` → 进入下一需求。
硬门: 每个页面/每行最多执行一次 repair;禁止 repeat/while/until threshold 式循环打磨;禁止不看 repair plan 直接重写;禁止只改测试;禁止用 reference 图当背景;禁止 CSV 标 done 后再补。`diff_report.json` 是测量结果,`repair_plan.json` 是唯一修复输入;模型不得跳过 repair plan 直接凭热图或肉眼改。若 `diagnostic.kind=component_region_pixels` 且没有 `actualTrace`,不得直接声称是 bbox 错,必须先补 trace 或按设计 contract 检查该组件的 shape/text/asset 实现。单次 repair 复验达标才可 `done`;复验仍有 P0/P1 或阈值不达标时写 `error` 并继续下一需求。

### 12. done 前审计
命令(**`flutter test` 全行程只允许 3 次调用**:③红灯一次、⑤绿灯一次、本步骤一次——**三次全部 scoped 到 `test/<feature>`**,trace 测试先生成再随本 feature 套件同跑,禁止再单独起 targeted 调用;每次调用冷启 JIT 编译 20-40s,逐 case 跑是实测 40min/页的第二大浪费。**全仓回归不在本步骤跑**——它随工程增长线性变慢且批内每 feature 重复一遍,由串行扇入统一跑一次、全绿才许写 done):
```bash
# 先生成 trace 测试(它随下面的全量 flutter test 一起执行并写出 actual_layout_trace.json):
python3 ~/.claude/skills/iFF/scripts/merge_shared_expected.py --expected lib/<feature>/presentation/<canvas>.dart.expected.json --local spec_dir/shared_components.local.json --scene spec_dir/scene.json --out spec_dir/merged_expected.json
python3 ~/.claude/skills/iFF/scripts/gen_layout_trace_test.py --expected spec_dir/merged_expected.json --page-import package:<pkg>/<feature>/presentation/<online_page>.dart --extra-imports package:<pkg>/<feature>/data/<repo_or_fixture>.dart --page-type <OnlinePageWidget> --page-expr "<OnlinePageWidget(repository: Mock<Feature>Repository.design())>" --trace-out spec_dir/actual_layout_trace.json --out test/<feature>/<feature>_layout_trace_test.dart
flutter test test/<feature>        # 唯一一次:交互测试 + trace 测试 + 本 feature 回归全在这一次调用里(全仓回归由扇入批级统一跑一次)
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
python3 ~/.claude/skills/iFF/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
# Track B 新门:
python3 ~/.claude/skills/iFF/scripts/check_interaction_wiring.py --lib-root lib --test-root test --entry lib/main.dart --pubspec pubspec.yaml --contract spec_dir/interaction_contract.json --out spec_dir/wiring_report.json
python3 ~/.claude/skills/iFF/scripts/check_api_integration.py --api-contract spec_dir/api_contract.json --lib-root lib --out spec_dir/api_integration_report.json
# 结构化逐组件保真门(替代 golden-vs-golden;不变量③⑥):trace **真实上线页** vs render_plan 期望。
# --page-type/--page-expr 必须是真实页面(注入**同源设计 fixture** 的构造),**不是孤立画布**——
# 这样 SafeArea/Stack 坍塌等页面级包裹 bug(见 memory)才会被 getRect 抓到;--extra-imports 传 repo/fixture。
# 多状态特性:每状态一个 trace 测试文件,全部在上面同一次 flutter test 里执行。
# merged_expected 含公共组件区域期望(bbox+presence,key=源 node id;挂载缺失/位置错/坍塌被 missing/bbox 抓到):
python3 ~/.claude/skills/iFF/scripts/check_render_fidelity.py --trace spec_dir/actual_layout_trace.json --expected spec_dir/merged_expected.json --tokens spec_dir/tokens.json --diff-report spec_dir/diff_report.json --out spec_dir/render_fidelity_report.json
```
硬门: CSV 行仍是 `doing`;worker 已加载当前 iFF 规则且 compliance 校验通过;reference 是完整 artboard;actual 是真实模拟器截图(**组件上线页**,非 golden 静态画布);fixture 同源且取值源自设计稿展示值;交互 case 覆盖和 red/green 证据通过;多状态数量一致;`render_plan` 未使用整图冒充;页面结构由真实组件、文本、按钮、卡片、输入框、状态区域组成;**`check_render_fidelity` 通过(真实上线页逐组件:每节点 bbox≤2px、主色 RGB≤3、字号/圆角≤1px、文案 100%、token 100%;缺节点=Offstage/坍塌判失败;**icon/asset 区域形状门**:`--diff-report` 接入后,asset 区域原始 pixelMismatch>0.10 判 `asset_shape` 失败——bbox/主色看不见"位置对、颜色对、字形错"的图标,平坦区像素通道看得见,AA 残差(~<5%)不受影响)= 视觉验收的 PASS 门**;`visual_diff` 的像素 `ssim/pixelMismatch` 只作诊断,**不作 done 阻断**(跨引擎抗锯齿天花板,见 final_reminders);`repair_plan.json` 必须**存在**(像素诊断产物),但其 `summary.p0Count` **不作 done 阻断**——它由像素 diff 派生,p0 多为跨引擎字形 AA / 被排除的系统状态栏切图,属天花板;视觉是否达标只看 `check_render_fidelity`(若 `repair_plan` 出现**平坦区真实缺陷**类 p0,才回到单次 repair,但 AA/状态栏类 p0 一律不算);**`check_interaction_wiring` 通过(无 tested-but-unwired)**;**`check_api_integration` 通过(每端点有 repo 调用)**;test/analyze 通过。全部满足后才写 `status=done`、`actual_screenshot`、`visual_manifest`、`visual_report`。
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
- 每行 `done` 前必须强校验:CSV 原 status 还不是 `done`;`worker_compliance.json` 证明 worker 加载了当前 iFF 规则;`reference.png` 是完整 artboard;最终 `actual.png` 来自真实运行截图;manifest provenance 有效;测试 fixture 与 app runtime fixture 同源;`interaction_test_plan.json` 的每个 case id 都映射到测试且有 red/green evidence;多状态设计稿的运行截图呈现同一组状态;`render_plan.json` 通过整图冒充审计;页面结构不是整图铺底;`check_render_fidelity.py` 对真实上线页 trace 逐组件达标(bbox≤2px/色≤3/字号·圆角≤1px/文案·token 100%/无缺节点/asset 区域 pixelMismatch≤0.10)= 视觉 PASS 门;像素 `diff_report.json` 的 `ssim/pixelMismatch` 只作诊断,受跨引擎天花板限制,不作 done 阻断;`repair_plan.json` 存在且没有 P0 action;`flutter test` 通过;`flutter analyze` 通过。
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
P0 — 非确定性只留给模型:模型只能做项目约定适配、业务逻辑补全、组件组织和按 `repair_plan_top.json` 修代码;不能替代脚本生成 JSON、统计数量、判定阈值、比对截图、排序修复项或审计 provenance。
P0 — done 总门:`status=done` 只能在 `check_done_gate.py` exit 0 之后写入;模型无权豁免任何一项失败(包括"看起来是误报"——误报去修 gate 脚本,不许绕行)。文本节点(含动态槽)**严禁被固定高度 + 裁切(ClipRRect/clipBehavior)容器包裹**——下降部被裁会把 "days" 渲成 "davs" 且 bbox/主色保真看不见(R1 实测);chip/胶囊类背景由画布画,文本悬浮其上不裁切;此类缺陷由 done 总门的平坦区 text 真缺陷通道兜底。
P0 — 阅读纪律(token 预算属于正确性;实测强制整读大 JSON 每页烧 10-25 万 token 且拖慢生成):模型先读 `artifact_digest.json`(83× 压缩);`scene.json`/`render_plan.json`/`layout_contract.json`/`repair_plan.json`/`diff_report.json`/`oas.json`/`raw.json` **禁止整读**,单节点数据按 node id 窗口查;计划由 `prefill_implementation_plan.py` 机器预填,模型只填 `modelFields` 占位字段(`__MODEL__` 残留即 check 失败);repair 只读 `repair_plan_top.json`;接口只读 `api_contract.json`。
P1 — `flutter test` 调用预算:每行 ≤3 次(red / green / done 审计各一次,**三次全部 scoped 到 `test/<feature>`**,审计含 trace 测试),**全部由 assembly-worker 执行,board-worker 一次都不许跑**;**全仓回归由串行扇入每批统一跑一次**(不随 feature 数重复、不随工程增长拖慢单行),全绿才许回写 done;禁止逐 case、逐文件反复起跑(每次冷启 JIT 20-40s)。
P1 — 交互三层闭环:①锚定——交互文字的视觉引用只认 `board_index` 确定性检索(唯一命中绑定/多候选模型确认/零命中 pending_route),`resolve_interaction_anchors --check` 不过不得设计测试;②状态机——多状态 feature 必须 `make_state_machine` 骨架+模型填边+`--check`,每条迁移边=一条 INT-SM 规则;③journey——跨页边进 `.iff/flow_graph.json`(扇入合并+路由轻验),全部行 done 后生成故事地图并真机回放清单终验。
P0 — 99% 还原靠设计稿编译器,不是模型看图想象 UI:视觉实现主输入是 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`、`repair_plan.json`;`spec.md` 只能补充解释。
P0 — 第一版坐标编译:固定 artboard 根节点,用 `FittedBox` 或固定 artboard canvas 做适配,按 Figma `path/parent/children/bbox` + contract/render_plan 映射节点到 Widget,用真实 tokens/assets;先做到像,再谈工程优雅。
P0 — 保真量化门(结构化,不靠裸像素 SSIM,不变量③⑤):PASS 门 = `check_render_fidelity.py` 对**真实上线页渲染 trace** 逐组件达标——每可见节点 bbox 偏移 ≤ 2 logical px、主色 RGB 差 ≤ 3、字号/圆角误差 ≤ 1px、文案 100% 命中、token 100% 命中、无缺失(Offstage/坍塌)节点、**asset 区域形状达标(`--diff-report` 通道:区域 pixelMismatch ≤ 0.10,专治"位置/颜色对但图标字形错")**。像素 `SSIM`/`pixelMismatch`(`visual_diff.py`)**只作诊断**,受跨引擎抗锯齿天花板(~0.87 窗口SSIM / ~3% 真实差异,见下条)限制,**不作 done 阻断、严禁为过门放宽阈值**;真实缺陷修完仍有像素残差属天花板,据实记录。
P0 — 视觉一致性门:每行 green 后必须用完整设计 `reference.png` 与运行时 `actual.png` 对比;没有 `reference.png` 不得实现,没有真实设备 `actual.png` 不得 `done`;“截图一致”验收只认 emulator/simulator 运行截图,任何从 reference 派生出来的 actual 都是无效证据;主要布局、资产、颜色、字号、圆角、间距、首屏层级明显不一致时,必须根据 `repair_plan.json` 修改一次并重新截图复验;复验达标才允许 CSV 写 `done`,复验仍不达标写 `error` 并进入下一需求;不得用 Material 默认图标、占位盒子、近似卡片替代设计稿已导出的资产;main 扇入后必须重新截图验收,发现差异也只能单次修正实现。
P0 — 并行扇出只写各自 feature 文件夹,**绝不并行改共享文件**(pubspec/路由/DI/codegen/analyze 一律留到串行扇入一次性做)。
P0 — 公共组件复用:跨行共享区域(导航头/底部 tab/跨行同 signature 分组)先检测、先查注册表,**能复用绝不重画**;检测(`detect_shared_components.py`,componentId 优先、结构哈希兜底)与登记(`register_shared_component.py`)必须脚本化,禁止模型凭名字/截图判断"是同一个组件";公共组件的创建/修改只能发生在 2.5(实现可并行,pubspec/analyze/test/登记必须串行收口)或串行扇入,行 worker 只读挂载已登记 widget;`covered_by_shared_component` 区域不进画布;同一 signature 两个实现 = 错误;`assets_incomplete`(icon 无任何切图来源)必须显式登记并上报,禁止 Material 默认图标或近似图形静默顶替。
P0 — 单行 **TDD**:先写测试跑出 red 再实现;测试源 = UI 理解 + `interaction_test_plan.json`;**交互描述每条都要覆盖 HAPPY/BOUNDARY/FAILURE**,case id 必须写进测试名或注释;测试只落本 feature test 目录;`interaction_test_evidence.json` 必须记录 red/green 命令和 exit_code。
P0 — iFF 只定**流程**,不定实现细节:架构/目录/命名/资产·路由·状态·接口口径,一律由 subagent **读当前工程(目录+相关代码+工程规则文件)后随项目实现**,绝不自创或硬编码某套架构。
P0 — 视觉实现红线:无论目标是否写“截图一致”,都禁止把设计稿截图、完整 artboard、reference 派生图作为组件可见层、背景图、`Image.asset`、`DecorationImage`、整图铺底或透明热区覆盖;交互热区可以叠加在真实视觉节点上,但不能替代视觉节点;验收只看真实 Flutter 页面/组件渲染结果与设计稿的一致性,必须组件逐层实现、截图比对、按 `repair_plan.json` 单次修复并复验。
P0 — 视觉 provenance:每个 `reference.png`/`actual.png` 旁必须有 `visual_manifest.json`;最终 `actual_source` 必须是 `simulator_screenshot`,不得是 `widget_golden` 或 `generated_from_reference`。
P0 — runtime 数据同源:视觉测试 fixture、widget preview、app shell/mock repository 必须使用同一份 fixture/provider;多状态长图必须在 app runtime 返回同一组状态数据,禁止测试多状态但最终 app 只注入默认单状态。
P1 — 扇出并发先定为**每批 2 个互不影响的功能**,且**必须真并行**(同一条消息发起全部 Agent 调用;实测串行是 40min/页的第一大原因);设备窗口(9-11)是唯一互斥点,用 `device_lock.py`(mkdir 原子锁,任何退出路径必须 release,stale 锁自动破除)。
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
