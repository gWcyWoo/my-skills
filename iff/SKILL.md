---
name: iff
description: Use when an external `goal` command drives batch implementation of Flutter frontend from a design-spec sheet (CSV/Excel). `iFF` = implement Flutter Flow. 读表 → 并行扇出每行一个 subagent 实现各自 feature → 串行扇入集成(依赖/资产/路由/codegen/analyze)→ 回写。落地到当前 Flutter 工程, 触发于 "iFF"批处理设计稿表格。
---

<role>
iFF 在 MAIN session 运行,是**编排者**:被外部 `goal` 指令调起(goal 设目标 + 验收标准),读取设计稿表格,**并行扇出**——每个未处理行一个 subagent 实现其对应 feature——再**串行扇入**集成共享改动(依赖/资产/路由/codegen/analyze),最后逐行回写结果。落地到 iFF 运行时的当前 Flutter 工程,遵循其架构/规范。取代旧 fc。
</role>

<context>
## 调用与分层(已确认)
- `goal` 是 Codex 外部显式生命周期,不由 iFF 隐式创建。启动时用 `get_goal` 读取目标 + 最终验收标准 + 表格路径;不存在 active goal 时显式报错。只有用户明确要求创建 goal 时才可用 `create_goal`;**不得从普通 iFF 请求推断或创建 goal**。全部验收边界通过后才用 `update_goal` 标记完成。
- iFF 自身是编排者,内部用 **Codex collaboration subagent** 并行扇出/扇入处理全表;不再是"外部喂一行"的单行 worker。
- Codex 工具适配:用 `spawn_agent` 创建 worker,固定 `fork_turns: "none"`,只传 `worker_prompt.md` 全文;在当前并发上限内连续 spawn 所有 ready worker,不得等待一个完成后才创建下一个。用 `wait_agent` 等待完成;运行中补充事实用 `send_message`,已空闲后继续任务用 `followup_task`;用 `list_agents` 查状态,只在取消时用 `interrupt_agent`。Codex 没有 worker close 步骤,agent 完成后自然结束。主会话只汇总结果并执行串行扇入。
- 子 agent 不会天然继承 main session 已加载的 skill 正文。每个 board/assembly worker 的 spawn prompt 必须由 `make_worker_prompt.py` 根据 feature manifest + 当前 preflight 生成≤8KB v3 合同;worker **不得重复整读** `iff/SKILL.md`/`test_rules.md`/`implementation_rules.md`。worker 用 `complete_worker.py` 写原子 receipt,main 扇入前用 `check_worker_compliance.py` 重算当前合同、结果、输出与全部指纹。禁止手写 prompt 或 v2 compliance。

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
- **公共组件(串行解析,扇出前)**:跨行共享的导航头/底部 tab 等区域,由 main 在扇出前统一解析(检测 → 查注册表 → 缺失则串行实现 + 登记,见 instructions 2.5);worker 对公共组件**只读复用**(挂载已登记 widget),严禁在扇出中创建/修改公共组件文件;公共组件区域的视觉缺陷不占 worker 单次修复预算,记录后留到串行扇入统一处理。
- **扇出(确定性 fetch + 两类模型 worker)**:
  - **①确定性 fetch(每行一个 CLI,行间可并行)**:`run_fetch_pipeline.py` 按源顺序解析全部 URL,逐板跑固定 0-3 步,记录命令/exit/SHA,单板失败不吞掉其余板;不创建模型 worker、不消费 token。
  - **②board-worker(每板一个,全部并行;视觉编译单元)**:输入 = 本板 spec_dir + 公共组件 local 文件;产出 = 本板 `<state>_canvas.dart(+expected/slots)`、`artifact_digest.json`、`implementation_map.json` 与保真准备。**只写本板专属文件**;禁写 page/selector/fixture/路由/pubspec;不跑 `flutter test`。
  - **③assembly-worker(每 feature 一个,板 worker 全部返回后)**:selector/page/colors/同源 fixture/slot mapper → 交互/状态/数据 → TDD red/green → trace/diff/单次 repair。禁止写 pubspec/路由/DI/工程资产、禁止最终客户端运行和 done;只输出 `fan_in_request.json` 与覆盖全部 state 的 `state_changes.json` 给 main 串行处理。
  - 返回:各 worker v3 receipt + 有界摘要 + fan-in/state change 清单;视觉 QA、最终目标客户端与 done 由 main 在串行扇入后执行。
- **扇入(串行,一次性)**:校验全部 receipt → 原子应用有界模型决策与 `fan_in_request.json` → `pub add`/资产/pubspec/路由/DI → `build_runner`/`flutter analyze`/flow 校验 → `run_client_device_tests.py` 一次同时生成交互和数据客户端证据 → 主会话最终视觉验收 → 重算 context/done。
- **main 瘦身(P0;R1 实测教训:main 包办 12 张板取稿编译 + 通读产物 → context 爆掉中断 1.8h)**:main 只允许 ①读写表格 ②跑 `.iff`/skill 脚本并读其 **stdout 摘要** ③`make_worker_prompt.py` 生成 prompt 并 spawn ④汇总 worker 返回摘要。**禁止**:亲读任何 spec 产物文件(scene/render_plan/digest 都不行——digest 也是给 worker 的)、亲自执行流水线 0-12 步、手搓 worker prompt(R1 手搓丢了公共组件注入与守门)。
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
1. **接收 goal**:用 `get_goal` 读取 active goal 的目标 + 验收标准 + 目标表格路径;没有 active goal 时停止并报告,不得自动调用 `create_goal`。
2. **读表 + 认领**:解析 CSV/Excel,挑 **status 为空**的行,每批取 **N 行(默认 2)**;**立即回写这几行 status=`doing`**(认领,防重复处理 / 支持断点续跑)。
2.5. **预取稿 + 批内公共组件解析(扇出前)**:main 对每行直接运行 `run_fetch_pipeline.py --skill-dir ~/.agents/skills/iff --row-json <row.json> --spec-root <feature_spec_root> --out <fetch_report.json>`(行间可并行,无模型 worker)→ 全部返回后 main 跑 `detect_shared_components.py`。候选语义只读 `component_model_packet.json`;可写回的模型结论交 `apply_model_decision.py` 做源 SHA/decision/path 校验后原子落盘。缺失组件串行实现,登记后重跑 detect;同时预拉 OAS 并生成 board index。
2.5a. **系统 UI 退役**:fetch 完成后、公共组件检测前,对每个已编译 scene 运行 `prune_system_ui_components.py --project-root <工程> --scene <spec_dir>/scene.json --registry <工程>/.iff/shared_components.json --out <spec_dir>/system_ui_prune_report.json --apply`;只退役来源相同且 canonical nodes 全部落在 `systemUiExclusions` 的旧生成组件。
2.6. **公共组件单决策包**:`detect_shared_components` 后反复运行 `make_component_model_packet.py`;模型每次只读≤8KB packet 中一个 candidate 的 variation、related skeleton 与当前业务事实,禁止整读 batch。loose skeleton 只召回候选,绝不自动复用。
3. **扇出(画板级,Codex collaboration 工具)**:**必须真并行——在当前并发上限内连续调用 `spawn_agent(fork_turns: "none")`,不得等待一个完成后才创建下一个;超出槽位的 ready worker 进入有界队列,任一 worker 完成后立即补位。严禁行级串行等待(R1 实测 54min/页)。唯一互斥资源是设备窗口(9-11),由 `device_lock.py` 串行化。**
   - **3a. board-worker 全并行**(每板一个,`make_worker_prompt.py --mode board` 生成 prompt):compliance → digest → 本板 canvas/expected/slots(6.7)→ trace 测试文件生成 → 本板 implementation_map 片段;只写本板专属文件,不跑 flutter test。
   - **3b. assembly-worker 每 feature 一个**(板 worker 全部返回后,`--mode assembly`):selector/page/fixture/slot 绑定 → 交互契约+状态机+锚定 → prefill + 有界模型决策 → TDD red/green → 数据接入 → trace/diff/单次 repair → 输出 `fan_in_request.json`/`state_changes.json`;工程共享写入、目标客户端与 final gates 留给 main。
   - 模型负责业务逻辑与工程接入,视觉实现必须由机器产物和 diff 驱动。
4. **扇入(串行集成)**:去重汇总 → `pub add` 依赖 → 资产拷贝 + pubspec 注册 → 注册路由/DI → **flow 图合并与轻验**(assembly 返回的跨页边 → `update_flow_graph.py --graph .iff/flow_graph.json add --edges <edges.json>`;路由注册完后导出路由清单跑 `update_flow_graph.py check --routes <routes.txt>`——新边的目标路由必须已注册,pending_route 只报告不阻断)→ `build_runner` → `flutter analyze` → 启动 emulator/simulator → `flutter run` → `adb screencap` 或 `xcrun simctl io booted screenshot` 获取最终 `actual.png` → crop 到 app viewport → 与 `reference.png` 尺寸对齐 → `run_visual_diff` 输出 `diff_report.json` → `make_repair_plan` 输出 `repair_plan.json` → 按 `repair_plan.json` 修改一次 → 重新截图/重新 diff → 最终运行截图验收。每行最多一次 repair,不得循环打磨;单次 repair 后仍不达标则该行 `status=error`,继续下一需求。扇出中被 defer 的**公共组件区域缺陷**在此串行处理:修组件本体一次并复验所有受影响页(组件改一处、各页共享);本批登记过新公共组件时,`.iff/shared_components.json` 属工程资产随工程提交;`assets_incomplete` 的组件必须在扇入总结中显式上报(icon 无任何切图来源,需设计侧补标切图)。
5. **回写(完成)**:写 `done` 前**必须先过确定性总门** `check_done_gate.py --spec-root lanhu/specs/<feature> --feature-manifest .iff/features/<feature>.json --state-changes lanhu/specs/<feature>/state_changes.json`。总门重算每板视觉原始输入、interaction/data/context、v3 receipts 与全 state 文件所有权;**exit 非 0 一律不得写 `done`**。单 state 旧入口 `--state-key + --changed-files` 仅保留兼容。
5.5. **自我进化(每张设计完即触发,异步,不阻塞当前批)**:对刚跑完的每张设计,收集该 worker 的失败记录(`{blockers[], manual_judgements[], 命中的 CASE-id, gate 结果}`)→ `make_evolution_prompt.py --skill-dir ~/.agents/skills/iff --design-name <名> --failure-record <记录>` 生成 prompt → 用 `spawn_agent(fork_turns: "none")` 创建一个 **evolution 子 agent**(在 **skill 仓的 git worktree** 里干活,**不碰当前任务/被测工程/`main`**)。它按 `SELF_IMPROVE.md` 路由 A/B/C,产出**一个 PR**(A 改脚本+红前绿后 fixture / B 写案例记忆+毕业 / C 升级人),host 自适应提交(`open_pr.py`),人审合入才生效。详见 `iff/SELF_IMPROVE.md`。
6. **验收**:对照 goal 的验收标准核对(`analyze` 无 error、各行达标、最终视觉验收无 P0/P1 问题)。**全部行 done 后**:`make_journey_map.py --graph .iff/flow_graph.json --out .iff/journey_map.md` 生成用户故事地图(mermaid)+ E2E 回放清单,按清单在真机逐条走通 journey(跨页交互的统一终验;`pending_route` 是后续行的工作清单,不算失败)。只有所有边界具备当前证据且 check_done_gate.py exit 0 后才调用 `update_goal(status="complete")`;否则保持 active 并准确报告缺失证据。
</instructions>

<pipeline>
## 固定流水线(P0)
iFF 是设计稿编译器 + 模型补全业务逻辑 + 真机截图 diff + 单次 repair 复验。模型不直接“看图写 UI”。**阅读纪律(P0,token 预算属于正确性)**:脚本先生成 `artifact_digest.json`,再由 `make_visual_model_packet.py` 产出有字节硬上限的 `visual_model_packet.json`;视觉 worker 每次只读 packet 中当前一个 action。**大 JSON(`scene.json`/`render_plan.json`/`layout_contract.json`/`repair_plan.json`/`diff_report.json`/`oas.json`/`raw.json`)禁止整读**——它们由脚本消费,需要 packet 点名的单个 node 才按 id 窗口查;repair 只读 `repair_plan_top.json`;可固化的解析、计数、哈希、分类、排序、阈值、文件范围、证据新鲜度全部交脚本,模型只做组件语义、项目约定和当前事实推理。
当前 `raw.json` 的主数据是 `figma_json.artboard`;一律走 Figma JSON 专用编译器 `export_figma_scene.py` / `group_figma_layout.py` / `make_figma_layout_contract.py`,不得用 generic JSON walk + bbox/name 启发式。
	所有确定性环节必须由本 skill 目录脚本保证,脚本唯一合法目录是 `~/.agents/skills/iff/scripts/`;禁止引用 `fd/scripts`、项目本地 `scripts/` 或临时脚本。确定性环节包括:worker prompt 生成/合规校验、设计获取/cover 下载、分类、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、设计产物总审计、fixture 生成、interaction contract/test plan、交互覆盖审计、资产复制/pubspec 注册、真机截图/manifest、视觉 diff、repair plan、manifest/fixture/render plan 审计、公共组件检测/注册表登记。

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
python3 ~/.agents/skills/iff/scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff --out .iff/preflight_report.json
python3 ~/.agents/skills/iff/scripts/make_worker_prompt.py --skill-dir ~/.agents/skills/iff --row-json spec_dir/row.json --spec-dir spec_dir --project-root . --mode board --feature-manifest .iff/features/<feature>.json --preflight-report .iff/preflight_report.json --out lanhu/specs/<feature>/.iff/workers/board--<board>.prompt.md
# Codex 主会话读取生成的 prompt 全文后调用 collaboration 工具;所有 ready worker 连续 spawn:
# spawn_agent({task_name: "<worker-id>", message: "<prompt全文>", fork_turns: "none"})
# worker 按 prompt 调 complete_worker.py 生成 *.receipt.json 后,main 重算:
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --skill-dir ~/.agents/skills/iff --feature-manifest .iff/features/<feature>.json --manifest lanhu/specs/<feature>/.iff/workers/board--<board>.receipt.json
python3 ~/.agents/skills/iff/scripts/check_model_context.py --skill-dir ~/.agents/skills/iff --spec-root lanhu/specs/<feature> --project-root . --feature-manifest .iff/features/<feature>.json --out lanhu/specs/<feature>/model_context_report.json
```
输出:每个 expected worker 唯一的 `.contract.json/.prompt.md/.result.json/.receipt.json`、累计 `.iff/model_context.jsonl` 与 `model_context_report.json`。
硬门: roster 只由 feature manifest 推导(N 个唯一 board + 1 assembly);v2、缺失/多余 receipt、合同>8KB、要求整读规则、指纹/输出陈旧、任一 packet>8KB/多 action/源 SHA 陈旧都作废。报告区分 current retained、cumulative generated、controlled baseline 与 unmeasured channels;UTF-8 bytes 不冒充 tokenizer token。

### 批内公共组件解析(main 侧,串行,扇出前;worker 不执行本节)
命令:
```bash
# 各选中行先按步骤 1→3 产出 scene/groups(spec_dir 缓存,worker 后续命中即跳过),然后:
python3 ~/.agents/skills/iff/scripts/detect_shared_components.py --spec-dirs <row1_spec_dir> <row2_spec_dir> --registry .iff/shared_components.json --out .iff/batch_shared_components.json
# 每次只解决一个候选;current_business_facts.json 只含当前 feature/route/state:
python3 ~/.agents/skills/iff/scripts/make_component_model_packet.py --batch .iff/batch_shared_components.json --business-facts current_business_facts.json --out .iff/component_model_packet.json
# status=candidate 先由模型确认 family/alias/role-map;status=missing 再串行实现,两者登记前都必须有组件合同:
python3 ~/.agents/skills/iff/scripts/register_shared_component.py --registry .iff/shared_components.json --signature <sig> --source-alias <已确认跨文件struct签名> --role-map <role-map.json> --name <WidgetClass> --widget-path lib/<共享widget目录>/<file>.dart --project-root . --component-contract .iff/component_contracts/<family>.json --consumer-id <feature/state> --consumer-visual-gate <board>/visual_gate_report.json --asset <已注册资产路径> --source-spec-dir <best_asset_source> --from-batch .iff/batch_shared_components.json --component-expected lib/<共享widget目录>/<canvas>.dart.expected.json
# 登记后重跑 detect 刷新各行 spec_dir/shared_components.local.json(候选全部 reuse)再生成 worker prompt
```
输出: `.iff/shared_components.json`(工程级 registry v2:family/contract/widget hash/跨文件 alias/role map/consumers)、`.iff/batch_shared_components.json`(reuse/missing/candidate、只含差异项的 variation matrix、资产池)、各行 `spec_dir/shared_components.local.json`。
候选补充:`related_signatures` 来自忽略可选叶节点数量/几何的 loose skeleton,只用于模型召回可能的同 family 变体;脚本无权据此复用。
硬门: `componentId` 精确命中可复用;只有结构哈希相同只能成为 `candidate`,模型仅根据当前 variation facts + 业务语义确认是否同一 family,未确认不得创建/复用。公共组件合同必须先过 `check_component_contract.py`:明确非空 invariants、语义 variants、businessInputs、uiStateInputs、events、受控 slots;业务不得传 color/padding/radius/font/style/decoration 等原始视觉 override,slot 必须限制 allowedRoles。跨文件可选节点用一次确认的 role-map,禁止按节点总数或名称猜。组件源码或合同变化后必须跑 `check_shared_component_consumers.py`,所有 consumer board 重新生成视觉 gate。扇出 worker 对公共组件只读;同一 signature 不得对应两个 widget;`assets_incomplete` 必须显式登记;登记后重跑 detect。

### 0a. 归属判定(Track B 入口,新页面 / 状态变体 / 复用)
命令:
```bash
python3 ~/.agents/skills/iff/scripts/reconcile_feature.py --lib-root lib --manifest-root .iff/features --title "$ROW_TITLE" --route-hint <route> --state-hint <state> --out spec_dir/reconcile_decision.json
```
输出: `reconcile_decision.json`(现有 feature 清单 + 候选匹配 + 待模型填的 `decision`)。
硬门: 写任何组件前必须先定归属。脚本优先精确 route 并列出现有 state;模型只判断业务语义。新 state 用 `variant:<feature>`,已有 state 的新稿用 `revision:<feature>:<state>`,不得复制页面。每个 feature 必须有 `.iff/features/<feature>.json`:state 各自拥有 canvas/generatedFiles/board,状态间文件所有权互斥;既有 page/router 放 protectedFiles,由串行集成改。实现后跑 `check_feature_manifest.py`;assembly 输出 version=1 的 `state_changes.json`,必须恰好覆盖 manifest 全部 state、路径归属合法且文件不跨 state 重复,并由 done 复验。

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
硬门: `raw.json` 必须包含 `figma_json.artboard`;`download_cover.py` 必须从 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 取完整 cover;`reference.png` 尺寸必须等于 artboard;不能用 export slice 冒充完整 reference。

### 2. 导出 Figma scene/tokens/assets_manifest
命令:
```bash
python3 ~/.agents/skills/iff/scripts/export_figma_scene.py --raw spec_dir/raw.json --assets spec_dir/assets/manifest.json --out spec_dir/scene.json
# exporter 内部强制执行 system_ui_filter；缓存 scene 可原地刷新：
python3 ~/.agents/skills/iff/scripts/system_ui_filter.py --scene spec_dir/scene.json --out spec_dir/scene.json --asset-base spec_dir [--exclude-node <经确认的设备伪影节点id>]
python3 ~/.agents/skills/iff/scripts/check_figma_scene.py --scene spec_dir/scene.json
python3 ~/.agents/skills/iff/scripts/export_tokens.py --scene spec_dir/scene.json --out spec_dir/tokens.json
python3 ~/.agents/skills/iff/scripts/export_assets_manifest.py --scene spec_dir/scene.json --out spec_dir/assets_manifest.json
```
输出: `scene.json`、`tokens.json`、`assets_manifest.json`;每个节点必须从 `figma_json.artboard.layers` 编译,保留真实 `id/path/parent/children/type/figmaType/bbox/z/depth/visible/effectiveVisible/opacity/blendMode/fills/rawFills/solidFills/gradientFills/imageFills/border/radius/shadow/effects/blur/mask/maskType/clipsContent/constraints/layout/exportSettings/componentId/componentProperties/variantProperties/isInstance/absoluteTransform/relativeTransform/exportable/asset`;文字节点还必须含 `text/fontSize/weight/lineHeight/paragraphSpacing/textStyle/textRuns`;图片/图标节点必须有 asset 映射。`systemUiExclusions` 记录被剔除的状态栏、摄像头挖孔/刘海/灵动岛等设备系统 UI 及确定性原因。
硬门: `scene.sourceSchema` 必须是 `lanhu_figma_json`;主视觉节点没有 bbox、颜色、文字或 asset 映射时不能实现;worker 不能只读 `spec.md`;颜色、字号、圆角、阴影、资产清单必须来自机器产物,不得凭感觉补。系统 UI 判定必须组合顶部窄带几何与内容指纹；被排除节点及子树必须 `visible=false/effectiveVisible=false`,render plan 必须 `implementation=hidden,required=false`。异常位置的设备伪影只能在确认具体 scene 节点后用 `--exclude-node` 排除,不得扩大启发式误删业务内容。

### 3. 自动分组 groups.json
命令:
```bash
python3 ~/.agents/skills/iff/scripts/group_figma_layout.py --scene spec_dir/scene.json --out spec_dir/groups.json
```
输出: `groups.json`,优先来自 Figma hierarchy,每个 group 保留 `node/path/parent/children/bbox/depth/source=figma_hierarchy`,并分类为 `header`、`loan_card`、`list`、`form`、`button_group`、`support_section`、`bottom_tabs`、`repeated_region`、`region`。
硬门: 分组必须先尊重 Figma group/component/layer hierarchy,只能用 bbox/name 作为辅助;重复卡片数量必须和 reference 一致;`variant_board` 下所有状态必须被识别出来。

### 4. 生成 layout_contract/render_plan
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_figma_layout_contract.py --scene spec_dir/scene.json --groups spec_dir/groups.json --out spec_dir/layout_contract.json
python3 ~/.agents/skills/iff/scripts/make_render_plan.py --scene spec_dir/scene.json --assets spec_dir/assets_manifest.json --layout spec_dir/layout_contract.json --out spec_dir/render_plan.json
# spec_dir/shared_components.local.json 存在且非空时,上面命令必须追加:--shared spec_dir/shared_components.local.json
python3 ~/.agents/skills/iff/scripts/check_design_artifacts.py --spec-dir spec_dir
```
输出: `layout_contract.json`、`render_plan.json`、`design_artifacts_report.json`;`layout_contract` 必须来自 Figma hierarchy,记录每个组件的设计节点、path、bbox、children/descendants relative bbox、主要 node -> widget 预期映射;`render_plan` 规定每个节点用 `image_png`/`image_webp`/`svg`/`asset`/`text`/`shape`/`oval_shape`/`gradient_shape`/`image_fill`/`vector_shape`/`shape_container`/`interactive_hit_area`/`clip_group`/`mask_group`/`covered_by_asset`/`covered_by_text`/`hidden` 哪种方式实现。
硬门: 主要文字、按钮、图片、装饰角没有 widget mapping 时不能编码;每个 widget 必须能追溯到设计节点 id;`render_plan` 不得出现整张 reference/artboard 背景;交互热区只能覆盖真实视觉节点,不能替代视觉实现。`check_design_artifacts.py` 必须确认 reference/raw/scene/classification artboard 尺寸一致,groups/layout/render/assets 的 node id 都能回溯到 `scene.json`,variant_board 状态/分组数量足够,required render node 都有 layout widget mapping;失败时不得写 `implementation_plan.json`。
语义: `image|image_png|image_webp|svg|asset` 是独立导出资产,必须作为原子可见层渲染,其 descendants 不再单独画;`image_fill` 必须按 Figma image fill 处理,不得用纯色占位;`gradient_shape` 必须保留渐变方向/stop,不得降级成单色;`vector_shape`/`shape_container` 必须按 Figma bbox、fill、border、radius、shadow/effects 实现;`clip_group`/`mask_group` 是裁剪/遮罩语义,不能随意扁平成普通 Container;`covered_by_asset` 和 `covered_by_text` 不是可见 widget;`covered_by_shared_component` 也不是画布可见节点——该 group 子树由已登记的公共组件 widget 按 group bbox 挂载渲染(render_plan 顶层 `sharedComponents` 列出挂载点),画布不得重画,其节点不计入 required 覆盖;`text` 必须渲染 scene/render data 的真实字符串和样式,禁止黑色矩形占位;`oval_shape` 必须按椭圆绘制,禁止用 bbox 矩形代替。

### 5. 生成同源 visual fixture
命令:
```bash
# 同源设计 fixture:内容=设计稿展示值(消费 6.7 generate_canvas 各状态产出的 <canvas>.dart.slots.json
# 种子),**故须在 6.7 各可见状态画布生成之后运行**;feature-agnostic,一状态一个 --slots。
python3 ~/.agents/skills/iff/scripts/make_visual_fixture.py --feature <feature> \
  --slots <state>=lib/<feature>/presentation/<state>_canvas.dart.slots.json \
  [--slots <state2>=...] --out lib/<feature>/data/<feature>_visual_fixture.dart
```
输出: `visual_fixture.dart` 或 `visual_fixture.json`。
硬门: App、widget test、visual test、preview/mock repository 都只能 import 同一份 fixture;测试里自己造数据失败;App shell 只返回一个默认状态失败;设计稿有 9 张卡片而 runtime fixture 少于 9 张失败。

### 6. 编译 interaction 列
命令:
```bash
printf '%s' "$ROW_INTERACTION" > spec_dir/interaction.txt
python3 ~/.agents/skills/iff/scripts/parse_interactions.py --input spec_dir/interaction.txt --out spec_dir/interaction_contract.json
# 解析器只做确定性句法拆分;业务前缀不自动忽略。语义非规则必须由模型 confirmedByModel,
# 多触发复合句必须由模型明确判 single/split;否则完整性门失败。
python3 ~/.agents/skills/iff/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_completeness_report.json
# 模型只读≤8KB的单动作包:每次只补一条规则语义/actionTarget、一项状态含义/初始状态/迁移边、
# 一条锚点判断或一个未证明 case;不截断来源/候选,actionTarget 候选过多时先选 feature/board。
python3 ~/.agents/skills/iff/scripts/make_interaction_model_packet.py --spec-root spec_dir --project-root . --out spec_dir/interaction_model_packet.json
# (只读 interaction_model_packet.json,解决其唯一 action,再生成下一包;禁止整读 contract/state/anchors/test machine log)
python3 ~/.agents/skills/iff/scripts/check_interaction_contract.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_contract_report.json
# 状态机(P0,多状态 feature):板=节点,迁移=交互。骨架绑定当前 boards/contract/feature-manifest 哈希,
# 空含义/空 trigger/重复边失败;模型每包只填一个状态含义、初始状态或一条边的 trigger/condition
# (依据 交互描述+板语义+案例记忆);每条边追加为 contract 的 INT-SM-xxx 规则(享受 HAPPY/BOUNDARY/FAILURE
# 全覆盖);占位残留或零迁移无理由则 --check 失败,不得进入测试计划。
python3 ~/.agents/skills/iff/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json
# (模型填 nodes[*].meaning 与 edges,把边写进 interaction_contract.json 的 rules)
python3 ~/.agents/skills/iff/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json --contract spec_dir/interaction_contract.json --feature-manifest .iff/features/<feature>.json --check
python3 ~/.agents/skills/iff/scripts/make_interaction_tests_plan.py --contract spec_dir/interaction_contract.json --api-contract apifox_contract.json --out spec_dir/interaction_test_plan.json
# 交互视觉锚定(P0):交互文字里的视觉引用(带引号的 UI 文案 / 无引号的页面·画板提及)先做确定性检索,
# 唯一命中自动绑定;多候选由模型在候选内确认(judgment,不是搜索);零命中必须标 pending_route(跨行目标,
# 测试断言导航 intent 对 mock)。--check 不过不得进入测试设计。索引由 main 在 2.5 末尾产出(.iff/board_index.json)。
python3 ~/.agents/skills/iff/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json
# (模型编辑 anchors:ambiguous 只能从 candidates 填 confirmed;unresolved 必须填 pending_route+targetIntent)
python3 ~/.agents/skills/iff/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json --check
```
输出: `interaction_contract.json`、`interaction_test_plan.json`、`interaction_completeness_report.json`;每条交互规则 id 由规则原文哈希稳定生成,目标身份为 `feature/board/key` 或受限系统手势,每规则生成带结构化 observable target 的 `HAPPY`/`BOUNDARY`/`FAILURE` 三类 case。
硬门: 原文每项必须恰好落入 rule 或带 reason 的 `acknowledgedNonRules`;每 rule 必须有具体 action/outcomes,且 `actionTarget` 必须是 `board_index` 存在的 `iff:<nodeId>` 或显式 system gesture。case id 必须是实际运行的 `testWidgets` 名称,不接受注释或普通 unit test 充数。

### 6.5 计划阶段:对齐设计稿与当前工程
命令(固定顺序:digest → 机器预填 → 模型只填判断字段 → 校验):
```bash
python3 ~/.agents/skills/iff/scripts/summarize_spec_artifacts.py --spec-dir spec_dir            # 产 artifact_digest.json,模型读它,不读大 JSON
python3 ~/.agents/skills/iff/scripts/prefill_implementation_plan.py --spec-dir spec_dir          # 确定性字段全部机器预填
# 模型只把 modelFields 列出的 __MODEL__ 占位字段填完(projectAlignment/fixture 来源/合并理由),不改机器字段
python3 ~/.agents/skills/iff/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
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

### 6.6 注入项目实现规范到 AGENTS.md(确定性,P0)
落地工程前必须把实现规范注入目标工程 `AGENTS.md`,让所有 agent(含本 worker)统一遵守:
```bash
python3 ~/.agents/skills/iff/scripts/sync_project_rules.py --rules ~/.agents/skills/iff/implementation_rules.md --memory ~/.agents/skills/iff/evolution/case_memory.md --project-root .
```
`implementation_rules.md` 是权威源;`make_worker_prompt.py` 把当前角色适用的 `IMPL-*` 硬门编进 bounded v3 合同,`complete_worker.py` receipt 绑定完整文件 SHA,worker 不重复整读全文。
注入会把 `evolution/case_memory.md`(B 类判断先例)一并写进 AGENTS.md;worker 在 归属/⑥交互绑定/⑦数据绑定 前**必须先读案例记忆**,命中 signature 就按其 decision 做(看 why 判适用性),并在产物里记录命中的 CASE-id(供 evolution 子 agent 累计 `seen`)。

### 6.7 脚本生成响应式画布 + 颜色 token + 字体(确定性,P0)
可见层生成是**确定性的,必须脚本化**——禁止模型手写。`generate_canvas.py` 走**关系换算**:每个尺寸/位置都是「设计像素 × u」,`u = LayoutBuilder.maxWidth / 设计宽度`(`IMPL-LAYOUT-1`),设计宽度下 1:1 还原(供视觉 QA),真机按比例自适应;颜色全抽到 `app_colors.dart`(`IMPL-TOKEN`),不写死宽高/`scale`(`IMPL-LAYOUT-2`),不加 `TextStyle.height`(`IMPL-LAYOUT-4`),按区域拆 widget(`IMPL-COMP-1`),中文注释(`IMPL-DOC`)。
命令:
```bash
# 1) 编译可见层 + 颜色 token(响应式;资产前缀走 assets/images/,IMPL-ASSET-2)
# 先产组件清单(只需 render_plan + classification),供 generate_canvas 标记动态文本槽:
python3 ~/.agents/skills/iff/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.agents/skills/iff/scripts/generate_canvas.py --render-plan spec_dir/render_plan.json \
  --classification spec_dir/design_classification.json --component-manifest spec_dir/component_manifest.json \
  --out lib/<feature>/presentation/home_artboard_canvas.dart --colors-import app_colors.dart --asset-prefix assets/images/
python3 ~/.agents/skills/iff/scripts/make_status_bar_policy.py --scene spec_dir/scene.json --class-name <State>StatusBarPolicy --out lib/<feature>/presentation/<state>_status_bar_policy.dart
# 产物含:可见层 dart(动态槽 = Text(slotText['<id>'] ?? '设计值'))、<out>.expected.json(保真基准)、
# <out>.slots.json(设计种子 fixture:槽节点id->设计展示值,不变量⑦)。上层页面/同源 fixture 用 slots.json 初始化。
# 2) 资产复制到 assets/images/ 并在 pubspec 注册(IMPL-ASSET-2)
python3 ~/.agents/skills/iff/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/images/
# 3) 设计字体真打包(否则 Android 回退 Roboto,文字逐像素全错);SF Pro 用本机 SFNS.ttf
cp /System/Library/Fonts/SFNS.ttf fonts/SFProText.ttf   # 注册 family "SF Pro Text" 到 pubspec fonts:
```
`generate_canvas.py` 已内建:文字 `fontFamily`/`align`/`verticalAlignment`/多色 `textRuns`(RichText);list 形 `border`(描边)、operand 继承圆角、渐变、椭圆;`absoluteTransform` 翻转节点重算真实位置(切图不二次旋转);boolean `Subtract` 用 `PunchedRect`(圆角矩形挖椭圆洞露出底层 leaf);跳过 boolean operand 与 covered/hidden;无 asset 的 `Star*` 画真星形。要新增渲染语义就改这个脚本,不在 dart 里手补。
硬门: 画布 dart 顶部必须是 `// GENERATED by iFF generate_canvas.py`;状态栏策略必须由 `make_status_bar_policy.py` 生成、与当前 scene 一致并被上线页引用;无内联 `Color(0x..)`、无 `TextStyle.height`、无写死设计稿宽高;字体未打包不得进入截图。

### 7. 坐标编译产出**上线页可见层本体**(数据驱动 + 可 trace)
**定位(不变量①③⑥)**:`6.7` 的 `generate_canvas.py` 产出的、每个可见节点挂 `ValueKey('iff:<节点id>')` 的坐标画布**就是上线页的可见层本体**——几何/颜色/圆角/字号/间距全部由脚本从 `render_plan.json`/`tokens.json` 喂入,**模型禁止手写 `Positioned` 或靠眼睛调样式;调不对=脚本没把该确定性值喂进去,改 `generate_canvas.py` 不改 app**。它同时产出 `<out>.dart.expected.json`(每节点归一化几何 + 设计样式),作为 `check_render_fidelity.py` 的**设计期望基准**(源自 render_plan = 设计真值,不是 golden 图)。**不再产出独立"golden"静态画布、不再做 golden-vs-golden 像素比对**。上线页 = 这层可见画布 +(动态文本/金额槽由**同源 fixture** 填充,槽位来自 `data_slot_bindings.json`)+ 透明交互热区(事件由页面层编排)。**严禁把可见层做成与数据无关的静态展示、严禁用 `Offstage` 把数据驱动组件藏起来充数**;可见层必须真实挂在 app 对应路由/首屏并随数据变化。保真由 `check_render_fidelity.py` 对**真实渲染 trace** 逐组件保证(步骤 12 PASS 门)。
TDD 固定输入:先按 `interaction_test_plan.json` + 当前 data bindings/runtime manifest 写通过真实页面/public widget surface 的 `testWidgets`/`integration_test`;每 case 的公开 UI action 必须直接作用于计划目标,`expect/expectLater` 必须直接断言计划的结构化 observable。用 `run_feature_tests.py --phase red ...` 与 `--phase green ...` 各运行一次固定 `flutter test --machine`,同写 interaction/data 用例级结果和当前 plan/bindings/runtime/test 指纹;编译错或无关测试失败不算 red。main 扇入后用 `run_client_device_tests.py` 从 `app.main()` 在目标 Android/iOS 客户端一次执行全部交互及可见数据 case,从同一 stdout 持久化自动截图 PNG 并生成两域 evidence;对应 checker 重算当前源码/测试/资源/契约/capture 哈希。**iFF 不接受 Browser/Chrome/Web,也不接受手写 observations/report**。
固定实现方式:可见层由 `6.7` 的 `generate_canvas.py` 产出,**不得手写**;外层用 `FittedBox` 或固定 artboard canvas 做响应式适配,避免 `Transform.scale` 造成 widget test 命中异常;每个 visible render node 按 `render_plan` bbox 生成 `Positioned` + 固定 `SizedBox`;背景、输入框、按钮等节点必须按 bbox 填满,不得依赖子组件 intrinsic size;文字使用 `fontSize/weight/lineHeight/color` + 打包的设计字体;shape 使用 tokens 中的颜色、圆角、边框、阴影;装饰、图标、图片使用真实独立 asset;语义组件、业务按钮和命中区域只能透明覆盖在坐标画布上,不得参与可见像素布局。**唯一例外**:`render_plan.sharedComponents` 列出的已登记公共组件,按 group bbox 以 `Positioned` 挂载为该区域的可见层(组件本体在串行阶段已验证;不算"语义模板替代")。
硬门: 交互测试不得 skip/弱断言/只测存在;不得直接调 domain/reducer 方法代替 public UI 动作;red 必须至少有一个计划内 case 真失败,green 必须在同 plan/test 指纹下全部实际执行并成功。不能用 Material 默认 icon 替代设计 asset;不能用“差不多”的间距;不能凭感觉写颜色、圆角、阴影;禁止把完整设计稿或 reference 派生图当可见层,但允许使用设计稿导出的独立背景、卡片、图标等真实资产。禁止用 Row/Column/Flex、region/card shell 或业务语义模板生成可见像素来替代 render_plan 中的 visible nodes;禁止把 textlayer wrapper 或文字节点画成黑色矩形;禁止在已渲染原子资产后重复渲染其子节点;`implementation_map.json` 必须覆盖 `render_plan.json` 中至少 98% 的 required visible node,且全部 image/text node 必须映射;每个 visible node mapping 必须包含 `bbox`、`implementation`、`widget` 和 `renderMode:"absolute_positioned"` 或等价坐标模式。

### 8. 资产注册
命令:
```bash
python3 ~/.agents/skills/iff/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/lanhu/home/
python3 ~/.agents/skills/iff/scripts/update_pubspec_assets.py --pubspec pubspec.yaml --asset assets/lanhu/home/
```
输出: 已复制资产和更新后的 `pubspec.yaml` 资产注册清单。
硬门: 资产优先级 `webP > png`;简单矢量使用 svg;复杂渐变、遮罩、复杂阴影、多层组合使用 webP;缺 asset 标 `error`;不能画近似图标代替;不能用占位色块代替;所有 exportable asset 必须注册并使用;禁止整张设计稿作为背景资产。

### 8.1 真接口契约 + DTO codegen(Track B)
命令:
```bash
# spec_dir/oas.json 已由 main 在 2.5 预拉(缓存命中直接用);缺失时先从当前 callable tools
# 中定位“读取 Apifox project OAS”的工具并把原始结果保存为 spec_dir/oas.json;
# 当前环境无此能力时立即报告 setup blocker,不得猜工具名或推导契约。
python3 ~/.agents/skills/iff/scripts/normalize_api_contract.py --oas spec_dir/oas.json --out spec_dir/api_contract.json
python3 ~/.agents/skills/iff/scripts/normalize_api_contract.py --oas spec_dir/oas.json --out spec_dir/api_contract.json --check
# 再按 OAS codegen DTO(json_serializable / openapi 生成器),禁手搓与后端漂移;
# worker 内 build_runner 必须 --build-filter 限定本 feature(全量 codegen 1-3 分钟且撞共享产物):
# dart run build_runner build --build-filter="lib/<feature>/**" --delete-conflicting-outputs
```
输出: `api_contract.json`(OAS SHA、endpoint/method/request/response status、递归 JSON path、type/format/required-path/nullable/enum、allOf/oneOf/anyOf variants)+ 生成的 DTO 模型。
硬门: 真实运行必须用 Apifox 真契约,不得用推导契约糊弄;DTO 字段以 OAS 为准;无 `oas.json`、当前环境没有可调用的 Apifox OAS 工具、未解析本地 schema/response/parameter/requestBody/pathItem `$ref`、出现外部 `$ref`、歧义 JSON media/type时脚本失败;feature/done gate 必须用 `--check` 重算 canonical 输出,仅 source SHA 相等不算当前。worker 必须先调用当前环境实际暴露的 Apifox OAS 工具。**模型不得整读 `oas.json` 或 `api_contract.json`**;确定性脚本消费完整契约,模型只读步骤 8.2 的 `data_model_packet.json`。worker 内禁跑全量 `build_runner`(无 `--build-filter` 即违规,全量 codegen 留给串行扇入)。

### 8.2 组件清单 + 数据槽绑定(Track B)
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.agents/skills/iff/scripts/bind_data_slots.py --manifest spec_dir/component_manifest.json --api-contract spec_dir/api_contract.json --interaction-contract spec_dir/interaction_contract.json --out spec_dir/data_slot_bindings.json
# 同一 feature 的状态分属多 board 时,每 board 先产上述两个文件,然后 assembly 在 feature root 合并:
python3 ~/.agents/skills/iff/scripts/merge_feature_data.py --spec-root lanhu/specs/<feature> --feature-manifest .iff/features/<feature>.json --api-contract lanhu/specs/<feature>/api_contract.json --out-manifest lanhu/specs/<feature>/component_manifest.json --out-bindings lanhu/specs/<feature>/data_slot_bindings.json
python3 ~/.agents/skills/iff/scripts/make_data_model_packet.py --spec-root spec_dir --out spec_dir/data_model_packet.json
# 模型只读 data_model_packet.json,完成其唯一 action 后重生成;直到 action=none/进入 gate repair。
python3 ~/.agents/skills/iff/scripts/check_data_bindings.py --manifest spec_dir/component_manifest.json --api-contract spec_dir/api_contract.json --bindings spec_dir/data_slot_bindings.json
```
输出: `component_manifest.json`(静态/动态槽候选)+ `data_slot_bindings.json`(槽↔endpoint/method/status/variant/JSON path/type/transform,含输入 SHA)+ `data_model_packet.json`(≤8KB,一个 action)。多 board 合并产物为 feature root 唯一输入,每槽增加 `state/board`;不同 state 可复用同 node id,测试 id 自动变为 `DATA-SLOT:<state>:<node>`。
硬门: 每个动态槽**恰好一次**:①字段身份完整存在于当前契约、transform/type 兼容且 `confirmedByModel=true`;或②非空 `staticReason` 且 `confirmedByModel=true`。多 state 以 `(state,node)` 为唯一键;合并脚本对每 board 的 manifest/bindings/API SHA 和槽集合做校验,旧绑定或状态冲突必须失败。任何 confidence 都不能绕过语义确认;字段只能从 packet 的真实候选中选择,模型不得发明字段。候选过多固定 `choose_operation → choose_field_group → choose_field`,每包≤8KB且一次只解决一个槽;确定性 gate failure 标记 `requiresJudgment=false`,模型只负责编排脚本/当前状态。动态槽**先钉死设计宽度**(IMPL-DATA)。

### 8.3 数据接入 + 交互接线 + 状态选择(Track B,上线页业务层)
固定方式(可见像素由脚本钉死,业务/数据/交互由模型写,门兜底):
- **可见层不由模型重建**:像素就是步骤 7 `generate_canvas.py` 产出的带 key 坐标画布(几何/样式脚本喂入)。模型只在其上做三件事:① 把动态文本/金额槽接到**同源 fixture/DTO**(槽位来自 `data_slot_bindings.json`,默认值=设计展示值);② 按 `apply_status` 等状态选择要渲染的态;③ 把 `interaction_contract` 的 intent 接到透明热区事件 + 页面编排 + 导航/风控链。**不用 Row/Column 重排可见像素,不手写 `Positioned`/颜色/圆角/字号**(要改像素就改 `generate_canvas.py`)。
- **领域逻辑必须被运行时调用,不能只被测试引用**。
- Repository 真 HTTP + mock **同接口同源**(同 DTO 形,可注入互换);loading/error/empty/轮询/禁截图按交互规则接;切 mock⇄API(同值)可见层零变化、切不同值可见文本必须变化(数据驱动证据)。
- 模型按当前工程写 `data_runtime_manifest.json`:只覆盖当前 feature operation 闭包——所有已确认 binding 用到的 operation 必须恰好一条;无 SLOT 的业务 operation 必须 `confirmedByModel=true`。每条记录非空 `id/publicMethod`、`endpoint/method/interface/real/mock/dto/mapper/consumer/requiredStates/stateTargets`;脚本验证 import graph,模型不手算 reachability,也不把项目 OAS 的无关 endpoint 拉入当前 feature。
- 所有网络 operation 固定需要 loading/success/error;响应字段路径含 `[]` 时脚本自动要求 empty;retry/polling/refresh 等只在当前业务事实支持时由模型加入。
- 设计 slots 是展示真值,API OAS 是传输真值,mapper 是唯一桥。`make_visual_fixture` 同时产 `.source.json`;fixture seed 或生成 Dart 任一 SHA 变化即 stale。设计 fixture 只用于 preview/test seed,不得冒充生产 HTTP response。
- 严格 TDD 不增加 Flutter 冷启动:RED、GREEN 各调用一次 `run_feature_tests.py`,同一 machine run 同时写 interaction/data evidence。每个真实字段有 `DATA-SLOT:<node>`(多状态为 `DATA-SLOT:<state>:<node>`),每 operation 有 `DATA-REPO:<id>` 与所有 `DATA-STATE:<id>:<state>` case。`check_data_coverage.py` 要求:SLOT 通过 public widget/app surface 对同一 `(state,node,field)` 输入两值并断言两个可见输出;REPO 通过 public repository API + 本地真实 HTTP 断言 method/path/200/映射后 DTO;STATE 通过 public UI 断言 manifest 的确切 `key/text`。最终 `run_client_device_tests.py` 从 `app.main()` 在 Android/iOS 一次执行交互+SLOT/STATE;SLOT 自动保存两张像素不同 PNG,STATE 一张,两域 evidence 绑定同一命令/stdout 与当前输入 SHA。禁止手写 action/observed/capture manifest。
硬门: 上线页可见层是步骤 7 的带 key 数据驱动画布(非静态 golden、非 Offstage 充数);`check_render_fidelity.py` 通过;`check_interaction_wiring.py` 通过;`check_data_feature.py` 重算 canonical OAS、bindings、feature operation closure、API integration、fixture、public behavior coverage、RED-GREEN、真实 Android/iOS runner evidence 并产当前 `data_gate_report.json`。`liveApiVerified=true` 只能来自 `run_live_api_tests.py`,且 gate 用 `check_live_api_evidence.py` 对当前 request config/base URL 再发真实 HTTP 并验证 status/schema;要求测试环境/生产契约时传 `--require-live-api`,否则不得宣称 live 端到端已验证。

### 9. 真实运行截图
命令(Android):
```bash
# 在占用设备前验证 scene、页面、生成策略、入口及 Android 原生启动窗口一致：
python3 ~/.agents/skills/iff/scripts/check_capture_readiness.py --project-root . --entry lib/main.dart --scene spec_dir/scene.json --page-source lib/<feature>/presentation/<online_page>.dart --policy-source lib/<feature>/presentation/<state>_status_bar_policy.dart --startup-policy-source lib/<feature>/presentation/<initial_state>_status_bar_policy.dart --out spec_dir/capture_readiness.json
# 设备窗口互斥(并行 worker 共享一台 emulator/simulator):安装/启动/截图前必须持锁,
# 锁窗口 = 本步骤起,至步骤 11 复验截图结束;成功、失败、error 任何退出路径都必须 release。
python3 ~/.agents/skills/iff/scripts/device_lock.py acquire --lock .iff/device.lock --label "$ROW_TITLE" --timeout 900
# 非首屏的 feature 页加 --route /<feature-route> 直接启到该页,**不要改 main.dart 的 initialRoute**。
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py --platform android --device emulator-5554 --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
# 无需 repair 时立即释放;需 repair 则持锁跑完步骤 11 的 rerun/复验截图后释放:
python3 ~/.agents/skills/iff/scripts/device_lock.py release --lock .iff/device.lock
```
命令(iOS):
```bash
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py --platform ios --device "$SIM_ID" --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
输出: `actual.png`(**组件上线页**截图,真机像素诊断用)和 `visual_manifest.json`(`actual_source=simulator_screenshot`,`device_id`,`project_root`,`app_hashes`,`runtime_input_hashes`,`launch_command`,`route`,`viewport`,`capture_command`,`timestamp`)。Dart/资产/pubspec/路由/设备任一变化后旧证据 stale。结构化逐组件保真门用的是 `check_render_fidelity.py`(真实渲染 trace,步骤 12),不再抓 golden.png 做像素比对。
硬门: 推荐视觉专用 emulator profile,宽度直接设为 artboard 宽度(例如 750),density 固定 160,隐藏 debug banner并固定时钟。设计稿伪状态栏由 `system_ui_filter.py` 剔除,App 不得重画。`check_capture_readiness.py` 必须验证生成策略与 scene 一致:含 status-bar exclusion 时使用透明 edge-to-edge 且不预留 top inset；不含时隐藏顶部 overlay 且同样不预留 top inset。入口须在 `runApp` 前应用初始策略；Android LaunchTheme/NormalTheme 与 FlutterActivity 必须匹配启动策略,hidden 启动不得闪现系统栏。截图只允许真实 `adb screencap`/`simctl screenshot`;不得 resize actual,如必须裁剪只能做确定性 top-crop,禁止 center-crop;`actual_source != simulator_screenshot` 不能 `done`;`actual.png` 不能由 reference 派生。

### 10. 自动 diff
命令:
```bash
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.agents/skills/iff/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
python3 ~/.agents/skills/iff/scripts/make_visual_gate_report.py --spec-dir spec_dir --out spec_dir/visual_gate_report.json --component-registry .iff/shared_components.json --project-root .
python3 ~/.agents/skills/iff/scripts/check_visual_board.py --spec-dir spec_dir
```
输出: `diff_report.json`、`diff_heatmap.png` 和 `repair_plan.json`;`diff_report.json` 至少包含 `ssim`、`pixelMismatch`、`viewportIssues`、node-level `bboxIssues`、`textIssues`、`assetIssues`、`shapeIssues`、颜色 delta、字号/行高差异、缺失 asset 区域、按影响面积排序的 `topP0`;`repair_plan.json` 必须去重合并同一 bbox/score 的设计节点 alias,保留 `rawActionCount` 与 dedup 后 `actionCount`,把差异按 `viewport` → `layout_region` → `asset_region` → `text_region` → `shape_region` → `fine_pixels` 排序,并给出每项的组件、node、role、score、expected、observed、structuralDelta、diagnostic、repairAction、sourceNodes。若存在 `implementation_map.json` 或 `actual_layout_trace.json`,必须合并到 `implementationHints` 和 `actualTrace`;若不存在,必须在 `diagnosticWarnings` 中说明边界,不得凭空编造文件、widget 位置或真实 bbox/font 差异。
硬门: actual/reference 尺寸不一致、viewport/crop 错、结构化 fidelity 失败、shape/asset/text 平坦区真缺陷必须进入单次 repair,复验仍失败则 `error`。SSIM/pixelMismatch 是跨引擎诊断与 repair 排序信号,不直接阻断 done、不得为过阈值反复打磨。`visual_gate_report.json` 对 reference/actual/fidelity/diff/manifest 全部记录 SHA-256;任一输入变化即 stale,每个 board 必须独立通过。
额外视觉硬门:`visual_diff.py` 对 expected widget coverage 外的非 AA 显著差异输出 `unexpectedIssues`;`make_visual_gate_report.py` 将其分类为 `unexpected_region`,不得用全局 SSIM 代替。

### 11. diff 驱动单次修复
固定单次流程:**模型只读 `repair_plan_top.json`**(summary+topAction+首批同类 action;完整 `repair_plan.json` 可达 177KB,属脚本产物禁整读)→ 只处理 dedup 后最大 P0 类别和第一批同类 action → 按优先级修截图尺寸/裁剪/viewport、节点位置尺寸、资产缺失、文字字号/行高/weight、颜色/圆角/阴影、细节间距中的命中项 → rerun app → capture screenshot → rerun diff → 记录 `post_repair_diff_report.json` 和 `visual_report.md` → 进入下一需求。
硬门: 每个页面/每行最多执行一次 repair;禁止 repeat/while/until threshold 式循环打磨;禁止只改测试、用 reference 图当背景或标 done 后再补。`diff_report.json` 是测量,`repair_plan_top.json` 经 `visual_model_packet.json` 暴露的当前 action 是模型唯一修复输入。若无 actualTrace,不得把区域像素差直接声称为 bbox 错。复验后只要 viewport、结构化 fidelity、shape/asset/text 真缺陷仍失败就写 `error`;仅 SSIM/AA 诊断残差不阻断。

### 12. done 前审计
命令(**host `flutter test` 只允许 3 次调用**:③红灯一次、⑤绿灯一次、本步骤一次;另保留 1 次不可省略的 Android/iOS 目标客户端全 case 终验——trace 测试先生成再随全量套件同跑,禁止逐 case/逐文件起跑):
```bash
# 先生成 trace 测试(它随下面的全量 flutter test 一起执行并写出 actual_layout_trace.json):
python3 ~/.agents/skills/iff/scripts/merge_shared_expected.py --expected lib/<feature>/presentation/<canvas>.dart.expected.json --local spec_dir/shared_components.local.json --scene spec_dir/scene.json --out spec_dir/merged_expected.json
python3 ~/.agents/skills/iff/scripts/gen_layout_trace_test.py --expected spec_dir/merged_expected.json --page-import package:<pkg>/<feature>/presentation/<online_page>.dart --extra-imports package:<pkg>/<feature>/data/<repo_or_fixture>.dart --page-type <OnlinePageWidget> --page-expr "<OnlinePageWidget(repository: Mock<Feature>Repository.design())>" --trace-out spec_dir/actual_layout_trace.json --out test/<feature>/<feature>_layout_trace_test.dart
flutter test        # 唯一一次:交互测试 + trace 测试 + 回归全在这一次调用里
flutter analyze
python3 ~/.agents/skills/iff/scripts/check_visual_manifest.py spec_dir/visual_manifest.json
python3 ~/.agents/skills/iff/scripts/check_fixture_source.py --root .  # 自动探测 *VisualFixture 符号:test 与运行时须引用同一份(同源)
python3 ~/.agents/skills/iff/scripts/check_render_plan.py spec_dir/render_plan.json
python3 ~/.agents/skills/iff/scripts/check_design_artifacts.py --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_implementation_map.py --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json
python3 ~/.agents/skills/iff/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_completeness_report.json
python3 ~/.agents/skills/iff/scripts/check_interaction_contract.py --contract spec_dir/interaction_contract.json --out spec_dir/interaction_contract_report.json
python3 ~/.agents/skills/iff/scripts/check_interaction_coverage.py --plan spec_dir/interaction_test_plan.json --test-root test --evidence spec_dir/interaction_test_evidence.json
# 目标客户端终验(main 串行扇入后只跑一次;同一 Flutter 输出生成两域 evidence):
python3 ~/.agents/skills/iff/scripts/run_client_device_tests.py --platform android --device <device-id> --interaction-plan spec_dir/interaction_test_plan.json --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root integration_test --project-root . --interaction-evidence spec_dir/interaction_device_evidence.json --data-evidence spec_dir/data_device_evidence.json
python3 ~/.agents/skills/iff/scripts/check_interaction_device_evidence.py --plan spec_dir/interaction_test_plan.json --test-root integration_test --project-root . --evidence spec_dir/interaction_device_evidence.json
python3 ~/.agents/skills/iff/scripts/check_data_device_evidence.py --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root integration_test --project-root . --evidence spec_dir/data_device_evidence.json
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --skill-dir ~/.agents/skills/iff --feature-manifest .iff/features/<feature>.json --manifest lanhu/specs/<feature>/.iff/workers/<worker>.receipt.json
python3 ~/.agents/skills/iff/scripts/check_model_context.py --skill-dir ~/.agents/skills/iff --spec-root lanhu/specs/<feature> --project-root . --feature-manifest .iff/features/<feature>.json --out lanhu/specs/<feature>/model_context_report.json
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.agents/skills/iff/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
# Track B 新门:
python3 ~/.agents/skills/iff/scripts/check_interaction_wiring.py --lib-root lib --test-root test --entry lib/main.dart --pubspec pubspec.yaml --contract spec_dir/interaction_contract.json --out spec_dir/wiring_report.json
python3 ~/.agents/skills/iff/scripts/check_interaction_feature.py --spec-root lanhu/specs/<feature> --project-root . --feature-manifest .iff/features/<feature>.json --out spec_dir/interaction_gate_report.json
python3 ~/.agents/skills/iff/scripts/check_data_bindings.py --manifest spec_dir/component_manifest.json --api-contract spec_dir/api_contract.json --bindings spec_dir/data_slot_bindings.json
python3 ~/.agents/skills/iff/scripts/check_data_runtime.py --project-root . --runtime-manifest spec_dir/data_runtime_manifest.json --api-contract spec_dir/api_contract.json --bindings spec_dir/data_slot_bindings.json --out spec_dir/data_runtime_report.json
python3 ~/.agents/skills/iff/scripts/check_api_integration.py --api-contract spec_dir/api_contract.json --lib-root lib --runtime-manifest spec_dir/data_runtime_manifest.json --out spec_dir/api_integration_report.json
python3 ~/.agents/skills/iff/scripts/check_data_coverage.py --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root test
python3 ~/.agents/skills/iff/scripts/check_data_evidence.py --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root test --evidence spec_dir/data_test_evidence.json --app-root lib --device-evidence spec_dir/data_device_evidence.json
python3 ~/.agents/skills/iff/scripts/run_client_device_tests.py --platform android --device <device-id> --interaction-plan spec_dir/interaction_test_plan.json --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root integration_test --project-root . --interaction-evidence spec_dir/interaction_device_evidence.json --data-evidence spec_dir/data_device_evidence.json
python3 ~/.agents/skills/iff/scripts/check_data_device_evidence.py --bindings spec_dir/data_slot_bindings.json --runtime-manifest spec_dir/data_runtime_manifest.json --test-root integration_test --project-root . --evidence spec_dir/data_device_evidence.json
# 仅当有可访问的 test/staging 环境时;live_api_requests.json 为每个 runtime id 提供 path/query/header/body/expectedStatus:
python3 ~/.agents/skills/iff/scripts/run_live_api_tests.py --api-contract spec_dir/api_contract.json --runtime-manifest spec_dir/data_runtime_manifest.json --requests spec_dir/live_api_requests.json --base-url https://<environment> --out spec_dir/live_api_report.json
python3 ~/.agents/skills/iff/scripts/check_live_api_evidence.py --api-contract spec_dir/api_contract.json --runtime-manifest spec_dir/data_runtime_manifest.json --report spec_dir/live_api_report.json
python3 ~/.agents/skills/iff/scripts/check_data_feature.py --spec-root lanhu/specs/<feature> --project-root . --runtime-manifest spec_dir/data_runtime_manifest.json --out spec_dir/data_gate_report.json
# 结构化逐组件保真门(替代 golden-vs-golden;不变量③⑥):trace **真实上线页** vs render_plan 期望。
# --page-type/--page-expr 必须是真实页面(注入**同源设计 fixture** 的构造),**不是孤立画布**——
# 这样错误的顶部 SafeArea、Stack 坍塌等页面级包裹 bug(见 memory)才会被 getRect 抓到;--extra-imports 传 repo/fixture。
# 多状态特性:每状态一个 trace 测试文件,全部在上面同一次 flutter test 里执行。
# merged_expected 含公共组件区域期望(bbox+presence,key=源 node id;挂载缺失/位置错/坍塌被 missing/bbox 抓到):
python3 ~/.agents/skills/iff/scripts/check_render_fidelity.py --trace spec_dir/actual_layout_trace.json --expected spec_dir/merged_expected.json --tokens spec_dir/tokens.json --diff-report spec_dir/diff_report.json --out spec_dir/render_fidelity_report.json
python3 ~/.agents/skills/iff/scripts/make_visual_gate_report.py --spec-dir spec_dir --out spec_dir/visual_gate_report.json --component-registry .iff/shared_components.json --project-root .
python3 ~/.agents/skills/iff/scripts/check_visual_board.py --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_visual_provenance.py --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_visual_feature.py --spec-root lanhu/specs/<feature> --manifest .iff/features/<feature>.json
python3 ~/.agents/skills/iff/scripts/check_feature_manifest.py --manifest-root .iff/features
python3 ~/.agents/skills/iff/scripts/check_shared_component_consumers.py --registry .iff/shared_components.json --project-root .
```
硬门: CSV 行仍是 `doing`;worker 已加载当前 iFF 规则且 compliance 校验通过;reference 是完整 artboard;actual 是真实模拟器截图(**组件上线页**,非 golden 静态画布);fixture seed/生成文件 provenance 当前;交互和数据 case 在同一 RED/GREEN 指纹下通过且最终有目标 Android/iOS 客户端运行时证据;当前 feature operation closure 的真实 method/path、共享 interface/DTO/mapper、入口 consumer 和适用状态全部由 `check_data_feature` 当前重算,项目 OAS 的无关 operation 不扩张 scope;多状态数量一致;`render_plan` 未使用整图冒充;页面结构由真实组件、文本、按钮、卡片、输入框、状态区域组成;**`check_render_fidelity` 通过(真实上线页逐组件:每节点 bbox≤2px、主色 RGB≤3、字号/圆角≤1px、文案 100%、token 100%;缺节点=Offstage/坍塌判失败;**icon/asset 区域形状门**:`--diff-report` 接入后,asset 区域原始 pixelMismatch>0.10 判 `asset_shape` 失败——bbox/主色看不见"位置对、颜色对、字形错"的图标,平坦区像素通道看得见,AA 残差(~<5%)不受影响)= 视觉验收的 PASS 门**;`visual_diff` 的像素 `ssim/pixelMismatch` 只作诊断,**不作 done 阻断**;`repair_plan.json` 必须存在但像素派生 p0Count 不直接阻断;**interaction_gate + data_gate 都由 done gate 重算当前 fingerprints**;test/analyze 通过。全部满足后才写 `status=done`、`actual_screenshot`、`visual_manifest`、`visual_report`。
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
- 每行 `done` 前必须强校验:CSV 原 status 还不是 `done`;manifest 推导的全部 board+assembly v3 receipt 当前且无多余 worker;`model_context_report.json` 由 done 重算且全部 prompt/packet≤8KB、单 action、源 SHA 当前;每个 feature state 有独立 board 与 `state_changes.json`;Done Gate 从当前 PNG/layout/trace/expected/tokens 重跑 `visual_diff.py` 与 `check_render_fidelity.py` 并逐字段比对,手改报告无效;最终 `actual.png` 来自真实运行截图;interaction/data 共享一次目标客户端运行;公共组件 consumer、文件所有权、test/analyze 全部通过。
- 最小 CSV 回写:缺 `reference.png`、无法生成 `actual.png`、或单次 repair 复验后仍无法消除 P0/P1 视觉问题时,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求;若表格有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,同步写入对应路径。
</visual_gate>

<success_criteria>
- iFF 被 goal 调起后:读表 → 每行按 `<pipeline>` 固定命令产出机器视觉产物 → 并行实现各未处理行 feature(互不踩踏)→ 串行集成(依赖/资产/路由/codegen/analyze 一次性)→ 真机截图 diff → 单次 repair 复验 → 回写 `status/error/spec_dir`。
- `flutter test` 与 `flutter analyze` 无 error;每个 worker 有当前 v3 receipt;每个 feature/state 有独立、当前、可重算 board gate;页面由真实 Flutter 组件逐层渲染而非整图铺底;交互/数据证据与 fixture 同源且共享一次客户端运行;结构化 fidelity、viewport、shape/asset/text 真缺陷硬门通过;公共组件 consumer 绑定当前源码+合同;SSIM/P0 像素诊断残差只记录不阻断。
</success_criteria>

<final_reminders>
P0 — 坐标画布脚本化:可见层 dart 由 `generate_canvas.py`(步骤 6.7)产出,**禁止模型手写 `Positioned`**;设计字体必须真打包(SF Pro 用本机 `SFNS.ttf`),否则文字逐像素全错。新增渲染语义改 `generate_canvas.py`,不要在生成的 dart 里手补。
P0 — 跨引擎像素天花板(现实约束,已证明,勿白追):Flutter(Impeller)与 Figma/Lanhu 光栅化的字形/边缘抗锯齿必然不同。`visual_diff.py` 保留窗口 SSIM 与 pixelmatch 诊断供定位,但 `SSIM>=0.99` 对文字/矢量设计可能物理不可达。只修 `pixelMismatchRealDefect` 指向且被 viewport/结构化 fidelity/shape/asset/text 硬门确认的真实缺陷;**严禁为过像素阈值放宽参数或循环打磨**,AA 残差如实记录但不报错。
P0 — 固定流水线:worker 必须按 `<pipeline>` 的 0-12 步执行,每步固定输入/输出/命令/硬门;不得跳步、合并步骤、凭经验替代脚本产物,或在缺输出时继续实现。
P0 — worker 规则注入:main 必须用当前 preflight + feature manifest 生成≤8KB v3 角色合同;worker 不整读通用规则,`complete_worker.py` receipt 必须绑定 canonical prompt、结果、输出、三份规则、renderer/contract library/preflight SHA;main 重算通过后才接收。
P0 — 确定性必须脚本化:worker prompt/合规校验、分类、取稿、cover 下载、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、fixture、interaction contract/test plan、交互覆盖审计、资产注册、真机截图、manifest、diff、repair plan、审计都必须由 `~/.agents/skills/iff/scripts/` 下脚本完成;禁止调用 `fd/scripts`、项目本地 `scripts/`、临时脚本或让 worker 手工判断。
P0 — 非确定性只留给模型:模型只能做项目约定适配、业务逻辑补全、组件组织和按 `repair_plan_top.json` 修代码;不能替代脚本生成 JSON、统计数量、判定阈值、比对截图、排序修复项或审计 provenance。
P0 — done 总门:`status=done` 只能在 `check_done_gate.py` exit 0 之后写入;模型无权豁免任何一项失败(包括"看起来是误报"——误报去修 gate 脚本,不许绕行)。文本节点(含动态槽)**严禁被固定高度 + 裁切(ClipRRect/clipBehavior)容器包裹**——下降部被裁会把 "days" 渲成 "davs" 且 bbox/主色保真看不见(R1 实测);chip/胶囊类背景由画布画,文本悬浮其上不裁切;此类缺陷由 done 总门的平坦区 text 真缺陷通道兜底。
P0 — 阅读纪律(token 预算属于正确性):脚本先产 `artifact_digest.json`;视觉/交互/数据模型分别只读 `visual_model_packet.json`、`interaction_model_packet.json`、`data_model_packet.json`,每份≤8KB且正好一个 action。OAS、完整 API/interaction contract、component manifest、bindings、state/anchors/test machine log 禁止整读;一次只解决 packet 点名的当前事实。`check_model_context.py` 统计字节/哈希/action 与避免的重复规则字节,`check_done_gate.py` 重算当前报告;不得把字节冒充具体 tokenizer token。
P0 — 公共组件模型上下文:批级语义判断只读 `component_model_packet.json`,每包正好一个 candidate;视觉 packet 的 candidate/modelField/hardFailure 也只能各暴露一个对象,不能用复数数组伪装“一个 action”。
P1 — `flutter test` 调用预算:每行 host ≤3 次(red/green/done 各一次),由 assembly 执行且 board 不运行;目标 Android/iOS 客户端由 main 扇入后 ≤1 次。RED/GREEN 用 `run_feature_tests.py`,客户端用 `run_client_device_tests.py`,两者都让交互/数据共享同一 Flutter 进程与输出。
P1 — 交互三层闭环:①锚定——交互文字的视觉引用只认 `board_index` 确定性检索(唯一命中绑定/多候选模型确认/零命中 pending_route),`resolve_interaction_anchors --check` 不过不得设计测试;②状态机——多状态 feature 必须 `make_state_machine` 骨架+模型填边+`--check`,每条迁移边=一条 INT-SM 规则;③journey——跨页边进 `.iff/flow_graph.json`(扇入合并+路由轻验),全部行 done 后生成故事地图并真机回放清单终验。
P0 — 99% 还原靠设计稿编译器,不是模型看图想象 UI:视觉实现主输入是 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`、`repair_plan.json`;`spec.md` 只能补充解释。
P0 — 字体与异常保真:scene→render_plan→canvas expected→真实页 trace→fidelity 必须保留并校验 fontFamily/fontStyle/fontWeight/letterSpacing/lineHeight;未知 Flutter 渲染异常不得清空,不可确定渲染的 vector 必须在生成阶段显式失败。
P0 — 第一版坐标编译:固定 artboard 根节点,用 `FittedBox` 或固定 artboard canvas 做适配,按 Figma `path/parent/children/bbox` + contract/render_plan 映射节点到 Widget,用真实 tokens/assets;先做到像,再谈工程优雅。
P0 — 保真量化门(结构化,不靠裸像素 SSIM,不变量③⑤):PASS 门 = `check_render_fidelity.py` 对**真实上线页渲染 trace** 逐组件达标——每可见节点 bbox 偏移 ≤ 2 logical px、主色 RGB 差 ≤ 3、字号/圆角误差 ≤ 1px、文案 100% 命中、token 100% 命中、无缺失(Offstage/坍塌)节点、**asset 区域形状达标(`--diff-report` 通道:区域 pixelMismatch ≤ 0.10,专治"位置/颜色对但图标字形错")**。像素 `SSIM`/`pixelMismatch`(`visual_diff.py`)**只作诊断**,受跨引擎抗锯齿天花板(~0.87 窗口SSIM / ~3% 真实差异,见下条)限制,**不作 done 阻断、严禁为过门放宽阈值**;真实缺陷修完仍有像素残差属天花板,据实记录。
P0 — 视觉一致性门:每行 green 后必须用完整设计 `reference.png` 与运行时 `actual.png` 对比;没有 `reference.png` 不得实现,没有真实设备 `actual.png` 不得 `done`;“截图一致”验收只认 emulator/simulator 运行截图,任何从 reference 派生出来的 actual 都是无效证据;主要布局、资产、颜色、字号、圆角、间距、首屏层级明显不一致时,必须根据 `repair_plan.json` 修改一次并重新截图复验;复验达标才允许 CSV 写 `done`,复验仍不达标写 `error` 并进入下一需求;不得用 Material 默认图标、占位盒子、近似卡片替代设计稿已导出的资产;main 扇入后必须重新截图验收,发现差异也只能单次修正实现。
P0 — 并行扇出只写各自 feature 文件夹,**绝不并行改共享文件**(pubspec/路由/DI/codegen/analyze 一律留到串行扇入一次性做)。
P0 — 公共组件复用:`componentId` 精确命中可直接复用;结构哈希只生成待模型语义确认的 candidate,不能自动复用。确认后必须有 family contract、跨文件 alias/role-map、widget+contract 哈希和 consumer 列表;组件/合同变化重验全部 consumer。创建/修改仅在串行阶段,worker 只读挂载;`covered_by_shared_component` 不进画布;`assets_incomplete` 显式登记。
P0 — 单行 **TDD**:先写测试跑出 red 再实现;测试源 = UI 理解 + interaction plan + data bindings/runtime manifest;交互每条覆盖 HAPPY/BOUNDARY/FAILURE,数据每个动态槽/operation/适用状态都有 DATA case。case id 必须在实际执行的 `testWidgets` 名称,经公开页面入口并断言可观察结果;`run_feature_tests.py` 一次运行记录两域 case 级 red/green 与当前 plan/bindings/runtime/test 指纹,最终在目标 Android/iOS 客户端取得运行时证据。
P0 — iFF 只定**流程**,不定实现细节:架构/目录/命名/资产·路由·状态·接口口径,一律由 subagent **读当前工程(目录+相关代码+工程规则文件)后随项目实现**,绝不自创或硬编码某套架构。
P0 — 视觉实现红线:无论目标是否写“截图一致”,都禁止把设计稿截图、完整 artboard、reference 派生图作为组件可见层、背景图、`Image.asset`、`DecorationImage`、整图铺底或透明热区覆盖;交互热区可以叠加在真实视觉节点上,但不能替代视觉节点;验收只看真实 Flutter 页面/组件渲染结果与设计稿的一致性,必须组件逐层实现、截图比对、按 `repair_plan.json` 单次修复并复验。
P0 — 视觉 provenance:每个 `reference.png`/`actual.png` 旁必须有 `visual_manifest.json`;最终 `actual_source` 必须是 `simulator_screenshot`,并绑定拍摄时的 project/app/runtime inputs/launch route/device/viewport;不得是 `widget_golden` 或 `generated_from_reference`,当前输入变化后旧证据必须失败。
P0 — runtime 数据同源:视觉测试 fixture、widget preview、app shell/mock repository 必须使用同一份 fixture/provider;多状态长图必须在 app runtime 返回同一组状态数据,禁止测试多状态但最终 app 只注入默认单状态。
P1 — 扇出并发先定为**每批 2 个互不影响的功能**,且**必须真并行**(在当前并发上限内连续 `spawn_agent`,超出槽位有界排队;实测串行是 40min/页的第一大原因);设备窗口(9-11)是唯一互斥点,用 `device_lock.py`(mkdir 原子锁,任何退出路径必须 release,stale 锁自动破除)。
P1 — iFF 读表 + 回写 `status/error/spec_dir`;`goal` 是外部指令,iFF 不实现它。
P1 — 工作队列:**只选 status 为空**的行,每批 N(默认 2);选中**即刻标 `doing`**(认领/防重/可续),完成标 `done` 或 `error`。
P1 — 单行顺序:确认视觉策略 → 本 skill 脚本取稿/下载完整 cover → **当前环境实际暴露的 Apifox OAS 工具读取契约** → 生成 scene/tokens/assets_manifest/groups/layout_contract/render_plan/fixture/interaction_contract/interaction_test_plan → 读项目 → 按交互测试计划设计测试(接口用例用真实契约 mock)→ 坐标编译实现 UI → 接口接入+mock 渲染 → 真实设备截图 diff → 单次 repair 复验 → 交互覆盖/视觉/manifest 自检。
P1 — 运行时外部依赖:**当前环境可调用的 Apifox OAS 工具**、Lanhu 网络/API 访问、Flutter 设备/模拟器;真跑/测试前需在目标环境就绪。
P2 — `spec_dir` 缓存命中且包含 `reference.png` 才跳过取稿(幂等)。
P1 — 可见层工具链回归自测(改完即跑):任何对 `generate_canvas.py` / `gen_layout_trace_test.py` /
`check_render_fidelity.py` 的改动,改完**必须**跑 `python3 ~/.agents/skills/iff/scripts/selftest_canvas.py
--project <flutter工程>`——它用 `iff/selftest/` 的合成 reference 走完整链(生成画布 → flutter analyze 干净
→ 生成 trace 测试 → flutter test → check_render_fidelity 逐节点过),覆盖 text/金额/圆角 shape/渐变/
瘦高 Vector→'<'、矮宽 Vector→'v' chevron/输入值文本等易回归节点类型。绿了才提交。这是为根除"改一处编译/
运行回归被下一轮 worker 撞上"(曾致 R5/R7 训练)而固化的纪律。
