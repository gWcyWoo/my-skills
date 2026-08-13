#!/usr/bin/env python3
"""P3b2 Vue package vertical self-test."""

from __future__ import annotations

import importlib
import hashlib
import json
import sys
import tempfile
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    ).encode("utf-8")


def test_vue_descriptor_is_complete_and_inactive() -> None:
    module = importlib.import_module("platforms.vue_standard_v1")
    descriptor = module.describe()
    assert tuple(descriptor) == (
        "kind",
        "schema_version",
        "platform_id",
        "profile_id",
        "activation_state",
        "executable",
        "operations",
    )
    assert descriptor["kind"] == "icp.vue-platform-adapter-descriptor.v1"
    assert descriptor["schema_version"] == 1
    assert descriptor["platform_id"] == "vue"
    assert descriptor["profile_id"] == "vue-vite"
    assert descriptor["activation_state"] == "inactive"
    assert descriptor["executable"] is False
    assert [item["id"] for item in descriptor["operations"]] == [
        "project_preflight",
        "visible_codegen",
        "fixture_codegen",
        "trace_harness",
        "packaging",
        "test_runner",
        "runtime_capture",
        "project_gates",
        "fan_in",
    ]
    assert all(
        item["implementation_state"] == "implemented"
        for item in descriptor["operations"]
    )
    assert _canonical(module.describe()) == _canonical(descriptor)
    report = module.verify_descriptor()
    assert report == {
        "ok": True,
        "kind": "icp.vue-platform-adapter-descriptor-verify.v1",
        "schema_version": 1,
        "platform_id": "vue",
        "profile_id": "vue-vite",
        "activation_state": "inactive",
        "executable": False,
        "operations_total": 9,
    }


def _write_vue_project(root: Path) -> None:
    (root / "src").mkdir()
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


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_vue_project_preflight_is_read_only_and_binds_toolchain() -> None:
    module = importlib.import_module("platforms.vue_project_preflight_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        _write_vue_project(root)
        before = _tree_bytes(root)
        report = module.preflight(root)
        assert _tree_bytes(root) == before
    assert tuple(report) == (
        "kind",
        "schema_version",
        "operation_id",
        "platform_id",
        "profile_id",
        "project_root",
        "project",
        "toolchain",
    )
    assert report["kind"] == "icp.vue-project-preflight.v1"
    assert report["operation_id"] == "vue.project_preflight.v1"
    assert report["platform_id"] == "vue"
    assert report["profile_id"] == "vue-vite"
    assert report["project"]["package_name"] == "icp-vue-fixture"
    assert report["project"]["source_directory"] == "src"
    assert report["project"]["unit_test_directory"] == "tests/unit"
    assert report["project"]["e2e_test_directory"] == "tests/e2e"
    assert report["toolchain"]["node_version"].startswith("v")
    assert report["toolchain"]["npm_version"]
    assert len(report["toolchain"]["node_executable_sha256"]) == 64
    assert len(report["toolchain"]["npm_executable_sha256"]) == 64


def test_vue_visible_codegen_plan_is_deterministic_and_non_executable() -> None:
    module = importlib.import_module("platforms.vue_operations_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()
        project_root = base / "project"
        run_root = base / "run"
        project_root.mkdir()
        run_root.mkdir()
        _write_vue_project(project_root)
        (project_root / "src" / "features" / "login").mkdir(parents=True)
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
        before_project = _tree_bytes(project_root)
        before_run = _tree_bytes(run_root)
        first = module.build("vue.visible_codegen.v1", request)
        second = module.build("vue.visible_codegen.v1", dict(request))
        assert first == second
        assert _tree_bytes(project_root) == before_project
        assert _tree_bytes(run_root) == before_run
    assert tuple(first) == (
        "kind",
        "schema_version",
        "operation_id",
        "platform_id",
        "profile_id",
        "request_digest",
        "steps",
    )
    assert first["kind"] == "icp.vue-operation-plan.v1"
    assert first["operation_id"] == "vue.visible_codegen.v1"
    assert first["platform_id"] == "vue"
    assert first["profile_id"] == "vue-vite"
    assert first["steps"] == [
        {
            "step_id": "render_vue_feature",
            "action": "render_vue_feature",
            "inputs": {
                "design_bundle": str(run_root / "design" / "bundle.json"),
                "requirement_contract": str(
                    run_root / "contracts" / "requirement.json"
                ),
            },
            "outputs": {
                "sfc": str(project_root / "src" / "features" / "login" / "LoginPage.vue"),
                "css": str(project_root / "src" / "features" / "login" / "login.css"),
            },
        }
    ]
    assert not any(
        key in _canonical(first).decode("utf-8")
        for key in ('"command"', '"argv"', '"shell"', '"env"', '"executable"')
    )
    verify = module.verify_plan(first)
    assert verify["ok"] is True
    assert verify["operation_id"] == "vue.visible_codegen.v1"
    assert verify["steps_total"] == 1
    assert len(verify["plan_digest"]) == 64


def test_vue_operation_registry_covers_all_non_preflight_ports() -> None:
    module = importlib.import_module("platforms.vue_operations_v1")
    assert module.list_operation_ids() == (
        "vue.visible_codegen.v1",
        "vue.fixture_codegen.v1",
        "vue.trace_harness.v1",
        "vue.packaging.v1",
        "vue.test_runner.v1",
        "vue.runtime_capture.v1",
        "vue.project_gates.v1",
        "vue.fan_in.v1",
    )


def test_vue_fixture_codegen_plan_binds_visual_contract() -> None:
    module = importlib.import_module("platforms.vue_operations_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()
        project_root = base / "project"
        run_root = base / "run"
        project_root.mkdir()
        run_root.mkdir()
        _write_vue_project(project_root)
        (project_root / "src" / "features" / "login").mkdir(parents=True)
        (run_root / "contracts").mkdir()
        (run_root / "contracts" / "visual.json").write_text("{}\n", encoding="utf-8")
        plan = module.build(
            "vue.fixture_codegen.v1",
            {
                "project_root": str(project_root),
                "run_root": str(run_root),
                "feature_id": "login",
                "visual_contract": "contracts/visual.json",
                "fixture_out": "src/features/login/login.fixture.js",
            },
        )
    assert plan["steps"] == [
        {
            "step_id": "render_vue_fixture",
            "action": "render_vue_fixture",
            "inputs": {"visual_contract": str(run_root / "contracts" / "visual.json")},
            "outputs": {
                "fixture": str(
                    project_root / "src" / "features" / "login" / "login.fixture.js"
                )
            },
        }
    ]
    assert module.verify_plan(plan)["operation_id"] == "vue.fixture_codegen.v1"


def test_vue_remaining_operation_plans_are_closed_and_verifiable() -> None:
    module = importlib.import_module("platforms.vue_operations_v1")
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()
        project_root = base / "project"
        run_root = base / "run"
        project_root.mkdir()
        run_root.mkdir()
        _write_vue_project(project_root)
        (run_root / "inputs").mkdir()
        (run_root / "outputs").mkdir()
        for name in ("assets.json", "mutations.json"):
            (run_root / "inputs" / name).write_text("{}\n", encoding="utf-8")
        common = {"project_root": str(project_root), "run_root": str(run_root)}
        cases = (
            (
                "vue.trace_harness.v1",
                {**common, "route": "/login", "dom_trace_out": "outputs/dom-trace.json"},
                "capture_dom_trace",
            ),
            (
                "vue.packaging.v1",
                {
                    **common,
                    "assets_manifest": "inputs/assets.json",
                    "receipt_out": "outputs/packaging.json",
                },
                "prepare_vue_packaging",
            ),
            (
                "vue.test_runner.v1",
                {**common, "phase": "red", "evidence_out": "outputs/tests.json"},
                "run_vue_tests",
            ),
            (
                "vue.runtime_capture.v1",
                {
                    **common,
                    "route": "/login",
                    "viewport": {"width": 390, "height": 844},
                    "actual_out": "outputs/actual.png",
                    "provenance_out": "outputs/capture.json",
                },
                "capture_browser_screenshot",
            ),
            (
                "vue.project_gates.v1",
                {**common, "report_out": "outputs/gates.json"},
                "run_vue_project_gates",
            ),
            (
                "vue.fan_in.v1",
                {
                    **common,
                    "mutation_manifest": "inputs/mutations.json",
                    "receipt_out": "outputs/fan-in.json",
                },
                "apply_vue_fan_in",
            ),
        )
        for operation_id, request, action in cases:
            plan = module.build(operation_id, request)
            assert plan["operation_id"] == operation_id
            assert plan["steps"][0]["action"] == action
            assert module.verify_plan(plan)["operation_id"] == operation_id
            encoded = _canonical(plan).decode("utf-8")
            for forbidden in ('"command"', '"argv"', '"shell"', '"env"'):
                assert forbidden not in encoded


def test_vue_platform_package_is_indexed_resolvable_and_active() -> None:
    package = importlib.import_module("platforms.vue_package_v1")
    contract = importlib.import_module("platforms.platform_package_contract_v1")
    resolver = importlib.import_module("platform_package_resolver_v1")
    common = importlib.import_module("icp_common")
    descriptor = package.describe_package()
    contract.validate_descriptor(descriptor)
    assert descriptor["platform_id"] == "vue"
    assert descriptor["profile_id"] == "vue-vite"
    assert descriptor["activation_state"] == "active"
    assert descriptor["executable"] is True
    assert descriptor["actual_source_types"] == ["browser_screenshot"]
    assert [item["role"] for item in descriptor["components"]] == [
        "descriptor",
        "project_preflight",
        "operation_plans",
        "binding",
        "authorization",
        "executor",
    ]
    assert all(item["implementation_state"] == "implemented" for item in descriptor["ports"])
    verify = package.verify_package()
    assert verify["ok"] is True
    assert verify["package_digest"] == contract.compute_descriptor_digest(descriptor)

    index_path = SCRIPTS_ROOT.parent / "references" / "platform_packages_v1.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert [(item["platform_id"], item["profile_id"]) for item in index["packages"]] == [
        ("android-java", "android-java-standard"),
        ("android-kotlin", "android-kotlin-standard"),
        ("flutter", "flutter-standard"),
        ("ios-objc", "ios-objc-standard"),
        ("ios-swift", "ios-swift-standard"),
        ("nextjs", "nextjs-standard"),
        ("vue", "vue-vite"),
    ]
    module_path = SCRIPTS_ROOT / "platforms" / "vue_package_v1.py"
    module_bytes = module_path.read_bytes()
    row = next(item for item in index["packages"] if item["platform_id"] == "vue")
    assert row["package_module_sha256"] == hashlib.sha256(module_bytes).hexdigest()
    assert row["package_descriptor_digest"] == verify["package_digest"]
    resolution = resolver.resolve_package(
        platform_id="vue",
        profile_id="vue-vite",
        registries=common.load_registries(),
        package_index=index,
        package_descriptor=descriptor,
        package_module_bytes=module_bytes,
    )
    assert resolution["platform_id"] == "vue"
    assert resolution["profile_id"] == "vue-vite"
    assert resolution["activation_state"] == "active"
    assert resolution["executable"] is True


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
