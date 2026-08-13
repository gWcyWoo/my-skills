# ICP P3 PlatformPackage 架构方案（Codex 修订稿；后续只使用 GLM explore/code）

状态：仅架构草案；禁止实现、禁止激活、禁止修改 `iff/**`。

## 1. 结论

P3 首个切片选择“薄 PlatformPackage 数据契约”，不先激活 Flutter，也不直接开始 Vue 代码生成。

原因：当前七个平台的生产 registry 均为 `activated=false`（`icp/references/registries.json:16,23,28,33,38,43,48`）；support gate 之后的生产 preflight 仍只返回平台名（`icp/scripts/preflight_selection.py:446-451`）。直接激活 Flutter 会让 claim 路径先开放，但没有一个完成的平台包分发/总编排闭环。直接实现 Vue 又会在接口未固定前复制 Flutter 的目录与安全机制。P3a 因此只定义平台包“描述什么”，不共享平台业务实现。

## 2. 公共入口和参数

继续使用一个 `$icp` 入口和现有严格 run-config：

```json
{
  "task_source": "csv",
  "task_ref": "...",
  "design_source": "lanhu-figma",
  "platform": "flutter|vue|nextjs|ios-swift|ios-objc|android-java|android-kotlin",
  "profile": "受 registry 控制的 profile，可省略时仅使用受控默认值",
  "project_root": "..."
}
```

不得增加 `command`、`script`、`argv`、`env`、`shell`、`runner`、`prompt`、任意模块路径或任意 adapter 路径。`platform/profile` 只能选择内部 registry 与固定 PlatformPackage resolver 已登记的组合。

### Skill 入口的 EntryReadinessGate

`$icp` 的第一段必须是短时、fail-closed 的入口检查，不能立即 claim、创建 worker 或开始长时间设计解析/代码生成。它先收集五个选择轴及其 locator：`task_source/task_ref`、`design_source`（以及候选行中的 design locator）、`platform`、`profile`、`project_root`；再组合 TaskSource、DesignSource 和已验证 PlatformPackage 声明的固定 requirements。

入口输出 canonical `icp.entry-readiness-report.v1`：

```text
status = needs-user-input | blocked | no-work | ready
resolved_config_digest
package_descriptor_digest
task_source_snapshot_digest
candidate_identity_digest
checks[] = {id, owner, status = pass | missing | blocked | deferred, evidence_digest}
missing_user_inputs[] = {id, reason_code, accepted_shape_id, secure_supply_channel, sensitive}
deferred_checks[] = {id, blocked_by}
blockers[] = {code, scope, evidence_digest, remediation_id}
```

`needs-user-input` 必须按稳定顺序一次列出当前能够确定的全部缺项；`reason_code`、`accepted_shape_id`、`secure_supply_channel`、`remediation_id` 都是内部受控 ID，面向用户的说明由 SKILL 固定模板渲染，不能把来源文本直接注入报告/prompt。不得回显 credential/token/secret 值，只能要求用户通过受控 credential slot 或明确文件/URL/ID 补充。若缺少 `platform` 等上游选择而无法判断后续平台需求，必须显式列出 `deferred_checks`，用户补充后从头重跑全部 gate，不能续用旧报告。

`blocked` 用于 unsupported platform/profile、缺失工具链/浏览器/simulator/device、目录权限/原子写能力或不可访问的来源；不得把这些伪装成已支持。`no-work` 表示当前没有可认领候选行，是成功的无任务终态，不创建 run root、不 claim、不启动 worker，也不能伪装为 `ready`。`ready` 必须证明候选行的必填字段、TaskSource 锁/同目录原子替换能力、DesignSource credential/locator/read access、project root、平台 toolchain/test/runtime target 和所有 required ports 当前可用。原子能力探测只能在 TaskSource 同目录的受控临时命名空间内创建/替换探测文件，必须验证清理完成；清理失败即 `blocked`。绝不触碰真实表格内容或行状态。

只在 `ready` 后才允许进入 manifest/claim/worker。claim 后禁止请求用户输入或无限等待；可预见的授权、签名、设备、浏览器、凭据与安装要求必须在入口解决，运行中出现不可预见故障则按 claim ack 自动 `doing -> error` 并保存诊断/恢复证据。入口检查不能保证外部设备或网络在长任务中永不失效，但必须消除所有当时可确定的交互依赖。

## 3. 完整执行时序

最终激活后的顺序必须是：

1. strict-decode 核心选择轴；缺项时生成 `needs-user-input`，不接触来源；
2. resolve run-config；support/package/capability gate 先验证非空 registry profile/default profile 与确定性 run-root 推导，再由固定 resolver 选择 `(platform, profile)` 的 PlatformPackage；不支持时在任何 TaskSource access/manifest/claim 前 fail closed；
3. 从固定 TaskSource、DesignSource 与 PlatformPackage descriptor 合并 requirements；registry 不得提供 probe command；
4. 只读选择候选行并运行入口 probes：TaskSource snapshot/schema/锁与原子写能力、候选行必填数据、DesignSource locator/credential/read access、project root、平台 project/toolchain/test/runtime target；不改变行状态；
5. 聚合 `needs-user-input` / `blocked` / `no-work` / `ready`；前三者给出受控模板报告并停止且零 run/claim/worker 副作用，用户补充后从步骤 1 重跑；`ready` 时立即复验易变条件；
6. 对同一 TaskSource snapshot/candidate identities 冻结现有 `icp.selection_manifest.v1`，保持其 schema 不变；snapshot 漂移则丢弃 readiness 并从步骤 1 重跑；
7. 在 run root 原子、不可覆盖地发布 ready-only `entry-readiness.v1.json`，绑定 selection manifest path/digest 与全部非敏感 evidence digests；
8. 重新验证同一 package，并原子、不可覆盖地发布 `platform-package-selection.v1.json`，绑定 entry-readiness、selection manifest、registry/profile、package index/descriptor/verification digests，以及固定 readiness/resolver/freezer/verifier 的有序 `producer_script_digests`；发布失败时仍未 claim；
9. CSV CAS 原子 claim：空状态 -> `doing`；从此禁止任何等待用户输入的分支；
10. 只为成功 claim 的行导出输入；
11. DesignSource `fetch_normalize` 并验证 canonical design bundle；
12. 从 row exports + design bundle 构建并验证共享 requirement/interaction/API/data/visual contracts；
13. 逐画板/feature 并行 fan-out：worker compliance -> RED -> 平台 codegen -> 资产/字体/依赖 packaging -> GREEN -> 平台项目门禁；
14. 生成平台 runtime trace；
15. 从真实 browser/simulator/device 取得 actual screenshot 和 provenance；reference/design screenshot 永远不能作为 actual；
16. visual diff；最多一个受控 repair budget，修复后重新经过完整门禁；
17. done gate；
18. 平台提供确定性 fan-in plan，shared orchestrator 串行执行、复验 receipts；
19. 只有完成证据全部成立才 CAS `doing -> done`；任何失败按同一 claim ack CAS `doing -> error`，不得提前回写；运行中不可预见的缺失依赖不得挂起等待用户。

当前原子 claim 已由 `csv_task_source.claim` 提供（`icp/scripts/csv_task_source.py:306`），生产 orchestration 中 support gate 位于 claim 之前（`icp/scripts/prepare_selection.py:162,245`）。此顺序不可逆转。若 selection manifest 已冻结但 adjacent artifact 发布失败，允许留下未 claim、不可复用的 orphan run root；不得删除后重用同一 batch/run identity。

## 4. 依赖方向

```text
RunConfig
  -> TaskSource / DesignSource
  -> Shared artifact contracts
  -> ICP orchestrator
  -> fixed PlatformPackage resolver
  -> one platform package
  -> platform project/toolchain/runtime
```

规则：

- `shared_core/` 不得 import `platforms/`、vendor capsule 或项目工具链。
- PlatformPackage 可以消费 shared artifacts，但不得反向定义 TaskSource/DesignSource 语义。
- orchestrator 只依赖 PlatformPackage 数据契约和公开角色，不依赖 Flutter/Dart/Vue/Swift/Gradle 细节。
- 平台包不得读取 registry 中的命令；registry 永远是纯数据。

目录保持增量式，不移动现有脚本：

```text
icp/
  scripts/
    task_sources/                 # TaskSource primitives/wrappers
    design_sources/               # DesignSource facades
    shared_core/                  # pure schemas/serializers only
    platforms/
      platform_package_contract_v1.py
      flutter_package_v1.py
      vue_package_v1.py           # later P3b2
      vue_standard_v1.py
      vue_project_preflight_v1.py
      vue_operations_v1.py
      ... existing platform-owned modules remain in place
      families/                   # only after two real adapters prove reuse
    entry_readiness_v1.py         # later P3b1, aggregate/probe/report contract
    platform_package_resolver_v1.py   # later P3b1, fixed mapping
    freeze_platform_package_selection_v1.py # later P3b1, not wired into production yet
    verify_platform_package_selection_v1.py
    orchestrate_client_project_v1.py # later P3d
    ... existing orchestration files remain in place
  vendor/iff_v1/                  # frozen compatibility capsule
  references/
    entry-readiness-v1.md         # detailed source/platform check matrix
    platform_packages_v1.json     # fixed package module basename/SHA index
    ... registries, baselines, approved architecture
```

不得为了目录美观移动现有扁平模块。新 family 目录只有在两个真实平台实现证明相同语义后才能创建。

## 5. 三个边界

### TaskSource

固定语义：`describe_requirements/probe_readiness/select_candidates/claim/export_inputs/writeback`。CSV 是当前实现；入口 probe 必须验证 schema、候选行必填字段、锁和同目录临时原子替换能力但不得改变行状态。claim/writeback 必须保持 CAS、flock、同目录原子替换、claim ack 绑定。以后新增 Excel/服务型 TaskSource 只能实现相同 readiness + 状态机，不能绕过它。

### DesignSource

固定语义：`describe_requirements/resolve/probe_readiness/fetch_normalize/verify_bundle`。入口 probe 只验证受控 credential slot、locator 形状、read access 与候选设计资源存在性，不回显 secret，也不把完整 normalize 当作入口长任务。当前 Lanhu/Figma facade 的生产入口为 `fetch_normalize`（`icp/scripts/design_sources/lanhu_figma_v1.py:963`）。DesignSource 产出 canonical design bundle，不产出 Dart、Vue SFC、Swift 或 Android View。

### PlatformPackage

P3a 新增纯数据 descriptor：

```text
kind = icp.platform-package-descriptor.v1
schema_version = 1
platform_id
profile_id
activation_state = inactive
executable = false
registry_digest
selected_profile_digest
supported_task_sources[]
supported_design_sources[]
actual_source_types[]
entry_requirements[] = {
  id,
  owner = user | source | environment | platform,
  required,
  sensitive,
  probe_id,
  accepted_shape_id,
  remediation_id
}
components[] = {
  role,
  module_basename,
  module_sha256,
  contract_kind,
  public_api[]
}
ports[] = {
  id,
  capability_state,
  implementation_state,
  provider_component_role,
  artifact_contracts[]
}
```

`profile_id` 在 v1 中必须是非空字符串，不允许 `null`。当前只有 Flutter/Vue 同时具备 registry profile 与 run-root 推导；Next.js、iOS 和 Android 的 adapter 工作开始前，必须先以单独、用户批准的 registry diff 增加至少一个 profile/default profile，并在 `freeze_selection_manifest.py` 增加确定性 `_PLATFORM_ROOTS` 映射及 verifier/selftest。缺一项就不允许生成 package descriptor，也不允许 TaskSource access/manifest/claim；不通过把 `profile_id` 改成 nullable 绕过。

组件角色固定为：`descriptor`、`project_preflight`、`operation_plans`、`binding`、`authorization`、`executor`。runtime capture、test runner、fan-in 通过九个 operation ports 描述，不强迫它们各自成为独立 Python 模块。

`ports[].implementation_state` 的 v1 受控值只有 `implemented` 与 `not-implemented`；它不复用 P2c descriptor 的 `legacy-mapped` / `new-port-required` 历史迁移状态。Flutter package 中已有真实模块的 `project_preflight` 必须标为 `implemented`，但不得改写冻结的 P2c descriptor。

`entry_requirements` 只能声明受控 requirement/probe/accepted-shape/remediation ID；用户说明由固定模板生成。不得包含自由文本命令、任意路径、任意 env 名或 secret。probe 实现必须来自已验证 package 的固定 `project_preflight` 组件。平台所需的 SDK、test runner、browser/simulator/device、签名或权限必须在这里声明，使 skill 能在用户离场前完成检查。

共享 validator 只验证形状、ID、顺序、固定目录内的 basename/SHA、受控状态值和禁止字段；`contract_kind` 是平台所有的版本化标识，不能假设所有平台都返回 Flutter 的 object kind。P3a package-level 验证只对 descriptor 调用现有 `verify_descriptor()`；其余五个 request-scoped 组件执行 fixed-root containment、regular-file/no-symlink、live SHA-256、basename、预期 public entrypoint 的静态 AST 校验，不调用需要 project/plan/binding/authorization 参数的深层 verifier。深层语义验证继续由现有 binding -> authorization -> executor 请求链负责。

`supported_task_sources` / `supported_design_sources` 必须是当前内部 registry 的受控 ID，不能携带 locator、路径或命令；`actual_source_types` 只能取 shared policy 的受控枚举（如 `browser_screenshot`、`simulator_screenshot`、`emulator_screenshot`、`physical_device_screenshot`），明确禁止 `reference`、`design_image` 等来源。`verify_package` 必须重算当前 registry/profile digest 并要求相等。验证报告另外产生 canonical `package_digest`，descriptor 本身不保存自引用 digest。

P3a 公开 API 仅为：

```python
describe_package() -> dict
verify_package() -> dict
```

无 CLI、无动态路径、无 subprocess、无 import-time I/O、无 activation override。模块只允许从自身安装位置下固定 `icp/scripts/platforms/` 解析组件 basename 并重算 SHA。

当前 Flutter 已有可包装的六层公开接口：descriptor `describe`（`flutter_standard_v1.py:705`）、project preflight（`flutter_project_preflight_v1.py:887`）、operation `build`（`flutter_operations_v1.py:4625`）、binding（`flutter_execution_binding_v1.py:595`）、authorization（`flutter_execution_authorization_v1.py:873`）、executor（`flutter_execution_executor_v1.py:1908`）。P3a 只能引用和验证它们，不能改写或抽取其实现。

## 6. Shared artifacts 与平台 artifacts

### 平台无关

- resolved run-config；
- selection manifest + verifier（当前 verifier 入口 `verify_selection_manifest_v1.py:783`）；
- ready-only adjacent `entry-readiness.v1`：绑定 selection manifest/config/package/source snapshot/candidate identities、稳定排序的 checks 与非敏感 evidence digests；`needs-user-input`/`blocked`/`no-work` 只返回给入口，不发布可执行 run artifact；
- adjacent `platform-package-selection.v1`：不修改 selection manifest v1；绑定 entry-readiness、manifest、registry/profile、固定 package index、package descriptor/verification digests，以及 `entry_readiness_v1.py`、`platform_package_resolver_v1.py`、`freeze_platform_package_selection_v1.py`、`verify_platform_package_selection_v1.py` 的固定相对路径与有序 SHA-256，并采用原子 no-clobber 发布；
- claim ack、row export；
- canonical design bundle：raw/spec/reference manifest/scene/tokens/assets/classification/provenance；
- requirement contract、interaction contract、API contract、data contract、visual/responsive contract；这些来自 row exports + verified design bundle，不来自平台代码；
- worker compliance envelope：至少绑定 platform/profile、operation port、selection manifest digest、row identity、design bundle digest、allowed output roots、required artifact contract IDs；不得携带自由命令；
- expected/slots projection 的纯 schema/serializer（当前 `build_projection_bytes`：`shared_core/expected_slots_projection_v1.py:534`）；
- merged-expectation provenance 的纯 schema；
- RuntimeTrace envelope：只统一 platform/profile、trace kind、source artifact digests、node-id mapping digest、trace payload digest；payload schema由平台拥有；
- VisualEvidence envelope：绑定 reference digest、actual digest、actual source kind、runtime target/build/viewport digests、diff report digest；actual source kind 必须是受控 `browser_screenshot` / `simulator_screenshot` / `emulator_screenshot` / `physical_device_screenshot` capture class。这四个枚举值允许出现在 shared contract；它们不是平台工具或命令名；
- repair budget、completion evidence、done/writeback 时序的共享字段。

注意：共享 schema 不等于所有平台必须运行 iFF merge。expected/slots projection 与 merged provenance 可由 capability 协商启用；Flutter 的 legacy bytes、merge producer、Dart trace consumer 都不自动成为跨平台语义。

adjacent artifact 的 producer digests 在发布时从固定安装位置重算，后续 binding 在加载 verifier 前先拒绝 symlink/path escape 并直接比对 verifier SHA，再由 verifier 重算全部 producer digests。该机制只冻结“manifest/package selection 完成后到 claim/execute”的身份，不能证明冻结前本机安装目录未被预先篡改；冻结前安装目录继续沿用现有 selection manifest 的本地信任边界，不把 self-attestation 描述成供应链认证。

### 平台所有

- project scaffolding 与 toolchain preflight；
- codegen IR 到 Flutter/Vue/Swift/ObjC/Java/Kotlin 的转换；
- dependency/assets/fonts packaging；
- UT/IT 命令与测试框架；
- runtime trace 的实现（Dart layout trace、DOM trace、native view trace）；
- browser/simulator/device 选择、启动、截图命令；
- project gates；
- fan-in 的具体 mutation plan；
- 平台专属 binding/authorization/executor，直到至少两个真实平台证明可以安全抽取共同机制。

Flutter P2.5d 的三步 trace 只属于 Flutter：`_TRACE_STEPS_SPEC` 位于 `flutter_operations_v1.py:275`，且具体步骤为 frozen merge、Flutter provenance gate、frozen Dart trace consumer（同文件 `:282,299,320`）。不得将它重命名为通用 RuntimeTrace。

## 7. 能力协商与激活

沿用九个 port：`project_preflight`、`visible_codegen`、`fixture_codegen`、`trace_harness`、`packaging`、`test_runner`、`runtime_capture`、`project_gates`、`fan_in`。

每个平台 package 必须声明每个 port 的 `capability_state` 与 `implementation_state`。激活条件：

1. registry 有非空 profile/default profile，run-root 推导与 manifest verifier 已实现并通过测试；
2. `entry_requirements` 完整，`needs-user-input`/`blocked`/`no-work` 时对 manifest/claim/worker 的零副作用测试通过，ready artifact 能被后续链复验；
3. 所有 `required` port 的 `implementation_state=implemented`；
4. `optional-with-shared-policy` 有实现或明确的 shared fallback policy；
5. descriptor、preflight、plan、binding、authorization、executor 全链验证；
6. 真实项目端到端通过；
7. runtime screenshot provenance 与 visual diff 通过；
8. claim/writeback 时序通过竞争测试；
9. 旧 iFF 与 ICP Flutter parity 完全通过；
10. 单独的 registry activation diff 经用户批准。

因此 activation 必须是后续独立阶段。任何 `activated=true` 被接受前，生产 support gate 必须已经调用固定 resolver 和 `verify_package`，并在 TaskSource 打开前验证 package、输入源兼容性和 required ports。P3a/P3b/P3c 不修改 `activated=false`。

## 8. Worker prompt 注入

shared orchestrator 从已验证 package descriptor 生成 canonical `platform_context.json`，内容只允许：platform/profile IDs、entry-readiness report digest、capability IDs/states、artifact contract IDs、项目相对输出边界、固定测试/门禁角色。禁止包含 missing-input 内容、credential/secret、自由命令、shell、env、任意 prompt 片段或模块路径。

worker prompt 由固定模板 + canonical platform context + 当前 row exports/design bundle references 组成。worker 只能产出 package 声明允许的 artifacts；worker compliance verifier 必须检查 platform/profile/port/artifact identities。平台包负责把已验证 artifacts 变成固定 plan；worker 永远不能直接提供 executable argv。

## 9. Fan-in

shared orchestrator 只负责：等待全部 feature evidence、排序、调用 package 的 `fan_in` plan builder、验证 plan/binding/authorization、串行交给受控 executor、复验 receipts/done gate。

具体 mutation 属于平台：Flutter 可继续使用冻结 assembly primitives；Vue 使用固定的 route/import/assets/build plan；iOS 使用固定 Xcode project/resource plan；Android 使用固定 Gradle/source/resource plan。禁止共享任意 shell fan-in。

## 10. iFF 分类与迁移矩阵

| 现有职责/代表脚本 | P3 所有者 | 策略 |
|---|---|---|
| CSV row status primitive | TaskSource | 保持冻结 copy + wrapper；不移动 |
| fetch/write/download/export/classify DesignSource primitives | frozen vendor + DesignSource facade | 保持 capsule SHA；不通用化网络/凭据细节 |
| scene/tokens/assets/classification/provenance | DesignSource/shared artifact | 只稳定 schema 与 verifier |
| `generate_canvas.py`, `make_visual_fixture.py` | Flutter package | 保持 frozen capsule 与现有 plans |
| packaging/TDD/runtime capture/project gates/fan-in legacy primitives | Flutter package | 保持 operation ownership 与 SHA |
| expected/slots projection、merged provenance | SharedCore schema | 纯函数/纯 schema；平台 producer/consumer 仍平台所有 |
| worker compliance、artifact chain、visual evidence、done gate 时序 | shared policy contracts | 只抽取证据语义，不抽取平台命令 |
| 其他脚本 | 未分类 | 在证明 caller、artifact producer、consumer 前不移动、不删除、不重命名 |

`iff/**` 始终保持只读。兼容路径继续通过 `icp/vendor/iff_v1` 与固定 manifest；只有 ICP Flutter parity 完全通过且 Vue 闭环完成后，才另立方案把 `iff` 变成调用 ICP Flutter package 的薄包装。

## 11. Flutter parity

冻结并比较：

- iFF schema/脚本 SHA/调用顺序；
- representative design bundle；
- per-feature artifacts；
- RED、packaging、GREEN evidence；
- trace/provenance；
- real simulator screenshot provenance；
- visual diff/repair/done/fan-in/writeback chronology。

同一 fixture 在旧 iFF 与 ICP Flutter 必须满足字节相等或由正式 normalization contract 定义的语义相等；任何未解释差异阻止 activation。现有 vendor/baseline 与 `git diff --exit-code -- iff` 是最低门禁，不足以单独证明端到端 parity。

## 12. Vue 首个非 Flutter adapter

Vue 使用真实 Vite 项目：

- `vue_vite_v1.py` descriptor/package；
- Node/Vite/package.json/src/tests 的只读 preflight；
- Vue SFC/CSS codegen；
- Vitest RED -> GREEN；
- Playwright 启动真实浏览器；
- DOM node trace，node IDs 必须关联 design IR；
- `actual.png` 只能来自 Playwright browser screenshot，并记录 URL/viewport/browser/project build digest；
- visual diff、单次 repair、completion evidence；
- 确定性 route/import/assets/build/test/fan-in plans；
- Vue 自己的 binding/authorization/executor，先复用契约，不复用 Flutter 类。

Vue 不运行 Dart trace、pubspec、Flutter device scripts 或 iFF merge，除非一个明确 capability 的 compatibility proof 单独证明必要且正确。

## 13. 逐需求 checkpoint、退出恢复与顺序推进

shared orchestrator 同一时间只能有一个 active requirement；一个需求内部的 feature/artboard 可以按现有规则并行，但 active requirement 完成或终态失败前不得 claim 第二行。稳定 `requirement_id` 由 selection manifest digest + row identity 派生，claim 后再绑定完整 `claim_ack` digest，不能使用标题或数组下标充当唯一身份。

每个需求使用三个状态层：

- `active-requirement.v1.json`：state root 下原子 no-clobber 的唯一 active pointer，绑定 run/requirement/claim/progress identities；
- `requirement-progress.v1.json`：原子替换的可变游标，绑定 verified operation plan digest、next step、每个 feature 的当前位置；
- `checkpoint-receipts/*.json`：每个完成步骤的不可覆盖 receipt，至少绑定 step/feature ID、input digest、output artifact digests、producer/verifier digests 和前一 receipt digest，形成有序 hash chain。

不能只凭 `status=done` 跳步。恢复时必须取得 state-root/run-root 独占锁，复验 row 仍为同一 claim 的 `doing`、selection/readiness/package/plan identities、receipt chain 和实际产物摘要；从第一个缺失或无效 checkpoint 继续。只有 `started` 而没有完成 receipt 的步骤视为未完成：只有声明了 idempotent replay 或有确定性 recovery verifier 才能重跑，否则 fail closed，不能跳过。

为关闭 claim 后尚未来得及写 progress 的崩溃窗口，claim 前必须先发布 `requirement-claim-intent.v1.json`，绑定 row identity、expected empty status、source SHA before 和确定性 expected SHA after。CSV claim 在同一 flock 临界区验证 intent 后执行现有 CAS。恢复规则固定为：intent + row empty -> 重新执行 CAS；intent + row doing + exact expected-after SHA -> 重建并持久化 claim ack；其他组合 -> `blocked`，不得 claim 新需求。现有 `csv_task_source.claim` / `writeback` 兼容 API 保留（当前 ack 字段见 `csv_task_source.py:350-359`，writeback 仍是 `doing -> outcome` CAS，`:461-468`），新协议只能做兼容包装或新增显式 API，不能削弱旧调用。

进程被终止、机器重启或 worker 中断时不写终态：row 保持 `doing`，active pointer、progress 和 receipts 保留。再次进入 `$icp` 时，EntryReadinessGate 在选择新候选前先检查固定 state root：恰好一个合法 active requirement 时优先 resume；存在多个 active pointers、active lock 仍被持有、row/claim/source identity 不一致或 progress tamper 时立即拒绝，不得另起任务。

需求成功时顺序固定为：done gate -> CAS `doing -> done` -> 复验 writeback ack -> seal immutable completion evidence -> 删除 active pointer 与可变 progress/临时 scratch -> 复验清理 -> 重新运行入口 readiness 并选择第二个需求。终态 error 同样先 CAS `doing -> error`、seal failure evidence，再清除 active pointer/可变 progress。checkpoint receipts、最终截图 provenance、visual diff、completion/failure evidence 属于审计链，永远不能因“清进度”删除。清理或 writeback 未完全成功时仍视为 active，禁止开始下一需求。

resume 不复用旧入口假设：恢复前仍需复验当前 package/toolchain/runtime target；若缺少新的用户输入，在未启动任何新 worker/step 时返回 `needs-user-input`，保留原 active state。claim 后的执行阶段本身不得挂起等待用户。

## 14. 平台族复用

- Web family：Vue 先证明 browser capture/DOM trace 契约；Next.js 后续复用 schema 与 Playwright policy，但保留 SSR/app-router/build/preflight 语义。
- iOS family：Swift 先接现有 `cip` 项目约定；ObjC 后接。共享 Xcode/simctl/capture evidence schema，不共享 codegen、依赖或 source layout。
- Android family：Kotlin 先接现有 `cap` 项目约定；Java 后接。共享 Gradle/ADB/emulator/capture evidence schema，不共享语言 codegen/dependencies。
- Flutter 保持独立 family。只有两个真实实现有相同安全语义时，才允许把实现上移为 family module。

## 15. 分阶段实施

### P3a：PlatformPackage contract + Flutter conformance（全部 inactive）

新增：

- `icp/scripts/platforms/platform_package_contract_v1.py`
- `icp/scripts/platforms/flutter_package_v1.py`
- `icp/scripts/selftest_p3a_platform_package_contract.py`
- 用户批准后把本方案写入 `icp/references/p3-platform-package-architecture.md` 并在 `SKILL.md` 增加简短指针。

不得修改 registry、preflight/selection、SharedCore、任何现有 Flutter production 文件、vendor/baseline/iff。Flutter package 只引用并重算当前六个组件 SHA；descriptor 调用 `verify_descriptor()`，其余五个组件只做 fixed-root/regular-file/no-symlink/basename/SHA/static-entrypoint package-level 校验，request-scoped 深层校验保持原执行链。测试必须包含第二个 synthetic non-Flutter descriptor，证明 shared validator 没有 Flutter literal/port implementation assumptions。

### P3a2：逐需求 progress/claim-intent 纯契约（全部 inactive）

新增：

- `icp/references/requirement-resume-v1.md`
- `icp/scripts/requirement_progress_v1.py`
- `icp/scripts/requirement_claim_intent_v1.py`
- `icp/scripts/selftest_p3a2_requirement_resume.py`

只冻结 active pointer、progress、checkpoint receipt、claim intent/recovery report 的 canonical schema/verifier 和状态机；用临时目录/fake TaskSource 做中断恢复、tamper、双 active、started-without-receipt、cleanup 与顺序推进 RED。不得接入生产 claim/writeback、不得修改 `csv_task_source.py`、不得启动 worker。P3a 当前实现不包含 P3a2；P3a 验收完成后再单独进入该阶段。

### P3b1：固定 resolver + package-aware support gate（inactive）

新增：

- `icp/references/platform_packages_v1.json`
- `icp/references/entry-readiness-v1.md`
- `icp/scripts/entry_readiness_v1.py`
- `icp/scripts/platform_package_resolver_v1.py`
- `icp/scripts/freeze_platform_package_selection_v1.py`
- `icp/scripts/verify_platform_package_selection_v1.py`
- `icp/scripts/selftest_p3b1_entry_readiness.py`
- `icp/scripts/selftest_p3b1_platform_package_selection.py`

修改：

- `icp/scripts/preflight_selection.py`：package-aware support gate；
- `icp/scripts/prepare_selection.py`：同一 gate 与 EntryReadinessGate 必须位于 manifest/claim 前；选择新候选前先发现/复验 fixed state root 的 active requirement；本阶段不接入 ready artifact、claim intent 或 progress 的生产发布；
- `icp/SKILL.md`：入口第一步固定为 readiness；缺项时汇总请求用户补充并停止，claim 后禁止等待用户；详细检查矩阵只链接 `references/entry-readiness-v1.md`，不把平台细节堆入入口正文。

固定 resolver 以内部纯数据 index 把 `(platform, profile)` 映射到固定 package module basename/SHA，registry 不提供 import path。EntryReadinessGate 聚合 core config、候选行、来源、项目和平台 requirements；用 in-memory activated-registry 与 fake probes 证明所有缺项稳定排序且无 secret 回显，并证明 `needs-user-input`/`blocked`/`no-work` 对 manifest/claim/worker 零副作用。prerequisite/package 缺失、index/package/producer digest 漂移、输入源不兼容或 required port 不完整仍在 TaskSource access 前失败；producer 脚本的 symlink/path escape/order/unknown-field tamper 全部 fail closed。生产 registry 仍全 inactive，freezer/verifier 只通过直接 selftest 调用，不写入生产 run root。

### P3b2：Vue descriptor/project preflight/plan（inactive）

新增：

- `icp/scripts/platforms/vue_standard_v1.py`
- `icp/scripts/platforms/vue_project_preflight_v1.py`
- `icp/scripts/platforms/vue_operations_v1.py`
- `icp/scripts/platforms/vue_package_v1.py`
- `icp/scripts/selftest_p3b2_vue_package.py`

修改 `icp/references/platform_packages_v1.json`，只加入 inactive Vue package identity。实现 Vue descriptor、只读 project preflight、静态 deterministic plan builder/verifier；接入 fixed resolver，但不执行、不 claim、不激活。

### P3c：Vue vertical execution chain（inactive）

新增：

- `icp/scripts/platforms/vue_execution_binding_v1.py`
- `icp/scripts/platforms/vue_execution_authorization_v1.py`
- `icp/scripts/platforms/vue_execution_executor_v1.py`
- `icp/scripts/selftest_p3c_vue_execution_chain.py`
- `icp/fixtures/vue_vite_v1/package.json`
- `icp/fixtures/vue_vite_v1/index.html`
- `icp/fixtures/vue_vite_v1/src/App.vue`
- `icp/fixtures/vue_vite_v1/src/main.js`
- `icp/fixtures/vue_vite_v1/tests/unit/app.spec.js`
- `icp/fixtures/vue_vite_v1/tests/e2e/app.spec.js`

修改 `vue_package_v1.py`、`vue_operations_v1.py` 与 `platform_packages_v1.json` 的受影响 digests/ports。真实 Vite fixture 覆盖 SFC/CSS、Vitest、Playwright DOM trace/browser screenshot、visual diff、repair/done/fan-in；实现 Vue binding/authorization/executor 与 one-time receipts。仍不改 registry activation。

### P3d：shared orchestrator + Flutter parity activation audit

新增：

- `icp/scripts/orchestrate_client_project_v1.py`
- `icp/scripts/selftest_p3d_shared_orchestrator.py`
- `icp/scripts/selftest_p3d_flutter_parity.py`
- `icp/scripts/selftest_p3d_requirement_resume_integration.py`

修改：

- `icp/scripts/prepare_selection.py`：manifest freeze 成功后、claim 前依次发布 ready-only entry-readiness、platform-package-selection 和首个 requirement claim-intent；一次只 claim 一个 requirement；任一失败均不 claim；
- `icp/scripts/csv_task_source.py`：保留现有 `claim`/`writeback` API，新增显式 claim-intent 验证与 crash-recovery API；不得改变旧调用结果；
- `icp/scripts/requirement_progress_v1.py` 与 `icp/scripts/requirement_claim_intent_v1.py`：接入真实 claim ack、active pointer、checkpoint receipts、resume/cleanup；
- `icp/scripts/platforms/flutter_operations_v1.py`：plan/request identity 加入 requirement/claim-intent/progress、entry-readiness 与 platform-package-selection path/digest；
- `icp/scripts/platforms/flutter_execution_binding_v1.py`：先固定摘要验证 adjacent verifier，再同时复验 selection manifest、entry-readiness 与 platform-package-selection；
- `icp/scripts/platforms/flutter_execution_authorization_v1.py`：绑定并复验两个 adjacent artifact identities；
- `icp/scripts/platforms/flutter_execution_executor_v1.py`：消费同一已授权 requirement/readiness/package identity，逐步骤产出可验证 checkpoint receipt，拒绝换需求、换包、stale readiness 或摘要漂移；
- `icp/scripts/platforms/flutter_package_v1.py` 与 `icp/references/platform_packages_v1.json`：更新受影响组件/package digest；
- 对应既有 Flutter selftests、`icp/SKILL.md` P3 状态/执行时序和批准后的 `icp/references/p3-platform-package-architecture.md`。

保持 `icp.selection_manifest.v1` 和 `verify_selection_manifest_v1.py` 不变；不得预先 claim 第二个 requirement，不得在 claim 后重新选择另一个 package，也不得让正在执行的 step 进入交互等待。当前需求完成/终态 error、writeback 与 active cleanup 全部复验后，重新运行 readiness 并选择下一需求。先用 in-memory/test registry 运行完整 Flutter parity。`registries.json` 的 Flutter activation 是单独审计、单独用户批准、单独 diff，不与 P3d parity 实现合并。

### P3e：Vue parity/activation audit

新增 `icp/scripts/selftest_p3e_vue_parity.py`；修改 Vue 相关 digest/selftests 和 `SKILL.md` 状态。真实 Vue 项目完整闭环、竞争 claim/writeback、失败恢复与 provenance 通过；`registries.json` 的 Vue activation 同样是单独审计、单独用户批准、单独 diff。

### P4+

Next.js -> iOS Swift -> iOS ObjC -> Android Kotlin -> Android Java；每个平台重复 inactive descriptor/preflight/plan -> vertical execution/evidence -> activation audit，不批量激活。

## 16. P3a/P3b1 严格 RED 与验收

RED 必须先证明：

- module 尚不存在；
- exact public API/descriptor keys/order/kinds；
- shared contract 源码无 Flutter/Vue/Dart/pubspec/adb/simctl/Gradle/Xcode 等平台、工具链、命令或 artifact literal；仅允许 schema 明确定义的四个 `actual_source_types` capture-class 枚举值；
- component role/basename/SHA/API tamper、重复、缺失、重排、未知字段全部 fail closed；
- `entry_requirements` 的 owner/required/sensitive/probe/accepted-shape/remediation 顺序、枚举、unknown-field 与 command/env/path/secret 注入全部 fail closed；
- 禁止 path/command/argv/env/shell/prompt/activation override；
- Flutter package 的六个组件 SHA 与 live bytes 一致；
- package verify 对 descriptor 调用 `verify_descriptor()`；其余五个组件必须通过 fixed-root containment、regular-file/no-symlink、live SHA-256、basename 和预期 public entrypoint 静态 AST 校验，不伪造无参 verifier，也不提前执行 request-scoped deep verification；
- `implementation_state` 只接受 `implemented` / `not-implemented`，且 Flutter `project_preflight` 在 package 中为 `implemented`，冻结的 P2c descriptor 保持 `new-port-required`；
- `activation_state=inactive`, `executable=false`；
- import-time zero I/O；无 subprocess/network/write；
- 所有当前 Flutter、SharedCore、registry、vendor/baseline/iff hashes 保持 P2.5d final；
- `git diff --exit-code -- iff`；
- 全部既有 ICP selftests（已知 fake-Flutter `exited -9` 单例必须原样报告，不得隐藏）；
- vendor verifier、baseline check、skill quick validation、无 `__pycache__`。

P3b1 EntryReadiness RED 必须另外证明：

- core config 缺多项时按固定顺序一次返回全部当前可判定的 `missing_user_inputs`，上游选择不足时列出 `deferred_checks`；
- report 永不包含 credential/token/secret value，错误消息不泄漏输入内容；
- unsupported platform/package 在任何 TaskSource access 前拒绝；来源/候选行/project/platform probe 缺项在 manifest freeze/claim/worker 前拒绝；
- `needs-user-input`、`blocked` 与 `no-work` 不创建可执行 run artifact、不改变行状态、不启动 worker；
- 用户补充后从 strict decode 开始重跑，旧 report/config/source snapshot/candidate digest 不可复用；
- ready 条件在 freeze/claim 前复验，source snapshot 或 runtime target 漂移必须 fail closed；
- ready-only artifact 原子 no-clobber，后续 binding/authorization/executor 复验同一 digest；
- claim 后不存在用户交互等待分支；不可预见故障必须走同一 claim ack 的 `doing -> error` 并产生诊断证据；
- fake TaskSource/DesignSource/platform probes 覆盖 all-pass、multi-missing、blocked、no-work、secret-redaction、controlled-template、probe-exception、atomicity、cleanup-failure 与 zero-side-effect。

## 17. Stop rules / 非目标

- P3a 不实现 Vue，不激活任何平台，不开放 claim。
- 不建立通用基类继承 Flutter 实现。
- 不抽取现有 Flutter executor；不改其 trust/TOCTOU/environment 边界。
- 不修改九个 port 的语义或增加自由操作。
- EntryReadinessGate 不得自动安装 SDK/package、选择未声明的 device/browser、索取明文 secret 或把用户缺项降级成 warning；需要授权的修复必须在开始长任务前由用户完成。
- claim 后不得暂停等待用户、弹出设备选择或凭据输入；未预见的外部失效走 error/writeback，不伪造 unattended success。
- 不迁移/重命名/删除 iFF 或 ICP 现有脚本。
- 如果 shared contract 需要 `if platform == ...`、巨型可选字段 union、自由模块路径、自由命令或 Flutter-specific artifact，立即停止并回到架构评审。
- 如果第二个真实平台无法无损实现 package contract，升级 contract version；不得放宽 v1 验证来迁就实现。
- 后续外部探索或实现只使用用户指定的 `$glm explore` / `$glm code`；不得再调用 Kimi。每个 GLM 结果仍须由 Codex 独立核验。P3a 已获用户批准；后续阶段仍按各自边界推进。
