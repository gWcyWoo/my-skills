#!/usr/bin/env python3
"""Contract tests for platform-owned entry materials and runtime targets."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(SCRIPT_DIR))

from platforms import inactive_platform_core_v1 as core  # noqa: E402


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _executable(path: Path, body: str) -> str:
    _write(path, "#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path.resolve())


def _config(root: Path, document: dict) -> None:
    _write(
        root / ".icp" / "platform-config.json",
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
    )


def _expect_missing_config() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        with mock.patch.object(core.shutil, "which", return_value=None):
            try:
                core.preflight("nextjs", "nextjs-v1", root)
            except core.InactivePlatformError as exc:
                detail = str(exc)
                for requirement in (
                    ".icp/platform-config.json",
                    "next.config.js",
                    "package.json",
                    "installation:package-lock.json",
                    "installation:node_modules/next/package.json",
                    "installation:node_modules/react/package.json",
                    "tool:node",
                    "tool:npm",
                    "deferred:runtime_target",
                ):
                    assert requirement in detail, (requirement, detail)
            else:
                raise AssertionError("preflight accepted a project without entry materials")


def _nextjs_passes_with_complete_materials() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        bin_dir = root / "bin"
        node = _executable(bin_dir / "node", "exit 0\n")
        npm = _executable(bin_dir / "npm", "exit 0\n")
        _write(root / "next.config.js", "module.exports = {}\n")
        _write(root / "package-lock.json", "{}\n")
        (root / "node_modules" / "next").mkdir(parents=True)
        (root / "node_modules" / "react").mkdir(parents=True)
        _write(root / "node_modules" / "next" / "package.json", "{}\n")
        _write(root / "node_modules" / "react" / "package.json", "{}\n")
        _write(
            root / "package.json",
            json.dumps(
                {
                    "dependencies": {"next": "1", "react": "1"},
                    "scripts": {"dev": "next dev", "test": "test", "build": "next build"},
                }
            ),
        )
        _config(root, {"route": "/", "viewport_width": 390, "viewport_height": 844})
        with mock.patch.object(core.shutil, "which", side_effect=lambda name: {"node": node, "npm": npm}.get(name)):
            report = core.preflight("nextjs", "nextjs-v1", root)
        assert report["status"] == "pass"
        assert len(report["platform_config_digest"]) == 64


def _missing_materials_are_platform_scoped_and_complete() -> None:
    cases = (
        (
            "ios-swift",
            "ios-swift-v1",
            (".icp/platform-config.json", "*.xcodeproj", "source:.swift", "tool:xcodebuild", "tool:xcrun"),
            ("tool:adb", "tool:npm"),
        ),
        (
            "android-kotlin",
            "android-kotlin-v1",
            (
                ".icp/platform-config.json",
                "gradlew",
                "settings.gradle|settings.gradle.kts",
                "source:.kt",
                "tool:java",
                "tool:adb",
            ),
            ("tool:xcrun", "tool:npm"),
        ),
    )
    for platform_id, profile_id, expected, forbidden in cases:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with mock.patch.object(core.shutil, "which", return_value=None):
                try:
                    core.preflight(platform_id, profile_id, root)
                except core.InactivePlatformError as exc:
                    detail = str(exc)
                else:
                    raise AssertionError(f"{platform_id} accepted incomplete entry materials")
            for requirement in expected:
                assert requirement in detail, (platform_id, requirement, detail)
            for unrelated in forbidden:
                assert unrelated not in detail, (platform_id, unrelated, detail)


def _ios_passes_only_for_selected_simulator() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        bin_dir = root / "bin"
        xcodebuild = _executable(bin_dir / "xcodebuild", "exit 0\n")
        xcrun = _executable(bin_dir / "xcrun", "printf '%s\\n' '{\"devices\":\"SIM-1\"}'\n")
        (root / "Client.xcodeproj").mkdir()
        _write(root / "Sources" / "App.swift", "struct App {}\n")
        _config(
            root,
            {
                "project": "Client.xcodeproj",
                "scheme": "Client",
                "simulator_udid": "SIM-1",
                "app_product": "build/Client.app",
                "bundle_id": "com.example.client",
            },
        )
        tools = {"xcodebuild": xcodebuild, "xcrun": xcrun}
        with mock.patch.object(core.shutil, "which", side_effect=lambda name: tools.get(name)):
            report = core.preflight("ios-swift", "ios-swift-v1", root)
        assert report["status"] == "pass"

        _config(
            root,
            {
                "project": "Client.xcodeproj",
                "scheme": "Client",
                "simulator_udid": "SIM-MISSING",
                "app_product": "build/Client.app",
                "bundle_id": "com.example.client",
            },
        )
        with mock.patch.object(core.shutil, "which", side_effect=lambda name: tools.get(name)):
            try:
                core.preflight("ios-swift", "ios-swift-v1", root)
            except core.InactivePlatformError as exc:
                assert "runtime:simulator_udid" in str(exc)
            else:
                raise AssertionError("preflight accepted an unavailable simulator")


def _android_passes_only_for_selected_device() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        bin_dir = root / "bin"
        java = _executable(bin_dir / "java", "exit 0\n")
        adb = _executable(bin_dir / "adb", "printf 'List of devices attached\\nEMU-1\\tdevice\\n'\n")
        _executable(root / "gradlew", "exit 0\n")
        _write(root / "settings.gradle.kts", "rootProject.name = \"Client\"\n")
        _write(root / "gradle" / "wrapper" / "gradle-wrapper.jar", "fixture\n")
        _write(root / "gradle" / "wrapper" / "gradle-wrapper.properties", "fixture\n")
        _write(root / "app" / "src" / "main" / "App.kt", "class App\n")
        _config(
            root,
            {
                "module": "app",
                "variant": "debug",
                "device_serial": "EMU-1",
                "application_id": "com.example.client",
                "activity": ".MainActivity",
                "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            },
        )
        tools = {"java": java, "adb": adb}
        with mock.patch.object(core.shutil, "which", side_effect=lambda name: tools.get(name)):
            report = core.preflight("android-kotlin", "android-kotlin-v1", root)
        assert report["status"] == "pass"

        _config(
            root,
            {
                "module": "app",
                "variant": "debug",
                "device_serial": "EMU-MISSING",
                "application_id": "com.example.client",
                "activity": ".MainActivity",
                "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            },
        )
        with mock.patch.object(core.shutil, "which", side_effect=lambda name: tools.get(name)):
            try:
                core.preflight("android-kotlin", "android-kotlin-v1", root)
            except core.InactivePlatformError as exc:
                assert "runtime:device_serial" in str(exc)
            else:
                raise AssertionError("preflight accepted an unavailable Android device")


def main() -> int:
    tests = (
        _expect_missing_config,
        _nextjs_passes_with_complete_materials,
        _missing_materials_are_platform_scoped_and_complete,
        _ios_passes_only_for_selected_simulator,
        _android_passes_only_for_selected_device,
    )
    for test in tests:
        test()
    print(f"PASS: {len(tests)} entry runtime material cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
