#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2d2a Flutter
trusted-operation plan registry (visible/fixture/trace).

Covers the public Python API of ``platforms/flutter_operations_v1.py``:

1. ``list_operation_ids() -> tuple[str, ...]`` returns exactly the three
   legacy-backed Flutter argv operation IDs in the fixed order.
2. ``build(operation_id, request) -> dict`` verifies the installed P2a
   capsule first, strict-loads the fixed vendor manifest with duplicate-
   key rejection, validates the exact request schema, builds a canonical
   plan of kind ``icp.trusted-operation-plan.v1``, calls ``verify_plan``
   on it, and returns the plan.
3. ``verify_plan(plan) -> dict`` independently re-verifies the capsule/
   manifest binding, the plan structure, step order, primitive SHA,
   fixed interpreter/script/cwd/timeout, and argv value validators, and
   returns a report of kind ``icp.trusted-operation-plan-verify.v1``.

No CLI is exposed. No subprocess is executed. The module never imports
or reads sibling ``iff/``, never edits the registry or P2c descriptor,
and never writes to the project/run/capsule trees.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2a_flutter_operations.py
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
import re
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
def _canonical_tempdir(prefix: str = "p2d2a_"):
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


def _make_visible_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
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


def _setup_visible_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "canvas").mkdir(parents=True, exist_ok=True)
    (project_root / "lib" / "status").mkdir(parents=True, exist_ok=True)
    _write_json(run_root / "render_plan.json", {"nodes": []})
    _write_json(run_root / "scene.json", {"scene": []})
    _write_json(run_root / "classification.json", {"dims": {}})
    _write_json(run_root / "component_manifest.json", {"components": []})


def _make_fixture_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    # P2.5b: fixture_codegen now requires a ``projections`` map whose
    # state-id set equals ``slots``. Each value is a relative existing
    # ``.json`` path under run_root.
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "feature_id": "fancy_widget",
        "slots": {
            "loading": "slot_loading.json",
            "ready": "slot_ready.json",
            "error": "slot_error.json",
        },
        "projections": {
            "loading": "proj_loading.json",
            "ready": "proj_ready.json",
            "error": "proj_error.json",
        },
        "out": "lib/fixtures/fixture.dart",
    }


def _setup_fixture_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "fixtures").mkdir(parents=True, exist_ok=True)
    for name in ("loading", "ready", "error"):
        _write_json(run_root / f"slot_{name}.json", {"state": name})
        _write_json(run_root / f"proj_{name}.json", {"proj": name})


def _make_trace_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    # P2.5d: 17-key schema. The old ambiguous ``expected`` key is gone;
    # the request now carries page_canvas_expected + page_canvas_projection
    # + shared_components_local + scene + merged_expected_out +
    # provenance_out. The trusted plan is three steps: merge -> gate ->
    # gen_layout_trace_test, with the gate's output (merged_expected.json)
    # bound to gen_layout_trace_test's --expected so the consumer's
    # raw-sidecar + adjacent-merged auto-adoption branch is structurally
    # unreachable.
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "page_canvas_expected": "canvas.expected.json",
        "page_canvas_projection": "canvas.projection.json",
        "shared_components_local": "shared_components.local.json",
        "scene": "scene.json",
        "merged_expected_out": "trace/merged_expected.json",
        "provenance_out": "trace/merged_expected.provenance.json",
        "page_import_path": "lib/page/home_page.dart",
        "page_type": "HomePage",
        "trace_out": "trace/trace.json",
        "responsive_out": "responsive.json",
        "responsive_contract_out": "responsive_contract.json",
        "viewports_file": "viewports.json",
        "safe_area_policy": "edge_to_edge",
        "out": "test/home_layout_trace_test.dart",
    }


def _setup_trace_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "page").mkdir(parents=True, exist_ok=True)
    (project_root / "test").mkdir(parents=True, exist_ok=True)
    (run_root / "trace").mkdir(parents=True, exist_ok=True)
    _write_json(run_root / "canvas.expected.json", {"expect": []})
    _write_json(run_root / "canvas.projection.json", {"proj": []})
    _write_json(run_root / "scene.json", {"scene": []})
    _write_json(run_root / "viewports.json", {"viewports": []})


@contextlib.contextmanager
def _visible_project():
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_visible_inputs(proj, run)
        yield proj, run, _make_visible_request(proj, run)


@contextlib.contextmanager
def _fixture_project():
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_fixture_inputs(proj, run)
        yield proj, run, _make_fixture_request(proj, run)


@contextlib.contextmanager
def _trace_project():
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_trace_inputs(proj, run)
        yield proj, run, _make_trace_request(proj, run)


# ---------------------------------------------------------------------------
# 1. Module + constants + public API surface.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2d2a_loads")
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.KIND_PLAN == KIND_PLAN
    assert module.KIND_VERIFY == KIND_VERIFY
    assert module.PLATFORM_ID == PLATFORM_ID
    assert module.PROFILE_ID == PROFILE_ID
    assert module.TIMEOUT_SECONDS == TIMEOUT_SECONDS
    assert isinstance(module.SCRIPT_NAME, str) and module.SCRIPT_NAME


def test_module_exposes_typed_exception() -> None:
    module = _load("p2d2a_exc")
    assert hasattr(module, "OperationPlanError")
    assert issubclass(module.OperationPlanError, ValueError)


def test_module_has_no_cli_main() -> None:
    module = _load("p2d2a_nocli")
    assert not hasattr(module, "main")
    source = MODULE_PATH.read_text()
    assert '__name__ == "__main__"' not in source


def test_public_api_exposes_only_three_functions() -> None:
    module = _load("p2d2a_pubapi")
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


def test_list_operation_ids_signature_takes_no_args() -> None:
    module = _load("p2d2a_sig_list")
    sig = inspect.signature(module.list_operation_ids)
    assert list(sig.parameters) == []


def test_build_signature() -> None:
    module = _load("p2d2a_sig_build")
    sig = inspect.signature(module.build)
    params = list(sig.parameters)
    assert params == ["operation_id", "request"], sig
    assert sig.parameters["operation_id"].default is inspect.Parameter.empty
    assert sig.parameters["request"].default is inspect.Parameter.empty


def test_verify_plan_signature() -> None:
    module = _load("p2d2a_sig_verify")
    sig = inspect.signature(module.verify_plan)
    params = list(sig.parameters)
    assert params == ["plan"], sig
    assert sig.parameters["plan"].default is inspect.Parameter.empty


def test_module_exposes_no_override_parameters() -> None:
    module = _load("p2d2a_noparams")
    forbidden = (
        "EXECUTABLE_OVERRIDE", "INTERPRETER_OVERRIDE", "ENV_OVERRIDE",
        "ARGV_OVERRIDE", "COMMAND_OVERRIDE", "REGISTRY_OVERRIDE",
        "MANIFEST_OVERRIDE", "CAPSULE_OVERRIDE", "ACTIVATION",
    )
    for attr in forbidden:
        assert not hasattr(module, attr), f"module exposes override {attr}"


# ---------------------------------------------------------------------------
# 2. Operation order.
# ---------------------------------------------------------------------------


def test_list_operation_ids_exact_order() -> None:
    module = _load("p2d2a_oporder")
    assert module.list_operation_ids() == OPERATION_IDS
    assert isinstance(module.list_operation_ids(), tuple)


def test_list_operation_ids_returns_new_tuple_each_call() -> None:
    """Mutating the returned tuple must not affect subsequent calls."""
    module = _load("p2d2a_newtuple")
    a = module.list_operation_ids()
    b = module.list_operation_ids()
    assert a == b
    assert a is not b


# ---------------------------------------------------------------------------
# 3. Capsule-first ordering.
# ---------------------------------------------------------------------------


def test_build_calls_verify_capsule_first() -> None:
    module = _load("p2d2a_capsfirst")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _visible_project() as (proj, run, request):
            try:
                module.build("flutter.visible_codegen.v1", request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_verify_plan_calls_verify_capsule_first() -> None:
    module = _load("p2d2a_capsfirst_verify")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        try:
            module.verify_plan({"kind": KIND_PLAN, "schema_version": SCHEMA_VERSION})
        except module.OperationPlanError as exc:
            assert "capsule boom" in str(exc)
        else:
            raise AssertionError("verify_plan did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_capsule_failure_redacts_generic_exception() -> None:
    module = _load("p2d2a_capsgeneric")

    class _SecretError(Exception):
        pass

    def _boom():
        raise _SecretError("SUPER_SECRET_BLOB")

    module._verify_capsule = _boom
    try:
        with _visible_project() as (proj, run, request):
            try:
                module.build("flutter.visible_codegen.v1", request)
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


def test_build_rejects_unknown_operation_id() -> None:
    module = _load("p2d2a_unknown_op")
    with _visible_project() as (proj, run, request):
        try:
            module.build("flutter.future_op.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown operation_id accepted")


def test_build_rejects_non_dict_request() -> None:
    module = _load("p2d2a_nondict")
    try:
        module.build("flutter.visible_codegen.v1", "not a dict")
    except module.OperationPlanError:
        pass
    else:
        raise AssertionError("non-dict request accepted")


def test_build_rejects_forbidden_command_key() -> None:
    module = _load("p2d2a_cmd")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["command"] = "evil"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden command key accepted")


def test_build_rejects_forbidden_shell_key() -> None:
    module = _load("p2d2a_shell")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["shell"] = True
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden shell key accepted")


def test_build_rejects_forbidden_env_key() -> None:
    module = _load("p2d2a_env")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["env"] = {"X": "1"}
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden env key accepted")


def test_build_rejects_forbidden_executable_key() -> None:
    module = _load("p2d2a_exec")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["executable"] = "/bin/sh"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden executable key accepted")


def test_build_rejects_forbidden_argv_key() -> None:
    module = _load("p2d2a_argv_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["argv"] = ["x"]
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden argv key accepted")


def test_build_rejects_forbidden_script_key() -> None:
    module = _load("p2d2a_script_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["script"] = "evil.py"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden script key accepted")


def test_build_rejects_forbidden_interpreter_key() -> None:
    module = _load("p2d2a_interp_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["interpreter"] = "/usr/bin/python"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden interpreter key accepted")


def test_build_rejects_forbidden_operation_id_key_in_request() -> None:
    module = _load("p2d2a_opid_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["operation_id"] = "evil"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden operation_id key accepted")


def test_build_rejects_forbidden_prompt_key() -> None:
    module = _load("p2d2a_prompt_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["prompt"] = "do evil"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden prompt key accepted")


def test_build_rejects_nested_forbidden_key_in_slots() -> None:
    """Forbidden keys must be rejected recursively inside nested dicts."""
    module = _load("p2d2a_nested_forbidden")
    with _fixture_project() as (proj, run, request):
        bad = dict(request)
        bad = {**bad, "slots": {**bad["slots"], "command": "evil.json"}}
        try:
            module.build("flutter.fixture_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("nested forbidden key in slots accepted")


def test_build_rejects_extra_unknown_key() -> None:
    module = _load("p2d2a_extra_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["unexpected_extra"] = "x"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown extra key accepted")


def test_build_rejects_missing_key() -> None:
    module = _load("p2d2a_missing_key")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        del bad["feature_id"]
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing key accepted")


# ---------------------------------------------------------------------------
# 5. Plan schema: top-level + step keys.
# ---------------------------------------------------------------------------


def test_build_visible_returns_canonical_plan_shape() -> None:
    module = _load("p2d2a_visible_shape")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    assert set(plan.keys()) == {
        "kind", "schema_version", "operation_id", "platform_id",
        "profile_id", "request_digest", "steps",
    }, sorted(plan.keys())
    assert plan["kind"] == KIND_PLAN
    assert plan["schema_version"] == SCHEMA_VERSION
    assert plan["operation_id"] == "flutter.visible_codegen.v1"
    assert plan["platform_id"] == PLATFORM_ID
    assert plan["profile_id"] == PROFILE_ID
    assert _is_sha256_hex(plan["request_digest"])
    assert isinstance(plan["steps"], list)
    # P2.5a2: visible_codegen has exactly four ordered steps:
    # generate_canvas, adapt_expected_slots (platform-origin post-step),
    # make_implementation_map, make_status_bar_policy.
    assert len(plan["steps"]) == 4


def test_build_visible_step_keys_exact() -> None:
    module = _load("p2d2a_step_keys")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    for i, step in enumerate(plan["steps"]):
        assert set(step.keys()) == {
            "step_id", "primitive", "primitive_sha256", "argv",
            "cwd", "timeout_seconds",
        }, f"step[{i}] keys: {sorted(step.keys())}"


def test_build_visible_step_ids_and_primitives_in_order() -> None:
    module = _load("p2d2a_step_ids")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    # P2.5a2: the adapt_expected_slots step sits between generate_canvas
    # and make_implementation_map; it is a platform-origin primitive
    # (resolved through PLATFORM_SCRIPTS_DIR, not the capsule).
    assert [s["step_id"] for s in plan["steps"]] == [
        "generate_canvas",
        "adapt_expected_slots",
        "make_implementation_map",
        "make_status_bar_policy",
    ]
    assert [s["primitive"] for s in plan["steps"]] == [
        "generate_canvas.py",
        "flutter_expected_slots_adapter_v1.py",
        "make_implementation_map.py",
        "make_status_bar_policy.py",
    ]


def test_build_visible_step_timeout_and_cwd() -> None:
    module = _load("p2d2a_step_tc")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    for i, step in enumerate(plan["steps"]):
        assert step["timeout_seconds"] == TIMEOUT_SECONDS, f"step[{i}] timeout"
        assert step["cwd"] == str(proj), f"step[{i}] cwd"


def test_build_visible_argv_interpreter_and_script_fixed() -> None:
    module = _load("p2d2a_argv_interp")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    capsule_script_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    platform_script_dir = ICP_ROOT / "scripts" / "platforms"
    # P2.5a2: each step's argv[1] is resolved through its closed origin
    # (capsule for the three legacy primitives, platform for the
    # adapt_expected_slots post-step).
    for i, step in enumerate(plan["steps"]):
        argv = step["argv"]
        assert argv[0] == sys.executable, f"step[{i}] argv[0]"
        if step["step_id"] == "adapt_expected_slots":
            expected_dir = platform_script_dir
        else:
            expected_dir = capsule_script_dir
        assert argv[1] == str(expected_dir / step["primitive"]), f"step[{i}] argv[1]"


# ---------------------------------------------------------------------------
# 6. visible_codegen argv exact structure.
# ---------------------------------------------------------------------------


def test_build_visible_generate_canvas_argv_exact() -> None:
    module = _load("p2d2a_vis_argv1")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    argv = plan["steps"][0]["argv"]
    # argv[0:2] are interpreter + script.
    flags = argv[2:]
    assert flags == [
        "--render-plan", str(run / "render_plan.json"),
        "--out", str(proj / "lib" / "canvas" / "canvas.dart"),
        "--colors-out", str(proj / "lib" / "canvas" / "colors.dart"),
        "--colors-import", "package:my_app/canvas/colors.dart",
        "--asset-prefix", "assets/icp/fancy_widget",
        "--classification", str(run / "classification.json"),
        "--component-manifest", str(run / "component_manifest.json"),
        "--class-name", "CanvasWidget",
    ], flags


def test_build_visible_adapt_expected_slots_argv_exact() -> None:
    """P2.5a2/P2.5b: the second visible_codegen step is
    adapt_expected_slots. It receives the already-validated
    project_root, canvas output path, run_root, and feature_id; its
    argv[1] resolves through the platform scripts directory (not the
    capsule). P2.5b extended the argv with ``--run-root`` and
    ``--feature-id`` so the adapter additionally publishes the
    canonical projection artifact."""
    module = _load("p2d2a_vis_argv_adapt")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    adapt = plan["steps"][1]
    assert adapt["step_id"] == "adapt_expected_slots"
    argv = adapt["argv"]
    flags = argv[2:]
    assert flags == [
        "--project-root", str(proj),
        "--canvas", str(proj / "lib" / "canvas" / "canvas.dart"),
        "--run-root", str(run),
        "--feature-id", "fancy_widget",
    ], flags


def test_build_visible_make_implementation_map_argv_exact() -> None:
    module = _load("p2d2a_vis_argv2")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    # P2.5a2: make_implementation_map is now the third step (index 2).
    argv = plan["steps"][2]["argv"]
    flags = argv[2:]
    assert flags == [
        "--render-plan", str(run / "render_plan.json"),
        "--canvas", str(proj / "lib" / "canvas" / "canvas.dart"),
        "--out", str(run / "implementation_map.json"),
    ], flags


def test_build_visible_make_status_bar_policy_argv_exact() -> None:
    module = _load("p2d2a_vis_argv3")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    # P2.5a2: make_status_bar_policy is now the fourth step (index 3).
    argv = plan["steps"][3]["argv"]
    flags = argv[2:]
    assert flags == [
        "--scene", str(run / "scene.json"),
        "--class-name", "StatusBarWidget",
        "--out", str(proj / "lib" / "status" / "status_bar.dart"),
    ], flags


def test_build_visible_no_artboard_flags() -> None:
    """--artboard-width and --artboard-height must not be emitted."""
    module = _load("p2d2a_no_artboard")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    for step in plan["steps"]:
        argv = step["argv"]
        assert "--artboard-width" not in argv
        assert "--artboard-height" not in argv


def test_build_visible_colors_import_strips_lib_prefix() -> None:
    module = _load("p2d2a_colorstrip")
    with _visible_project() as (proj, run, request):
        request = dict(request)
        request["colors_out"] = "lib/colors.dart"
        request["colors_import_path"] = "lib/colors.dart"
        plan = module.build("flutter.visible_codegen.v1", request)
    argv = plan["steps"][0]["argv"]
    # colors-import is at index 8 (after interp, script, render-plan, val, out, val, colors-out, val)
    idx = argv.index("--colors-import")
    assert argv[idx + 1] == "package:my_app/colors.dart"


# ---------------------------------------------------------------------------
# 7. fixture_codegen argv exact structure.
# ---------------------------------------------------------------------------


def test_build_fixture_returns_canonical_plan_shape() -> None:
    module = _load("p2d2a_fix_shape")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
    assert plan["kind"] == KIND_PLAN
    assert plan["operation_id"] == "flutter.fixture_codegen.v1"
    # P2.5b: fixture_codegen now has two ordered steps.
    assert len(plan["steps"]) == 2
    step0 = plan["steps"][0]
    assert step0["step_id"] == "verify_fixture_projections"
    assert step0["primitive"] == "flutter_fixture_projection_guard_v1.py"
    step1 = plan["steps"][1]
    assert step1["step_id"] == "make_visual_fixture"
    assert step1["primitive"] == "make_visual_fixture.py"


def test_build_fixture_argv_exact_sorted() -> None:
    module = _load("p2d2a_fix_argv")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
    # P2.5b: the make_visual_fixture step is now step[1] (the guard is
    # step[0]).
    argv = plan["steps"][1]["argv"]
    flags = argv[2:]
    # Slots must be sorted by state id: error, loading, ready.
    assert flags == [
        "--feature", "fancy_widget",
        "--slots", f"error={run / 'slot_error.json'}",
        "--slots", f"loading={run / 'slot_loading.json'}",
        "--slots", f"ready={run / 'slot_ready.json'}",
        "--out", str(proj / "lib" / "fixtures" / "fixture.dart"),
    ], flags


def test_build_fixture_guard_argv_exact_sorted() -> None:
    """P2.5b: the verify_fixture_projections guard step's argv is
    deterministic: --run-root, then sorted --projection STATE=ABS pairs,
    then sorted --slots STATE=ABS pairs."""
    module = _load("p2d2a_fix_guard_argv")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
    argv = plan["steps"][0]["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == str(
        module.PLATFORM_SCRIPTS_DIR / "flutter_fixture_projection_guard_v1.py"
    )
    flags = argv[2:]
    assert flags == [
        "--run-root", str(run),
        "--projection", f"error={run / 'proj_error.json'}",
        "--projection", f"loading={run / 'proj_loading.json'}",
        "--projection", f"ready={run / 'proj_ready.json'}",
        "--slots", f"error={run / 'slot_error.json'}",
        "--slots", f"loading={run / 'slot_loading.json'}",
        "--slots", f"ready={run / 'slot_ready.json'}",
    ], flags


def test_build_fixture_slots_sorted_regardless_of_insertion_order() -> None:
    module = _load("p2d2a_fix_sort")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_fixture_inputs(proj, run)
        # Insert in reverse order.
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "feature_id": "fancy_widget",
            "slots": {
                "ready": "slot_ready.json",
                "loading": "slot_loading.json",
                "error": "slot_error.json",
            },
            "projections": {
                "ready": "proj_ready.json",
                "loading": "proj_loading.json",
                "error": "proj_error.json",
            },
            "out": "lib/fixtures/fixture.dart",
        }
        plan = module.build("flutter.fixture_codegen.v1", request)
    # P2.5b: make_visual_fixture is now step[1].
    argv = plan["steps"][1]["argv"]
    slots_flags = [argv[i + 1] for i in range(len(argv)) if argv[i] == "--slots"]
    states = [s.split("=", 1)[0] for s in slots_flags]
    assert states == ["error", "loading", "ready"], states


def test_build_fixture_rejects_empty_slots() -> None:
    module = _load("p2d2a_fix_empty")
    with _fixture_project() as (proj, run, request):
        bad = dict(request)
        bad["slots"] = {}
        try:
            module.build("flutter.fixture_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("empty slots accepted")


def test_build_fixture_rejects_too_many_slots() -> None:
    module = _load("p2d2a_fix_too_many")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "fixtures").mkdir(parents=True)
        slots = {}
        projections = {}
        for i in range(33):
            name = f"state_{i:02d}"
            slots[name] = f"{name}.json"
            projections[name] = f"proj_{name}.json"
            _write_json(run / f"{name}.json", {"i": i})
            _write_json(run / f"proj_{name}.json", {"i": i})
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "feature_id": "widget",
            "slots": slots,
            "projections": projections,
            "out": "lib/fixtures/fixture.dart",
        }
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("33 slots accepted")


def test_build_fixture_accepts_32_slots() -> None:
    module = _load("p2d2a_fix_32")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "fixtures").mkdir(parents=True)
        slots = {}
        projections = {}
        for i in range(32):
            name = f"state_{i:02d}"
            slots[name] = f"{name}.json"
            projections[name] = f"proj_{name}.json"
            _write_json(run / f"{name}.json", {"i": i})
            _write_json(run / f"proj_{name}.json", {"i": i})
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "feature_id": "widget",
            "slots": slots,
            "projections": projections,
            "out": "lib/fixtures/fixture.dart",
        }
        plan = module.build("flutter.fixture_codegen.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_fixture_rejects_slots_not_dict() -> None:
    module = _load("p2d2a_fix_slots_not_dict")
    with _fixture_project() as (proj, run, request):
        bad = dict(request)
        bad["slots"] = ["a", "b"]
        try:
            module.build("flutter.fixture_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-dict slots accepted")


def test_build_fixture_rejects_invalid_state_id() -> None:
    module = _load("p2d2a_fix_bad_state")
    with _fixture_project() as (proj, run, request):
        bad = dict(request)
        bad["slots"] = {"Bad-State": "slot_loading.json"}
        try:
            module.build("flutter.fixture_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid state id accepted")


# ---------------------------------------------------------------------------
# 8. trace_harness argv exact structure.
# ---------------------------------------------------------------------------


def test_build_trace_returns_canonical_plan_shape() -> None:
    module = _load("p2d2a_trace_shape")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    assert plan["kind"] == KIND_PLAN
    assert plan["operation_id"] == "flutter.trace_harness.v1"
    # P2.5d: trace_harness now has three ordered steps:
    # merge_shared_expected, verify_merged_expectation_provenance
    # (platform-origin gate), gen_layout_trace_test.
    assert len(plan["steps"]) == 3
    step = plan["steps"][0]
    assert step["step_id"] == "merge_shared_expected"
    assert step["primitive"] == "merge_shared_expected.py"


def test_build_trace_argv_exact() -> None:
    module = _load("p2d2a_trace_argv")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    # Step 0 argv: merge_shared_expected --expected --local --scene --out.
    argv = plan["steps"][0]["argv"]
    flags = argv[2:]
    assert flags == [
        "--expected", str(run / "canvas.expected.json"),
        "--local", str(run / "shared_components.local.json"),
        "--scene", str(run / "scene.json"),
        "--out", str(run / "trace" / "merged_expected.json"),
    ], flags


def test_build_trace_rejects_page_expr_option() -> None:
    """--page-expr must not be supported in P2d2a."""
    module = _load("p2d2a_trace_no_page_expr")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    # P2.5d: --page-expr would only appear on step 2 (gen_layout_trace_test).
    argv = plan["steps"][2]["argv"]
    assert "--page-expr" not in argv


def test_build_trace_rejects_extra_imports_option() -> None:
    """--extra-imports must not be supported in P2d2a."""
    module = _load("p2d2a_trace_no_extra_imports")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    argv = plan["steps"][2]["argv"]
    assert "--extra-imports" not in argv


def test_build_trace_rejects_raw_viewports_option() -> None:
    """Raw --viewports must not be supported in P2d2a."""
    module = _load("p2d2a_trace_no_raw_viewports")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    argv = plan["steps"][2]["argv"]
    assert "--viewports" not in argv
    assert "--viewports-file" in argv


def test_build_trace_page_import_path_must_begin_lib() -> None:
    module = _load("p2d2a_trace_lib")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["page_import_path"] = "tool/page.dart"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("page_import_path without lib/ accepted")


def test_build_trace_safe_area_policy_enum() -> None:
    module = _load("p2d2a_trace_enum")
    with _trace_project() as (proj, run, request):
        request = dict(request)
        request["safe_area_policy"] = "inset_content"
        plan = module.build("flutter.trace_harness.v1", request)
    # P2.5d: --safe-area-policy is on step 2 (gen_layout_trace_test).
    argv = plan["steps"][2]["argv"]
    idx = argv.index("--safe-area-policy")
    assert argv[idx + 1] == "inset_content"


def test_build_trace_rejects_invalid_safe_area_policy() -> None:
    module = _load("p2d2a_trace_bad_enum")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["safe_area_policy"] = "weird_value"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid safe_area_policy accepted")


def test_build_trace_out_must_end_with_layout_trace_test() -> None:
    module = _load("p2d2a_trace_out_ext")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["out"] = "test/foo_test.dart"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("out without _layout_trace_test.dart accepted")


# ---------------------------------------------------------------------------
# 9. Manifest SHA binding.
# ---------------------------------------------------------------------------


def test_build_primitive_sha_matches_manifest() -> None:
    module = _load("p2d2a_sha_bind")
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = {e["name"]: e["sha256"] for e in manifest["scripts"]}
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    capsule_script_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    platform_script_dir = ICP_ROOT / "scripts" / "platforms"
    for step in plan["steps"]:
        assert _is_sha256_hex(step["primitive_sha256"])
        # P2.5a2: the adapt_expected_slots step is platform-origin; its
        # SHA is recomputed from the file under PLATFORM_SCRIPTS_DIR and
        # is NOT present in the capsule manifest. Every other step is
        # capsule-origin and its SHA must equal the manifest entry.
        if step["step_id"] == "adapt_expected_slots":
            assert step["primitive"] not in sha_map, (
                "platform primitive must not collide with capsule manifest"
            )
            expected_path = platform_script_dir / step["primitive"]
            assert step["primitive_sha256"] == hashlib.sha256(
                expected_path.read_bytes()
            ).hexdigest()
        else:
            assert step["primitive_sha256"] == sha_map[step["primitive"]]
            expected_path = capsule_script_dir / step["primitive"]
            # The manifest SHA must match the file bytes too.
            assert step["primitive_sha256"] == hashlib.sha256(
                expected_path.read_bytes()
            ).hexdigest()


def test_build_fixture_primitive_sha_matches_manifest() -> None:
    module = _load("p2d2a_sha_bind_fix")
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = {e["name"]: e["sha256"] for e in manifest["scripts"]}
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
    # P2.5b: the fixture plan now has two steps. The make_visual_fixture
    # step is capsule-origin and binds to the manifest SHA; the
    # verify_fixture_projections step is platform-origin and its SHA is
    # recomputed from the file (NOT in the manifest).
    for step in plan["steps"]:
        if step["step_id"] == "verify_fixture_projections":
            # Platform-origin: SHA must equal the live file SHA and the
            # primitive must NOT be in the manifest.
            assert step["primitive"] not in sha_map
            live_sha = hashlib.sha256(
                (module.PLATFORM_SCRIPTS_DIR / step["primitive"]).read_bytes()
            ).hexdigest()
            assert step["primitive_sha256"] == live_sha
        else:
            assert step["primitive_sha256"] == sha_map[step["primitive"]]


def test_build_trace_primitive_sha_matches_manifest() -> None:
    module = _load("p2d2a_sha_bind_trace")
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = {e["name"]: e["sha256"] for e in manifest["scripts"]}
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    for step in plan["steps"]:
        if step["primitive"] == "flutter_merged_expectation_provenance_gate_v1.py":
            # P2.5d platform-origin gate: SHA recomputed from file,
            # NOT present in the capsule manifest.
            assert step["primitive"] not in sha_map
            live = hashlib.sha256(
                (module.PLATFORM_SCRIPTS_DIR / step["primitive"]).read_bytes()
            ).hexdigest()
            assert step["primitive_sha256"] == live
        else:
            assert step["primitive_sha256"] == sha_map[step["primitive"]]


# ---------------------------------------------------------------------------
# 10. Determinism.
# ---------------------------------------------------------------------------


def test_build_request_digest_is_canonical_request_sha256() -> None:
    module = _load("p2d2a_digest_canon")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        expected = hashlib.sha256(_canonical_json(request)).hexdigest()
    assert plan["request_digest"] == expected


def test_build_deterministic_in_process() -> None:
    module = _load("p2d2a_det_proc")
    with _visible_project() as (proj, run, request):
        p1 = module.build("flutter.visible_codegen.v1", request)
        p2 = module.build("flutter.visible_codegen.v1", request)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_deterministic_across_modules() -> None:
    with _visible_project() as (proj, run, request):
        m1 = _load("p2d2a_det_mod1")
        m2 = _load("p2d2a_det_mod2")
        p1 = m1.build("flutter.visible_codegen.v1", request)
        p2 = m2.build("flutter.visible_codegen.v1", request)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_deterministic_across_cwd() -> None:
    with _visible_project() as (proj, run, request):
        start_cwd = os.getcwd()
        m = _load("p2d2a_det_cwd")
        try:
            os.chdir(str(proj))
            p1 = m.build("flutter.visible_codegen.v1", request)
        finally:
            os.chdir(start_cwd)
        try:
            os.chdir(str(run))
            p2 = m.build("flutter.visible_codegen.v1", request)
        finally:
            os.chdir(start_cwd)
    assert _canonical_json(p1) == _canonical_json(p2)


def test_build_deterministic_across_processes() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_visible_inputs(proj, run)
        request = _make_visible_request(proj, run)
        request_file = tmp / "request.json"
        request_file.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        helper = tmp / "child_build.py"
        helper.write_text(
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('fov1', %r)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "req = json.load(open(%r))\n"
            "plan = m.build(%r, req)\n"
            "sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + chr(10))\n"
            % (str(MODULE_PATH), str(request_file), "flutter.visible_codegen.v1")
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r1 = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True, env=env)
        r2 = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True, env=env)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr
        assert r1.stdout == r2.stdout


def test_build_deterministic_across_map_order() -> None:
    """The plan must be identical regardless of dict insertion order."""
    module = _load("p2d2a_det_mapord")
    with _fixture_project() as (proj, run, request):
        # Build a second request with slots/projections in different
        # insertion order. P2.5b: projections must keep the same state
        # set as slots.
        request_b = dict(request)
        request_b["slots"] = {
            "ready": request["slots"]["ready"],
            "error": request["slots"]["error"],
            "loading": request["slots"]["loading"],
        }
        request_b["projections"] = {
            "ready": request["projections"]["ready"],
            "error": request["projections"]["error"],
            "loading": request["projections"]["loading"],
        }
        p1 = module.build("flutter.fixture_codegen.v1", request)
        p2 = module.build("flutter.fixture_codegen.v1", request_b)
    assert _canonical_json(p1) == _canonical_json(p2)


# ---------------------------------------------------------------------------
# 11. verify_plan report shape.
# ---------------------------------------------------------------------------


def test_verify_plan_returns_canonical_report_shape() -> None:
    module = _load("p2d2a_verify_shape")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        report = module.verify_plan(plan)
    assert set(report.keys()) == {
        "ok", "kind", "schema_version", "operation_id",
        "steps_total", "plan_digest",
    }, sorted(report.keys())
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["operation_id"] == "flutter.visible_codegen.v1"
    # P2.5a2: visible_codegen now has four ordered steps.
    assert report["steps_total"] == 4
    assert _is_sha256_hex(report["plan_digest"])


def test_verify_plan_digest_matches_canonical_plan_bytes() -> None:
    module = _load("p2d2a_verify_digest")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        report = module.verify_plan(plan)
        expected = hashlib.sha256(_canonical_json(plan)).hexdigest()
    assert report["plan_digest"] == expected


def test_verify_plan_fixture_and_trace() -> None:
    module = _load("p2d2a_verify_fix_trace")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.fixture_codegen.v1"
    # P2.5b: fixture_codegen now has two ordered steps.
    assert report["steps_total"] == 2
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.trace_harness.v1"
    # P2.5d: trace_harness now has three ordered steps.
    assert report["steps_total"] == 3


# ---------------------------------------------------------------------------
# 12. verify_plan rejects tampered plans.
# ---------------------------------------------------------------------------


def _tamper(plan: dict, mutation) -> dict:
    new_plan = copy.deepcopy(plan)
    mutation(new_plan)
    return new_plan


def test_verify_plan_rejects_wrong_kind() -> None:
    module = _load("p2d2a_tamper_kind")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("kind", "evil"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong kind accepted")


def test_verify_plan_rejects_wrong_schema_version() -> None:
    module = _load("p2d2a_tamper_sv")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("schema_version", 2))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong schema_version accepted")


def test_verify_plan_rejects_wrong_platform_id() -> None:
    module = _load("p2d2a_tamper_pid")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("platform_id", "vue"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong platform_id accepted")


def test_verify_plan_rejects_wrong_profile_id() -> None:
    module = _load("p2d2a_tamper_prof")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("profile_id", "other"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong profile_id accepted")


def test_verify_plan_rejects_unknown_operation_id() -> None:
    module = _load("p2d2a_tamper_opid")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("operation_id", "flutter.future_op.v1"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown operation_id in plan accepted")


def test_verify_plan_rejects_malformed_request_digest() -> None:
    module = _load("p2d2a_tamper_rd")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("request_digest", "notsha"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("malformed request_digest accepted")


def test_verify_plan_rejects_extra_top_level_key() -> None:
    module = _load("p2d2a_tamper_extra")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = _tamper(plan, lambda p: p.__setitem__("extra", "x"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("extra top-level key accepted")


def test_verify_plan_rejects_tampered_primitive_sha() -> None:
    module = _load("p2d2a_tamper_psha")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["primitive_sha256"] = "a" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered primitive_sha256 accepted")


def test_verify_plan_rejects_tampered_step_id() -> None:
    module = _load("p2d2a_tamper_sid")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["step_id"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered step_id accepted")


def test_verify_plan_rejects_tampered_primitive_name() -> None:
    module = _load("p2d2a_tamper_pname")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["primitive"] = "evil.py"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered primitive name accepted")


def test_verify_plan_rejects_tampered_interpreter() -> None:
    module = _load("p2d2a_tamper_interp")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][0] = "/bin/sh"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered interpreter accepted")


def test_verify_plan_rejects_tampered_script_path() -> None:
    module = _load("p2d2a_tamper_script")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][1] = "/tmp/evil.py"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered script path accepted")


def test_verify_plan_rejects_tampered_timeout() -> None:
    module = _load("p2d2a_tamper_to")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["timeout_seconds"] = 999
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered timeout accepted")


def test_verify_plan_rejects_tampered_cwd() -> None:
    module = _load("p2d2a_tamper_cwd")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = "/etc"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered cwd accepted")


def test_verify_plan_rejects_tampered_argv_value() -> None:
    module = _load("p2d2a_tamper_argv_val")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        # Tamper the class-name value to an invalid identifier.
        idx = bad["steps"][0]["argv"].index("--class-name")
        bad["steps"][0]["argv"][idx + 1] = "not-a-class"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered argv value accepted")


def test_verify_plan_rejects_added_executable_field_in_step() -> None:
    module = _load("p2d2a_tamper_exec_field")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["command"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added command field in step accepted")


def test_verify_plan_rejects_added_shell_field_in_plan() -> None:
    module = _load("p2d2a_tamper_shell_plan")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["shell"] = True
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added shell field in plan accepted")


def test_verify_plan_rejects_added_env_field_in_argv() -> None:
    module = _load("p2d2a_tamper_env_argv")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        # Add a "shell" value as a stray flag.
        bad["steps"][0]["argv"].extend(["--shell", "true"])
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added stray flag accepted")


def test_verify_plan_rejects_wrong_step_count() -> None:
    module = _load("p2d2a_tamper_count")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"] = bad["steps"][:2]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("truncated steps accepted")


def test_verify_plan_rejects_swapped_step_order() -> None:
    module = _load("p2d2a_tamper_swap")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"] = [bad["steps"][1], bad["steps"][0], bad["steps"][2]]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("swapped step order accepted")


def test_verify_plan_rejects_duplicate_primitive_ownership() -> None:
    module = _load("p2d2a_tamper_dup_prim")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        # Make step 2 use the same primitive as step 1.
        bad["steps"][1]["primitive"] = bad["steps"][0]["primitive"]
        bad["steps"][1]["primitive_sha256"] = bad["steps"][0]["primitive_sha256"]
        bad["steps"][1]["step_id"] = bad["steps"][0]["step_id"]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("duplicate primitive ownership accepted")


# ---------------------------------------------------------------------------
# 13. Path / project_root / run_root validation.
# ---------------------------------------------------------------------------


def test_build_rejects_relative_project_root() -> None:
    module = _load("p2d2a_rel_proj")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["project_root"] = "relative/path"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative project_root accepted")


def test_build_rejects_dotdot_in_project_root() -> None:
    module = _load("p2d2a_dotdot_proj")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["project_root"] = str(proj) + "/sub/../.."
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("dotdot project_root accepted")


def test_build_rejects_non_lexically_normalized_project_root() -> None:
    module = _load("p2d2a_norm_proj")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["project_root"] = str(proj) + "/./x"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-normalized project_root accepted")


def test_build_rejects_missing_project_root() -> None:
    module = _load("p2d2a_missing_proj")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["project_root"] = str(proj / "does_not_exist")
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing project_root accepted")


def test_build_rejects_file_as_project_root() -> None:
    module = _load("p2d2a_file_proj")
    with _visible_project() as (proj, run, request):
        f = proj / "regular.txt"
        f.write_text("hi", encoding="utf-8")
        bad = dict(request)
        bad["project_root"] = str(f)
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("regular file project_root accepted")


def test_build_rejects_symlinked_project_root() -> None:
    module = _load("p2d2a_sym_proj")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_visible_inputs(proj, run)
        link = tmp / "proj_link"
        os.symlink(proj, link)
        request = _make_visible_request(proj, run)
        bad = dict(request)
        bad["project_root"] = str(link)
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked project_root accepted")


def test_build_rejects_run_root_equal_to_project_root() -> None:
    module = _load("p2d2a_eq_roots")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["run_root"] = str(proj)
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("run_root == project_root accepted")


def test_build_rejects_run_root_nested_in_project_root() -> None:
    module = _load("p2d2a_run_in_proj")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / "run"
        run.mkdir()
        _setup_visible_inputs(proj, run)
        request = _make_visible_request(proj, run)
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("run_root nested in project_root accepted")


def test_build_rejects_project_root_nested_in_run_root() -> None:
    module = _load("p2d2a_proj_in_run")
    with _canonical_tempdir() as tmp:
        run = tmp / "run"
        run.mkdir()
        proj = run / "proj"
        proj.mkdir()
        _setup_visible_inputs(proj, run)
        request = _make_visible_request(proj, run)
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("project_root nested in run_root accepted")


# ---------------------------------------------------------------------------
# 13b. Internal manifest run-root rule (P2e1 alignment).
#
# The frozen selection manifest derives the Flutter run root as
# ``<project>/.iff/icp_runs/<batch_id>``. The plan builder must accept
# that exact internal path (so a binding can re-use the manifest's own
# run root) while continuing to reject every other project-internal
# path. ``<batch_id>`` must match the freezer's safe grammar
# ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$``.
# ---------------------------------------------------------------------------


_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _make_internal_run_root(project_root: Path, batch_id: str) -> Path:
    """Create ``<project>/.iff/icp_runs/<batch_id>`` and return it."""
    run = project_root / ".iff" / "icp_runs" / batch_id
    run.mkdir(parents=True, exist_ok=False)
    return run


def test_build_accepts_exact_internal_manifest_run_root_fixture() -> None:
    """A real ``fixture_codegen`` request whose ``run_root`` is exactly
    ``<project>/.iff/icp_runs/<batch_id>`` must be accepted."""
    module = _load("p2d2a_internal_ok")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = _make_internal_run_root(proj, "batch-001")
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        plan = module.build("flutter.fixture_codegen.v1", request)
    assert plan["operation_id"] == "flutter.fixture_codegen.v1"
    report = module.verify_plan(plan)
    assert report["ok"] is True


def test_build_accepts_external_disjoint_run_root_fixture() -> None:
    """A disjoint project-external run root must remain accepted
    (compatibility with the pre-P2e1 behaviour)."""
    module = _load("p2d2a_external_ok")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        plan = module.build("flutter.fixture_codegen.v1", request)
    assert plan["operation_id"] == "flutter.fixture_codegen.v1"


def test_build_rejects_arbitrary_nested_project_run_root() -> None:
    """An arbitrary project-internal run root (``<project>/run``) is
    still rejected — only the exact manifest path is whitelisted."""
    module = _load("p2d2a_arb_nested")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / "run"
        run.mkdir()
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("arbitrary nested run_root accepted")


def test_build_rejects_internal_iff_dir_as_run_root() -> None:
    """``<project>/.iff`` itself is not a valid run root."""
    module = _load("p2d2a_iff_only")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / ".iff"
        run.mkdir()
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("<project>/.iff accepted as run_root")


def test_build_rejects_internal_icp_runs_dir_as_run_root() -> None:
    """``<project>/.iff/icp_runs`` itself is not a valid run root (no
    batch segment)."""
    module = _load("p2d2a_icp_runs_only")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / ".iff" / "icp_runs"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("<project>/.iff/icp_runs accepted as run_root")


def test_build_rejects_internal_run_root_with_extra_segment() -> None:
    """``<project>/.iff/icp_runs/<batch>/extra`` has an extra segment and
    is rejected."""
    module = _load("p2d2a_extra_seg")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / ".iff" / "icp_runs" / "batch-001" / "extra"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("extra-segment run_root accepted")


def test_build_rejects_internal_run_root_unsafe_batch_dot() -> None:
    """A batch segment of ``.`` is rejected (path collapse attempt)."""
    module = _load("p2d2a_batch_dot")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        # ``.iff/icp_runs/.`` resolves to ``icp_runs``; build the dir as
        # the literal ``.`` name to exercise the grammar check.
        run = proj / ".iff" / "icp_runs" / "."
        # mkdir of ``.`` is a no-op on the parent; instead place a dir
        # whose name is a grammar-invalid token.
        run = proj / ".iff" / "icp_runs" / "..bad"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unsafe batch id accepted")


def test_build_rejects_internal_run_root_unsafe_batch_slash() -> None:
    """A batch segment containing ``/`` is rejected by the grammar."""
    module = _load("p2d2a_batch_slash")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        # Construct ``<project>/.iff/icp_runs/a/b`` which has 4 internal
        # segments (not the allowed 3) and an unsafe token.
        run = proj / ".iff" / "icp_runs" / "a" / "b"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("slash-containing batch accepted")


def test_build_rejects_internal_run_root_trailing_newline_batch() -> None:
    """A batch segment ending in a newline (``batch-001\\n``) is rejected.

    macOS permits a directory name containing a newline, so this is a
    real on-disk fixture. Python's ``re.match(r'...$')`` accepts a value
    ending in a single newline (``$`` may match before the final
    newline); the documented grammar
    ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`` is a *whole-string* contract
    and whitespace must be rejected. The operation root rule must use
    exact full-string matching.
    """
    module = _load("p2d2a_batch_newline")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        # A directory whose final component is ``batch-001\n``. macOS
        # allows this; build the directory so the existing root
        # validator accepts it as a real non-symlink directory, then
        # require the batch-grammar check to reject the trailing
        # newline.
        newline_batch = "batch-001\n"
        run = proj / ".iff" / "icp_runs" / newline_batch
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("trailing-newline batch accepted")


def test_internal_run_root_batch_rule_uses_fullmatch_directly() -> None:
    """Direct unit check: ``_check_root_nesting`` must reject a run root
    whose batch component ends in a newline, even when both paths are
    already canonical (the regex contract is whole-string). This
    isolates the grammar enforcement from the root validator."""
    module = _load("p2d2a_batch_fullmatch_unit")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / ".iff" / "icp_runs" / "batch-001\n"
        run.mkdir(parents=True)
        try:
            module._check_root_nesting(proj, run)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError(
                "_check_root_nesting accepted a trailing-newline batch"
            )


def test_build_rejects_internal_run_root_empty_batch() -> None:
    """An empty batch segment is rejected."""
    module = _load("p2d2a_batch_empty")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        # ``.iff/icp_runs`` with no batch is already covered; here we
        # check the prefix lookalike ``.iff/icp_runs_`` (prefix variant).
        run = proj / ".iff" / "icp_runs_" / "batch-001"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("prefix-lookalike icp_runs_ accepted")


def test_build_rejects_internal_run_root_prefix_lookalike_iff() -> None:
    """``<project>/.iff2/icp_runs/<batch>`` is a prefix lookalike and is
    rejected."""
    module = _load("p2d2a_prefix_iff2")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / ".iff2" / "icp_runs" / "batch-001"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("prefix-lookalike .iff2 accepted")


def test_build_rejects_internal_run_root_wrong_state_dirname() -> None:
    """``<project>/.iffX/icp_runs/<batch>`` style or ``<project>/run/icp_runs/<batch>``
    must be rejected (only ``.iff`` is the Flutter state root)."""
    module = _load("p2d2a_wrong_state")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        run = proj / "run" / "icp_runs" / "batch-001"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong state dirname accepted")


def test_build_rejects_symlinked_iff_ancestor_in_internal_run_root() -> None:
    """A symlinked ``.iff`` ancestor is rejected by the root validator."""
    module = _load("p2d2a_sym_iff")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        real_state = tmp / "real_iff"
        real_state.mkdir()
        (proj / ".iff").symlink_to(real_state, target_is_directory=True)
        run = proj / ".iff" / "icp_runs" / "batch-001"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked .iff accepted")


def test_build_rejects_symlinked_icp_runs_in_internal_run_root() -> None:
    """A symlinked ``icp_runs`` ancestor is rejected."""
    module = _load("p2d2a_sym_icp_runs")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        (proj / ".iff").mkdir()
        real_runs = tmp / "real_runs"
        real_runs.mkdir()
        (proj / ".iff" / "icp_runs").symlink_to(real_runs, target_is_directory=True)
        run = proj / ".iff" / "icp_runs" / "batch-001"
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked icp_runs accepted")


def test_build_rejects_symlinked_batch_in_internal_run_root() -> None:
    """A symlinked batch directory is rejected."""
    module = _load("p2d2a_sym_batch")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        (proj / ".iff" / "icp_runs").mkdir(parents=True)
        real_batch = tmp / "real_batch"
        real_batch.mkdir()
        (proj / ".iff" / "icp_runs" / "batch-001").symlink_to(
            real_batch, target_is_directory=True
        )
        run = proj / ".iff" / "icp_runs" / "batch-001"
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked batch accepted")


def test_internal_manifest_run_root_batch_grammar_range() -> None:
    """The accepted internal run root must obey the freezer batch grammar.
    A maximal safe id is accepted; an overlong id is rejected."""
    module = _load("p2d2a_batch_grammar")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        safe = "b" + "0" * 127  # 128 chars total, matches {0,127} after first
        run = _make_internal_run_root(proj, safe)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        plan = module.build("flutter.fixture_codegen.v1", request)
        assert plan["operation_id"] == "flutter.fixture_codegen.v1"
    # Overlong id rejected.
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        too_long = "b" + "0" * 128  # 129 chars
        run = proj / ".iff" / "icp_runs" / too_long
        run.mkdir(parents=True)
        _setup_fixture_inputs(proj, run)
        request = _make_fixture_request(proj, run)
        try:
            module.build("flutter.fixture_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("overlong batch id accepted")


# ---------------------------------------------------------------------------
# 14. Run-input path rules.
# ---------------------------------------------------------------------------


def test_build_rejects_missing_run_input() -> None:
    module = _load("p2d2a_missing_input")
    with _visible_project() as (proj, run, request):
        (run / "render_plan.json").unlink()
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing run-input accepted")


def test_build_rejects_run_input_directory() -> None:
    module = _load("p2d2a_input_dir")
    with _visible_project() as (proj, run, request):
        (run / "render_plan.json").unlink()
        (run / "render_plan.json").mkdir()
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("directory run-input accepted")


def test_build_rejects_symlinked_run_input() -> None:
    module = _load("p2d2a_sym_input")
    with _visible_project() as (proj, run, request):
        outside = proj / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (run / "render_plan.json").unlink()
        os.symlink(outside, run / "render_plan.json")
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked run-input accepted")


def test_build_rejects_run_input_absolute_path() -> None:
    module = _load("p2d2a_abs_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = str(run / "render_plan.json")
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("absolute run-input accepted")


def test_build_rejects_run_input_dotdot() -> None:
    module = _load("p2d2a_dotdot_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = "../outside.json"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("dotdot run-input accepted")


def test_build_rejects_run_input_wrong_extension() -> None:
    module = _load("p2d2a_ext_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = "render_plan.txt"
        (run / "render_plan.txt").write_text("{}", encoding="utf-8")
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong extension run-input accepted")


def test_build_rejects_run_input_backslash() -> None:
    module = _load("p2d2a_bs_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = "sub\\dir/render_plan.json"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("backslash run-input accepted")


def test_build_rejects_run_input_with_empty_component() -> None:
    module = _load("p2d2a_empty_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = "sub//render_plan.json"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("empty component run-input accepted")


def test_build_rejects_run_input_with_uri_scheme() -> None:
    module = _load("p2d2a_uri_input")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = "file://x/render_plan.json"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("URI scheme run-input accepted")


def test_build_rejects_run_input_symlinked_component() -> None:
    module = _load("p2d2a_symcomp_input")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        # Create a symlinked subdirectory in run_root.
        real_dir = tmp / "real_sub"
        real_dir.mkdir()
        _write_json(real_dir / "render_plan.json", {"x": 1})
        os.symlink(real_dir, run / "sub")
        _write_json(run / "scene.json", {"s": 1})
        _write_json(run / "classification.json", {"c": 1})
        _write_json(run / "component_manifest.json", {"m": 1})
        request = _make_visible_request(proj, run)
        request["render_plan"] = "sub/render_plan.json"
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked component run-input accepted")


# ---------------------------------------------------------------------------
# 15. Project-output path rules.
# ---------------------------------------------------------------------------


def test_build_allows_absent_project_output() -> None:
    module = _load("p2d2a_absent_out")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_visible_inputs(proj, run)
        # lib/canvas dir exists but the .dart files do not.
        request = _make_visible_request(proj, run)
        plan = module.build("flutter.visible_codegen.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_allows_existing_project_output_regular_file() -> None:
    module = _load("p2d2a_existing_out")
    with _visible_project() as (proj, run, request):
        (proj / "lib" / "canvas" / "canvas.dart").write_text("// existing", encoding="utf-8")
        plan = module.build("flutter.visible_codegen.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_rejects_project_output_directory() -> None:
    module = _load("p2d2a_out_dir")
    with _visible_project() as (proj, run, request):
        (proj / "lib" / "canvas" / "canvas.dart").mkdir()
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("directory project-output accepted")


def test_build_rejects_symlinked_project_output() -> None:
    module = _load("p2d2a_sym_out")
    with _visible_project() as (proj, run, request):
        outside = proj / "outside.dart"
        outside.write_text("// hi", encoding="utf-8")
        (proj / "lib" / "canvas" / "canvas.dart").unlink(missing_ok=True)
        os.symlink(outside, proj / "lib" / "canvas" / "canvas.dart")
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked project-output accepted")


def test_build_rejects_project_output_wrong_extension() -> None:
    module = _load("p2d2a_out_ext")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["canvas_out"] = "lib/canvas/canvas.txt"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong extension project-output accepted")


def test_build_rejects_project_output_dotdot() -> None:
    module = _load("p2d2a_out_dotdot")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["canvas_out"] = "../escape.dart"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("dotdot project-output accepted")


def test_build_rejects_project_output_absolute() -> None:
    module = _load("p2d2a_out_abs")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["canvas_out"] = str(proj / "lib" / "canvas" / "canvas.dart")
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("absolute project-output accepted")


def test_build_rejects_colors_import_path_not_equal_colors_out() -> None:
    module = _load("p2d2a_cip_neq")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["colors_out"] = "lib/canvas/colors.dart"
        bad["colors_import_path"] = "lib/other/colors.dart"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("colors_import_path != colors_out accepted")


# ---------------------------------------------------------------------------
# 16. Run-output path rules.
# ---------------------------------------------------------------------------


def test_build_allows_absent_run_output() -> None:
    module = _load("p2d2a_absent_runout")
    with _visible_project() as (proj, run, request):
        # implementation_map_out does not exist yet — that's allowed.
        plan = module.build("flutter.visible_codegen.v1", request)
    assert plan["kind"] == KIND_PLAN


def test_build_rejects_run_output_wrong_extension() -> None:
    module = _load("p2d2a_runout_ext")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["implementation_map_out"] = "impl.txt"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong extension run-output accepted")


def test_build_rejects_run_output_directory() -> None:
    module = _load("p2d2a_runout_dir")
    with _visible_project() as (proj, run, request):
        (run / "implementation_map.json").mkdir()
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("directory run-output accepted")


def test_build_rejects_run_output_symlinked_component() -> None:
    module = _load("p2d2a_runout_symcomp")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        _write_json(run / "render_plan.json", {"x": 1})
        _write_json(run / "scene.json", {"s": 1})
        _write_json(run / "classification.json", {"c": 1})
        _write_json(run / "component_manifest.json", {"m": 1})
        real_out_dir = tmp / "real_out"
        real_out_dir.mkdir()
        os.symlink(real_out_dir, run / "out_dir")
        request = _make_visible_request(proj, run)
        request["implementation_map_out"] = "out_dir/impl.json"
        try:
            module.build("flutter.visible_codegen.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked component run-output accepted")


# ---------------------------------------------------------------------------
# 17. Identifier rules.
# ---------------------------------------------------------------------------


def test_build_rejects_invalid_package_name() -> None:
    module = _load("p2d2a_bad_pkg")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["package_name"] = "My-App"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid package_name accepted")


def test_build_rejects_invalid_feature_id() -> None:
    module = _load("p2d2a_bad_feat")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["feature_id"] = "Feature-Id"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid feature_id accepted")


def test_build_rejects_invalid_dart_class_name() -> None:
    module = _load("p2d2a_bad_class")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["canvas_class_name"] = "not-a-class"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid Dart class accepted")


def test_build_rejects_dart_class_starting_lowercase() -> None:
    module = _load("p2d2a_lower_class")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["status_bar_class_name"] = "statusBar"
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("lowercase-leading Dart class accepted")


def test_build_constructs_asset_prefix_from_feature_id() -> None:
    module = _load("p2d2a_asset_prefix")
    with _visible_project() as (proj, run, request):
        request = dict(request)
        request["feature_id"] = "my_super_feature"
        plan = module.build("flutter.visible_codegen.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--asset-prefix")
    assert argv[idx + 1] == "assets/icp/my_super_feature"


# ---------------------------------------------------------------------------
# 18. No subprocess / shell / executor.
# ---------------------------------------------------------------------------


def test_module_does_not_import_subprocess() -> None:
    import ast as _ast
    tree = _ast.parse(MODULE_PATH.read_text())
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess", "module imports subprocess"
                assert not alias.name.startswith("subprocess."), "module imports subprocess"
        elif isinstance(node, _ast.ImportFrom):
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
    """Loading and running build must never reference iff/ in output."""
    module = _load("p2d2a_noreadiff")
    iff_path = REPO_ROOT / "iff"
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    assert str(iff_path) not in json.dumps(plan)


# ---------------------------------------------------------------------------
# 19. No writes during build / verify.
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
    module = _load("p2d2a_nowrite_build")
    with _visible_project() as (proj, run, request):
        before_proj = _snapshot(proj)
        before_run = _snapshot(run)
        module.build("flutter.visible_codegen.v1", request)
        after_proj = _snapshot(proj)
        after_run = _snapshot(run)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_run.keys()) == set(after_run.keys())
    for p, data in before_run.items():
        assert after_run[p] == data, f"run mutated: {p}"


def test_verify_plan_does_not_mutate_project_or_run() -> None:
    module = _load("p2d2a_nowrite_verify")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
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
    module = _load("p2d2a_nowrite_capsule")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    before = _snapshot(capsule_dir)
    with _visible_project() as (proj, run, request):
        module.build("flutter.visible_codegen.v1", request)
    after = _snapshot(capsule_dir)
    assert set(before.keys()) == set(after.keys())
    for p, data in before.items():
        assert after[p] == data, f"capsule mutated: {p}"


def test_build_does_not_create_pycache_in_project() -> None:
    module = _load("p2d2a_nopyc")
    with _visible_project() as (proj, run, request):
        module.build("flutter.visible_codegen.v1", request)
        pyc_dirs = [p for p in proj.rglob("__pycache__") if p.is_dir()]
    assert pyc_dirs == [], pyc_dirs


# ---------------------------------------------------------------------------
# 20. Registry / P2c descriptor unchanged.
# ---------------------------------------------------------------------------


def test_build_does_not_edit_registry() -> None:
    module = _load("p2d2a_noedit_reg")
    before = REGISTRY_PATH.read_bytes()
    with _visible_project() as (proj, run, request):
        module.build("flutter.visible_codegen.v1", request)
    after = REGISTRY_PATH.read_bytes()
    assert before == after, "registries.json was mutated"


def test_build_does_not_edit_p2c_descriptor() -> None:
    module = _load("p2d2a_noedit_desc")
    before = P2C_DESCRIPTOR_PATH.read_bytes()
    with _visible_project() as (proj, run, request):
        module.build("flutter.visible_codegen.v1", request)
    after = P2C_DESCRIPTOR_PATH.read_bytes()
    assert before == after, "P2c descriptor was mutated"


def test_build_does_not_touch_pycache_in_capsule() -> None:
    module = _load("p2d2a_nocapsule_pyc")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    pyc_before = list(capsule_dir.rglob("__pycache__"))
    with _visible_project() as (proj, run, request):
        module.build("flutter.visible_codegen.v1", request)
    pyc_after = list(capsule_dir.rglob("__pycache__"))
    assert pyc_before == pyc_after


# ---------------------------------------------------------------------------
# 21. Generic exception redaction.
# ---------------------------------------------------------------------------


def test_build_redacts_generic_exception_from_path_validation() -> None:
    """An unexpected OSError during path validation must surface as a
    module-local OperationPlanError whose message exposes type only."""
    module = _load("p2d2a_redact")
    original = module._validate_root_path

    def _boom(value, role):
        raise OSError("SUPER_SECRET_OSERROR")

    module._validate_root_path = _boom
    try:
        with _visible_project() as (proj, run, request):
            try:
                module.build("flutter.visible_codegen.v1", request)
            except module.OperationPlanError as exc:
                msg = str(exc)
                assert "SUPER_SECRET_OSERROR" not in msg
            else:
                raise AssertionError("generic OSError swallowed")
    finally:
        module._validate_root_path = original


def test_verify_plan_redacts_generic_exception() -> None:
    module = _load("p2d2a_redact_verify")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
    original = module._validate_root_path

    def _boom(*args, **kwargs):
        raise OSError("SUPER_SECRET_VERIFY")

    # Patch a helper used inside verify_plan to raise generic.
    module._manifest_sha_map = _boom
    try:
        try:
            module.verify_plan(plan)
        except module.OperationPlanError as exc:
            msg = str(exc)
            assert "SUPER_SECRET_VERIFY" not in msg
        else:
            raise AssertionError("generic exception swallowed in verify_plan")
    finally:
        del module._manifest_sha_map


# ---------------------------------------------------------------------------
# 22. build calls verify_plan internally before returning.
# ---------------------------------------------------------------------------


def test_build_calls_verify_plan_internally() -> None:
    module = _load("p2d2a_internal_verify")
    called = {"count": 0}
    original = module.verify_plan

    def _tracking(plan):
        called["count"] += 1
        return original(plan)

    module.verify_plan = _tracking
    try:
        with _visible_project() as (proj, run, request):
            plan = module.build("flutter.visible_codegen.v1", request)
    finally:
        module.verify_plan = original
    assert called["count"] >= 1


def test_build_fails_if_internal_verify_fails() -> None:
    """If the internally-built plan fails verify_plan (e.g. due to a bug
    patched into verify), build must fail visibly."""
    module = _load("p2d2a_internal_fail")

    def _boom(plan):
        raise module.OperationPlanError("internal verify boom")

    module.verify_plan = _boom
    try:
        with _visible_project() as (proj, run, request):
            try:
                module.build("flutter.visible_codegen.v1", request)
            except module.OperationPlanError as exc:
                assert "internal verify boom" in str(exc)
            else:
                raise AssertionError("build swallowed internal verify failure")
    finally:
        del module.verify_plan


# ---------------------------------------------------------------------------
# 23. Manifest duplicate-key rejection.
# ---------------------------------------------------------------------------


def test_module_loads_manifest_with_duplicate_key_rejection() -> None:
    """The module's strict manifest decoder must reject duplicate JSON keys."""
    module = _load("p2d2a_dup_manifest")
    # The module exposes _decode_json_strict (or equivalent); we verify
    # the manifest load path rejects duplicates by inspecting source.
    source = MODULE_PATH.read_text()
    assert "object_pairs_hook" in source or "_reject_duplicate_keys" in source


# ---------------------------------------------------------------------------
# 24. verify_plan argv value validators (request-derived positions).
# ---------------------------------------------------------------------------


def test_verify_plan_rejects_invalid_dart_class_in_argv() -> None:
    module = _load("p2d2a_vp_bad_class")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--class-name")
        bad["steps"][0]["argv"][idx + 1] = "0invalid"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid Dart class in argv accepted by verify_plan")


def test_verify_plan_rejects_invalid_safe_area_enum_in_argv() -> None:
    module = _load("p2d2a_vp_bad_enum")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
        bad = copy.deepcopy(plan)
        # P2.5d: --safe-area-policy lives on step 2 (gen_layout_trace_test),
        # not step 0 (merge_shared_expected).
        idx = bad["steps"][2]["argv"].index("--safe-area-policy")
        bad["steps"][2]["argv"][idx + 1] = "weird"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid safe-area enum accepted by verify_plan")


def test_verify_plan_rejects_invalid_package_import_in_argv() -> None:
    module = _load("p2d2a_vp_bad_import")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--colors-import")
        bad["steps"][0]["argv"][idx + 1] = "not-a-package-import"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid package import accepted by verify_plan")


def test_verify_plan_rejects_non_absolute_path_in_argv() -> None:
    module = _load("p2d2a_vp_rel_path")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--render-plan")
        bad["steps"][0]["argv"][idx + 1] = "relative/path.json"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative path in argv accepted by verify_plan")


def test_verify_plan_rejects_wrong_extension_in_argv() -> None:
    module = _load("p2d2a_vp_wrong_ext")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--out")
        bad["steps"][0]["argv"][idx + 1] = str(proj / "lib" / "canvas" / "canvas.txt")
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("wrong extension in argv accepted by verify_plan")


def test_verify_plan_rejects_invalid_asset_prefix_in_argv() -> None:
    module = _load("p2d2a_vp_bad_prefix")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--asset-prefix")
        bad["steps"][0]["argv"][idx + 1] = "assets/other/x"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid asset prefix accepted by verify_plan")


def test_verify_plan_rejects_invalid_slots_pair_in_argv() -> None:
    module = _load("p2d2a_vp_bad_slots")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--slots")
        bad["steps"][0]["argv"][idx + 1] = "not-a-pair"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("invalid slots pair accepted by verify_plan")


def test_verify_plan_rejects_unsorted_slots_in_argv() -> None:
    """Slots in argv must be sorted by state id; out-of-order must fail."""
    module = _load("p2d2a_vp_unsorted_slots")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
        bad = copy.deepcopy(plan)
        # Swap two slot flag values.
        argv = bad["steps"][0]["argv"]
        i_first = argv.index("--slots")
        # Find the three slot values.
        slot_idxs = [i for i, v in enumerate(argv) if v == "--slots"]
        # Swap first and second slot values.
        v_first = argv[slot_idxs[0] + 1]
        argv[slot_idxs[0] + 1] = argv[slot_idxs[1] + 1]
        argv[slot_idxs[1] + 1] = v_first
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unsorted slots accepted by verify_plan")


def test_verify_plan_rejects_step_with_extra_key() -> None:
    module = _load("p2d2a_vp_step_extra")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["executable"] = "/bin/sh"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("step with extra executable key accepted")


# ---------------------------------------------------------------------------
# 25. Full happy-path for all three operations.
# ---------------------------------------------------------------------------


def test_build_visible_happy_path() -> None:
    module = _load("p2d2a_happy_visible")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    # P2.5a2: visible_codegen now has four ordered steps.
    assert report["steps_total"] == 4


def test_build_fixture_happy_path() -> None:
    module = _load("p2d2a_happy_fixture")
    with _fixture_project() as (proj, run, request):
        plan = module.build("flutter.fixture_codegen.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    # P2.5b: fixture_codegen now has two ordered steps.
    assert report["steps_total"] == 2


def test_build_trace_happy_path() -> None:
    module = _load("p2d2a_happy_trace")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    # P2.5d: trace_harness now has three ordered steps.
    assert report["steps_total"] == 3


def test_build_all_three_in_sequence() -> None:
    module = _load("p2d2a_all_three")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        # Set up all inputs needed for all three operations.
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        (proj / "lib" / "fixtures").mkdir(parents=True)
        (proj / "lib" / "page").mkdir(parents=True)
        (proj / "test").mkdir(parents=True)
        (run / "trace").mkdir(parents=True, exist_ok=True)
        _write_json(run / "render_plan.json", {})
        _write_json(run / "scene.json", {})
        _write_json(run / "classification.json", {})
        _write_json(run / "component_manifest.json", {})
        _write_json(run / "slot_loading.json", {})
        _write_json(run / "slot_ready.json", {})
        _write_json(run / "slot_error.json", {})
        # P2.5b: fixture_codegen now also requires projection artifacts
        # for each slot state.
        _write_json(run / "proj_loading.json", {})
        _write_json(run / "proj_ready.json", {})
        _write_json(run / "proj_error.json", {})
        # P2.5d: trace_harness now requires page_canvas_expected,
        # page_canvas_projection, scene, viewports_file as existing
        # files, plus merged_expected_out + provenance_out as output
        # targets under run_root.
        _write_json(run / "canvas.expected.json", {})
        _write_json(run / "canvas.projection.json", {})
        _write_json(run / "viewports.json", {})

        vis_req = _make_visible_request(proj, run)
        fix_req = _make_fixture_request(proj, run)
        trace_req = _make_trace_request(proj, run)

        vis_plan = module.build("flutter.visible_codegen.v1", vis_req)
        fix_plan = module.build("flutter.fixture_codegen.v1", fix_req)
        trace_plan = module.build("flutter.trace_harness.v1", trace_req)

    assert module.verify_plan(vis_plan)["ok"]
    assert module.verify_plan(fix_plan)["ok"]
    assert module.verify_plan(trace_plan)["ok"]


# ---------------------------------------------------------------------------
# 26. verify_plan report determinism.
# ---------------------------------------------------------------------------


def test_verify_plan_deterministic_in_process() -> None:
    module = _load("p2d2a_vp_det")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        r1 = module.verify_plan(plan)
        r2 = module.verify_plan(plan)
    assert _canonical_json(r1) == _canonical_json(r2)


# ---------------------------------------------------------------------------
# 27. Additional boundary tests.
# ---------------------------------------------------------------------------


def test_build_rejects_non_string_package_name() -> None:
    module = _load("p2d2a_nonstr_pkg")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["package_name"] = 123
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-string package_name accepted")


def test_build_rejects_non_string_path_value() -> None:
    module = _load("p2d2a_nonstr_path")
    with _visible_project() as (proj, run, request):
        bad = dict(request)
        bad["render_plan"] = 123
        try:
            module.build("flutter.visible_codegen.v1", bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-string path accepted")


def test_verify_plan_rejects_non_dict_plan() -> None:
    module = _load("p2d2a_vp_nondict")
    try:
        module.verify_plan("not a dict")
    except module.OperationPlanError:
        pass
    else:
        raise AssertionError("non-dict plan accepted")


def test_verify_plan_rejects_plan_with_no_steps() -> None:
    module = _load("p2d2a_vp_no_steps")
    with _visible_project() as (proj, run, request):
        plan = module.build("flutter.visible_codegen.v1", request)
        bad = copy.deepcopy(plan)
        bad["steps"] = "not a list"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-list steps accepted")


def test_build_visible_accepts_run_input_in_subdir() -> None:
    module = _load("p2d2a_subdir_input")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        (run / "inputs").mkdir(parents=True)
        _write_json(run / "inputs" / "render_plan.json", {})
        _write_json(run / "scene.json", {})
        _write_json(run / "classification.json", {})
        _write_json(run / "component_manifest.json", {})
        request = _make_visible_request(proj, run)
        request["render_plan"] = "inputs/render_plan.json"
        plan = module.build("flutter.visible_codegen.v1", request)
    assert plan["steps"][0]["argv"][3] == str(run / "inputs" / "render_plan.json")


def test_build_visible_constructs_colors_import_without_lib() -> None:
    """When colors_out does not start with lib/, the import is built as-is."""
    module = _load("p2d2a_no_lib_import")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "canvas").mkdir(parents=True)
        (proj / "lib" / "status").mkdir(parents=True)
        (proj / "tool").mkdir(parents=True)
        _write_json(run / "render_plan.json", {})
        _write_json(run / "scene.json", {})
        _write_json(run / "classification.json", {})
        _write_json(run / "component_manifest.json", {})
        request = _make_visible_request(proj, run)
        request["colors_out"] = "tool/colors.dart"
        request["colors_import_path"] = "tool/colors.dart"
        plan = module.build("flutter.visible_codegen.v1", request)
    argv = plan["steps"][0]["argv"]
    idx = argv.index("--colors-import")
    assert argv[idx + 1] == "package:my_app/tool/colors.dart"


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
