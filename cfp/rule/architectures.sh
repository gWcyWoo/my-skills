#!/usr/bin/env bash
# cFP Phase 2 架构结构数据 —— 单一事实源:既供 script/show_arch.sh 展示,也供 scaffold.sh 建目录。
# 目录均相对 lib/;<feature> 为占位符,scaffold.sh 会替换为示例功能名(默认 home),show 时原样展示。
# Grounding 来源:
#   1 官方 MVVM 分层      — docs.flutter.dev/app-architecture/recommendations(Compass app)
#   2 Feature-first 3 层  — 社区通用
#   3 Feature-first 4 层  — codewithandrea.com/articles/flutter-project-structure(Riverpod App Architecture)
#   4 Layer-first 4 层    — 同上(层在外、功能在内)
#   5 Clean Architecture  — Reso Coder 风(presentation/domain/data 严格分层)
#   6 Stacked            — FilledStacks stacked CLI 约定结构(stacked.filledstacks.com)
#   7 GetX               — kauemurakami.github.io/getx_pattern

# arch_name <id> —— 结构名;无效编号返回 1。
arch_name() {
  case "$1" in
    1) echo "官方 MVVM 分层 (Flutter 团队 / Compass)";;
    2) echo "Feature-first 3 层 (data/domain/presentation)";;
    3) echo "Feature-first 4 层 (presentation/application/domain/data, Riverpod)";;
    4) echo "Layer-first 4 层 (层在外、功能在内)";;
    5) echo "Clean Architecture 严格 3 层 (Reso Coder 风)";;
    6) echo "Stacked (MVVM + services, 需 stacked 全家桶)";;
    7) echo "GetX (getx_pattern, 需 get 全家桶)";;
    *) return 1;;
  esac
}

# arch_note <id> —— 一句话说明该结构的取舍/约束。
arch_note() {
  case "$1" in
    1) echo "按层划分:UI 层(views+view_model,MVVM)+ Data 层(repositories+services)+ 可选 Domain。Flutter 官方推荐。";;
    2) echo "按功能划分,每功能内 3 层;core/ 放共享。最常见的 feature-first。";;
    3) echo "比 3 层多一个 application(services)层;lib/src 下集中放公共目录。Riverpod 社区主流。";;
    4) echo "与 4 层语义相同,但顶层是层、层内再按功能分。适合强约束层边界。";;
    5) echo "domain 放 entities+usecases+仓库接口;data 放 models+datasources+仓库实现。通常配 Bloc。";;
    6) echo "Stacked 约定:views/<feature> 内 view+viewmodel;app 用 @StackedApp 声明路由+DI(locator/router 由 build_runner 生成)。绑定 stacked 包,接管状态+路由+DI。";;
    7) echo "GetX 约定:modules/<feature> 内 binding+controller+page;routes 集中路由。绑定 get 包,接管状态+路由。";;
    *) return 1;;
  esac
}

# arch_dirs <id> —— 该结构要创建的目录列表(相对 lib/,每行一个,含 <feature> 占位)。无效编号返回 1。
arch_dirs() {
  case "$1" in
    1) cat <<'EOF'
config
routing
data/repositories
data/services
data/models
domain/models
domain/use_cases
ui/core
ui/<feature>/view_model
ui/<feature>/widgets
utils
EOF
    ;;
    2) cat <<'EOF'
core
features/<feature>/data
features/<feature>/domain
features/<feature>/presentation
EOF
    ;;
    3) cat <<'EOF'
src/features/<feature>/presentation
src/features/<feature>/application
src/features/<feature>/domain
src/features/<feature>/data
src/common_widgets
src/constants
src/routing
src/utils
EOF
    ;;
    4) cat <<'EOF'
src/presentation/<feature>
src/application/<feature>
src/domain/<feature>
src/data/<feature>
src/common_widgets
src/constants
src/routing
src/utils
EOF
    ;;
    5) cat <<'EOF'
core/error
core/network
core/usecases
features/<feature>/data/datasources
features/<feature>/data/models
features/<feature>/data/repositories
features/<feature>/domain/entities
features/<feature>/domain/repositories
features/<feature>/domain/usecases
features/<feature>/presentation/bloc
features/<feature>/presentation/pages
features/<feature>/presentation/widgets
EOF
    ;;
    6) cat <<'EOF'
app
ui/common
ui/views/<feature>
ui/widgets/common
services
models
EOF
    ;;
    7) cat <<'EOF'
app/data/provider
app/data/model
app/data/repository
app/modules/<feature>/widgets
app/modules/widgets
app/routes
app/theme
EOF
    ;;
    *) return 1;;
  esac
}
