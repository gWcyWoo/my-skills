# 平台命令提示

使用当前可用工具的实际参数；以下命令中的占位符必须来自已确认输入，路径正确引用。只读取本次平台与工具所需段落。

## Android

- 现有 `apkanalyzer manifest application-id <apk>`，或 `aapt dump badging <apk>` 可提取包 ID；两者都不可用时询问 ID，不为读 ID 安装完整 build-tools。
- `adb devices`、`emulator -list-avds` 用于发现目标。后续 adb 命令带 `-s <serial>`。
- 安装：`adb -s <serial> install -r <apk>`；核实：`adb -s <serial> shell pm path <package>`。
- 启动：`adb -s <serial> shell monkey -p <package> 1`；需要 activity 时用 `shell cmd package resolve-activity --brief <package>`。
- 只有用户要求 clean reinstall 时才卸载或清数据。

## iOS

- 从 `.app/Info.plist` 读取 `CFBundleIdentifier` 和目标平台信息；`.ipa` 解包副本后读取 `Payload/*.app/Info.plist`。
- `xcrun simctl list devices available` / `booted` 发现 Simulator；后续使用具体 UDID。
- `xcrun simctl install <udid> <app>`、`get_app_container <udid> <bundle-id>`、`launch <udid> <bundle-id>` 安装并验证启动。
- 真机 IPA 使用已配置的 XCUITest/Xcode 设备工具，并核实信任、Developer Mode、签名与目标匹配。不能用 Simulator 替代要求的真机验证。

## Maestro

检查 `maestro --version`、`java -version`。仅实际需要且已授权时安装；使用当前官方安装说明。环境访问受限时报告权限错误，不把环境故障当作测试失败。

## Appium

检查 `appium --version` 和 `appium driver list --installed`。Android 使用 `uiautomator2`，iOS 使用 `xcuitest`；仅安装目标平台缺失且已授权的驱动，再运行对应 `appium driver doctor`。
