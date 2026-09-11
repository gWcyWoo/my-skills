# 工程选项与脚本参数

以下编号是选项标识，不是用户回复格式要求。复用已给出的选择，接受明确自然语言；缺少的产品选择可合并询问。

6. **收集工程选项**：
   - Q1 项目名(Dart 包名 lower_snake_case):`1. 用目录名 <dir>` `2. 自定义输入`。校验合法性(`test`、dart 关键字、含连字符等非法 → 拒绝并重问)。
   - Q2 包名前缀 org:`1. com.example` `2. 自定义输入`。
   - Q3 目标平台(多选，映射为平台名列表):`1. android 2. ios 3. web 4. macos 5. windows 6. linux`。
   - Q4 create 模板:`1. app(标准,自己铺架构) 2. skeleton(官方架构模板)`。
   - Q5 架构分层(**浏览式,7 选 1**):列出 7 个选项名 —
     `1. 官方 MVVM 分层  2. Feature-first 3层  3. Feature-first 4层(Riverpod)  4. Layer-first 4层  5. Clean Architecture 严格3层  6. Stacked  7. GetX`。
     需要比较结构时运行 `bash ~/.agents/skills/cfp/script/show_arch.sh <n>`；记下 `ARCH=<选定编号>`(选项/结构数据见 `rule/architectures.sh`)。
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
   调用:`PROJECT_DIR=... MODE=... ... bash ~/.agents/skills/cfp/script/scaffold.sh`(ARCH=6/7 时脚本自动用 stacked/get 接管 STATE/ROUTER/DI)。
   脚本依次:create → (fvm)`fvm use` 锁版本 → 建架构目录 → `pub add` 依赖+dev依赖 → 写 lint 配置 → 附加项 → (需codegen)`build_runner` → `pub get`+`analyze` 自检;每步打印 `标签... done|FAILED`。
   **预览**:同样的 env 前加 `CFP_DRY_RUN=1`,只打印计划不执行,可先给用户确认再真跑。
