# iFF 实现规范(Flutter)— 权威源

> 本文件是 iFF 落地 Flutter 代码的**强制实现规范(MUST)**,所有 worker 写代码前必须加载并遵守。
> 由 `scripts/sync_project_rules.py` **注入到目标工程的 `CLAUDE.md`**(分隔块内),工程内所有 agent 统一遵守;改规范只改本文件再同步,不在工程副本里直接改。
> 规则 ID `IMPL-<类>-<n>` 供:worker 按 ID 精确引用、`worker_compliance.json` 核对、`check_static.py` 与结构 QA 映射。

## 速查索引

| 类 | 主题 | 关键硬点 |
|---|---|---|
| `CORE` | 总则 | 证据驱动 · 随项目 · 不绕检查 |
| `STYLE` | 风格命名 | 两空格 · PascalCase/camelCase/snake_case · 单引号 · 尾逗号 · 显式返回类型 |
| `DOC` | 中文注释 | 解释"为什么" · 公共基础设施完整注释 · 失效注释同步更新 |
| `LAYER` | 分层 | presentation/domain/data · 公共组件不含业务流程 |
| `LAYOUT` | 布局响应式 | **关系换算优先 · 禁硬编码坐标/scale · TextStyle 禁 height** |
| `HIER` | 视觉层级还原 | 父容器/右侧图标/整行宽度/文本归属 |
| `COMP` | 组件拆分 | 先搜复用 · 不过度抽 · 一致样式抽公共组件 |
| `FORM` | 表单 | 输入/选择拆开 · 原生 InputDecoration · 不包 InkWell |
| `TOKEN` | 颜色 token | 不散落 Color(0x..) · 集中 app_colors · 不留转发别名 |
| `IMG` | 图片图标 | 集中复用 · 缺失先列清单 · 忽略系统状态栏切图 |
| `UNIT` | 单位换算 | **像素 ÷2** · pt/dp/sp 原值 · 注释不搬单位 |
| `ASSET` | 资源运行时 | assets/images/ · 禁引用 lanhu/ · 禁远程 URL · 不提交构建产物 |
| `FLOW` | 申请链路 | 复用公共 Header/底部按钮/AppColors |
| `DIALOG` | 弹窗 | Dialog(transparent) · Column.min · 禁画布尺寸 |
| `SHEET` | 底部弹框 | 宽度自适应 · 固定 footer |
| `INFRA` | 工具/服务/仓库 | 先查既有 · key 集中 · 单例/Provider 复用+可注入 |
| `TEST` | 测试 | *_test.dart · 可观察行为 · UI/模型/mock 改动同步 |
| `DOCS` | 文档 | docs/ 单一来源 · 需求即入文档 |
| `VCS` | 提交 PR | 祈使句 · PR 含验证命令+截图 |

> 优先级:本文件 > iFF `SKILL.md` 流程细节 > 通用习惯。冲突显式指出并解决,不取折中。

---

## CORE 总则
- **IMPL-CORE-1** 证据驱动:严格依据设计图 / `lanhu/specs/**/spec.md` 视觉事实生成,不凭印象/猜测增删改可见元素;确需调整先说明原因并取得确认。
- **IMPL-CORE-2** 随项目:架构/目录/命名/token/组件入口先**读当前工程**复用既有约定,不自创、不硬编码某套架构;新增公共抽象前先搜是否已有等价实现。
- **IMPL-CORE-3** 不绕检查:不得为过 `check_static.py` 等静态检查而生成只供匹配的辅助常量、隐藏 `Text`/`AssetImage`、`assert` 引用或无意义字面量;工具识别不了语义 token 时在验收里说明局限,不污染代码。

## STYLE 风格与命名
- **IMPL-STYLE-1** 两空格缩进。
- **IMPL-STYLE-2** 类/Widget `PascalCase`;方法/变量 `camelCase`;文件 `snake_case.dart`;标识符不得随意/临时/模糊。
- **IMPL-STYLE-3** 常量随现有 Dart 风格,仅编译期常量且项目已有约定才 `ALL_CAPS`。
- **IMPL-STYLE-4** `flutter_lints` + 更严:strict casts/inference、禁原始类型、**单引号**、**尾随逗号**、**显式返回类型**。
- **IMPL-STYLE-5** 验证先 `flutter analyze` 再测试。

## DOC 中文注释(不得敷衍)
- **IMPL-DOC-1** 中文注释;解释**为什么这样做 / 在保证什么**,不复述表面行为;新代码默认比现状更充分。
- **IMPL-DOC-2** 非显而易见逻辑必须注释;状态流转、跳转条件、落库语义、延迟执行原因必须说明。
- **IMPL-DOC-3** 单例/Provider/Repository/工具入口写设计意图;工具/拦截器/服务/协议封装等公共基础设施写:职责边界、调用顺序、失败策略、安全隐私边界、为何放该层;公共入口写参数含义、默认值语义、异常处理、调试注意、误用风险。
- **IMPL-DOC-4** 有约束含义的常量/key/标记位写用途。
- **IMPL-DOC-5** 注释不与代码冲突;改逻辑时失效注释同步更新。

## LAYER 分层
- **IMPL-LAYER-1** 展示与页面逻辑→`presentation/`;模型领域对象→`domain/`;mock→`data/`。
- **IMPL-LAYER-2** 公共组件只给视觉结构+必要事件入口,**不含**跳转/校验/提交等业务流程。

## LAYOUT 布局与响应式(核心)
- **IMPL-LAYOUT-1 关系换算优先**:尺寸/位置/间距一律用相对量——比例、`Flex`/`Expanded` 权重、对齐、`padding`、或"设计值 × 响应单位 `unit`"(`unit = LayoutBuilder.maxWidth / 设计宽度`);数值从精确 bbox 反算。设计尺寸下逐像素准,多屏按比例自适应。
- **IMPL-LAYOUT-2 禁硬编码**:禁止写死设计稿宽高、固定画布 `SizedBox`、`scale`/`_designWidth`/`_panelWidth`/`_panelHeight` 之类还原常量。**唯一允许的"坐标"是关系换算值(× unit 或 fraction),绝不允许裸像素硬编码。**
- **IMPL-LAYOUT-3 结构选择**:自然成行/列/栈的内容优先 `Column`/`Row`/`Flex`/`Wrap`+gap;仅当线性布局无法表达真实遮挡或复杂精确定位(如卡片角部装饰、复杂 artboard)才用 `Align`/`Stack`,且坐标用关系换算值。**简单页面(弹窗/表单/列表项)严禁 Stack 还原坐标。**
- **IMPL-LAYOUT-4 宽度自适应**:组件宽度交父级约束,不写死设计稿宽度;整行/整块容器(覆盖整行的 Rectangle)铺满父容器,不只包裹文本。
- **IMPL-LAYOUT-5 文字垂直关系**:`TextStyle` **禁加 `height`**;垂直关系靠父级布局/`padding`/间距/约束表达,避免跨平台字体裁切漂移。
- **IMPL-LAYOUT-6 像素级定义**:验收"像素级"指**元素/尺寸/层级/关系逐像素准**;字形边缘抗锯齿差属渲染引擎(Impeller≠Figma),不计缺陷,也不得为消除它牺牲响应式或写死坐标。

## HIER 视觉层级还原
- **IMPL-HIER-1** 不只看文字图层:同时查父级容器、同组图标、右侧箭头、背景框、边框、阴影。
- **IMPL-HIER-2** "文本+右侧箭头/图标"作为完整行组件实现,不漏右侧图标。
- **IMPL-HIER-3** 卡片内说明文本在 Flutter 中也放该卡片组件内部。

## COMP 组件拆分与公共组件
- **IMPL-COMP-1** 优先拆小组件、避免巨大 `build`;但单个简单控件(单 `Text`/`Icon`/`SizedBox`/单层装饰)默认不抽。
- **IMPL-COMP-2** 仅当有明确语义/复用价值/状态隔离/复杂布局/测试定位价值才抽;新建前先搜相似组件,有候选先说明复用代价。
- **IMPL-COMP-3** 多页面功能+视觉一致必须抽公共组件,不每页手写。
- **IMPL-COMP-4** 公共组件可暴露可覆盖参数但必须给业务默认值;调用点只传必需或与默认不同的参数;对外参数补中文注释(作用、默认值语义、何时覆盖、错配影响)。

## FORM 表单输入与选择
- **IMPL-FORM-1** 输入框与选择框职责拆开,不塞同一复杂组件。
- **IMPL-FORM-2 表单 = 坐标画布(框/标签)+ 真实输入控件(值)**:坐标画布(generate_canvas)负责并**只**负责输入框**边框 + 静态 label** 的可见像素(保真源);**输入的"值"是真实可编辑控件**,挂 `ValueKey('iff:<值节点id>')` 透明叠加在该值节点 bbox×u 上:
  - 文本输入用原生 `TextField`/`TextFormField`,但 **`InputDecoration` 必须折叠**(`border: InputBorder.none`、无 `labelText`/`filled`/`contentPadding` 复制),否则会和画布的框/标签**双重渲染**破坏 render_fidelity;**不包 `InkWell`/`GestureDetector` 模拟聚焦**。
  - 画布**仍按 render_plan 渲染该值节点**(展示同源设计值,作为设计/空态的保真像素);叠加的 `TextField` **显示真实输入值**(初值=同源设计值/接口回填),用户输入即可见。为避免双重渲染,输入控件给一个**与设计底色一致的不透明背景**盖住下方画布值像素(或聚焦/有内容时才覆盖);`check_render_fidelity` 与 trace 在设计/空态读到的就是设计值(画布 Text 或承载设计初值的 TextField,二者都=设计值,trace 已支持读 EditableText),保真通过。**不要求 generate_canvas 跳过值节点**(脚本无表单字段感知,不强求)。
  - 选择类(性别/证件类型/日期)用 tap 唤起 dialog/`showDatePicker`(picker-only),选中值同样回写到该值节点的展示控件。
  - 无设计值节点的字段(如某些占位输入),其输入控件直接渲染可见文本。
- **IMPL-FORM-3** 显示不全允许折行;输入时过滤换行符;长 label 优先浮动到边框。

## TOKEN 颜色与样式
- **IMPL-TOKEN-1** 不散落 `Color(0x..)`/`Colors.*`;复用色集中 `lib/src/core/theme/app_colors.dart` 按语义命名。
- **IMPL-TOKEN-2** 页面内不留只转发 token 的 `static const Color` 别名。
- **IMPL-TOKEN-3** 同链路一致样式统一,优先抽公共组件/token;迁移颜色查整条链路无遗漏。

## IMG 图片与图标
- **IMPL-IMG-1** 集中抽取复用;新增前先查等价资源,避免重复导入。
- **IMPL-IMG-2** 新增资源常量/管理入口先说明方案位置再实现。
- **IMPL-IMG-3** 缺失资源列清单(缺失项/影响/可选处理)待确认;不自行生成设计缺失图标;忽略系统状态栏等非产品切图。

## UNIT 单位换算
- **IMPL-UNIT-1** 代码与注释不留 `pt/px/dp/sp`。
- **IMPL-UNIT-2** 来源像素→**值 ÷2**;来源 pt/dp/sp→原值。
- **IMPL-UNIT-3** 注释解释数值设计意图/约束,不写"多少 px 来自设计稿"。

## ASSET 资源与运行时
- **IMPL-ASSET-1** 不提交构建产物。
- **IMPL-ASSET-2** 运行资源筛选后复制到 `assets/images/`、复用、在 `pubspec.yaml` 注册;运行时**禁**引用 `lanhu/` 中间产物、**禁**依赖远程设计图 URL。
- **IMPL-ASSET-3** 真实 API 前用本地资源+mock(mock 放 `data/`)。

## FLOW 申请链路
- **IMPL-FLOW-1** 申请 1/2/3、添加银行卡同链路,公共 Header/底部主按钮/表单字段/选择弹层复用公共组件。
- **IMPL-FLOW-2** 底部主按钮统一 `ApplicationBottomActionBar`(以申请 1 为基准),设计未变不单页重定义样式。
- **IMPL-FLOW-3** 颜色统一走 `AppColors`,不重定义相同色值。

## DIALOG 弹窗
- **IMPL-DIALOG-1** 相似弹窗一个入口参数化复用,不每图复制 `showXxxModal`。
- **IMPL-DIALOG-2** 结构 `showDialog -> Dialog(backgroundColor: Colors.transparent) -> 内容组件`;内容组件不再手写 `SafeArea+Center+viewport padding+LayoutBuilder` 外层画布。
- **IMPL-DIALOG-3** 根内容 `Column(mainAxisSize: MainAxisSize.min)`,高度自然撑开,禁按画布推导固定宽高/缩放;只留有设计意义 token。
- **IMPL-DIALOG-4** 图片优先 `Column`+`crossAxisAlignment`,真实遮挡才 `Stack`;图片 `BoxFit.contain` 不拉伸不参与缩放;卡片 `DecoratedBox`/`Container`+`Padding`,宽度交父级;按钮行 `Row`+`Expanded`+gap 等分。
- **IMPL-DIALOG-5** 按钮组件只封装视觉+点击;关闭顺序与跳转在入口/页面层组合。

## SHEET 底部弹框
- **IMPL-SHEET-1** 宽度自适应宿主;内容 `SingleChildScrollView`,固定按钮放固定 footer。
- **IMPL-SHEET-2** 按钮上方的协议/说明视为固定底部一部分,不放滚动末项;同底部背景包提示+按钮则同一 footer 容器。

## INFRA 工具/服务/仓库边界
- **IMPL-INFRA-1** 需新增复杂工具/helper/service/manager/公共入口前,先查既有并确认项目推荐入口,不直接发明抽象。
- **IMPL-INFRA-2** 本地存储 key 集中管理,不散落。
- **IMPL-INFRA-3** 持有连接/拦截器/缓存/全局状态的基础设施不每次临时创建;Provider/单例/统一入口复用,保留测试注入与 reset。

## CMPB 组件合成(Track B 上线页)
- **IMPL-CMPB-1** 上线页**可见层本体 = `generate_canvas` 产出的带 `ValueKey('iff:<节点id>')` 数据驱动坐标画布**(几何/样式由脚本从 `render_plan`/`tokens` 喂入);**不是静态 golden、不挂 preview 充数、不作"几何标尺"旁置**;严禁用 `Offstage` 把数据驱动组件藏起来,可见层必须真实挂在对应路由并随数据变化。
- **IMPL-CMPB-2** 共享视觉原语(按钮/金额/胶囊/header…)抽公共;按态卡片各自文件但内部**组合原语**,不复制视觉(C1 折中)。
- **IMPL-CMPB-3** 可见像素由 `generate_canvas` 脚本从 `render_plan`/`tokens` 喂入,**模型禁止手写 `Positioned`/颜色/圆角/字号或靠眼睛调**(调不对=脚本没喂进该值,**改 `generate_canvas.py` 不改 app**);模型只参数化数据/事件;保真由 `check_render_fidelity` 对**真实渲染 trace** 逐组件(bbox≤2px/主色 RGB≤3/字号·圆角≤1px/文案·token 100%/无缺节点)保证,**非 golden-vs-golden、非裸像素 SSIM**。
- **IMPL-CMPB-4** 组件 typed props + 业务默认值 + 中文注释(作用/默认值语义/何时覆盖/错配影响)。

## DATA 数据驱动槽位
- **IMPL-DATA-1** 动态槽 = 字段 + 变换 + 出现条件;来源 `data_slot_bindings.json`,`needsModelBinding` 每条须模型按交互规则确认(如 INT-010 `level_money`→`max_money` 回退)。
- **IMPL-DATA-1b 槽位广度(凡接口字段皆动态)**:`make_component_manifest` 的正则只自动标出数字/金额/日期类动态文本;**凡是取值来自 OAS 数据字段的可见文本——包括纯文本(产品名/标题/状态文案/问候语/姓名等)——都必须被确认为 `dynamic_text_slot`**(在 `component_manifest.json` 里 `confirmedByModel=true` 并补绑定),由 `generate_canvas` 走 `slotText` 注入。**只有真正的 UI chrome(按钮文案、分区标题、固定 copy)才保持静态字面量**。把接口数据字段(如卡片产品名、状态)当静态画死=数据未驱动,违反不变量④。
- **IMPL-DATA-2** 文本值走 DTO,不写字面量;格式化(₦千分位/日期/百分比)在领域层,组件只呈现。
- **IMPL-DATA-3** 动态槽**先钉死设计宽度**(暂不放宽 flex);变长真数据裁切的取舍验证后再定。

## API 接口对接
- **IMPL-API-1** DTO 由 Apifox 真 OAS codegen,字段以 OAS 为准,禁手搓与后端漂移。
- **IMPL-API-2** Repository 真 HTTP + mock **同源**(同 DTO 形);可注入单例(IMPL-INFRA-3),保留测试注入与 reset。
- **IMPL-API-3** 每个声明端点必须有 repo 调用点(`check_api_integration`);loading/error/empty/轮询/禁截图按交互规则接。

## WIRE 交互接线
- **IMPL-WIRE-1** 每条交互规则的领域逻辑必须接到**运行时调用点**(组件事件/页面编排/repository),不能只被测试引用(`check_interaction_wiring`)。
- **IMPL-WIRE-2** 组件只暴露视觉+事件入口;跳转/校验/链路编排在页面层(IMPL-LAYER-2)。
- **IMPL-WIRE-3** intent 携带链路所需参数(pid/catch_stage/route/notice),页面据此编排,不二次猜测。

## TEST 测试
- **IMPL-TEST-1** `flutter_test` 单元+组件测试,`*_test.dart`。
- **IMPL-TEST-2** 断言聚焦可观察行为。
- **IMPL-TEST-3** 改可见 UI/模型结构/mock 契约同步补改测试。
- **IMPL-TEST-4** 视觉关键分区补断言:整块容器宽度铺满、右侧图标存在、说明文本父组件归属。
- **IMPL-TEST-5** 优先定向测试,收尾/跨模块才大范围。

## DOCS 文档单一来源
- **IMPL-DOCS-1** `docs/` 单一事实来源;用户给的页面需求/交互/接口状态规则同步进 `docs/`,无文档则新建。
- **IMPL-DOCS-2** 交互/流程/接口/登录态只改 `docs/`;Lanhu spec 残留业务规则先迁 `docs/` 再删;详见 `docs/documentation_rules.md`、`docs/auth_session_flow.md`。

## VCS 提交与 PR
- **IMPL-VCS-1** 祈使句提交(如 `Add first loan home page`)。
- **IMPL-VCS-2** PR 含变更说明、验证命令、关联 issue/需求/设计稿;涉 UI 附截图。
