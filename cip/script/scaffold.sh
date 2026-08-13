#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
. "$ROOT/lib/common.sh"
. "$ROOT/rule/architectures.sh"

PROJECT_DIR="${PROJECT_DIR:-}"
APP_NAME="${APP_NAME:-}"
BUNDLE_ID="${BUNDLE_ID:-}"
DEPLOYMENT_TARGET="${DEPLOYMENT_TARGET:-17.0}"
DEVICES="${DEVICES:-universal}"
UI="${UI:-swiftui}"
ARCH="${ARCH:-1}"
NET="${NET:-urlsession}"
STORAGE="${STORAGE:-none}"
DI="${DI:-manual}"
TESTS="${TESTS:-unit}"
LINT="${LINT:-none}"
EXTRAS="${EXTRAS:-}"
CI_PROVIDER="${CI_PROVIDER:-github}"
DRY_RUN="${CIP_DRY_RUN:-0}"
XCODEGEN_CMD="${XCODEGEN_CMD:-xcodegen}"
XCODEBUILD_CMD="${XCODEBUILD_CMD:-xcodebuild}"

validate_choice() {
  local value="$1"
  shift
  local allowed
  for allowed in "$@"; do
    [ "$value" = "$allowed" ] && return 0
  done
  return 1
}

contains_extra() {
  case ",$EXTRAS," in
    *",$1,"*) return 0 ;;
    *) return 1 ;;
  esac
}

guard_path() {
  [ ! -e "$PROJECT_DIR/$1" ] || die '覆盖保护' "已存在受管路径: $PROJECT_DIR/$1"
}

version_major() {
  printf '%s\n' "${1%%.*}"
}

[ -n "$PROJECT_DIR" ] || die '参数校验' 'PROJECT_DIR 不能为空'
case "$PROJECT_DIR" in /*) ;; *) die '参数校验' 'PROJECT_DIR 必须是绝对路径' ;; esac
[[ "$APP_NAME" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]] || die '参数校验' 'APP_NAME 必须匹配 [A-Za-z][A-Za-z0-9_]*'
APP_TYPE_NAME="$(printf '%s' "${APP_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${APP_NAME:1}"
[[ "$BUNDLE_ID" =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ ]] || die '参数校验' 'BUNDLE_ID 必须是至少两段的点分标识符'
[[ "$DEPLOYMENT_TARGET" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || die '参数校验' 'DEPLOYMENT_TARGET 必须是数字版本'
validate_choice "$DEVICES" iphone ipad universal || die '参数校验' 'DEVICES 必须是 iphone|ipad|universal'
validate_choice "$UI" swiftui uikit || die '参数校验' 'UI 必须是 swiftui|uikit'
architecture_name "$ARCH" >/dev/null || die '参数校验' 'ARCH 必须是 1|2|3|4'
validate_choice "$NET" urlsession none || die '参数校验' 'NET 必须是 urlsession|none'
validate_choice "$STORAGE" userdefaults swiftdata none || die '参数校验' 'STORAGE 必须是 userdefaults|swiftdata|none'
validate_choice "$DI" manual none || die '参数校验' 'DI 必须是 manual|none'
validate_choice "$TESTS" unit ui both none || die '参数校验' 'TESTS 必须是 unit|ui|both|none'
validate_choice "$LINT" swiftlint none || die '参数校验' 'LINT 必须是 swiftlint|none'
validate_choice "$CI_PROVIDER" github gitlab || die '参数校验' 'CI_PROVIDER 必须是 github|gitlab'

MAJOR="$(version_major "$DEPLOYMENT_TARGET")"
if [ "$UI" = "swiftui" ] && [ "$MAJOR" -lt 14 ]; then
  die '版本兼容校验' 'SwiftUI 工程要求 iOS 14.0+'
fi
if [ "$STORAGE" = "swiftdata" ] && [ "$MAJOR" -lt 17 ]; then
  die '版本兼容校验' 'SwiftData 要求 iOS 17.0+'
fi

ARCH_NAME="$(architecture_name "$ARCH")"
HOME_REL="$(architecture_home_dir "$ARCH" "$UI")"
INFRA_REL="$(architecture_infrastructure_dir "$ARCH")"
case "$DEVICES" in
  iphone) DEVICE_FAMILY='1' ;;
  ipad) DEVICE_FAMILY='2' ;;
  universal) DEVICE_FAMILY='1,2' ;;
esac

if [ "$DRY_RUN" = "1" ]; then
  printf 'cIP 脚手架预览\n'
  printf 'PROJECT_DIR=%s\nAPP_NAME=%s\nBUNDLE_ID=%s\n' "$PROJECT_DIR" "$APP_NAME" "$BUNDLE_ID"
  printf 'DEPLOYMENT_TARGET=%s\nDEVICES=%s\nUI=%s\n' "$DEPLOYMENT_TARGET" "$DEVICES" "$UI"
  printf 'ARCH=%s (%s)\nNET=%s\nSTORAGE=%s\nDI=%s\n' "$ARCH" "$ARCH_NAME" "$NET" "$STORAGE" "$DI"
  printf 'TESTS=%s\nLINT=%s\nEXTRAS=%s\nCI_PROVIDER=%s\n' "$TESTS" "$LINT" "${EXTRAS:-none}" "$CI_PROVIDER"
  printf '计划: 校验覆盖保护 → 生成 Swift 源码/project.yml → xcodegen generate → SwiftLint(如选) → Simulator build\n'
  exit 0
fi

[ "$(uname -s)" = "Darwin" ] || die '系统校验' '仅支持 macOS'
if [ -n "${DEVELOPER_DIR:-}" ]; then
  export DEVELOPER_DIR
fi
command -v "$XCODEGEN_CMD" >/dev/null 2>&1 || die 'XcodeGen 检测' "$XCODEGEN_CMD NOT FOUND"
command -v "$XCODEBUILD_CMD" >/dev/null 2>&1 || die 'Xcode 检测' "$XCODEBUILD_CMD NOT FOUND"
if [ "$LINT" = "swiftlint" ]; then
  command -v swiftlint >/dev/null 2>&1 || die 'SwiftLint 检测' 'swiftlint NOT FOUND'
fi

run_step '创建工程根目录' mkdir -p "$PROJECT_DIR" || exit 1
guard_path 'project.yml'
guard_path "${APP_NAME}.xcodeproj"
guard_path "Sources/${APP_NAME}"
guard_path '.cip-generated'
guard_path '.gitignore'
guard_path '.build/DerivedData'
if [ "$LINT" = "swiftlint" ]; then guard_path '.swiftlint.yml'; fi
if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then guard_path "Tests/${APP_NAME}Tests"; fi
if [ "$TESTS" = "ui" ] || [ "$TESTS" = "both" ]; then guard_path "UITests/${APP_NAME}UITests"; fi
if contains_extra readme; then guard_path 'README.md'; fi
if contains_extra xcconfig; then guard_path 'Configs'; fi
if contains_extra l10n; then guard_path 'Resources'; fi
if contains_extra ci && [ "$CI_PROVIDER" = "github" ]; then guard_path '.github/workflows/ios.yml'; fi
if contains_extra ci && [ "$CI_PROVIDER" = "gitlab" ]; then guard_path '.gitlab-ci.yml'; fi

create_structure() {
  local app_root="$PROJECT_DIR/Sources/$APP_NAME"
  case "$ARCH" in
    1) mkdir -p "$app_root/App" "$app_root/Core/Networking" "$app_root/Core/Persistence" "$app_root/Features/Home/Models" "$app_root/Features/Home/ViewModels" "$app_root/Features/Home/Views" ;;
    2) mkdir -p "$app_root/App" "$app_root/Core" "$app_root/Features/Home/Data" "$app_root/Features/Home/Domain" "$app_root/Features/Home/Presentation" ;;
    3) mkdir -p "$app_root/App" "$app_root/Data/Networking" "$app_root/Data/Persistence" "$app_root/Domain" "$app_root/Presentation" ;;
    4) mkdir -p "$app_root/App" "$app_root/Models/Services/Networking" "$app_root/Models/Services/Persistence" "$app_root/Views" "$app_root/Controllers" ;;
  esac
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then mkdir -p "$PROJECT_DIR/Tests/${APP_NAME}Tests"; fi
  if [ "$TESTS" = "ui" ] || [ "$TESTS" = "both" ]; then mkdir -p "$PROJECT_DIR/UITests/${APP_NAME}UITests"; fi
}

write_project_spec() {
  cat > "$PROJECT_DIR/project.yml" <<YAML
name: $APP_NAME
configs:
  Debug: debug
  Release: release
targets:
  $APP_NAME:
    type: application
    platform: iOS
    deploymentTarget: "$DEPLOYMENT_TARGET"
    sources:
      - path: Sources/$APP_NAME
YAML
  if contains_extra l10n; then
    cat >> "$PROJECT_DIR/project.yml" <<YAML
      - path: Resources
YAML
  fi
  if contains_extra xcconfig; then
    cat >> "$PROJECT_DIR/project.yml" <<YAML
    configFiles:
      Debug: Configs/Debug.xcconfig
      Release: Configs/Release.xcconfig
YAML
  fi
  cat >> "$PROJECT_DIR/project.yml" <<YAML
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: $BUNDLE_ID
        PRODUCT_NAME: $APP_NAME
        SWIFT_VERSION: "5.0"
        TARGETED_DEVICE_FAMILY: "$DEVICE_FAMILY"
        GENERATE_INFOPLIST_FILE: "YES"
        INFOPLIST_KEY_CFBundleDisplayName: $APP_NAME
        INFOPLIST_KEY_UILaunchScreen_Generation: "YES"
YAML
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then
    cat >> "$PROJECT_DIR/project.yml" <<YAML
  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    deploymentTarget: "$DEPLOYMENT_TARGET"
    sources:
      - path: Tests/${APP_NAME}Tests
    dependencies:
      - target: $APP_NAME
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: ${BUNDLE_ID}.tests
        GENERATE_INFOPLIST_FILE: "YES"
YAML
  fi
  if [ "$TESTS" = "ui" ] || [ "$TESTS" = "both" ]; then
    cat >> "$PROJECT_DIR/project.yml" <<YAML
  ${APP_NAME}UITests:
    type: bundle.ui-testing
    platform: iOS
    deploymentTarget: "$DEPLOYMENT_TARGET"
    sources:
      - path: UITests/${APP_NAME}UITests
    dependencies:
      - target: $APP_NAME
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: ${BUNDLE_ID}.uitests
        GENERATE_INFOPLIST_FILE: "YES"
YAML
  fi
  cat >> "$PROJECT_DIR/project.yml" <<YAML
schemes:
  $APP_NAME:
    build:
      targets:
        $APP_NAME: all
    run:
      config: Debug
YAML
  if [ "$TESTS" != "none" ]; then
    cat >> "$PROJECT_DIR/project.yml" <<YAML
    test:
      config: Debug
      gatherCoverageData: true
      targets:
YAML
    if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then
      printf '        - %sTests\n' "$APP_NAME" >> "$PROJECT_DIR/project.yml"
    fi
    if [ "$TESTS" = "ui" ] || [ "$TESTS" = "both" ]; then
      printf '        - %sUITests\n' "$APP_NAME" >> "$PROJECT_DIR/project.yml"
    fi
  fi
}

write_app_sources() {
  local app_root="$PROJECT_DIR/Sources/$APP_NAME"
  local home_dir="$app_root/$HOME_REL"
  if [ "$UI" = "swiftui" ]; then
    if [ "$STORAGE" = "swiftdata" ]; then
      cat > "$app_root/App/${APP_NAME}App.swift" <<SWIFT
import SwiftData
import SwiftUI

@main
struct ${APP_TYPE_NAME}App: App {
    var body: some Scene {
        WindowGroup { HomeView() }
            .modelContainer(PersistenceController.container)
    }
}
SWIFT
    else
      cat > "$app_root/App/${APP_NAME}App.swift" <<SWIFT
import SwiftUI

@main
struct ${APP_TYPE_NAME}App: App {
    var body: some Scene {
        WindowGroup { HomeView() }
    }
}
SWIFT
    fi
    if contains_extra sample; then
      cat > "$home_dir/HomeView.swift" <<'SWIFT'
import SwiftUI

struct HomeView: View {
    @State private var count = 0

    var body: some View {
        VStack(spacing: 16) {
            Text("iOS project ready")
            Button("Count: \(count)") { count += 1 }
        }
        .padding()
    }
}
SWIFT
    else
      cat > "$home_dir/HomeView.swift" <<'SWIFT'
import SwiftUI

struct HomeView: View {
    var body: some View { Text("iOS project ready") }
}
SWIFT
    fi
  else
    cat > "$app_root/App/AppDelegate.swift" <<'SWIFT'
import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = UINavigationController(rootViewController: HomeViewController())
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}
SWIFT
    cat > "$home_dir/HomeViewController.swift" <<'SWIFT'
import UIKit

final class HomeViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let label = UILabel()
        label.text = "iOS project ready"
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }
}
SWIFT
  fi
}

write_optional_sources() {
  local app_root="$PROJECT_DIR/Sources/$APP_NAME"
  local infrastructure="$app_root/$INFRA_REL"
  if [ "$NET" = "urlsession" ]; then
    mkdir -p "$infrastructure/Networking"
    cat > "$infrastructure/Networking/NetworkClient.swift" <<'SWIFT'
import Foundation

protocol NetworkClient {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

struct URLSessionNetworkClient: NetworkClient {
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await URLSession.shared.data(for: request)
    }
}
SWIFT
  fi
  if [ "$STORAGE" = "userdefaults" ]; then
    mkdir -p "$infrastructure/Persistence"
    cat > "$infrastructure/Persistence/UserDefaultsStore.swift" <<'SWIFT'
import Foundation

struct UserDefaultsStore {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    func set(_ value: Any?, forKey key: String) { defaults.set(value, forKey: key) }
    func value(forKey key: String) -> Any? { defaults.object(forKey: key) }
}
SWIFT
  elif [ "$STORAGE" = "swiftdata" ]; then
    mkdir -p "$infrastructure/Persistence"
    cat > "$infrastructure/Persistence/PersistenceController.swift" <<'SWIFT'
import Foundation
import SwiftData

@Model
final class StoredItem {
    var createdAt: Date
    init(createdAt: Date = .now) { self.createdAt = createdAt }
}

enum PersistenceController {
    static let container: ModelContainer = {
        do {
            return try ModelContainer(for: StoredItem.self)
        } catch {
            fatalError("SwiftData container failed: \(error)")
        }
    }()
}
SWIFT
  fi
  if [ "$DI" = "manual" ]; then
    if [ "$NET" = "urlsession" ]; then
      cat > "$app_root/App/AppContainer.swift" <<'SWIFT'
struct AppContainer {
    let networkClient: any NetworkClient
    static let live = AppContainer(networkClient: URLSessionNetworkClient())
}
SWIFT
    else
      cat > "$app_root/App/AppContainer.swift" <<'SWIFT'
struct AppContainer {
    static let live = AppContainer()
}
SWIFT
    fi
  fi
}

write_tests() {
  if [ "$TESTS" = "unit" ] || [ "$TESTS" = "both" ]; then
    cat > "$PROJECT_DIR/Tests/${APP_NAME}Tests/${APP_NAME}Tests.swift" <<SWIFT
import XCTest
@testable import $APP_NAME

final class ${APP_TYPE_NAME}Tests: XCTestCase {
    func testSanity() { XCTAssertTrue(true) }
}
SWIFT
  fi
  if [ "$TESTS" = "ui" ] || [ "$TESTS" = "both" ]; then
    cat > "$PROJECT_DIR/UITests/${APP_NAME}UITests/${APP_NAME}UITests.swift" <<SWIFT
import XCTest

final class ${APP_TYPE_NAME}UITests: XCTestCase {
    func testLaunch() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 5))
    }
}
SWIFT
  fi
}

write_extras() {
  cat > "$PROJECT_DIR/.gitignore" <<'EOF'
.build/
DerivedData/
*.xcuserstate
xcuserdata/
EOF
  if [ "$LINT" = "swiftlint" ]; then
    cat > "$PROJECT_DIR/.swiftlint.yml" <<'YAML'
excluded:
  - .build
  - DerivedData
line_length: 120
YAML
  fi
  if contains_extra readme; then
    cat > "$PROJECT_DIR/README.md" <<EOF
# $APP_NAME

Native iOS project generated by cIP.
EOF
  fi
  if contains_extra xcconfig; then
    mkdir -p "$PROJECT_DIR/Configs"
    printf 'SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG\n' > "$PROJECT_DIR/Configs/Debug.xcconfig"
    printf 'SWIFT_COMPILATION_MODE = wholemodule\n' > "$PROJECT_DIR/Configs/Release.xcconfig"
  fi
  if contains_extra l10n; then
    mkdir -p "$PROJECT_DIR/Resources/en.lproj"
    printf '"app.title" = "%s";\n' "$APP_NAME" > "$PROJECT_DIR/Resources/en.lproj/Localizable.strings"
  fi
  if contains_extra ci && [ "$CI_PROVIDER" = "github" ]; then
    mkdir -p "$PROJECT_DIR/.github/workflows"
    cat > "$PROJECT_DIR/.github/workflows/ios.yml" <<EOF
name: iOS
on: [push, pull_request]
jobs:
  build:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - run: brew install xcodegen
      - run: xcodegen generate
      - run: xcodebuild -project ${APP_NAME}.xcodeproj -scheme ${APP_NAME} -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
EOF
  elif contains_extra ci; then
    cat > "$PROJECT_DIR/.gitlab-ci.yml" <<EOF
stages: [build]
ios-build:
  stage: build
  tags: [macos]
  script:
    - brew install xcodegen
    - xcodegen generate
    - xcodebuild -project ${APP_NAME}.xcodeproj -scheme ${APP_NAME} -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
EOF
  fi
  cat > "$PROJECT_DIR/.cip-generated" <<EOF
app=$APP_NAME
bundle_id=$BUNDLE_ID
architecture=$ARCH_NAME
EOF
}

generate_project() {
  cd "$PROJECT_DIR" && "$XCODEGEN_CMD" generate --spec project.yml --project "$PROJECT_DIR"
}

lint_project() {
  cd "$PROJECT_DIR" && swiftlint lint --config .swiftlint.yml
}

build_project() {
  cd "$PROJECT_DIR" && "$XCODEBUILD_CMD" -project "${APP_NAME}.xcodeproj" -scheme "$APP_NAME" -configuration Debug -destination 'generic/platform=iOS Simulator' -derivedDataPath .build/DerivedData CODE_SIGNING_ALLOWED=NO build
}

build_tests() {
  cd "$PROJECT_DIR" && "$XCODEBUILD_CMD" -project "${APP_NAME}.xcodeproj" -scheme "$APP_NAME" -configuration Debug -destination 'generic/platform=iOS Simulator' -derivedDataPath .build/DerivedData CODE_SIGNING_ALLOWED=NO build-for-testing
}

run_step '创建架构目录' create_structure || exit 1
run_step '写入 project.yml' write_project_spec || exit 1
run_step '写入应用源码' write_app_sources || exit 1
run_step '写入基础设施源码' write_optional_sources || exit 1
run_step '写入测试源码' write_tests || exit 1
run_step '写入附加文件' write_extras || exit 1
run_step '生成 Xcode 工程' generate_project || exit 1
if [ "$LINT" = "swiftlint" ]; then run_step 'SwiftLint 检查' lint_project || exit 1; fi
run_step 'Simulator Debug build' build_project || exit 1
if [ "$TESTS" != "none" ]; then run_step '测试 Target 编译' build_tests || exit 1; fi

printf '\nPhase 2 最终结果\n'
printf '工程路径: %s\nXcode 工程: %s/%s.xcodeproj\n' "$PROJECT_DIR" "$PROJECT_DIR" "$APP_NAME"
printf 'Bundle ID: %s\n最低 iOS: %s\n设备: %s\nUI: %s\n' "$BUNDLE_ID" "$DEPLOYMENT_TARGET" "$DEVICES" "$UI"
printf '架构: %s\n网络: %s\n持久化: %s\nDI: %s\n测试: %s\nLint: %s\n附加项: %s\n' "$ARCH_NAME" "$NET" "$STORAGE" "$DI" "$TESTS" "$LINT" "${EXTRAS:-none}"
print_counts
printf '打开工程: open %q\n' "$PROJECT_DIR/${APP_NAME}.xcodeproj"
