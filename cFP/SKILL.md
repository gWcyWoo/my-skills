---
name: cFP
description: Use when creating a new standard Flutter/Dart project that follows this company's business conventions (structure, dependencies, scaffolding). `cFP` = create Flutter Project. 触发于 "cFP"、"创建 flutter 工程"、"新建公司标准 flutter dart 项目"。
---

<role>
cFP 在 MAIN session 运行,按公司标准从零搭建一个 Flutter/Dart 工程:Phase 1 确认目录并经 FVM 或全局确定 Flutter 版本,Phase 2 逐题交互收集工程选项再做确定性脚手架。全程每步打印输出;所有决策由用户回编号选定,绝不自动选。确定性工作下放脚本,主会话只负责提问、调用脚本、转述结果。
</role>

<context>
TODO — 待设计:公司标准的目录结构、依赖、脚手架规则。

## 版本管理方式(已确认)
- **A:2 = FVM**:用 FVM 管理 Flutter 版本,按工程锁版本(`.fvmrc`)。
- **B:1 = Dart 随 Flutter 自带**:不单独安装/管理 Dart;Dart 版本由所选 Flutter 版本决定,`flutter --version` 输出里读取其内置 Dart 版本。
- 全局已有的 flutter/dart **不动**,FVM 与之共存;工程内一律用 `fvm flutter` / `.fvm` 取固定版本(裸 `flutter` 仍指向全局)。
- FVM 官方命令(grounded,fvm.app):安装 `fvm install <ver>` / `fvm install stable`(最新稳定);列已缓存 `fvm list`;列可用 `fvm releases`;工程锁版本 `fvm use <ver>`(生成 `.fvmrc` + `.fvm/`)。
- **FVM 自身安装(确定性分支)**:检测到 `brew` → `brew install fvm`;否则 → `curl -fsSL https://fvm.app/install.sh | bash`(目标机不一定有 brew,以脚本兜底)。
- **使用当前版本时跳过 FVM(策略1,已确认)**:FVM 维护独立 SDK 缓存(不复用全局 flutter),`fvm install <已有版本>` 会重下一份。故若用户选「使用当前版本」(目标机已有该 Flutter)→ **不装 FVM、不 `fvm install`**,直接用全局 `flutter` 建工程,工程**不写 `.fvmrc`**(不锁版本)。仅当「升级/指定其它版本」或「机器无 Flutter」时才走 FVM 路径(`fvm install` + Phase 2 `fvm use` 锁版本)。代价:工程有两种形态(MODE=global 不锁 / MODE=fvm 锁)——已知并接受。

## 输出纪律(已确认)
- **每个步骤都要打印**:工程创建流程逐步执行,每个逻辑步骤打印一行 `步骤标签... done`(失败则 `步骤标签... FAILED` 并附原因)。
- **结尾显示最终结果**:全部步骤跑完后,打印一个汇总(成功/失败计数、工程路径等关键产物)。
</context>

<instructions>
**Phase 1 — 环境与目录确认(交互;选择权始终在用户,用 prose 编号菜单,不用 AskUserQuestion)**

1. **确定工程目录**(后续 `fvm flutter create` 与所有生成代码均以此目录为基准):
   呈现菜单 — `1. 当前目录 (<pwd>)`  `2. 指定目录(用户给出绝对路径)`。
   用户选定后回显最终工程根目录 PROJECT_DIR。打印 `工程目录确认... done`。

2. **检测环境**:跑 `bash ~/.claude/skills/cFP/script/detect.sh`,逐行打印 brew / fvm / flutter(全局)/ dart(全局或 Flutter 内置)的版本或 `NOT FOUND`,以及 `fvm` 已缓存的版本列表。

3. **选定 Flutter 版本与模式**(prose 编号菜单,选择权在用户):
   - 检测到可用全局 Flutter:`1. 使用当前版本 (<ver>)`  `2. 升级/切换到指定版本(用户给版本号)`。
   - 未检测到任何 Flutter:`1. 安装最新稳定版`  `2. 安装指定版本(用户给版本号)`。
   据选择解析模式(见 context「策略1」):
   - 选「使用当前版本」 → **MODE=global**、`FLUTTER_CMD=flutter`、不锁版本(无 TARGET)。
   - 其它(指定版本 / 最新 / 机器无 Flutter)→ **MODE=fvm**、`FLUTTER_CMD=fvm flutter`、TARGET=具体版本号或 `stable`。

4. **安装/纳管(仅 MODE=fvm)**:
   - MODE=global:跳过安装,打印 `使用全局 Flutter <ver>,跳过 FVM... done`。
   - MODE=fvm:跑 `bash ~/.claude/skills/cFP/script/install.sh <TARGET>`(① 无 fvm 按 brew 分支安装;② `fvm install <TARGET>`;③ 回读纳管版本+内置 Dart)。每步 `标签... done|FAILED`。
   注:`fvm use`(写 `.fvmrc` 锁版本)在 Phase 2 工程目录内执行,仅 MODE=fvm。

5. **打印 Phase 1 最终结果**:PROJECT_DIR、MODE(global/fvm)、使用的 Flutter 版本 + 内置 Dart 版本、`FLUTTER_CMD`、成功/失败步骤计数。

**Phase 2 — 工程脚手架(交互;每个决策一个 prose 编号菜单,选择权在用户,不用 AskUserQuestion,绝不自动选——即便只有一项;自由文本项一律给「自定义输入」选项)**

逐题询问收集答案 → 调 `script/scaffold.sh` 做确定性脚手架。每步打印 `标签... done|FAILED`。

6. **逐题收集决策**(按顺序提问,每题都给多个可选项,等用户回编号):
   - Q1 项目名(Dart 包名 lower_snake_case):`1. 用目录名 <dir>` `2. 自定义输入`。校验合法性(`test`、dart 关键字、含连字符等非法 → 拒绝并重问)。
   - Q2 包名前缀 org:`1. com.example` `2. 自定义输入`。
   - Q3 目标平台(多选,回逗号分隔编号):`1. android 2. ios 3. web 4. macos 5. windows 6. linux`。
   - Q4 create 模板:`1. app(标准,自己铺架构) 2. skeleton(官方架构模板)`。
   - Q5 架构分层(**浏览式,7 选 1**):列出 7 个选项名 —
     `1. 官方 MVVM 分层  2. Feature-first 3层  3. Feature-first 4层(Riverpod)  4. Layer-first 4层  5. Clean Architecture 严格3层  6. Stacked  7. GetX`。
     用户回编号 → 跑 `bash ~/.claude/skills/cFP/script/show_arch.sh <n>` 显示该结构的 `lib/` 分层 → 询问「确定用这套?还是看其它编号?」→ 循环展示直到用户确认。记下 `ARCH=<确认的编号>`(选项/结构数据见 `rule/architectures.sh`)。
     注:选 6(Stacked)/7(GetX)会接管 Q6 状态管理 / Q7 路由(框架自带),后续据此固定或跳过相应提问。
   - Q6 状态管理:`1. Riverpod 2. Bloc 3. Provider 4. 不加`。
   - Q7 路由:`1. go_router 2. auto_route 3. 不加`。
   - Q8 网络:`1. dio 2. http 3. dio+retrofit 4. 不加`。
   - Q9 依赖注入:`1. get_it(+injectable) 2. provider 3. 跟随状态管理 4. 不加`。
   - Q10 模型/序列化:`1. freezed+json_serializable 2. built_value 3. 不加(手写)`。
   - Q11 Lint:`1. very_good_analysis 2. flutter_lints 3. 自定义`。
   - Q12 附加(多选,可空):`1. README 模板 2. CI(github/gitlab) 3. 环境/flavor 配置 4. l10n 国际化 5. 示例页+目录占位`。

7. **执行脚手架**:把答案经**环境变量**传给 `scaffold.sh` 并运行。映射:
   `PROJECT_DIR`(Phase1)、`MODE`(Phase1 global/fvm)、`TARGET`(Phase1,fvm 版本)、
   `PROJ_NAME`=Q1、`ORG`=Q2、`PLATFORMS`=Q3(逗号)、`TEMPLATE`=Q4(app/skeleton)、`ARCH`=Q5(1-7)、
   `STATE`=Q6(riverpod/bloc/provider/none)、`ROUTER`=Q7(go_router/auto_route/none)、`NET`=Q8(dio/http/dio_retrofit/none)、
   `DI`=Q9(get_it/provider/follow/none)、`MODEL`=Q10(freezed/built_value/none)、`LINT`=Q11(very_good_analysis/flutter_lints/custom)、
   `EXTRAS`=Q12(逗号:readme,ci,env,l10n,sample)、`CI_PROVIDER`(github/gitlab)、`SAMPLE_FEATURE`(默认 home)。
   调用:`PROJECT_DIR=... MODE=... ... bash ~/.claude/skills/cFP/script/scaffold.sh`(ARCH=6/7 时脚本自动用 stacked/get 接管 STATE/ROUTER/DI)。
   脚本依次:create → (fvm)`fvm use` 锁版本 → 建架构目录 → `pub add` 依赖+dev依赖 → 写 lint 配置 → 附加项 → (需codegen)`build_runner` → `pub get`+`analyze` 自检;每步打印 `标签... done|FAILED`。
   **预览**:同样的 env 前加 `CFP_DRY_RUN=1`,只打印计划不执行,可先给用户确认再真跑。

8. **打印 Phase 2 最终结果**:工程路径、包名/org、平台、架构、所选栈(状态/路由/网络/DI/模型/lint)、附加项、成功/失败计数、运行提示(`cd <dir> && <FLUTTER_CMD> run`)。
</instructions>

<success_criteria>
- Phase 1:确定 PROJECT_DIR + MODE(global/fvm)+ 使用的 Flutter/Dart 版本 + FLUTTER_CMD,每步打印 `... done|FAILED`,末尾给汇总。
- Phase 2:逐题交互收集 Q1–Q12(每题用户从编号选,绝不自动选)→ `scaffold.sh` 完成 `create` + 锁版本(fvm)+ 架构目录 + 依赖 + lint + 附加 + build_runner(如需)→ `analyze` 通过;每步打印 `... done|FAILED`,末尾给最终汇总(工程路径 + 所选栈 + 运行提示)。
- 工程可 `cd <dir> && <FLUTTER_CMD> run`(或至少 `analyze` 无 error)。
</success_criteria>

<final_reminders>
P0 — 每个步骤必须打印 `步骤标签... done|FAILED`;全部跑完后必须打印最终结果汇总。
P0 — Phase 2 每个决策(Q1–Q12)都必须以 prose 编号菜单交互询问、由用户回编号选定;绝不自动选(即便只有一项),不用 AskUserQuestion。
P1 — 确定性工作(create/目录/装包/写配置/build_runner)放 `scaffold.sh`;主会话只负责提问与转述。
P1 — MODE=global 用裸 `flutter`、不写 `.fvmrc`;MODE=fvm 用 `fvm flutter` 并 `fvm use` 锁版本。
P2 — 自由文本项(项目名/org/自定义架构)在菜单里给「自定义输入」分支;项目名需校验 Dart 包名合法性。
</final_reminders>
