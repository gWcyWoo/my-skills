#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/rule/toolchain.sh"

TOOL="${1:-}"
case "$TOOL" in
  gradle|jdk17|sdk) ;;
  *) die '安装参数校验' '用法: install.sh <gradle|jdk17|sdk> [ANDROID_SDK_ROOT]' ;;
esac

if [ "$TOOL" = "gradle" ] || [ "$TOOL" = "jdk17" ]; then
  command -v brew >/dev/null 2>&1 || die 'Homebrew 检测' 'brew NOT FOUND；请手动安装后重试'
  if [ "$TOOL" = "gradle" ]; then
    if command -v gradle >/dev/null 2>&1; then done_step 'Gradle 已安装'; else run_step '安装 Gradle' brew install gradle || exit 1; fi
    run_step '验证 Gradle' gradle --version || exit 1
  else
    if brew list --versions openjdk@17 >/dev/null 2>&1; then done_step 'OpenJDK 17 已安装'; else run_step '安装 OpenJDK 17' brew install openjdk@17 || exit 1; fi
    JDK_PREFIX="$(brew --prefix openjdk@17 2>/dev/null || true)"
    [ -n "$JDK_PREFIX" ] || die '验证 OpenJDK 17' 'brew prefix openjdk@17 失败'
    if [ -d "$JDK_PREFIX/libexec/openjdk.jdk/Contents/Home" ]; then
      JDK_HOME="$JDK_PREFIX/libexec/openjdk.jdk/Contents/Home"
    else
      JDK_HOME="$JDK_PREFIX"
    fi
    done_step "OpenJDK 17 JAVA_HOME: $JDK_HOME"
  fi
else
  SDK_ROOT="${2:-}"
  [ -n "$SDK_ROOT" ] || die 'SDK 参数校验' 'ANDROID_SDK_ROOT 不能为空'
  SDKMANAGER="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
  [ -x "$SDKMANAGER" ] || die 'sdkmanager 检测' "$SDKMANAGER NOT FOUND"
  export ANDROID_SDK_ROOT="$SDK_ROOT"
  run_step '安装 Android SDK packages' "$SDKMANAGER" \
    "platforms;android-$COMPILE_SDK" "build-tools;$BUILD_TOOLS_VERSION" 'platform-tools' || exit 1
  [ -d "$SDK_ROOT/platforms/android-$COMPILE_SDK" ] || die '验证 Android platform' "android-$COMPILE_SDK NOT FOUND"
  [ -d "$SDK_ROOT/build-tools/$BUILD_TOOLS_VERSION" ] || die '验证 Build Tools' "$BUILD_TOOLS_VERSION NOT FOUND"
  [ -x "$SDK_ROOT/platform-tools/adb" ] || die '验证 platform-tools' 'adb NOT FOUND'
  done_step '验证 Android SDK packages'
fi

printf '\n安装结果汇总\n'
printf '工具: %s\n' "$TOOL"
print_counts
