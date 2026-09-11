---
name: cfp
description: Create a Flutter/Dart project using the bundled company scaffolding.
---

# cFP

创建符合现有脚本约定的 Flutter/Dart 工程。

## 交互与完成边界

复用用户已给出的目录、工具链和技术选择。仅询问影响工程身份或技术栈的缺项；可合并提问并接受明确自然语言，不要求逐题回编号。用户要求推荐或使用默认值时，按现有脚本支持的选项给出一套选择。

使用现有 detect/install/scaffold 脚本。先 dry-run 检查路径和选项；已授权创建且方案明确就执行，只有未决选择、覆盖已有文件或未授权的全局工具安装才需确认。不要覆盖已有受管文件。

脚本输出留在执行记录中；对话报告关键选择、失败原因、产物和验证结果，不逐行复述 done。脚手架已运行的检查不重复执行；不能把生成测试文件或编译测试 APK 声称为设备测试通过。

## 版本模式与执行

- 用 `script/detect.sh` 检测全局 Flutter/Dart、FVM 和缓存版本。
- 用户使用当前全局 Flutter 时：`MODE=global`，直接使用 `flutter`，不安装 FVM、不重复下载 SDK、不写 `.fvmrc`。
- 用户选择其他版本或机器没有 Flutter 时：`MODE=fvm`，用 `script/install.sh <TARGET>` 安装所选 SDK，再由 scaffold 在工程内 `fvm use` 锁版本。目标为最新版本时通过当前官方发布信息解析，不凭旧笔记猜版本。
- Dart 随 Flutter 提供；不单独安装 Dart，不改动现有全局 Flutter/Dart。MODE=fvm 工程使用 `fvm flutter`。
- 收集选项及环境变量时读 [options.md](references/options.md)。以同一组环境变量运行 `CFP_DRY_RUN=1 bash ~/.agents/skills/cfp/script/scaffold.sh`，再运行真实脚手架。
- 保留脚本的依赖解析、必要 codegen 和 `analyze`。交付工程路径、版本模式、所选栈和实际验证边界；analyze 通过不等于客户端运行通过。
