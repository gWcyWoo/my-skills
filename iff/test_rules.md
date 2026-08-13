# iFF 测试规则(单行 TDD)

> **迁移自 原 `tc`(general/unit/integration)并适配 Flutter + 自主批处理**:已剥离 tc 的交互 gate / STOP / `test-writer` / plan 评审(iFF 全自动、无用户 gate),保留其实质纪律,补 Flutter 测试惯例。每个 subagent 对自己这一行的 feature 按本规则走 TDD(red → green → refactor)。

## 测试来源(两源)
1. **设计结构 → widget 测试**:模型从 `artifact_digest.json` 与 bounded visual/data packet 理解当前 action;完整 `component_manifest.json`/`data_slot_bindings.json` 由脚本消费,禁整读。测试断言真实组件、关键文案、状态区域、资产节点和交互热区存在;断言可观察结果,不把 `spec.md` 当视觉来源。
2. **交互规则 → widget/integration 测试**:先用 `parse_interactions.py` + `make_interaction_tests_plan.py` 把 `interaction` 编译为 `interaction_contract.json` 和 `interaction_test_plan.json`;`interaction` 里**每一条交互描述都要覆盖 HAPPY / BOUNDARY / FAILURE**。每个测试必须在测试名或注释中包含 plan 里的 case id(如 `INT-001-HAPPY`),供 `check_interaction_coverage.py` 审计。涉及接口的交互:把 `api` 作为 **mock 依赖**(按接口契约伪造),断言「触发 →(mock 接口)→ 状态/渲染/导航」的可观察结果;不断言调用次数/内部顺序(除非顺序本身是契约)。

## 分层职责(单元 与 widget/集成 等同重要,只有合起来才证明正确)
- **单元测试**拥有:复杂纯逻辑、边界矩阵、widget/集成难可靠触达的分支;锁「输入 → 输出/效果」,绝不锁代码形状;若单元里需要 mock 网络/进程,说明该用例属集成,移到集成。
- **widget/集成测试**拥有:界面/交互/接口入口、流程(happy 与变体)、数据与校验边界、错误/失败路径(在同一入口注入);断言可观察结果(渲染、状态、导航、回调效果)。**一契约一来源**:邻居的 mock 必须源自同一接口契约,不得各自臆造。

## Track B 测试(组件 / 接口 / 接线)
- **组件测试**:每个按态组件用同源 fixture 渲染,断言该态的可见文本/按钮/动态槽值正确,点击发出预期 `intent`(断言回调/intent 可观察结果,不直接断言导航实现)。
- **Repository 测试**:经 repository 公共 interface 注入边界 HTTP fake,断言真实 method/path/request/response DTO/mapper 与 loading/success/error/适用 empty/retry/polling;real/mock 共用 interface/DTO/mapper,fixture provenance 由 `check_fixture_source` 验证。
- **数据驱动测试**:每个真实 binding 有 `DATA-SLOT:<node>` case;同 feature 多设计状态使用 `DATA-SLOT:<state>:<node>`,即使 node id 重复也不合并覆盖。至少用两个 DTO 值通过同 mapper 渲染真实页面并断言 `ValueKey('iff:<node>')` 对应可见文本变化;不得依赖设计字面量 fallback。每 operation 有 `DATA-REPO:<id>` 与全部 `DATA-STATE:<id>:<state>` case;最终必须在目标 Android 模拟器/iOS Simulator(或真机)客户端观察全部 SLOT/STATE 可见结果,每 case 有公开页面 action 和真实 runtime capture,SLOT 记录两个不同输入与对应两个不同可见值;不得用 Web/Chrome 或 VM 命令参数代替。
- **集成测试**:页面层 `tap → intent → 导航/风控链/接口` 的可观察结果;每条交互规则必须有一条集成或组件测试覆盖其**运行时路径**(对应 `check_interaction_wiring`:领域逻辑不能只被单测引用而运行时不可达)。
- **接线断言**:至少一条测试经由真实 app 入口可达路径触发交互逻辑(而非直接 import 领域函数),为 wiring 门提供行为级支撑。

## 红灯纪律(硬)
- 新功能:所有新测试必须因**缺功能而失败**,不是编译/环境错误。为让包能编译,**仅**可给确实新增的符号加**空签名桩**(空体返回未实现/零值);桩必须保持空——往桩里写逻辑、或改写/删除/重命名任何**已有**生产符号,都是实现(green 阶段才做)。
- 绝不用 `skip` / `solo` / 注释掉断言 / 伪造结果 来制造红或绿。
- red 阶段只写**测试 + 空桩**;若某红测试只能靠写生产代码才能转绿,那属于 green 阶段。
- 每行必须用 `run_feature_tests.py` 在同一 Flutter machine run 写 `interaction_test_evidence.json` + `data_test_evidence.json`;记录 red/green 命令、exit code、逐 case 结果与当前 plan/bindings/runtime/test SHA。red 至少一个两域计划内 case 失败,green 全 case 成功且未 skip。
- **调用预算(硬)**:red 证据 = `run_feature_tests.py` 对本 feature 测试目录的**一次** Flutter 调用(交互+数据全部同一次红);green 同理一次;done 审计再全量一次(含 trace)。全行程 ≤3 次;禁止分别调用 interaction/data runner、逐 case、逐文件反复冷启。客户端终验由 main 在串行扇入后只跑一次 `run_client_device_tests.py`,同一命令/输出同时生成 interaction/data evidence。
- **模型上下文预算(硬)**:board/assembly v3 合同与 component/每板 visual/interaction/data packet 每文件≤8KB;packet 正好一个 action;取稿由 `run_fetch_pipeline.py` 直接执行,不占模型上下文。完整 row/公共组件/大 JSON 由脚本消费。`check_model_context.py` 必须按 feature manifest 精确重算 worker roster、receipt、合同、三份规则、packet 源 SHA、累计生成字节与当前保留字节;陈旧、缺失/多余、超限、多 action、要求整读规则都失败。
- 测试名陈述**契约(行为)**,不陈述实现;锁定既有行为的守护用例要显式标注。

## 隔离与确定性
- 无随机、注入时钟、临时目录;等待用截止轮询而非裸 sleep;widget 测试用 `pump` / `pumpAndSettle` 推进,不依赖真实计时。

## 自主执行(iFF 区别于 tc 之处)
- **全自动**:无用户 STOP、无 plan 评审。以「测试确实先 red 过」为硬证据自证 red gate,再实现到 green,最后重构。green 后该 feature 的全部测试必须真绿(不得靠 skip/弱断言)。
