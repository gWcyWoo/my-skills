---
name: cip
description: Use when creating a new standard native iOS/Swift Xcode project with guided company-style scaffolding. `cIP` = create iOS Project. 触发于 "cip"、"cIP"、"create ios project"、"创建 iOS 工程"、"新建原生 Swift/Xcode 项目"。
---

<role>
cIP 在 MAIN session 运行，按 cFP 的两阶段纪律从零创建原生 iOS/Swift 工程：Phase 1 确认目录和 Xcode 工具链，Phase 2 逐题收集选项后用 XcodeGen 做确定性脚手架。每个决策都由用户回复编号；主会话只提问、调用脚本、转述结果，文件生成和验证交给脚本。
</role>

<context>
## 固定技术边界
- 只创建原生 iOS 工程；不创建 Flutter、React Native 或跨端工程。
- 必须在 macOS 上使用完整 Xcode。只安装 Command Line Tools、未接受 Xcode license 或 Xcode 不可用时，停止并显示原始错误。
- 使用 XcodeGen 从 `project.yml` 生成 `.xcodeproj`。XcodeGen 缺失时，必须先让用户用编号明确选择是否通过 Homebrew 安装。
- 自定义 Xcode 通过当前命令的 `DEVELOPER_DIR=<Xcode.app>/Contents/Developer` 使用；不调用 `sudo xcode-select -s`，不修改系统全局选择。
- 默认只提供 Apple 原生实现：SwiftUI/UIKit、URLSession、UserDefaults/SwiftData、手工依赖注入。不要擅自增加第三方 SDK。

## 输出纪律
- 每个逻辑步骤打印 `步骤标签... done`；失败打印 `步骤标签... FAILED` 和原始原因。
- 每个 Phase 结束打印成功/失败计数和关键产物。
- 所有菜单使用 prose 编号，不调用 `request_user_input` 或其他选择题工具。
- 裸文本、混合格式或缺少编号的回复无效；重显当前菜单，不猜测用户意图。
</context>

<instructions>
## Phase 1 — 环境与目录

1. 确认工程根目录，显示：`1. 当前目录 (<pwd>)`、`2. 指定绝对路径`。用户选择后回显 `PROJECT_DIR`，打印 `工程目录确认... done`。
2. 运行 `bash ~/.agents/skills/cip/script/detect.sh`，原样转述 macOS、Homebrew、active developer directory、Xcode、Swift、XcodeGen、SwiftLint 和已安装的 Xcode.app。
3. 选择 Xcode：
   - active Xcode 可用：`1. 使用当前 Xcode (<version>)`、`2. 使用其它 Xcode.app`。
   - active Xcode 不可用但检测到其它 Xcode.app：只显示检测到的路径编号，仍要求用户选编号。
   - 用户选择其它 Xcode.app 后，校验绝对路径及 `<path>/Contents/Developer/usr/bin/xcodebuild`，设置 `DEVELOPER_DIR=<path>/Contents/Developer`，再运行 `DEVELOPER_DIR=... bash ~/.agents/skills/cip/script/detect.sh` 复检。
   - 没有完整 Xcode 时停止；让用户安装/完成首次启动后重新运行 cIP，不自动打开 GUI，不自动接受 license。
4. 确认 XcodeGen：
   - 已安装：打印版本和 `XcodeGen 确认... done`。
   - 未安装但有 Homebrew：显示 `1. brew install xcodegen`、`2. 停止，我手动安装`；选 1 后运行 `bash ~/.agents/skills/cip/script/install.sh xcodegen`。
   - Homebrew 也缺失：停止并显示缺失边界，不执行网络安装脚本。
5. 打印 Phase 1 汇总：`PROJECT_DIR`、`DEVELOPER_DIR`（active 时写 `active`）、Xcode/Swift/XcodeGen 版本、成功/失败计数。

## Phase 2 — 工程脚手架

逐题显示编号菜单；每题只接受编号，含自定义文本的选项只接受 `编号 空格 文本`。

6. 按顺序收集：
   - Q1 工程/Target 名：`1. 使用目录名`、`2. 自定义输入`。只接受 `[A-Za-z][A-Za-z0-9_]*`。
   - Q2 Bundle ID：`1. com.example.<小写工程名>`、`2. 自定义输入`。必须至少两段，点分段不能为空。
   - Q3 最低 iOS：`1. 17.0`、`2. 自定义输入`。只接受数字版本；SwiftData 要求 iOS 17.0+。
   - Q4 设备：`1. iPhone`、`2. iPad`、`3. Universal`。
   - Q5 UI：`1. SwiftUI`、`2. UIKit`。SwiftUI 要求 iOS 14.0+。
   - Q6 架构（浏览式）：`1. Feature-first MVVM`、`2. Clean Architecture 3层`、`3. Layer-first MVVM`、`4. MVC`。用户回复编号后运行 `bash ~/.agents/skills/cip/script/show_arch.sh <n>`，再显示 `1. 确认`、`2. 返回架构菜单`；循环到确认，记录 `ARCH`。
   - Q7 网络：`1. URLSession`、`2. 不加`。
   - Q8 持久化：`1. UserDefaults`、`2. SwiftData`、`3. 不加`。
   - Q9 依赖注入：`1. 手工 AppContainer`、`2. 不加`。
   - Q10 测试：`1. Unit Tests`、`2. UI Tests`、`3. 两者`、`4. 不加`。
   - Q11 Lint：`1. SwiftLint`、`2. 不加`。若选 SwiftLint 且检测不到，显示 `1. brew install swiftlint`、`2. 返回重选`；选 1 后运行 `bash ~/.agents/skills/cip/script/install.sh swiftlint`。
   - Q12 附加项（多选，逗号分隔，可空）：`1. README`、`2. CI`、`3. xcconfig`、`4. l10n`、`5. 示例页`。选 CI 后再问 `1. GitHub Actions`、`2. GitLab CI`。
7. 把答案映射为环境变量：
   - `PROJECT_DIR`、`DEVELOPER_DIR` 来自 Phase 1。
   - `APP_NAME`=Q1，`BUNDLE_ID`=Q2，`DEPLOYMENT_TARGET`=Q3。
   - `DEVICES`=Q4 (`iphone|ipad|universal`)，`UI`=Q5 (`swiftui|uikit`)，`ARCH`=Q6 (`1..4`)。
   - `NET`=Q7 (`urlsession|none`)，`STORAGE`=Q8 (`userdefaults|swiftdata|none`)，`DI`=Q9 (`manual|none`)。
   - `TESTS`=Q10 (`unit|ui|both|none`)，`LINT`=Q11 (`swiftlint|none`)。
   - `EXTRAS`=Q12（逗号：`readme,ci,xcconfig,l10n,sample`），`CI_PROVIDER=github|gitlab`。
8. 必须先用同一组环境变量加 `CIP_DRY_RUN=1` 运行 `bash ~/.agents/skills/cip/script/scaffold.sh`。显示计划后询问：`1. 执行`、`2. 返回修改选项`。只有用户回 `1` 才运行真实脚手架。
9. 真实脚手架依次生成目录和 Swift 源码、写 `project.yml`、生成 `.xcodeproj`、运行 SwiftLint（如选择）、执行无签名 Simulator build。任何已存在的受管路径都直接失败，不覆盖。
10. 打印 Phase 2 汇总：工程路径、Bundle ID、最低系统、设备、UI、架构、网络、持久化、DI、测试、lint、附加项、成功/失败计数，以及 `open <PROJECT_DIR>/<APP_NAME>.xcodeproj`。
</instructions>

<success_criteria>
- Phase 1 明确 `PROJECT_DIR`、Xcode/Swift/XcodeGen 和 active/custom `DEVELOPER_DIR`。
- Phase 2 的 Q1-Q12 全部由用户通过严格编号选择；架构先预览再确认；真实执行前完成 dry-run 和二次编号确认。
- `scaffold.sh` 不覆盖已有受管路径，生成 `project.yml`、原生 Swift 源码和 `.xcodeproj`。
- `xcodebuild` 对 `generic/platform=iOS Simulator` 的无签名 Debug build 成功；失败时保留原始错误。
</success_criteria>

<final_reminders>
P0 — 不自动选菜单，不解释用户的裸文本为选择。
P0 — 不修改全局 `xcode-select`，不自动处理 Xcode GUI/license。
P0 — 每步输出 `done|FAILED`，最后输出汇总。
P1 — 先 dry-run，再经编号确认真实执行。
P1 — 确定性文件生成只由 `script/scaffold.sh` 完成。
</final_reminders>
