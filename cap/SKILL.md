---
name: cap
description: Use when creating a new standard native Android project with Kotlin and Gradle through guided company-style scaffolding. `cAP` = create Android Project. 触发于 "cap"、"cAP"、"create android project"、"create android kotlin project"、"创建 Android 工程"、"创建 Android Kotlin 工程"、"新建原生 Android 项目"。
---

<role>
cAP 在 MAIN session 运行，沿用 cFP/cIP 的两阶段纪律创建原生 Android/Kotlin 工程：Phase 1 确认目录、JDK、Gradle 与 Android SDK，Phase 2 逐题收集选项后执行确定性脚手架。每个决策都由用户回复编号；主会话只提问、调用脚本和转述结果。
</role>

<context>
## 固定技术边界
- 只创建原生 Android/Kotlin 工程；不创建 Flutter、React Native、KMP 或 Java-only 工程。
- 使用 `rule/toolchain.sh` 中固定的兼容组合：AGP 9.2.1、Gradle 9.4.1、JDK 17、compileSdk/targetSdk 37、Build Tools 36.0.0；该组合兼容当前 Android Studio 2025.3。
- AGP 9 使用 built-in Kotlin；不要应用 `org.jetbrains.kotlin.android`。Compose 分支只应用匹配 Kotlin 2.3.21 的 Compose Compiler plugin。
- 不修改全局 `JAVA_HOME`、PATH 或 Android SDK 配置；只给当前命令传环境变量。
- 不自动接受 Android SDK license，不自动启动 Android Studio，不创建模拟器。

## 输出纪律
- 每步打印 `步骤标签... done`；失败打印 `步骤标签... FAILED` 和原始原因。
- 每个 Phase 结束打印成功/失败计数与关键产物。
- 所有菜单用 prose 编号，不调用 `request_user_input` 或其他选择题工具。
- 裸文本、混合格式或缺少编号的回复无效；重显当前菜单，不猜测。
</context>

<instructions>
## Phase 1 — 环境与目录

1. 确认工程根目录：`1. 当前目录 (<pwd>)`、`2. 指定绝对路径`。回显 `PROJECT_DIR` 并打印 `工程目录确认... done`。
2. 运行 `bash ~/.agents/skills/cap/script/detect.sh`，原样转述 OS、Homebrew、Android Studio、JAVA_HOME、Java/Javac、Gradle、Android SDK、sdkmanager、adb、已安装 platforms/build-tools 和 cAP 目标工具链。
3. 确认 JDK 17：
   - 当前 JDK 可用：`1. 使用当前 JDK 17 (<path>)`、`2. 指定 JAVA_HOME`。
   - 当前 JDK 不可用但检测到 Android Studio JBR/JDK 17：显示检测路径编号供选择。
   - 都不可用且有 Homebrew：显示 `1. brew install openjdk@17`、`2. 停止，我手动安装`；选 1 后运行 `bash ~/.agents/skills/cap/script/install.sh jdk17`，再复检。
   - 记录 `JAVA_HOME`，不写 shell profile。
4. 确认 Gradle bootstrap：
   - 已安装：记录 `GRADLE_CMD`。
   - 未安装且有 Homebrew：显示 `1. brew install gradle`、`2. 停止，我手动安装`；选 1 后运行 `bash ~/.agents/skills/cap/script/install.sh gradle`。
   - Gradle 只用于生成锁定到 9.4.1 的 Wrapper；后续构建只用工程内 `./gradlew`。
5. 确认 Android SDK：
   - 让用户从检测到的 SDK root 中编号选择或用 `编号 空格 绝对路径` 自定义，记录 `ANDROID_SDK_ROOT`。
   - 校验 `sdkmanager`、`platforms;android-37`、`build-tools;36.0.0`、`platform-tools`。
   - 包缺失时显示 `1. 用 sdkmanager 安装缺失包`、`2. 停止，我手动处理`；选 1 后运行 `bash ~/.agents/skills/cap/script/install.sh sdk <ANDROID_SDK_ROOT>`。
   - license 未接受导致安装失败时停止，显示原始错误，让用户手动运行 `sdkmanager --licenses`；不要管道输入 `yes`。
6. 打印 Phase 1 汇总：`PROJECT_DIR`、`JAVA_HOME`、`GRADLE_CMD`、`ANDROID_SDK_ROOT`、JDK/Gradle/SDK 版本和成功/失败计数。

## Phase 2 — 工程脚手架

逐题显示编号菜单；含自定义文本的选项只接受 `编号 空格 文本`。

7. 按顺序收集：
   - Q1 工程名：`1. 使用目录名`、`2. 自定义输入`。只接受 `[A-Za-z][A-Za-z0-9_]*`。
   - Q2 Application ID/package：`1. com.example.<小写工程名>`、`2. 自定义输入`。每段必须是合法 Kotlin/Java 标识符。
   - Q3 minSdk：`1. 24`、`2. 自定义输入`。只接受 23–37。
   - Q4 UI：`1. Jetpack Compose`、`2. 原生 Views（代码布局）`。
   - Q5 架构（浏览式）：`1. Feature-first MVVM`、`2. Clean Architecture 3层`、`3. Layer-first MVVM`、`4. MVC`。运行 `bash ~/.agents/skills/cap/script/show_arch.sh <n>` 后显示 `1. 确认`、`2. 返回架构菜单`，循环到确认。
   - Q6 状态：`1. ViewModel + StateFlow`、`2. 不加`。
   - Q7 网络：`1. HttpURLConnection`、`2. 不加`。
   - Q8 持久化：`1. SharedPreferences`、`2. 不加`。
   - Q9 依赖注入：`1. 手工 AppContainer`、`2. 不加`。
   - Q10 测试：`1. Unit Tests`、`2. Instrumented Tests`、`3. 两者`、`4. 不加`。
   - Q11 Lint：`1. Android Lint`、`2. 不运行 lint`。
   - Q12 附加项（多选，逗号分隔，可空）：`1. README`、`2. CI`、`3. dev/prod flavors`、`4. 中文 l10n`、`5. 示例计数页`。选 CI 后再问 `1. GitHub Actions`、`2. GitLab CI`。
8. 映射环境变量：
   - Phase 1：`PROJECT_DIR`、`JAVA_HOME`、`GRADLE_CMD`、`ANDROID_SDK_ROOT`。
   - Q1–Q5：`APP_NAME`、`PACKAGE_NAME`、`MIN_SDK`、`UI=compose|views`、`ARCH=1..4`。
   - Q6–Q11：`STATE=stateflow|none`、`NET=urlconnection|none`、`STORAGE=shared_preferences|none`、`DI=manual|none`、`TESTS=unit|instrumented|both|none`、`LINT=android|none`。
   - Q12：`EXTRAS=readme,ci,flavors,l10n,sample`、`CI_PROVIDER=github|gitlab`。
9. 必须先加 `CAP_DRY_RUN=1` 运行 `bash ~/.agents/skills/cap/script/scaffold.sh`。显示计划后询问 `1. 执行`、`2. 返回修改选项`；只有回复 `1` 才真实执行。
10. 真实脚手架依次生成 Gradle Wrapper、Kotlin DSL、Manifest/resources、架构源码、测试与附加项，然后执行 `assembleDebug`、选中的测试编译/运行和 `lintDebug`。任何已有受管路径都失败，不覆盖。
11. 打印 Phase 2 汇总：工程路径、Application ID、SDK、UI、架构、状态、网络、存储、DI、测试、lint、附加项、成功/失败计数，以及 `cd <PROJECT_DIR> && ./gradlew :app:assembleDebug`。
</instructions>

<success_criteria>
- Phase 1 明确目录、JDK 17、Gradle bootstrap、Android SDK root 和必需 SDK packages。
- Q1–Q12 全部由严格编号选择；架构先预览再确认；真实执行前完成 dry-run 与二次编号确认。
- 生成 Gradle 9.4.1 Wrapper、Kotlin DSL、原生 Kotlin 源码、Manifest/resources 和所选测试。
- `:app:assembleDebug` 成功；Unit Tests、Instrumented test APK 和 Android Lint 按选择通过。失败保留原始错误。
</success_criteria>

<final_reminders>
P0 — 不自动选择，不接受无编号回复。
P0 — 不修改全局环境，不自动接受 SDK license。
P0 — 每步输出 `done|FAILED`，最后输出汇总。
P1 — 先 dry-run，再经编号确认真实执行。
P1 — 文件生成和 Gradle 验证只由 `script/scaffold.sh` 完成。
</final_reminders>
