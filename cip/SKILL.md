---
name: cip
description: Create a native iOS/Swift project using the bundled XcodeGen scaffolding.
---

# cIP

使用 XcodeGen 创建原生 iOS/Swift 工程。

## 交互与完成边界

复用用户已给出的目录、工具链和技术选择。仅询问影响工程身份或技术栈的缺项；可合并提问并接受明确自然语言，不要求逐题回编号。用户要求推荐或使用默认值时，按现有脚本支持的选项给出一套选择。

使用现有 detect/install/scaffold 脚本。先 dry-run 检查路径和选项；已授权创建且方案明确就执行，只有未决选择、覆盖已有文件或未授权的全局工具安装才需确认。不要覆盖已有受管文件。

脚本输出留在执行记录中；对话报告关键选择、失败原因、产物和验证结果，不逐行复述 done。脚手架已运行的检查不重复执行；不能把生成测试文件或编译测试 APK 声称为设备测试通过。

## 工具链与执行

- 用 `script/detect.sh` 检查完整 Xcode、Swift、XcodeGen。仅 Command Line Tools 不足；Xcode license/首次启动由用户完成。
- 使用已明确的可用 Xcode。自定义安装只设置命令级 `DEVELOPER_DIR`，不修改全局 `xcode-select`，不自动打开 GUI。
- XcodeGen 或所选 SwiftLint 缺失时，确认必要安装范围后用 `script/install.sh xcodegen|swiftlint`；无 Homebrew 时报告缺项，不自行运行网络安装脚本。
- 默认使用 Apple 原生实现，不擅自增加第三方 SDK。
- 收集选项及环境变量时读 [options.md](references/options.md)。以同一组环境变量运行 `CIP_DRY_RUN=1 bash ~/.agents/skills/cip/script/scaffold.sh`，再运行真实脚手架。
- 保留所选 lint 和脚本的无签名 Simulator Debug build。交付工程路径、Bundle ID、所选栈与结果；build 通过不等于 UI Tests 已运行。
