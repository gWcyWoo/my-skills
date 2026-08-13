#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(checker: Path, root: Path, expected: int, extra: list[str] | None = None) -> dict:
    report = root / "capture_readiness.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--project-root",
            str(root),
            "--entry",
            str(root / "lib" / "main.dart"),
            "--out",
            str(report),
            *(extra or []),
        ],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    return json.loads(report.read_text(encoding="utf-8"))


def write_project(root: Path, app_source: str, unrelated_source: str = "") -> None:
    (root / "lib").mkdir(parents=True)
    (root / "pubspec.yaml").write_text("name: capture_fixture\n", encoding="utf-8")
    (root / "lib" / "main.dart").write_text(
        "import 'app.dart';\nvoid main() => runApp(const App());\n",
        encoding="utf-8",
    )
    (root / "lib" / "app.dart").write_text(app_source, encoding="utf-8")
    if unrelated_source:
        (root / "lib" / "unrelated.dart").write_text(unrelated_source, encoding="utf-8")


def main() -> int:
    checker = Path(__file__).with_name("check_capture_readiness.py")
    with tempfile.TemporaryDirectory(prefix="iff-capture-readiness-") as tmp:
        root = Path(tmp)
        passing = root / "passing"
        write_project(
            passing,
            "class App { const App(); Widget build(context) => MaterialApp("
            "debugShowCheckedModeBanner: false); }\n",
        )
        report = run(checker, passing, 0)
        assert report["ok"] is True, report
        assert report["appShellFiles"] == [str((passing / "lib" / "app.dart").resolve())], report

        failing = root / "failing"
        write_project(
            failing,
            "class App { const App(); Widget build(context) => MaterialApp(); }\n",
            "final ignored = MaterialApp(debugShowCheckedModeBanner: false);\n",
        )
        report = run(checker, failing, 1)
        assert report["ok"] is False, report
        assert report["reason"] == "debug_banner_not_disabled", report
        assert str((failing / "lib" / "unrelated.dart").resolve()) not in report["reachableFiles"], report

        hidden_system_bar = root / "hidden-system-bar"
        write_project(
            hidden_system_bar,
            "class App { const App(); Widget build(context) => MaterialApp("
            "debugShowCheckedModeBanner: false); }\n",
        )
        (hidden_system_bar / "lib" / "main.dart").write_text(
            "import 'app.dart';\n"
            "Future<void> main() async {\n"
            "  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);\n"
            "  runApp(const App());\n"
            "}\n",
            encoding="utf-8",
        )
        page = hidden_system_bar / "lib" / "page.dart"
        page.write_text("Widget build(context) => SafeArea(child: Placeholder());\n", encoding="utf-8")
        scene = hidden_system_bar / "scene.json"
        scene.write_text(
            json.dumps({"systemUiExclusions": [{"node": "status", "role": "status_bar"}]}),
            encoding="utf-8",
        )
        report = run(
            checker,
            hidden_system_bar,
            1,
            ["--scene", str(scene), "--safe-area-source", str(page)],
        )
        assert report["reason"] == "system_status_bar_hidden", report

        visible_without_safe_area = root / "visible-without-safe-area"
        write_project(
            visible_without_safe_area,
            "class App { const App(); Widget build(context) => MaterialApp("
            "debugShowCheckedModeBanner: false); }\n",
        )
        (visible_without_safe_area / "lib" / "main.dart").write_text(
            "import 'app.dart';\n"
            "Future<void> main() async {\n"
            "  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\n"
            "  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(\n"
            "    statusBarColor: Colors.transparent,\n"
            "  ));\n"
            "  runApp(const App());\n"
            "}\n",
            encoding="utf-8",
        )
        unsafe_page = visible_without_safe_area / "lib" / "page.dart"
        unsafe_page.write_text("Widget build(context) => Placeholder();\n", encoding="utf-8")
        visible_scene = visible_without_safe_area / "scene.json"
        visible_scene.write_text(scene.read_text(encoding="utf-8"), encoding="utf-8")
        report = run(
            checker,
            visible_without_safe_area,
            0,
            ["--scene", str(visible_scene), "--page-source", str(unsafe_page)],
        )
        assert report["statusBarPolicy"]["mode"] == "overlay", report
        unsafe_page.write_text(
            "Widget build(context) => SafeArea(top: false, child: Placeholder());\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            visible_without_safe_area,
            0,
            ["--scene", str(visible_scene), "--page-source", str(unsafe_page)],
        )
        assert report["topInsetSources"] == [], report
        unsafe_page.write_text("Widget build(context) => SafeArea(child: Placeholder());\n", encoding="utf-8")
        report = run(
            checker,
            visible_without_safe_area,
            1,
            ["--scene", str(visible_scene), "--page-source", str(unsafe_page)],
        )
        assert report["reason"] == "status_bar_content_not_behind", report
        unsafe_page.write_text("Widget build(context) => Placeholder();\n", encoding="utf-8")
        main_source = (visible_without_safe_area / "lib" / "main.dart").read_text(encoding="utf-8")
        (visible_without_safe_area / "lib" / "main.dart").write_text(
            main_source.replace("Colors.transparent", "Colors.white"),
            encoding="utf-8",
        )
        report = run(
            checker,
            visible_without_safe_area,
            1,
            ["--scene", str(visible_scene), "--page-source", str(unsafe_page)],
        )
        assert report["reason"] == "status_bar_transparency_missing", report

        no_status_bar = root / "no-status-bar"
        write_project(
            no_status_bar,
            "class App { const App(); Widget build(context) => MaterialApp("
            "debugShowCheckedModeBanner: false); }\n",
        )
        (no_status_bar / "lib" / "main.dart").write_text(
            "import 'app.dart';\n"
            "Future<void> main() async {\n"
            "  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\n"
            "  runApp(const App());\n"
            "}\n",
            encoding="utf-8",
        )
        page_without_status_bar = no_status_bar / "lib" / "page.dart"
        page_without_status_bar.write_text("Widget build(context) => Placeholder();\n", encoding="utf-8")
        no_status_scene = no_status_bar / "scene.json"
        no_status_scene.write_text(json.dumps({"systemUiExclusions": []}), encoding="utf-8")
        report = run(
            checker,
            no_status_bar,
            1,
            ["--scene", str(no_status_scene), "--page-source", str(page_without_status_bar)],
        )
        assert report["reason"] == "unexpected_system_status_bar", report
        (no_status_bar / "lib" / "main.dart").write_text(
            "import 'app.dart';\n"
            "Future<void> main() async {\n"
            "  await SystemChrome.setEnabledSystemUIMode(\n"
            "    SystemUiMode.manual,\n"
            "    overlays: const [SystemUiOverlay.bottom],\n"
            "  );\n"
            "  runApp(const App());\n"
            "}\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            no_status_bar,
            0,
            ["--scene", str(no_status_scene), "--page-source", str(page_without_status_bar)],
        )
        assert report["statusBarPolicy"]["mode"] == "hidden", report
        page_without_status_bar.write_text(
            "Widget build(context) => SafeArea(child: Placeholder());\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            no_status_bar,
            1,
            ["--scene", str(no_status_scene), "--page-source", str(page_without_status_bar)],
        )
        assert report["reason"] == "top_inset_reserved_without_status_bar", report

        dynamic_policy = root / "dynamic-policy"
        write_project(
            dynamic_policy,
            "import 'page.dart';\n"
            "import 'system_ui.dart';\n"
            "class App { const App(); Widget build(context) => MaterialApp(\n"
            "debugShowCheckedModeBanner: false, home: buildPage()); }\n",
        )
        (dynamic_policy / "lib" / "system_ui.dart").write_text(
            "Future<void> applyPolicy(bool visible) async {\n"
            "  if (visible) {\n"
            "    await _driver.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\n"
            "    _driver.setSystemUIOverlayStyle(const SystemUiOverlayStyle(\n"
            "      statusBarColor: Colors.transparent,\n"
            "    ));\n"
            "  } else {\n"
            "    await _driver.setEnabledSystemUIMode(\n"
            "      SystemUiMode.manual,\n"
            "      overlays: const [SystemUiOverlay.bottom],\n"
            "    );\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        dynamic_page = dynamic_policy / "lib" / "page.dart"
        dynamic_page.write_text(
            "import 'state.dart';\n"
            "Widget buildPage() {\n"
            "  applyPolicy(designStatusBarDetected);\n"
            "  return Placeholder();\n"
            "}\n",
            encoding="utf-8",
        )
        generated_policy = dynamic_policy / "lib" / "waiting_status_bar_policy.dart"
        generated_policy.write_text(
            "// GENERATED by iFF make_status_bar_policy.py; DO NOT EDIT.\n"
            "abstract final class WaitingStatusBarPolicy {\n"
            "  static const bool designStatusBarDetected = true;\n"
            "  static const String mode = 'overlay';\n"
            "  static const bool transparent = true;\n"
            "  static const bool overlaysContent = true;\n"
            "  static const bool reserveTopInset = false;\n"
            "}\n",
            encoding="utf-8",
        )
        startup_policy = dynamic_policy / "lib" / "apply_status_bar_policy.dart"
        startup_policy.write_text(
            "// GENERATED by iFF make_status_bar_policy.py; DO NOT EDIT.\n"
            "abstract final class ApplyStatusBarPolicy {\n"
            "  static const bool designStatusBarDetected = false;\n"
            "  static const String mode = 'hidden';\n"
            "  static const bool transparent = false;\n"
            "  static const bool overlaysContent = false;\n"
            "  static const bool reserveTopInset = false;\n"
            "}\n",
            encoding="utf-8",
        )
        (dynamic_policy / "lib" / "state.dart").write_text(
            "import 'waiting_status_bar_policy.dart';\n"
            "bool get designStatusBarDetected => "
            "WaitingStatusBarPolicy.designStatusBarDetected;\n",
            encoding="utf-8",
        )
        dynamic_scene = dynamic_policy / "scene.json"
        dynamic_scene.write_text(scene.read_text(encoding="utf-8"), encoding="utf-8")
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
            ],
        )
        assert report["reason"] == "status_bar_policy_applied_after_run_app", report
        (dynamic_policy / "lib" / "main.dart").write_text(
            "import 'app.dart';\n"
            "import 'system_ui.dart';\n"
            "Future<void> main() async {\n"
            "  await _controller.applyDesignPolicy(\n"
            "    designStatusBarDetected: true,\n"
            "  );\n"
            "  runApp(const App());\n"
            "}\n",
            encoding="utf-8",
        )
        android_values = dynamic_policy / "android" / "app" / "src" / "main" / "res" / "values"
        android_values.mkdir(parents=True)
        android_styles = android_values / "styles.xml"
        android_styles.write_text(
            "<resources>\n"
            "  <style name=\"LaunchTheme\"><item name=\"android:windowBackground\">"
            "@drawable/launch_background</item></style>\n"
            "  <style name=\"NormalTheme\"><item name=\"android:windowBackground\">"
            "?android:colorBackground</item></style>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_theme_status_bar_flash", report
        android_styles.write_text(
            "<resources>\n"
            "  <style name=\"LaunchTheme\">"
            "<item name=\"android:windowFullscreen\">true</item></style>\n"
            "  <style name=\"NormalTheme\">"
            "<item name=\"android:windowFullscreen\">true</item></style>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_theme_status_bar_flash", report
        android_styles.write_text(
            "<resources>\n"
            "  <style name=\"LaunchTheme\" parent=\"@android:style/Theme.Light.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item></style>\n"
            "  <style name=\"NormalTheme\" parent=\"@android:style/Theme.Light.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item></style>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_theme_status_bar_flash", report
        android_styles.write_text(
            "<resources>\n"
            "  <style name=\"LaunchTheme\" parent=\"@android:style/Theme.Light.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item>"
            "<item name=\"android:windowDrawsSystemBarBackgrounds\">true</item>"
            "<item name=\"android:statusBarColor\">@android:color/transparent</item>"
            "</style>\n"
            "  <style name=\"NormalTheme\" parent=\"@android:style/Theme.Light.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item>"
            "<item name=\"android:windowDrawsSystemBarBackgrounds\">true</item>"
            "<item name=\"android:statusBarColor\">@android:color/transparent</item>"
            "</style>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_theme_status_bar_flash", report
        android_styles.write_text(
            "<resources>\n"
            "  <style name=\"LaunchTheme\" parent=\"@android:style/Theme.Translucent.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item>"
            "<item name=\"android:windowDrawsSystemBarBackgrounds\">true</item>"
            "<item name=\"android:statusBarColor\">@android:color/transparent</item>"
            "<item name=\"android:windowIsTranslucent\">true</item>"
            "</style>\n"
            "  <style name=\"NormalTheme\" parent=\"@android:style/Theme.Light.NoTitleBar.Fullscreen\">"
            "<item name=\"android:windowFullscreen\">true</item>"
            "<item name=\"android:windowDrawsSystemBarBackgrounds\">true</item>"
            "<item name=\"android:statusBarColor\">@android:color/transparent</item>"
            "</style>\n"
            "</resources>\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_theme_status_bar_flash", report
        android_styles.write_text(
            android_styles.read_text(encoding="utf-8").replace(
                '<item name="android:windowIsTranslucent">true</item>',
                '<item name="android:windowIsTranslucent">true</item>'
                '<item name="android:windowAnimationStyle">@null</item>',
                1,
            ),
            encoding="utf-8",
        )
        main_activity = (
            dynamic_policy
            / "android"
            / "app"
            / "src"
            / "main"
            / "kotlin"
            / "example"
            / "MainActivity.kt"
        )
        main_activity.parent.mkdir(parents=True)
        main_activity.write_text(
            "class MainActivity : FlutterActivity() {\n"
            "  override fun onCreate(savedInstanceState: Bundle?) {\n"
            "    window.setFlags(FLAG_FULLSCREEN, FLAG_FULLSCREEN)\n"
            "    window.insetsController?.hide(WindowInsets.Type.statusBars())\n"
            "    super.onCreate(savedInstanceState)\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_activity_status_bar_flash", report
        main_activity.write_text(
            "class MainActivity : FlutterActivity() {\n"
            "  override fun onCreate(savedInstanceState: Bundle?) {\n"
            "    window.setFlags(FLAG_FULLSCREEN, FLAG_FULLSCREEN)\n"
            "    super.onCreate(savedInstanceState)\n"
            "    window.insetsController?.hide(WindowInsets.Type.statusBars())\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["reason"] == "android_launch_activity_status_bar_flash", report
        main_activity.write_text(
            "class MainActivity : FlutterActivity() {\n"
            "  private var startupStatusBarPending = true\n"
            "  override fun onCreate(savedInstanceState: Bundle?) {\n"
            "    window.setFlags(FLAG_FULLSCREEN, FLAG_FULLSCREEN)\n"
            "    super.onCreate(savedInstanceState)\n"
            "    hideStartupStatusBar()\n"
            "  }\n"
            "  override fun onPostResume() { super.onPostResume(); hideStartupStatusBar() }\n"
            "  override fun onWindowFocusChanged(hasFocus: Boolean) {\n"
            "    super.onWindowFocusChanged(hasFocus); if (hasFocus) hideStartupStatusBar()\n"
            "  }\n"
            "  override fun onFlutterUiDisplayed() {\n"
            "    super.onFlutterUiDisplayed(); startupStatusBarPending = false\n"
            "  }\n"
            "  private fun hideStartupStatusBar() {\n"
            "    if (startupStatusBarPending) {\n"
            "      window.insetsController?.hide(WindowInsets.Type.statusBars())\n"
            "    }\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            0,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
                "--startup-policy-source",
                str(startup_policy),
            ],
        )
        assert report["policySource"]["mode"] == "overlay", report
        generated_policy.write_text(
            generated_policy.read_text(encoding="utf-8")
            .replace("designStatusBarDetected = true", "designStatusBarDetected = false")
            .replace("mode = 'overlay'", "mode = 'hidden'")
            .replace("transparent = true", "transparent = false")
            .replace("overlaysContent = true", "overlaysContent = false"),
            encoding="utf-8",
        )
        report = run(
            checker,
            dynamic_policy,
            1,
            [
                "--scene",
                str(dynamic_scene),
                "--page-source",
                str(dynamic_page),
                "--policy-source",
                str(generated_policy),
            ],
        )
        assert report["reason"] == "status_bar_policy_scene_mismatch", report

    print("PASS: capture readiness enforces debug-banner and per-scene status-bar policies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
