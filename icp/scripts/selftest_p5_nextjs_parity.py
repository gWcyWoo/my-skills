#!/usr/bin/env python3
"""Next.js eight-port execution and browser-evidence parity."""

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

from platforms import nextjs_execution_authorization_v1 as authorization  # noqa: E402
from platforms import nextjs_execution_binding_v1 as binding  # noqa: E402
from platforms import nextjs_execution_executor_v1 as executor  # noqa: E402
from platforms import nextjs_execution_handler_v1 as handler  # noqa: E402
from platforms import nextjs_operations_v1 as operations  # noqa: E402


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


def _execute(manifest: Path, operation_id: str, request: dict, nonce_character: str) -> dict:
    bound = binding.prepare_binding(manifest, operation_id, request)
    authorized = authorization.prepare_authorization(
        bound, execution_nonce=nonce_character * 64
    )
    return executor.execute_authorization(
        authorized,
        execution_nonce=nonce_character * 64,
        expected_binding_digest=bound["binding_digest"],
        expected_authorization_digest=authorized["authorization_digest"],
    )


def _fixture() -> tuple[tempfile.TemporaryDirectory, Path, Path, Path]:
    temporary = tempfile.TemporaryDirectory(prefix="icp-nextjs-parity-")
    root = Path(temporary.name).resolve()
    project = root / "project"
    run = project / ".icp" / "runs" / "test-run"
    project.mkdir()
    run.mkdir(parents=True)
    _write(project / "package.json", '{"scripts":{"dev":"next dev","test":"vitest","build":"next build"}}\n')
    config = {"route": "/", "viewport_width": 390, "viewport_height": 844}
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
        '{"kind":"icp.platform-package-selection.v1","platform_id":"nextjs","profile_id":"nextjs-standard"}',
    )
    manifest = _write(run / "selection-manifest.json", '{"kind":"test-selection"}\n')
    return temporary, project, run, manifest


def _fake_npm(root: Path) -> Path:
    script = _write(
        root / "npm",
        """#!/usr/bin/env python3
import http.server
import sys

if len(sys.argv) >= 3 and sys.argv[1:3] == ['run', 'dev']:
    port = int(sys.argv[sys.argv.index('--port') + 1])
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'<!doctype html><html><body><main data-design-node-id="root">Next ICP</main></body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
raise SystemExit(0)
""",
    )
    script.chmod(0o700)
    return script


def test_all_eight_operation_plans_are_closed_and_verifiable() -> None:
    temporary, project, run, _manifest = _fixture()
    try:
        source = _write(run / "input.txt", "input\n")
        del source
        for index, operation_id in enumerate(operations.list_operation_ids()):
            request = _request(
                project,
                run,
                f"feature-{index}",
                {"input": _artifact("run", "input.txt")},
                {"output": _artifact("run", f"output-{index}.json")},
            )
            plan = operations.build(operation_id, request)
            report = operations.verify_plan(plan)
            assert report["plan_digest"]
            assert plan["steps"][0]["action"].startswith("nextjs_")
    finally:
        temporary.cleanup()


def test_publication_fan_in_test_and_build_ports_execute() -> None:
    temporary, project, run, manifest = _fixture()
    original_which = handler.shutil.which
    fake_npm = _fake_npm(run)
    handler.shutil.which = lambda name: str(fake_npm) if name == "npm" else original_which(name)
    try:
        _write(run / "Feature.tsx", "export default function Feature(){return <main>ok</main>}\n")
        visible = _request(
            project,
            run,
            "feature-visible",
            {"component": _artifact("run", "Feature.tsx")},
            {"component": _artifact("project", "app/Feature.tsx")},
        )
        assert _execute(manifest, "nextjs.visible_codegen.v1", visible, "a")["status"] == "succeeded"

        for operation_id, suffix, nonce in (
            ("nextjs.fixture_codegen.v1", "fixture", "b"),
            ("nextjs.packaging.v1", "asset", "c"),
        ):
            _write(run / f"{suffix}.txt", f"{suffix}\n")
            request = _request(
                project,
                run,
                f"feature-{suffix}",
                {suffix: _artifact("run", f"{suffix}.txt")},
                {suffix: _artifact("project", f"public/{suffix}.txt")},
            )
            assert _execute(manifest, operation_id, request, nonce)["status"] == "succeeded"

        _write(project / "app" / "routes.ts", "export const routes=[];\n")
        import hashlib
        expected = hashlib.sha256((project / "app" / "routes.ts").read_bytes()).hexdigest()
        _write(
            run / "mutation.json",
            json.dumps(
                {
                    "path": "app/routes.ts",
                    "expected_sha256": expected,
                    "content": "export const routes=['/feature'];\n",
                }
            ),
        )
        fan_in = _request(
            project,
            run,
            "feature-fan-in",
            {"mutation_plan": _artifact("run", "mutation.json")},
            {"receipt": _artifact("run", "fan-in-receipt.json")},
        )
        assert _execute(manifest, "nextjs.fan_in.v1", fan_in, "d")["status"] == "succeeded"

        for operation_id, output, nonce in (
            ("nextjs.test_runner.v1", "test-receipt.json", "e"),
            ("nextjs.project_gates.v1", "gates-receipt.json", "f"),
        ):
            request = _request(
                project,
                run,
                f"feature-{nonce}",
                {"package": _artifact("project", "package.json")},
                {"receipt": _artifact("run", output)},
            )
            assert _execute(manifest, operation_id, request, nonce)["status"] == "succeeded"
    finally:
        handler.shutil.which = original_which
        temporary.cleanup()


def test_real_chrome_dom_trace_and_screenshot_provenance() -> None:
    temporary, project, run, manifest = _fixture()
    original_which = handler.shutil.which
    fake_npm = _fake_npm(run)
    handler.shutil.which = lambda name: str(fake_npm) if name == "npm" else original_which(name)
    try:
        _write(
            run / "runtime.json",
            json.dumps({"route": "/", "viewport_width": 390, "viewport_height": 844}),
        )
        trace_request = _request(
            project,
            run,
            "feature-trace",
            {"runtime": _artifact("run", "runtime.json")},
            {"trace": _artifact("run", "dom-trace.json")},
        )
        assert _execute(manifest, "nextjs.trace_harness.v1", trace_request, "1")["status"] == "succeeded"
        capture_request = _request(
            project,
            run,
            "feature-capture",
            {"runtime": _artifact("run", "runtime.json")},
            {
                "actual": _artifact("run", "actual.png"),
                "provenance": _artifact("run", "provenance.json"),
            },
        )
        assert _execute(manifest, "nextjs.runtime_capture.v1", capture_request, "2")["status"] == "succeeded"
        provenance = json.loads((run / "provenance.json").read_text())
        assert provenance["actual_source"] == "browser_screenshot"
        assert (run / "actual.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
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
