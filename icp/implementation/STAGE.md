# Stage 3 — implementation

> 前置条件：目标平台有可用的构建、测试和渲染采集入口。相同工具链与配置首次使用时验证一次能力；失败定位到具体入口，不在每个页面重复搭建或调试宿主。

## 输入

Stage 2 全部冻结产物 + 目标仓库(分支基线哈希记录在案)。

| 文件 | 来源 | 用途 |
|---|---|---|
| enriched.json | Stage 1 | 组件结构 + 设计值(frame/text/fills) |
| component-binding.json | Stage 2 | 组件名/类型/参数/API/交互 |
| cover.png | Stage 1 | 视觉对照基准 |
| design.json meta | Stage 1 | artboard 元信息(width/height/scale) |
| assets/ | Stage 1 | 切图资产 |
| slices.json | Stage 1 | 切图资产清单 (id→file 映射) |

## 不变量

- 不得新增交互原子;缺失 → `blocking_stage2_defect` 停止。
- 设计值不转换:蓝图保留设计稿原值,单位转换在代码生成时按平台策略执行。
- 无归因不重试:每次失败必须归类后才能修复或重试。
- 验证产物全部入档:截图、视图树、对照报告、归因账本。

## 验收分工与证据复用

开始实现前，在已有 checklist 中将源交互及用户补充要求映射到用例、验收层级和责任节点；记录预期结果、禁止副作用及需覆盖的真实调用边界，不新增一套重复台账。任务中新增或澄清的要求同步更新该映射；收尾时核对当前约定，不能只用初始源表或旧用例集全绿判定完成。复用未失效证据，只补受影响的缺口。

| 层级 | 验收责任 |
|---|---|
| 页面 | 本页渲染由设计稿比对验收；交互实现阶段以真实业务代码测试验证状态、参数、接口调用与错误恢复，最后 Step 7 再验证真实页面操作与接线，不能用空回调或只记录配置代替实现 |
| 共享能力 | 公共网络、鉴权、语言、超时和系统能力适配的合同；页面仍验证自己的接入与结果 |
| 功能树 | 真实父子入口、跨页状态、回边和共享配置接线；每个跨页缺口指定责任节点 |

每条需求必须有归属和有效证据。父页未实现时，验证子页自身的公开输入输出合同，并把真实父子连接留给对应集成用例；不为通过验收制造假父页。单页独立任务仍须完成其全部约定范围。

接口功能实现与真实服务联调分开：实现阶段按正式合同完成请求/响应、鉴权与语言传递、页面状态和成功/失败回调，并接入可配置的服务器地址及会话来源；用本地 HTTP 夹具等外部边界替代验证实际自有调用链。真实地址或测试账号未就绪时不阻塞这些实现，不猜地址、不伪造真实服务成功；未配置地址时按下节实现正式 shape 的模拟响应及自动切换，不用配置缺失提示替代默认要求。不能将固定空地址/空令牌、空回调或仅记录观察值当作已完成接线。经用户约定，真实服务测试可待地址与账号接入后集中执行；在现有 checklist 分别记录功能实现、本地验证和真实服务联调，注明待验前提与范围。仅缺已批准延后的真实服务联调，不判为功能未实现；仍缺必要代码、接线或本地证据则保留实现缺口，不能把本地通过称为真实服务通过。

渲染、截图、多尺寸与共享回归可在功能树阶段集中执行以复用构建和设备，但必须保留每个页面所需的检查及证据。默认仍完成本页视觉检查；只有执行范围明确分配给功能树的项目才可延后。页面通过不代表功能树通过，延后项目未验收前不得宣称全链路完成或执行交付 Git 写操作。

复用证据须注明需求/用例、测试标识、源码快照（含未提交改动）、合同/依赖版本、配置、设备或视口、结果与路径。相关输入变化则失效并重验受影响部分；无关文件变化不触发全量重验。同一有效运行可同时证明 RED、根因或回归，不为报告或不同阶段重复运行。

交互实现阶段只做代码测试，禁止为此启动模拟器、真机、页面 UI 自动化或设备测试宿主。测试执行真实自有业务链路，时钟/网络/OS 等外部边界可按 TDD 规则替代；不能替代正在验证的业务决策。真实页面操作仅在设计稿比对通过后的最后 Step 7 执行，不把代码通过称为页面操作或真实服务通过。

### 接口数据渲染与数据源切换

对依赖接口数据的页面，未配置实际地址时默认按已核实的 Apifox shape 提供模拟响应，并将该默认要求纳入现有输入及验收映射；用户明确排除时记录其决定。正式合同缺失（`resolved: null`）仍是合同缺口，不能猜测 DTO 或生成模拟响应来冒充完成。业务数据统一经过接口响应解析 → Repository/状态层 → 页面字段绑定，模拟响应只替代外部服务边界，不在 View 或状态层硬编码金额、列表、联系人等业务值，也不另写一套模拟页面。固定标题、按钮和法定静态内容仍按需求使用资源文案。

复用现有配置与网络入口做最小选择：实际地址未配置时走模拟响应；地址配置后自动使用真实请求与当前会话，无需修改页面、DTO 或再手动切换 mock 开关。必须鉴权的真实请求仍需有效会话；地址无效、缺令牌、请求失败或成功返回空数据均走各自约定状态，不能回退模拟数据掩盖问题。模拟行为不产生真实上传、删除等外部副作用，也不得记作真实服务成功。

本地验证须证明：未配置地址时模拟响应经过真实解析并显示在实际页面；配置地址后请求到达受控 HTTP 服务，返回字段变化会改变页面内容；页面所用字段的映射、必要格式化及空值处理符合合同；失败/空结果不混入模拟数据。复用有效证据，只补缺口，不仅断言工厂选中了某个类型。现有 checklist 记录字段绑定、当前数据来源、自动切换证据及真实服务待验范围，不新增重复台账或通用数据源框架。

## 流程

### Step 1: 蓝图提取 (脚本,确定性)

输入: enriched.json + design.json(meta) + slices.json
产出: `layout-blueprint.json`
命令:
```
blueprint.py --enriched enriched.json --design design.json --slices slices.json --output layout-blueprint.json
```

内容:
- artboard 元信息: width, height, scale (从 design.json meta.device 解析)
- 每个组件的布局意图: layout(column/row/stack), 从 frame 坐标推导
- 每个组件的约束: width(fill/fixed), 从 frame vs 父 frame 推导
- padding/spacing: 从相邻节点间距推导
- 设计值原样保留: container frame(供 spacing/padding 推导)、首个 text span 的 style、填充值；不转换单位，text 不保留 frame。多层填充以 `fill.layers` / `child_fills[*].layers` 的完整顺序为准，外层字段仅兼容原首层摘要。渐变保留 `from` / `to` / `transform`，坐标可能超出 0–1；不得仅凭 stops 顺序猜方向。旧产物缺少这些字段时从冻结 design 经 bind/clean/enrich/blueprint 重提取，不猜值或重新抓取整份设计。
- 资产清单: 来自 slices.json (设计师标记导出的节点,仅含有本地文件的条目); 祖先已导出时子孙不重复列出; 每项含 id, name, file(assets/ 相对路径,相对于 Stage 1 out-dir), resource_name(平台资源名); 可选 size

不做: 不改数值,不选单位,不含平台语法。

记录:
- `blueprint_components`: 组件数
- `blueprint_texts`: 文案数
- `blueprint_assets`: 资产数
- `blueprint_layouts`: 推导出的布局类型分布 {column: N, row: N, stack: N}

### Step 2: 接口契约提取 (脚本,确定性)

输入: component-binding.json
产出: `api-contract.json`
命令:
```
contract.py --binding component-binding.json --output api-contract.json
```

内容:
- 每个 API：`resolved` 有值时为真实端点 (path/method/auth/request/response)；当前脚本在 `resolved` 为 null 时标记 `mock: true`，该历史标记不代表用户授权 mock，也不证明接口完成
- 每个组件的参数签名
- 交互列表: 直接透传 Stage 2 component-binding.json 的 `interactions[]` (type: behavior/data),不做合成

数据策略 (Stage 2 的 `apis[].resolved` 决定 Stage 3 如何生成数据层):
- `resolved` 有值 + `deprecated: false` → Repository 用 `resolved.path`，DTO 字段按 `resolved.response` 映射
- `resolved` 有值 + `deprecated: true` → 优先用 `resolved.alternative`；无替代则标注废弃，Repository 仍用原路径
- `resolved: null` → 按 Stage 2 记录合同缺口，不凭设计稿推断 DTO 或默认生成硬编码 Repository；仅用户明确要求原型/mock 时才使用替代
- 无 API (纯 UI) → 不生成 Repository，组件参数由调用方传入

auth 映射 (`resolved.auth` → 项目 `AuthPolicy`，确定性映射):
- `"public"` → `AuthPolicy.PUBLIC`
- `"bearer"` → `AuthPolicy.REQUIRED`
- `"optional"` → `AuthPolicy.OPTIONAL`

不做: 不生成代码,不含平台语法。

记录:
- `contract_apis`: API 端点总数; `contract_apis_resolved`: resolved 数; `contract_apis_mock`: mock 数
- `contract_interactions`: 交互原子数
- `contract_components`: 组件数 (含 new/existing_shared/extract_shared/platform_builtin 分布)

### Step 3: 代码生成 (模型)

输入: layout-blueprint.json + api-contract.json + 目标平台 + 项目结构
产出: 代码文件 (Screen/ViewModel/API 接口)

实现顺序固定为以下三段，不交替执行：

1. **先 UI**：依据 Stage 1/2 的蓝图、组件、资源和完整页面状态，一次性完整实现 UI。可分多次补丁，但不拆成“写一个控件就测试一次”；UI 不写、不运行单元/集成测试，也不提前启动点击、截图或设计稿比对循环。
2. **再交互**：UI 完成后，按 Step 7 从源交互描述拆解用例，实现行为、接口、埋点、接线与数据绑定及对应代码测试。验收覆盖完整接口 shape（含不直接显示的合同字段）和条件分支。业务代码选用 TDD 时按 `../../tdd/SKILL.md` 逐用例 RED→实现→GREEN；UI 不属于此 TDD 范围。交互测试仅使用非设备代码测试入口，禁止模拟器、真机及 UI 自动化。编译失败或零执行不算 RED，已有行为如实记录 EXISTING_GREEN。
3. **最后统一核验**：UI、交互实现和对应代码测试完成后，依次执行 Step 4 编译、Step 5 渲染、Step 6 设计稿比对；确认代码用例全部通过且 UI 比对通过后，最后集中启动一次 Step 7 真实页面操作验收。模拟器/设备在前面的实现阶段禁用于测试，在后段仅用于渲染比对和最后页面操作。复用相同源码和配置的有效代码测试结果，缺陷修复后重验受影响范围；设计稿比对遵守 Step 6 的最多 5 轮规则，不把该上限误用于业务 TDD 的 RED/GREEN 次数。

前置扫描 (生成前完成；已有带版本的有效调查直接复用，只补变化或缺失信息):
- 读该 route 已有的全部实现(Screen/ViewModel/Repository/DTO),理解当前功能与结构;新页面此项为空
- 扫描目标项目的包结构,确定新文件放置路径
- 找到路由注册点 (NavGraph/Router),确定注册方式
- 找到网络层 (API client/Retrofit/Ktor),确定调用约定和 AuthPolicy 枚举
- 找到已有组件 (component_type=existing_shared 的 source_path),确认接口
- 找到已有 Repository 实现,确认 DTO 风格和网络调用约定

模型的任务:
- 按平台选择单位转换策略 (设计值 → dp/sp 或 pt)
- 按蓝图布局意图翻译成平台代码
- 按接口契约生成数据层:
  - resolved API → Repository 类 + DTO data class，路径/字段/auth 严格按 `resolved` 的值
  - 同时读取 Stage 2 保存的完整 Apifox shape，按实际 Content-Type、参数位置、required/nullable、成功/错误状态码及包裹层实现；本地 HTTP 夹具和预期断言由该合同推导，不从待测代码反推
  - 正式 API 的未配置地址展示需求 → 按「接口数据渲染与数据源切换」在外部服务边界提供模拟响应，复用真实 Repository/DTO/页面链；本地 HTTP 夹具通过不等于应用已具备此数据源切换
  - 仅为原型批准的 mock API → MockRepository 只服务该原型范围，不计为正式接口实现或真实服务联调完成
  - 纯 UI → 不生成 Repository，组件参数由调用方直接传入
- 将代码文件写入项目 + 注册路由

约束: 不得新增交互原子;蓝图里没有的组件不生成。不得用批量脚本/模板替代模型逐页生成。

#### 组件类型规则

按 component_type 分支处理:

| component_type | 生成策略 | 关键约束 |
|---|---|---|
| `existing_shared` | `import source_path` 的类,按 params 传参调用 | 不重新实现;source_path 文件必须存在 |
| `extract_shared` | 在共享目录创建可复用组件,affected 列表中的组件改为引用它 | 必须创建独立文件;affected 组件必须同步修改 |
| `platform_builtin` | 使用平台标准组件 (NavigationBar/TextField 等) | 不自行实现平台已提供的功能 |
| `new` | 从 blueprint 布局+样式全新实现 | 按蓝图结构和布局约束生成 |

#### 布局翻译规则

blueprint 的 layout/spacing/padding 表达元素间的结构关系,代码必须用布局组件实现,禁止用绝对坐标模拟:

| blueprint 信号 | Compose | Flutter | SwiftUI | 禁止 |
|---|---|---|---|---|
| layout: column + spacing | Column(verticalArrangement = spacedBy(N.dp)) | Column + SizedBox(height: N) | VStack(spacing: N) | offset(y=) |
| layout: row + spacing | Row(horizontalArrangement = spacedBy(N.dp)) | Row + SizedBox(width: N) | HStack(spacing: N) | offset(x=) |
| padding | Modifier.padding(...) | EdgeInsets | .padding(...) | offset 模拟 padding |
| width: fill | Modifier.fillMaxWidth() | double.infinity / Expanded | .frame(maxWidth: .infinity) | 固定像素宽 |
| width: fixed | Modifier.width(N.dp) | SizedBox(width: N) | .frame(width: N) | fillMaxWidth |
| children_widths | 子元素各自的 fill/fixed 信号,相对于所在容器推导 | 同 width: fill/fixed 规则 | 同 width: fill/fixed 规则 | 照抄像素宽 |

等比例 offset(引用 maxWidth/maxHeight 的约束计算)允许,如 `offset(y = maxHeight * ratio)`。

#### 图标实现规则

blueprint 的 assets[] 每项代表一个设计师标记导出的图标/图片资产 (祖先已导出时子孙不重复列出; 含文本子孙的节点不作为图片资产):

| 情况 | 做法 |
|---|---|
| blueprint assets[] 有对应条目 | 将 file 复制到项目资源目录,以 resource_name 命名,用平台图片 API 引用 |
| 无 asset,语义可识别的标准 UI 图标 (返回/关闭/删除/添加/搜索/设置/勾选等) | 用平台标准图标库 (Material Icons / SF Symbols / Flutter Icons) |
| 无 asset,非标准图标 | 停机,不得继续 |

平台资源部署 (file 为 PNG/JPG 时):
- Compose: `res/drawable/<resource_name>.png` + `painterResource(R.drawable.<resource_name>)`
- Flutter: `assets/images/<resource_name>.png` + `Image.asset(...)`,在 `pubspec.yaml` 注册 assets
- SwiftUI: `Assets.xcassets/<resource_name>` + `Image("<resource_name>")`

file 为 SVG 时:
- Compose: 先转为 Vector Drawable XML 存入 `res/drawable/` + `painterResource(R.drawable.<resource_name>)`
- Flutter: `assets/images/<resource_name>.svg` + `flutter_svg` 包的 `SvgPicture.asset(...)`
- SwiftUI: `Assets.xcassets/` (勾选 Preserve Vector Data) + `Image("<resource_name>")`

**禁止**: 用 Canvas / Path / drawLine / drawRect 等绘制 API 手绘图标。任何情况都不允许。

验证 (针对当前已实现范围执行；页面结束时覆盖完整合同，两个通道):

**确定性检查** (validate.py check-codegen):
```
validate.py check-codegen --blueprint layout-blueprint.json --contract api-contract.json --gen-dir <feature-dir> --platform <compose|swiftui|flutter|uikit|android-views>
```
5 项确定性检查:
- 文案覆盖: ≥80% 的 blueprint 文案出现在代码中 (含资源文件)
- DTO 覆盖: resolved API 的 response 字段在代码中有对应 DTO 属性 (snake_case 或 camelCase 均可)
- 资产覆盖: blueprint 的 assets 中有 `file` 字段的条目,其 `resource_name` 必须出现在代码中 (含资源文件)
- extract_shared 引用: extract_shared 的 affected 组件名必须出现在生成代码中 (warning)
- 绝对定位检测: 检查 offset/absoluteOffset (compose)、Positioned/AnimatedPositioned/PositionedDirectional/AnimatedPositionedDirectional/PositionedTransition 及其命名构造器 (.directional/.fromRect/.fromRelativeRect) + Transform.translate (flutter)、.offset/.position (swiftui); 两层豁免: 文件级——文件包含响应式作用域标记 (compose: BoxWithConstraints; flutter: LayoutBuilder; swiftui: GeometryReader) 则跳过整个文件; 行级——offset 所在行+4行窗口内包含比例信号 (compose: maxWidth/maxHeight; flutter: constraints.属性访问; swiftui: geometry) 则跳过; 注释与字符串内不计

**语义检查** (模型判断,读 blueprint + contract + 生成代码):
1. role→widget: blueprint 的 form/action/navigation/list/modal 角色在代码中有对应平台 widget
2. layout→布局: blueprint 的 row/stack 布局在代码中有对应平台布局组件
3. 组件分区: 多个非装饰组 → 代码中有对应数量的容器分区
4. API 覆盖: resolved API → ViewModel 通过 Repository 获取数据，核对最终请求路径与前缀、method、auth、Content-Type、参数及响应/错误处理符合完整 Apifox shape；仅字面值或 DTO 字段存在不证明合同满足。mock API 仅验收用户批准的原型范围，不算真实接口通过
5. 交互覆盖: contract 有交互 → 代码有平台对应的状态管理组件,且 UI 从 ViewModel/State 读取动态数据 (不硬编码 API 返回值)
6. 样式绑定: 当前组件的字体、填充叠层、渐变方向与资产按冻结值实际绑定；不能仅有颜色定义，或先用默认控件样式占位再把已知差异留到验收。缺少值先核对上游产物，不猜色；最终仍须真实渲染对比。
7. 组件复用: component_type=existing_shared 的组件在代码中 import 了 source_path 的类; platform_builtin 使用了平台标准实现; extract_shared 创建了可复用组件

文案检查仅在比较时做 Unicode NFC 规范化，不改源文案，也不忽略大小写、标点或缺字；该覆盖率检查仍是启发式，不能替代逐字与渲染验收。有问题先区分真实缺陷与检查器局限。完成整页实现后统一检查；真实缺陷修复后重跑受影响检查，不因单次补丁重跑整页验收。动态文案、资源别名等疑似误报必须给出合同依据、实际绑定与运行证据；保留原始失败结果，在 checklist 逐项记录替代证据和裁定。不通过改业务文案、复制资源或修改测试来迎合字符串匹配，也不把未证实的误报直接忽略。

记录:
- `gen_files`: 生成的文件列表 + 行数
- `gen_platform`: 目标平台 + 框架
- `gen_unit_strategy`: 使用的单位转换策略
- `gen_route_registered`: 路由是否已注册到 NavGraph
- `check_codegen_rounds`: check-codegen 验证轮数
- `check_codegen_errors`: 每轮错误 [{round, errors}]

### Step 4: 编译闸门 (确定性)

构建产物 (Android: APK, iOS: .app, Web: dist/)。编译错 → 修 → 重新构建,循环直到通过。

复用项目已有 runner、增量缓存及运行中的设备。测试命令已成功构建相同源码、依赖、配置的所需产物时，不再额外构建；否则执行所需构建。源码、目标或构建配置变更后禁止沿用不匹配产物。新增测试先核对公开接口、语言/并发约束和真实 selector；项目支持低成本编译检查时优先使用，不额外要求一轮完整构建。

记录:
- `compile_rounds`: 编译修复轮数
- `compile_errors`: 每轮错误类型 + 数量 [{round, errors: [{type, message, file, line}]}]
- `compile_time_ms`: 每轮构建耗时

### Step 5: 渲染采集

安装 → 启动 → 导航到目标页 → 采集可观测结构与截图。已有真实 UI 测试的采集结果若覆盖相同页面、状态与构建，直接复用，不再单独跑 probe。
产出: `view_tree.xml` + `screenshot.png`，或带明确路径的等价结构断言与截图证据。
命令:
```
probe.py --project <project-root> --out-dir <dir> --package <pkg> --target <android|ios|web> [--route <route>] [--blueprint layout-blueprint.json] [--device <name>] [--serial <id>] [--skip-build] [--skip-boot] [--keep-device]
```

Step 4 产物确认与本次输入一致时，使用 `--skip-build`；已启动设备且具备使用权时配合 `--skip-boot --keep-device`。这些参数不校验产物新鲜度，也不提供设备锁，调用方仍须核实。运行完释放资源使用权，设备是否关闭遵循项目约定。

导航策略 (按平台):
- Android: deep link (`am start -a VIEW -d app://<route>`)
- iOS: deep link (`xcrun simctl openurl app://<route>`)
- Web: 直接导航到 URL path

目标页必须由独有标识/状态、实际路由和渲染证据确认。probe 当前用至少一条 blueprint 文案匹配作启发式检查：公共文案命中不证明到达，视图树缺失也不直接证明业务导航失败。工具不能暴露结构时记录原始结果，使用平台公开的语义断言、真实操作与截图证明同一合同；不得跳过到达验证。实际未到达或无可靠替代证据时，停止后续视觉验收并定位原因。

记录:
- `render_ok`: 是否成功渲染
- `render_time_ms`: 从安装到截图完成的耗时
- `render_view_nodes`: 视图树节点数

### Step 6: 逐组件对比 + 修复循环 (硬闸门)

输入: screenshot.png + cover.png + enriched.json + component-binding.json + layout-blueprint.json + api-contract.json + view_tree.xml（或 Step 5 已核实的等价结构证据）
产出: `visual-diff.json` (工作日志) + 修复后的代码

**最多 5 轮完整比对，包括首次比对和修复后的复核。** 每轮按 Stage 2 的组件分解检查所有组件、四个维度及页面级问题，汇总全部差异后再集中分析和修复；不能发现一个差异就中断扫描、修复并重启。复核仍完整扫描，既确认旧差异消除，也查找新增差异。只有完整检查且零差异才通过；达到 5 轮仍有差异则保持未通过。

#### 对比粒度: 逐组件

不是拿整张截图与整张设计稿做一次大 diff。而是:

1. 从 component-binding.json 取组件列表 (Stage 2 已分解)
2. 每个组件在 enriched.json 中有 frame (x, y, width, height)
3. 对每个组件:
   a. 在 cover.png 中定位该组件区域 (用 enriched.json frame + artboard scale)
   b. 在 screenshot.png 中定位对应区域 (用 view_tree.xml bounds 或坐标映射)
   c. 对该组件区域做四维检查
4. 额外检查: 页面级问题 (整体布局、组件间距、全局导航栏)

好处:
- 精确定位: 每个差异归属到具体组件
- 高效: 模型聚焦小区域,不遗漏细节
- 利用 Stage 2: 组件分解已完成,不重复劳动

#### 四维检查 (每个组件)

**维度 1: 结构**
- 该组件在截图中是否存在
- 定位方式是否正确 (弹窗: BottomSheet vs Dialog 必须与设计稿一致)
- 内部子元素层级是否正确
- 滚动内容: 如该组件在 LazyColumn 中且不可见 → 滚动截图或滚动 dump,不能跳过

- 容器背景色/填充: 与设计稿一致 (blueprint child_fills/fill 的色值)

通过标准: 组件存在 + 层级正确 + 定位正确 + 填充色正确

**维度 2: 图标**
- 该组件内的每个图标是否存在
- 形状是否与设计稿一致 (不能用方块/圆点/emoji 近似)
- 实现方式: 必须用导出资产 (Image/painterResource) 或平台标准图标库 (Material Icons / SF Symbols),不得用 Canvas/Path 手绘

通过标准: 所有图标存在 + 形状匹配 + 实现方式正确

**维度 3: 文案**
- 该组件内的每条文案是否与设计稿逐字一致
- 文本样式: 下划线/加粗/颜色 必须与设计稿一致
- 动态数据 (API 返回) 必须有 mock 值,不能空白
- hint/placeholder 文案必须一致

通过标准: 文案内容正确 + 样式正确 + 动态数据有 mock 值

**维度 4: 交互元素**
- 该组件内的按钮/链接/输入框/选择器是否存在且类型正确
- 控件样式: Slider/Checkbox/Switch 外观必须与设计稿匹配,不能用 Material 默认样式了事

通过标准: 交互元素存在 + 类型正确 + 样式匹配

#### 验证流程

```
for round in 本页尚未执行的轮次（1..5）:
    components = load(component-binding.json)

    all_diffs = []
    for comp in components:
        1. 定位 comp 在 cover.png 和 screenshot.png 中的区域
        2. 对该区域做四维检查
        3. 发现差异 → 记录到 all_diffs[], 标注所属组件

    4. 页面级检查: 组件间距、全局导航栏、整体布局
       差异 → 追加到 all_diffs[]

    5. 确认所有组件、所需页面状态/视口及页面级四维检查完整
       不可见组件须滚动采集；无法可靠观测的项目记为未验证，不能算零差异
       将全部 all_diffs 与未验证项写入 visual-diff.json 当前轮
       每条: component, dimension, location, design, actual, severity, cause, fix, status

    6. 如果检查完整且 0 差异 → pass = true, break
       如果 round == 5 → pass = false，保留 issues_remaining 与未验证项，停止本页比对循环

    7. 对每条差异做根因分析:
       - 什么导致了这个差异? (cause — 定位到代码逻辑)
       - 改哪个文件哪一行? (fix)
    8. 集中修复本轮完整清单中的差异，不修一个就重启一轮
    9. 回 Step 4 → Step 5 → Step 6: 重编译 → 重渲染 → 重逐组件对比
    10. 下一轮检查上轮差异是否已消除,标记 status: fixed/open

```

第 5 轮未通过时，记录剩余差异、未收敛原因和证据，本页保持未通过，不进行第 6 轮，也不通过重启会话、换执行者或修改观测方法重置轮数。继续其他可独立推进的工作；本页追加比对须由用户另行调整上限。

visual-diff.json 是模型的工作日志。模型每轮读上一轮记录,确认修复是否生效,发现新差异则追加。

#### 辅助工具: struct-diff (脚本预检)

已有可解析视图树时，在首次对比及相关结构/文案变化后跑 struct_diff.py 做覆盖率预检；同版本输入复用结果。若工具无法读取结构，按 Step 5 记录替代证据，不伪造视图树来满足脚本：
```
struct_diff.py --view-tree view_tree.xml --blueprint layout-blueprint.json --output struct-diff.json --threshold 0.8
```

gate 通过条件 (三项全满足):
1. 文案覆盖率 ≥ threshold (默认 0.8)
2. 层级顺序正确 (struct_hierarchy_ok)
3. 至少有内容 (expected_texts > 0 或 comp_matched > 0)

注意: component_coverage 在 gate 输出中但仅供参考,不参与 ok 判定。

- struct-diff.json 的 missing 列表直接告诉模型缺了哪些文案

这是辅助定位工具,不是独立闸门。最终通过标准是逐组件四维检查全过；80% 文案覆盖率不能作为允许遗漏其余文案的依据。

#### 差异记录格式

每条差异包含:
- `component`: 所属组件名 (来自 component-binding.json)
- `dimension`: structure / icon / text / interaction
- `location`: 在组件内的位置 (如"关闭按钮"、"第3行文案")
- `design`: 设计稿中是什么 (具体描述)
- `actual`: 实际渲染是什么 (具体描述)
- `severity`: critical / major / minor
  - critical: 组件缺失、图标完全错误、文案内容错误
  - major: 样式明显不符 (下划线缺失、图标形状偏差大)
  - minor: 间距微调、圆角差异
- `cause`: 根本原因 (如 "代码使用 Dialog 而设计稿是 BottomSheet")
- `attribution`: codegen / environment / semantic
- `fix`: 修复措施 (文件:行号, 改什么)
- `status`: open / fixed

#### 归因分类

- `codegen`: 生成代码错 (图标形状错、文案样式缺、组件类型选错) → 修代码,回 Step 4
- `environment`: 物理上无法在模拟器中重现的差异 → 调整渲染策略 (滚动拼接、注入 mock)
- `semantic`: spec 本身错 → 回 Stage 1/2,停止

**禁止**: 将 codegen 问题归因为 environment。图标缺失是 codegen,文案样式错是 codegen。

产出 `visual-diff.json`:
```json
{
  "pass": true,
  "total_rounds": 2,
  "rounds": [
    {
      "round": 1,
      "diffs": [
        {
          "id": "d1",
          "component": "header",
          "dimension": "icon",
          "location": "关闭按钮",
          "design": "圆形深绿背景 + 白色X线条",
          "actual": "无背景 + 绿色X线条",
          "severity": "major",
          "cause": "未使用导出资产,手绘了关闭按钮图标",
          "attribution": "codegen",
          "fix": "PayVisaScreen.kt:42 改用 Image(painterResource(R.drawable.icon_close))",
          "status": "fixed"
        }
      ],
      "summary": {
        "total": 3,
        "by_dimension": {"structure": 0, "icon": 2, "text": 1, "interaction": 0},
        "by_severity": {"critical": 0, "major": 2, "minor": 1}
      }
    }
  ],
  "issues_remaining": []
}
```

记录 (每轮追加到 `attribution-ledger.json`): 文件顶层是记录对象数组，如 `[{"round": 1, "attribution": "codegen"}]`，各记录补齐下列字段，无记录时写 `[]`；不要套用上方 `visual-diff.json` 的 `{"rounds": [...]}` 外层。`metrics.py` 直接遍历此数组，同轮多条记录共用 round，分别计入归因数量。
- `round`: 第几轮
- `component`: 组件名
- `dimension`: structure / icon / text / interaction
- `attribution`: codegen / environment / semantic
- `issue`: 差异描述 (设计稿 vs 实际)
- `cause`: 根本原因
- `fix`: 修复措施 (文件:行号)
- `files_changed`: 修改的文件列表

### Step 7: 最后执行真实页面操作验收

本节的用例推导与代码测试规则在 Step 3 的 UI 完成后、交互实现前使用。真实页面操作必须同时满足两个前提：当前实现的代码用例全部通过，Step 6 的 UI 设计稿比对通过。然后集中启动一次完整页面验收，在同一验收批次按既有交互用例验证实际点击、输入、导航、恢复与接线；不逐个用例反复启动验收，不重新拆解需求或重复已有有效代码测试。所需操作全部通过后汇总证据并收尾；发现失败则保留具体缺口，修复后只做必要的受影响复验，不重启整套验收，也不把“一次启动”当作跳过失败的理由。

首次启动最终验收前，依据已有源要求映射一次核对整个验收批次：各需求分支均有对应场景和实际页面效果的关键断言，不能用业务状态通过代替页面绑定验证，也不能用元素存在代替所需的可见、可操作结果；核对夹具的完整前置条件，并在场景内先确认实际起始状态再执行操作。发现遗漏先补齐本批次用例，不等运行后再做覆盖补查。此处只复用既有映射与证据，不新增台账、不提前启动页面操作、不重复有效代码测试；这是模型的覆盖审核，不是新增的自动门禁。

#### 测试层级规则

UI 不做单元/集成测试，外观由 Step 5-6 渲染比对验收。交互实现阶段通过非设备代码测试验证真实业务入口的状态变化、导航意图及参数、请求/响应、持久化、埋点和禁止副作用；业务跨层使用真实实现，不 mock 自有链路。最后的真实页面操作单独验证 UI 是否实际调用这些入口及显示正确结果，不能提前混入代码 TDD。

各平台的交互代码测试统一使用可直接执行受测业务代码的非设备入口。现有测试 target 只能依赖模拟器/App 设备宿主时，不能继续使用它执行交互代码测试；优先复用现有非设备入口，缺失时明确记录入口缺口，不通过复制业务实现、shadow 类型或 mock 自有代码伪造通过。最后的真实页面操作使用相应平台的实际页面及可靠操作工具；这属于最终验收，不是 UI 单元/集成测试。

#### 测试用例推导

先将源交互列表逐条与实现及测试对照，覆盖每条描述中的行为、接口、埋点及其条件分支，不能只检查解析后的 interactions[] 而漏掉提取时丢失的要求。在现有 checklist/用例映射中记录源条目或 ID → 实现入口 → 测试标识/关键断言 → 实际执行结果与证据路径；一条描述含多项义务时分别核对。允许一个实际场景证明多个需求，不按条目数量机械增加重复测试；每项都须有能检出相应错误的有效用例，不能只比较需求数与测试数。未实现、无有效用例、未执行或证据失效分别记录为质量缺口；无法自动测试时记录替代验证及剩余缺口，不计为自动测试已覆盖。

- 行为：从适当的实际入口触发，断言页面/状态/导航/持久化结果及禁止副作用，不能只证明回调存在。
- 接口：按正式 shape 验证请求、响应处理和接口字段驱动的页面结果，包含适用的模拟响应/真实请求切换；遵循上文「接口数据渲染与数据源切换」。
- 埋点：按明确的事件合同验证触发时机、事件名、参数来源与值、次数/顺序及不应上报的分支。通过真实业务入口在上报边界捕获事件，不能 mock 掉正在验证的埋点决策，也不向真实分析平台发送测试事件。未定义事件名或字段时记录合同缺口，不自行发明；源要求没有埋点则不新增。

各用例还须明确：

- 来源与输入：冻结需求、condition、trigger、起始状态及夹具值。
- 正例：精确的输出、状态变化、路由或请求/响应处理，以及禁止的副作用。网络日志出现一个路径只能证明调用发生，不能证明字段、鉴权和响应处理正确。
- 反例与边界：覆盖需求及相关平台前置条件缺失、错误恢复、顺序/生命周期等实际风险；断言预期降级结果及禁止副作用，不仅断言不崩溃。预期来自合同，不能由当前实现决定。
- 缺陷敏感性：记录用例要检出的具体错误；复用已有有效用例，不为凑数量制造 RED。
- 交接包含当前实际调用链的必要信息或已有调查路径；不重复抄录整页源码。

#### Mock 边界约束

不 mock 被验证的自有业务链路。替代只放在系统所有权边界外（外部网络服务、时钟、OS/硬件等），返回值须符合正式合同。fake 不能实现正在验证的业务，也不能代替要求真实平台交互的证据；TDD 选定时同时遵守其边界规则。

#### 静态检查与有效证据

测试代码写完后，批量对本次新增/修改文件执行现有检查，保存原始结果：

```bash
python3 scripts/test_lint.py <test_file_or_dir> --json
```

`@test-pattern` 可声明 `ui-interaction`、`value-assertion`、`error-handling` 或 `snapshot`，按实际测试性质选择；只截图不能标为 golden 比对。缺标注先补准确标注，不为每种模式另写重复测试。

lint 是启发式检查，不是编译器或测试执行器。无断言、仅 mock 回声、弱断言、绕开自有链路等真实质量问题必须修复。工具不识别公开宿主或 helper 断言时，只检查相关调用与断言是否实际执行、是否能检出缺陷；记录具体误报、对应源码/运行证据及裁定。未证实前不能豁免；也不能为了 lint 全绿把正确测试改成无效结构。

#### 运行与失败处理

复用项目现有测试入口；首次复用时确认它不只透传进程退出码：由代码读取原生测试结果，核对实际执行的目标与数量，零测试、所选目标未执行或结果不完整均不得报验证成功。用已有失败/成功记录验证该判断；多 target / 嵌套 suite 按独立测试结果计数，不取最后一条汇总或累加父子汇总。缺失时只补现有入口的结果校验，不新建通用 runner。保留原始退出码与校验结论，业务断言失败仍交模型判定是否为有效 RED；不声称 skill 已自动提供次数限制或资源锁。

1. 补丁成功落地、测试已注册到目标且 selector 核对通过后才运行；任何前置失败都停止后续命令，不能分号串接后盲目继续。确认所需夹具、资源使用权及证据输出目录；测试发现命令不可用时核对真实方法名，并在结果中确认实际执行。
2. 每个运行请求只执行一次。长运行用原生等待/完成通知，原始日志落盘，只返回当前用例、源码版本、命令/selector、构建结果、实际执行/通过/失败/跳过数、退出码、耗时和证据路径。
3. 编译/发现/夹具/环境失败与业务断言失败分开；退出码 0 或构建成功不等于测试执行。零测试、选错用例、缺少目标断言均不能算 RED/GREEN。
4. 只有目标业务断言因缺失/错误行为失败才是有效 RED；纯观测失败先修验证入口，不据此修改业务。GREEN 须核实当前用例及受影响回归真实通过，要求的用例不得跳过。
5. 失败先定位原因与最小下一步，再发起一次有理由的修复/运行；worker 不自行扩展到其他验收或无依据重跑。同一原因重复出现时检查假设与观测通道，不仅增加等待或重试次数。
6. 改动后只重跑受影响检查；仅影响行为不强制重做全部视觉，仅影响布局也不自动重测所有网络用例。必要的完整回归在页面/功能树的既定验收点执行，不因“最后再确认一次”重复已有效的同范围运行。

从已有实际执行结果汇总 `behavior-result.json`，复用同一有效证据，不为汇总重新运行。正、负分组互斥，同一测试只计一次；分组 total/passed 之和须等于总数。IOLE 完成入口读取此既有报告，缺失、零执行、未全过或计数不一致时拒绝 done；表格写回前使用同一入口的 `--check`。报告不替代源要求映射、原始结果与当前源码的关联核对，不将静态文件存在或手填计数称为实际验证。

结构示例（含失败，不能用于标记 done）:
```json
{
  "behavior_total": 5,
  "behavior_passed": 4,
  "positive": {"total": 3, "passed": 2, "failed": [
    {"interaction": "ix_1", "trigger": "点击发送验证码", "expected": "按钮禁用+loading", "actual": "按钮未变化", "attribution": "codegen"}
  ]},
  "negative": {"total": 2, "passed": 2, "failed": []},
  "mock_violations": [],
  "quality_check": {"lint_violations": 0, "level_mismatches": 0, "chain_mocks": 0, "rewrites": 0}
}
```

## 产出文件

| 文件 | 说明 |
|---|---|
| 代码文件 | 平台对应的 UI/状态管理文件 |
| layout-blueprint.json | Step 1 蓝图 |
| api-contract.json | Step 2 接口契约 |
| screenshot.png | Step 5 渲染截图 |
| view_tree.xml | Step 5 视图树 |
| probe-result.json | Step 5 渲染采集结构化结果 |
| struct-diff.json | Step 6 辅助预检报告 (文案覆盖率) |
| visual-diff.json | Step 6 逐组件四维验证工作日志 (含每轮差异+修复记录) |
| attribution-ledger.json | Step 6-7 归因账本 |
| behavior-result.json | Step 7 交互验证结果 |
| stage3-metrics.json | 全流程指标汇总 |

## 指标与工具限制

正常页面使用既有产物汇总 `stage3-metrics.json`。字段说明、示例与按工具分类的已知限制见 [REFERENCE.md](REFERENCE.md)，仅在汇总或相关诊断时读取。计数不能替代需求覆盖映射，已知限制不能自动免除真实验收。

## 交付

mr=0 仅本地产物;mr=1 提交分支;mr=2 开 MR。默认从 mr=0 开始,升档由 IOLE 控制。
