#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/rule/toolchain.sh"

find_sdk_root() {
  if [ -n "${ANDROID_SDK_ROOT:-}" ]; then printf '%s\n' "$ANDROID_SDK_ROOT"; return; fi
  if [ -n "${ANDROID_HOME:-}" ]; then printf '%s\n' "$ANDROID_HOME"; return; fi
  if [ -d "$HOME/Library/Android/sdk" ]; then printf '%s\n' "$HOME/Library/Android/sdk"; return; fi
  if [ -d "$HOME/Android/Sdk" ]; then printf '%s\n' "$HOME/Android/Sdk"; return; fi
  printf '%s\n' ''
}

find_sdkmanager() {
  local sdk="$1" candidate
  for candidate in "$sdk/cmdline-tools/latest/bin/sdkmanager" "$sdk/cmdline-tools/bin/sdkmanager"; do
    [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return; }
  done
  command -v sdkmanager 2>/dev/null || true
}

info "OS... $(uname -s) $(uname -m)"
if command -v brew >/dev/null 2>&1; then info "brew... $(brew --version 2>&1 | sed -n '1p')"; else info 'brew... NOT FOUND'; fi

if [ -d '/Applications/Android Studio.app' ]; then
  STUDIO_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' '/Applications/Android Studio.app/Contents/Info.plist' 2>/dev/null || printf 'UNKNOWN')"
  info "Android Studio... $STUDIO_VERSION (/Applications/Android Studio.app)"
else
  info 'Android Studio... NOT FOUND at /Applications/Android Studio.app'
fi

info "JAVA_HOME... ${JAVA_HOME:-NOT SET}"
if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
  info "JAVA_HOME java... $($JAVA_HOME/bin/java -version 2>&1 | sed -n '1p')"
fi
if command -v java >/dev/null 2>&1; then
  info "PATH java... $(java -version 2>&1 | sed -n '1p')"
  PATH_JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 | sed -n 's/^[[:space:]]*java.home = //p' | sed -n '1p')"
  info "PATH Java home... ${PATH_JAVA_HOME:-UNKNOWN}"
else
  info 'PATH java... NOT FOUND'
fi
if command -v javac >/dev/null 2>&1; then info "javac... $(javac -version 2>&1 | sed -n '1p')"; else info 'javac... NOT FOUND'; fi
if [ -x /usr/libexec/java_home ]; then info "macOS JDK 17... $(/usr/libexec/java_home -v 17 2>/dev/null || printf 'NOT FOUND')"; fi
if [ -x '/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java' ]; then
  info "Android Studio JBR... $(/Applications/Android\ Studio.app/Contents/jbr/Contents/Home/bin/java -version 2>&1 | sed -n '1p') (/Applications/Android Studio.app/Contents/jbr/Contents/Home)"
fi

if command -v gradle >/dev/null 2>&1; then info "gradle... $(gradle --version 2>&1 | sed -n '/^Gradle /p' | sed -n '1p')"; else info 'gradle... NOT FOUND'; fi

SDK_ROOT="$(find_sdk_root)"
info "Android SDK root... ${SDK_ROOT:-NOT FOUND}"
SDKMANAGER="$(find_sdkmanager "$SDK_ROOT")"
if [ -n "$SDKMANAGER" ]; then info "sdkmanager... $SDKMANAGER"; else info 'sdkmanager... NOT FOUND'; fi

if [ -n "$SDK_ROOT" ] && [ -d "$SDK_ROOT/platforms" ]; then
  info 'installed platforms...'
  find "$SDK_ROOT/platforms" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort | sed 's/^/    /'
else
  info 'installed platforms... NOT FOUND'
fi
if [ -n "$SDK_ROOT" ] && [ -d "$SDK_ROOT/build-tools" ]; then
  info 'installed build-tools...'
  find "$SDK_ROOT/build-tools" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort | sed 's/^/    /'
else
  info 'installed build-tools... NOT FOUND'
fi

if command -v adb >/dev/null 2>&1; then
  info "adb... $(adb version 2>&1 | sed -n '1p')"
elif [ -x "$SDK_ROOT/platform-tools/adb" ]; then
  info "adb... $("$SDK_ROOT/platform-tools/adb" version 2>&1 | sed -n '1p')"
else
  info 'adb... NOT FOUND'
fi

print_toolchain
