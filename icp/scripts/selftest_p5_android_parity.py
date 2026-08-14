#!/usr/bin/env python3
"""Kotlin/Java controlled Gradle, ADB, trace, and screenshot parity."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from platforms import android_execution_handler_v1 as handler  # noqa: E402
from platforms import android_java_execution_authorization_v1 as java_authorization  # noqa: E402
from platforms import android_java_execution_binding_v1 as java_binding  # noqa: E402
from platforms import android_java_execution_executor_v1 as java_executor  # noqa: E402
from platforms import android_java_operations_v1 as java_operations  # noqa: E402
from platforms import android_kotlin_execution_authorization_v1 as kotlin_authorization  # noqa: E402
from platforms import android_kotlin_execution_binding_v1 as kotlin_binding  # noqa: E402
from platforms import android_kotlin_execution_executor_v1 as kotlin_executor  # noqa: E402
from platforms import android_kotlin_operations_v1 as kotlin_operations  # noqa: E402


def _write(path: Path, data: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def _artifact(root: str, path: str) -> dict[str, str]:
    return {"root": root, "path": path}


def _request(project: Path, run: Path, feature: str, inputs: dict, outputs: dict) -> dict:
    return {
        "project_root": str(project),
        "run_root": str(run),
        "feature_id": feature,
        "inputs": dict(sorted(inputs.items())),
        "outputs": dict(sorted(outputs.items())),
    }


def _fixture() -> tuple[tempfile.TemporaryDirectory, Path, Path, Path]:
    temporary = tempfile.TemporaryDirectory(prefix="icp-android-parity-")
    root = Path(temporary.name).resolve()
    project = root / "project"
    run = project / ".icp" / "runs" / "test-run"
    project.mkdir()
    run.mkdir(parents=True)
    _write(project / "settings.gradle.kts", 'rootProject.name = "App"\ninclude(":app")\n')
    config = {
        "module": "app",
        "variant": "Debug",
        "device_serial": "emulator-5554",
        "application_id": "com.example.app",
        "activity": "com.example.app.MainActivity",
        "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
    }
    _write(project / ".icp" / "platform-config.json", json.dumps(config))
    config_digest = hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write(
        run / "entry-readiness.json",
        json.dumps(
            {
                "kind": "icp.entry-readiness-report.v1",
                "status": "ready",
                "checks": [
                    {"id": "runtime_config", "status": "pass", "evidence_digest": config_digest}
                ],
            }
        ),
    )
    _write(
        run / "platform-package-selection.json",
        '{"kind":"icp.platform-package-selection.v1","platform_id":"android-kotlin","profile_id":"android-kotlin-standard"}',
    )
    manifest = _write(run / "selection-manifest.json", '{"kind":"test-selection"}\n')
    return temporary, project, run, manifest


def _execute(platform: str, manifest: Path, operation_id: str, request: dict, nonce: str) -> dict:
    if platform == "android-kotlin":
        binding_module, authorization_module, executor_module = (
            kotlin_binding,
            kotlin_authorization,
            kotlin_executor,
        )
    else:
        binding_module, authorization_module, executor_module = (
            java_binding,
            java_authorization,
            java_executor,
        )
    _write(
        manifest.parent / "platform-package-selection.json",
        json.dumps(
            {
                "kind": "icp.platform-package-selection.v1",
                "platform_id": platform,
                "profile_id": f"{platform}-standard",
            }
        ),
    )
    bound = binding_module.prepare_binding(manifest, operation_id, request)
    authorized = authorization_module.prepare_authorization(bound, execution_nonce=nonce * 64)
    return executor_module.execute_authorization(
        authorized,
        execution_nonce=nonce * 64,
        expected_binding_digest=bound["binding_digest"],
        expected_authorization_digest=authorized["authorization_digest"],
    )


def _fake_tools(project: Path, run: Path) -> tuple[Path, Path]:
    gradlew = _write(
        project / "gradlew",
        """#!/usr/bin/env python3
import pathlib
import os
import sys

pathlib.Path.cwd().joinpath('android-home.txt').write_text(os.environ.get('ANDROID_HOME', ''))

if any('assembleDebug' in arg for arg in sys.argv):
    path = pathlib.Path.cwd() / 'app' / 'build' / 'outputs' / 'apk' / 'debug' / 'app-debug.apk'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'fake-apk')
raise SystemExit(0)
""",
    )
    adb = _write(
        run / "adb",
        """#!/usr/bin/env python3
import pathlib
import sys

with pathlib.Path.cwd().joinpath('adb-argv.log').open('a') as stream:
    stream.write(' '.join(sys.argv[1:]) + '\\n')
if 'exec-out' in sys.argv and 'screencap' in sys.argv:
    sys.stdout.buffer.write(b'\\x89PNG\\r\\n\\x1a\\n' + b'fake-android-png')
elif 'exec-out' in sys.argv and 'cat' in sys.argv:
    sys.stdout.write('<hierarchy rotation="0"><node text="ICP" /></hierarchy>')
raise SystemExit(0)
""",
    )
    gradlew.chmod(0o700)
    adb.chmod(0o700)
    return gradlew, adb


def test_kotlin_and_java_all_operation_plans_are_verifiable() -> None:
    temporary, project, run, _manifest = _fixture()
    try:
        _write(run / "input.json", "{}\n")
        for platform, operations in (
            ("android-kotlin", kotlin_operations),
            ("android-java", java_operations),
        ):
            for index, operation_id in enumerate(operations.list_operation_ids()):
                plan = operations.build(
                    operation_id,
                    _request(
                        project,
                        run,
                        f"feature-{platform}-{index}",
                        {"input": _artifact("run", "input.json")},
                        {"output": _artifact("run", f"{platform}-{index}.json")},
                    ),
                )
                assert operations.verify_plan(plan)["plan_digest"]
    finally:
        temporary.cleanup()


def test_kotlin_and_java_publish_language_owned_sources() -> None:
    temporary, project, run, manifest = _fixture()
    try:
        for platform, extension, source, nonce in (
            ("android-kotlin", ".kt", "package com.example\nclass Feature\n", "a"),
            ("android-java", ".java", "package com.example; public final class Feature {}\n", "b"),
        ):
            _write(run / f"Feature{extension}", source)
            request = _request(
                project,
                run,
                f"feature-{platform}",
                {"source": _artifact("run", f"Feature{extension}")},
                {"source": _artifact("project", f"app/src/main/java/com/example/Feature{extension}")},
            )
            report = _execute(platform, manifest, f"{platform}.visible_codegen.v1", request, nonce)
            assert report["status"] == "succeeded"
    finally:
        temporary.cleanup()


def test_kotlin_gradle_trace_tests_gates_capture_and_fan_in() -> None:
    temporary, project, run, manifest = _fixture()
    original_which = handler.shutil.which
    original_android_home = os.environ.get("ANDROID_HOME")
    os.environ["ANDROID_HOME"] = "/fixture/android-sdk"
    _gradlew, adb = _fake_tools(project, run)
    handler.shutil.which = lambda name: str(adb) if name == "adb" else original_which(name)
    try:
        runtime_test = {"module": "app", "variant": "Debug"}
        _write(run / "runtime-test.json", json.dumps(runtime_test))
        for operation_id, output, nonce in (
            ("android-kotlin.test_runner.v1", "test.json", "c"),
            ("android-kotlin.project_gates.v1", "gates.json", "d"),
        ):
            request = _request(
                project,
                run,
                f"feature-{nonce}",
                {"runtime": _artifact("run", "runtime-test.json")},
                {"receipt": _artifact("run", output)},
            )
            assert _execute("android-kotlin", manifest, operation_id, request, nonce)["status"] == "succeeded"

        runtime_device = {
            "module": "app",
            "variant": "Debug",
            "device_serial": "emulator-5554",
            "application_id": "com.example.app",
            "activity": "com.example.app.MainActivity",
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
        }
        _write(run / "runtime-device.json", json.dumps(runtime_device))
        trace_request = _request(
            project,
            run,
            "feature-trace",
            {"runtime": _artifact("run", "runtime-device.json")},
            {"trace": _artifact("run", "window.xml")},
        )
        assert _execute("android-kotlin", manifest, "android-kotlin.trace_harness.v1", trace_request, "e")["status"] == "succeeded"
        capture_request = _request(
            project,
            run,
            "feature-capture",
            {"runtime": _artifact("run", "runtime-device.json")},
            {
                "actual": _artifact("run", "actual.png"),
                "provenance": _artifact("run", "provenance.json"),
            },
        )
        assert _execute("android-kotlin", manifest, "android-kotlin.runtime_capture.v1", capture_request, "f")["status"] == "succeeded"
        first_provenance = json.loads((run / "provenance.json").read_text())
        assert first_provenance["actual_source"] == "emulator_screenshot"
        assert first_provenance["capture_id"]
        assert first_provenance["state_reset_id"]

        second_capture_request = _request(
            project,
            run,
            "feature-capture-second",
            {"runtime": _artifact("run", "runtime-device.json")},
            {
                "actual": _artifact("run", "actual-second.png"),
                "provenance": _artifact("run", "provenance-second.json"),
            },
        )
        assert _execute(
            "android-kotlin",
            manifest,
            "android-kotlin.runtime_capture.v1",
            second_capture_request,
            "2",
        )["status"] == "succeeded"
        second_provenance = json.loads((run / "provenance-second.json").read_text())
        assert first_provenance["capture_id"] != second_provenance["capture_id"]
        assert first_provenance["state_reset_id"] != second_provenance["state_reset_id"]
        assert (project / "android-home.txt").read_text() == "/fixture/android-sdk"
        start_commands = [
            line.split()
            for line in (project / "adb-argv.log").read_text().splitlines()
            if "am start" in line
        ]
        assert start_commands
        assert all("-W" in command for command in start_commands)

        _write(project / "app" / "build.gradle.kts", "plugins {}\n")
        expected = hashlib.sha256((project / "app" / "build.gradle.kts").read_bytes()).hexdigest()
        _write(
            run / "mutation.json",
            json.dumps({"path": "app/build.gradle.kts", "expected_sha256": expected, "content": "plugins { id(\"com.android.application\") }\n"}),
        )
        fan_in = _request(
            project,
            run,
            "feature-fan-in",
            {"mutation_plan": _artifact("run", "mutation.json")},
            {"receipt": _artifact("run", "fan-in.json")},
        )
        assert _execute("android-kotlin", manifest, "android-kotlin.fan_in.v1", fan_in, "1")["status"] == "succeeded"
    finally:
        handler.shutil.which = original_which
        if original_android_home is None:
            os.environ.pop("ANDROID_HOME", None)
        else:
            os.environ["ANDROID_HOME"] = original_android_home
        temporary.cleanup()


def main() -> int:
    tests = sorted(name for name in globals() if name.startswith("test_"))
    failures = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"ok {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
