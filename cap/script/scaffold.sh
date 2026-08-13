#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/rule/toolchain.sh"
. "$ROOT/rule/architectures.sh"

PROJECT_DIR="${PROJECT_DIR:-}"
APP_NAME="${APP_NAME:-}"
PACKAGE_NAME="${PACKAGE_NAME:-}"
MIN_SDK="${MIN_SDK:-24}"
UI="${UI:-compose}"
ARCH="${ARCH:-1}"
STATE="${STATE:-stateflow}"
NET="${NET:-none}"
STORAGE="${STORAGE:-none}"
DI="${DI:-manual}"
TESTS="${TESTS:-unit}"
LINT="${LINT:-android}"
EXTRAS="${EXTRAS:-}"
CI_PROVIDER="${CI_PROVIDER:-github}"
GRADLE_CMD="${GRADLE_CMD:-gradle}"
GRADLEW_OVERRIDE="${GRADLEW_CMD:-}"
DRY_RUN="${CAP_DRY_RUN:-0}"

validate_choice() {
  local value="$1"
  shift
  local allowed
  for allowed in "$@"; do [ "$value" = "$allowed" ] && return 0; done
  return 1
}

contains_extra() {
  case ",$EXTRAS," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

guard_path() {
  [ ! -e "$PROJECT_DIR/$1" ] || die '覆盖保护' "已存在受管路径: $PROJECT_DIR/$1"
}

path_to_package() { printf '%s\n' "$1" | tr '/' '.'; }

[ -n "$PROJECT_DIR" ] || die '参数校验' 'PROJECT_DIR 不能为空'
case "$PROJECT_DIR" in /*) ;; *) die '参数校验' 'PROJECT_DIR 必须是绝对路径' ;; esac
[[ "$APP_NAME" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]] || die '参数校验' 'APP_NAME 必须匹配 [A-Za-z][A-Za-z0-9_]*'
[[ "$PACKAGE_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$ ]] || die '参数校验' 'PACKAGE_NAME 必须是至少两段的合法点分标识符'
[[ "$MIN_SDK" =~ ^[0-9]+$ ]] || die '参数校验' 'MIN_SDK 必须是整数'
[ "$MIN_SDK" -ge 23 ] && [ "$MIN_SDK" -le "$TARGET_SDK" ] || die '参数校验' "MIN_SDK 必须在 23..$TARGET_SDK"
validate_choice "$UI" compose views || die '参数校验' 'UI 必须是 compose|views'
architecture_name "$ARCH" >/dev/null || die '参数校验' 'ARCH 必须是 1|2|3|4'
validate_choice "$STATE" stateflow none || die '参数校验' 'STATE 必须是 stateflow|none'
validate_choice "$NET" urlconnection none || die '参数校验' 'NET 必须是 urlconnection|none'
validate_choice "$STORAGE" shared_preferences none || die '参数校验' 'STORAGE 必须是 shared_preferences|none'
validate_choice "$DI" manual none || die '参数校验' 'DI 必须是 manual|none'
validate_choice "$TESTS" unit instrumented both none || die '参数校验' 'TESTS 必须是 unit|instrumented|both|none'
validate_choice "$LINT" android none || die '参数校验' 'LINT 必须是 android|none'
validate_choice "$CI_PROVIDER" github gitlab || die '参数校验' 'CI_PROVIDER 必须是 github|gitlab'

ARCH_NAME="$(architecture_name "$ARCH")"
UI_REL="$(architecture_ui_dir "$ARCH")"
STATE_REL="$(architecture_state_dir "$ARCH")"
INFRA_REL="$(architecture_infrastructure_dir "$ARCH")"
UI_PACKAGE="$PACKAGE_NAME.$(path_to_package "$UI_REL")"
STATE_PACKAGE="$PACKAGE_NAME.$(path_to_package "$STATE_REL")"
INFRA_PACKAGE="$PACKAGE_NAME.$(path_to_package "$INFRA_REL")"
PACKAGE_PATH="$(printf '%s\n' "$PACKAGE_NAME" | tr '.' '/')"
if contains_extra flavors; then
  ASSEMBLE_TASK='assembleDevDebug'
  UNIT_TASK='testDevDebugUnitTest'
  INSTRUMENTED_TASK='assembleDevDebugAndroidTest'
  LINT_TASK='lintDevDebug'
else
  ASSEMBLE_TASK='assembleDebug'
  UNIT_TASK='testDebugUnitTest'
  INSTRUMENTED_TASK='assembleDebugAndroidTest'
  LINT_TASK='lintDebug'
fi
GRADLE_TASKS=":app:$ASSEMBLE_TASK"
if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then GRADLE_TASKS="$GRADLE_TASKS :app:$UNIT_TASK"; fi
if [ "$TESTS" = "instrumented" ] || [ "$TESTS" = "both" ]; then GRADLE_TASKS="$GRADLE_TASKS :app:$INSTRUMENTED_TASK"; fi
if [ "$LINT" = "android" ]; then GRADLE_TASKS="$GRADLE_TASKS :app:$LINT_TASK"; fi

if [ "$DRY_RUN" = "1" ]; then
  printf 'cAP 脚手架预览\n'
  printf 'PROJECT_DIR=%s\nAPP_NAME=%s\nPACKAGE_NAME=%s\nMIN_SDK=%s\n' "$PROJECT_DIR" "$APP_NAME" "$PACKAGE_NAME" "$MIN_SDK"
  printf 'UI=%s\nARCH=%s (%s)\nSTATE=%s\nNET=%s\nSTORAGE=%s\nDI=%s\n' "$UI" "$ARCH" "$ARCH_NAME" "$STATE" "$NET" "$STORAGE" "$DI"
  printf 'TESTS=%s\nLINT=%s\nEXTRAS=%s\nCI_PROVIDER=%s\n' "$TESTS" "$LINT" "${EXTRAS:-none}" "$CI_PROVIDER"
  print_toolchain
  printf '计划: 覆盖保护 → Gradle Wrapper → Kotlin DSL/Manifest/resources → 架构源码/测试 → assembleDebug → 测试/lint\n'
  exit 0
fi

if [ -n "${JAVA_HOME:-}" ]; then
  [ -x "$JAVA_HOME/bin/java" ] || die 'JDK 检测' "$JAVA_HOME/bin/java NOT FOUND"
  export JAVA_HOME
  JAVA_CMD="$JAVA_HOME/bin/java"
else
  command -v java >/dev/null 2>&1 || die 'JDK 检测' 'java NOT FOUND'
  JAVA_CMD="$(command -v java)"
fi
JAVA_LINE="$($JAVA_CMD -version 2>&1 | sed -n '1p')"
JAVA_VERSION="$(printf '%s\n' "$JAVA_LINE" | sed -E 's/.*version "([0-9]+).*/\1/')"
[ "$JAVA_VERSION" = "$JDK_MAJOR" ] || die 'JDK 版本校验' "需要 JDK $JDK_MAJOR，当前: $JAVA_LINE"

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
[ -n "$SDK_ROOT" ] || die 'Android SDK 检测' 'ANDROID_SDK_ROOT 不能为空'
[ -d "$SDK_ROOT/platforms/android-$COMPILE_SDK" ] || [ -d "$SDK_ROOT/platforms/android-$COMPILE_SDK.0" ] || die 'Android SDK 检测' "platforms/android-$COMPILE_SDK{,.0} NOT FOUND"
[ -d "$SDK_ROOT/build-tools/$BUILD_TOOLS_VERSION" ] || die 'Android SDK 检测' "build-tools/$BUILD_TOOLS_VERSION NOT FOUND"
[ -x "$SDK_ROOT/platform-tools/adb" ] || die 'Android SDK 检测' 'platform-tools/adb NOT FOUND'
export ANDROID_SDK_ROOT="$SDK_ROOT"
command -v "$GRADLE_CMD" >/dev/null 2>&1 || die 'Gradle 检测' "$GRADLE_CMD NOT FOUND"

run_step '创建工程根目录' mkdir -p "$PROJECT_DIR" || exit 1
for managed in settings.gradle.kts build.gradle.kts gradle.properties local.properties gradle gradlew gradlew.bat app .cap-generated .gitignore; do guard_path "$managed"; done
if contains_extra readme; then guard_path 'README.md'; fi
if contains_extra ci && [ "$CI_PROVIDER" = "github" ]; then guard_path '.github/workflows/android.yml'; fi
if contains_extra ci && [ "$CI_PROVIDER" = "gitlab" ]; then guard_path '.gitlab-ci.yml'; fi

write_wrapper_bootstrap() {
  printf 'rootProject.name = "%s"\n' "$APP_NAME" > "$PROJECT_DIR/settings.gradle.kts"
  printf '// Temporary bootstrap for the Gradle Wrapper task.\n' > "$PROJECT_DIR/build.gradle.kts"
}

generate_wrapper() {
  "$GRADLE_CMD" -p "$PROJECT_DIR" wrapper --gradle-version "$GRADLE_VERSION" --distribution-type bin
}

write_build_files() {
  cat > "$PROJECT_DIR/settings.gradle.kts" <<EOF
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "$APP_NAME"
include(":app")
EOF
  cat > "$PROJECT_DIR/build.gradle.kts" <<EOF
plugins {
    id("com.android.application") version "$AGP_VERSION" apply false
EOF
  if [ "$UI" = "compose" ]; then
    printf '    id("org.jetbrains.kotlin.plugin.compose") version "%s" apply false\n' "$COMPOSE_COMPILER_VERSION" >> "$PROJECT_DIR/build.gradle.kts"
  fi
  printf '}\n' >> "$PROJECT_DIR/build.gradle.kts"
  cat > "$PROJECT_DIR/gradle.properties" <<'EOF'
org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
EOF
  SDK_ESCAPED="$(printf '%s\n' "$SDK_ROOT" | sed 's/\\/\\\\/g; s/ /\\ /g; s/:/\\:/g')"
  printf 'sdk.dir=%s\n' "$SDK_ESCAPED" > "$PROJECT_DIR/local.properties"
  mkdir -p "$PROJECT_DIR/app"
  cat > "$PROJECT_DIR/app/build.gradle.kts" <<EOF
plugins {
    id("com.android.application")
EOF
  if [ "$UI" = "compose" ]; then printf '    id("org.jetbrains.kotlin.plugin.compose")\n' >> "$PROJECT_DIR/app/build.gradle.kts"; fi
  cat >> "$PROJECT_DIR/app/build.gradle.kts" <<EOF
}

android {
    namespace = "$PACKAGE_NAME"
    compileSdk = $COMPILE_SDK

    defaultConfig {
        applicationId = "$PACKAGE_NAME"
        minSdk = $MIN_SDK
        targetSdk = $TARGET_SDK
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
EOF
  if [ "$UI" = "compose" ]; then
    cat >> "$PROJECT_DIR/app/build.gradle.kts" <<'EOF'

    buildFeatures {
        compose = true
    }
EOF
  fi
  if contains_extra flavors; then
    cat >> "$PROJECT_DIR/app/build.gradle.kts" <<'EOF'

    flavorDimensions += "environment"
    productFlavors {
        create("dev") {
            dimension = "environment"
            applicationIdSuffix = ".dev"
            versionNameSuffix = "-dev"
        }
        create("prod") {
            dimension = "environment"
        }
    }
EOF
  fi
  cat >> "$PROJECT_DIR/app/build.gradle.kts" <<'EOF'
}

dependencies {
EOF
  if [ "$UI" = "compose" ]; then
    cat >> "$PROJECT_DIR/app/build.gradle.kts" <<EOF
    val composeBom = platform("androidx.compose:compose-bom:$COMPOSE_BOM_VERSION")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:$ACTIVITY_VERSION")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
EOF
  else
    printf '    implementation("androidx.activity:activity-ktx:%s")\n' "$ACTIVITY_VERSION" >> "$PROJECT_DIR/app/build.gradle.kts"
  fi
  if [ "$STATE" = "stateflow" ]; then
    printf '    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:%s")\n' "$LIFECYCLE_VERSION" >> "$PROJECT_DIR/app/build.gradle.kts"
    if [ "$UI" = "compose" ]; then
      printf '    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:%s")\n' "$LIFECYCLE_VERSION" >> "$PROJECT_DIR/app/build.gradle.kts"
    else
      printf '    implementation("androidx.lifecycle:lifecycle-runtime-ktx:%s")\n' "$LIFECYCLE_VERSION" >> "$PROJECT_DIR/app/build.gradle.kts"
    fi
  fi
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then printf '    testImplementation("junit:junit:%s")\n' "$JUNIT_VERSION" >> "$PROJECT_DIR/app/build.gradle.kts"; fi
  if [ "$TESTS" = "instrumented" ] || [ "$TESTS" = "both" ]; then
    cat >> "$PROJECT_DIR/app/build.gradle.kts" <<EOF
    androidTestImplementation("androidx.test:core-ktx:$ANDROIDX_TEST_CORE_VERSION")
    androidTestImplementation("androidx.test.ext:junit:$ANDROIDX_TEST_JUNIT_VERSION")
    androidTestImplementation("androidx.test:runner:$ANDROIDX_TEST_RUNNER_VERSION")
    androidTestImplementation("androidx.test.espresso:espresso-core:$ESPRESSO_VERSION")
EOF
  fi
  printf '}\n' >> "$PROJECT_DIR/app/build.gradle.kts"
  printf '%s\n' '# Add project-specific R8 rules here.' > "$PROJECT_DIR/app/proguard-rules.pro"
}

create_structure() {
  local root="$PROJECT_DIR/app/src/main/kotlin/$PACKAGE_PATH"
  case "$ARCH" in
    1) mkdir -p "$root/app" "$root/core/network" "$root/core/storage" "$root/features/home/model" "$root/features/home/state" "$root/features/home/ui" ;;
    2) mkdir -p "$root/app" "$root/core" "$root/features/home/data" "$root/features/home/domain" "$root/features/home/presentation" ;;
    3) mkdir -p "$root/app" "$root/data/network" "$root/data/storage" "$root/domain" "$root/presentation" ;;
    4) mkdir -p "$root/app" "$root/model/services" "$root/view" "$root/controller" ;;
  esac
  mkdir -p "$PROJECT_DIR/app/src/main/res/values"
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then mkdir -p "$PROJECT_DIR/app/src/test/kotlin/$PACKAGE_PATH"; fi
  if [ "$TESTS" = "instrumented" ] || [ "$TESTS" = "both" ]; then mkdir -p "$PROJECT_DIR/app/src/androidTest/kotlin/$PACKAGE_PATH"; fi
}

write_manifest_resources() {
  local app_name_attr=''
  if [ "$DI" = "manual" ]; then app_name_attr=' android:name=".app.MainApplication"'; fi
  cat > "$PROJECT_DIR/app/src/main/AndroidManifest.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application$app_name_attr
        android:allowBackup="true"
        android:label="@string/app_name"
        android:theme="@style/Theme.CAP">
        <activity
            android:name=".app.MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF
  cat > "$PROJECT_DIR/app/src/main/res/values/strings.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">$APP_NAME</string>
    <string name="ready">Android Kotlin project ready</string>
    <string name="count">Count: %1\$d</string>
</resources>
EOF
  cat > "$PROJECT_DIR/app/src/main/res/values/styles.xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="Theme.CAP" parent="android:style/Theme.Material.Light.NoActionBar">
        <item name="android:fontFamily">sans</item>
    </style>
</resources>
EOF
  if contains_extra l10n; then
    mkdir -p "$PROJECT_DIR/app/src/main/res/values-zh-rCN"
    cat > "$PROJECT_DIR/app/src/main/res/values-zh-rCN/strings.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">$APP_NAME</string>
    <string name="ready">Android Kotlin 工程已就绪</string>
    <string name="count">计数：%1\$d</string>
</resources>
EOF
  fi
}

write_state_source() {
  [ "$STATE" = "stateflow" ] || return 0
  local dir="$PROJECT_DIR/app/src/main/kotlin/$PACKAGE_PATH/$STATE_REL"
  cat > "$dir/HomeViewModel.kt" <<EOF
package $STATE_PACKAGE

import androidx.lifecycle.ViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class HomeState(val count: Int = 0)

class HomeViewModel : ViewModel() {
    private val _state = MutableStateFlow(HomeState())
    val state: StateFlow<HomeState> = _state.asStateFlow()
    fun increment() { _state.value = _state.value.copy(count = _state.value.count + 1) }
}
EOF
}

write_compose_sources() {
  local root="$PROJECT_DIR/app/src/main/kotlin/$PACKAGE_PATH"
  local ui_dir="$root/$UI_REL"
  if [ "$STATE" = "stateflow" ]; then
    cat > "$root/app/MainActivity.kt" <<EOF
package $PACKAGE_NAME.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.viewmodel.compose.viewModel
import $UI_PACKAGE.HomeScreen
import $STATE_PACKAGE.HomeViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HomeScreen(viewModel()) }
    }
}
EOF
    cat > "$ui_dir/HomeScreen.kt" <<EOF
package $UI_PACKAGE

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import $PACKAGE_NAME.R
import $STATE_PACKAGE.HomeViewModel

@Composable
fun HomeScreen(viewModel: HomeViewModel) {
    val state by viewModel.state.collectAsState()
    MaterialTheme {
        Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) {
            Text(androidx.compose.ui.res.stringResource(R.string.ready))
            Button(onClick = viewModel::increment) { Text(androidx.compose.ui.res.stringResource(R.string.count, state.count)) }
        }
    }
}
EOF
  else
    cat > "$root/app/MainActivity.kt" <<EOF
package $PACKAGE_NAME.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import $UI_PACKAGE.HomeScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HomeScreen() }
    }
}
EOF
    if contains_extra sample; then
      cat > "$ui_dir/HomeScreen.kt" <<EOF
package $UI_PACKAGE

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import $PACKAGE_NAME.R

@Composable
fun HomeScreen() {
    var count by remember { mutableIntStateOf(0) }
    MaterialTheme {
        Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) {
            Text(androidx.compose.ui.res.stringResource(R.string.ready))
            Button(onClick = { count++ }) { Text(androidx.compose.ui.res.stringResource(R.string.count, count)) }
        }
    }
}
EOF
    else
      cat > "$ui_dir/HomeScreen.kt" <<EOF
package $UI_PACKAGE

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import $PACKAGE_NAME.R

@Composable
fun HomeScreen() { MaterialTheme { Text(stringResource(R.string.ready)) } }
EOF
    fi
  fi
}

write_views_sources() {
  local root="$PROJECT_DIR/app/src/main/kotlin/$PACKAGE_PATH"
  local ui_dir="$root/$UI_REL"
  if [ "$STATE" = "stateflow" ] || contains_extra sample; then
    cat > "$ui_dir/HomeView.kt" <<EOF
package $UI_PACKAGE

import android.content.Context
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import $PACKAGE_NAME.R

data class HomeBinding(val root: View, val title: TextView, val button: Button)

object HomeView {
    fun create(context: Context, onIncrement: () -> Unit): HomeBinding {
        val title = TextView(context).apply { text = context.getString(R.string.ready) }
        val button = Button(context).apply { text = context.getString(R.string.count, 0); setOnClickListener { onIncrement() } }
        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            addView(title)
            addView(button)
        }
        return HomeBinding(root, title, button)
    }
}
EOF
  else
    cat > "$ui_dir/HomeView.kt" <<EOF
package $UI_PACKAGE

import android.content.Context
import android.view.View
import android.widget.TextView
import $PACKAGE_NAME.R

object HomeView {
    fun create(context: Context): View = TextView(context).apply { text = context.getString(R.string.ready) }
}
EOF
  fi
  if [ "$STATE" = "stateflow" ]; then
    cat > "$root/app/MainActivity.kt" <<EOF
package $PACKAGE_NAME.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import $PACKAGE_NAME.R
import $UI_PACKAGE.HomeView
import $STATE_PACKAGE.HomeViewModel

class MainActivity : ComponentActivity() {
    private val viewModel: HomeViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val binding = HomeView.create(this, viewModel::increment)
        setContentView(binding.root)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { binding.button.text = getString(R.string.count, it.count) }
            }
        }
    }
}
EOF
  elif contains_extra sample; then
    cat > "$root/app/MainActivity.kt" <<EOF
package $PACKAGE_NAME.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import $PACKAGE_NAME.R
import $UI_PACKAGE.HomeView

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        var count = 0
        lateinit var binding: ${UI_PACKAGE}.HomeBinding
        binding = HomeView.create(this) {
            count++
            binding.button.text = getString(R.string.count, count)
        }
        setContentView(binding.root)
    }
}
EOF
  else
    cat > "$root/app/MainActivity.kt" <<EOF
package $PACKAGE_NAME.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import $UI_PACKAGE.HomeView

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(HomeView.create(this))
    }
}
EOF
  fi
}

write_infrastructure_sources() {
  local root="$PROJECT_DIR/app/src/main/kotlin/$PACKAGE_PATH"
  local infra_dir="$root/$INFRA_REL"
  if [ "$NET" = "urlconnection" ]; then
    mkdir -p "$infra_dir/network"
    cat > "$infra_dir/network/NetworkClient.kt" <<EOF
package $INFRA_PACKAGE.network

import java.net.HttpURLConnection
import java.net.URL

class NetworkClient {
    fun get(url: URL): String {
        val connection = url.openConnection() as HttpURLConnection
        connection.requestMethod = "GET"
        return connection.inputStream.bufferedReader().use { it.readText() }
    }
}
EOF
  fi
  if [ "$STORAGE" = "shared_preferences" ]; then
    mkdir -p "$infra_dir/storage"
    cat > "$infra_dir/storage/PreferencesStore.kt" <<EOF
package $INFRA_PACKAGE.storage

import android.content.Context

class PreferencesStore(context: Context) {
    private val preferences = context.getSharedPreferences("app", Context.MODE_PRIVATE)
    fun putString(key: String, value: String) { preferences.edit().putString(key, value).apply() }
    fun getString(key: String): String? = preferences.getString(key, null)
}
EOF
  fi
  if [ "$DI" = "manual" ]; then
    cat > "$root/app/AppContainer.kt" <<EOF
package $PACKAGE_NAME.app

import android.content.Context
EOF
    if [ "$NET" = "urlconnection" ]; then printf 'import %s.network.NetworkClient\n' "$INFRA_PACKAGE" >> "$root/app/AppContainer.kt"; fi
    if [ "$STORAGE" = "shared_preferences" ]; then printf 'import %s.storage.PreferencesStore\n' "$INFRA_PACKAGE" >> "$root/app/AppContainer.kt"; fi
    cat >> "$root/app/AppContainer.kt" <<EOF

class AppContainer(context: Context) {
EOF
    if [ "$NET" = "urlconnection" ]; then printf '    val networkClient = NetworkClient()\n' >> "$root/app/AppContainer.kt"; fi
    if [ "$STORAGE" = "shared_preferences" ]; then printf '    val preferencesStore = PreferencesStore(context)\n' >> "$root/app/AppContainer.kt"; fi
    printf '}\n' >> "$root/app/AppContainer.kt"
    cat > "$root/app/MainApplication.kt" <<EOF
package $PACKAGE_NAME.app

import android.app.Application

class MainApplication : Application() {
    lateinit var container: AppContainer
        private set
    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
EOF
  fi
}

write_tests() {
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then
    cat > "$PROJECT_DIR/app/src/test/kotlin/$PACKAGE_PATH/ExampleUnitTest.kt" <<EOF
package $PACKAGE_NAME

import org.junit.Assert.assertEquals
import org.junit.Test

class ExampleUnitTest {
    @Test fun additionIsCorrect() { assertEquals(4, 2 + 2) }
}
EOF
  fi
  if [ "$TESTS" = "instrumented" ] || [ "$TESTS" = "both" ]; then
    cat > "$PROJECT_DIR/app/src/androidTest/kotlin/$PACKAGE_PATH/ExampleInstrumentedTest.kt" <<EOF
package $PACKAGE_NAME

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ExampleInstrumentedTest {
    @Test fun packageNameIsCorrect() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("$PACKAGE_NAME", context.packageName)
    }
}
EOF
  fi
}

write_extras() {
  cat > "$PROJECT_DIR/.gitignore" <<'EOF'
.gradle/
build/
**/build/
local.properties
.idea/
*.iml
EOF
  if contains_extra readme; then
    cat > "$PROJECT_DIR/README.md" <<EOF
# $APP_NAME

Native Android/Kotlin project generated by cAP.
EOF
  fi
  if contains_extra ci && [ "$CI_PROVIDER" = "github" ]; then
    mkdir -p "$PROJECT_DIR/.github/workflows"
    cat > "$PROJECT_DIR/.github/workflows/android.yml" <<EOF
name: Android
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: '17'
          cache: gradle
      - run: chmod +x gradlew
      - run: sdkmanager "platforms;android-$COMPILE_SDK" "build-tools;$BUILD_TOOLS_VERSION"
      - run: ./gradlew $GRADLE_TASKS --no-daemon
EOF
  elif contains_extra ci; then
    cat > "$PROJECT_DIR/.gitlab-ci.yml" <<'EOF'
stages: [build]
android-build:
  stage: build
  tags: [android]
  script:
    - chmod +x gradlew
EOF
    printf '    - ./gradlew %s --no-daemon\n' "$GRADLE_TASKS" >> "$PROJECT_DIR/.gitlab-ci.yml"
  fi
  cat > "$PROJECT_DIR/.cap-generated" <<EOF
app=$APP_NAME
package=$PACKAGE_NAME
architecture=$ARCH_NAME
agp=$AGP_VERSION
gradle=$GRADLE_VERSION
EOF
}

run_gradlew() {
  "$GRADLEW_CMD" -p "$PROJECT_DIR" --no-daemon "$@"
}

run_step '写入 Wrapper bootstrap' write_wrapper_bootstrap || exit 1
run_step "生成 Gradle $GRADLE_VERSION Wrapper" generate_wrapper || exit 1
if [ -n "$GRADLEW_OVERRIDE" ]; then
  GRADLEW_CMD="$GRADLEW_OVERRIDE"
else
  [ -x "$PROJECT_DIR/gradlew" ] || die '验证 Gradle Wrapper' "$PROJECT_DIR/gradlew NOT FOUND 或不可执行"
  GRADLEW_CMD="$PROJECT_DIR/gradlew"
fi
run_step '写入 Kotlin DSL' write_build_files || exit 1
run_step '创建架构目录' create_structure || exit 1
run_step '写入 Manifest/resources' write_manifest_resources || exit 1
run_step '写入状态源码' write_state_source || exit 1
if [ "$UI" = "compose" ]; then run_step '写入 Compose 源码' write_compose_sources || exit 1; else run_step '写入 Views 源码' write_views_sources || exit 1; fi
run_step '写入基础设施源码' write_infrastructure_sources || exit 1
run_step '写入测试源码' write_tests || exit 1
run_step '写入附加文件' write_extras || exit 1
run_step "$ASSEMBLE_TASK" run_gradlew ":app:$ASSEMBLE_TASK" || exit 1
if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then run_step 'Unit Tests' run_gradlew ":app:$UNIT_TASK" || exit 1; fi
if [ "$TESTS" = "instrumented" ] || [ "$TESTS" = "both" ]; then run_step 'Instrumented test APK 编译' run_gradlew ":app:$INSTRUMENTED_TASK" || exit 1; fi
if [ "$LINT" = "android" ]; then run_step 'Android Lint' run_gradlew ":app:$LINT_TASK" || exit 1; fi

printf '\nPhase 2 最终结果\n'
printf '工程路径: %s\nApplication ID: %s\nminSdk: %s\ncompileSdk/targetSdk: %s/%s\n' "$PROJECT_DIR" "$PACKAGE_NAME" "$MIN_SDK" "$COMPILE_SDK" "$TARGET_SDK"
printf 'UI: %s\n架构: %s\n状态: %s\n网络: %s\n存储: %s\nDI: %s\n测试: %s\nLint: %s\n附加项: %s\n' "$UI" "$ARCH_NAME" "$STATE" "$NET" "$STORAGE" "$DI" "$TESTS" "$LINT" "${EXTRAS:-none}"
print_counts
printf '构建命令: cd %q && ./gradlew :app:%s\n' "$PROJECT_DIR" "$ASSEMBLE_TASK"
