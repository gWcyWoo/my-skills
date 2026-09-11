# 工程选项与脚本参数

以下编号是选项标识，不是用户回复格式要求。复用已给出的选择，接受明确自然语言；缺少的产品选择可合并询问。

7. 工程选项：
   - Q1 工程名：`1. 使用目录名`、`2. 自定义输入`。只接受 `[A-Za-z][A-Za-z0-9_]*`。
   - Q2 Application ID/package：`1. com.example.<小写工程名>`、`2. 自定义输入`。每段必须是合法 Kotlin/Java 标识符。
   - Q3 minSdk：`1. 24`、`2. 自定义输入`。只接受 23–37。
   - Q4 UI：`1. Jetpack Compose`、`2. 原生 Views（代码布局）`。
   - Q5 架构（浏览式）：`1. Feature-first MVVM`、`2. Clean Architecture 3层`、`3. Layer-first MVVM`、`4. MVC`。需要比较结构时运行 `bash ~/.agents/skills/cap/script/show_arch.sh <n>`。
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
