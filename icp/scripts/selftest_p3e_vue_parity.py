#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import selftest_p3c_vue_execution_chain as fixtures
from platforms import vue_execution_authorization_v1 as authorization_v1
from platforms import vue_execution_binding_v1 as binding_v1
from platforms import vue_execution_executor_v1 as executor_v1


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _execute(manifest_path: Path, operation_id: str, request: dict, nonce: str) -> dict:
    binding = binding_v1.prepare_binding(
        manifest_path=str(manifest_path), operation_id=operation_id, request=request
    )
    binding_digest = binding_v1.document_digest(binding)
    authorization = authorization_v1.prepare_authorization(
        binding,
        expected_manifest_path=str(manifest_path),
        expected_manifest_sha256=binding["selection_manifest_sha256"],
        expected_binding_digest=binding_digest,
        execution_nonce=nonce,
    )
    return executor_v1.execute_authorization(
        authorization,
        expected_manifest_path=str(manifest_path),
        expected_manifest_sha256=binding["selection_manifest_sha256"],
        expected_binding_digest=binding_digest,
        expected_authorization_digest=authorization["authorization_digest"],
    )


def test_fixture_packaging_and_fan_in_execute_with_durable_receipts() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3e-vue-") as directory:
        base = Path(directory).resolve()
        project_root, manifest_path = fixtures._frozen_vue_run(base)
        run_root = manifest_path.parent
        visual_contract = run_root / "contracts" / "visual.json"
        assets_manifest = run_root / "assets" / "manifest.json"
        mutation_manifest = run_root / "mutations" / "fan-in.json"
        (project_root / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
        (run_root / "receipts").mkdir(parents=True, exist_ok=True)
        _write_json(visual_contract, {"kind": "visual", "states": ["default"]})
        _write_json(assets_manifest, {"kind": "assets", "assets": []})
        app_path = project_root / "src" / "App.vue"
        before = app_path.read_bytes()
        _write_json(
            mutation_manifest,
            {
                "kind": "icp.vue-mutation-manifest.v1",
                "schema_version": 1,
                "mutations": [
                    {
                        "path": "src/App.vue",
                        "expected_sha256": hashlib.sha256(before).hexdigest(),
                        "content": "<template><main data-icp-fan-in>Integrated</main></template>\n",
                    }
                ],
            },
        )
        common = {"project_root": str(project_root), "run_root": str(run_root)}
        fixture_report = _execute(
            manifest_path,
            "vue.fixture_codegen.v1",
            {
                **common,
                "feature_id": "login",
                "visual_contract": "contracts/visual.json",
                "fixture_out": "tests/fixtures/login.fixture.js",
            },
            "21" * 16,
        )
        assert fixture_report["status"] == "success"
        packaging_report = _execute(
            manifest_path,
            "vue.packaging.v1",
            {
                **common,
                "assets_manifest": "assets/manifest.json",
                "receipt_out": "receipts/packaging.json",
            },
            "22" * 16,
        )
        assert packaging_report["status"] == "success"
        fan_in_report = _execute(
            manifest_path,
            "vue.fan_in.v1",
            {
                **common,
                "mutation_manifest": "mutations/fan-in.json",
                "receipt_out": "receipts/fan-in.json",
            },
            "23" * 16,
        )
        assert fan_in_report["status"] == "success"
        assert b"data-icp-fan-in" in app_path.read_bytes()


def test_real_vite_chrome_capture_has_browser_provenance() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3e-vue-browser-") as directory:
        base = Path(directory).resolve()
        project_root, manifest_path = fixtures._frozen_vue_run(base)
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "vue_vite_v1"
        shutil.copytree(fixture_root, project_root, dirs_exist_ok=True)
        npm = shutil.which("npm")
        if npm is None:
            raise AssertionError("npm is required for the real Vue parity fixture")
        installed = subprocess.run(
            [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=project_root,
            shell=False,
            capture_output=True,
            timeout=180,
            check=False,
        )
        assert installed.returncode == 0, installed.stderr.decode("utf-8", errors="replace")
        run_root = manifest_path.parent
        (run_root / "runtime").mkdir(parents=True, exist_ok=True)
        trace_report = _execute(
            manifest_path,
            "vue.trace_harness.v1",
            {
                "project_root": str(project_root),
                "run_root": str(run_root),
                "route": "/",
                "dom_trace_out": "runtime/dom-trace.json",
            },
            "30" * 16,
        )
        assert trace_report["status"] == "success", trace_report
        request = {
            "project_root": str(project_root),
            "run_root": str(run_root),
            "route": "/",
            "viewport": {"width": 390, "height": 844},
            "actual_out": "runtime/actual.png",
            "provenance_out": "runtime/provenance.json",
        }
        report = _execute(
            manifest_path,
            "vue.runtime_capture.v1",
            request,
            "31" * 16,
        )
        assert report["status"] == "success", report
        actual = run_root / "runtime" / "actual.png"
        provenance = json.loads((run_root / "runtime" / "provenance.json").read_text(encoding="utf-8"))
        assert actual.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert provenance["actual_source"] == "browser_screenshot"
        assert provenance["actual_sha256"] == hashlib.sha256(actual.read_bytes()).hexdigest()
        test_report = _execute(
            manifest_path,
            "vue.test_runner.v1",
            {
                "project_root": str(project_root),
                "run_root": str(run_root),
                "phase": "green",
                "evidence_out": "runtime/unit-evidence.json",
            },
            "32" * 16,
        )
        assert test_report["status"] == "success", test_report
        gates_report = _execute(
            manifest_path,
            "vue.project_gates.v1",
            {
                "project_root": str(project_root),
                "run_root": str(run_root),
                "report_out": "runtime/gates.json",
            },
            "33" * 16,
        )
        assert gates_report["status"] == "success", gates_report


def main() -> int:
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    failures = 0
    for name, test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok {name}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
