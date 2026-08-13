#!/usr/bin/env python3
"""TDD contract for controlled non-Flutter/Vue platform execution."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from platforms import nextjs_execution_authorization_v1 as authorization  # noqa: E402
from platforms import nextjs_execution_binding_v1 as binding  # noqa: E402
from platforms import nextjs_execution_executor_v1 as executor  # noqa: E402
from platforms import nextjs_operations_v1 as operations  # noqa: E402


NONCE = "a" * 64


def _fixture() -> tuple[tempfile.TemporaryDirectory, Path, Path, Path, dict]:
    temporary = tempfile.TemporaryDirectory(prefix="icp-p5-controlled-")
    root = Path(temporary.name).resolve()
    project = root / "project"
    run = project / ".icp" / "runs" / "test-run"
    (project / "app").mkdir(parents=True)
    (run / "generated").mkdir(parents=True)
    config = {"route": "/", "viewport_width": 390, "viewport_height": 844}
    (project / ".icp" / "platform-config.json").write_text(json.dumps(config))
    config_digest = hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (run / "entry-readiness.json").write_text(
        json.dumps(
            {
                "kind": "icp.entry-readiness-report.v1",
                "status": "ready",
                "checks": [
                    {"id": "runtime_config", "status": "pass", "evidence_digest": config_digest}
                ],
            }
        )
    )
    (run / "platform-package-selection.json").write_text(
        '{"kind":"icp.platform-package-selection.v1","platform_id":"nextjs","profile_id":"nextjs-standard"}'
    )
    source = run / "generated" / "Feature.tsx"
    source.write_text("export default function Feature(){return <main>ok</main>}\n")
    manifest = run / "selection-manifest.json"
    manifest.write_text('{"kind":"test-selection"}\n')
    request = {
        "project_root": str(project),
        "run_root": str(run),
        "feature_id": "feature-home",
        "inputs": {
            "component": {"root": "run", "path": "generated/Feature.tsx"},
        },
        "outputs": {
            "component": {"root": "project", "path": "app/Feature.tsx"},
        },
    }
    return temporary, project, run, manifest, request


def test_visible_codegen_executes_once_and_replays_receipt() -> None:
    temporary, project, _run, manifest, request = _fixture()
    try:
        plan = operations.build("nextjs.visible_codegen.v1", request)
        operations.verify_plan(plan)
        bound = binding.prepare_binding(manifest, "nextjs.visible_codegen.v1", request)
        authorized = authorization.prepare_authorization(bound, execution_nonce=NONCE)
        first = executor.execute_authorization(
            authorized,
            execution_nonce=NONCE,
            expected_binding_digest=bound["binding_digest"],
            expected_authorization_digest=authorized["authorization_digest"],
        )
        second = executor.execute_authorization(
            authorized,
            execution_nonce=NONCE,
            expected_binding_digest=bound["binding_digest"],
            expected_authorization_digest=authorized["authorization_digest"],
        )
        assert first == second
        assert first["status"] == "succeeded"
        assert first["replayed"] is False
        assert (project / "app" / "Feature.tsx").read_text().endswith("</main>}\n")
    finally:
        temporary.cleanup()


def test_operation_plan_rejects_tampered_output() -> None:
    temporary, _project, _run, _manifest, request = _fixture()
    try:
        plan = operations.build("nextjs.visible_codegen.v1", request)
        tampered = copy.deepcopy(plan)
        tampered["steps"][0]["outputs"]["component"] = "/tmp/escape.tsx"
        try:
            operations.verify_plan(tampered)
        except Exception:
            return
        raise AssertionError("tampered output was accepted")
    finally:
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
