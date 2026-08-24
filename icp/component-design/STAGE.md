# Stage 2 — 组件化 + 交互绑定

将 Stage 1 的语义 group 绑定到具体组件，拆解交互描述为原子交互图。

## 输入

- `component-spec.json`（Stage 1 冻结产物，只读）
- `design_image`（设计图，视觉比对用）
- `interaction_description`（自然语言交互描述）
- `api_description`（接口描述，自然语言）
- 目标项目代码（cwd）

## 流程

```
Step 1  识别平台 + 扫描组件
        模型读项目代码 → 确定目标平台 + 组件体系
        模型扫描项目已有公共组件 → 建组件清单
        填 checklist Step 1 → check.py --step 1
  ↓
Step 2  组件匹配
        模型：每个 group → 一个组件绑定
        validate.py check-binding ──errors──→ 修正 → 重验
        └─ ok → 填 checklist Step 2 → check.py --step 2
                 ├─ 未完成 → 补充（可能需回 check-binding）
                 └─ ok ↓
Step 3  交互拆解
        模型：解析 api_description → 语义端点列表(semantic_hint)
        模型：用 Apifox MCP 查每个语义端点的真实 schema → resolved
              ├─ 命中 → 填 path/method/auth/request/response/deprecated
              └─ 未命中 → resolved: null (Stage 3 走 mock)
        模型：拆解 interaction_description → 原子交互 + 触发图
        validate.py check-interactions ──errors──→ 修正 → 重验
        └─ ok → 填 checklist Step 3 → check.py --step 3
                 ├─ 未完成 → 补充（可能需回 check-interactions）
                 └─ ok ↓
输出: component-binding.json
```

## 输出格式

```json
{
  "platform": {
    "name": "flutter",
    "framework": "material"
  },
  "apis": [
    {
      "semantic_hint": "/auth/otp-requests",
      "resolved": {
        "path": "/auth/sendVerifyCode",
        "method": "POST",
        "auth": "public",
        "request": {"client_tel": "string", "verify_type": "string"},
        "response": {"data": {"verify_code": "string"}},
        "deprecated": false
      }
    }
  ],
  "components": [
    {
      "group_name": "导航栏",
      "component_name": "AppNavBar",
      "component_type": "existing_shared",
      "source_path": "lib/widgets/app_nav_bar.dart",
      "params": ["title", "onBack", "actions"],
      "affected": null
    },
    {
      "group_name": "验证码输入",
      "component_name": "OtpInput",
      "component_type": "extract_shared",
      "source_path": null,
      "params": ["length", "onComplete"],
      "affected": [
        {"name": "PageAOtpField", "source_path": "lib/pages/a/otp_field.dart"},
        {"name": "PageBOtpField", "source_path": "lib/pages/b/otp_field.dart"}
      ]
    }
  ],
  "interactions": [
    {
      "id": "ix_1",
      "component": "LoginForm",
      "type": "data",
      "condition": null,
      "state": "sending_otp",
      "trigger": "点击发送验证码",
      "behavior": "按钮禁用，显示 loading",
      "result": "发送验证码到手机",
      "api": "/auth/otp-requests",
      "triggers": ["ix_2"]
    }
  ]
}
```

## 组件绑定

每个 group 绑定一个组件：

| 字段 | 含义 |
|---|---|
| `group_name` | 来自 component-spec.json 的语义 group 名 |
| `component_name` | 组件名（项目代码中的类名/函数名） |
| `component_type` | `existing_shared` / `extract_shared` / `platform_builtin` / `new` |
| `source_path` | `existing_shared` 时为已有文件路径；其余为 null |
| `params` | 组件参数列表（共享组件靠参数区分业务） |
| `affected` | 仅 `extract_shared`：需一起改造的现有组件 `[{name, source_path}]` |

### 组件类型判定

优先级 a > b > c > d：

a. **existing_shared** — 项目已有公共组件可直接复用，绑定其名字和路径
b. **extract_shared** — 多个 group（或已有组件）外观+交互模式相同 → 抽为公共组件；
   相同的外观和交互作为主体，差异部分作为 params；
   affected 记录所有需要改造的现有组件，Stage 3 统一重构
c. **platform_builtin** — 平台标准组件（导航栏、列表、输入框等）；`check-binding` 会在项目根目录 grep 源码验证该组件是否实际使用，未找到报 `unverified_builtin` warning
d. **new** — 以上都不是

多个 group 绑同一 component_name = 公共组件，数据通过 params 区分。

## 原子交互

### 字段

| 字段 | 含义 |
|---|---|
| `id` | 唯一标识（ix_1, ix_2, …） |
| `component` | 交互影响的组件——**必须是 components 列表中已声明的 `component_name`**，不能用逻辑页面名（如用 `CommonCard` 而非 `CustomerServiceModal`）；`check-interactions` 会校验 |
| `type` | `behavior`（纯 UI）/ `data`（涉及 API） |
| `condition` | 前提条件（null = 无条件） |
| `state` | 涉及的 UI 状态（null = 纯 UI 交互，无状态变化） |
| `trigger` | 触发动作（用户操作 / 系统事件 / 其他交互的结果） |
| `behavior` | 发生什么（UI 变化） |
| `result` | 产生什么（状态变更 / 路由跳转） |
| `api` | `type=data` 时必填，引用 apis 中的 `semantic_hint`；`behavior` 时为 null |
| `triggers` | 后续交互 id 列表（空列表 = 终点） |

### 交互图

原子交互通过 `triggers` 形成有向图。环合法（如"提交失败 → 重新填写 → 提交"）。

## API 解析：Apifox 为准

Sheet `api` 列只有语义提示（如 `/support`、`/feedback/types`），路径、字段、鉴权都不准确。Apifox OAS 是唯一 source of truth。

### 解析流程

1. 从 `api_description` 提取语义端点列表，记为 `semantic_hint`
2. 用 Apifox MCP 读 OAS index（`read_project_oas`），按语义匹配真实端点：
   - `/support` → `GET /support/customerService`（语义匹配：客服）
   - `/auth/otp-requests` → `POST /auth/sendVerifyCode`（语义匹配：发送验证码）
   - `/feedback` → `POST /feedback/record`（语义匹配：意见反馈）
3. 用 `read_project_oas_ref_resources` 拉匹配到的端点详情（完整定义：method、path、
   headers、parameters、security、requestBody、responses、deprecated、descriptions）。
   模型理解完整定义 + 项目已有网络层代码（API client、auth 模式、DTO 风格），综合产出 `resolved`：
   - `path` + `method`：真实路径
   - `auth`：综合 `security`、`parameters` 中的 `Authorization` header、描述文本判定：
     无鉴权 → `"public"`；必须鉴权 → `"bearer"`；可选鉴权（如 `required: false`）→ `"optional"`
   - `request`：requestBody schema 的顶层字段 + 类型
   - `response`：responses.200 schema 的 `data` 字段结构
   - `deprecated`：是否废弃（废弃端点标注替代方案）
4. 无法匹配 → `resolved: null`，Stage 3 生成 mock Repository

### apis 字段说明

| 字段 | 含义 |
|---|---|
| `semantic_hint` | Sheet/api_description 里的原始端点，保留作追溯 |
| `resolved` | Apifox 解析结果，null 表示未匹配 |
| `resolved.path` | Apifox 真实路径（代码里用这个） |
| `resolved.method` | GET/POST |
| `resolved.auth` | `"public"` / `"bearer"` / `"optional"` |
| `resolved.request` | 请求体字段 schema（GET 则为 query params） |
| `resolved.response` | 响应体 `data` 字段 schema |
| `resolved.deprecated` | 是否废弃；废弃时附 `alternative` 说明替代方案 |

### 废弃端点处理

Apifox 标 `deprecated: true` 时：
- 如有替代端点（如 `/file/uploadImage` → `/file/getAssumeRole` 直传），resolved 填替代端点
- 如无替代且必须兼容，resolved 保留原端点，`deprecated: true` + 注释原因

## 脚本

`scripts/validate.py` — 结构验证:

| 命令 | 输入 | 输出 |
|---|---|---|
| `check-binding` | `--component-spec <f>` `--binding <f>` | 绑定验证结果 |
| `check-interactions` | `--binding <f>` `--component-spec <f>`(可选但**建议给**) | 交互验证结果 |

`scripts/check.py` — checklist 验证:

| 命令 | 输入 | 输出 |
|---|---|---|
| `check.py <checklist>` | stage2-checklist.md 路径 | 全部步骤验证 |
| `check.py <checklist> --step N` | stage2-checklist.md 路径 + 步骤号 | 单步验证 |

输出格式: `{"ok": false, "errors": [{"type": "...", ...}]}` / `{"ok": true}`

### check-binding 检查项

| # | 检查 | 错误类型 |
|---|---|---|
| 1 | component-spec 每个 group 在 binding.components 中有条目 | `unbound_group` |
| 2 | component_type 是 4 种之一 | `invalid_type` |
| 3 | existing_shared 的 source_path 非 null 且文件存在 | `missing_source` |
| 4 | affected 仅出现在 extract_shared | `invalid_affected` |
| 5 | affected 中每个 source_path 文件存在 | `missing_affected_source` |
| 6 | existing_shared / extract_shared 的 params 非空 | `empty_params` |

### check-binding 警告项

| # | 检查 | 警告类型 |
|---|---|---|
| 1 | binding 中有 component-spec 不存在的 group_name | `extra_group` |

### check-interactions 检查项

| # | 检查 | 错误类型 |
|---|---|---|
| 1 | 每个交互有 id 且唯一 | `missing_id` / `duplicate_id` |
| 2 | 每个交互 5 核心字段齐备（condition 可 null） | `incomplete_interaction` |
| 3 | type=data 时 api 非 null | `missing_api` |
| 4 | api 引用的 endpoint 在 apis 列表中存在 | `unknown_api` |
| 5 | triggers 引用的 id 存在 | `broken_trigger` |
| 6 | component 在 components 中存在 | `unknown_component` |
| 7 | `role` 为 action/form 的组件有交互归属（需给 `--component-spec`） | `idle_interactive_component` |

### 警告项（不阻塞，模型必须审查）

| # | 检查 | 警告类型 |
|---|---|---|
| 1 | 组件无任何交互归属，且 role 未知（没给 `--component-spec`） | `idle_component` |

role 已知且非 action/form 的组件按设计就该空闲，不报。

## 过程文件

工作目录：`{project}/.claude/icp/{title}/`

Stage 2 启动时在工作目录创建 `stage2-checklist.md`，每步完成后更新。

### stage2-checklist.md 模板

```markdown
# Stage 2 Checklist

## Step 1: 识别平台 + 扫描组件
- [ ] platform: 
- [ ] scanned_dirs: 
- [ ] shared_components: 

## Step 2: 组件匹配
- [ ] groups_bound: 
- [ ] new_reuse_scan: 
- [ ] extract_shared_scan: 
- [ ] affected_complete: 
- [ ] check_binding: 

## Step 3: 交互拆解
- [ ] apis_parsed: 
- [ ] apis_resolved: 
- [ ] interactions_decomposed: 
- [ ] coverage_verified: 
- [ ] flow_traced: 
- [ ] fields_verified: 
- [ ] check_interactions: 
```

### checklist 项说明

| 项 | 填写内容 |
|---|---|
| platform | 平台/框架，如 `flutter/material` |
| scanned_dirs | 扫描过的共享组件目录 |
| shared_components | 发现的可复用组件数量和列表 |
| groups_bound | N 个 group 绑定了 N 个组件 |
| new_reuse_scan | 每个 new 组件扫描了哪些目录，为什么不复用 |
| extract_shared_scan | 组件两两比对结果，发现/未发现抽取机会 |
| affected_complete | 每个 extract_shared 的 affected 扫描范围和结果 |
| check_binding | validate.py 通过，经 N 轮修正 |
| apis_parsed | 从 api_description 解析出的语义端点数量 |
| apis_resolved | N/M 个端点在 Apifox 解析成功；未解析的列出原因 |
| interactions_decomposed | 拆出的交互数量 |
| coverage_verified | interaction_description 逐句对照，N 句全覆盖 |
| flow_traced | 从入口走完的路径数，无断链 |
| fields_verified | N 个交互的 trigger/behavior/result 回源核对 |
| check_interactions | validate.py 通过，经 N 轮修正 |

### check.py

```
python3 scripts/check.py <checklist> [--step N]
```

输出格式同 validate.py：`{"ok": true}` 或 `{"ok": false, "errors": [...]}`

错误类型：`unchecked`（未勾选）、`empty_value`（勾选但无内容）、`empty_checklist`、`unknown_step`

## 收敛

每个步骤两层验证：

1. **validate.py** — 结构验证（check-binding / check-interactions），有错误 → 修正 → 重验
2. **check.py** — checklist 验证，有未填项 → 补充 → 重验

check.py 未通过时，模型的补充可能影响 JSON 结构 → 修正后先过 validate.py 再过 check.py。

两层都通过才进入下一步。

禁止：跳过 interaction_description 中的任何交互行为；编造 api_description 中不存在的 API；使用 Sheet/api_description 的路径作为 resolved.path（必须经 Apifox 确认）。

## 职责划分

脚本(确定性)：
- validate.py — 组件绑定完整性、路径真实性、affected 约束、交互结构、引用正确性
- check.py — checklist 完成度（项全填且非空）

模型(语义判断)：
- 识别目标平台和组件体系
- 扫描项目组件，判断 component_type，发现 extract_shared 机会
- 解析自然语言 → 结构化 apis + 原子交互
- 修正脚本报告的错误，审查脚本警告
- 填写 checklist 各项（必须有具体证据，不能空填）

## 跨阶段禁令

- 不得改动 Stage 1 的语义分组（发现分组错误 → 回 Stage 1 重跑）
- 每个 group 必须绑定一个 component
