# Stage 3 — implementation

> 前置条件:模拟器采集回路可用(probe.py 能完成 启动→安装→截屏→dump视图树→退出,全程无人工)。

## 输入

Stage 2 全部冻结产物 + 目标仓库(分支基线哈希记录在案)。

| 文件 | 来源 | 用途 |
|---|---|---|
| enriched.json | Stage 1 | 组件结构 + 设计值(frame/text/fills) |
| component-binding.json | Stage 2 | 组件名/类型/参数/API/交互 |
| cover.png | Stage 1 | 视觉对照基准 |
| design.json meta | Stage 1 | artboard 元信息(width/height/scale) |
| assets/ | Stage 1 | 切图资产 |

## 不变量

- 不得新增交互原子;缺失 → `blocking_stage2_defect` 停止。
- 设计值不转换:蓝图保留设计稿原值,单位转换在代码生成时按平台策略执行。
- 无归因不重试:每次失败必须归类后才能修复或重试。
- 验证产物全部入档:截图、视图树、对照报告、归因账本。

## 流程

### Step 1: 蓝图提取 (脚本,确定性)

输入: enriched.json + design.json(meta)
产出: `layout-blueprint.json`

内容:
- artboard 元信息: width, height, scale (从 design.json meta.device 解析)
- 每个组件的布局意图: layout(column/row/stack), 从 frame 坐标推导
- 每个组件的约束: width(fill/fixed/wrap), 从 frame vs 父 frame 推导
- padding/spacing: 从相邻节点间距推导
- 设计值原样保留: frame, text.spans, fills — 不转换单位
- 资产清单: 需要图片的节点 + 对应 assets/ 文件名

不做: 不改数值,不选单位,不含平台语法。

记录:
- `blueprint_components`: 组件数
- `blueprint_texts`: 文案数
- `blueprint_assets`: 资产数
- `blueprint_layouts`: 推导出的布局类型分布 {column: N, row: N, stack: N}

### Step 2: 接口契约提取 (脚本,确定性)

输入: component-binding.json
产出: `api-contract.json`

内容:
- 每个 API：`resolved` 有值时为真实端点 (path/method/auth/request/response)；`resolved` 为 null 时标记 `mock: true`
- 每个组件的参数签名
- 交互原子列表: 点击→导航, 点击→API调用, 输入→状态绑定

数据策略 (Stage 2 的 `apis[].resolved` 决定 Stage 3 如何生成数据层):
- `resolved` 有值 + `deprecated: false` → Repository 用 `resolved.path`，DTO 字段按 `resolved.response` 映射
- `resolved` 有值 + `deprecated: true` → 优先用 `resolved.alternative`；无替代则标注废弃，Repository 仍用原路径
- `resolved: null` → `mock: true`，Repository 返回硬编码数据，DTO 字段从设计稿文案推断
- 无 API (纯 UI) → 不生成 Repository，组件参数由调用方传入

auth 映射 (`resolved.auth` → 项目 `AuthPolicy`，确定性映射):
- `"public"` → `AuthPolicy.PUBLIC`
- `"bearer"` → `AuthPolicy.REQUIRED`
- `"optional"` → `AuthPolicy.OPTIONAL`

不做: 不生成代码,不含平台语法。

记录:
- `contract_apis`: API 端点数 (resolved N / mock M)
- `contract_interactions`: 交互原子数
- `contract_components`: 组件数 (含 new/existing/platform_builtin 分布)

### Step 3: 代码生成 (模型)

输入: layout-blueprint.json + api-contract.json + 目标平台 + 项目结构
产出: 代码文件 (Screen/ViewModel/API 接口)

前置扫描 (模型在生成前必须完成):
- 读该 route 已有的全部实现(Screen/ViewModel/Repository/DTO),理解当前功能与结构;新页面此项为空
- 扫描目标项目的包结构,确定新文件放置路径
- 找到路由注册点 (NavGraph/Router),确定注册方式
- 找到网络层 (API client/Retrofit/Ktor),确定调用约定和 AuthPolicy 枚举
- 找到已有组件 (component_type=existing 的 source_path),确认接口
- 找到已有 Repository 实现,确认 DTO 风格和网络调用约定

模型的任务:
- 按平台选择单位转换策略 (设计值 → dp/sp 或 pt)
- 按蓝图布局意图翻译成平台代码
- 按接口契约生成数据层:
  - resolved API → Repository 类 + DTO data class，路径/字段/auth 严格按 `resolved` 的值
  - mock API → MockRepository 实现同一接口，返回与设计稿文案匹配的硬编码数据
  - 纯 UI → 不生成 Repository，组件参数由调用方直接传入
- 将代码文件写入项目 + 注册路由

约束: 不得新增交互原子;蓝图里没有的组件不生成。不得用批量脚本/模板替代模型逐页生成。

验证 (代码写入后立即执行,两个通道):

**确定性检查** (validate.py check-codegen):
```
validate.py check-codegen --blueprint layout-blueprint.json --contract api-contract.json --gen-dir <feature-dir> --platform <compose|swiftui|flutter|uikit|android-views>
```
2 项确定性检查:
- 文案覆盖: ≥80% 的 blueprint 文案出现在代码中 (含资源文件)
- DTO 覆盖: resolved API 的 response 字段在代码中有对应 DTO 属性 (snake_case 或 camelCase 均可)

**语义检查** (模型判断,读 blueprint + contract + 生成代码):
1. role→widget: blueprint 的 form/action/navigation/list/modal 角色在代码中有对应平台 widget
2. layout→布局: blueprint 的 row/stack 布局在代码中有对应平台布局组件
3. 组件分区: 多个非装饰组 → 代码中有对应数量的容器分区
4. API 覆盖: resolved API → ViewModel 通过 Repository 获取数据,Repository 请求路径字面值匹配 resolved.path,auth 匹配 resolved.auth; mock API → MockRepository 返回的硬编码数据与设计稿文案一致
5. 交互覆盖: contract 有交互 → 代码有平台对应的状态管理组件,且 UI 从 ViewModel/State 读取动态数据 (不硬编码 API 返回值)
6. 颜色覆盖: blueprint 色值在代码中有对应的颜色定义 (值匹配,非仅存在颜色 API)
7. 组件复用: component_type=existing_shared 的组件在代码中 import 了 source_path 的类; platform_builtin 使用了平台标准实现; extract_shared 创建了可复用组件

有问题 → 修代码 → 两个通道都重新执行,循环直到 ok。

记录:
- `gen_files`: 生成的文件列表 + 行数
- `gen_platform`: 目标平台 + 框架
- `gen_unit_strategy`: 使用的单位转换策略
- `gen_route_registered`: 路由是否已注册到 NavGraph
- `check_codegen_rounds`: check-codegen 验证轮数
- `check_codegen_errors`: 每轮错误 [{round, errors}]

### Step 4: 编译闸门 (确定性)

构建产物 (Android: APK, iOS: .app, Web: dist/)。编译错 → 修 → 重新构建,循环直到通过。

记录:
- `compile_rounds`: 编译修复轮数
- `compile_errors`: 每轮错误类型 + 数量 [{round, errors: [{type, message, file, line}]}]
- `compile_time_ms`: 每轮构建耗时

### Step 5: 渲染采集

安装 → 启动 → 导航到目标页 → dump 视图树 + 截图。
产出: `view_tree.xml` + `screenshot.png`

导航策略 (按平台):
- Android: deep link (`am start -a VIEW -d app://<route>`)
- iOS: deep link (`xcrun simctl openurl app://<route>`)
- Web: 直接导航到 URL path

导航失败 (目标页未渲染) 是 hard error, 不是 silent fallback — 归因为 environment 或 codegen,停止后续步骤。验证方法: 截图后检查视图树是否包含至少一条 blueprint 里的文案;如果 0 条匹配,判定为导航失败。

记录:
- `render_ok`: 是否成功渲染
- `render_time_ms`: 从安装到截图完成的耗时
- `render_view_nodes`: 视图树节点数

### Step 6: 逐组件对比 + 修复循环 (硬闸门)

输入: screenshot.png + cover.png + enriched.json + component-binding.json + layout-blueprint.json + api-contract.json + view_tree.xml
产出: `visual-diff.json` (工作日志) + 修复后的代码

**这是闭环验证步骤,不是观察步骤。** 按 Stage 2 的组件分解,逐个组件对比设计稿与渲染结果,发现差异 → 分析根因 → 修代码 → 重编译渲染 → 再次对比,循环直到所有组件在四个维度全部通过。

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
- 品牌 Logo 必须用图片资产或精确 Canvas 还原,不能用纯文本

通过标准: 所有图标存在 + 形状匹配

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
round = 0
while true:
    round += 1
    components = load(component-binding.json)

    all_diffs = []
    for comp in components:
        1. 定位 comp 在 cover.png 和 screenshot.png 中的区域
        2. 对该区域做四维检查
        3. 发现差异 → 记录到 all_diffs[], 标注所属组件

    4. 页面级检查: 组件间距、全局导航栏、整体布局
       差异 → 追加到 all_diffs[]

    5. 将 all_diffs 写入 visual-diff.json 当前轮
       每条: component, dimension, location, design, actual, severity, cause, fix, status

    6. 如果 0 差异 → pass = true, break

    7. 对每条差异做根因分析:
       - 什么导致了这个差异? (cause — 定位到代码逻辑)
       - 改哪个文件哪一行? (fix)
    8. 按分析结果修改代码
    9. 回 Step 4 → Step 5 → Step 6: 重编译 → 重渲染 → 重逐组件对比
    10. 下一轮检查上轮差异是否已消除,标记 status: fixed/open

    if round > 5:
        记录未收敛原因,停止
```

visual-diff.json 是模型的工作日志。模型每轮读上一轮记录,确认修复是否生效,发现新差异则追加。

#### 辅助工具: struct-diff (脚本预检)

每轮对比前先跑 struct_diff.py 做文案覆盖率快速检查:
```
struct_diff.py --view-tree view_tree.xml --blueprint layout-blueprint.json --output struct-diff.json --threshold 0.8
```
- 文案覆盖率 < 80% → 说明代码遗漏大量文案,优先修文案再做视觉对比
- struct-diff.json 的 missing 列表直接告诉模型缺了哪些文案

这是辅助定位工具,不是独立闸门。最终通过标准是逐组件四维检查全过。

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
          "cause": "Canvas drawLine 缺少 drawCircle 背景",
          "attribution": "codegen",
          "fix": "PayVisaScreen.kt:42 添加 drawCircle",
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

记录 (每轮追加到 `attribution-ledger.json`):
- `round`: 第几轮
- `component`: 组件名
- `dimension`: structure / icon / text / interaction
- `attribution`: codegen / environment / semantic
- `issue`: 差异描述 (设计稿 vs 实际)
- `cause`: 根本原因
- `fix`: 修复措施 (文件:行号)
- `files_changed`: 修改的文件列表

### Step 7: 行为验证

从 api-contract.json 的 interactions 列表逐条推导测试用例并执行:

#### 测试层级规则

每条 interaction 的 spec 描述了从 trigger 到 result 的链路,链路跨越几层,测试就必须覆盖几层。

层级判定 (确定性,从 interaction 的 trigger/behavior/result 文本机械推导):
1. 数 spec 中的 actor 边界: UI 组件、ViewModel/状态管理、Repository/数据层、系统服务/OS API
2. 跨越 ≥2 层 → 集成测试必选 (Activity 宿主 + 真实 ViewModel + 真实 Repository); 组件测试只作补充
3. 仅 1 层 (纯 UI 渲染/静态检查) → 组件测试即可

示例:
- "点击从通讯录中选择 → 校验姓名并规范+7号码 → 回填联系人" = UI→系统服务→ViewModel→UI = 4 层 → 集成测试
- "按钮 clickable=true" = 纯 UI = 1 层 → 组件测试

#### 测试用例推导

每条 interaction 产生正例和反例两类用例:

**正例** — 前置条件满足时,预期行为发生:
1. 每条 interaction 转为一个用例:
   - 前置: interaction.condition (null 则无前置)
   - 操作: interaction.trigger (点击/输入/滑动等设备交互)
   - 预期行为: interaction.behavior (UI 变化: 按钮禁用、loading 等)
   - 预期结果: interaction.result (状态变更/路由跳转/API 调用)
2. interaction.triggers 链构成多步场景 (ix_1→ix_2→ix_3),按链顺序依次执行
3. type=data 的 interaction 额外验证 (interaction.api 与 apis[] 按路径匹配,取 resolved 状态): resolved API → 代码中对该路径有网络调用; mock API (resolved=null) → 代码中有 MockRepository 返回对应数据
4. 生成 prompt 必须包含该 interaction 的实际代码调用链 (Screen→ViewModel→Repository→回填),不能只给 spec

**反例** — 前置条件缺失时,系统优雅处理而非崩溃:
1. 识别该 interaction 使用的框架 API 及其前置条件 (如 `rememberLauncherForActivityResult` 需要 `ActivityResultRegistryOwner`; 权限 API 需要授权状态; 网络请求需要连接)
2. 每个前置条件产生一个反例: 该条件不满足时,实现必须有明确的降级/错误处理路径,不得 crash
3. 反例断言: 系统显示错误提示 / 降级 UI / 保持可交互状态 (具体行为由实现决定,但必须非崩溃)

反例的前置条件来源按优先级:
- 框架 API 文档定义的 required 依赖 (如 CompositionLocal 的 Owner/Context)
- 平台运行时条件 (权限、网络、存储)
- interaction.condition 本身 (condition 不满足时的行为)

#### Mock 边界约束

不 mock 交互链路内的层。测试中的 mock/fake/注入遵循:

| 位置 | 允许 mock | 说明 |
|---|---|---|
| 交互链路内 (spec 的 trigger→result 经过的所有层) | 否 | 用真实实现; 若必须 fake 则配 contract test |
| 交互链路外端 (网络响应/OS 返回值/文件IO/硬件传感器) | 是 | mock 返回值与 api-contract 或文档一致 |

contract test: 同一组断言分别跑在 fake 和真实实现上,两边都过 fake 才合法。fake 与真实实现行为分叉时 contract test 失败,阻断交付。

#### 测试质量验证 (确定性,测试生成后执行)

测试代码写完后,执行 `test_lint.py` 静态检查,不合规则打回重写:

```bash
python3 scripts/test_lint.py <test_file_or_dir> --json
```

#### 合约驱动: 交互→模式→测试

每个交互绑定测试模式,模型按模式写测试,脚本按模式验证结构。

**交互→模式映射** (确定性,从 interaction 属性机械推导):

| 交互属性 | 绑定模式 | 最少用例数 |
|---|---|---|
| 所有交互 | `ui-interaction` | 1 |
| type=data (有 API) | + `value-assertion` | +1 |
| 有前置条件 / OS API 依赖 | + `error-handling` | +1 |

示例:
- 纯 UI 按钮 → 绑 `ui-interaction` → 1 个测试
- 点击登录 (调用 /auth/sessions) → 绑 `ui-interaction` + `value-assertion` → 至少 2 个测试
- 权限请求 (需 OS 权限) → 绑 `ui-interaction` + `error-handling` → 至少 2 个测试
- 提交表单 (调用 API + 需网络) → 绑 `ui-interaction` + `value-assertion` + `error-handling` → 至少 3 个测试

**有效模式 + 结构要求**:

| 模式 | 注解值 | 结构要求 | 指导 |
|---|---|---|---|
| UI 交互 | `ui-interaction` | UI 渲染 + 设备操作 + UI 状态断言 | 渲染组件 → tap/type → assertIsDisplayed |
| 值断言 | `value-assertion` | assertEquals/expect + 非 SUT 调用的 expected | expected 用字面量/构造器/枚举,不用 `vm.get()` |
| 异常处理 | `error-handling` | assertThrows/assertFailsWith + 异常类型 | 前置条件缺失 → 断言异常或降级 |
| 快照 | `snapshot` | 快照/golden 比对调用 | captureToImage + assertAgainstGolden |

每个测试必须声明 `// @test-pattern: <模式>`:
- 不标 → `unclassified` 打回
- 标了但结构不符 → `pattern-mismatch` 打回
- 选松的模式绕过 → 结构不符,打回

**反模式二次防线** (模式验证之外的额外检查):

| 模式 | 规则 | 违规示例 | 打回理由 |
|---|---|---|---|
| — | no-assertion | smoke test | "无断言" |
| A 回调绑定 | callback-counter/flag/capture/collect | `var x=0; x++; assertEquals(1,x)` | "验证回调副作用,不验证可观测状态" |
| B Mock 回声 | mock-assert / verify-only | `assertEquals(1, mockObj.c)` | "断言 mock 行为 / 仅验证调用" |
| D 烟雾断言 | weak-assertion | `assertNotNull(r)` | "仅检查存在" |
| E 实现耦合 | verify-order / verify-count | `verifyOrder { a(); b() }` | "耦合内部实现" |
| F 白名单 | no-device-action / no-ui-query | `setContent{};assertIsDisplayed()` | "未触发交互 / 未验证结果" |

**层级匹配** (模型自查,lint 不覆盖):
- ≥2 层的 interaction: 测试必须使用 Activity 宿主 (Compose: `createAndroidComposeRule<Activity>`; 非 `createComposeRule()`)
- 不合规 → 打回: "ix_N 跨 M 层,需要集成测试,当前是组件测试"

**链路内 mock** (模型自查,lint 不覆盖):
- interaction 链路内 (trigger→result 经过的层) 不 mock,只 mock 链路外端
- 不合规 → 打回: "ix_N 的 ViewModel 在链路内,不能用 lambda 替代"

lint 全部通过 + 模型自查通过后,进入执行阶段。

#### 验证方法

| 交互类型 | 操作 | 正例断言 |
|---|---|---|
| 按钮可点击 | 无 (静态检查) | 视图树中 clickable=true / accessible |
| 点击→导航 | 设备 tap 触发按钮 | dump 视图树,当前 route 切换到预期页面 |
| 点击→API调用 (resolved) | 设备 tap 触发按钮 | 日志中出现对 interaction.api 路径的网络请求 |
| 点击→API调用 (mock) | 设备 tap 触发按钮 | ViewModel 状态更新 (mock 无网络请求,验证 UI 数据变化) |
| 表单输入 | 设备输入文本 | dump 视图树,输入框 text 属性包含输入值 |
| 状态变化 | 执行 trigger 操作 | dump 前后视图树,UI 变化匹配 interaction.behavior |

反例验证: 注入前置条件缺失状态 → 执行操作 → 断言应用未崩溃 + 显示降级/错误 UI。

每个用例: 执行操作 → 采集实际结果 → 与预期比对 → 记录 pass/fail。

失败 → 归因 → 修 → 回 Step 4 重编译渲染。

产出 `behavior-result.json`:
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
| struct-diff.json | Step 6 辅助预检报告 (文案覆盖率) |
| visual-diff.json | Step 6 逐组件四维验证工作日志 (含每轮差异+修复记录) |
| attribution-ledger.json | Step 6-7 归因账本 |
| behavior-result.json | Step 7 交互验证结果 |
| stage3-metrics.json | 全流程指标汇总 |

## stage3-metrics.json

汇总所有步骤的记录项,一个页面一份。用于跨页面横向对比。

```json
{
  "title": "单期还款",
  "platform": "android",
  "timestamp": "...",
  "step1_blueprint": { "blueprint_components": 5, "blueprint_texts": 11 },
  "step2_contract": { "contract_apis": 1, "contract_interactions": 1 },
  "step3": { "gen_files": ["..."], "gen_platform": "android/compose" },
  "step4": { "compile_rounds": 2, "compile_errors": ["..."] },
  "step5_probe": { "render_ok": true, "render_view_nodes": 28 },
  "step6_struct_diff": { "matched": 11, "total": 11, "missing": [] },
  "step7_visual_diff": {
    "visual_pass": true,
    "visual_issues": []
  },
  "step8_attribution": { "total_rounds": 2, "attributions": {"codegen": 3, "environment": 1} },
  "step9_behavior": { "behavior_total": 3, "positive_passed": 2, "negative_passed": 1, "mock_violations": 0, "quality_rewrites": 0 }
}
```

## 复盘数据点

| 指标 | 来源 | 优化信号 |
|---|---|---|
| 编译修复轮数 | step4.compile_rounds | 高 → 代码生成 prompt/约束需改进 |
| 编译错误类型分布 | step4.compile_errors | 集中在某类 → 针对性加 prompt 约束 |
| 文案覆盖率 | step6_struct_diff.matched | 低 → 蓝图提取或代码生成遗漏文案 |
| 视觉修复轮数 | step7_visual_diff | visual_issues 多 → 初次生成与设计稿还原能力弱 |
| 归因分布 | step8_attribution.attributions | codegen 占比高 → 代码生成 prompt 需改进 |
| 严重度分布 | step6.by_severity | critical 多 → 结构性缺陷; major 多 → 需针对性改进 |
| 正例通过率 | step9.positive_passed/total | 低 → 交互实现能力或接口契约质量 |
| 反例通过率 | step9.negative_passed/total | 低 → 缺少前置条件缺失时的降级处理 |
| mock 违规数 | step9.mock_violations | >0 → 测试绕过了框架边界,有效性不可信 |
| 测试重写次数 | step9.quality_rewrites | 高 → 模型首次生成的测试层级/断言质量不达标 |
| 单页总耗时 | timestamp diff | 基线,跨页面对比 |

## 交付

mr=0 仅本地产物;mr=1 提交分支;mr=2 开 MR。默认从 mr=0 开始,升档由 IOLE 控制。
