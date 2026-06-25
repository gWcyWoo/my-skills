#!/usr/bin/env bash
# cFP Phase 2 / 步骤7:确定性工程脚手架。读取环境变量(Phase 1 + Phase 2 的答案)→ 建工程。
# 每个逻辑步骤打印 "标签... done|FAILED";末尾打印汇总。
# CFP_DRY_RUN=1 → 只打印计划、不执行(用于预览/测试,无副作用)。
#
# 输入(环境变量):
#   PROJECT_DIR   工程根目录(必填,工程文件直接生成于此)
#   MODE          global | fvm(必填;决定用全局 flutter 还是 fvm 锁版本)
#   TARGET        MODE=fvm 时的 Flutter 版本号(或 stable)
#   PROJ_NAME     Dart 包名(必填,lower_snake_case)
#   ORG           包名前缀(默认 com.example)
#   PLATFORMS     逗号分隔平台,如 android,ios,web(默认 android,ios)
#   TEMPLATE      app | skeleton(默认 app)
#   ARCH          架构编号 1-7(必填;见 rule/architectures.sh)
#   STATE         riverpod|bloc|provider|none(ARCH=6/7 时被框架接管)
#   ROUTER        go_router|auto_route|none(同上)
#   NET           dio|http|dio_retrofit|none
#   DI            get_it|provider|follow|none
#   MODEL         freezed|built_value|none
#   LINT          very_good_analysis|flutter_lints|custom(默认 flutter_lints)
#   EXTRAS        逗号分隔:readme,ci,env,l10n,sample(可空)
#   CI_PROVIDER   github|gitlab(EXTRAS 含 ci 时用,默认 github)
#   SAMPLE_FEATURE 架构里 <feature> 占位的示例功能名(默认 home)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/rule/architectures.sh"

# ---- 读取与默认 ----
PROJECT_DIR="${PROJECT_DIR:?需要 PROJECT_DIR}"
MODE="${MODE:?需要 MODE (global|fvm)}"
TARGET="${TARGET:-}"
PROJ_NAME="${PROJ_NAME:?需要 PROJ_NAME}"
ORG="${ORG:-com.example}"
PLATFORMS="${PLATFORMS:-android,ios}"
TEMPLATE="${TEMPLATE:-app}"
ARCH="${ARCH:?需要 ARCH (1-7)}"
STATE="${STATE:-none}"
ROUTER="${ROUTER:-none}"
NET="${NET:-none}"
DI="${DI:-none}"
MODEL="${MODEL:-none}"
LINT="${LINT:-flutter_lints}"
EXTRAS="${EXTRAS:-}"
CI_PROVIDER="${CI_PROVIDER:-github}"
SAMPLE_FEATURE="${SAMPLE_FEATURE:-home}"
DRY="${CFP_DRY_RUN:-0}"

arch_name "$ARCH" >/dev/null || { echo "ARCH 非法: '$ARCH'(应为 1-7)" >&2; exit 2; }

# MODE 决定 flutter/dart 命令(fvm 路径用 fvm_bin 兜底,规避 PATH 不持久)。
if [ "$MODE" = "fvm" ]; then
  FVM="$(fvm_bin)"
  if [ -z "$FVM" ]; then
    if [ "${CFP_DRY_RUN:-0}" = "1" ]; then FVM="fvm"; else
      echo "MODE=fvm 但找不到 fvm(应先经 install.sh 安装)" >&2; exit 1; fi
  fi
  [ -n "$TARGET" ] || { echo "MODE=fvm 需要 TARGET 版本" >&2; exit 2; }
  FLUTTER_CMD="$FVM flutter"; DART_CMD="$FVM dart"
else
  FLUTTER_CMD="flutter"; DART_CMD="dart"
fi

# ---- 步骤计数与执行助手 ----
OK_N=0; FAIL_N=0; FAILS=""
_ok(){ OK_N=$((OK_N+1)); }
_fail(){ FAIL_N=$((FAIL_N+1)); FAILS="$FAILS\n  - $1"; }

# do_step "标签" cmd...  —— 外部命令步骤(DRY 仅打印;否则 step 执行 + 计数)。
do_step() {
  local label="$1"; shift
  if [ "$DRY" = "1" ]; then printf '%s... [DRY] %s\n' "$label" "$*"; _ok; return 0; fi
  if step "$label" "$@"; then _ok; return 0; else _fail "$label"; return 1; fi
}

# fn_step "标签" 函数名  —— 复合/写文件步骤(函数内可多条命令;DRY 仅打印函数名)。
fn_step() {
  local label="$1" fn="$2"
  if [ "$DRY" = "1" ]; then printf '%s... [DRY] %s\n' "$label" "$fn"; _ok; return 0; fi
  if "$fn" >/dev/null 2>&1; then printf '%s... done\n' "$label"; _ok; return 0
  else printf '%s... FAILED\n' "$label"; _fail "$label"; return 1; fi
}

# ---- 依赖累积(空格字符串,去重)----
REG=""; DEV=""
add_reg(){ local p; for p in "$@"; do case " $REG " in *" $p "*) ;; *) REG="$REG $p";; esac; done; }
add_dev(){ local p; for p in "$@"; do case " $DEV " in *" $p "*) ;; *) DEV="$DEV $p";; esac; done; }

# 架构 6/7 接管状态/路由/DI
case "$ARCH" in
  6) add_reg stacked stacked_services; add_dev stacked_generator build_runner; STATE=stacked; ROUTER=stacked; DI=stacked;;
  7) add_reg get; STATE=getx; ROUTER=getx; DI=getx;;
esac
case "$STATE" in
  riverpod) add_reg flutter_riverpod;;
  bloc)     add_reg flutter_bloc;;
  provider) add_reg provider;;
esac
case "$ROUTER" in
  go_router)  add_reg go_router;;
  auto_route) add_reg auto_route; add_dev auto_route_generator build_runner;;
esac
case "$NET" in
  dio)          add_reg dio;;
  http)         add_reg http;;
  dio_retrofit) add_reg dio retrofit; add_dev retrofit_generator build_runner;;
esac
case "$DI" in
  get_it)   add_reg get_it injectable; add_dev injectable_generator build_runner;;
  provider) add_reg provider;;
esac
case "$MODEL" in
  freezed)     add_reg freezed_annotation json_annotation; add_dev freezed json_serializable build_runner;;
  built_value) add_reg built_value built_collection; add_dev built_value_generator build_runner;;
esac
case "$LINT" in
  very_good_analysis) add_dev very_good_analysis;;
esac

# ---- 复合步骤函数 ----
enter_dir() {
  if [ "$DRY" = "1" ]; then printf '进入工程目录... [DRY] cd %s\n' "$PROJECT_DIR"; _ok; return 0; fi
  if cd "$PROJECT_DIR"; then printf '进入工程目录... done\n'; _ok; return 0
  else printf '进入工程目录... FAILED\n    无法 cd 到 %s\n' "$PROJECT_DIR"; _fail "进入工程目录"; exit 1; fi
}

make_structure() {
  local d
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    d="${d//<feature>/$SAMPLE_FEATURE}"
    mkdir -p "lib/$d" || return 1
    : > "lib/$d/.gitkeep" || return 1
  done < <(arch_dirs "$ARCH")
}

gen_lint_custom() {
  cat > analysis_options.yaml <<'EOF'
include: package:flutter_lints/flutter.yaml
analyzer:
  language:
    strict-casts: true
    strict-raw-types: true
linter:
  rules:
    - prefer_const_constructors
    - prefer_final_locals
    - always_declare_return_types
    - avoid_print
EOF
}
gen_lint_vga() {
  cat > analysis_options.yaml <<'EOF'
include: package:very_good_analysis/analysis_options.yaml
EOF
}

gen_readme() {
  local run="flutter run"; [ "$MODE" = "fvm" ] && run="fvm flutter run"
  cat > README.md <<EOF
# $PROJ_NAME

公司标准 Flutter 工程(由 cFP 生成)。

## 环境
- Flutter: $( [ "$MODE" = "fvm" ] && echo "FVM 锁定 $TARGET(见 .fvmrc)" || echo "全局" )
- 架构: $(arch_name "$ARCH")

## 运行
\`\`\`bash
cd $(basename "$PROJECT_DIR")
$run
\`\`\`
EOF
}

gen_ci() {
  if [ "$CI_PROVIDER" = "gitlab" ]; then
    cat > .gitlab-ci.yml <<'EOF'
stages: [analyze, test]
flutter_analyze:
  stage: analyze
  image: ghcr.io/cirruslabs/flutter:stable
  script:
    - flutter pub get
    - flutter analyze
flutter_test:
  stage: test
  image: ghcr.io/cirruslabs/flutter:stable
  script:
    - flutter pub get
    - flutter test
EOF
  else
    mkdir -p .github/workflows
    cat > .github/workflows/flutter.yml <<'EOF'
name: flutter
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with: { channel: stable }
      - run: flutter pub get
      - run: flutter analyze
      - run: flutter test
EOF
  fi
}

gen_env() {
  cat > .env.example <<'EOF'
# 运行时环境变量示例,复制为 .env 并填写;通过 --dart-define-from-file=.env 注入。
API_BASE_URL=https://api.example.com
EOF
  : > .env
  if [ -f .gitignore ]; then
    grep -qxF '.env' .gitignore || printf '\n.env\n' >> .gitignore
  fi
}

gen_l10n() {
  cat > l10n.yaml <<'EOF'
arb-dir: lib/l10n
template-arb-file: app_en.arb
output-localization-file: app_localizations.dart
EOF
  mkdir -p lib/l10n
  cat > lib/l10n/app_en.arb <<'EOF'
{
  "@@locale": "en",
  "appTitle": "App",
  "@appTitle": { "description": "Application title" }
}
EOF
}

# ============ 执行 ============
echo "=== cFP Phase 2 脚手架开始$( [ "$DRY" = 1 ] && echo '(DRY-RUN 预览)') ==="

# A. 创建 Flutter 工程
if [ "$MODE" = "fvm" ]; then
  do_step "创建工程目录" mkdir -p "$PROJECT_DIR"
  enter_dir
  do_step "FVM 锁定版本 $TARGET (.fvmrc)" $FVM use "$TARGET" --force
  do_step "创建 Flutter 工程 (fvm)" $FVM flutter create --org "$ORG" --project-name "$PROJ_NAME" --platforms "$PLATFORMS" -t "$TEMPLATE" .
else
  do_step "创建 Flutter 工程 (全局)" flutter create --org "$ORG" --project-name "$PROJ_NAME" --platforms "$PLATFORMS" -t "$TEMPLATE" "$PROJECT_DIR"
  enter_dir
fi

# B. 架构目录
fn_step "创建架构目录 (ARCH=$ARCH → 示例功能 $SAMPLE_FEATURE)" make_structure

# C. 依赖
if [ -n "${REG# }" ]; then do_step "添加依赖 ($REG )" $FLUTTER_CMD pub add $REG; fi
if [ -n "${DEV# }" ]; then
  DEVARGS=""; for p in $DEV; do DEVARGS="$DEVARGS dev:$p"; done
  do_step "添加 dev 依赖 ($DEV )" $FLUTTER_CMD pub add $DEVARGS
fi

# D. Lint
case "$LINT" in
  very_good_analysis) fn_step "写 analysis_options.yaml (very_good_analysis)" gen_lint_vga;;
  custom)             fn_step "写 analysis_options.yaml (自定义基线)" gen_lint_custom;;
  *)                  echo "Lint: flutter_lints(flutter create 默认已含)... done"; _ok;;
esac

# E. 附加项
case ",$EXTRAS," in *",readme,"*) fn_step "生成 README.md" gen_readme;; esac
case ",$EXTRAS," in *",ci,"*)     fn_step "生成 CI 配置 ($CI_PROVIDER)" gen_ci;; esac
case ",$EXTRAS," in *",env,"*)    fn_step "生成环境配置 (.env/.env.example)" gen_env;; esac
case ",$EXTRAS," in *",l10n,"*)
  fn_step "生成 l10n 脚手架 (l10n.yaml + arb)" gen_l10n
  do_step "添加 l10n 依赖" $FLUTTER_CMD pub add flutter_localizations --sdk=flutter intl:any
  echo "提示:请在 pubspec.yaml 的 flutter: 段下加 'generate: true' 以启用 l10n 代码生成"
  ;;
esac

# F. 代码生成(若选了需要 build_runner 的项)
case " $DEV " in
  *" build_runner "*) do_step "代码生成 (build_runner)" $DART_CMD run build_runner build --delete-conflicting-outputs;;
esac

# G. 自检
do_step "依赖拉取 (pub get)" $FLUTTER_CMD pub get
do_step "静态分析自检 (analyze, 仅 error 视为失败)" $FLUTTER_CMD analyze --no-fatal-infos --no-fatal-warnings

# ============ 汇总 ============
echo "=== cFP Phase 2 最终结果 ==="
echo "  工程路径   : $PROJECT_DIR"
echo "  包名/org   : $PROJ_NAME / $ORG"
echo "  平台       : $PLATFORMS   模板: $TEMPLATE"
echo "  架构       : $(arch_name "$ARCH")"
echo "  栈         : state=$STATE router=$ROUTER net=$NET di=$DI model=$MODEL lint=$LINT"
echo "  附加       : ${EXTRAS:-(无)}"
echo "  依赖       :${REG:- (无)}"
echo "  dev 依赖   :${DEV:- (无)}"
echo "  步骤       : 成功 $OK_N / 失败 $FAIL_N"
if [ "$FAIL_N" -gt 0 ]; then printf "  失败项     :%b\n" "$FAILS"; fi
RUNHINT="flutter run"; [ "$MODE" = "fvm" ] && RUNHINT="fvm flutter run"
echo "  运行       : cd $PROJECT_DIR && $RUNHINT"
[ "$FAIL_N" -eq 0 ]
