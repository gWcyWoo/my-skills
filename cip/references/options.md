# 工程选项与脚本参数

以下编号是选项标识，不是用户回复格式要求。复用已给出的选择，接受明确自然语言；缺少的产品选择可合并询问。

6. 工程选项：
   - Q1 工程/Target 名：`1. 使用目录名`、`2. 自定义输入`。只接受 `[A-Za-z][A-Za-z0-9_]*`。
   - Q2 Bundle ID：`1. com.example.<小写工程名>`、`2. 自定义输入`。必须至少两段，点分段不能为空。
   - Q3 最低 iOS：`1. 17.0`、`2. 自定义输入`。只接受数字版本；SwiftData 要求 iOS 17.0+。
   - Q4 设备：`1. iPhone`、`2. iPad`、`3. Universal`。
   - Q5 UI：`1. SwiftUI`、`2. UIKit`。SwiftUI 要求 iOS 14.0+。
   - Q6 架构（浏览式）：`1. Feature-first MVVM`、`2. Clean Architecture 3层`、`3. Layer-first MVVM`、`4. MVC`。需要比较结构时运行 `bash ~/.agents/skills/cip/script/show_arch.sh <n>`；记录 `ARCH`。
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
