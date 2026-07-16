# iFF 测试规则(单行 TDD)

> **迁移自 原 `tc`(general/unit/integration)并适配 Flutter + 自主批处理**:已剥离 tc 的交互 gate / STOP / `test-writer` / plan 评审(iFF 全自动、无用户 gate),保留其实质纪律,补 Flutter 测试惯例。每个 subagent 对自己这一行的 feature 按本规则走 TDD(red → green → refactor)。

## 测试来源(两源)
1. **设计结构 → widget 测试**:从 `artifact_digest.json`、`component_manifest.json`、`data_slot_bindings.json`、`tokens.json`、`groups.json`(+ `ui_notes`)理解 UI(大 JSON 禁整读,按 node id 窗口查,见 SKILL.md 阅读纪律),断言真实组件、关键文案、状态区域、资产节点和交互热区存在;断言可观察结果,不把 `spec.md` 当视觉来源。
2. **交互规则 → widget/integration 测试**:先用 `parse_interactions.py` + `make_interaction_tests_plan.py` 把 `interaction` 编译为 `interaction_contract.json` 和 `interaction_test_plan.json`;`interaction` 里**每一条交互描述都要覆盖 HAPPY / BOUNDARY / FAILURE**。每个测试必须在测试名或注释中包含 plan 里的 case id(如 `INT-001-HAPPY`),供 `check_interaction_coverage.py` 审计。涉及接口的交互:把 `api` 作为 **mock 依赖**(按接口契约伪造),断言「触发 →(mock 接口)→ 状态/渲染/导航」的可观察结果;不断言调用次数/内部顺序(除非顺序本身是契约)。

## 分层职责(单元 与 widget/集成 等同重要,只有合起来才证明正确)
- **单元测试**拥有:复杂纯逻辑、边界矩阵、widget/集成难可靠触达的分支;锁「输入 → 输出/效果」,绝不锁代码形状;若单元里需要 mock 网络/进程,说明该用例属集成,移到集成。
- **widget/集成测试**拥有:界面/交互/接口入口、流程(happy 与变体)、数据与校验边界、错误/失败路径(在同一入口注入);断言可观察结果(渲染、状态、导航、回调效果)。**一契约一来源**:邻居的 mock 必须源自同一接口契约,不得各自臆造。

## Track B 测试(组件 / 接口 / 接线)
- **组件测试**:每个按态组件用同源 fixture 渲染,断言该态的可见文本/按钮/动态槽值正确,点击发出预期 `intent`(断言回调/intent 可观察结果,不直接断言导航实现)。
- **Repository 测试**:用 Apifox 真 OAS 形 mock(同 DTO)断言 fetch/apply/authStatus 解析与错误/空态;mock 与运行时同源(`check_fixture_source`)。
- **集成测试**:页面层 `tap → intent → 导航/风控链/接口` 的可观察结果;每条交互规则必须有一条集成或组件测试覆盖其**运行时路径**(对应 `check_interaction_wiring`:领域逻辑不能只被单测引用而运行时不可达)。
- **接线断言**:至少一条测试经由真实 app 入口可达路径触发交互逻辑(而非直接 import 领域函数),为 wiring 门提供行为级支撑。

## 红灯纪律(硬)
- 新功能:所有新测试必须因**缺功能而失败**,不是编译/环境错误。为让包能编译,**仅**可给确实新增的符号加**空签名桩**(空体返回未实现/零值);桩必须保持空——往桩里写逻辑、或改写/删除/重命名任何**已有**生产符号,都是实现(green 阶段才做)。
- 绝不用 `skip` / `solo` / 注释掉断言 / 伪造结果 来制造红或绿。
- red 阶段只写**测试 + 空桩**;若某红测试只能靠写生产代码才能转绿,那属于 green 阶段。
- red 必须因缺功能/行为失败,不得因画板资产未注册、字体未打包、pubspec 缺项、编译或环境错误失败。RED 与 GREEN 都必须由 `assembly_tdd_guard.py` 执行,禁止 assembly 直接调用对应的 `flutter test` 或手写证据。有效 red 记录后、唯一 green 前,assembly 必须运行一次 `prepare_assembly_packaging.py prepare` 完成全部画板资产目录和必需字体登记;该命令不得运行 `flutter test`,不得占用测试调用预算。
- 每行必须写 `spec_dir/interaction_test_evidence.json`,记录 guarded red/green 命令、exit_code、run id、纳秒时序、packaging hash 和每个 interaction case id 的测试映射;red 的 exit_code 必须非 0 且 `failure_kind="missing_feature_behavior"`,green 的 exit_code 必须为 0。packaging 必须绑定当前 guarded RED 且时间更新;GREEN guard 必须在启动测试前复验 packaging;done/completion gate 必须拒绝 direct、旧、伪造或乱序 GREEN evidence。
- **调用预算(硬)**:red 证据 = 对本 feature 测试目录的**一次** `flutter test test/<feature>` 调用(全部新测试在同一次里红);green 同理**一次**;done 审计对 `test/<feature>` 再**一次**(含 trace 测试;**全仓回归由 main 串行扇入批级统一跑一次,不占本预算、不由 worker 跑**)。全行程 `flutter test` ≤ 3 次;**禁止逐 case、逐文件反复起 `flutter test`**——每次调用冷启 JIT 编译 20-40s,是实测单页耗时(40min)的第二大浪费。修复后的复跑合并进下一次预算内调用,不单独加跑。
- 测试名陈述**契约(行为)**,不陈述实现;锁定既有行为的守护用例要显式标注。

## 隔离与确定性
- 无随机、注入时钟、临时目录;等待用截止轮询而非裸 sleep;widget 测试用 `pump` / `pumpAndSettle` 推进,不依赖真实计时。

## 自主执行(iFF 区别于 tc 之处)
- **全自动**:无用户 STOP、无 plan 评审。以「测试确实先 red 过」为硬证据自证 red gate,再实现到 green,最后重构。green 后该 feature 的全部测试必须真绿(不得靠 skip/弱断言)。
