---
name: iff
description: Use when an external `goal` command drives batch implementation of Flutter frontend from a design-spec sheet (CSV/Excel). `iFF` = implement Flutter Flow. 读表 → 画板并行扇出 → feature assembly(RED → 资产/字体/pubspec 打包 → GREEN)→ 串行扇入集成(依赖/路由/codegen/analyze)→ 回写。落地到当前 Flutter 工程, 触发于 "iFF"批处理设计稿表格。
---

<role>
iFF 在 MAIN session 运行,是**编排者**:被外部 `goal` 指令调起(goal 设目标 + 验收标准),读取设计稿表格,**画板并行扇出**后由 feature assembly 完成 RED → 资产/字体/pubspec 打包 → GREEN,再**串行扇入**集成其余共享改动(依赖/路由/codegen/analyze),最后逐行回写结果。落地到 iFF 运行时的当前 Flutter 工程,遵循其架构/规范。取代旧 fc。
</role>

<context>
## 调用与分层(已确认)
- `goal` 是**外部指令**(非本仓库 skill):设定目标 + 最终验收标准,调起 iFF。iFF 不实现 goal,只被它驱动。
- iFF 自身是编排者,内部用**并行 subagent(Codex collaboration tools 扇出/扇入)** 处理全表;不再是"外部喂一行"的单行 worker。
- 工具适配(Codex):fetch/board/contract worker 用 `spawn_agent` 创建(`message` 传入 `worker_prompt.md` 全文,`fork_turns: "none"`);实际并发不得超过当前可用槽位(主会话也占槽)。槽位足够时连续完成本批全部 `spawn_agent` 调用后才开始等待;槽位不足时按最大可用并发分波,每波先 spawn 满再 `wait_agent`,释放槽位后补下一波,禁止退化为 spawn 一个就等待一个。用 `wait_agent` 收结果;运行中的 agent 需补充输入时用 `send_message`,已空闲且要继续执行时用 `followup_task`。shared worker 是唯一 liveness 例外:必须把本地 worker 进程放在 `shared_worker_supervisor.py run` 后并行启动,禁止直接 `spawn_agent` 或裸跑进程。主会话只汇总结果并执行串行扇入。
- 子 agent 不会天然继承 main session 已加载的 skill 正文。每个 worker prompt 必须由 `make_worker_prompt.py` 生成;fetch/board/contract/shared worker 先读 `iff/SKILL.md` 与 `iff/test_rules.md`,**assembly 例外:只执行生成 prompt 内的版本锁定、有界 assembly contract,禁止整读 440 行 SKILL/test_rules**。shared prompt 同时产出 `*.shared_invocation.json`,且只认 `shared_worker_supervisor.py run` 的 exit 0;assembly prompt 产出 `*.assembly_invocation.json`,main 必须用 `assembly_worker_supervisor.py prepare` → spawn/wait → `verify` 完成交接,本地进程调用必须改用其 `run` 包裹。worker 必须写 `worker_compliance.json`,main 扇入前用对应 supervisor/`check_worker_compliance.py` 校验。禁止手写短 prompt 直接启动 worker。

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
**并行硬约束**:工程共享改动点(`pubspec.yaml`、路由/导航表、DI、主题、l10n、`build_runner`、`flutter analyze`)**不能无锁并行写**,否则互相踩踏。唯一 assembly 例外是 `prepare_assembly_packaging.py`:它只登记当前 feature 已收集的资产目录/必需字体,用工程级锁原子更新 `pubspec.yaml`,且必须发生在有效 RED 后、唯一 GREEN 前;依赖和其余共享改动仍只在 main 串行扇入。故:
- **公共组件(串行解析,扇出前)**:跨行共享的导航头/底部 tab 等区域,由 main 在扇出前统一解析(检测 → 查注册表 → 缺失则并行实现 + 串行收口登记,见 instructions 2.5);worker 对公共组件**只读复用**(挂载已登记 widget),严禁在扇出中创建/修改公共组件文件;公共组件区域的视觉缺陷不占 worker 单次修复预算,记录后留到串行扇入统一处理。
- **扇出(画板级三段式;R1 实测教训:行级扇出让 1 个 worker 串行磨 8-11 张板,54min/页)**:
  - **①fetch-worker(每行一个,行间并行)**:对本行每张板依次跑固定流水线 0-3 步脚本(取稿/scene/tokens/assets_manifest/groups → `lanhu/specs/<feature>/<board>/`),纯脚本执行、不读产物、不做判断;返回每板取稿成败。之后 main 跑 detect/建缺失公共组件(串行)/重跑 detect/预拉 OAS(见 instructions 2.5)。
  - **②board-worker(每板一个,全部并行;视觉编译单元)**:输入 = 本板 spec_dir + 公共组件 local 文件;产出 = 本板 `<state>_canvas.dart(+expected/slots)`、`<state>_canvas_colors.dart`(无 token 时可不存在)、`artifact_digest.json`、本板 implementation_map 片段、本板保真准备。**只写本板专属文件**(R1 产物已证明各板 canvas/expected/slots/colors 天然不相交);禁写 page/selector/fixture/trace 测试/路由/pubspec;**不跑任何 `flutter test`**(trace 测试依赖 assembly 才确定的上线 page/fixture,测试调用预算全部归 assembly)。
  - **②'contract-worker(每 feature 一个,与 board-worker 同批并行)**:输入 = interaction 文本 + `.iff/board_index.json` + 各板 specs + 预拉 `oas.json`/`oas_ref_resources.json`(全部在 2.5 末尾就绪,与画板产物零依赖);产出 = 步骤 6 系列全部契约(interaction_contract/完整性门/状态机/`interaction_anchors.json`/api_contract/test plan,`--check` 已过),最后必须以 `check_contract_artifacts.py` exit 0 收口。只写 feature 级 spec_dir 契约文件;禁碰 lib/test/板产物/共享文件;不跑任何 flutter 命令;总门非零时必须返回失败,不得 `ok=true`。
  - **③assembly-worker(每 feature 一个,板 worker 与 contract worker 全部返回后串行)**:先跑 `check_contract_artifacts.py` 消费并复验 contract-worker 的步骤 6 产物(非零立即停止,不重算)→ `assembly_plan_batch.py prepare` 一次性完成全板 audit/digest/确定性 plan 预填,模型只填小型 `assembly_decisions.json`,再由 `apply` 批量回填/校验(禁止逐板 patch 大 plan)→ selector/colors/同源 fixture/slot mapper + 测试空桩 → `assembly_tdd_guard.py red` 执行 TDD RED 一次(必须是缺功能/行为失败,不得是 packaging 失败)→ `prepare_assembly_packaging.py prepare` 在工程级锁内注册本 feature 全部画板资产目录和必需字体并签发绑定 RED 的 `assembly_packaging.json` → runtime page/trace 测试 → `assembly_tdd_guard.py green` 复验 packaging 新鲜度后执行 GREEN 一次并产出每板 canonical `actual_layout_trace.json`(`pageType` 非空且 `nodes` 为非空 node-id→runtime-record 对象)→ 8.x 数据接入 → 设备 I/O(9-11,短窗口持锁,构建/repair 修改锁外)截图+带 `--require-actual-trace` 的 diff+单次 model-owned repair → 12 审计(feature 级一次并刷新 trace)→ 最后用 `assembly_completion.py issue` 运行 `check_done_gate`(含同一 trace schema 与 RED→packaging→GREEN chronology/provenance 复验)并签发完成证据。缺/空/旧/legacy-shaped trace 在消耗 repair 预算前失败;只有 assembly 写 feature 共享文件(此时板 worker 已退场,无并行冲突)。
  - 视觉 QA 硬门、单次修复预算、`actual_source` 证据规则不变(由 assembly 执行)。
  - 返回:依赖/资产/路由·DI 清单 + 各板 spec_dir + compliance + evidence + 视觉证据 + 成败。
- **扇入(串行,一次性)**:先复验各 feature 的 `assembly_packaging.json`/completion evidence → 汇总去重 → `pub add` 依赖 → 注册所有路由/DI → `build_runner` → `flutter analyze` → flow 图合并+新边路由校验 → **主会话真实设备最终视觉验收**。feature 画板资产/字体/pubspec 登记不得延后到这里;公共组件资产仍按 2.5 的 shared-worker 串行收口合同处理。
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
- **选行**:每批读 **N 行**(默认 N=4;设备池 <2 台时退回 N=2——设备 I/O 是唯一互斥点,单设备下更大的批只是在排队)**status 为空**的行;选中后**立即把这几行 status 改为 `doing`**(认领、防重、可断点续);文件层面已隔离,无需功能依赖分析。
</context>

<instructions>
1. **接收 goal**:从外部 `goal` 指令拿到目标 + 验收标准 + 目标表格路径。
2. **读表 + 认领**:解析 CSV/Excel,挑 **status 为空**的行,每批取 **N 行(默认 4;设备池 <2 台退回 2)**;**立即回写这几行 status=`doing`**(认领,防重复处理 / 支持断点续跑)。CSV 回写必须使用 `python3 ~/.agents/skills/iff/scripts/csv_row_status.py update --csv <sheet.csv> --title <exact-title> --expect-status '' --status doing`;恢复已失败的活动行必须显式改为 `--expect-status error`。终态回写必须在同一条原子命令里追加已有元数据列,例如 `--set-column error=<原因> --set-column spec_dir=<绝对路径>`;表中存在 `visual_report`/`actual_screenshot`/`visual_manifest` 时用同一参数一并写入,禁止先改 status 再分次补证据。后续确定性诊断若补强了已处于 `error`/`doing` 的行,允许 `--expect-status <same> --status <same>` 仅更新元数据;至少一个 `--set-column` 值必须真实变化,无变化 no-op 失败。脚本只接受唯一语义列(`title|标题`,`status|状态`)和唯一 `title+expected-status` 行,持锁后同目录原子替换,逐字节保留 UTF-8 BOM、分隔符、既有字段引号和换行;`--set-column` 只允许精确命中一个既有非 title/status 列;零匹配、重复匹配、状态漂移、未知/重复元数据列、非 UTF-8 或歧义 schema 一律失败且不写文件。读取诊断用同脚本 `inspect --csv <sheet.csv> --title <exact-title>`。认领后、任何 worker 启动前，必须用同脚本 `export --csv <sheet.csv> --title <exact-title> --expect-status doing --out <spec_dir>/row.json --interaction-out <spec_dir>/interaction.txt --ui-notes-out <spec_dir>/ui_notes.txt --api-out <spec_dir>/api.txt` 从唯一活动行生成规范输入；脚本按中英文语义列映射并逐字保留多行字段，禁止主会话或 worker 手工重建、裁剪或摘要这些字段。
2.5. **预取稿 + 批内公共组件解析(扇出前)**:main 用 `make_worker_prompt.py --mode fetch` 给每个选中行 spawn 一个 **fetch-worker**(行间并行),它对本行每张板跑固定流水线 0-3 步脚本(main 自己**不跑取稿、不读产物**)。**外部网络/审批边界**:fetch-worker 对每个联网命令只在当前 sandbox 执行一次;DNS/连接/network-sandbox/审批失败时禁止 worker 自行 `require_escalated`、重复重试或声称不可见的授权,必须按生成 prompt 的固定 schema 返回 `external_blocker`(`kind=external_network`,`owner=main_session`,`requires_escalation=true`,原样 exact argv + error),其它板各试一次后汇总。main 对 exact argv 去重,由 main 以 `allow the iFF workflow to fetch the user-provided Lanhu design` 为可见、限界 justification 请求一次审批,只执行报告的命令;成功后用 `followup_task` 让原 fetch-worker 从缓存继续本地 0-3 步,拒绝则 fail-visible,禁止伪造/跳过产物。全部 fetch-worker 完成后,对每个已编译 scene 先跑 `prune_system_ui_components.py --project-root <工程> --scene <spec_dir>/scene.json --registry <工程>/.iff/shared_components.json --out <spec_dir>/system_ui_prune_report.json --apply`,只退役 `source_spec_dir` 相同且 `canonical_nodes` 全部落在 `systemUiExclusions` 的生成组件;再跑 `detect_shared_components.py --spec-dirs <各行spec_dir> --registry <工程>/.iff/shared_components.json --out <工程>/.iff/batch_shared_components.json`(同时写各行 `spec_dir/shared_components.local.json`)→ 对 `status=missing` 的公共组件分两段:**实现并行**——每组件通过 `shared_worker_supervisor.py run` 启动一个专用 shared-component worker(同批并行发起),以 `best_asset_source` 行的机器产物 + `pooled_assets`(跨行资产池化:A 页缺切图的 icon 可用 B 页同位置切图)实现该组件到工程共享 widget 目录;实现阶段各 worker **只写自家 widget dart + 组件测试文件 + 拷自家资产文件,禁碰 pubspec/注册表、禁跑 `flutter analyze`/`flutter test`**(analyze/test 编译整个 lib 树,兄弟组件半成品文件会造成假红);组件**可见层必须由 `generate_canvas.py` 从源行该 group 子树生成**(key=源行 node id,产出组件自己的 `*.expected.json`——这是消费页逐页校验的基准)。**收口串行**——全部 worker 返回后 main 在一致的树上验门:逐个 `update_pubspec_assets.py` 注册资产 → **一次** `flutter analyze` 干净 + **一次** `flutter test`(覆盖本批全部共享组件 widget 测试)→ 逐个 `register_shared_component.py` 登记,**必须带** `--from-batch`(存源行 canonical 节点序)与 `--component-expected <组件expected.json>`(存组件 keyed 期望节点),`assets_incomplete` 时必须带 `--assets-incomplete` 显式记录,禁止静默近似;任一组件验门失败只登记通过的、失败组件按 missing 上报 → **重跑 detect 刷新 local 文件**(候选全部转 `reuse`)后才生成 worker prompt 并扇出。本步骤同时**预拉各行 OAS**:main 调 `read_project_oas` 原样存 `spec_dir/oas.json`,再调 `read_project_oas_ref_resources` 原样存首批缓存 `spec_dir/oas_ref_resources.json`;首批响应不得视为完整映射,必须按 8.1 的 `missing → MCP → merge` 确定性循环补齐传递闭包后才生成 contract-worker prompt。两份大 JSON 只供脚本消费,worker 缓存命中即免拉。随后跑 `make_board_index.py --specs-dir lanhu/specs --out .iff/board_index.json`(交互锚定的确定性索引)。无公共组件候选时仍须完成 OAS 闭包与索引后才扇出。
	   **shared worker 启动合同**:main 必须先跑 `make_shared_component_jobs.py`;所有 `missing` 都拆成独立 job,`paint_missing_positions` 是可恢复输入而不是 blocker,stdout 返回 `count/jobs/blockedCount/blockers`。随后逐 job 跑 `make_worker_prompt.py --mode shared --component-json <job>/component.json --spec-dir <job>`;stdout 返回 `{prompt,invocationContract}`。每个 shared worker 只能在该 contract 的 `runCommandPrefix` 后追加本地 worker argv并行启动;禁止 `spawn_agent`、裸跑进程或手写 prompt。supervisor 启动前清除旧 result/compliance,按当前 invocation/prompt/hash 绑定结果,默认 total=1200s、idle=300s(命令行可收紧/放宽,但不得同时关闭),超时终止完整进程组并写 `shared_failure.json`;worker stdout/stderr 流式转发并捕获到 `shared_worker.log`。shared worker 用 `make_render_plan.py --root-node` 生成带 `rootNode` 坐标空间、相对 group 原点的组件 render plan,再用 `prepare_shared_component_assets.py` 合并 `best_asset_source` 与 `pooled_assets`;真实导出原子 asset 覆盖整个组件 root 是合法的,脚本必须记录 `exported_design_asset` provenance,其 descendants 视为已覆盖,不得按页面整图误杀。对确认为可见、无 paint、无子节点且未被祖先原子 asset 覆盖的叶节点,该脚本必须从完整 `reference.png` 仅裁出节点 bbox 的局部原子资产,把 reference hash/source bbox/pixel bbox/node/reason 写入 `shared_assets.json.reference_fallbacks` 与节点 `assetProvenance`,禁止裁整张 reference。**随后必须用 `check_render_plan.py` 校验所有 required visible 节点有 paint source,并验证导出资产/局部兜底 provenance;伪造 provenance、页面整图兜底继续拒绝**,通过后才可调用 `generate_canvas.py`;generator 必须 exit 0 且 stdout `expectedNodeCount>0`,否则 worker 失败且不得写 success result;无颜色 token 时 generator 必须省略 colors import/file,测试必须由 `generate_shared_component_test.py` 从工程 `pubspec.yaml` 生成 package import,禁止 worker 手写相对 `lib` import。只有 worker exit 0 + 本轮新写且 `success=true` 的 `<job>/shared_result.json` + 新鲜当前 compliance 均由 supervisor 验过时才成功;exit 0、自然结束或旧文件均不是成功证据。
3. **扇出(画板级,Codex collaboration tools)**:**必须真并行——按当前可用 subagent 槽位分波,每波连续 spawn 满后才调用 `wait_agent`;严禁 spawn 一个就等待一个(R1 实测行级串行 54min/页)。唯一互斥资源是设备 I/O(9-11 的安装/启动/截图),由 `device_lock.py` 串行化(支持 `--pool` 多 emulator;构建与 repair 修改一律锁外)。**
   - **3a. board-worker + contract-worker 全并行**(同一条消息发起:board 每板一个 `--mode board`,contract 每 feature 一个 `--mode contract`):board = compliance → digest → 本板 canvas/expected/slots + canvas 专属 colors(6.7,无 token 时可不存在)→ 本板 implementation_map 片段,只写本板专属文件,不生成依赖上线 page/fixture 的 trace 测试、不跑 flutter test;contract = 步骤 6 系列(交互契约+完整性门+状态机+锚定+api_contract+test plan,含模型填边/锚定确认),只写 feature 级 spec_dir 契约文件,不跑任何 flutter 命令。**contract-worker 返回后 main 必须立即运行 `check_contract_artifacts.py --spec-dir <feature_spec_dir> --index .iff/board_index.json`;只有 exit 0 才把该 worker 记为成功并进入 3b。非零时即使 worker 进程/agent 状态为成功也必须按 contract 失败处理,禁止 spawn assembly。**
	   - **3b. assembly-worker 每 feature 一个**(该 feature 的板 worker 与 contract worker 全部返回后,`--mode assembly`):selector/fixture/slot 绑定 → 消费步骤 6 产物(验 --check 通过,不重算)→ `assembly_plan_batch.py prepare` 批量 prefill,模型只编辑小型 `assembly_decisions.json`,再 `apply` 批量回填/校验 → 默认 TDD RED 一次(缺功能/行为失败);仅当用户明确授权接管已存在且当前测试全绿的实现时,生成 prompt 必须显式带 `--recovery-mode preexisting-green`,由 guard 运行范围测试并哈希锁定 source/test/contract,禁止伪造 RED → `prepare_assembly_packaging.py prepare` 原子登记全部画板资产目录/必需字体并写 `assembly_packaging.json` → runtime page + trace 测试 → GREEN 一次 → 数据接入(8.x)→ 截图+diff+进展约束 repair(9-11,每个 source-bound fingerprint 最多 3 次、总 claim 最多 32 次,每次要求新截图/diff,短窗口持锁,构建/修改锁外;若当前 claim 因 planner 通用修正变为 ineligible,只能用预算脚本 `replan` 在同一 diff 上替换并留存 invalidation,禁止手改状态)→ 审计(12,trace,feature 级一次)→ `assembly_completion.py issue`。`make_worker_prompt.py` 的 assembly stdout 是 `{prompt, invocationContract}` JSON;main 在 spawn 前执行 contract 的 `prepareCommand`,wait 返回后无条件执行 `verifyCommand`;若用 `codex exec` 等本地进程则只允许在 contract 的 `runCommandPrefix` 后追加 argv,让 supervisor 包住进程。**只有 supervisor verify 对本次启动后新签发 evidence 返回 0 才是成功;worker 进程/agent exit 0 或自然结束都不是成功证据**。多 feature 的 assembly 可并行,但 `pubspec.yaml` 只允许该 packaging 脚本用工程级锁更新;其余工程级共享改动仍留扇入。
   - 模型负责业务逻辑与工程接入,视觉实现必须由机器产物和 diff 驱动。
4. **扇入(串行集成)**:先用 completion/done gate 复验每个 feature 当前 `assembly_packaging.json`(缺失、资产/字体文件或 pubspec 登记漂移即拒绝)→ 去重汇总 → `pub add` 依赖 → 注册路由/DI → **flow 图合并与轻验**(assembly 返回的跨页边 → `update_flow_graph.py --graph .iff/flow_graph.json add --edges <edges.json>`;路由注册完后导出路由清单跑 `update_flow_graph.py check --routes <routes.txt>`——新边的目标路由必须已注册,pending_route 只报告不阻断)→ `build_runner` → `flutter analyze` → `retire_stale_flutter_template_tests.py --project-root . --out .iff/stale_template_tests.json`(只归档仍保持 Flutter Counter 模板全部特征、但真实 `home:` 已不再指向 `MyHomePage` 的单个 starter test;自定义测试或仍在用 Counter 首页一律保留)→ **`flutter test`(全仓回归,本批唯一一次全量调用;红了先归因到肇事 feature——文件隔离下通常是扇入集成或跨 feature 共享改动引入——修复或把该行改 `error`;全绿是步骤 5 写 `done` 的前置)** → 启动 emulator/simulator → `flutter run` → `adb screencap` 或 `xcrun simctl io booted screenshot` 获取最终 `actual.png` → crop 到 app viewport → 与 `reference.png` 尺寸对齐 → `run_visual_diff` 输出 `diff_report.json` → `make_repair_plan` 输出 `repair_plan.json` → 按 `repair_plan.json` 修改一次 → 重新截图/重新 diff → 最终运行截图验收。每行最多一次 repair,不得循环打磨;单次 repair 后仍不达标则该行 `status=error`,继续下一需求。feature 画板资产/字体/pubspec 登记不得在本步骤补做。扇出中被 defer 的**公共组件区域缺陷**在此串行处理:修组件本体一次并复验所有受影响页(组件改一处、各页共享);本批登记过新公共组件时,`.iff/shared_components.json` 属工程资产随工程提交;设计节点缺失 paint/export 时优先使用已校验的局部 reference-region fallback,只有节点非叶、bbox 无效/完全越界或等于整张 reference 等无法安全局部适配时才写 `error` 并附确定性原因。
5. **回写(完成)**:main 收到 assembly 结果后,**无论 worker/agent 是否 exit 0**,都必须执行生成的 `invocationContract.verifyCommand`;它要求本轮 `prepareCommand` 状态、拒绝旧 evidence,并内部运行 `assembly_completion.py verify` 重跑 `check_done_gate`。缺状态、缺/旧文件、hash 漂移或 verify 非零一律把该 worker 当失败,不得进入成功扇入/回写。写 `done` 另有前置:**扇入的全仓 `flutter test` 回归已全绿(步骤 4)**。完成证据聚合校验每板 fidelity ok+assetShape 通道已跑、digest/prefill 已执行、公共组件无 missing、red/green 证据、wiring ok、api 全接、最终像素诊断存在且平坦区无 asset/text 真缺陷、manifest 真机来源、compliance;任一失败不得写 `done`。全绿后逐行把 status `doing`→`done`(成功)或 `error`(失败,详情写 `error` 列),并写 `spec_dir`;若表中已有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,写入最终视觉证据路径。
5.5. **自我进化(每张设计完即触发,异步,不阻塞当前批)**:对刚跑完的每张设计,收集该 worker 的失败记录(`{blockers[], manual_judgements[], 命中的 CASE-id, gate 结果}`)→ `make_evolution_prompt.py --skill-dir ~/.agents/skills/iff --design-name <名> --failure-record <记录>` 生成 prompt → 用 `spawn_agent` 创建一个 **evolution 子 agent**(在 **skill 仓的 git worktree** 里干活,**不碰当前任务/被测工程/`main`**)。它按 `SELF_IMPROVE.md` 路由 A/B/C,产出**一个 PR**(A 改脚本+红前绿后 fixture / B 写案例记忆+毕业 / C 升级人),host 自适应提交(`open_pr.py`),人审合入才生效。详见 `iff/SELF_IMPROVE.md`。
6. **验收**:对照 goal 的验收标准核对(`analyze` 无 error、各行达标、最终视觉验收无 P0/P1 问题)。**全部行 done 后**:`make_journey_map.py --graph .iff/flow_graph.json --out .iff/journey_map.md` 生成用户故事地图(mermaid)+ E2E 回放清单,按清单在真机逐条走通 journey(跨页交互的统一终验;`pending_route` 是后续行的工作清单,不算失败)。
</instructions>

<pipeline>
## 固定流水线(P0)
iFF 是设计稿编译器 + 模型补全业务逻辑 + 真机截图 diff + 单次 repair 复验。模型不直接“看图写 UI”。**阅读纪律(P0,token 预算属于正确性)**:模型先读 `artifact_digest.json`(`summarize_spec_artifacts.py` 产出,含所有产物的 schema key/计数/case id/端点/公共组件);**大 JSON(`scene.json`/`render_plan.json`/`layout_contract.json`/`repair_plan.json`/`diff_report.json`/`oas.json`/`oas_ref_resources.json`/`raw.json`)禁止整读**——它们由脚本消费(可见层由 `generate_canvas.py` 生成,模型不需要逐节点数据),需要单个节点数据时按 node id 窗口查;小文件(`tokens.json`/`groups.json`/`design_classification.json`/`api_contract.json`/`component_manifest.json`/`data_slot_bindings.json`/`interaction_test_plan.json`)可整读。**接口返回的方案/文案/金额不是设计真值**:有完整 API 来源证据的动态字段允许与设计展示值不同,设计稿只约束其容器、排版、样式和状态结构。
当前 `raw.json` 的主数据是 `figma_json.artboard`;一律走 Figma JSON 专用编译器 `export_figma_scene.py` / `group_figma_layout.py` / `make_figma_layout_contract.py`,不得用 generic JSON walk + bbox/name 启发式。
	所有确定性环节必须由本 skill 目录脚本保证,脚本唯一合法目录是 `~/.agents/skills/iff/scripts/`;禁止引用 `fd/scripts`、项目本地 `scripts/` 或临时脚本。确定性环节包括:worker prompt 生成/assembly supervisor 新鲜证据交接/合规校验、设计获取/cover 下载、分类、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、设计产物总审计、Apifox OAS 引用解析/契约归一化、fixture 生成、interaction contract/test plan、交互覆盖审计、资产复制/pubspec 注册、真机截图/manifest、视觉 diff、repair plan、manifest/fixture/render plan 审计、公共组件检测/注册表登记。

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
# 仅经用户明确授权接管既有全绿实现时,在 assembly 命令追加: --recovery-mode preexisting-green
# shared stdout 返回 {"prompt":...,"invocationContract":...};只能把 worker argv 追加在 contract 的 runCommandPrefix 后:
python3 ~/.agents/skills/iff/scripts/shared_worker_supervisor.py run --contract <job>/worker_prompt.md.shared_invocation.json -- codex exec --json --model <model> -
# 多个 shared job 并行启动多个上述 supervisor;禁止直接 spawn_agent/裸跑 shared worker。默认 total=1200s、idle=300s;
# 可用 --total-timeout/--idle-timeout 配置(0 仅关闭单项,两项不得同时为 0)。stdout 最后一行是机器 JSON,
# worker 流输出在 stderr,完整捕获见 <job>/shared_worker.log,失败见 <job>/shared_failure.json。
# assembly stdout 返回 {"prompt":...,"invocationContract":...};先清旧证据并签发本轮状态:
python3 ~/.agents/skills/iff/scripts/assembly_worker_supervisor.py prepare --contract spec_dir/worker_prompt.md.assembly_invocation.json
# Codex 编排者再用 spawn_agent 发起 worker;连续建齐本批 worker 后再调用 wait_agent:
# spawn_agent(task_name="<unique>", fork_turns="none", message="<worker_prompt.md 全文>")
# wait_agent 返回后无条件验交接;只有本命令 exit 0 才接收 assembly:
python3 ~/.agents/skills/iff/scripts/assembly_worker_supervisor.py verify --contract spec_dir/worker_prompt.md.assembly_invocation.json
# 若 worker 由本地进程启动,禁止直接看子进程 exit 0;用 run 包裹并把 prompt 经 stdin 传给命令:
python3 ~/.agents/skills/iff/scripts/assembly_worker_supervisor.py run --contract spec_dir/worker_prompt.md.assembly_invocation.json -- codex exec --json --model <model> -
# assembly invocation contract is fresh-only; `codex exec ... resume ...` is forbidden because stale session context can override the current hash-locked contract.
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.agents/skills/iff
```
输出: `worker_prompt.md`、shared 专属 `worker_prompt.md.shared_invocation.json`/`shared_supervisor_state.json`/`shared_worker.log`(失败另有 `shared_failure.json`)、assembly 专属 `worker_prompt.md.assembly_invocation.json`/`assembly_supervisor_state.json`、`worker_compliance.json`。
硬门: main 不得手写短 prompt 直接启动 worker;fetch/board/contract/shared worker 未证明读取当前 `iff/SKILL.md`、`iff/test_rules.md` 时结果作废;shared worker 只认 supervisor 对当前 invocation 的 exit 0,旧 result/compliance、worker exit 0、自然结束均无效;assembly 必须证明执行生成 prompt 内的有界 contract,**不得为合规再整读全文**。assembly 未先 prepare、evidence 非本轮新签发、或 supervisor verify 非零时,即使 worker exit 0 也必须失败。任一 worker 未通过 pipeline scripts 预检、或 hash 与当前 skill 不一致时结果作废并重跑;不得进入扇入。

### 批内公共组件解析(main 侧,扇出前;实现并行、收口串行;行 worker 不执行本节)
命令:
```bash
# 各选中行先按步骤 1→3 产出 scene/groups(spec_dir 缓存,worker 后续命中即跳过),然后:
python3 ~/.agents/skills/iff/scripts/detect_shared_components.py --spec-dirs <row1_spec_dir> <row2_spec_dir> --registry .iff/shared_components.json --out .iff/batch_shared_components.json
python3 ~/.agents/skills/iff/scripts/make_shared_component_jobs.py --batch .iff/batch_shared_components.json --project-root . --out-dir .iff/shared_jobs
# 对 jobs.json 中每个 job 生成完整 prompt + shared invocation contract:
python3 ~/.agents/skills/iff/scripts/make_worker_prompt.py --mode shared --component-json <job>/component.json --spec-dir <job> --project-root . --out <job>/worker_prompt.md
# 按各 stdout 的 invocationContract 并行启动 supervisor;只接收 supervisor exit 0:
python3 ~/.agents/skills/iff/scripts/shared_worker_supervisor.py run --contract <job>/worker_prompt.md.shared_invocation.json -- codex exec --json --model <model> -
# 对 status=missing 的组件:并行实现(best_asset_source 行产物 + pooled_assets;各 worker 只写自家文件,
# 禁碰 pubspec/注册表、禁跑 analyze/test)→ 全部返回后串行收口:pubspec 资产注册 + 一次 analyze +
# 一次 flutter test(全部组件 widget 测试)在一致的树上通过后,逐个登记:
python3 ~/.agents/skills/iff/scripts/register_shared_component.py --registry .iff/shared_components.json --signature <sig> --name <WidgetClass> --widget-path lib/<共享widget目录>/<file>.dart --asset <已注册资产路径> --source-spec-dir <best_asset_source> --from-batch .iff/batch_shared_components.json --component-expected lib/<共享widget目录>/<canvas>.dart.expected.json
# 登记后重跑 detect 刷新各行 spec_dir/shared_components.local.json(候选全部 reuse)再生成 worker prompt
```
输出: `.iff/shared_components.json`(工程级注册表:signature → widget/资产,随工程提交)、`.iff/batch_shared_components.json`(本批解析:reuse/missing、`best_asset_source`、`pooled_assets`、`assets_incomplete`)、`.iff/shared_jobs/jobs.json`(`jobs`=全部 missing 组件,`blockers` 保留给未来不可生成 job 的结构错误;paint 缺口不进入 blockers)、各 job 的 `*.shared_invocation.json`/`shared_worker.log`/`shared_result.json`/`worker_compliance.json`、各行 `spec_dir/shared_components.local.json`(步骤 4 `--shared` 的输入)。
硬门: 公共组件的创建/修改只允许发生在本步骤或串行扇入,扇出中的行 worker 对公共组件只读;**并行实现阶段的组件 worker 禁碰 pubspec/注册表、禁跑 analyze/test——这些全部属串行收口**(在一致的树上验门,避免半成品互踩假红);`jobs.json.blockers` 非空时不得为其中 signature 生成 prompt/启动 worker,受影响行不得进入 board/contract/assembly,但禁止连带中止无关行;paint 缺口本身不得写 blocker。shared worker 只能由 `shared_worker_supervisor.py run` 启动,任一 timeout/非零/failure JSON/旧或缺 result/compliance 都按该组件失败,不得无限等待或进入登记;同一 signature 不得对应两个不同 widget(`register_shared_component.py` 冲突即报错);`assets_incomplete` 包括任何行都无切图的 icon 位置和未被祖先原子 asset 覆盖的 visible paintless leaf;后者必须使旧 registry 条目失效并回到 `missing`,再由局部 reference-region fallback 消解,禁止复用透明旧 widget、Material 默认图标或近似图形静默顶替;`make_worker_prompt.py` 必须在本步骤之后运行(否则 local 文件不会注入 worker prompt);组件 signature 匹配只认 `detect_shared_components.py`(componentId 优先,结构哈希兜底),禁止模型凭名字/截图判断"是同一个组件"。

### 0a. 归属判定(Track B 入口,新页面 / 状态变体 / 复用)
命令:
```bash
python3 ~/.agents/skills/iff/scripts/reconcile_feature.py --lib-root lib --title "$ROW_TITLE" --out spec_dir/reconcile_decision.json
```
输出: `reconcile_decision.json`(现有 feature 清单 + 候选匹配 + 待模型填的 `decision`)。
硬门: 写任何组件前必须先定归属。脚本只做确定性清单;**模型必须读懂业务是否相同**再设 `decision` 为 `new` / `extend:<feature>` / `variant:<feature>`。同一屏不同状态的多张设计稿应作为既有 feature 的**变体**(加一态 + 一张 golden),不得复制成新页面。

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
# exporter 内部强制执行 system_ui_filter；缓存 scene 需要从错误点重跑时可原地刷新：
python3 ~/.agents/skills/iff/scripts/system_ui_filter.py --scene spec_dir/scene.json --out spec_dir/scene.json --asset-base spec_dir [--exclude-node <用户/模型依据节点证据确认的设备伪影id>]
python3 ~/.agents/skills/iff/scripts/check_figma_scene.py --scene spec_dir/scene.json
python3 ~/.agents/skills/iff/scripts/export_tokens.py --scene spec_dir/scene.json --out spec_dir/tokens.json
python3 ~/.agents/skills/iff/scripts/export_assets_manifest.py --scene spec_dir/scene.json --out spec_dir/assets_manifest.json
```
输出: `scene.json`、`tokens.json`、`assets_manifest.json`;每个节点必须从 `figma_json.artboard.layers` 编译,保留真实 `id/path/parent/children/type/figmaType/bbox/z/depth/visible/effectiveVisible/opacity/blendMode/fills/rawFills/solidFills/gradientFills/imageFills/border/radius/shadow/effects/blur/mask/maskType/clipsContent/constraints/layout/exportSettings/componentId/componentProperties/variantProperties/isInstance/absoluteTransform/relativeTransform/exportable/asset`;文字节点还必须含 `text/fontSize/weight/lineHeight/paragraphSpacing/textStyle/textRuns`;图片/图标节点必须有 asset 映射。`systemUiExclusions` 记录被剔除的状态栏、摄像头挖孔/刘海/灵动岛等设备系统 UI 及确定性原因。
硬门: `scene.sourceSchema` 必须是 `lanhu_figma_json`;主视觉节点没有 bbox、颜色、文字或 asset 映射时不能实现;worker 不能只读 `spec.md`;颜色、字号、圆角、阴影、资产清单必须来自机器产物,不得凭感觉补。系统 UI 判定不得只依赖设计节点命名：必须组合顶部窄带几何、时间/信号/Wi-Fi/电量内容指纹、摄像头深色居中几何等证据；被判定节点及子树必须 `visible=false/effectiveVisible=false`，render plan 必须 `implementation=hidden,required=false`，不得进入 Flutter 资产引用。若设计导出异常让设备/截图伪影脱离顶部几何区，只能在用户确认且模型以 scene 节点证据定位后用 `--exclude-node` 显式排除；禁止扩大全局启发式误删普通黑色 Logo、星形或业务装饰，未知节点必须失败。

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
**执行者:contract-worker(与 board-worker 同批并行;输入只依赖 2.5 产物,与画板产物零依赖)。assembly 只消费本节产物并验 `--check` 通过,不重算。**
命令:
```bash
# interaction.txt 已由步骤 2 的 csv_row_status.py export 从规范行逐字生成；禁止在此覆盖或重建。
python3 ~/.agents/skills/iff/scripts/parse_interactions.py --input spec_dir/interaction.txt --out spec_dir/interaction_contract.json
# 契约完整性门(不变量④:每条交互规则都要覆盖):被丢进 ignoredItems 里、却带"触发+效果"信号的句子
# 必须被提取成规则,或显式登记到契约的 acknowledgedNonRules——否则 100% 覆盖只是"残缺清单的 100%"。
# 可执行的有界提升器内部先跑一次完整性检查:按报告顺序处理每个 occurrence,重叠/重复显式去重,
# 其余行为项追加连续 INT-xxx;只接受与 occurrence 精确空白归一化匹配的真实非规则 acknowledgement。
# 本命令不做最终复查,避免 worker 在预期的首次非零检查上提前停止。
python3 ~/.agents/skills/iff/scripts/promote_interaction_rules.py --contract spec_dir/interaction_contract.json --completeness-report spec_dir/interaction_completeness_report.json --out spec_dir/interaction_promotion_report.json
# 状态机(P0,多状态 feature):板=节点,迁移=交互。骨架确定性生成,模型只填每条边的 trigger/condition
# (依据 交互描述+板语义+案例记忆);每条边追加为 contract 的 INT-SM-xxx 规则(享受 HAPPY/BOUNDARY/FAILURE
# 全覆盖);占位残留或零迁移无理由则 --check 失败,不得进入测试计划。
python3 ~/.agents/skills/iff/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json
# (模型填 nodes[*].meaning 与 edges,把边写进 interaction_contract.json 的 rules)
python3 ~/.agents/skills/iff/scripts/make_state_machine.py --spec-root lanhu/specs/<feature> --out spec_dir/state_machine.json --check
python3 ~/.agents/skills/iff/scripts/make_interaction_tests_plan.py --contract spec_dir/interaction_contract.json --api-contract apifox_contract.json --out spec_dir/interaction_test_plan.json
# test plan 重生成后只复查一次;仍失败立即显式停止,禁止再次提升/ack/循环。
python3 ~/.agents/skills/iff/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --row spec_dir/row.json --out spec_dir/interaction_completeness_report.json
# 交互视觉锚定(P0):交互文字里的视觉引用(带引号的 UI 文案 / 无引号的页面·画板提及)先做确定性检索,
# 唯一命中自动绑定;多候选由模型在候选内确认(judgment,不是搜索);零命中必须标 pending_route(跨行目标,
# 测试断言导航 intent 对 mock)。--check 不过不得进入测试设计。索引由 main 在 2.5 末尾产出(.iff/board_index.json)。
python3 ~/.agents/skills/iff/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json
# (模型编辑 anchors:ambiguous 填 confirmed,unresolved 填 pending_route)
python3 ~/.agents/skills/iff/scripts/resolve_interaction_anchors.py --contract spec_dir/interaction_contract.json --index .iff/board_index.json --out spec_dir/interaction_anchors.json --check
python3 ~/.agents/skills/iff/scripts/check_contract_artifacts.py --spec-dir spec_dir --index .iff/board_index.json
```
输出: `interaction_contract.json`、`interaction_test_plan.json`、`interaction_completeness_report.json`、`interaction_promotion_report.json`、`state_machine.json`、`interaction_anchors.json`、`oas_missing_ref_paths.json`、`api_contract.json`;每条交互规则都有稳定 `INT-xxx` id,每条规则生成 `HAPPY`/`BOUNDARY`/`FAILURE` 三类测试 case id。
硬门: `interaction` 非空但无法解析触发动作或期望结果时,该行 `status=error`;不得让 worker 自由解释。提升器必须消费首次报告的每个 occurrence,保持既有规则顺序并只追加连续 `INT-xxx`;重复/重叠 occurrence 必须在 promotion report 中显式去重,不得自动 acknowledgement。test plan 重生成后 **`check_interaction_completeness` 必须且只再跑一次并通过**;仍有未提取规则立即显式停止,不得迭代。生成的 case id 必须进入测试名或测试注释,否则 done 前覆盖审计失败。contract-worker 返回成功前和 assembly-worker 写任何文件前都必须运行同一 `check_contract_artifacts.py`;缺少/损坏任一契约 JSON、缺少 board index、或 anchors `--check` 失败时命令必须非零退出。

### 6.5 计划阶段:对齐设计稿与当前工程
命令(board/单板固定顺序:digest → 机器预填 → 模型只填判断字段 → 校验;**assembly 必须改走后面的批量命令**):
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
- `projectAlignment`: 当前工程入口、App shell、已存在/缺失的 feature 目录、worker 扇出允许写的文件、assembly 在有效 RED 后通过 `prepare_assembly_packaging.py` 持锁写入的 feature 资产/字体 pubspec 范围,以及必须留给串行扇入的其余共享文件(依赖/路由/DI/codegen)。
- `fixtureAlignment`: runtime、widget test、preview/mock repository 共同使用的 fixture 来源;`variant_board` 必须列出所有状态及卡片数量,少状态计划无效。
- `traceAndRepair`: `implementation_map.json` 与 `actual_layout_trace.json` 的生成策略,截图/diff/repair plan 命令,`singleRepairBudget=1`,以及单次 repair 后的 `post_repair_diff_report.json` 记录策略。
- `forbiddenShortcuts`: 禁止整图铺底、reference 派生 actual、Material 默认图标/占位图替代、测试自造数据、并行改共享文件。
若表格指定的路径在当前工程不存在,计划必须明确缺口并给出最小随项目脚手架;不得假装已有结构存在。若机器产物实际 schema 与本说明文字不一致,以实际 schema 为准并在计划中记录差异。

assembly 批量命令(生成 prompt 已填入绝对路径):
```bash
python3 ~/.agents/skills/iff/scripts/assembly_plan_batch.py prepare --spec-root lanhu/specs/<feature> --project-root . --context lanhu/specs/<feature>/assembly_context.json --decisions lanhu/specs/<feature>/assembly_decisions.json
# 模型只编辑小型 assembly_decisions.json:feature 级 projectAlignment/fixtureSource + 每板 stateData;禁止打开或 patch implementation_plan.json
python3 ~/.agents/skills/iff/scripts/assembly_plan_batch.py apply --context lanhu/specs/<feature>/assembly_context.json --decisions lanhu/specs/<feature>/assembly_decisions.json
```
硬门:`prepare` 内部按稳定板序运行 design audit/digest/prefill/implementation-map 门;`apply` 由脚本把共享判断批量写回所有大 plan,并为每板运行 `check_implementation_plan.py`。region merge/skip rationale 等可确定字段由脚本填充;模型只保留项目归属、fixture 与状态数据判断。assembly prompt 不得列出逐板 plan 命令或要求逐板大 JSON patch。

### 6.6 注入项目实现规范到 AGENTS.md(确定性,P0)
落地工程前必须把实现规范注入目标工程 `AGENTS.md`,让所有 agent(含本 worker)统一遵守:
```bash
python3 ~/.agents/skills/iff/scripts/sync_project_rules.py --rules ~/.agents/skills/iff/implementation_rules.md --memory ~/.agents/skills/iff/evolution/case_memory.md --project-root .
```
worker 必须**先加载 `iff/implementation_rules.md`(权威源)**并在 `worker_compliance.json` 记录,所有可见层实现按 `IMPL-*` 规则执行。
注入会把 `evolution/case_memory.md`(B 类判断先例)一并写进 AGENTS.md;worker 在 归属/⑥交互绑定/⑦数据绑定 前**必须先读案例记忆**,命中 signature 就按其 decision 做(看 why 判适用性),并在产物里记录命中的 CASE-id(供 evolution 子 agent 累计 `seen`)。

### 6.7 脚本生成响应式画布 + 颜色 token + 字体(确定性,P0)
可见层生成是**确定性的,必须脚本化**——禁止模型手写。`generate_canvas.py` 走**关系换算**:每个尺寸/位置都是「设计像素 × u」,`u = LayoutBuilder.maxWidth / 设计宽度`(`IMPL-LAYOUT-1`),设计宽度下 1:1 还原(供视觉 QA),真机按比例自适应;颜色全抽到调用者用 `--colors-out/--colors-import` 声明的 Dart 文件(`IMPL-TOKEN`;board-worker 必须每 canvas 独占,禁止并行共享),不写死宽高/`scale`(`IMPL-LAYOUT-2`),不加 `TextStyle.height`(`IMPL-LAYOUT-4`),按区域拆 widget(`IMPL-COMP-1`),中文注释(`IMPL-DOC`)。
命令:
```bash
# 1) 编译可见层 + 颜色 token(响应式;资产前缀走 assets/images/,IMPL-ASSET-2)
# 先产组件清单(只需 render_plan + classification),供 generate_canvas 标记动态文本槽:
python3 ~/.agents/skills/iff/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.agents/skills/iff/scripts/generate_canvas.py --render-plan spec_dir/render_plan.json \
  --classification spec_dir/design_classification.json --component-manifest spec_dir/component_manifest.json \
  --class-name <StateCanvas> --out lib/<feature>/presentation/home_artboard_canvas.dart \
  --colors-out lib/<feature>/presentation/home_artboard_canvas_colors.dart \
  --colors-import home_artboard_canvas_colors.dart --asset-prefix assets/images/
python3 ~/.agents/skills/iff/scripts/make_status_bar_policy.py --scene spec_dir/scene.json --class-name <State>StatusBarPolicy --out lib/<feature>/presentation/<state>_status_bar_policy.dart
# 产物含:可见层 dart(动态槽 = Text(slotText['<id>'] ?? '设计值'))、<out>.expected.json(保真基准)、
# <out>.slots.json(设计种子 fixture:槽节点id->设计展示值,不变量⑦)。上层页面/同源 fixture 用 slots.json 初始化。
# 2) board-worker 只复制资产到 assets/images/(IMPL-ASSET-2);禁止写 pubspec
python3 ~/.agents/skills/iff/scripts/copy_assets.py --manifest spec_dir/assets_manifest.json --target assets/images/
# 3) 字体文件复制 + 字体/全部画板资产目录 pubspec 登记由 assembly 在有效 RED 后统一执行
#    `prepare_assembly_packaging.py prepare`;board-worker 禁止手工复制字体或改 pubspec。
```
`generate_canvas.py` 已内建:文字 `fontFamily`/`align`/`verticalAlignment`/多色 `textRuns`(RichText);list 形 `border`(描边)、operand 继承圆角、渐变、椭圆;`absoluteTransform` 翻转节点重算真实位置(切图不二次旋转);boolean `Subtract` 用 `PunchedRect`(圆角矩形挖椭圆洞露出底层 leaf);跳过 boolean operand 与 covered/hidden;无 asset 的 `Star*` 画真星形。要新增渲染语义就改这个脚本,不在 dart 里手补。
硬门: 画布 dart 顶部必须是 `// GENERATED by iFF generate_canvas.py`;状态栏策略 dart 顶部必须是 `// GENERATED by iFF make_status_bar_policy.py`,其 `mode/designStatusBarDetected/reserveTopInset` 必须与当前 scene 一致并由上线页引用;无内联 `Color(0x..)`、无 `TextStyle.height`、无写死设计稿宽高;字体未打包不得进入截图。

### 7. 坐标编译产出**上线页可见层本体**(数据驱动 + 可 trace)
**定位(不变量①③⑥)**:`6.7` 的 `generate_canvas.py` 产出的、每个可见节点挂 `ValueKey('iff:<节点id>')` 的坐标画布**就是上线页的可见层本体**——几何/颜色/圆角/字号/间距全部由脚本从 `render_plan.json`/`tokens.json` 喂入,**模型禁止手写 `Positioned` 或靠眼睛调样式;调不对=脚本没把该确定性值喂进去,改 `generate_canvas.py` 不改 app**。它同时产出 `<out>.dart.expected.json`(每节点归一化几何 + 设计样式),作为 `check_render_fidelity.py` 的**设计期望基准**(源自 render_plan = 设计真值,不是 golden 图)。**不再产出独立"golden"静态画布、不再做 golden-vs-golden 像素比对**。上线页 = 这层可见画布 + 动态文本/金额槽(槽位来自 `data_slot_bindings.json`)+ 透明交互热区(事件由页面层编排)。设计 fixture 只作无接口时的默认展示值;若槽位 `confirmedByModel=true`、`contentSource.kind="api"`、`binding.field` 非空且 `contentSource.evidence` 给出端点/响应字段或 repository 字段证据,运行时值**允许与设计展示值不同**。**严禁把可见层做成与数据无关的静态展示、严禁用 `Offstage` 把数据驱动组件藏起来充数**;可见层必须真实挂在 app 对应路由/首屏并随数据变化。保真由 `check_render_fidelity.py` 对**真实渲染 trace** 逐组件保证(步骤 12 PASS 门)。
TDD 固定输入:先按 `interaction_test_plan.json` 写 widget/integration 测试,每个 case id 必须字面出现在测试名或注释里;RED/GREEN 均必须通过 `assembly_tdd_guard.py red|green` 执行,禁止直接调用对应的 `flutter test` 或手写证据。guard 保存 `spec_dir/interaction_test_evidence.json`,且 red 必须是缺功能/行为失败并记录 `red.failure_kind="missing_feature_behavior"`,不得是 asset/font/pubspec/编译/环境错误。**RED 之后、GREEN 之前**必须运行步骤 8 的 `prepare_assembly_packaging.py prepare`,脚本要求 green evidence 尚不存在、绑定 guarded RED 的 run/hash/timestamp 且自身时间更新,其本身不得调用 `flutter test`;再实现上线 page/同源 fixture并用 `gen_layout_trace_test.py` 为每板生成上线 page trace 测试,由 GREEN guard 先复验 packaging 再执行唯一 green `flutter test test/<feature>` 并写出每板 canonical `actual_layout_trace.json`(`pageType` 非空且 `nodes` 是非空对象)。缺/空/旧 packaging evidence 或缺/空/旧/legacy-shaped trace 必须在 GREEN/截图/repair 前停止,不得消耗单次 repair 预算。
固定实现方式:可见层由 `6.7` 的 `generate_canvas.py` 产出,**不得手写**;外层用 `FittedBox` 或固定 artboard canvas 做响应式适配,避免 `Transform.scale` 造成 widget test 命中异常;每个 visible render node 按 `render_plan` bbox 生成 `Positioned` + 固定 `SizedBox`;背景、输入框、按钮等节点必须按 bbox 填满,不得依赖子组件 intrinsic size;文字使用 `fontSize/weight/lineHeight/color` + 打包的设计字体;shape 使用 tokens 中的颜色、圆角、边框、阴影;装饰、图标、图片使用真实独立 asset;语义组件、业务按钮和命中区域只能透明覆盖在坐标画布上,不得参与可见像素布局。**唯一例外**:`render_plan.sharedComponents` 列出的已登记公共组件,按 group bbox 以 `Positioned` 挂载为该区域的可见层(组件本体在串行阶段已验证;不算"语义模板替代")。
硬门: 交互测试不得 skip/弱断言/只测存在;red evidence 必须 exit_code 非 0,green evidence 必须 exit_code = 0;不能用 Material 默认 icon 替代设计 asset;不能用“差不多”的间距;不能凭感觉写颜色、圆角、阴影;禁止把完整设计稿或 reference 派生图当可见层,但允许使用设计稿导出的独立背景、卡片、图标等真实资产。禁止用 Row/Column/Flex、region/card shell 或业务语义模板生成可见像素来替代 render_plan 中的 visible nodes;禁止把 textlayer wrapper 或文字节点画成黑色矩形;禁止在已渲染原子资产后重复渲染其子节点;`implementation_map.json` 必须覆盖 `render_plan.json` 中至少 98% 的 required visible node,且全部 image/text node 必须映射;每个 visible node mapping 必须包含 `bbox`、`implementation`、`widget` 和 `renderMode:"absolute_positioned"` 或等价坐标模式。

### 8. Assembly pre-GREEN 资产/字体/pubspec 打包
命令:
```bash
python3 ~/.agents/skills/iff/scripts/prepare_assembly_packaging.py prepare \
  --spec-root lanhu/specs/<feature> --project-root . --pubspec pubspec.yaml \
  --out lanhu/specs/<feature>/assembly_packaging.json
```
前后测试命令(唯一规定入口):`python3 ~/.agents/skills/iff/scripts/assembly_tdd_guard.py red --spec-root lanhu/specs/<feature> --project-root . --test-target test/<feature> --failure-kind missing_feature_behavior` → 上述 packaging → `python3 ~/.agents/skills/iff/scripts/assembly_tdd_guard.py green --spec-root lanhu/specs/<feature> --project-root . --test-target test/<feature>`。RED/GREEN 禁止直接运行 `flutter test`。
执行者/时序:只允许 assembly-worker 在唯一 RED 已记录后、runtime page/trace 和唯一 GREEN 前执行。脚本扫描 `lib/<feature>/presentation/*_canvas.dart` 的真实 asset/font 引用,要求 board-worker 已复制每个引用文件,按稳定排序收集**全部**资产父目录,用工程级 `.iff/assembly_packaging.lock` 原子更新 `pubspec.yaml`,并为已知必需字体复制/登记真实字体文件(SF Pro Text → `fonts/SFProText.ttf`,默认来源 `/System/Library/Fonts/SFNS.ttf`)。多 feature assembly 可并行,但禁止绕过该锁手改 pubspec。
输出:`assembly_packaging.json`(`phase=post_red_pre_green`,画板、资产文件/目录、字体、文件 hash、prepare 时 pubspec hash)和已原子更新的 `pubspec.yaml`。
硬门:命令非零、证据缺失、任一画板引用资产缺失、未知字体无确定性映射、字体文件缺失、资产目录或字体未登记时,**禁止 GREEN**;脚本不得运行 `flutter test`,不得消耗调用预算。GREEN guard 必须在测试启动前重验 packaging 当前有效且 `preparedAtNs > red.completedAtNs`;`check_done_gate.py` 必须重验 RED→packaging→GREEN 的 run id、record hash、packaging hash 和纳秒时序,缺失、direct evidence、乱序或漂移不得签发 completion。资产优先级 `webP > png`;简单矢量使用 svg;复杂渐变、遮罩、复杂阴影、多层组合使用 webP;不能画近似图标/占位色块;所有 exportable asset 必须注册并使用;禁止整张设计稿作为背景资产。公共组件资产仍只归 2.5 shared-worker 串行收口,本步骤不改变其所有权。

### 8.1 真接口契约 + DTO codegen(Track B)
命令:
```bash
# main 在 2.5 预拉 root 与首批 ref-resources 响应并原样保存(缓存命中直接用);任一缺失时 worker 调对应 Apifox MCP:
# read_project_oas -> spec_dir/oas.json
# read_project_oas_ref_resources -> spec_dir/oas_ref_resources.json
# 首批响应不是完整闭包。列出当前未缓存的外部文档 URI(fragment-only 自动忽略,输出去重稳定排序):
python3 ~/.agents/skills/iff/scripts/oas_ref_resource_cache.py missing --oas spec_dir/oas.json --ref-resources spec_dir/oas_ref_resources.json --out spec_dir/oas_missing_ref_paths.json
# 若 missing != []:main 把该数组中的路径原样交给 read_project_oas_ref_resources,响应保存为
# spec_dir/oas_ref_resources.next.json;禁止 main 手搓/补写 JSON。随后确定性原子合并:
python3 ~/.agents/skills/iff/scripts/oas_ref_resource_cache.py merge --base spec_dir/oas_ref_resources.json --incoming spec_dir/oas_ref_resources.next.json --required spec_dir/oas_missing_ref_paths.json --out spec_dir/oas_ref_resources.json
# 重跑 missing → MCP → merge,直到 missing=[]。merge 对零新增、重复 missing、漏返回 required、冲突资源均明确失败;
# 任一 exit 非 0 立即 error,禁止伪造资源、跳过缺失或继续 normalize。
python3 ~/.agents/skills/iff/scripts/normalize_api_contract.py --oas spec_dir/oas.json --ref-resources spec_dir/oas_ref_resources.json --out spec_dir/api_contract.json
# 再按 OAS codegen DTO(json_serializable / openapi 生成器),禁手搓与后端漂移;
# worker 内 build_runner 必须 --build-filter 限定本 feature(全量 codegen 1-3 分钟且撞共享产物):
# dart run build_runner build --build-filter="lib/<feature>/**" --delete-conflicting-outputs
```
输出: `api_contract.json`(真字段/类型/枚举)+ 生成的 DTO 模型。
硬门: 真实运行必须用 Apifox 真契约,不得用推导契约糊弄;DTO 字段以 OAS 为准;root 含外部 `$ref` 时必须提供完整 ref-resource 映射,缺 ref 或引用环由脚本明确失败,禁止模型手工追 ref/补端点;**模型只读 `api_contract.json`(~4KB),`oas.json`/`oas_ref_resources.json` 禁整读**;worker 内禁跑全量 `build_runner`(无 `--build-filter` 即违规,全量 codegen 留给串行扇入)。

### 8.2 组件清单 + 数据槽绑定(Track B)
命令:
```bash
python3 ~/.agents/skills/iff/scripts/make_component_manifest.py --render-plan spec_dir/render_plan.json --classification spec_dir/design_classification.json --out spec_dir/component_manifest.json
python3 ~/.agents/skills/iff/scripts/bind_data_slots.py --manifest spec_dir/component_manifest.json --api-contract spec_dir/api_contract.json --interaction-contract spec_dir/interaction_contract.json --out spec_dir/data_slot_bindings.json
```
输出: `component_manifest.json`(组件树:header / loan_card 变体 / bottom,静态/动态槽)+ `data_slot_bindings.json`(动态槽↔字段↔变换↔内容来源证据)。接口字段必须写 `contentSource.kind="api"` 与可核验的端点/响应字段或 repository 字段,否则不得豁免设计展示值。
硬门: 组件由清单驱动拆分;`bind_data_slots` 高置信绑定可直接用,`needsModelBinding` 每条**模型必须按交互规则确认**(如 INT-010 `level_money`→`max_money` 回退),`confirmedByModel=true` 才算定;动态槽**先钉死设计宽度**(IMPL-DATA)。

### 8.3 数据接入 + 交互接线 + 状态选择(Track B,上线页业务层)
固定方式(可见像素由脚本钉死,业务/数据/交互由模型写,门兜底):
- **可见层不由模型重建**:像素就是步骤 7 `generate_canvas.py` 产出的带 key 坐标画布(几何/样式脚本喂入)。模型只在其上做三件事:① 把动态文本/金额槽接到 fixture/DTO(槽位来自 `data_slot_bindings.json`,默认值=设计展示值;已确认的 API 字段可返回其它值);② 按 `apply_status` 等状态选择要渲染的态;③ 把 `interaction_contract` 的 intent 接到透明热区事件 + 页面编排 + 导航/风控链。API 动态内容只豁免值相等,不豁免 keyed 容器 bbox、约束、overflow/maxLines、样式、交互与数据绑定。**不用 Row/Column 重排可见像素,不手写 `Positioned`/颜色/圆角/字号**(要改像素就改 `generate_canvas.py`)。
- **领域逻辑必须被运行时调用,不能只被测试引用**。
- Repository 真 HTTP + mock **同接口同源**(同 DTO 形,可注入互换);loading/error/empty/轮询/禁截图按交互规则接;切 mock⇄API(同值)可见层零变化、切不同值可见文本必须变化(数据驱动证据)。
硬门: 上线页可见层是步骤 7 的带 key 数据驱动画布(非静态 golden、非 Offstage 充数);`check_render_fidelity.py` 通过(真实 trace 逐组件达标);`check_interaction_wiring.py` 必须通过(每条交互逻辑运行时可达);`check_api_integration.py` 必须通过(每端点有 repo 调用点);fixture 同源且取值源自设计稿。

### 9. 模拟器验收截图 + 实体设备交互预览
用户要求“真机上看”时,不得把 emulator/simulator 当实体设备:先运行 `python3 ~/.agents/skills/iff/scripts/physical_device_preview.py --project-root . --device <可选id> --dart-define IFF_HOME_STATE=<state> --out .iff/physical_device_preview.json`;只接受 `emulator=false` 的 Android/iOS mobile。脚本输出 `runCommand`;`ok=true` 后原样执行并保持 `flutter run` 会话供用户查看。实体设备预览不替代下面 `actual_source=simulator_screenshot` 的标准化视觉证据。
硬门:iOS 构建前必须校验工程 `DEVELOPMENT_TEAM`、本地 Apple Development identity、bundle id、目标 UDID 与本地 profile;确定的 team/identity 不匹配必须在构建前以结构化 `ios_signing` blocker 停止,不得自动改 bundle id/team 或伪造 profile。用户修复外部 Apple 账号/签名状态后,重跑同一预检并从 `runCommand` 继续。
命令(确定性选择; Android 不可用时回退 iOS Simulator):
```bash
# 真实入口可达的 MaterialApp/CupertinoApp 必须显式关闭 debug banner;非零在设备 I/O/repair 前停止。
python3 ~/.agents/skills/iff/scripts/check_capture_readiness.py --project-root . --entry lib/main.dart --scene spec_dir/scene.json --page-source lib/<feature>/presentation/<online_page>.dart --policy-source lib/<feature>/presentation/<state>_status_bar_policy.dart --startup-policy-source lib/<feature>/presentation/<initial_state>_status_bar_policy.dart --out spec_dir/capture_readiness.json
# 先做有界平台/设备选择;只选择真实 Android emulator 或 iOS Simulator。
# Android emulator 启动失败/超时会保留 actionable stderr 到 fallbackReason,然后回退 iOS。
# 禁止 adb wait-for-device;所有 adb/emulator/simctl 调用都由脚本 timeout 收口。
python3 ~/.agents/skills/iff/scripts/select_runtime_device.py --platform auto \
  --command-timeout 10 --boot-timeout 120 --out spec_dir/runtime_device.json
# 读取这个小 JSON 的 platform 后,只在锁外预构建被选中的平台:
# android -> flutter build apk --debug
# ios     -> flutter build ios --simulator --debug

# 设备互斥只护**设备 I/O**(安装/启动/截图),不护构建:Gradle/Xcode 编译是设备窗口最大成本,必须在锁外先做——
# 单设备(默认):
python3 ~/.agents/skills/iff/scripts/device_lock.py acquire --lock .iff/device.lock --label "$ROW_TITLE" --timeout 900
# 设备池(main 在 goal 环境探明多台 emulator 时下发;池内 profile 必须完全一致——宽=artboard、density 160、
# 隐 banner、固定时钟,否则同页跨设备像素诊断漂移):acquire stdout 末行返回 JSON {"device":...,"lock":...}:
# python3 ~/.agents/skills/iff/scripts/device_lock.py acquire --lock .iff/device.lock --pool "emulator-5554,emulator-5556" --label "$ROW_TITLE" --timeout 900
# 非首屏的 feature 页加 --route /<feature-route> 直接启到该页,**不要改 main.dart 的 initialRoute**。
# capture 会复验 selection 中设备仍 ready;flutter launch 与 adb/simctl 截图均有界,不会无限等待。截图默认要求至少 2 个连续稳定帧,最多采样 4 次;有 reference 时同时拒绝与参考亮区重叠的大面积异常黑块。未得到稳定且非损坏帧必须报错,不得覆盖 `actual.png` 或继续 diff。
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py \
  --selection spec_dir/runtime_device.json --command-timeout 15 --launch-timeout 300 \
  --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
# 截图完**立即释放**(成功、失败、error 任何退出路径都必须 release;池模式加 --device):
python3 ~/.agents/skills/iff/scripts/device_lock.py release --lock .iff/device.lock [--device <device>]
# 需 repair 时**不持锁跨 repair**:修改+重建全在锁外完成,复验截图前重新 acquire(两个短 I/O 窗口)。
# 复验是全新 build+run,资产/pubspec/字体改动天然被重新打包,证据链不受影响。
```
强制 iOS(需要时):
```bash
python3 ~/.agents/skills/iff/scripts/select_runtime_device.py --platform ios \
  --command-timeout 10 --boot-timeout 120 --out spec_dir/runtime_device.json
python3 ~/.agents/skills/iff/scripts/capture_runtime_screenshot.py \
  --selection spec_dir/runtime_device.json --out spec_dir/actual.png --manifest spec_dir/visual_manifest.json
```
输出: `runtime_device.json`(被选平台/设备、启动来源、Android 失败时的 `fallbackReason`)、`actual.png`(**组件上线页**截图,真机像素诊断用)和 `visual_manifest.json`(`actual_source=simulator_screenshot`,`platform`,`device_id`,`capture_command`,`timestamp`)。结构化逐组件保真门用的是 `check_render_fidelity.py`(真实渲染 trace,步骤 12),不再抓 golden.png 做像素比对。
硬门: 推荐视觉专用 emulator profile,宽度直接设为 artboard 宽度(例如 750),density 固定 160,隐藏 debug banner并固定时钟。设计稿中的时间/信号/Wi-Fi/电量等伪状态栏节点始终由 `system_ui_filter.py` 剔除,App 不得重画。`check_capture_readiness.py` 必须按 scene 自动执行双态合同并核验 `--policy-source` 是 `make_status_bar_policy.py` 当前生成、与 scene 一致且被 `--page-source` 引用:① `systemUiExclusions` 含 `role=status_bar` 时,真实系统状态栏必须可见,使用 `SystemUiMode.edgeToEdge` + 透明 `statusBarColor`,页面从屏幕顶部开始并绘制到状态栏背后;页面根部禁止默认 `SafeArea`、`MediaQuery.*.top` 或未启用 `extendBodyBehindAppBar` 的 AppBar 预留顶部空间,如仅需保护侧边/底部则用 `SafeArea(top:false,...)`。② scene 明确不含状态栏时,使用 `SystemUiMode.manual` 且 overlays 只保留 `SystemUiOverlay.bottom`,完全隐藏顶部状态栏并且不预留 top inset。入口必须在 `runApp` 前 `await` 初始策略并把同一控制器交给页面复用；Android 的 `LaunchTheme`/`NormalTheme` 和实际 `FlutterActivity` 必须匹配 `--startup-policy-source`：hidden 必须使用系统 `NoTitleBar.Fullscreen` 父主题、`windowFullscreen=true`、`windowDrawsSystemBarBackgrounds=true` 和透明 `statusBarColor`（只写 fullscreen item 不足以约束 Android 12+ 系统 SplashScreen），还要在 `super.onCreate` 前设置 `FLAG_FULLSCREEN`，在其后安全隐藏 Insets，并在 `onPostResume`/`onWindowFocusChanged` 持续恢复隐藏直到 `onFlutterUiDisplayed` 关闭一次性启动守卫（提前访问 InsetsController 会因 DecorView 未创建而崩溃，永久守卫又会破坏后续 overlay 页面）；overlay 则必须为非 fullscreen + 透明 statusBarColor + drawsSystemBarBackgrounds 且不得保留原生强制隐藏，禁止原生启动窗口先显示默认状态栏再在首帧后切换。混合页面必须逐页应用对应生成策略;未传 `--scene` 只检查 debug banner,不得猜测状态栏策略。`capture_readiness.json.statusBarPolicy` 必须记录 `overlay|hidden`、可见性、透明覆盖和 `reserveTopInset=false`。真实系统时间/信号/电量只允许出现在系统层,不能进入 artboard diff;摄像头/挖孔属于设备外观,不得由 App 绘制。禁止 `adb wait-for-device` 或任何无 timeout 的设备命令;Android 不可用/启动失败时必须按选择脚本确定性回退 iOS Simulator,两边都失败则原样上报两侧诊断并停止;截图只允许真实 `adb screencap`/`simctl screenshot`;不得 resize actual,如必须裁剪只能做确定性 top-crop,禁止 center-crop;`actual_source != simulator_screenshot` 不能 `done`;`actual.png` 不能由 reference 派生。

hidden 启动补充硬门：`LaunchTheme` 必须使用 `Theme.Translucent.NoTitleBar.Fullscreen`（或显式 `windowIsTranslucent=true`）并设置 `windowAnimationStyle=@null`，用于绕过 Android 12+ 系统 SplashScreen，同时禁止透明启动窗口进场动画把桌面状态栏带入 App 过渡帧；`NormalTheme` 必须保持不透明 fullscreen。`check_capture_readiness.py` 必须验证该组合。
### 10. 自动 diff
命令:
```bash
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --data-slot-bindings spec_dir/data_slot_bindings.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.agents/skills/iff/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --require-actual-trace --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
```
输出: `diff_report.json`、`diff_heatmap.png` 和 `repair_plan.json`;`diff_report.json` 至少包含 `ssim`、`pixelMismatch`、`viewportIssues`、node-level `bboxIssues`、`textIssues`、`assetIssues`、`shapeIssues`、颜色 delta、字号/行高差异、缺失 asset 区域、按影响面积排序的 `topP0`;`repair_plan.json` 必须去重合并同一 bbox/score 的设计节点 alias,保留 `rawActionCount` 与 dedup 后 `actionCount`,把差异按 `viewport` → `layout_region` → `asset_region` → `text_region` → `shape_region` → `fine_pixels` 排序,并给出每项的组件、node、role、score、expected、observed、structuralDelta、diagnostic、repairAction、sourceNodes。若存在 `implementation_map.json` 或 `actual_layout_trace.json`,必须合并到 `implementationHints` 和 `actualTrace`;若不存在,必须在 `diagnosticWarnings` 中说明边界,不得凭空编造文件、widget 位置或真实 bbox/font 差异。
硬门: actual/reference 尺寸不一致、SSIM < 0.99、非透明像素差异 > 1%、主节点 bbox 偏移 > 2 logical px、主色 RGB 差 > 3、字号误差 > 1px、圆角误差 > 1px、OCR 文案不一致、缺 asset,都必须进入单次 repair。单次 repair 复验后仍不达标时不得继续循环修,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求。

### 11. diff 驱动单次修复
固定单次流程:**模型只读 `repair_plan_top.json`**(summary+topAction+首批同类 action;完整 `repair_plan.json` 可达 177KB,属脚本产物禁整读)→ 只处理 dedup 后最大 P0 类别和第一批同类 action → 按优先级修截图尺寸/裁剪/viewport、节点位置尺寸、资产缺失、文字字号/行高/weight、颜色/圆角/阴影、细节间距中的命中项(**修改+重建在锁外**)→ 重新 acquire 设备锁 → rerun app → capture screenshot → release → rerun diff → 记录 `post_repair_diff_report.json` 和 `visual_report.md` → 进入下一需求。
硬门: 每个页面/每行最多执行一次 repair;禁止 repeat/while/until threshold 式循环打磨;禁止不看 repair plan 直接重写;禁止只改测试;禁止用 reference 图当背景;禁止 CSV 标 done 后再补。`diff_report.json` 是测量结果,`repair_plan.json` 是唯一修复输入,模型只读 `repair_plan_top.json` 并负责实现修改;确定性脚本只测量/守门,不得自动改业务 UI。首次 plan 必须带 `--require-actual-trace` 且 `hasActualTrace=true`;缺/空 trace 在 repair 前停止且不消耗预算。单次 repair 后用第 3 次 audit `flutter test test/<feature>` 刷新 trace,再只复验截图/diff/plan 一次;复验仍有 P0/P1 或阈值不达标时写 `error` 并继续下一需求。

### 12. done 前审计
命令(**`flutter test` 全行程只允许 3 次调用**:③红灯一次、⑤绿灯一次、本步骤一次——**三次全部 scoped 到 `test/<feature>`**。trace 测试已在 green 前生成并随 green 首次产出 `actual_layout_trace.json`;本步骤在单次 repair 后用同一 feature 套件刷新 trace,禁止再单独起 targeted 调用;每次调用冷启 JIT 编译 20-40s,逐 case 跑是实测 40min/页的第二大浪费。**全仓回归不在本步骤跑**——它随工程增长线性变慢且批内每 feature 重复一遍,由串行扇入统一跑一次、全绿才许写 done):
```bash
# 先生成 trace 测试(它随下面的全量 flutter test 一起执行并写出 actual_layout_trace.json):
python3 ~/.agents/skills/iff/scripts/merge_shared_expected.py --expected lib/<feature>/presentation/<canvas>.dart.expected.json --local spec_dir/shared_components.local.json --scene spec_dir/scene.json --out spec_dir/merged_expected.json
# 任一共享组件仍为 status=missing 时本步必须失败，禁止静默漏出视觉门。detector 仅可凭同 source spec + 完全一致 canonical node 顺序迁移旧签名注册项；paintless 节点仅在注册 expected 已有 image/asset provenance 时复用。
# 设计导出坐标不完美是常态：header bbox 若出现 x<=artboardWidth 但 x+width 越界的“右边缘误写为 x”形态，detector 必须确定性归一为 x-width，并记录 bbox_adaptation；merge/trace/assembly 全部消费归一坐标。普通 region 的有意越界不得套用此适配。
python3 ~/.agents/skills/iff/scripts/gen_layout_trace_test.py --expected spec_dir/merged_expected.json --page-import package:<pkg>/<feature>/presentation/<online_page>.dart --extra-imports package:<pkg>/<feature>/data/<repo_or_fixture>.dart --page-type <OnlinePageWidget> --page-expr "<OnlinePageWidget(repository: Mock<Feature>Repository.design())>" --trace-out spec_dir/actual_layout_trace.json --out test/<feature>/<feature>_layout_trace_test.dart
# trace 必须包含与同板 merged_expected.json 完全一致的 expectedNodeIds；误传 raw sidecar 时生成器自动采用 trace 同目录 merged expected，并以当前 canvas 节点覆盖陈旧基础几何。
flutter test test/<feature>        # 唯一一次:交互测试 + trace 测试 + 本 feature 回归全在这一次调用里(全仓回归由扇入批级统一跑一次)
python3 ~/.agents/skills/iff/scripts/check_responsive_layout.py --contract spec_dir/responsive_layout_contract.json --report spec_dir/responsive_layout_report.json
python3 ~/.agents/skills/iff/scripts/check_asset_resources.py --assets-manifest spec_dir/assets_manifest.json
# 响应式硬合同:所有移动端 UI 以 Figma 375 逻辑宽设计稿为基准。设计导出若为 750px @2x，只在生成期除以 scale=2；运行时禁止使用 screenWidth/designWidth、Transform.scale 或屏幕宽高比进行整体缩放。Android 将逻辑标注直接作为 dp、字体作为 sp；iOS 将逻辑标注直接作为 pt。Flutter 对应逻辑像素和未缩放字体。375 宽必须逐标注还原；其它宽度只允许使用 left/right/center/stretch 锚点、约束布局和必要断点重排，固定尺寸与字体值不随屏幕变化。长页滚动、短页顶部对齐；顶部系统区域严格消费 `capture_readiness.json.statusBarPolicy`:overlay 页面不预留 top inset,hidden 页面也不预留 top inset,侧边/底部安全区可用 `SafeArea(top:false,...)`。若工程存在 .iff/target_viewports.json，gen_layout_trace_test.py 必须传 --viewports-file；否则验证 320x568、375x812、430x932。每个 viewport 必须 runtimeScale=1、无缺节点、无 overflow/无限约束，逻辑 bbox 偏差<=2px；done gate 强制复验 contract/report，并拒绝旧 fit-width 等比缩放策略。
# 图片硬合同:图标、简单 Logo、可矢量化插画优先选纯 SVG/VectorDrawable；SVG 含 `<image>`/`foreignObject` 时按位图处理，禁止用低分辨率 PNG 冒充矢量资源。所有图片必须由显式逻辑 width/height 或 aspectRatio 容器约束，并显式声明 ContentScale/BoxFit；原始像素尺寸不得参与布局。Android 本地位图按 mdpi/xhdpi/xxhdpi 等 density 资源目录提供，由系统选择；Compose 网络照片使用 Coil `ImageRequest.size(逻辑尺寸×density)`、明确 `contentScale` 并启用内存/磁盘缓存，CDN/服务端 URL 同步携带目标像素尺寸。iOS 使用对应 pt 容器和 scale-aware asset catalog。Flutter 使用 SVG renderer；位图使用 1.0x/2.0x/3.0x 变体或至少 3x 源并按容器×devicePixelRatio 解码；网络照片使用缓存 provider、目标 decode 尺寸和明确 BoxFit。每张画板导出资产清单后必须运行 `check_asset_resources.py`，拒绝错误资源类型、缺失 logicalSize/sourceDensity 和低于目标密度的位图。
flutter analyze
python3 ~/.agents/skills/iff/scripts/prepare_assembly_packaging.py verify --evidence lanhu/specs/<feature>/assembly_packaging.json
python3 ~/.agents/skills/iff/scripts/check_visual_manifest.py spec_dir/visual_manifest.json
python3 ~/.agents/skills/iff/scripts/check_capture_readiness.py --project-root . --entry lib/main.dart --scene spec_dir/scene.json --page-source lib/<feature>/presentation/<online_page>.dart --policy-source lib/<feature>/presentation/<state>_status_bar_policy.dart --startup-policy-source lib/<feature>/presentation/<initial_state>_status_bar_policy.dart --out spec_dir/capture_readiness.json
python3 ~/.agents/skills/iff/scripts/check_fixture_source.py --root .  # 自动探测 *VisualFixture 符号:test 与运行时须引用同一份(同源)
python3 ~/.agents/skills/iff/scripts/check_render_plan.py spec_dir/render_plan.json
python3 ~/.agents/skills/iff/scripts/check_design_artifacts.py --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_implementation_plan.py --plan spec_dir/implementation_plan.json --spec-dir spec_dir
python3 ~/.agents/skills/iff/scripts/check_implementation_map.py --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json
python3 ~/.agents/skills/iff/scripts/check_interaction_completeness.py --contract spec_dir/interaction_contract.json --row spec_dir/row.json --out spec_dir/interaction_completeness_report.json
python3 ~/.agents/skills/iff/scripts/check_interaction_coverage.py --plan spec_dir/interaction_test_plan.json --test-root test --evidence spec_dir/interaction_test_evidence.json
python3 ~/.agents/skills/iff/scripts/check_worker_compliance.py --manifest spec_dir/worker_compliance.json --skill-dir ~/.agents/skills/iff
python3 ~/.agents/skills/iff/scripts/visual_diff.py --reference spec_dir/reference.png --actual spec_dir/actual.png --layout spec_dir/layout_contract.json --data-slot-bindings spec_dir/data_slot_bindings.json --out spec_dir/diff_report.json --heatmap spec_dir/diff_heatmap.png
python3 ~/.agents/skills/iff/scripts/make_repair_plan.py --diff spec_dir/diff_report.json --layout spec_dir/layout_contract.json --render-plan spec_dir/render_plan.json --implementation-map spec_dir/implementation_map.json --actual-trace spec_dir/actual_layout_trace.json --out spec_dir/repair_plan.json --top-out spec_dir/repair_plan_top.json
# Track B 新门:
python3 ~/.agents/skills/iff/scripts/check_interaction_wiring.py --lib-root lib --test-root test --entry lib/main.dart --pubspec pubspec.yaml --contract spec_dir/interaction_contract.json --out spec_dir/wiring_report.json
python3 ~/.agents/skills/iff/scripts/check_api_integration.py --api-contract spec_dir/api_contract.json --lib-root lib --out spec_dir/api_integration_report.json
# 结构化逐组件保真门(替代 golden-vs-golden;不变量③⑥):trace **真实上线页** vs render_plan 期望。
# --page-type/--page-expr 必须是真实页面(注入**同源设计 fixture** 的构造),**不是孤立画布**——
# 这样错误的顶部 SafeArea、Stack 坍塌等页面级包裹 bug(见 memory)才会被 getRect 抓到;--extra-imports 传 repo/fixture。
# 多状态特性:每状态一个 trace 测试文件,全部在上面同一次 flutter test 里执行。
# merged_expected 含公共组件区域期望(bbox+presence,key=源 node id;挂载缺失/位置错/坍塌被 missing/bbox 抓到):
python3 ~/.agents/skills/iff/scripts/check_render_fidelity.py --trace spec_dir/actual_layout_trace.json --expected spec_dir/merged_expected.json --tokens spec_dir/tokens.json --diff-report spec_dir/diff_report.json --data-slot-bindings spec_dir/data_slot_bindings.json --out spec_dir/render_fidelity_report.json
```
硬门: CSV 行仍是 `doing`;worker 已加载当前 iFF 规则且 compliance 校验通过;`assembly_packaging.json` 的 phase/画板/资产/字体/hash/pubspec 登记当前重验通过;`capture_readiness.json.ok=true` 且真实入口显式关闭 debug banner;reference 是完整 artboard;actual 是真实模拟器截图(**组件上线页**,非 golden 静态画布);fixture 同源且取值源自设计稿展示值;交互 case 覆盖和 red/green 证据通过;多状态数量一致;`render_plan` 未使用整图冒充;页面结构由真实组件、文本、按钮、卡片、输入框、状态区域组成;**`check_render_fidelity` 通过(真实上线页逐组件:每节点 bbox≤2px、主色 RGB≤3、字号/圆角≤1px、文案 100%、token 100%;缺节点=Offstage/坍塌判失败;**icon/asset 区域形状门**:`--diff-report` 接入后,asset 区域原始 pixelMismatch>0.10 判 `asset_shape` 失败——bbox/主色看不见"位置对、颜色对、字形错"的图标,平坦区像素通道看得见,AA 残差(~<5%)不受影响)= 视觉验收的 PASS 门**;`visual_diff` 的像素 `ssim/pixelMismatch` 只作诊断,**不作 done 阻断**(跨引擎抗锯齿天花板,见 final_reminders);`repair_plan.json` 必须**存在**(像素诊断产物),但其 `summary.p0Count` **不作 done 阻断**——它由像素 diff 派生,p0 多为跨引擎字形 AA / 被排除的系统状态栏切图,属天花板;视觉是否达标只看 `check_render_fidelity`(若 `repair_plan` 出现**平坦区真实缺陷**类 p0,才回到单次 repair,但 AA/状态栏类 p0 一律不算);**`check_interaction_wiring` 通过(无 tested-but-unwired)**;**`check_api_integration` 通过(每端点有 repo 调用)**;test/analyze 通过。全部满足后才写 `status=done`、`actual_screenshot`、`visual_manifest`、`visual_report`。
</pipeline>

<visual_gate>
## P0 — 视觉一致性门
- `spec_dir/reference.png` 是完整设计 artboard 截图;优先从 Lanhu `/api/project/image` 的 `result.url` 或 `versions[0].url` 下载完整 `FigmaCover*.png`;没有完整 reference 不得实现,该行直接 `status=error`, `error=缺少完整设计 reference.png`。
- 每个视觉文件旁必须有 `visual_manifest.json`,至少包含 `reference_source`、`actual_source`、`device_id`、`capture_command`、`timestamp`。缺 manifest 或字段缺失时不得 `done`。
- “截图一致”验收只认设备真实截图:最终 `actual.png` 必须来自 emulator/simulator 运行后的 `adb screencap` 或 `xcrun simctl io booted screenshot`;`actual_source` 必须是 `simulator_screenshot`。`widget_golden` 可用于 worker 中间 QA,但不能作为最终 done 证据。
- `actual_source=generated_from_reference` 一律不能标 `done`,只能用于设计稿基准图。禁止把 reference 缩放后当 actual、把设计稿截图直接当运行截图、只看测试通过不看模拟器截图、只检查文件存在。
- 红线:验收必须是真实代码页面/组件渲染结果与设计稿结果保持一致;禁止将完整设计稿截图/完整 artboard 作为组件可见层、背景图、`Image.asset`、`DecorationImage` 或整图铺底。唯一允许的 reference 派生可见资产是 `prepare_shared_component_assets.py` 为 paintless 可见叶节点生成的节点 bbox 局部 PNG,且必须有门禁可验证的 `assetProvenance`;文本、数据槽、交互层和其他结构仍须真实组件实现。
- 测试 fixture 与 app runtime fixture 必须同源:widget 测试、preview、app shell/mock repository 必须读取同一份 fixture/provider。禁止测试里覆盖多状态数据、运行 app 时只注入一个默认产品或默认状态。
- 如果设计稿是多状态长图,app shell 的 preview/mock repository 必须返回同一组状态数据,最终模拟器截图必须呈现这组状态;少状态、默认单状态或与测试 fixture 不同源时不得 `done`。
- 每行 green 后必须用运行时 `actual.png` 对比 `reference.png`;没有有效运行截图不得 `done`;发现不一致时必须按 `repair_plan.json` 只修改一次并重新截图,不得只写报告或直接失败。
- 视觉报告至少检查:首屏主要模块位置/尺寸/层级、资产使用、颜色、字号、圆角、间距、文案、横竖布局结构、debug banner。
- 设计稿已有切图或导出资产时,不得用 Material 默认图标、占位盒子、近似卡片替代。
- 卡片/分区结构不得从设计稿的横向或分区布局变成居中竖排;首屏层级明显不一致时必须进入单次 repair,复验仍明显不一致则写 `error` 后进入下一需求。
- 文案必须与设计稿/表格补充一致;debug banner 不得出现在验收截图。
- worker 视觉 QA 通过后,主会话扇入还必须启动真实 app,按最终入口/路由/资产注册和同源 runtime fixture 在真实设备尺寸重新截图,保存 `reference.png`、`actual.png`、`compare/notes.md`;若发现新差异,只能按最终 `repair_plan.json` 修一次并重新截图/复验,不得循环到无差异。
- 每行唯一 GREEN 前必须已有 `assembly_packaging.json`;其画板资产目录、必需字体文件和 pubspec 登记必须由 `prepare_assembly_packaging.py prepare` 在有效 RED 后一次完成。done/completion gate 重验失败时不得用扇入补登记后继续,该 assembly 结果作废。
- 每行 `done` 前必须强校验:CSV 原 status 还不是 `done`;`worker_compliance.json` 证明 worker 加载了当前 iFF 规则;`reference.png` 是完整 artboard;最终 `actual.png` 来自真实运行截图;manifest provenance 有效;测试 fixture 与 app runtime fixture 同源;`interaction_test_plan.json` 的每个 case id 都映射到测试且有 red/green evidence;多状态设计稿的运行截图呈现同一组状态;`render_plan.json` 通过整图冒充审计;页面结构不是整图铺底;`check_render_fidelity.py` 对真实上线页 trace 逐组件达标(bbox≤2px/色≤3/字号·圆角≤1px/文案·token 100%/无缺节点/asset 区域 pixelMismatch≤0.10)= 视觉 PASS 门;像素 `diff_report.json` 的 `ssim/pixelMismatch` 只作诊断,受跨引擎天花板限制,不作 done 阻断;`repair_plan.json` 存在且没有 P0 action;`flutter test` 通过;`flutter analyze` 通过。
- 最小 CSV 回写:缺 `reference.png`、无法生成 `actual.png`、或单次 repair 复验后仍无法消除 P0/P1 视觉问题时,写 `status=error`, `error=视觉单次修复后仍不一致: ...`,然后进入下一需求;若表格有 `visual_report`/`actual_screenshot`/`visual_manifest` 列,同步写入对应路径。
</visual_gate>

<success_criteria>
- iFF 被 goal 调起后:读表 → 每行按 `<pipeline>` 固定命令产出机器视觉产物 → 并行实现画板 → feature assembly 有效 RED 后原子完成资产/字体/pubspec 打包并仅跑一次 GREEN → 串行集成(依赖/路由/codegen/analyze 一次性)→ 真机截图 diff → 单次 repair 复验 → 回写 `status/error/spec_dir`。
- `flutter test` 与 `flutter analyze` 无 error;每个已处理行的 worker 都有当前 iFF 规则 compliance;每个 feature 落地且符合 `reference.png` + `scene.json` + `groups.json` + `tokens.json` + `assets_manifest.json` + `layout_contract.json` + `render_plan.json` + `interaction_contract.json` + `interaction_test_plan.json` + `repair_plan.json`;页面由真实 Flutter 组件逐层渲染,不是整图铺底;交互 case 覆盖和 red/green evidence 通过;测试 fixture 与 app runtime fixture 同源;多状态设计稿在真实 app shell 中呈现同一组状态;真实上线页 `check_render_fidelity.py` 逐组件达标(结构化 PASS 门,非裸像素 SSIM)+ 真实设备 `actual.png`/`visual_manifest.json` 留作诊断 + `repair_plan.json` 无 P0 action。
</success_criteria>

<final_reminders>
P0 — 坐标画布脚本化:可见层 dart 由 `generate_canvas.py`(步骤 6.7)产出,**禁止模型手写 `Positioned`**;设计字体必须真打包(SF Pro 用本机 `SFNS.ttf`),否则文字逐像素全错。新增渲染语义改 `generate_canvas.py`,不要在生成的 dart 里手补。
P0 — 文本换行与 run 样式也属于设计编译:当 text bbox 高度明确对应多行但源文本没有 `\n` 时，`generate_canvas.py` 必须按 bbox/字号确定性写入显示换行；多 style run 优先保持 run 边界，普通文本按设计宽度贪心换行。每个 run 必须使用自己的 fontWeight，expected 同时记录 `sourceText` 与最终 `text/textRuns`；禁止因 Flutter 与 Figma 字宽差异让比较符、单位或末尾单词漂到错误行。
P0 — 跨引擎像素天花板(现实约束,已证明,勿白追):Flutter(Impeller)与 Figma/Lanhu 光栅化的字形/边缘抗锯齿必然不同,**即使填充逐像素一致、字体已打包**,仅边缘抗锯齿在 `delta>3` 下就约占 4.9% 像素(边缘像素 55% 翻转)。`visual_diff.py` 已修为标准度量(`ssim_windowed` 8x8 + pixelmatch YIQ 抗锯齿剔除,`--aa-threshold` 默认 0.1;report 含 `ssimWindowed/ssimGlobalLegacy/pixelMismatchRealDefect/pixelMismatchStrictLegacy`),**阈值未动**且已回归验证(注入平移/改色/色块都仍 fail,只放过真抗锯齿与亚感知差)。即便如此,含文字设计忠实渲染仍 ~**0.87 窗口SSIM / ~3% 真实差异**,仍 `<0.99 / >1%`——窗口 SSIM ~0.87 是文字密集设计的**地板**(SSIM 惩罚每个含字窗口的抗锯齿结构)。故 `SSIM>=0.99 且 mismatch<=1%` 对含文字/矢量设计**跨引擎物理不可达**。诊断只看 `pixelMismatchRealDefect`(平坦区真实缺陷)定位可修项;**严禁为过门放宽阈值/delta/aa-threshold**;真实缺陷修完仍 P0 时据实写 `error` 说明天花板,勿把抗锯齿残差当 bug 反复打磨。
P0 — 固定流水线:worker 必须按 `<pipeline>` 的 0-12 步执行,每步固定输入/输出/命令/硬门;不得跳步、合并步骤、凭经验替代脚本产物,或在缺输出时继续实现。
P0 — worker 规则注入:main 必须用 `make_worker_prompt.py` 生成 spawn prompt;fetch/board/contract/shared worker 先读取当前 `iff/SKILL.md` 和 `iff/test_rules.md`;**assembly 只读生成 prompt 的有界、hash 锁定 contract,禁止再整读 SKILL/test_rules**,且其 main 交接必须由相邻 `*.assembly_invocation.json` 驱动 supervisor prepare/verify(进程用 run)。所有 worker 写 `worker_compliance.json`;main 用 `check_worker_compliance.py` 通过后才接收。子 agent 不会天然继承 main 已加载的 skill,禁止假设会自动继承。
P0 — shared worker liveness:shared prompt 的相邻 `*.shared_invocation.json` 是唯一启动入口;只能通过 `shared_worker_supervisor.py run` 启动本地进程。supervisor 必须清旧证据、流式捕获输出、执行 total/idle timeout、timeout 时杀完整进程组,并且只在 worker exit 0 + 本轮 invocation-bound `shared_result.json(success=true)` + 新鲜当前 compliance 全部通过时 exit 0;禁止 direct `spawn_agent`、裸进程、无限等待或把旧文件/自然结束当成功。
P0 — 确定性必须脚本化:worker prompt/合规校验、分类、取稿、cover 下载、Figma scene/tokens/assets_manifest 导出、Figma hierarchy 分组、Figma layout contract、render plan、fixture、interaction contract/test plan、交互覆盖审计、assembly pre-GREEN 资产/字体/pubspec 打包与证据复验、Flutter starter test 安全退役、真机截图、manifest、diff、repair plan、审计都必须由 `~/.agents/skills/iff/scripts/` 下脚本完成;禁止调用 `fd/scripts`、项目本地 `scripts/`、临时脚本或让 worker 手工判断。
P0 — 非确定性只留给模型:模型只能做项目约定适配、业务逻辑补全、组件组织和按 `repair_plan_top.json` 修代码;不能替代脚本生成 JSON、统计数量、判定阈值、比对截图、排序修复项或审计 provenance。
P0 — done 总门:assembly 只有在 `assembly_completion.py issue` 内部 `check_done_gate.py` exit 0 后才能生成 `assembly_completion.json`;main 必须通过 `assembly_worker_supervisor.py verify` 要求本轮 prepare 后的新 evidence,并由它调用 `assembly_completion.py verify` 重跑 gate;**worker exit 0 不能替代 supervisor exit 0**。模型无权豁免任何一项失败(包括"看起来是误报"——误报去修 gate 脚本,不许绕行)。文本节点(含动态槽)**严禁被固定高度 + 裁切(ClipRRect/clipBehavior)容器包裹**——下降部被裁会把 "days" 渲成 "davs" 且 bbox/主色保真看不见(R1 实测);chip/胶囊类背景由画布画,文本悬浮其上不裁切;此类缺陷由 done 总门的平坦区 text 真缺陷通道兜底。
P0 — 阅读纪律(token 预算属于正确性;实测强制整读大 JSON 每页烧 10-25 万 token 且拖慢生成):模型先读 `artifact_digest.json`(83× 压缩);`scene.json`/`render_plan.json`/`layout_contract.json`/`implementation_plan.json`/`repair_plan.json`/`diff_report.json`/`oas.json`/`oas_ref_resources.json`/`raw.json` **禁止整读**,单节点数据按 node id 窗口查;assembly 的所有大 plan 由 `assembly_plan_batch.py` 批量预填/回填,模型只改小型 `assembly_decisions.json`;repair 只读 `repair_plan_top.json`;接口只读 `api_contract.json`。
P1 — `flutter test` 调用预算:每行 ≤3 次(red / green / done 审计各一次,**三次全部 scoped 到 `test/<feature>`**,审计含 trace 测试),**全部由 assembly-worker 执行,board-worker 一次都不许跑**;有效 RED 与唯一 GREEN 之间的 `prepare_assembly_packaging.py` 只做确定性文件/pubspec 打包,**禁止内部或额外运行任何 `flutter test`**;**全仓回归由串行扇入每批统一跑一次**(不随 feature 数重复、不随工程增长拖慢单行),全绿才许回写 done;禁止逐 case、逐文件反复起跑(每次冷启 JIT 20-40s)。
P1 — 交互三层闭环:①锚定——交互文字的视觉引用只认 `board_index` 确定性检索(唯一命中绑定/多候选模型确认/零命中 pending_route),`resolve_interaction_anchors --check` 不过不得设计测试;②状态机——多状态 feature 必须 `make_state_machine` 骨架+模型填边+`--check`,每条迁移边=一条 INT-SM 规则;③journey——跨页边进 `.iff/flow_graph.json`(扇入合并+路由轻验),全部行 done 后生成故事地图并真机回放清单终验。
P0 — 99% 还原靠设计稿编译器,不是模型看图想象 UI:视觉实现主输入是 `scene.json`、`groups.json`、`tokens.json`、`assets_manifest.json`、`layout_contract.json`、`render_plan.json`、`interaction_contract.json`、`interaction_test_plan.json`、`visual_fixture`、`diff_report.json`、`repair_plan.json`;`spec.md` 只能补充解释。
P0 — 第一版坐标编译:固定 artboard 根节点,用 `FittedBox` 或固定 artboard canvas 做适配,按 Figma `path/parent/children/bbox` + contract/render_plan 映射节点到 Widget,用真实 tokens/assets;先做到像,再谈工程优雅。
P0 — 保真量化门(结构化,不靠裸像素 SSIM,不变量③⑤):PASS 门 = `check_render_fidelity.py` 对**真实上线页渲染 trace** 逐组件达标——每可见节点 bbox 偏移 ≤ 2 logical px、主色 RGB 差 ≤ 3、字号/圆角误差 ≤ 1px、静态/未确认文案 100% 命中、已确认 API 文案只校验容器/排版/overflow/maxLines 而不要求值命中、token 100% 命中、无缺失(Offstage/坍塌)节点、**asset 区域形状达标(`--diff-report` 通道:先减去独立渲染的子节点 bbox,再剔除跨引擎 AA,`pixelMismatchRealDefect ≤ 0.10`;真实改色/缺失/错位仍失败)**。API 豁免必须由 `data_slot_bindings.json` 的 confirmedByModel + source kind + field + evidence 四项共同证明,并把文件传给 `visual_diff.py`/`check_render_fidelity.py`;未确认或证据不全立即失败。像素 `SSIM`/`pixelMismatch`(`visual_diff.py`)**只作诊断**,受跨引擎抗锯齿天花板(~0.87 窗口SSIM / ~3% 真实差异,见下条)限制,**不作 done 阻断、严禁为过门放宽阈值**;真实缺陷修完仍有像素残差属天花板,据实记录。
P0 — 视觉一致性门:每行 green 后必须用完整设计 `reference.png` 与运行时 `actual.png` 对比;没有 `reference.png` 不得实现,没有真实设备 `actual.png` 不得 `done`;“截图一致”验收只认 emulator/simulator 运行截图,任何从 reference 派生出来的 actual 都是无效证据;主要布局、资产、颜色、字号、圆角、间距、首屏层级明显不一致时,必须根据 `repair_plan.json` 修改一次并重新截图复验;复验达标才允许 CSV 写 `done`,复验仍不达标写 `error` 并进入下一需求;不得用 Material 默认图标、占位盒子、近似卡片替代设计稿已导出的资产;main 扇入后必须重新截图验收,发现差异也只能单次修正实现。
P0 — 并行 board-worker 只写各自画板文件和复制资产,不改 pubspec/路由/DI/codegen/analyze。feature assembly 只允许在有效 RED 后调用 `prepare_assembly_packaging.py` 通过工程级锁原子登记本 feature 全部资产目录/必需字体并在 GREEN 前产出 `assembly_packaging.json`;禁止手改/延后。依赖、路由、DI、codegen、analyze 仍一律留到串行扇入;shared-worker 的 pubspec 所有权仍按 2.5 串行收口,不变。
P0 — 公共组件复用:跨行共享区域(导航头/底部 tab/跨行同 signature 分组)先检测、先查注册表,**能复用绝不重画**;检测(`detect_shared_components.py`,componentId 优先、结构哈希兜底)与登记(`register_shared_component.py`)必须脚本化,禁止模型凭名字/截图判断"是同一个组件";公共组件的创建/修改只能发生在 2.5(实现可并行,pubspec/analyze/test/登记必须串行收口)或串行扇入,行 worker 只读挂载已登记 widget;`covered_by_shared_component` 区域不进画布;同一 signature 两个实现 = 错误;`assets_incomplete` 必须先由祖先原子资产覆盖或局部 reference-region fallback 确定性消解,仍不可安全适配时显式上报,禁止 Material 默认图标或近似图形静默顶替。
P0 — 单行 **TDD**:先写测试,由 `assembly_tdd_guard.py red` 跑出 red,packaging 后再由 `assembly_tdd_guard.py green` 跑 GREEN;测试源 = UI 理解 + `interaction_test_plan.json`;**交互描述每条都要覆盖 HAPPY/BOUNDARY/FAILURE**,case id 必须写进测试名或注释;测试只落本 feature test 目录;`interaction_test_evidence.json` 必须记录 guarded red/green 命令、exit_code、run/hash/timestamp provenance,且有效 red 必须记录 `failure_kind=missing_feature_behavior`;direct/out-of-order GREEN evidence 在 completion gate 一律失败。
P0 — iFF 只定**流程**,不定实现细节:架构/目录/命名/资产·路由·状态·接口口径,一律由 subagent **读当前工程(目录+相关代码+工程规则文件)后随项目实现**,绝不自创或硬编码某套架构。
P0 — 视觉实现红线:无论目标是否写“截图一致”,都禁止把设计稿截图或完整 artboard 作为组件可见层、背景图、`Image.asset`、`DecorationImage`、整图铺底或透明热区覆盖;允许确定性脚本仅为 paintless 可见叶节点裁切 bbox 局部 reference-region asset,但必须记录并通过 provenance/full-reference 门禁,不得包含相邻文本、数据槽或交互区域;交互热区可以叠加在真实视觉节点上,但不能替代视觉节点;验收只看真实 Flutter 页面/组件渲染结果与设计稿的一致性,必须组件逐层实现、截图比对、按 `repair_plan.json` 单次修复并复验。
P0 — 视觉 provenance:每个 `reference.png`/`actual.png` 旁必须有 `visual_manifest.json`;最终 `actual_source` 必须是 `simulator_screenshot`,不得是 `widget_golden` 或 `generated_from_reference`。
P0 — runtime 数据同源:视觉测试 fixture、widget preview、app shell/mock repository 必须使用同一份 fixture/provider;多状态长图必须在 app runtime 返回同一组状态数据,禁止测试多状态但最终 app 只注入默认单状态。
P1 — 工作批默认**每批 4 个互不影响的功能**(设备池 ≥2 台是前提;单设备退回 2,否则只是把排队搬进批里);实际 subagent 并发受 Codex 当前可用槽位限制,槽位不足则分波,但每波必须 spawn 满后才 `wait_agent`(实测逐个串行是 40min/页的第一大原因)。N 上调后 main 只收各 worker 固定 schema 的 JSON 摘要,**严禁 worker 回传产物内容**(protect main context,R1 教训);设备 I/O(9-11 的安装/启动/截图)是唯一互斥点,用 `device_lock.py`(mkdir 原子锁,支持 `--pool` 多 emulator——池内 profile 必须完全一致,任何退出路径必须 release,stale 锁自动破除);**构建(gradle/xcode)与 repair 修改一律锁外**,锁只护短截图窗口(首验、复验各一个)。
P1 — iFF 读表 + 回写 `status/error/spec_dir`;`goal` 是外部指令,iFF 不实现它。
P1 — 工作队列:**只选 status 为空**的行,每批 N(默认 4;设备池 <2 台退回 2);选中**即刻标 `doing`**(认领/防重/可续),完成标 `done` 或 `error`。
P1 — 单行顺序:确认视觉策略 → 本 skill 脚本取稿/下载完整 cover → **Apifox 读契约(运行时依赖,须配 Apifox MCP)** → 生成 scene/tokens/assets_manifest/groups/layout_contract/render_plan/fixture/interaction_contract/interaction_test_plan → 读项目 → 按交互测试计划设计测试(接口用例用真实契约 mock)→ 坐标编译实现 UI → 接口接入+mock 渲染 → 真实设备截图 diff → 单次 repair 复验 → 交互覆盖/视觉/manifest 自检。
P1 — 运行时外部依赖:**Apifox MCP**(读接口契约)、Lanhu 网络/API 访问、Flutter 设备/模拟器;真跑/测试前需在目标环境就绪。
P2 — `spec_dir` 缓存命中且包含 `reference.png` 才跳过取稿(幂等)。
P1 — 可见层工具链回归自测(改完即跑):任何对 `generate_canvas.py` / `gen_layout_trace_test.py` /
`check_render_fidelity.py` 的改动,改完**必须**跑 `python3 ~/.agents/skills/iff/scripts/selftest_canvas.py
--project <flutter工程>`——它用 `iff/selftest/` 的合成 reference 走完整链(生成画布 → flutter analyze 干净
→ 生成 trace 测试 → flutter test → check_render_fidelity 逐节点过),覆盖 text/金额/圆角 shape/渐变/
瘦高 Vector→'<'、矮宽 Vector→'v' chevron/输入值文本等易回归节点类型。绿了才提交。这是为根除"改一处编译/
运行回归被下一轮 worker 撞上"(曾致 R5/R7 训练)而固化的纪律。
