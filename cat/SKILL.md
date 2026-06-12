---
name: cat
description: Prepare and execute Android/iOS client automation tests. Use when the user provides or plans to provide an APK, Android App Bundle, iOS .app/.ipa, and a test-case file or directory; Codex must confirm package/platform, verify Maestro, Appium, platform drivers, emulator/simulator/device, install and launch the app, then read and run the requested test cases.
---

# CAT

## Rules

- Complete gates in order.
- Ask only for missing required input; stop until the user answers.
- Do not read or execute test cases before Gate 6 passes.
- Request approval before installing tools, creating emulators/simulators, launching GUI apps, or writing outside the workspace.
- Treat Codex/OpenClaw as orchestration only; test actions must belong to Chrome DevTools, Maestro, Appium, or an explicit combination.
- Treat every setup, inspection, installation, launch, and verification command in this skill as internal execution detail. Do not show those commands to the user; show only concise labeled results, relevant output values, and blockers. This visibility rule does not apply to commands that come from the test-case file itself.
- For every internal command node, report clear Chinese progress/result lines only. Use the exact user-facing flow defined by each gate, such as `检查包路径: pass`, `确认包类型: Android 包`, `Maestro 检查: 已安装`, and `Appium 安装: 安装完毕`.

## Gate 1: App Package

Ask for:

```text
请输入包路径:
```

After receiving the path, infer platform internally by suffix. Do not show this mapping to the user unless there is ambiguity:

```text
.apk  -> Android
.aab  -> Android bundle; ask for APK conversion/build path
.app  -> iOS simulator
.ipa  -> iOS real device unless user confirms another install path
.zip  -> inspect or ask whether it contains Payload/*.app
other -> ask platform and install method
```

Verify the path internally with `test -e <package-path>`. Do not show the command to the user.

If the path exists, show:

```text
检查包路径: pass
```

If the path does not exist, show:

```text
检查包路径: 包路径错误，请重新输入
```

Then ask `请输入包路径:` again and repeat Gate 1 path verification.

Resolve absolute path and record:

```text
package_path
platform
package_kind
ambiguity_or_blocker
```

After path verification passes, confirm package type from the internal suffix inference.

Show one of:

```text
确认包类型: Android 包
确认包类型: iOS 包
确认包类型: 无法确认，请输入平台和安装方式
```

Discover the package/app id internally without blocking setup. Do not show inspection commands or raw inspection steps to the user.

Internal safety rules:

- Treat the original package as read-only. Any operation that may unpack, rewrite, normalize, or otherwise materialize package contents must operate on a temporary copy, never the original path.
- Android APK inspections may read the original APK directly.
- iOS package analysis must use a workspace-local inspection copy under `./cat-package-inspect-<timestamp>/`. For `.ipa` or `.zip`, copy the package there and unpack only the copy. For `.app`, copy the app bundle there and read the copied `Info.plist`. After confirmation or blocker handling, delete the copied package/bundle and extracted contents.

Android package id flow:

1. Show:

   ```text
   检查 - apkanalyzer(用于获取包 id): 检查中
   ```

2. Internally run `command -v apkanalyzer`.

   If missing, show:

   ```text
   检查 - apkanalyzer(用于获取包 id): 未安装
   ```

   If found, show:

   ```text
   检查 - apkanalyzer(用于获取包 id): 已安装
   分析包 id: 分析中
   ```

   Then internally run `apkanalyzer manifest application-id <apk-path>`.

3. If `apkanalyzer` is missing or cannot identify the package id, show:

   ```text
   检查 - aapt(用于获取包 id): 检查中
   ```

   Internally run `command -v aapt`.

   If missing, show:

   ```text
   检查 - aapt(用于获取包 id): 未安装
   ```

   If found, show:

   ```text
   检查 - aapt(用于获取包 id): 已安装
   分析包 id: 分析中
   ```

   Then internally run `aapt dump badging <apk-path>` and extract the package name.

4. If both tools are missing or installed tools cannot identify the package id, stop package-id discovery and ask:

   ```text
   未能自动获取包 id，请输入包 id:
   ```

   After the user enters a package id, do not ask for another confirmation. Show:

   ```text
   用户确认包 id: <package_name>
   ```

5. When a package id is automatically found, show it and wait for user confirmation:

   ```text
   分析包 id: <package_name>，请确认是否正确
   ```

   After the user confirms, show:

   ```text
   用户确认包 id: <package_name>
   ```

   If the user says it is incorrect, ask `请输入包 id:`. After the user enters a package id, do not ask for another confirmation; show `用户确认包 id: <package_name>`.

iOS bundle id flow:

If the package is `.ipa` and the target is simulator, stop before copying and ask for a simulator-compatible `.app`.

1. Show:

   ```text
   复制 iOS 包用于分析: 进行中
   ```

2. Internally create `./cat-package-inspect-<timestamp>/`, copy the package or bundle there, and inspect only the copy.

3. Show:

   ```text
   复制 iOS 包用于分析: 完成
   分析包 id: 分析中
   ```

4. Internally read `CFBundleIdentifier` from the copied `Info.plist`. For `.ipa` or `.zip`, unpack the copy first, locate `Payload/*.app/Info.plist`, then read `CFBundleIdentifier`.

5. If the bundle id is found, show it and wait for user confirmation:

   ```text
   分析包 id: <bundle_id>，请确认是否正确
   ```

   After the user confirms, show:

   ```text
   用户确认包 id: <bundle_id>
   ```

   If the user says it is incorrect, ask `请输入包 id:`. After the user enters a bundle id, do not ask for another confirmation; show `用户确认包 id: <bundle_id>`.

6. If the bundle id cannot be found, ask:

   ```text
   未能自动获取包 id，请输入包 id:
   ```

   After the user enters a bundle id, do not ask for another confirmation. Show:

   ```text
   用户确认包 id: <bundle_id>
   ```

7. Always delete the copied package/bundle and extracted contents after confirmation or blocker handling, then show:

   ```text
   清理 iOS 分析副本: 完成
   ```

## Gate 2: Test Case Input

Ask for:

```text
请输入测试用例目录或者路径
```

Verify existence and classify the input shape internally:

```bash
test -e <test-case-path>
test -f <test-case-path>
test -d <test-case-path>
```

Rules:

- If `test_case_path` is a regular file, record it as a single test-case file.
- If `test_case_path` is a directory, record it as a test-case directory. Do not read directory files yet.
- If `test_case_path` is neither a regular file nor a directory, stop and ask for a valid file or directory.

Record:

```text
test_case_path
test_case_shape: file | directory
```

Do not read file contents.

## Gate 3: Maestro

Check Maestro internally. Do not show commands.

Show:

```text
Maestro 检查: 检查中
```

Internal check commands:

```bash
command -v maestro
maestro --version
java -version
```

If `maestro --version` fails only because sandbox access to `~/.maestro` is blocked, retry outside the sandbox with approval.

If Maestro is found, show:

```text
Maestro 检查: 已安装
```

If Maestro is missing, show:

```text
Maestro 检查: 未安装
```

Then ask before installing. After approval, show:

```text
Maestro 安装: 安装中
```

Install internally with one of:

```bash
curl -fsSL "https://get.maestro.mobile.dev" | bash
```

or:

```bash
brew tap mobile-dev-inc/tap
brew install mobile-dev-inc/tap/maestro
```

Verify after install internally:

```bash
maestro --version
maestro --help
```

If installation and verification pass, show:

```text
Maestro 安装: 安装完毕
```

If installation or verification fails, show:

```text
Maestro 安装: 失败，<blocker>
```

If Java is missing or below 17, stop and ask whether to install or switch Java.

Record:

```text
maestro_path
maestro_version
java_version
maestro_status
```

## Gate 4: Appium

Check Appium internally. Do not show commands.

Show:

```text
Appium 检查: 检查中
```

Internal check commands:

```bash
command -v appium
appium --version
appium driver list --installed
```

If Appium is found, show:

```text
Appium 检查: 已安装
```

If Appium is missing, show:

```text
Appium 检查: 未安装
```

Then ask before installing. After approval, show:

```text
Appium 安装: 安装中
```

Install internally:

```bash
npm install -g appium
```

Verify Appium after install internally. If installation and verification pass, show:

```text
Appium 安装: 安装完毕
```

If installation or verification fails, show:

```text
Appium 安装: 失败，<blocker>
```

Install missing driver for the platform internally after any required approval. Show:

```text
Appium 驱动检查: 检查中
```

Android internal driver commands:

```bash
appium driver install uiautomator2
appium driver doctor uiautomator2
```

iOS internal driver commands:

```bash
appium driver install xcuitest
appium driver doctor xcuitest
```

If both platforms are in scope, verify both drivers.

If the required driver is installed and doctor passes, show:

```text
Appium 驱动检查: 就绪
```

If driver installation or doctor fails, show:

```text
Appium 驱动检查: 阻塞，<blocker>
```

Record:

```text
appium_path
appium_version
required_driver
driver_status
doctor_status
```

## Gate 5: Target Device

Use the platform from Gate 1.

Android internal checks:

```bash
command -v adb
adb devices
command -v emulator
emulator -list-avds
```

If `adb devices` has an active `device`, use it.

If no device is active and one AVD exists, ask before opening it. After approval, run internally:

```bash
emulator -avd <avd-name>
adb wait-for-device
adb devices
```

If no device is active and multiple AVDs exist, ask the user to choose.

If no AVD exists, ask whether to create/install an Android emulator. Stop if the user declines.

iOS simulator internal checks:

```bash
command -v xcrun
xcrun simctl list devices available
xcrun simctl list devices booted
```

If a simulator is booted, use it.

If none is booted and one available simulator fits, ask before booting it. After approval, run internally:

```bash
xcrun simctl boot <simulator-udid>
xcrun simctl list devices booted
```

If no simulator/runtime exists, ask whether to install an iOS simulator runtime through Xcode. Stop if the user declines.

If GUI launch is needed, request approval. After approval, run internally:

```bash
open -a Simulator
```

iOS real-device internal checks:

```text
verify device is connected
verify device is trusted
verify Developer Mode and signing prerequisites
```

Do not treat a simulator as a substitute for a confirmed real-device `.ipa` flow.

Record:

```text
target_type
target_id
target_name
target_status
```

## Gate 6: Install And Launch App

Android APK internal install and launch:

```bash
adb devices
adb install -r <apk-path>
adb shell pm list packages
adb shell pm path <package-name>
adb shell monkey -p <package-name> 1
```

If `<package-name>` is unknown, first use any already-installed APK inspection tool from Gate 1. If still unknown after install, inspect installed packages internally:

```bash
adb shell pm list packages
```

Ask the user for `package_name` when the package cannot be identified confidently. Do not install Android build-tools only to derive it.

If clean reinstall is requested, run internally:

```bash
adb uninstall <package-name>
adb install <apk-path>
```

If activity is required and unknown, run internally:

```bash
adb shell cmd package resolve-activity --brief <package-name>
```

Use `aapt dump badging <apk-path>` only if `aapt` already exists and device-side activity resolution is insufficient.

iOS simulator `.app` internal install and launch:

```bash
xcrun simctl list devices booted
xcrun simctl install booted <app-path>
xcrun simctl get_app_container booted <bundle-id>
xcrun simctl launch booted <bundle-id>
```

iOS real-device `.ipa` internal install and launch checks:

```text
confirm signed IPA matches target device/account
install through configured Appium XCUITest or Xcode device tooling
verify bundle launch through the same real-device automation path
```

Do not mark Gate 6 complete until install and launch are proven.

Record:

```text
platform
package_path
package_name_or_bundle_id
target_id
install_status
launch_status
blocker
```

## Gate 7: Read And Run Test Cases

Enter this gate only after Gate 6 proves the app is installed and launchable.

If `test_case_shape` is `file`:

- Build a single-file queue from the specified test-case file.

If `test_case_shape` is `directory`:

- Build a deterministic queue of the directory's immediate regular files, sorted by path. Do not recurse unless the user explicitly requests recursive discovery.
- If the directory contains no regular files, stop and ask the user for a valid test-case file or directory.

Run the queue:

- Before processing the first queued file, create or overwrite `./test_result.md` with this header:

  ```text
  id | 用例名 | 测试结果 | 原因
  ```

- Read exactly one queued file at a time.
- For each file, call the `/goal` skill with an objective to execute that file's test cases against the prepared app and target.
- Do not read the next file until the current file's `/goal` run is complete and its result is recorded.
- After each `/goal` run, append one row to `./test_result.md` before continuing, regardless of whether the result is passed, failed, or blocked:

  ```text
  id | 用例名 | 测试结果 | 原因
  ```

- Use a stable `id` per case. If the test case file provides an id, use it; otherwise use the 1-based queue index.
- `用例名` is the test case name from the file or `/goal` result; if no case-level name is available, use the test-case file path.
- `测试结果` must be one of `通过`, `失败`, or `阻塞`.
- `原因` must be `通过` for passed cases, or the concrete failure/blocker reason from the `/goal` result for failed or blocked cases.
- Continue to the next queued file even after blocked or failed results.
- Stop only after every queued file has been processed.

Record:

```text
test_case_shape
test_case_files
current_test_case_file
per_file_goal_status
test_result_path
passed_files
failed_files
completed_files
blocker
```

## Stop After Gate 7

Summarize:

```text
package_path
platform
app_id
test_case_path
maestro_status
appium_status
driver_status
target_status
install_status
launch_status
test_case_shape
passed_files
completed_files
failed_files
test_result_path
blocker
```

Stop after all selected test-case files have been processed. Always point to `./test_result.md`.
