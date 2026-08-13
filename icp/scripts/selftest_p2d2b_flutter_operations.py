#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2d2b Flutter
trusted-operation plan registry extension (packaging/test_runner).

P2d2b extends ``platforms/flutter_operations_v1.py`` with two new
append-only operation IDs and their nine single-step variants:

* ``flutter.packaging.v1`` with actions:
  - ``copy_assets`` (primitive ``copy_assets.py``)
  - ``update_pubspec_asset`` (primitive ``update_pubspec_assets.py``)
  - ``prepare`` (primitive ``prepare_assembly_packaging.py``)
  - ``verify`` (primitive ``prepare_assembly_packaging.py``)
* ``flutter.test_runner.v1`` with phases:
  - ``red`` (primitive ``assembly_tdd_guard.py``, fixed failure-kind)
  - ``green`` (primitive ``assembly_tdd_guard.py``)
  - ``adopt`` (primitive ``assembly_tdd_guard.py``, fixed authorization)
  - ``verify`` (primitive ``assembly_tdd_guard.py``)
  - ``retire_stale_template_tests`` (primitive
    ``retire_stale_flutter_template_tests.py``)

This selftest never executes the primitives; it only validates that the
plan builder constructs deterministic, immutable argv plans and that
``verify_plan`` independently re-attests them. No CLI, no subprocess,
no project/run/capsule writes, no edits to the registry/P2c descriptor,
no reads of sibling ``iff/``.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2b_flutter_operations.py
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
MODULE_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
P2C_DESCRIPTOR_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"

KIND_PLAN = "icp.trusted-operation-plan.v1"
KIND_VERIFY = "icp.trusted-operation-plan-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 120
TIMEOUT_TDD_SECONDS = 600

OPERATION_IDS = (
    "flutter.visible_codegen.v1",
    "flutter.fixture_codegen.v1",
    "flutter.trace_harness.v1",
    "flutter.packaging.v1",
    "flutter.test_runner.v1",
    "flutter.runtime_capture.v1",
    "flutter.project_gates.v1",
    "flutter.fan_in.v1",
)

PACKAGING_ACTIONS = (
    "copy_assets",
    "update_pubspec_asset",
    "prepare",
    "verify",
)
TEST_RUNNER_PHASES = (
    "red",
    "green",
    "adopt",
    "verify",
    "retire_stale_template_tests",
)


# ---------------------------------------------------------------------------
# Module loader.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path = MODULE_PATH):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2d2b_"):
    """Yield a temp dir whose path is realpath-canonicalized so the macOS
    ``/tmp`` -> ``/private/tmp`` symlink never trips the strict resolve
    containment check."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> bytes:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def _write_pubspec(project_root: Path) -> None:
    """Write a minimal but valid pubspec.yaml at project_root."""
    (project_root / "pubspec.yaml").write_text(
        'name: my_app\n'
        'description: "test fixture"\n'
        'publish_to: "none"\n'
        'environment:\n'
        '  sdk: ">=3.0.0 <4.0.0"\n',
        encoding="utf-8",
    )


def _new_project_run(tmp: Path):
    proj = tmp / "proj"
    run = tmp / "run"
    proj.mkdir()
    run.mkdir()
    _write_pubspec(proj)
    return proj, run


# --- packaging fixtures --------------------------------------------------


def _make_packaging_copy_assets_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "action": "copy_assets",
        "asset_manifest_path": "asset_manifest.json",
        "asset_target_path": "assets/canvas",
    }


def _setup_packaging_copy_assets(project_root: Path, run_root: Path) -> None:
    _write_json(run_root / "asset_manifest.json", {"a": "a.png"})
    (project_root / "assets").mkdir(parents=True, exist_ok=True)


def _make_packaging_update_pubspec_asset_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "action": "update_pubspec_asset",
        "asset_path": "assets/icons/logo.png",
    }


def _setup_packaging_update_pubspec_asset(project_root: Path, run_root: Path) -> None:
    (project_root / "assets" / "icons").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "icons" / "logo.png").write_bytes(b"\x89PNG\r\n")


def _make_packaging_prepare_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "action": "prepare",
        "spec_root_path": "feature_spec",
        "packaging_out_path": "packaging_evidence.json",
    }


def _setup_packaging_prepare(project_root: Path, run_root: Path) -> None:
    (run_root / "feature_spec").mkdir(parents=True, exist_ok=True)


def _make_packaging_verify_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "action": "verify",
        "packaging_evidence_path": "packaging_evidence.json",
    }


def _setup_packaging_verify(project_root: Path, run_root: Path) -> None:
    _write_json(run_root / "packaging_evidence.json", {"phase": "post_red_pre_green"})


@contextlib.contextmanager
def _packaging_project(action: str):
    setups = {
        "copy_assets": (_make_packaging_copy_assets_request, _setup_packaging_copy_assets),
        "update_pubspec_asset": (
            _make_packaging_update_pubspec_asset_request,
            _setup_packaging_update_pubspec_asset,
        ),
        "prepare": (_make_packaging_prepare_request, _setup_packaging_prepare),
        "verify": (_make_packaging_verify_request, _setup_packaging_verify),
    }
    maker, setup = setups[action]
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        setup(proj, run)
        yield proj, run, maker(proj, run)


# --- test_runner fixtures -------------------------------------------------


def _make_test_runner_red_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "phase": "red",
        "spec_root_path": "feature_spec",
        "test_target": "test/widget/widget_test.dart",
    }


def _make_test_runner_green_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "phase": "green",
        "spec_root_path": "feature_spec",
        "test_target": "test/widget/widget_test.dart",
    }


def _make_test_runner_adopt_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "phase": "adopt",
        "spec_root_path": "feature_spec",
        "test_target": "test/widget/widget_test.dart",
    }


def _make_test_runner_verify_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "phase": "verify",
        "spec_root_path": "feature_spec",
    }


def _make_test_runner_retire_request(
    project_root: Path, run_root: Path
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "phase": "retire_stale_template_tests",
        "retirement_out_path": "retirement_report.json",
    }


def _setup_test_runner_red_green_adopt(project_root: Path, run_root: Path) -> None:
    (run_root / "feature_spec").mkdir(parents=True, exist_ok=True)
    (project_root / "test" / "widget").mkdir(parents=True, exist_ok=True)
    (project_root / "test" / "widget" / "widget_test.dart").write_text(
        "// test\n", encoding="utf-8"
    )


def _setup_test_runner_verify(project_root: Path, run_root: Path) -> None:
    (run_root / "feature_spec").mkdir(parents=True, exist_ok=True)


def _setup_test_runner_retire(project_root: Path, run_root: Path) -> None:
    pass


@contextlib.contextmanager
def _test_runner_project(phase: str):
    makers = {
        "red": _make_test_runner_red_request,
        "green": _make_test_runner_green_request,
        "adopt": _make_test_runner_adopt_request,
        "verify": _make_test_runner_verify_request,
        "retire_stale_template_tests": _make_test_runner_retire_request,
    }
    setups = {
        "red": _setup_test_runner_red_green_adopt,
        "green": _setup_test_runner_red_green_adopt,
        "adopt": _setup_test_runner_red_green_adopt,
        "verify": _setup_test_runner_verify,
        "retire_stale_template_tests": _setup_test_runner_retire,
    }
    maker = makers[phase]
    setup = setups[phase]
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        setup(proj, run)
        yield proj, run, maker(proj, run)


# ---------------------------------------------------------------------------
# 1. Module + constants + public API surface.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2d2b_loads")
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.KIND_PLAN == KIND_PLAN
    assert module.KIND_VERIFY == KIND_VERIFY
    assert module.PLATFORM_ID == PLATFORM_ID
    assert module.PROFILE_ID == PROFILE_ID
    assert module.TIMEOUT_SECONDS == TIMEOUT_SECONDS


def test_module_exposes_typed_exception() -> None:
    module = _load("p2d2b_exc")
    assert hasattr(module, "OperationPlanError")
    assert issubclass(module.OperationPlanError, ValueError)


def test_module_has_no_cli_main() -> None:
    module = _load("p2d2b_nocli")
    assert not hasattr(module, "main")
    source = MODULE_PATH.read_text()
    assert '__name__ == "__main__"' not in source


def test_public_api_exposes_only_three_functions() -> None:
    """The public Python API must remain exactly the three P2d2a functions."""
    module = _load("p2d2b_pubapi")
    assert callable(module.list_operation_ids)
    assert callable(module.build)
    assert callable(module.verify_plan)
    allowed = {"list_operation_ids", "build", "verify_plan"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed)
    assert extra == [], f"unexpected public functions: {extra}"
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"OperationPlanError"}, public_classes


def test_module_exposes_no_override_parameters() -> None:
    module = _load("p2d2b_noparams")
    forbidden = (
        "EXECUTABLE_OVERRIDE", "INTERPRETER_OVERRIDE", "ENV_OVERRIDE",
        "ARGV_OVERRIDE", "COMMAND_OVERRIDE", "REGISTRY_OVERRIDE",
        "MANIFEST_OVERRIDE", "CAPSULE_OVERRIDE", "ACTIVATION",
    )
    for attr in forbidden:
        assert not hasattr(module, attr), f"module exposes override {attr}"


# ---------------------------------------------------------------------------
# 2. Operation order — append-only five IDs.
# ---------------------------------------------------------------------------


def test_list_operation_ids_exact_order() -> None:
    module = _load("p2d2b_oporder")
    assert module.list_operation_ids() == OPERATION_IDS
    assert isinstance(module.list_operation_ids(), tuple)


def test_list_operation_ids_returns_new_tuple_each_call() -> None:
    module = _load("p2d2b_newtuple")
    a = module.list_operation_ids()
    b = module.list_operation_ids()
    assert a == b
    assert a is not b


def test_list_operation_ids_tuple_is_not_module_constant() -> None:
    """Mutating the returned tuple must not affect the module constant."""
    module = _load("p2d2b_notconst")
    returned = module.list_operation_ids()
    assert isinstance(returned, tuple)
    # The returned tuple must not be the same object as any module attribute.
    for attr in dir(module):
        if attr.startswith("_"):
            continue
        if getattr(module, attr) is returned:
            raise AssertionError(f"returned tuple aliases module attr {attr!r}")


# ---------------------------------------------------------------------------
# 3. Capsule-first ordering.
# ---------------------------------------------------------------------------


def test_build_calls_verify_capsule_first_packaging() -> None:
    module = _load("p2d2b_capsfirst_pack")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _packaging_project("prepare") as (proj, run, request):
            try:
                module.build("flutter.packaging.v1", request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_calls_verify_capsule_first_test_runner() -> None:
    module = _load("p2d2b_capsfirst_test")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _test_runner_project("red") as (proj, run, request):
            try:
                module.build("flutter.test_runner.v1", request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_capsule_failure_redacts_generic_exception() -> None:
    module = _load("p2d2b_capsgeneric")

    class _SecretError(Exception):
        pass

    def _boom():
        raise _SecretError("SUPER_SECRET_BLOB")

    module._verify_capsule = _boom
    try:
        with _packaging_project("prepare") as (proj, run, request):
            try:
                module.build("flutter.packaging.v1", request)
            except module.OperationPlanError as exc:
                msg = str(exc)
                assert "SUPER_SECRET_BLOB" not in msg
                assert "_SecretError" in msg or "SecretError" in msg
            else:
                raise AssertionError("build swallowed generic exception")
    finally:
        del module._verify_capsule


# ---------------------------------------------------------------------------
# 4. Unknown / forbidden / missing keys.
# ---------------------------------------------------------------------------


def test_build_rejects_unknown_operation_id_packaging_zone() -> None:
    """An unregistered future operation must remain unknown to the registry."""
    module = _load("p2d2b_unknown_op")
    with _packaging_project("prepare") as (proj, run, request):
        try:
            module.build("flutter.future_op.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown operation_id accepted")


def test_build_rejects_non_dict_request_packaging() -> None:
    module = _load("p2d2b_nondict_pack")
    try:
        module.build("flutter.packaging.v1", "not a dict")
    except module.OperationPlanError:
        pass
    else:
        raise AssertionError("non-dict request accepted")


def test_build_rejects_forbidden_command_key_in_packaging_request() -> None:
    module = _load("p2d2b_cmd_pack")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["command"] = "evil"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden command key accepted")


def test_build_rejects_forbidden_shell_key_in_test_runner_request() -> None:
    module = _load("p2d2b_shell_test")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["shell"] = True
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden shell key accepted")


def test_build_rejects_forbidden_executable_key_in_test_runner_request() -> None:
    """No caller-supplied Flutter executable is ever accepted."""
    module = _load("p2d2b_exec_test")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["executable"] = "/usr/local/bin/flutter"
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden executable key accepted")


def test_build_rejects_forbidden_argv_key_in_packaging_request() -> None:
    module = _load("p2d2b_argv_pack")
    with _packaging_project("copy_assets") as (proj, run, request):
        bad = dict(request)
        bad["argv"] = ["--flutter"]
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden argv key accepted")


def test_build_rejects_forbidden_operation_id_key_in_test_runner_request() -> None:
    module = _load("p2d2b_opid_test")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["operation_id"] = "evil"
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden operation_id key accepted")


def test_build_rejects_extra_unknown_key_in_packaging_request() -> None:
    module = _load("p2d2b_extra_pack")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["unexpected_extra"] = "x"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown extra key accepted")


def test_build_rejects_missing_action_in_packaging_request() -> None:
    module = _load("p2d2b_missing_action")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        del bad["action"]
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing action accepted")


def test_build_rejects_unknown_action_in_packaging_request() -> None:
    module = _load("p2d2b_unknown_action")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["action"] = "fan_in"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown action accepted")


def test_build_rejects_missing_phase_in_test_runner_request() -> None:
    module = _load("p2d2b_missing_phase")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        del bad["phase"]
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing phase accepted")


def test_build_rejects_unknown_phase_in_test_runner_request() -> None:
    module = _load("p2d2b_unknown_phase")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["phase"] = "amber"
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown phase accepted")


def test_build_rejects_action_specific_key_mismatch_packaging() -> None:
    """A copy_assets action must not carry prepare's spec_root_path."""
    module = _load("p2d2b_action_mismatch")
    with _packaging_project("copy_assets") as (proj, run, request):
        bad = dict(request)
        bad["spec_root_path"] = "feature_spec"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("action-specific key mismatch accepted")


def test_build_rejects_phase_specific_key_mismatch_test_runner() -> None:
    """A red phase must not carry retire's retirement_out_path."""
    module = _load("p2d2b_phase_mismatch")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["retirement_out_path"] = "retirement.json"
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("phase-specific key mismatch accepted")


# ---------------------------------------------------------------------------
# 5. Plan schema and step shape for the new operations.
# ---------------------------------------------------------------------------


def test_build_packaging_prepare_returns_canonical_plan_shape() -> None:
    module = _load("p2d2b_pack_shape")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    assert set(plan.keys()) == {
        "kind", "schema_version", "operation_id", "platform_id",
        "profile_id", "request_digest", "steps",
    }, sorted(plan.keys())
    assert plan["kind"] == KIND_PLAN
    assert plan["schema_version"] == SCHEMA_VERSION
    assert plan["operation_id"] == "flutter.packaging.v1"
    assert plan["platform_id"] == PLATFORM_ID
    assert plan["profile_id"] == PROFILE_ID
    assert _is_sha256_hex(plan["request_digest"])
    assert isinstance(plan["steps"], list)
    assert len(plan["steps"]) == 1


def test_build_test_runner_red_returns_canonical_plan_shape() -> None:
    module = _load("p2d2b_test_shape")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    assert set(plan.keys()) == {
        "kind", "schema_version", "operation_id", "platform_id",
        "profile_id", "request_digest", "steps",
    }
    assert plan["operation_id"] == "flutter.test_runner.v1"
    assert len(plan["steps"]) == 1


def test_build_new_step_keys_exact() -> None:
    module = _load("p2d2b_step_keys")
    for op_id, ctx in (
        ("flutter.packaging.v1", _packaging_project("prepare")),
        ("flutter.test_runner.v1", _test_runner_project("red")),
    ):
        with ctx as (proj, run, request):
            plan = module.build(op_id, request)
        for i, step in enumerate(plan["steps"]):
            assert set(step.keys()) == {
                "step_id", "primitive", "primitive_sha256", "argv",
                "cwd", "timeout_seconds",
            }, f"step[{i}] keys: {sorted(step.keys())}"


# ---------------------------------------------------------------------------
# 6. packaging.v1 argv / cwd / timeout / primitive exactness.
# ---------------------------------------------------------------------------


def test_build_packaging_copy_assets_argv_exact() -> None:
    module = _load("p2d2b_pack_copy_argv")
    with _packaging_project("copy_assets") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "copy_assets"
    assert step["primitive"] == "copy_assets.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "copy_assets.py")
    assert argv[2:] == [
        "--manifest", str(run / "asset_manifest.json"),
        "--target", str(proj / "assets" / "canvas"),
    ], argv[2:]


def test_build_packaging_update_pubspec_asset_argv_exact() -> None:
    module = _load("p2d2b_pack_pubspec_argv")
    with _packaging_project("update_pubspec_asset") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "update_pubspec_asset"
    assert step["primitive"] == "update_pubspec_assets.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "update_pubspec_assets.py"
    )
    # --asset value must be the relative POSIX string, not absolute.
    assert argv[2:] == [
        "--pubspec", str(proj / "pubspec.yaml"),
        "--asset", "assets/icons/logo.png",
    ], argv[2:]


def test_build_packaging_prepare_argv_exact() -> None:
    module = _load("p2d2b_pack_prep_argv")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "prepare_assembly_packaging"
    assert step["primitive"] == "prepare_assembly_packaging.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "prepare_assembly_packaging.py"
    )
    assert argv[2:] == [
        "prepare",
        "--spec-root", str(run / "feature_spec"),
        "--project-root", str(proj),
        "--pubspec", str(proj / "pubspec.yaml"),
        "--out", str(run / "packaging_evidence.json"),
    ], argv[2:]


def test_build_packaging_prepare_does_not_emit_font_source() -> None:
    module = _load("p2d2b_pack_prep_nofont")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    argv = plan["steps"][0]["argv"]
    assert "--font-source" not in argv


def test_build_packaging_verify_argv_exact() -> None:
    module = _load("p2d2b_pack_verify_argv")
    with _packaging_project("verify") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "verify_assembly_packaging"
    assert step["primitive"] == "prepare_assembly_packaging.py"
    # Packaging verify binds cwd to the lexical parent of the validated
    # --evidence path (here, run_root).
    assert step["cwd"] == str(run)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "prepare_assembly_packaging.py"
    )
    assert argv[2:] == [
        "verify",
        "--evidence", str(run / "packaging_evidence.json"),
    ], argv[2:]


# ---------------------------------------------------------------------------
# 7. test_runner.v1 argv / cwd / timeout / primitive exactness.
# ---------------------------------------------------------------------------


def test_build_test_runner_red_argv_exact() -> None:
    module = _load("p2d2b_test_red_argv")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "assembly_tdd_red"
    assert step["primitive"] == "assembly_tdd_guard.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_TDD_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "assembly_tdd_guard.py"
    )
    assert argv[2:] == [
        "red",
        "--spec-root", str(run / "feature_spec"),
        "--project-root", str(proj),
        "--test-target", "test/widget/widget_test.dart",
        "--failure-kind", "missing_feature_behavior",
    ], argv[2:]


def test_build_test_runner_green_argv_exact() -> None:
    module = _load("p2d2b_test_green_argv")
    with _test_runner_project("green") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "assembly_tdd_green"
    assert step["primitive"] == "assembly_tdd_guard.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_TDD_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "assembly_tdd_guard.py"
    )
    assert argv[2:] == [
        "green",
        "--spec-root", str(run / "feature_spec"),
        "--project-root", str(proj),
        "--test-target", "test/widget/widget_test.dart",
    ], argv[2:]


def test_build_test_runner_adopt_argv_exact() -> None:
    module = _load("p2d2b_test_adopt_argv")
    with _test_runner_project("adopt") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "assembly_tdd_adopt"
    assert step["primitive"] == "assembly_tdd_guard.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_TDD_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "assembly_tdd_guard.py"
    )
    assert argv[2:] == [
        "adopt",
        "--spec-root", str(run / "feature_spec"),
        "--project-root", str(proj),
        "--test-target", "test/widget/widget_test.dart",
        "--authorization", "preexisting-green",
    ], argv[2:]


def test_build_test_runner_verify_argv_exact() -> None:
    module = _load("p2d2b_test_verify_argv")
    with _test_runner_project("verify") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "verify_assembly_tdd"
    assert step["primitive"] == "assembly_tdd_guard.py"
    # test_runner verify binds cwd to the validated --spec-root path.
    assert step["cwd"] == str(run / "feature_spec")
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "assembly_tdd_guard.py"
    )
    assert argv[2:] == [
        "verify",
        "--spec-root", str(run / "feature_spec"),
    ], argv[2:]


def test_build_test_runner_retire_argv_exact() -> None:
    module = _load("p2d2b_test_retire_argv")
    with _test_runner_project("retire_stale_template_tests") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    step = plan["steps"][0]
    assert step["step_id"] == "retire_stale_template_tests"
    assert step["primitive"] == "retire_stale_flutter_template_tests.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        ICP_ROOT / "vendor" / "iff_v1" / "scripts" / "retire_stale_flutter_template_tests.py"
    )
    assert argv[2:] == [
        "--project-root", str(proj),
        "--out", str(run / "retirement_report.json"),
    ], argv[2:]


def test_build_test_runner_red_does_not_emit_flutter_flag() -> None:
    """No caller-selected Flutter executable surface; --flutter is omitted."""
    module = _load("p2d2b_test_red_noflutter")
    for phase in ("red", "green", "adopt", "verify"):
        with _test_runner_project(phase) as (proj, run, request):
            plan = module.build("flutter.test_runner.v1", request)
        argv = plan["steps"][0]["argv"]
        assert "--flutter" not in argv, f"phase {phase}: --flutter emitted"


def test_build_test_runner_red_fixed_failure_kind_only() -> None:
    """Only 'missing_feature_behavior' is the red failure kind."""
    module = _load("p2d2b_test_red_failure_kind")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--failure-kind")
    assert argv[idx + 1] == "missing_feature_behavior"


def test_build_test_runner_adopt_fixed_authorization_only() -> None:
    """Only 'preexisting-green' is the adopt authorization."""
    module = _load("p2d2b_test_adopt_auth")
    with _test_runner_project("adopt") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--authorization")
    assert argv[idx + 1] == "preexisting-green"


# ---------------------------------------------------------------------------
# 8. Primitive SHA binding to the immutable manifest.
# ---------------------------------------------------------------------------


def _manifest_sha_map() -> dict[str, str]:
    raw = MANIFEST_PATH.read_bytes()
    obj = json.loads(raw)
    return {entry["name"]: entry["sha256"] for entry in obj["scripts"]}


def test_build_packaging_primitives_match_manifest_sha() -> None:
    module = _load("p2d2b_pack_sha")
    sha_map = _manifest_sha_map()
    expectations = {
        "copy_assets": "copy_assets.py",
        "update_pubspec_asset": "update_pubspec_assets.py",
        "prepare": "prepare_assembly_packaging.py",
        "verify": "prepare_assembly_packaging.py",
    }
    for action, primitive in expectations.items():
        with _packaging_project(action) as (proj, run, request):
            plan = module.build("flutter.packaging.v1", request)
        step = plan["steps"][0]
        assert step["primitive"] == primitive
        assert step["primitive_sha256"] == sha_map[primitive], (
            f"action {action}: sha mismatch for {primitive}"
        )


def test_build_test_runner_primitives_match_manifest_sha() -> None:
    module = _load("p2d2b_test_sha")
    sha_map = _manifest_sha_map()
    expectations = {
        "red": "assembly_tdd_guard.py",
        "green": "assembly_tdd_guard.py",
        "adopt": "assembly_tdd_guard.py",
        "verify": "assembly_tdd_guard.py",
        "retire_stale_template_tests": "retire_stale_flutter_template_tests.py",
    }
    for phase, primitive in expectations.items():
        with _test_runner_project(phase) as (proj, run, request):
            plan = module.build("flutter.test_runner.v1", request)
        step = plan["steps"][0]
        assert step["primitive"] == primitive
        assert step["primitive_sha256"] == sha_map[primitive], (
            f"phase {phase}: sha mismatch for {primitive}"
        )


# ---------------------------------------------------------------------------
# 9. Determinism — process / module / cwd / map ordering.
# ---------------------------------------------------------------------------


def test_build_packaging_deterministic_in_process() -> None:
    module = _load("p2d2b_pack_det_proc")
    with _packaging_project("prepare") as (proj, run, request):
        p1 = module.build("flutter.packaging.v1", request)
        p2 = module.build("flutter.packaging.v1", request)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_test_runner_deterministic_in_process() -> None:
    module = _load("p2d2b_test_det_proc")
    with _test_runner_project("red") as (proj, run, request):
        p1 = module.build("flutter.test_runner.v1", request)
        p2 = module.build("flutter.test_runner.v1", request)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_new_ops_deterministic_across_modules() -> None:
    with _packaging_project("prepare") as (proj, run, request):
        m1 = _load("p2d2b_det_mod1")
        m2 = _load("p2d2b_det_mod2")
        p1 = m1.build("flutter.packaging.v1", request)
        p2 = m2.build("flutter.packaging.v1", request)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_new_ops_deterministic_across_cwd() -> None:
    with _test_runner_project("red") as (proj, run, request):
        start_cwd = os.getcwd()
        m = _load("p2d2b_det_cwd")
        try:
            os.chdir(str(proj))
            p1 = m.build("flutter.test_runner.v1", request)
        finally:
            os.chdir(start_cwd)
        try:
            os.chdir(str(run))
            p2 = m.build("flutter.test_runner.v1", request)
        finally:
            os.chdir(start_cwd)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_packaging_deterministic_across_processes() -> None:
    with _packaging_project("prepare") as (proj, run, request):
        request_file = proj.parent / "request.json"
        request_file.write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        helper = proj.parent / "child_build.py"
        helper.write_text(
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('fov1', %r)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "req = json.load(open(%r))\n"
            "plan = m.build(%r, req)\n"
            "sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + chr(10))\n"
            % (str(MODULE_PATH), str(request_file), "flutter.packaging.v1")
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r1 = subprocess.run(
            [sys.executable, str(helper)], capture_output=True, text=True, env=env
        )
        r2 = subprocess.run(
            [sys.executable, str(helper)], capture_output=True, text=True, env=env
        )
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout == r2.stdout


def test_build_test_runner_deterministic_across_processes() -> None:
    with _test_runner_project("red") as (proj, run, request):
        request_file = proj.parent / "request.json"
        request_file.write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        helper = proj.parent / "child_build.py"
        helper.write_text(
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('fov1', %r)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "req = json.load(open(%r))\n"
            "plan = m.build(%r, req)\n"
            "sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + chr(10))\n"
            % (str(MODULE_PATH), str(request_file), "flutter.test_runner.v1")
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r1 = subprocess.run(
            [sys.executable, str(helper)], capture_output=True, text=True, env=env
        )
        r2 = subprocess.run(
            [sys.executable, str(helper)], capture_output=True, text=True, env=env
        )
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout == r2.stdout


# ---------------------------------------------------------------------------
# 10. Request digest changes when values change.
# ---------------------------------------------------------------------------


def test_request_digest_changes_when_action_changes() -> None:
    """Two packaging requests with different actions must produce different
    request digests, even with otherwise identical common fields."""
    module = _load("p2d2b_digest_action")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        # Set up enough for both copy_assets and prepare to validate.
        _setup_packaging_copy_assets(proj, run)
        (run / "feature_spec").mkdir(parents=True, exist_ok=True)
        req_copy = _make_packaging_copy_assets_request(proj, run)
        req_prep = _make_packaging_prepare_request(proj, run)
        p_copy = module.build("flutter.packaging.v1", req_copy)
        p_prep = module.build("flutter.packaging.v1", req_prep)
    assert p_copy["request_digest"] != p_prep["request_digest"]


def test_request_digest_changes_when_phase_changes() -> None:
    module = _load("p2d2b_digest_phase")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_test_runner_red_green_adopt(proj, run)
        req_red = _make_test_runner_red_request(proj, run)
        req_green = _make_test_runner_green_request(proj, run)
        p_red = module.build("flutter.test_runner.v1", req_red)
        p_green = module.build("flutter.test_runner.v1", req_green)
    assert p_red["request_digest"] != p_green["request_digest"]


def test_request_digest_changes_when_test_target_changes() -> None:
    module = _load("p2d2b_digest_target")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True, exist_ok=True)
        (proj / "test" / "widget").mkdir(parents=True, exist_ok=True)
        (proj / "test" / "widget" / "widget_test.dart").write_text("// a\n")
        (proj / "test" / "other_test.dart").write_text("// b\n")
        req_a = _make_test_runner_red_request(proj, run)
        req_b = dict(req_a)
        req_b["test_target"] = "test/other_test.dart"
        p_a = module.build("flutter.test_runner.v1", req_a)
        p_b = module.build("flutter.test_runner.v1", req_b)
    assert p_a["request_digest"] != p_b["request_digest"]


# ---------------------------------------------------------------------------
# 11. Common project_root / run_root / package_name validation.
# ---------------------------------------------------------------------------


def test_build_packaging_rejects_relative_project_root() -> None:
    module = _load("p2d2b_pack_rel_proj")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["project_root"] = "relative/path"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative project_root accepted")


def test_build_test_runner_rejects_nondisjoint_roots() -> None:
    module = _load("p2d2b_test_nondisjoint")
    with _test_runner_project("red") as (proj, run, request):
        bad = dict(request)
        bad["run_root"] = str(proj)
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("nondisjoint roots accepted")


def test_build_test_runner_rejects_nested_run_in_project() -> None:
    module = _load("p2d2b_test_nested")
    with _test_runner_project("red") as (proj, run, request):
        nested = proj / "nested_run"
        nested.mkdir()
        bad = dict(request)
        bad["run_root"] = str(nested)
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("nested run_root accepted")


def test_build_packaging_rejects_invalid_package_name() -> None:
    module = _load("p2d2b_pack_bad_pkg")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["package_name"] = "My-App"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid package_name accepted")


# ---------------------------------------------------------------------------
# 12. packaging path rules.
# ---------------------------------------------------------------------------


def test_build_packaging_copy_assets_rejects_missing_manifest() -> None:
    module = _load("p2d2b_pack_copy_nomani")
    with _packaging_project("copy_assets") as (proj, run, request):
        (run / "asset_manifest.json").unlink()
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing manifest accepted")


def test_build_packaging_copy_assets_rejects_wrong_manifest_extension() -> None:
    module = _load("p2d2b_pack_copy_badmanext")
    with _packaging_project("copy_assets") as (proj, run, request):
        bad = dict(request)
        bad["asset_manifest_path"] = "asset_manifest.txt"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong manifest extension accepted")


def test_build_packaging_copy_assets_rejects_existing_target_regular_file() -> None:
    module = _load("p2d2b_pack_copy_targetfile")
    with _packaging_project("copy_assets") as (proj, run, request):
        (proj / "assets" / "canvas").mkdir()
        (proj / "assets" / "canvas" / "stale.txt").write_text("x")
        # Target the existing file directly.
        bad = dict(request)
        bad["asset_target_path"] = "assets/canvas/stale.txt"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("existing regular file target accepted")


def test_build_packaging_copy_assets_accepts_existing_target_dir() -> None:
    module = _load("p2d2b_pack_copy_targetdir")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_packaging_copy_assets(proj, run)
        (proj / "assets" / "canvas").mkdir(parents=True)
        request = _make_packaging_copy_assets_request(proj, run)
        plan = module.build("flutter.packaging.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_packaging_copy_assets_accepts_absent_target_with_safe_ancestors() -> None:
    module = _load("p2d2b_pack_copy_targetabsent")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_packaging_copy_assets(proj, run)
        # assets/ exists; assets/new_dir/ does not.
        request = _make_packaging_copy_assets_request(proj, run)
        request["asset_target_path"] = "assets/new_dir"
        plan = module.build("flutter.packaging.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_packaging_copy_assets_rejects_target_symlinked_component() -> None:
    module = _load("p2d2b_pack_copy_targetsym")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_packaging_copy_assets(proj, run)
        real_dir = tmp / "real_assets"
        real_dir.mkdir()
        os.symlink(real_dir, proj / "assets" / "symdir")
        request = _make_packaging_copy_assets_request(proj, run)
        request["asset_target_path"] = "assets/symdir/sub"
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked target component accepted")


def test_build_packaging_copy_assets_rejects_target_dotdot() -> None:
    module = _load("p2d2b_pack_copy_targetdd")
    with _packaging_project("copy_assets") as (proj, run, request):
        bad = dict(request)
        bad["asset_target_path"] = "../escape"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("dotdot target accepted")


# ---------------------------------------------------------------------------
# 13. packaging update_pubspec_asset asset_path rules.
# ---------------------------------------------------------------------------


def test_build_packaging_update_pubspec_asset_rejects_non_assets_path() -> None:
    module = _load("p2d2b_pack_pubspec_nonasset")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "lib").mkdir()
        (proj / "lib" / "x.dart").write_text("//", encoding="utf-8")
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        request["asset_path"] = "lib/x.dart"
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-assets/ asset_path accepted")


def test_build_packaging_update_pubspec_asset_rejects_assets_prefix_lookalike() -> None:
    """``assets_evil/x.png`` must NOT be accepted as an assets/ path."""
    module = _load("p2d2b_pack_pubspec_lookalike")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "assets_evil").mkdir()
        (proj / "assets_evil" / "x.png").write_bytes(b"\x89PNG")
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        request["asset_path"] = "assets_evil/x.png"
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("assets_evil/ prefix lookalike accepted")


def test_build_packaging_update_pubspec_asset_rejects_assets_itself() -> None:
    """``assets`` itself is not strictly below assets/."""
    module = _load("p2d2b_pack_pubspec_assets_eq")
    with _packaging_project("update_pubspec_asset") as (proj, run, request):
        bad = dict(request)
        bad["asset_path"] = "assets"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("asset_path == 'assets' accepted")


def test_build_packaging_update_pubspec_asset_rejects_pubspec_yaml() -> None:
    module = _load("p2d2b_pack_pubspec_pubyml")
    with _packaging_project("update_pubspec_asset") as (proj, run, request):
        bad = dict(request)
        bad["asset_path"] = "pubspec.yaml"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("pubspec.yaml as asset_path accepted")


def test_build_packaging_update_pubspec_asset_rejects_missing_pubspec() -> None:
    module = _load("p2d2b_pack_pubspec_nopsyml")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "pubspec.yaml").unlink()
        _setup_packaging_update_pubspec_asset(proj, run)
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing pubspec accepted")


def test_build_packaging_update_pubspec_asset_rejects_symlinked_pubspec() -> None:
    module = _load("p2d2b_pack_pubspec_sympsyml")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "pubspec.yaml").unlink()
        outside = tmp / "real_pubspec.yaml"
        outside.write_text("name: x\n", encoding="utf-8")
        os.symlink(outside, proj / "pubspec.yaml")
        _setup_packaging_update_pubspec_asset(proj, run)
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked pubspec accepted")


def test_build_packaging_update_pubspec_asset_accepts_existing_dir_target() -> None:
    module = _load("p2d2b_pack_pubspec_dirasset")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "assets" / "icons").mkdir(parents=True)
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        request["asset_path"] = "assets/icons"
        plan = module.build("flutter.packaging.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--asset")
    assert argv[idx + 1] == "assets/icons"


def test_build_packaging_update_pubspec_asset_rejects_symlinked_asset() -> None:
    module = _load("p2d2b_pack_pubspec_symasset")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (proj / "assets").mkdir(parents=True)
        outside = tmp / "outside.png"
        outside.write_bytes(b"\x89PNG")
        os.symlink(outside, proj / "assets" / "logo.png")
        request = _make_packaging_update_pubspec_asset_request(proj, run)
        request["asset_path"] = "assets/logo.png"
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked asset accepted")


# ---------------------------------------------------------------------------
# 14. packaging prepare/verify path rules.
# ---------------------------------------------------------------------------


def test_build_packaging_prepare_rejects_missing_spec_root() -> None:
    module = _load("p2d2b_pack_prep_nospec")
    with _packaging_project("prepare") as (proj, run, request):
        (run / "feature_spec").rmdir()
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing spec_root accepted")


def test_build_packaging_prepare_rejects_spec_root_file() -> None:
    module = _load("p2d2b_pack_prep_specfile")
    with _packaging_project("prepare") as (proj, run, request):
        (run / "feature_spec").rmdir()
        (run / "feature_spec").write_text("x")
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("spec_root file accepted")


def test_build_packaging_prepare_rejects_out_wrong_extension() -> None:
    module = _load("p2d2b_pack_prep_outext")
    with _packaging_project("prepare") as (proj, run, request):
        bad = dict(request)
        bad["packaging_out_path"] = "packaging.txt"
        try:
            module.build("flutter.packaging.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong out extension accepted")


def test_build_packaging_verify_rejects_missing_evidence() -> None:
    module = _load("p2d2b_pack_verify_noev")
    with _packaging_project("verify") as (proj, run, request):
        (run / "packaging_evidence.json").unlink()
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing evidence accepted")


def test_build_packaging_verify_rejects_evidence_directory() -> None:
    module = _load("p2d2b_pack_verify_evdir")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "packaging_evidence.json").mkdir()
        request = _make_packaging_verify_request(proj, run)
        try:
            module.build("flutter.packaging.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("directory evidence accepted")


# ---------------------------------------------------------------------------
# 15. test_runner test_target rules.
# ---------------------------------------------------------------------------


def test_build_test_runner_rejects_non_test_target() -> None:
    module = _load("p2d2b_test_non_test_target")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True)
        (proj / "lib").mkdir()
        (proj / "lib" / "x.dart").write_text("//", encoding="utf-8")
        request = _make_test_runner_red_request(proj, run)
        request["test_target"] = "lib/x.dart"
        try:
            module.build("flutter.test_runner.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-test/ target accepted")


def test_build_test_runner_rejects_test_target_equal_test() -> None:
    module = _load("p2d2b_test_target_eq_test")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True)
        (proj / "test").mkdir()
        request = _make_test_runner_red_request(proj, run)
        request["test_target"] = "test"
        try:
            module.build("flutter.test_runner.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("'test' target accepted")


def test_build_test_runner_rejects_test_prefix_lookalike() -> None:
    """``test_evil/x.dart`` must NOT be accepted as a test/ target."""
    module = _load("p2d2b_test_lookalike")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True)
        (proj / "test_evil").mkdir()
        (proj / "test_evil" / "x.dart").write_text("//", encoding="utf-8")
        request = _make_test_runner_red_request(proj, run)
        request["test_target"] = "test_evil/x.dart"
        try:
            module.build("flutter.test_runner.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("test_evil/ prefix lookalike accepted")


def test_build_test_runner_rejects_missing_test_target() -> None:
    module = _load("p2d2b_test_missing_target")
    with _test_runner_project("red") as (proj, run, request):
        (proj / "test" / "widget" / "widget_test.dart").unlink()
        try:
            module.build("flutter.test_runner.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing test_target accepted")


def test_build_test_runner_accepts_test_target_directory() -> None:
    module = _load("p2d2b_test_target_dir")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True)
        (proj / "test" / "widget").mkdir(parents=True)
        request = _make_test_runner_red_request(proj, run)
        request["test_target"] = "test/widget"
        plan = module.build("flutter.test_runner.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--test-target")
    assert argv[idx + 1] == "test/widget"


def test_build_test_runner_rejects_symlinked_test_target() -> None:
    module = _load("p2d2b_test_sym_target")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        (run / "feature_spec").mkdir(parents=True)
        (proj / "test").mkdir()
        outside = tmp / "outside.dart"
        outside.write_text("//", encoding="utf-8")
        os.symlink(outside, proj / "test" / "fake_test.dart")
        request = _make_test_runner_red_request(proj, run)
        request["test_target"] = "test/fake_test.dart"
        try:
            module.build("flutter.test_runner.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked test_target accepted")


def test_build_test_runner_retire_rejects_out_wrong_extension() -> None:
    module = _load("p2d2b_test_retire_outext")
    with _test_runner_project("retire_stale_template_tests") as (proj, run, request):
        bad = dict(request)
        bad["retirement_out_path"] = "report.txt"
        try:
            module.build("flutter.test_runner.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong retire out extension accepted")


# ---------------------------------------------------------------------------
# 16. verify_plan report shape.
# ---------------------------------------------------------------------------


def test_verify_plan_returns_canonical_report_shape_packaging() -> None:
    module = _load("p2d2b_vp_shape_pack")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        report = module.verify_plan(plan)
    assert set(report.keys()) == {
        "ok", "kind", "schema_version", "operation_id",
        "steps_total", "plan_digest",
    }, sorted(report.keys())
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["operation_id"] == "flutter.packaging.v1"
    assert report["steps_total"] == 1
    assert _is_sha256_hex(report["plan_digest"])


def test_verify_plan_returns_canonical_report_shape_test_runner() -> None:
    module = _load("p2d2b_vp_shape_test")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.test_runner.v1"
    assert report["steps_total"] == 1


def test_verify_plan_digest_matches_canonical_plan_bytes() -> None:
    module = _load("p2d2b_vp_digest")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        report = module.verify_plan(plan)
        expected = hashlib.sha256(_canonical_json(plan)).hexdigest()
    assert report["plan_digest"] == expected


def test_verify_plan_happy_path_all_nine_variants() -> None:
    module = _load("p2d2b_vp_happy")
    for action in PACKAGING_ACTIONS:
        with _packaging_project(action) as (proj, run, request):
            plan = module.build("flutter.packaging.v1", request)
            report = module.verify_plan(plan)
        assert report["ok"] is True, f"packaging action {action} failed verify"
        assert report["steps_total"] == 1
    for phase in TEST_RUNNER_PHASES:
        with _test_runner_project(phase) as (proj, run, request):
            plan = module.build("flutter.test_runner.v1", request)
            report = module.verify_plan(plan)
        assert report["ok"] is True, f"test_runner phase {phase} failed verify"
        assert report["steps_total"] == 1


def test_verify_plan_deterministic_in_process() -> None:
    module = _load("p2d2b_vp_det")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        r1 = module.verify_plan(plan)
        r2 = module.verify_plan(plan)
    assert _canonical_json(r1) == _canonical_json(r2)


# ---------------------------------------------------------------------------
# 17. verify_plan rejects tampered plans (variant inference + tamper paths).
# ---------------------------------------------------------------------------


def _tamper(plan: dict, mutation) -> dict:
    new_plan = copy.deepcopy(plan)
    mutation(new_plan)
    return new_plan


def test_verify_plan_rejects_two_step_packaging_plan() -> None:
    module = _load("p2d2b_vp_two_step")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("steps", [p["steps"][0], p["steps"][0]]))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("two-step packaging plan accepted")


def test_verify_plan_rejects_zero_step_test_runner_plan() -> None:
    module = _load("p2d2b_vp_zero_step")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("steps", []))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("zero-step plan accepted")


def test_verify_plan_rejects_unknown_step_id_in_packaging() -> None:
    module = _load("p2d2b_vp_unknown_sid")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = _tamper(
            plan, lambda p: p["steps"][0].__setitem__("step_id", "evil_step")
        )
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown step_id accepted")


def test_verify_plan_rejects_cross_variant_step_swap_packaging_to_test_runner() -> None:
    """A packaging operation_id must not carry a test_runner step_id."""
    module = _load("p2d2b_vp_xvariant_pack_test")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = _tamper(
            plan, lambda p: p["steps"][0].__setitem__("step_id", "assembly_tdd_red")
        )
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-variant step swap (packaging -> test_runner) accepted")


def test_verify_plan_rejects_cross_variant_step_swap_test_runner_to_packaging() -> None:
    module = _load("p2d2b_vp_xvariant_test_pack")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = _tamper(
            plan, lambda p: p["steps"][0].__setitem__("step_id", "copy_assets")
        )
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-variant step swap (test_runner -> packaging) accepted")


def test_verify_plan_rejects_cross_action_step_id_in_packaging() -> None:
    """A copy_assets plan must not declare step_id=prepare_assembly_packaging."""
    module = _load("p2d2b_vp_xaction")
    with _packaging_project("copy_assets") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        # Build a "prepare-style" step but keep copy_assets argv. The
        # step_id swap alone must be detected because the primitive and
        # argv no longer match the declared variant.
        bad["steps"][0]["step_id"] = "prepare_assembly_packaging"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-action step_id accepted")


def test_verify_plan_rejects_cross_phase_step_id_in_test_runner() -> None:
    module = _load("p2d2b_vp_xphase")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["step_id"] = "assembly_tdd_green"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-phase step_id accepted")


def test_verify_plan_rejects_primitive_reuse_outside_owned_variants() -> None:
    """copy_assets.py is owned only by copy_assets; using it for
    prepare_assembly_packaging must fail."""
    module = _load("p2d2b_vp_prim_misuse")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        sha_map = _manifest_sha_map()
        bad["steps"][0]["primitive"] = "copy_assets.py"
        bad["steps"][0]["primitive_sha256"] = sha_map["copy_assets.py"]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("primitive misuse accepted")


def test_verify_plan_rejects_tampered_step_id_packaging() -> None:
    module = _load("p2d2b_vp_tamper_sid")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["step_id"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered step_id accepted")


def test_verify_plan_rejects_tampered_primitive_sha_packaging() -> None:
    module = _load("p2d2b_vp_tamper_psha")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["primitive_sha256"] = "a" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered primitive_sha256 accepted")


def test_verify_plan_rejects_tampered_interpreter_test_runner() -> None:
    module = _load("p2d2b_vp_tamper_interp")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][0] = "/bin/sh"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered interpreter accepted")


def test_verify_plan_rejects_tampered_script_packaging() -> None:
    module = _load("p2d2b_vp_tamper_script")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][1] = "/tmp/evil.py"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered script accepted")


def test_verify_plan_rejects_tampered_cwd_packaging() -> None:
    module = _load("p2d2b_vp_tamper_cwd")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = "/etc"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered cwd accepted")


# ---------------------------------------------------------------------------
# 17b. cwd-binding rules for the new variants.
#
# Every variant must have a deterministic cwd relationship that
# verify_plan re-proves from the plan itself. The cwd_binding enum is:
#   - "project_root_or_descendant": cwd == project_root, and at least
#     one validated absolute argv path equals cwd OR is a strict
#     descendant. Covers P2d2a + project-bound P2d2b variants.
#   - "evidence_parent": packaging verify. cwd == Path(evidence).parent.
#   - "spec_root": test_runner verify. cwd == Path(spec_root).
# ---------------------------------------------------------------------------


def test_verify_plan_accepts_equal_to_cwd_project_root_red() -> None:
    """For red/green/adopt the only project-rooted argv value is
    --project-root <cwd> itself; equality must satisfy the cwd anchor."""
    module = _load("p2d2b_vp_cwd_eq_red")
    for phase in ("red", "green", "adopt"):
        with _test_runner_project(phase) as (proj, run, request):
            plan = module.build("flutter.test_runner.v1", request)
            report = module.verify_plan(plan)
        assert report["ok"] is True, f"phase {phase}: cwd equality rejected"


def test_verify_plan_accepts_equal_to_cwd_project_root_retire() -> None:
    module = _load("p2d2b_vp_cwd_eq_retire")
    with _test_runner_project("retire_stale_template_tests") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True


def test_verify_plan_accepts_descendant_for_p2d2a_visible() -> None:
    """P2d2a visible_codegen emits project-output .dart paths that are
    strict descendants of cwd; this must continue to pass."""
    module = _load("p2d2b_vp_cwd_desc_vis")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        _write_json(run / "render_plan.json", {})
        _write_json(run / "scene.json", {})
        _write_json(run / "classification.json", {})
        _write_json(run / "component_manifest.json", {})
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "feature_id": "fancy_widget",
            "render_plan": "render_plan.json",
            "scene": "scene.json",
            "classification": "classification.json",
            "component_manifest": "component_manifest.json",
            "canvas_out": "lib/canvas/canvas.dart",
            "colors_out": "lib/canvas/colors.dart",
            "colors_import_path": "lib/canvas/colors.dart",
            "implementation_map_out": "implementation_map.json",
            "status_bar_out": "lib/status/status_bar.dart",
            "canvas_class_name": "CanvasWidget",
            "status_bar_class_name": "StatusBarWidget",
        }
        plan = module.build("flutter.visible_codegen.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True


def test_verify_plan_packaging_verify_cwd_equals_evidence_parent() -> None:
    """packaging verify must emit cwd exactly equal to evidence parent."""
    module = _load("p2d2b_vp_pack_verify_cwd")
    with _packaging_project("verify") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        assert plan["steps"][0]["cwd"] == str(run)
        report = module.verify_plan(plan)
    assert report["ok"] is True


def test_verify_plan_packaging_verify_rejects_cwd_set_to_project_root() -> None:
    """A tampered cwd that points to another existing real directory
    (here, project_root) must be rejected by verify_plan."""
    module = _load("p2d2b_vp_pack_verify_cwd_projroot")
    with _packaging_project("verify") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(proj)  # another existing real dir
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("packaging verify cwd=project_root accepted")


def test_verify_plan_packaging_verify_rejects_cwd_set_to_arbitrary_real_dir() -> None:
    module = _load("p2d2b_vp_pack_verify_cwd_arb")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_packaging_verify(proj, run)
        request = _make_packaging_verify_request(proj, run)
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        # An existing real directory that is neither the evidence parent
        # nor project_root.
        other_dir = tmp / "other_real_dir"
        other_dir.mkdir()
        bad["steps"][0]["cwd"] = str(other_dir)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("packaging verify cwd=arbitrary real dir accepted")


def test_verify_plan_test_runner_verify_cwd_equals_spec_root() -> None:
    """test_runner verify must emit cwd exactly equal to spec_root."""
    module = _load("p2d2b_vp_test_verify_cwd")
    with _test_runner_project("verify") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        assert plan["steps"][0]["cwd"] == str(run / "feature_spec")
        report = module.verify_plan(plan)
    assert report["ok"] is True


def test_verify_plan_test_runner_verify_rejects_cwd_set_to_project_root() -> None:
    module = _load("p2d2b_vp_test_verify_cwd_projroot")
    with _test_runner_project("verify") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(proj)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("test_runner verify cwd=project_root accepted")


def test_verify_plan_test_runner_verify_rejects_cwd_set_to_arbitrary_real_dir() -> None:
    module = _load("p2d2b_vp_test_verify_cwd_arb")
    with _canonical_tempdir() as tmp:
        proj, run = _new_project_run(tmp)
        _setup_test_runner_verify(proj, run)
        request = _make_test_runner_verify_request(proj, run)
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        other_dir = tmp / "other_real_dir"
        other_dir.mkdir()
        bad["steps"][0]["cwd"] = str(other_dir)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("test_runner verify cwd=arbitrary real dir accepted")


def test_verify_plan_no_variant_bypasses_cwd_validation() -> None:
    """Sanity: every variant's plan, when its cwd is tampered to a
    directory unrelated to any argv path, must fail verification. This
    proves no variant silently skips cwd validation."""
    module = _load("p2d2b_vp_no_bypass")
    unrelated_dir = "/var/run"
    # packaging actions
    for action in PACKAGING_ACTIONS:
        with _packaging_project(action) as (proj, run, request):
            plan = module.build("flutter.packaging.v1", request)
            bad = copy.deepcopy(plan)
            bad["steps"][0]["cwd"] = unrelated_dir
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError(
                    f"packaging action {action}: cwd bypass accepted"
                )
    # test_runner phases
    for phase in TEST_RUNNER_PHASES:
        with _test_runner_project(phase) as (proj, run, request):
            plan = module.build("flutter.test_runner.v1", request)
            bad = copy.deepcopy(plan)
            bad["steps"][0]["cwd"] = unrelated_dir
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError(
                    f"test_runner phase {phase}: cwd bypass accepted"
                )


def test_verify_plan_rejects_tampered_timeout_test_runner_red() -> None:
    module = _load("p2d2b_vp_tamper_timeout")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["timeout_seconds"] = TIMEOUT_SECONDS  # wrong: red needs 600
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered timeout accepted")


def test_verify_plan_rejects_tampered_timeout_test_runner_verify() -> None:
    """verify phase uses 120, not 600."""
    module = _load("p2d2b_vp_tamper_timeout_verify")
    with _test_runner_project("verify") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["timeout_seconds"] = TIMEOUT_TDD_SECONDS
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("verify phase tampered timeout accepted")


def test_verify_plan_rejects_extra_argv_flag_in_test_runner_red() -> None:
    module = _load("p2d2b_vp_extra_argv")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"].extend(["--flutter", "/usr/local/bin/flutter"])
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("extra --flutter argv accepted")


def test_verify_plan_rejects_extra_argv_flag_in_packaging_prepare() -> None:
    module = _load("p2d2b_vp_extra_argv_pack")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"].extend(["--font-source", "/tmp/evil.ttf"])
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("extra --font-source argv accepted")


def test_verify_plan_rejects_omitted_argv_flag_in_test_runner_red() -> None:
    module = _load("p2d2b_vp_omit_argv")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        # Drop --failure-kind and its value.
        idx = bad["steps"][0]["argv"].index("--failure-kind")
        del bad["steps"][0]["argv"][idx:idx + 2]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("omitted --failure-kind accepted")


def test_verify_plan_rejects_tampered_failure_kind_in_argv() -> None:
    module = _load("p2d2b_vp_tamper_fk")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--failure-kind")
        bad["steps"][0]["argv"][idx + 1] = "wrong_kind"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered failure-kind accepted")


def test_verify_plan_rejects_tampered_authorization_in_argv() -> None:
    module = _load("p2d2b_vp_tamper_auth")
    with _test_runner_project("adopt") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--authorization")
        bad["steps"][0]["argv"][idx + 1] = "wrong"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered authorization accepted")


def test_verify_plan_rejects_tampered_positional_in_argv() -> None:
    module = _load("p2d2b_vp_tamper_pos")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][2] = "green"  # was "red"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered positional accepted")


def test_verify_plan_rejects_relative_asset_in_argv() -> None:
    """verify_plan independently rejects a tampered --asset that escapes
    the assets/ subtree."""
    module = _load("p2d2b_vp_rel_asset")
    with _packaging_project("update_pubspec_asset") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--asset")
        bad["steps"][0]["argv"][idx + 1] = "lib/x.dart"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative non-assets --asset accepted")


def test_verify_plan_rejects_relative_test_target_in_argv() -> None:
    module = _load("p2d2b_vp_rel_tt")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--test-target")
        bad["steps"][0]["argv"][idx + 1] = "lib/x.dart"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative non-test/ --test-target accepted")


def test_verify_plan_rejects_absolute_asset_in_argv() -> None:
    module = _load("p2d2b_vp_abs_asset")
    with _packaging_project("update_pubspec_asset") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--asset")
        bad["steps"][0]["argv"][idx + 1] = str(proj / "assets" / "icons" / "logo.png")
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("absolute --asset accepted")


def test_verify_plan_rejects_absolute_test_target_in_argv() -> None:
    module = _load("p2d2b_vp_abs_tt")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--test-target")
        bad["steps"][0]["argv"][idx + 1] = str(proj / "test" / "widget" / "widget_test.dart")
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("absolute --test-target accepted")


def test_verify_plan_rejects_added_command_field_in_step() -> None:
    module = _load("p2d2b_vp_cmd_field")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["command"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added command field accepted")


def test_verify_plan_rejects_added_top_level_action_field() -> None:
    module = _load("p2d2b_vp_top_action")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)
        bad = copy.deepcopy(plan)
        bad["action"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added top-level action field accepted")


# ---------------------------------------------------------------------------
# 18. Forbidden keys / generic-exception redaction.
# ---------------------------------------------------------------------------


def test_build_redacts_generic_exception_in_test_runner() -> None:
    module = _load("p2d2b_redact_test")

    def _boom(*args, **kwargs):
        raise OSError("SUPER_SECRET_OSERROR_TEST")

    module._validate_root_path = _boom
    try:
        with _test_runner_project("red") as (proj, run, request):
            try:
                module.build("flutter.test_runner.v1", request)
            except module.OperationPlanError as exc:
                msg = str(exc)
                assert "SUPER_SECRET_OSERROR_TEST" not in msg
            else:
                raise AssertionError("generic OSError swallowed")
    finally:
        del module._validate_root_path


def test_verify_plan_redacts_generic_exception_packaging() -> None:
    module = _load("p2d2b_redact_vp_pack")
    with _packaging_project("prepare") as (proj, run, request):
        plan = module.build("flutter.packaging.v1", request)

    def _boom(*args, **kwargs):
        raise OSError("SUPER_SECRET_VERIFY_PACK")

    module._manifest_sha_map = _boom
    try:
        try:
            module.verify_plan(plan)
        except module.OperationPlanError as exc:
            msg = str(exc)
            assert "SUPER_SECRET_VERIFY_PACK" not in msg
        else:
            raise AssertionError("generic exception swallowed in verify_plan")
    finally:
        del module._manifest_sha_map


def test_build_calls_verify_plan_internally() -> None:
    module = _load("p2d2b_internal_verify")
    called = {"count": 0}
    original = module.verify_plan

    def _tracking(plan):
        called["count"] += 1
        return original(plan)

    module.verify_plan = _tracking
    try:
        with _test_runner_project("red") as (proj, run, request):
            module.build("flutter.test_runner.v1", request)
    finally:
        module.verify_plan = original
    assert called["count"] >= 1


def test_build_fails_if_internal_verify_fails() -> None:
    module = _load("p2d2b_internal_fail")

    def _boom(plan):
        raise module.OperationPlanError("internal verify boom p2d2b")

    module.verify_plan = _boom
    try:
        with _packaging_project("prepare") as (proj, run, request):
            try:
                module.build("flutter.packaging.v1", request)
            except module.OperationPlanError as exc:
                assert "internal verify boom p2d2b" in str(exc)
            else:
                raise AssertionError("build swallowed internal verify failure")
    finally:
        del module.verify_plan


# ---------------------------------------------------------------------------
# 19. No subprocess / shell / CLI / stdlib-only / no iff.
# ---------------------------------------------------------------------------


def test_module_does_not_import_subprocess() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess", "module imports subprocess"
                assert not alias.name.startswith("subprocess."), "module imports subprocess"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert node.module != "subprocess", "module imports from subprocess"
            assert not node.module.startswith("subprocess."), "module imports from subprocess"


def test_module_source_has_no_shell_true() -> None:
    source = MODULE_PATH.read_text()
    assert "shell=True" not in source
    assert "shell = True" not in source


def test_module_uses_only_standard_library_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    allowed_prefixes = (
        "argparse", "hashlib", "importlib", "json", "os", "re",
        "stat", "sys", "pathlib", "typing", "__future__",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed_prefixes, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            top = node.module.split(".")[0]
            assert top in allowed_prefixes, f"non-stdlib from-import: {node.module}"


def test_module_does_not_import_sibling_iff() -> None:
    source = MODULE_PATH.read_text()
    assert "import iff" not in source
    assert "from iff " not in source
    assert "from iff." not in source
    for needle in ('Path("iff")', "iff/scripts/", "iff_root"):
        assert needle not in source, f"forbidden reference: {needle}"


def test_build_does_not_read_iff_at_runtime() -> None:
    module = _load("p2d2b_noreadiff")
    iff_path = REPO_ROOT / "iff"
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
    assert str(iff_path) not in json.dumps(plan)


# ---------------------------------------------------------------------------
# 20. No writes during build / verify.
# ---------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[Path, bytes]:
    snap: dict[Path, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.is_symlink():
            snap[p] = b"<symlink>"
        else:
            snap[p] = p.read_bytes()
    return snap


def test_build_does_not_mutate_project_or_run() -> None:
    module = _load("p2d2b_nowrite_build")
    with _packaging_project("prepare") as (proj, run, request):
        before_proj = _snapshot(proj)
        before_run = _snapshot(run)
        module.build("flutter.packaging.v1", request)
        after_proj = _snapshot(proj)
        after_run = _snapshot(run)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_run.keys()) == set(after_run.keys())
    for p, data in before_run.items():
        assert after_run[p] == data, f"run mutated: {p}"


def test_verify_plan_does_not_mutate_project_or_run() -> None:
    module = _load("p2d2b_nowrite_verify")
    with _test_runner_project("red") as (proj, run, request):
        plan = module.build("flutter.test_runner.v1", request)
        before_proj = _snapshot(proj)
        before_run = _snapshot(run)
        module.verify_plan(plan)
        after_proj = _snapshot(proj)
        after_run = _snapshot(run)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_run.keys()) == set(after_run.keys())
    for p, data in before_run.items():
        assert after_run[p] == data, f"run mutated: {p}"


def test_build_does_not_mutate_capsule() -> None:
    module = _load("p2d2b_nowrite_capsule")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    before = _snapshot(capsule_dir)
    with _packaging_project("prepare") as (proj, run, request):
        module.build("flutter.packaging.v1", request)
    after = _snapshot(capsule_dir)
    assert set(before.keys()) == set(after.keys())
    for p, data in before.items():
        assert after[p] == data, f"capsule mutated: {p}"


def test_build_does_not_create_pycache_in_project() -> None:
    module = _load("p2d2b_nopyc")
    with _test_runner_project("red") as (proj, run, request):
        module.build("flutter.test_runner.v1", request)
        pyc_dirs = [p for p in proj.rglob("__pycache__") if p.is_dir()]
    assert pyc_dirs == [], pyc_dirs


# ---------------------------------------------------------------------------
# 21. Registry / P2c descriptor / baselines / capsule unchanged.
# ---------------------------------------------------------------------------


def test_build_does_not_edit_registry() -> None:
    module = _load("p2d2b_noedit_reg")
    before = REGISTRY_PATH.read_bytes()
    with _packaging_project("prepare") as (proj, run, request):
        module.build("flutter.packaging.v1", request)
    after = REGISTRY_PATH.read_bytes()
    assert before == after, "registries.json was mutated"


def test_build_does_not_edit_p2c_descriptor() -> None:
    module = _load("p2d2b_noedit_desc")
    before = P2C_DESCRIPTOR_PATH.read_bytes()
    with _test_runner_project("red") as (proj, run, request):
        module.build("flutter.test_runner.v1", request)
    after = P2C_DESCRIPTOR_PATH.read_bytes()
    assert before == after, "P2c descriptor was mutated"


def test_build_does_not_touch_pycache_in_capsule() -> None:
    module = _load("p2d2b_nocapsule_pyc")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    pyc_before = list(capsule_dir.rglob("__pycache__"))
    with _packaging_project("prepare") as (proj, run, request):
        module.build("flutter.packaging.v1", request)
    pyc_after = list(capsule_dir.rglob("__pycache__"))
    assert pyc_before == pyc_after


def test_build_does_not_mutate_baseline_manifest() -> None:
    module = _load("p2d2b_noedit_baseline")
    baseline_path = ICP_ROOT / "references" / "baselines" / "iff-v1.json"
    if baseline_path.is_file():
        before = baseline_path.read_bytes()
        with _packaging_project("prepare") as (proj, run, request):
            module.build("flutter.packaging.v1", request)
        after = baseline_path.read_bytes()
        assert before == after, "iff-v1.json baseline was mutated"


def test_build_does_not_mutate_vendor_manifest() -> None:
    module = _load("p2d2b_noedit_vendor")
    before = MANIFEST_PATH.read_bytes()
    with _test_runner_project("red") as (proj, run, request):
        module.build("flutter.test_runner.v1", request)
    after = MANIFEST_PATH.read_bytes()
    assert before == after, "iff-v1-vendor.json was mutated"


# ---------------------------------------------------------------------------
# 22. Manifest duplicate-key rejection (regression guard).
# ---------------------------------------------------------------------------


def test_module_loads_manifest_with_duplicate_key_rejection() -> None:
    source = MODULE_PATH.read_text()
    assert "object_pairs_hook" in source or "_reject_duplicate_keys" in source


# ---------------------------------------------------------------------------
# 23. P2d2a operations still work — append-only registry guard.
# ---------------------------------------------------------------------------


def test_p2d2a_operations_still_pass_verification() -> None:
    """Sanity: the three P2d2a operations must continue to verify."""
    module = _load("p2d2b_append_guard")
    # Build a minimal visible_codegen plan inline.
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        _write_json(run / "render_plan.json", {})
        _write_json(run / "scene.json", {})
        _write_json(run / "classification.json", {})
        _write_json(run / "component_manifest.json", {})
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "feature_id": "fancy_widget",
            "render_plan": "render_plan.json",
            "scene": "scene.json",
            "classification": "classification.json",
            "component_manifest": "component_manifest.json",
            "canvas_out": "lib/canvas/canvas.dart",
            "colors_out": "lib/canvas/colors.dart",
            "colors_import_path": "lib/canvas/colors.dart",
            "implementation_map_out": "implementation_map.json",
            "status_bar_out": "lib/status/status_bar.dart",
            "canvas_class_name": "CanvasWidget",
            "status_bar_class_name": "StatusBarWidget",
        }
        plan = module.build("flutter.visible_codegen.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.visible_codegen.v1"


# ---------------------------------------------------------------------------
# Selftest runner.
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [name for name in globals() if name.startswith("test_")]
    failures = 0
    for name in sorted(tests):
        try:
            globals()[name]()
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
