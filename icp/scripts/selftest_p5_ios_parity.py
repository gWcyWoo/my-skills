#!/usr/bin/env python3
"""Swift/Objective-C controlled Xcode and simulator parity."""

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

from platforms import ios_execution_handler_v1 as handler  # noqa: E402
from platforms import ios_objc_execution_authorization_v1 as objc_authorization  # noqa: E402
from platforms import ios_objc_execution_binding_v1 as objc_binding  # noqa: E402
from platforms import ios_objc_execution_executor_v1 as objc_executor  # noqa: E402
from platforms import ios_objc_operations_v1 as objc_operations  # noqa: E402
from platforms import ios_swift_execution_authorization_v1 as swift_authorization  # noqa: E402
from platforms import ios_swift_execution_binding_v1 as swift_binding  # noqa: E402
from platforms import ios_swift_execution_executor_v1 as swift_executor  # noqa: E402
from platforms import ios_swift_operations_v1 as swift_operations  # noqa: E402


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
    temporary = tempfile.TemporaryDirectory(prefix="icp-ios-parity-")
    root = Path(temporary.name).resolve()
    project = root / "project"
    run = project / ".icp" / "runs" / "test-run"
    (project / "App.xcodeproj").mkdir(parents=True)
    run.mkdir(parents=True)
    config = {
        "project": "App.xcodeproj",
        "scheme": "App",
        "simulator_udid": "SIMULATOR-1",
        "app_product": "App",
        "bundle_id": "com.example.app",
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
        '{"kind":"icp.platform-package-selection.v1","platform_id":"ios-swift","profile_id":"ios-swift-standard"}',
    )
    manifest = _write(run / "selection-manifest.json", '{"kind":"test-selection"}\n')
    return temporary, project, run, manifest


def test_runtime_input_cannot_override_entry_selected_simulator() -> None:
    temporary, project, run, manifest = _fixture()
    try:
        runtime = _write(
            run / "runtime-mismatch.json",
            json.dumps(
                {
                    "project": "App.xcodeproj",
                    "scheme": "App",
                    "simulator_udid": "SIMULATOR-2",
                }
            ),
        )
        request = _request(
            project,
            run,
            "feature-runtime-binding",
            {"runtime": _artifact("run", runtime.name)},
            {"receipt": _artifact("run", "test.json")},
        )
        try:
            swift_binding.prepare_binding(manifest, "ios-swift.test_runner.v1", request)
        except Exception:
            return
        raise AssertionError("runtime input overrode the entry-selected simulator")
    finally:
        temporary.cleanup()


def _execute(platform: str, manifest: Path, operation_id: str, request: dict, nonce: str) -> dict:
    if platform == "ios-swift":
        binding_module, authorization_module, executor_module = (
            swift_binding,
            swift_authorization,
            swift_executor,
        )
    else:
        binding_module, authorization_module, executor_module = (
            objc_binding,
            objc_authorization,
            objc_executor,
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


def _fake_tools(root: Path) -> tuple[Path, Path]:
    xcodebuild = _write(
        root / "xcodebuild",
        """#!/usr/bin/env python3
import os
import pathlib
import sys

derived = pathlib.Path(sys.argv[sys.argv.index('-derivedDataPath') + 1])
if 'build' in sys.argv:
    (derived / 'Build' / 'Products' / 'Debug-iphonesimulator' / 'App.app').mkdir(parents=True, exist_ok=True)
trace = os.environ.get('ICP_TRACE_OUTPUT')
if trace:
    path = pathlib.Path(trace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"kind":"icp.ios-native-view-trace.v1"}\\n')
raise SystemExit(0)
""",
    )
    xcrun = _write(
        root / "xcrun",
        """#!/usr/bin/env python3
import pathlib
import sys

if 'screenshot' in sys.argv:
    pathlib.Path(sys.argv[-1]).write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + b'fake-ios-png')
raise SystemExit(0)
""",
    )
    xcodebuild.chmod(0o700)
    xcrun.chmod(0o700)
    return xcodebuild, xcrun


def test_swift_and_objc_all_operation_plans_are_verifiable() -> None:
    temporary, project, run, _manifest = _fixture()
    try:
        _write(run / "input.json", "{}\n")
        for platform, operations in (
            ("ios-swift", swift_operations),
            ("ios-objc", objc_operations),
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


def test_swift_and_objc_publish_language_owned_sources() -> None:
    temporary, project, run, manifest = _fixture()
    try:
        for platform, extension, source, nonce in (
            ("ios-swift", ".swift", "import SwiftUI\nstruct Feature: View { var body: some View { Text(\"ok\") } }\n", "a"),
            ("ios-objc", ".m", "#import <UIKit/UIKit.h>\n@implementation Feature\n@end\n", "b"),
        ):
            _write(run / f"Feature{extension}", source)
            request = _request(
                project,
                run,
                f"feature-{platform}",
                {"source": _artifact("run", f"Feature{extension}")},
                {"source": _artifact("project", f"Sources/Feature{extension}")},
            )
            report = _execute(platform, manifest, f"{platform}.visible_codegen.v1", request, nonce)
            assert report["status"] == "succeeded"
            assert (project / "Sources" / f"Feature{extension}").read_text() == source
    finally:
        temporary.cleanup()


def test_swift_xcode_trace_tests_gates_capture_and_fan_in() -> None:
    temporary, project, run, manifest = _fixture()
    original_which = handler.shutil.which
    xcodebuild, xcrun = _fake_tools(run)
    handler.shutil.which = lambda name: str(xcodebuild if name == "xcodebuild" else xcrun) if name in {"xcodebuild", "xcrun"} else original_which(name)
    try:
        runtime_test = {
            "project": "App.xcodeproj",
            "scheme": "App",
            "simulator_udid": "SIMULATOR-1",
        }
        _write(run / "runtime-test.json", json.dumps(runtime_test))
        for operation_id, output, nonce in (
            ("ios-swift.trace_harness.v1", "trace.json", "c"),
            ("ios-swift.test_runner.v1", "test.json", "d"),
            ("ios-swift.project_gates.v1", "gates.json", "e"),
        ):
            output_id = "trace" if "trace_harness" in operation_id else "receipt"
            request = _request(
                project,
                run,
                f"feature-{nonce}",
                {"runtime": _artifact("run", "runtime-test.json")},
                {output_id: _artifact("run", output)},
            )
            assert _execute("ios-swift", manifest, operation_id, request, nonce)["status"] == "succeeded"

        runtime_capture = {
            "project": "App.xcodeproj",
            "scheme": "App",
            "simulator_udid": "SIMULATOR-1",
            "app_product": "App",
            "bundle_id": "com.example.app",
        }
        _write(run / "runtime-capture.json", json.dumps(runtime_capture))
        capture_request = _request(
            project,
            run,
            "feature-capture",
            {"runtime": _artifact("run", "runtime-capture.json")},
            {
                "actual": _artifact("run", "actual.png"),
                "provenance": _artifact("run", "provenance.json"),
            },
        )
        assert _execute("ios-swift", manifest, "ios-swift.runtime_capture.v1", capture_request, "f")["status"] == "succeeded"
        assert json.loads((run / "provenance.json").read_text())["actual_source"] == "simulator_screenshot"

        _write(project / "Sources" / "Routes.swift", "let routes: [String] = []\n")
        expected = hashlib.sha256((project / "Sources" / "Routes.swift").read_bytes()).hexdigest()
        _write(
            run / "mutation.json",
            json.dumps({"path": "Sources/Routes.swift", "expected_sha256": expected, "content": "let routes = [\"feature\"]\n"}),
        )
        fan_in = _request(
            project,
            run,
            "feature-fan-in",
            {"mutation_plan": _artifact("run", "mutation.json")},
            {"receipt": _artifact("run", "fan-in.json")},
        )
        assert _execute("ios-swift", manifest, "ios-swift.fan_in.v1", fan_in, "1")["status"] == "succeeded"
    finally:
        handler.shutil.which = original_which
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
