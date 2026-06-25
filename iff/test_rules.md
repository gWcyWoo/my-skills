# iFF 测试规则(单行 TDD)

> **迁移自 原 `tc`(general/unit/integration)并适配 Flutter + 自主批处理**:已剥离 tc 的交互 gate / STOP / `test-writer` / plan 评审(iFF 全自动、无用户 gate),保留其实质纪律,补 Flutter 测试惯例。每个 subagent 对自己这一行的 feature 按本规则走 TDD(red → green → refactor)。

## 测试来源(两源)
1. **UI 理解 → widget 测试**:从 `spec.md`(+ `ui_notes`)理解 UI,断言渲染 / 关键元素存在 / 布局 / 文案;断言可观察结果,不锁实现细节。
2. **交互规则 → widget/integration 测试**:先用 `parse_interactions.py` + `make_interaction_tests_plan.py` 把 `interaction` 编译为 `interaction_contract.json` 和 `interaction_test_plan.json`;`interaction` 里**每一条交互描述都要覆盖 HAPPY / BOUNDARY / FAILURE**。每个测试必须在测试名或注释中包含 plan 里的 case id(如 `INT-001-HAPPY`),供 `check_interaction_coverage.py` 审计。涉及接口的交互:把 `api` 作为 **mock 依赖**(按接口契约伪造),断言「触发 →(mock 接口)→ 状态/渲染/导航」的可观察结果;不断言调用次数/内部顺序(除非顺序本身是契约)。

## 分层职责(单元 与 widget/集成 等同重要,只有合起来才证明正确)
- **单元测试**拥有:复杂纯逻辑、边界矩阵、widget/集成难可靠触达的分支;锁「输入 → 输出/效果」,绝不锁代码形状;若单元里需要 mock 网络/进程,说明该用例属集成,移到集成。
- **widget/集成测试**拥有:界面/交互/接口入口、流程(happy 与变体)、数据与校验边界、错误/失败路径(在同一入口注入);断言可观察结果(渲染、状态、导航、回调效果)。**一契约一来源**:邻居的 mock 必须源自同一接口契约,不得各自臆造。

## 红灯纪律(硬)
- 新功能:所有新测试必须因**缺功能而失败**,不是编译/环境错误。为让包能编译,**仅**可给确实新增的符号加**空签名桩**(空体返回未实现/零值);桩必须保持空——往桩里写逻辑、或改写/删除/重命名任何**已有**生产符号,都是实现(green 阶段才做)。
- 绝不用 `skip` / `solo` / 注释掉断言 / 伪造结果 来制造红或绿。
- red 阶段只写**测试 + 空桩**;若某红测试只能靠写生产代码才能转绿,那属于 green 阶段。
- 每行必须写 `spec_dir/interaction_test_evidence.json`,记录 red/green 命令、exit_code 和每个 interaction case id 的测试映射;red 的 exit_code 必须非 0,green 的 exit_code 必须为 0。
- 测试名陈述**契约(行为)**,不陈述实现;锁定既有行为的守护用例要显式标注。

## 隔离与确定性
- 无随机、注入时钟、临时目录;等待用截止轮询而非裸 sleep;widget 测试用 `pump` / `pumpAndSettle` 推进,不依赖真实计时。

## 自主执行(iFF 区别于 tc 之处)
- **全自动**:无用户 STOP、无 plan 评审。以「测试确实先 red 过」为硬证据自证 red gate,再实现到 green,最后重构。green 后该 feature 的全部测试必须真绿(不得靠 skip/弱断言)。
