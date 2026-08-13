#!/usr/bin/env python3
"""P3c Vue execution-chain vertical self-test."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


def _write_vue_project(root: Path) -> None:
    (root / "src" / "features" / "login").mkdir(parents=True)
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "e2e").mkdir(parents=True)
    package = {
        "name": "icp-vue-fixture",
        "private": True,
        "version": "1.0.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "test:unit": "vitest run",
            "test:e2e": "playwright test",
        },
        "dependencies": {"vue": "^3.0.0"},
        "devDependencies": {
            "@playwright/test": "^1.0.0",
            "vite": "^7.0.0",
            "vitest": "^3.0.0",
        },
    }
    (root / "package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "index.html").write_text('<div id="app"></div>\n', encoding="utf-8")
    (root / "src" / "main.js").write_text("export default {}\n", encoding="utf-8")
    (root / "src" / "App.vue").write_text("<template><main /></template>\n", encoding="utf-8")
    (root / "tests" / "unit" / "app.spec.js").write_text("export {}\n", encoding="utf-8")
    (root / "tests" / "e2e" / "app.spec.js").write_text("export {}\n", encoding="utf-8")


def _frozen_vue_run(base: Path) -> tuple[Path, Path]:
    freezer = importlib.import_module("freeze_selection_manifest")
    common = importlib.import_module("icp_common")
    project_root = base / "project"
    project_root.mkdir()
    _write_vue_project(project_root)
    task_ref = base / "tasks.csv"
    task_ref.write_text(
        "title,status,design_url\nLogin,,https://figma.com/file/icp-vue-login\n",
        encoding="utf-8",
    )
    resolved = {
        "design_source": "lanhu-figma",
        "platform": "vue",
        "profile": "vue-vite",
        "project_root": str(project_root),
        "task_ref": str(task_ref),
        "task_source": "csv",
    }
    ack = freezer.freeze_selection_manifest(
        resolved_config=resolved,
        candidates=[
            {
                "row_index": 2,
                "title": "Login",
                "status": "",
                "design_url": "https://figma.com/file/icp-vue-login",
            }
        ],
        batch_id="p3c-vue-binding",
        registries=common.load_registries(),
    )
    manifest_path = Path(ack["manifest_path"])
    (manifest_path.parent / "entry-readiness.json").write_text(
        '{"kind":"icp.entry-readiness-report.v1","status":"ready"}', encoding="utf-8"
    )
    (manifest_path.parent / "platform-package-selection.json").write_text(
        '{"kind":"icp.platform-package-selection.v1","platform_id":"vue","profile_id":"vue-vite"}',
        encoding="utf-8",
    )
    return project_root, manifest_path


def _prepare_visible_binding(base: Path) -> tuple[dict, Path]:
    binding_module = importlib.import_module("platforms.vue_execution_binding_v1")
    project_root, manifest_path = _frozen_vue_run(base)
    run_root = manifest_path.parent
    (run_root / "design").mkdir()
    (run_root / "contracts").mkdir()
    (run_root / "design" / "bundle.json").write_text("{}\n", encoding="utf-8")
    (run_root / "contracts" / "requirement.json").write_text("{}\n", encoding="utf-8")
    request = {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "feature_id": "login",
        "design_bundle": "design/bundle.json",
        "requirement_contract": "contracts/requirement.json",
        "sfc_out": "src/features/login/LoginPage.vue",
        "css_out": "src/features/login/login.css",
    }
    return (
        binding_module.prepare_binding(
            manifest_path=str(manifest_path),
            operation_id="vue.visible_codegen.v1",
            request=request,
        ),
        manifest_path,
    )


def test_vue_binding_rebuilds_current_active_plan() -> None:
    binding_module = importlib.import_module("platforms.vue_execution_binding_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        binding, manifest_path = _prepare_visible_binding(Path(tmpdir).resolve())
        verified = binding_module.verify_binding(binding)
    assert binding["kind"] == "icp.vue-execution-binding.v1"
    assert binding["platform_id"] == "vue"
    assert binding["profile_id"] == "vue-vite"
    assert binding["activation_state"] == "active"
    assert binding["executable"] is True
    assert binding["selection_verification"]["manifest_path"] == str(manifest_path)
    assert binding["package_resolution"]["activation_state"] == "active"
    assert binding["plan"]["operation_id"] == "vue.visible_codegen.v1"
    assert verified["ok"] is True
    assert verified["binding_digest"] == binding_module.document_digest(binding)


def test_vue_authorization_requires_supervisor_expected_digests() -> None:
    binding_module = importlib.import_module("platforms.vue_execution_binding_v1")
    authorization_module = importlib.import_module(
        "platforms.vue_execution_authorization_v1"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        binding, manifest_path = _prepare_visible_binding(Path(tmpdir).resolve())
        expected_binding_digest = binding_module.document_digest(binding)
        authorization = authorization_module.prepare_authorization(
            binding,
            expected_manifest_path=str(manifest_path),
            expected_manifest_sha256=binding["selection_manifest_sha256"],
            expected_binding_digest=expected_binding_digest,
            execution_nonce="12" * 16,
        )
        verify = authorization_module.verify_authorization(
            authorization,
            expected_manifest_path=str(manifest_path),
            expected_manifest_sha256=binding["selection_manifest_sha256"],
            expected_binding_digest=expected_binding_digest,
            expected_authorization_digest=authorization["authorization_digest"],
        )
    assert authorization["kind"] == "icp.vue-execution-authorization-candidate.v1"
    assert authorization["activation_state"] == "inactive"
    assert authorization["executable"] is False
    assert authorization["execution_nonce"] == "12" * 16
    assert authorization["binding"] == binding
    assert verify["ok"] is True
    assert verify["authorization_digest"] == authorization["authorization_digest"]


def test_vue_executor_renders_feature_once_with_durable_receipts() -> None:
    binding_module = importlib.import_module("platforms.vue_execution_binding_v1")
    authorization_module = importlib.import_module(
        "platforms.vue_execution_authorization_v1"
    )
    executor_module = importlib.import_module("platforms.vue_execution_executor_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        binding, manifest_path = _prepare_visible_binding(Path(tmpdir).resolve())
        binding_digest = binding_module.document_digest(binding)
        authorization = authorization_module.prepare_authorization(
            binding,
            expected_manifest_path=str(manifest_path),
            expected_manifest_sha256=binding["selection_manifest_sha256"],
            expected_binding_digest=binding_digest,
            execution_nonce="34" * 16,
        )
        kwargs = {
            "expected_manifest_path": str(manifest_path),
            "expected_manifest_sha256": binding["selection_manifest_sha256"],
            "expected_binding_digest": binding_digest,
            "expected_authorization_digest": authorization["authorization_digest"],
        }
        report = executor_module.execute_authorization(authorization, **kwargs)
        sfc = Path(binding["plan"]["steps"][0]["outputs"]["sfc"])
        css = Path(binding["plan"]["steps"][0]["outputs"]["css"])
        assert report["status"] == "success"
        assert sfc.is_file() and css.is_file()
        assert "<template>" in sfc.read_text(encoding="utf-8")
        assert "data-icp-feature=\"login\"" in sfc.read_text(encoding="utf-8")
        before = (sfc.read_bytes(), css.read_bytes())
        try:
            executor_module.execute_authorization(authorization, **kwargs)
        except executor_module.VueExecutionExecutorError:
            pass
        else:
            raise AssertionError("authorization replay unexpectedly succeeded")
        assert (sfc.read_bytes(), css.read_bytes()) == before
        receipt_root = manifest_path.parent / ".icp-vue-execution-receipts-v1"
        assert (receipt_root / f"{'34' * 16}.claim.json").is_file()
        assert (receipt_root / f"{'34' * 16}.result.json").is_file()


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
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"FAILED {failures}/{len(tests)}")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
