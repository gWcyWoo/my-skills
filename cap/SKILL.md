---
name: cap
description: Create a native Android/Kotlin project using the bundled company scaffolding.
---

# cAP

创建原生 Android/Kotlin 工程。

## 交互与完成边界

复用用户已给出的目录、工具链和技术选择。仅询问影响工程身份或技术栈的缺项；可合并提问并接受明确自然语言，不要求逐题回编号。用户要求推荐或使用默认值时，按现有脚本支持的选项给出一套选择。

使用现有 detect/install/scaffold 脚本。先 dry-run 检查路径和选项；已授权创建且方案明确就执行，只有未决选择、覆盖已有文件或未授权的全局工具安装才需确认。不要覆盖已有受管文件。

脚本输出留在执行记录中；对话报告关键选择、失败原因、产物和验证结果，不逐行复述 done。脚手架已运行的检查不重复执行；不能把生成测试文件或编译测试 APK 声称为设备测试通过。

## 工具链与执行

- 用 `script/detect.sh` 检查当前环境。兼容组合以 `rule/toolchain.sh` 为准；AGP 9 使用 built-in Kotlin，不应用 `org.jetbrains.kotlin.android`，Compose compiler 跟随脚本固定版本。
- 可用工具链直接复用；缺少 JDK、Gradle bootstrap 或 SDK package 时，确认必要安装范围后用 `script/install.sh` 的 `jdk17` / `gradle` / `sdk` 子命令。
- 环境变量只作用于当前命令，不修改全局 JAVA_HOME、PATH 或 SDK 配置；不自动接受 Android SDK license，不创建模拟器或启动 Android Studio。
- 收集选项及参数时读 [options.md](references/options.md)。参数齐全后，以同一组环境变量运行 `CAP_DRY_RUN=1 bash ~/.agents/skills/cap/script/scaffold.sh`，再运行真实脚手架。
- 保留脚本的 `assembleDebug` 和用户所选测试、lint 验证。交付工程路径、Application ID、所选栈及结果。
