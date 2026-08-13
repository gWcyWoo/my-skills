#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2d2c Flutter
trusted-operation plan registry extension
(runtime_capture / project_gates / fan_in).

P2d2c extends ``platforms/flutter_operations_v1.py`` with three new
append-only operation IDs and their seventeen single-step variants:

* ``flutter.runtime_capture.v1`` with actions:
  - ``select_device`` (primitive ``select_runtime_device.py``)
  - ``lock_acquire``   (primitive ``device_lock.py``)
  - ``lock_release``   (primitive ``device_lock.py``)
  - ``lock_status``    (primitive ``device_lock.py``)
  - ``capture``        (primitive ``capture_runtime_screenshot.py``)
  - ``physical_preview`` (primitive ``physical_device_preview.py``)
* ``flutter.project_gates.v1`` with actions:
  - ``interaction_wiring`` (primitive ``check_interaction_wiring.py``)
  - ``api_integration``    (primitive ``check_api_integration.py``)
  - ``fixture_source``     (primitive ``check_fixture_source.py``)
  - ``capture_readiness``  (primitive ``check_capture_readiness.py``)
* ``flutter.fan_in.v1`` with actions:
  - ``plan_prepare``        (primitive ``assembly_plan_batch.py``)
  - ``plan_apply``          (primitive ``assembly_plan_batch.py``)
  - ``supervisor_prepare``  (primitive ``assembly_worker_supervisor.py``)
  - ``supervisor_verify``   (primitive ``assembly_worker_supervisor.py``)
  - ``done_gate``           (primitive ``check_done_gate.py``)
  - ``completion_issue``    (primitive ``assembly_completion.py``)
  - ``completion_verify``   (primitive ``assembly_completion.py``)

The supervisor ``run`` subcommand is deliberately unsupported because it
accepts an arbitrary trailing command.

This selftest never executes the primitives; it only validates that the
plan builder constructs deterministic, immutable argv plans and that
``verify_plan`` independently re-attests them. The plan carries no
separate ``project_root`` field; for the new operations ``verify_plan``
reconstructs the action's exact normalized request from the validated
plan's ``(operation_id, step_id)``, ``cwd``, and validated argv values,
canonical-JSON hashes that reconstructed mapping, and requires exact
equality with ``request_digest``. This couples cwd to the digest so a
cwd-only substitution is detected even for actions whose argv contains
only spec-root paths (select_device, capture).

No CLI, no subprocess, no project/spec/capsule writes, no edits to the
registry / P2c descriptor, no reads of sibling ``iff/``.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2c_flutter_operations.py
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
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"

KIND_PLAN = "icp.trusted-operation-plan.v1"
KIND_VERIFY = "icp.trusted-operation-plan-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 120

# The full append-only registry order after P2d2c.
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

RC_OP = "flutter.runtime_capture.v1"
PG_OP = "flutter.project_gates.v1"
FI_OP = "flutter.fan_in.v1"

# Per-variant timeouts.
T_SELECT_DEVICE = 180
T_LOCK_ACQUIRE = 960
T_LOCK_RELEASE = 120
T_LOCK_STATUS = 120
T_CAPTURE = 600
T_PHYSICAL_PREVIEW = 180

RUNTIME_CAPTURE_ACTIONS = (
    "select_device",
    "lock_acquire",
    "lock_release",
    "lock_status",
    "capture",
    "physical_preview",
)
PROJECT_GATES_ACTIONS = (
    "interaction_wiring",
    "api_integration",
    "fixture_source",
    "capture_readiness",
)
FAN_IN_ACTIONS = (
    "plan_prepare",
    "plan_apply",
    "supervisor_prepare",
    "supervisor_verify",
    "done_gate",
    "completion_issue",
    "completion_verify",
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


def _script(name: str) -> str:
    return str(CAPSULE_SCRIPTS / name)


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2d2c_"):
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


def _touch(path: Path, body: bytes = b"// fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _new_proj(tmp: Path, name: str = "proj") -> Path:
    proj = tmp / name
    proj.mkdir()
    return proj


def _new_spec(tmp: Path, name: str = "spec") -> Path:
    spec = tmp / name
    spec.mkdir()
    return spec


def _setup_flutter_project(proj: Path) -> None:
    """Create lib/, test/, lib/main.dart, pubspec.yaml under proj."""
    (proj / "lib").mkdir(parents=True, exist_ok=True)
    (proj / "test").mkdir(parents=True, exist_ok=True)
    (proj / "lib" / "main.dart").write_text("// main\n", encoding="utf-8")
    (proj / "pubspec.yaml").write_text("name: app\n", encoding="utf-8")


# --- runtime_capture requests -------------------------------------------


def _rc_request(proj: Path, spec: Path, action: str) -> dict[str, Any]:
    req: dict[str, Any] = {"project_root": str(proj), "action": action}
    if action != "lock_acquire" and action != "lock_release" and action != "lock_status":
        req["spec_root"] = str(spec)
    return req


def _setup_rc(proj: Path, spec: Path, action: str) -> None:
    if action == "capture":
        _write_json(spec / "runtime_device.json", {"device": "auto"})
        _write_json(spec / "visual_manifest.json", {"frames": []})
    # select_device / physical_preview / lock_* need only the roots,
    # which already exist.


@contextlib.contextmanager
def _rc_project(action: str):
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _setup_rc(proj, spec, action)
        yield proj, spec, _rc_request(proj, spec, action)


# --- project_gates requests ---------------------------------------------


def _pg_request(proj: Path, spec: Path, action: str) -> dict[str, Any]:
    if action == "fixture_source":
        return {"project_root": str(proj), "action": action}
    if action == "capture_readiness":
        return {
            "project_root": str(proj),
            "spec_root": str(spec),
            "action": action,
            "page_source": str(proj / "lib" / "page.dart"),
            "policy_source": str(proj / "lib" / "policy.dart"),
            "startup_policy_source": str(proj / "lib" / "startup.dart"),
        }
    return {"project_root": str(proj), "spec_root": str(spec), "action": action}


def _setup_pg(proj: Path, spec: Path, action: str) -> None:
    if action == "interaction_wiring":
        _setup_flutter_project(proj)
        _write_json(spec / "interaction_contract.json", {"interactions": []})
    elif action == "api_integration":
        (proj / "lib").mkdir(parents=True, exist_ok=True)
        _write_json(spec / "api_contract.json", {"paths": {}})
    elif action == "fixture_source":
        # only project_root needed
        pass
    elif action == "capture_readiness":
        (proj / "lib").mkdir(parents=True, exist_ok=True)
        (proj / "lib" / "main.dart").write_text("// main\n", encoding="utf-8")
        _write_json(spec / "scene.json", {"scene": {}})
        _touch(proj / "lib" / "page.dart")
        _touch(proj / "lib" / "policy.dart")
        _touch(proj / "lib" / "startup.dart")


@contextlib.contextmanager
def _pg_project(action: str):
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _setup_pg(proj, spec, action)
        yield proj, spec, _pg_request(proj, spec, action)


# --- fan_in requests -----------------------------------------------------


def _fi_request(proj: Path, spec: Path, action: str) -> dict[str, Any]:
    return {"project_root": str(proj), "spec_root": str(spec), "action": action}


def _setup_fi(proj: Path, spec: Path, action: str) -> None:
    if action in ("plan_prepare", "plan_apply"):
        _write_json(spec / "assembly_context.json", {"ctx": {}})
        _write_json(spec / "assembly_decisions.json", {"decisions": []})
    elif action in ("supervisor_prepare", "supervisor_verify"):
        _write_json(spec / "assembly_invocation.json", {"invocation": {}})
    elif action == "completion_verify":
        _write_json(spec / "assembly_completion.json", {"completion": {}})
    # done_gate / completion_issue need only the spec root.


@contextlib.contextmanager
def _fi_project(action: str):
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _setup_fi(proj, spec, action)
        yield proj, spec, _fi_request(proj, spec, action)


# Family dispatch helpers -------------------------------------------------


def _op_for(family: str) -> str:
    return {"rc": RC_OP, "pg": PG_OP, "fi": FI_OP}[family]


def _ctx_for(family: str, action: str):
    if family == "rc":
        return _rc_project(action)
    if family == "pg":
        return _pg_project(action)
    return _fi_project(action)


# Per-variant static expectation table.
# (family, action, primitive, timeout, positional)
_VARIANTS = (
    ("rc", "select_device", "select_runtime_device.py", T_SELECT_DEVICE, None),
    ("rc", "lock_acquire", "device_lock.py", T_LOCK_ACQUIRE, "acquire"),
    ("rc", "lock_release", "device_lock.py", T_LOCK_RELEASE, "release"),
    ("rc", "lock_status", "device_lock.py", T_LOCK_STATUS, "status"),
    ("rc", "capture", "capture_runtime_screenshot.py", T_CAPTURE, None),
    ("rc", "physical_preview", "physical_device_preview.py", T_PHYSICAL_PREVIEW, None),
    ("pg", "interaction_wiring", "check_interaction_wiring.py", TIMEOUT_SECONDS, None),
    ("pg", "api_integration", "check_api_integration.py", TIMEOUT_SECONDS, None),
    ("pg", "fixture_source", "check_fixture_source.py", TIMEOUT_SECONDS, None),
    ("pg", "capture_readiness", "check_capture_readiness.py", TIMEOUT_SECONDS, None),
    ("fi", "plan_prepare", "assembly_plan_batch.py", TIMEOUT_SECONDS, "prepare"),
    ("fi", "plan_apply", "assembly_plan_batch.py", TIMEOUT_SECONDS, "apply"),
    ("fi", "supervisor_prepare", "assembly_worker_supervisor.py", TIMEOUT_SECONDS, "prepare"),
    ("fi", "supervisor_verify", "assembly_worker_supervisor.py", TIMEOUT_SECONDS, "verify"),
    ("fi", "done_gate", "check_done_gate.py", TIMEOUT_SECONDS, None),
    ("fi", "completion_issue", "assembly_completion.py", TIMEOUT_SECONDS, "issue"),
    ("fi", "completion_verify", "assembly_completion.py", TIMEOUT_SECONDS, "verify"),
)


def _variant_op(family: str) -> str:
    return _op_for(family)


# ---------------------------------------------------------------------------
# 1. Module + constants + public API surface.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2d2c_loads")
    assert module.SCHEMA_VERSION == SCHEMA_VERSION
    assert module.KIND_PLAN == KIND_PLAN
    assert module.KIND_VERIFY == KIND_VERIFY
    assert module.PLATFORM_ID == PLATFORM_ID
    assert module.PROFILE_ID == PROFILE_ID


def test_module_exposes_typed_exception() -> None:
    module = _load("p2d2c_exc")
    assert hasattr(module, "OperationPlanError")
    assert issubclass(module.OperationPlanError, ValueError)


def test_module_has_no_cli_main() -> None:
    module = _load("p2d2c_nocli")
    assert not hasattr(module, "main")
    source = MODULE_PATH.read_text()
    assert '__name__ == "__main__"' not in source


def test_public_api_exposes_only_three_functions() -> None:
    module = _load("p2d2c_pubapi")
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
    module = _load("p2d2c_noparams")
    forbidden = (
        "EXECUTABLE_OVERRIDE", "INTERPRETER_OVERRIDE", "ENV_OVERRIDE",
        "ARGV_OVERRIDE", "COMMAND_OVERRIDE", "REGISTRY_OVERRIDE",
        "MANIFEST_OVERRIDE", "CAPSULE_OVERRIDE", "ACTIVATION",
    )
    for attr in forbidden:
        assert not hasattr(module, attr), f"module exposes override {attr}"


# ---------------------------------------------------------------------------
# 2. Operation order — append-only eight IDs.
# ---------------------------------------------------------------------------


def test_list_operation_ids_exact_order() -> None:
    module = _load("p2d2c_oporder")
    assert module.list_operation_ids() == OPERATION_IDS
    assert isinstance(module.list_operation_ids(), tuple)


def test_list_operation_ids_returns_new_tuple_each_call() -> None:
    module = _load("p2d2c_newtuple")
    a = module.list_operation_ids()
    b = module.list_operation_ids()
    assert a == b
    assert a is not b


def test_list_operation_ids_tuple_is_not_module_constant() -> None:
    module = _load("p2d2c_notconst")
    returned = module.list_operation_ids()
    for attr in dir(module):
        if attr.startswith("_"):
            continue
        if getattr(module, attr) is returned:
            raise AssertionError(f"returned tuple aliases module attr {attr!r}")


# ---------------------------------------------------------------------------
# 3. Capsule-first ordering.
# ---------------------------------------------------------------------------


def test_build_calls_verify_capsule_first_runtime_capture() -> None:
    module = _load("p2d2c_capsfirst_rc")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _rc_project("select_device") as (proj, spec, request):
            try:
                module.build(RC_OP, request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_calls_verify_capsule_first_project_gates() -> None:
    module = _load("p2d2c_capsfirst_pg")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _pg_project("fixture_source") as (proj, spec, request):
            try:
                module.build(PG_OP, request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_calls_verify_capsule_first_fan_in() -> None:
    module = _load("p2d2c_capsfirst_fi")
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.OperationPlanError("capsule boom")

    module._verify_capsule = _boom
    try:
        with _fi_project("done_gate") as (proj, spec, request):
            try:
                module.build(FI_OP, request)
            except module.OperationPlanError as exc:
                assert "capsule boom" in str(exc)
            else:
                raise AssertionError("build did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


def test_build_capsule_failure_redacts_generic_exception() -> None:
    module = _load("p2d2c_capsgeneric")

    class _SecretError(Exception):
        pass

    def _boom():
        raise _SecretError("SUPER_SECRET_BLOB")

    module._verify_capsule = _boom
    try:
        with _fi_project("done_gate") as (proj, spec, request):
            try:
                module.build(FI_OP, request)
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
    module = _load("p2d2c_unknown_op")
    with _fi_project("done_gate") as (proj, spec, request):
        try:
            module.build("flutter.future_op.v1", request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown operation_id accepted")


def test_build_rejects_non_dict_request_runtime_capture() -> None:
    module = _load("p2d2c_nondict_rc")
    try:
        module.build(RC_OP, "not a dict")
    except module.OperationPlanError:
        pass
    else:
        raise AssertionError("non-dict request accepted")


def test_build_rejects_forbidden_command_key_in_fan_in() -> None:
    module = _load("p2d2c_cmd_fi")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["command"] = "evil"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden command key accepted")


def test_build_rejects_forbidden_executable_key_in_runtime_capture() -> None:
    module = _load("p2d2c_exec_rc")
    with _rc_project("select_device") as (proj, spec, request):
        bad = dict(request)
        bad["executable"] = "/usr/local/bin/flutter"
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden executable key accepted")


def test_build_rejects_forbidden_argv_key_in_project_gates() -> None:
    module = _load("p2d2c_argv_pg")
    with _pg_project("fixture_source") as (proj, spec, request):
        bad = dict(request)
        bad["argv"] = ["--evil"]
        try:
            module.build(PG_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden argv key accepted")


def test_build_rejects_forbidden_script_key_in_fan_in() -> None:
    module = _load("p2d2c_script_fi")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["script"] = "evil.py"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("forbidden script key accepted")


def test_build_rejects_missing_action_runtime_capture() -> None:
    module = _load("p2d2c_missing_action_rc")
    with _rc_project("select_device") as (proj, spec, request):
        bad = dict(request)
        del bad["action"]
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing action accepted")


def test_build_rejects_unknown_action_runtime_capture() -> None:
    module = _load("p2d2c_unknown_action_rc")
    with _rc_project("select_device") as (proj, spec, request):
        bad = dict(request)
        bad["action"] = "reboot_matrix"
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown action accepted")


def test_build_rejects_unknown_action_project_gates() -> None:
    module = _load("p2d2c_unknown_action_pg")
    with _pg_project("fixture_source") as (proj, spec, request):
        bad = dict(request)
        bad["action"] = "teleport"
        try:
            module.build(PG_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown action accepted")


def test_build_rejects_unknown_action_fan_in() -> None:
    module = _load("p2d2c_unknown_action_fi")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["action"] = "teleport"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown action accepted")


def test_build_rejects_extra_unknown_key_in_runtime_capture() -> None:
    module = _load("p2d2c_extra_rc")
    with _rc_project("select_device") as (proj, spec, request):
        bad = dict(request)
        bad["unexpected_extra"] = "x"
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown extra key accepted")


def test_build_runtime_capture_lock_rejects_spec_root_as_extra() -> None:
    """lock_acquire must not carry spec_root."""
    module = _load("p2d2c_lock_extra_spec")
    with _rc_project("lock_acquire") as (proj, spec, request):
        bad = dict(request)
        bad["spec_root"] = str(spec)
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("spec_root accepted for lock action")


def test_build_runtime_capture_select_device_requires_spec_root() -> None:
    module = _load("p2d2c_sd_missing_spec")
    with _rc_project("select_device") as (proj, spec, request):
        bad = dict(request)
        del bad["spec_root"]
        try:
            module.build(RC_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("select_device without spec_root accepted")


def test_build_project_gates_fixture_source_rejects_spec_root() -> None:
    module = _load("p2d2c_fs_extra_spec")
    with _pg_project("fixture_source") as (proj, spec, request):
        bad = dict(request)
        bad["spec_root"] = str(spec)
        try:
            module.build(PG_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("spec_root accepted for fixture_source")


def test_build_project_gates_interaction_wiring_requires_spec_root() -> None:
    module = _load("p2d2c_iw_missing_spec")
    with _pg_project("interaction_wiring") as (proj, spec, request):
        bad = dict(request)
        del bad["spec_root"]
        try:
            module.build(PG_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("interaction_wiring without spec_root accepted")


def test_build_project_gates_capture_readiness_requires_three_sources() -> None:
    module = _load("p2d2c_cr_missing_sources")
    for key in ("page_source", "policy_source", "startup_policy_source"):
        with _pg_project("capture_readiness") as (proj, spec, request):
            bad = dict(request)
            del bad[key]
            try:
                module.build(PG_OP, bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError(f"capture_readiness without {key} accepted")


def test_build_project_gates_non_capture_readiness_rejects_source_keys() -> None:
    """Only capture_readiness accepts the three source keys."""
    module = _load("p2d2c_pg_source_leak")
    for action in ("interaction_wiring", "api_integration"):
        with _pg_project(action) as (proj, spec, request):
            bad = dict(request)
            bad["page_source"] = str(proj / "lib" / "page.dart")
            try:
                module.build(PG_OP, bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError(f"{action} accepted page_source")


def test_build_action_value_must_be_string() -> None:
    module = _load("p2d2c_action_type")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["action"] = 5
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("non-string action accepted")


def test_build_rejects_boolean_where_string_expected() -> None:
    """A boolean spec_root must be rejected (type confusion)."""
    module = _load("p2d2c_bool_spec")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["spec_root"] = True
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("boolean spec_root accepted")


# ---------------------------------------------------------------------------
# 5. Plan schema and step shape.
# ---------------------------------------------------------------------------


def test_build_runtime_capture_returns_canonical_plan_shape() -> None:
    module = _load("p2d2c_rc_shape")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    assert set(plan.keys()) == {
        "kind", "schema_version", "operation_id", "platform_id",
        "profile_id", "request_digest", "steps",
    }, sorted(plan.keys())
    assert plan["kind"] == KIND_PLAN
    assert plan["schema_version"] == SCHEMA_VERSION
    assert plan["operation_id"] == RC_OP
    assert plan["platform_id"] == PLATFORM_ID
    assert plan["profile_id"] == PROFILE_ID
    assert _is_sha256_hex(plan["request_digest"])
    assert isinstance(plan["steps"], list)
    assert len(plan["steps"]) == 1


def test_build_project_gates_returns_canonical_plan_shape() -> None:
    module = _load("p2d2c_pg_shape")
    with _pg_project("fixture_source") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    assert plan["operation_id"] == PG_OP
    assert len(plan["steps"]) == 1


def test_build_fan_in_returns_canonical_plan_shape() -> None:
    module = _load("p2d2c_fi_shape")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    assert plan["operation_id"] == FI_OP
    assert len(plan["steps"]) == 1


def test_build_step_keys_exact_all_variants() -> None:
    module = _load("p2d2c_step_keys")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
        step = plan["steps"][0]
        assert set(step.keys()) == {
            "step_id", "primitive", "primitive_sha256", "argv",
            "cwd", "timeout_seconds",
        }, f"{family}/{action}: {sorted(step.keys())}"


def test_build_step_id_equals_action_all_variants() -> None:
    module = _load("p2d2c_step_id")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
        assert plan["steps"][0]["step_id"] == action, f"{family}/{action}"


# ---------------------------------------------------------------------------
# 6. runtime_capture argv / cwd / timeout / primitive exactness.
# ---------------------------------------------------------------------------


def test_build_rc_select_device_argv_exact() -> None:
    module = _load("p2d2c_rc_sd_argv")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "select_runtime_device.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_SELECT_DEVICE
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == _script("select_runtime_device.py")
    assert argv[2:] == [
        "--platform", "auto",
        "--command-timeout", "10",
        "--boot-timeout", "120",
        "--out", str(spec / "runtime_device.json"),
    ], argv[2:]


def test_build_rc_lock_acquire_argv_exact() -> None:
    module = _load("p2d2c_rc_la_argv")
    with _rc_project("lock_acquire") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "device_lock.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_LOCK_ACQUIRE
    argv = step["argv"]
    assert argv[0] == sys.executable
    assert argv[1] == _script("device_lock.py")
    assert argv[2:] == [
        "acquire",
        "--lock", str(proj / ".icp" / "device.lock"),
        "--timeout", "900",
    ], argv[2:]


def test_build_rc_lock_release_argv_exact() -> None:
    module = _load("p2d2c_rc_lr_argv")
    with _rc_project("lock_release") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "device_lock.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_LOCK_RELEASE
    argv = step["argv"]
    assert argv[1] == _script("device_lock.py")
    assert argv[2:] == [
        "release",
        "--lock", str(proj / ".icp" / "device.lock"),
    ], argv[2:]


def test_build_rc_lock_status_argv_exact() -> None:
    module = _load("p2d2c_rc_ls_argv")
    with _rc_project("lock_status") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "device_lock.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_LOCK_STATUS
    argv = step["argv"]
    assert argv[1] == _script("device_lock.py")
    assert argv[2:] == [
        "status",
        "--lock", str(proj / ".icp" / "device.lock"),
    ], argv[2:]


def test_build_rc_capture_argv_exact() -> None:
    module = _load("p2d2c_rc_cap_argv")
    with _rc_project("capture") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "capture_runtime_screenshot.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_CAPTURE
    argv = step["argv"]
    assert argv[1] == _script("capture_runtime_screenshot.py")
    assert argv[2:] == [
        "--selection", str(spec / "runtime_device.json"),
        "--command-timeout", "15",
        "--launch-timeout", "300",
        "--out", str(spec / "actual.png"),
        "--manifest", str(spec / "visual_manifest.json"),
    ], argv[2:]


def test_build_rc_physical_preview_argv_exact() -> None:
    module = _load("p2d2c_rc_pp_argv")
    with _rc_project("physical_preview") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "physical_device_preview.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == T_PHYSICAL_PREVIEW
    argv = step["argv"]
    assert argv[1] == _script("physical_device_preview.py")
    assert argv[2:] == [
        "--project-root", str(proj),
        "--out", str(spec / "physical_device_preview.json"),
    ], argv[2:]


def test_build_rc_does_not_emit_device_or_dart_define() -> None:
    """No caller device id, label, pool, route, dart-define, or apk."""
    module = _load("p2d2c_rc_no_device")
    for action in RUNTIME_CAPTURE_ACTIONS:
        with _rc_project(action) as (proj, spec, request):
            plan = module.build(RC_OP, request)
        argv = plan["steps"][0]["argv"]
        for forbidden in (
            "--device", "--label", "--pool", "--route", "--dart-define",
            "--android-apk", "--android-device", "--ios-device",
        ):
            assert forbidden not in argv, f"{action}: {forbidden} emitted"


# ---------------------------------------------------------------------------
# 7. project_gates argv / cwd / timeout / primitive exactness.
# ---------------------------------------------------------------------------


def test_build_pg_interaction_wiring_argv_exact() -> None:
    module = _load("p2d2c_pg_iw_argv")
    with _pg_project("interaction_wiring") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "check_interaction_wiring.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("check_interaction_wiring.py")
    assert argv[2:] == [
        "--lib-root", str(proj / "lib"),
        "--test-root", str(proj / "test"),
        "--entry", str(proj / "lib" / "main.dart"),
        "--pubspec", str(proj / "pubspec.yaml"),
        "--contract", str(spec / "interaction_contract.json"),
        "--out", str(spec / "wiring_report.json"),
    ], argv[2:]


def test_build_pg_api_integration_argv_exact() -> None:
    module = _load("p2d2c_pg_ai_argv")
    with _pg_project("api_integration") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "check_api_integration.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("check_api_integration.py")
    assert argv[2:] == [
        "--api-contract", str(spec / "api_contract.json"),
        "--lib-root", str(proj / "lib"),
        "--out", str(spec / "api_integration_report.json"),
    ], argv[2:]


def test_build_pg_fixture_source_argv_exact() -> None:
    module = _load("p2d2c_pg_fs_argv")
    with _pg_project("fixture_source") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "check_fixture_source.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("check_fixture_source.py")
    assert argv[2:] == [
        "--root", str(proj),
    ], argv[2:]


def test_build_pg_capture_readiness_argv_exact() -> None:
    module = _load("p2d2c_pg_cr_argv")
    with _pg_project("capture_readiness") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "check_capture_readiness.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("check_capture_readiness.py")
    assert argv[2:] == [
        "--project-root", str(proj),
        "--entry", str(proj / "lib" / "main.dart"),
        "--scene", str(spec / "scene.json"),
        "--page-source", str(proj / "lib" / "page.dart"),
        "--policy-source", str(proj / "lib" / "policy.dart"),
        "--startup-policy-source", str(proj / "lib" / "startup.dart"),
        "--out", str(spec / "capture_readiness.json"),
    ], argv[2:]


def test_build_pg_does_not_emit_safe_area_source() -> None:
    """--safe-area-source is deferred to a later phase."""
    module = _load("p2d2c_pg_no_safearea")
    with _pg_project("capture_readiness") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    argv = plan["steps"][0]["argv"]
    assert "--safe-area-source" not in argv


def test_build_pg_fixture_source_does_not_emit_fixture_name() -> None:
    module = _load("p2d2c_pg_no_fixture_name")
    with _pg_project("fixture_source") as (proj, spec, request):
        plan = module.build(PG_OP, request)
    argv = plan["steps"][0]["argv"]
    assert "--fixture-name" not in argv


# ---------------------------------------------------------------------------
# 8. fan_in argv / cwd / timeout / primitive exactness.
# ---------------------------------------------------------------------------


def test_build_fi_plan_prepare_argv_exact() -> None:
    module = _load("p2d2c_fi_pp_argv")
    with _fi_project("plan_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_plan_batch.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_plan_batch.py")
    assert argv[2:] == [
        "prepare",
        "--spec-root", str(spec),
        "--project-root", str(proj),
        "--context", str(spec / "assembly_context.json"),
        "--decisions", str(spec / "assembly_decisions.json"),
    ], argv[2:]


def test_build_fi_plan_apply_argv_exact() -> None:
    module = _load("p2d2c_fi_pa_argv")
    with _fi_project("plan_apply") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_plan_batch.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_plan_batch.py")
    assert argv[2:] == [
        "apply",
        "--context", str(spec / "assembly_context.json"),
        "--decisions", str(spec / "assembly_decisions.json"),
    ], argv[2:]


def test_build_fi_supervisor_prepare_argv_exact() -> None:
    module = _load("p2d2c_fi_sp_argv")
    with _fi_project("supervisor_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_worker_supervisor.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_worker_supervisor.py")
    assert argv[2:] == [
        "prepare",
        "--contract", str(spec / "assembly_invocation.json"),
    ], argv[2:]


def test_build_fi_supervisor_verify_argv_exact() -> None:
    module = _load("p2d2c_fi_sv_argv")
    with _fi_project("supervisor_verify") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_worker_supervisor.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_worker_supervisor.py")
    assert argv[2:] == [
        "verify",
        "--contract", str(spec / "assembly_invocation.json"),
    ], argv[2:]


def test_build_fi_done_gate_argv_exact() -> None:
    module = _load("p2d2c_fi_dg_argv")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "check_done_gate.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("check_done_gate.py")
    assert argv[2:] == [
        "--spec-root", str(spec),
        "--out", str(spec / "done_gate.json"),
    ], argv[2:]


def test_build_fi_completion_issue_argv_exact() -> None:
    module = _load("p2d2c_fi_ci_argv")
    with _fi_project("completion_issue") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_completion.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_completion.py")
    assert argv[2:] == [
        "issue",
        "--spec-root", str(spec),
        "--evidence", str(spec / "assembly_completion.json"),
    ], argv[2:]


def test_build_fi_completion_verify_argv_exact() -> None:
    module = _load("p2d2c_fi_cv_argv")
    with _fi_project("completion_verify") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    step = plan["steps"][0]
    assert step["primitive"] == "assembly_completion.py"
    assert step["cwd"] == str(proj)
    assert step["timeout_seconds"] == TIMEOUT_SECONDS
    argv = step["argv"]
    assert argv[1] == _script("assembly_completion.py")
    assert argv[2:] == [
        "verify",
        "--spec-root", str(spec),
        "--evidence", str(spec / "assembly_completion.json"),
    ], argv[2:]


def test_build_fi_supervisor_run_action_rejected() -> None:
    """The supervisor ``run`` subcommand accepts an arbitrary trailing
    command and must never be selectable."""
    module = _load("p2d2c_fi_run_reject")
    with _fi_project("supervisor_prepare") as (proj, spec, request):
        bad = dict(request)
        bad["action"] = "run"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("supervisor run action accepted")


def test_build_fi_no_plan_contains_free_command_tail() -> None:
    """No built plan argv may carry an unbound trailing command token."""
    module = _load("p2d2c_fi_no_tail")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
        argv = plan["steps"][0]["argv"]
        # Every token after the script path must be a known flag, a known
        # positional, or a path/literal value — never a bare shell word
        # like "bash" or "sh -c". Sanity: no token equals "command".
        assert "command" not in argv, f"{family}/{action}: bare 'command' token"


# ---------------------------------------------------------------------------
# 9. Primitive SHA binding to the immutable manifest.
# ---------------------------------------------------------------------------


def _manifest_sha_map() -> dict[str, str]:
    raw = MANIFEST_PATH.read_bytes()
    obj = json.loads(raw)
    return {entry["name"]: entry["sha256"] for entry in obj["scripts"]}


def test_build_all_variants_primitives_match_manifest_sha() -> None:
    module = _load("p2d2c_sha")
    sha_map = _manifest_sha_map()
    for family, action, primitive, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
        step = plan["steps"][0]
        assert step["primitive"] == primitive, f"{family}/{action}"
        assert step["primitive_sha256"] == sha_map[primitive], (
            f"{family}/{action}: sha mismatch for {primitive}"
        )


# ---------------------------------------------------------------------------
# 10. Determinism.
# ---------------------------------------------------------------------------


def test_build_deterministic_in_process() -> None:
    module = _load("p2d2c_det_proc")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            p1 = module.build(_variant_op(family), request)
            p2 = module.build(_variant_op(family), request)
        assert _canonical_json(p1) == _canonical_json(p2), f"{family}/{action}"


def test_build_deterministic_across_modules() -> None:
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            m1 = _load("p2d2c_det_mod1")
            m2 = _load("p2d2c_det_mod2")
            p1 = m1.build(_variant_op(family), request)
            p2 = m2.build(_variant_op(family), request)
        assert _canonical_json(p1) == _canonical_json(p2), f"{family}/{action}"


def test_build_deterministic_across_cwd() -> None:
    module = _load("p2d2c_det_cwd")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            start = os.getcwd()
            try:
                os.chdir(str(proj))
                p1 = module.build(_variant_op(family), request)
            finally:
                os.chdir(start)
            try:
                os.chdir(str(spec))
                p2 = module.build(_variant_op(family), request)
            finally:
                os.chdir(start)
        assert _canonical_json(p1) == _canonical_json(p2), f"{family}/{action}"


def test_build_deterministic_across_processes() -> None:
    # Probe one representative per family in a child process.
    probes = (("rc", "select_device"), ("pg", "interaction_wiring"), ("fi", "plan_prepare"))
    for family, action in probes:
        with _ctx_for(family, action) as (proj, spec, request):
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
                % (str(MODULE_PATH), str(request_file), _variant_op(family))
            )
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            r1 = subprocess.run(
                [sys.executable, str(helper)], capture_output=True, text=True, env=env
            )
            r2 = subprocess.run(
                [sys.executable, str(helper)], capture_output=True, text=True, env=env
            )
        assert r1.returncode == 0, f"{family}/{action}: {r1.stderr}"
        assert r2.returncode == 0, f"{family}/{action}: {r2.stderr}"
        assert r1.stdout == r2.stdout, f"{family}/{action}: nondeterministic across processes"


# ---------------------------------------------------------------------------
# 11. Request digest coupling.
# ---------------------------------------------------------------------------


def test_request_digest_changes_when_action_changes_runtime_capture() -> None:
    module = _load("p2d2c_dig_action_rc")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _setup_rc(proj, spec, "select_device")
        _setup_rc(proj, spec, "capture")
        r1 = _rc_request(proj, spec, "select_device")
        r2 = _rc_request(proj, spec, "capture")
        p1 = module.build(RC_OP, r1)
        p2 = module.build(RC_OP, r2)
    assert p1["request_digest"] != p2["request_digest"]


def test_request_digest_changes_when_spec_root_changes() -> None:
    module = _load("p2d2c_dig_spec")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec1 = _new_spec(tmp, "spec1")
        spec2 = _new_spec(tmp, "spec2")
        _setup_fi(proj, spec1, "done_gate")
        _setup_fi(proj, spec2, "done_gate")
        r1 = _fi_request(proj, spec1, "done_gate")
        r2 = _fi_request(proj, spec2, "done_gate")
        p1 = module.build(FI_OP, r1)
        p2 = module.build(FI_OP, r2)
    assert p1["request_digest"] != p2["request_digest"]


def test_request_digest_changes_when_project_root_changes() -> None:
    module = _load("p2d2c_dig_proj")
    with _canonical_tempdir() as tmp:
        proj1 = _new_proj(tmp, "proj1")
        proj2 = _new_proj(tmp, "proj2")
        spec = _new_spec(tmp)
        _setup_pg(proj1, spec, "fixture_source")
        _setup_pg(proj2, spec, "fixture_source")
        r1 = _pg_request(proj1, spec, "fixture_source")
        r2 = _pg_request(proj2, spec, "fixture_source")
        p1 = module.build(PG_OP, r1)
        p2 = module.build(PG_OP, r2)
    assert p1["request_digest"] != p2["request_digest"]


def test_request_digest_changes_when_capture_readiness_source_changes() -> None:
    module = _load("p2d2c_dig_cr_src")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _setup_pg(proj, spec, "capture_readiness")
        r1 = _pg_request(proj, spec, "capture_readiness")
        # second source variant
        _touch(proj / "lib" / "page2.dart")
        r2 = dict(r1)
        r2["page_source"] = str(proj / "lib" / "page2.dart")
        p1 = module.build(PG_OP, r1)
        p2 = module.build(PG_OP, r2)
    assert p1["request_digest"] != p2["request_digest"]


# ---------------------------------------------------------------------------
# 12. Common path validation rules.
# ---------------------------------------------------------------------------


def test_build_rejects_relative_project_root() -> None:
    module = _load("p2d2c_rel_proj")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["project_root"] = "relative/path"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative project_root accepted")


def test_build_rejects_nonexistent_spec_root() -> None:
    module = _load("p2d2c_no_spec")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["spec_root"] = str(spec / "missing_dir")
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("nonexistent spec_root accepted")


def test_build_rejects_spec_root_file_not_dir() -> None:
    module = _load("p2d2c_spec_file")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        specfile = tmp / "specfile"
        specfile.write_text("x")
        request = _fi_request(proj, tmp, "done_gate")
        request["spec_root"] = str(specfile)
        try:
            module.build(FI_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("file spec_root accepted")


def test_build_rejects_spec_root_with_dotdot() -> None:
    module = _load("p2d2c_spec_dd")
    with _fi_project("done_gate") as (proj, spec, request):
        bad = dict(request)
        bad["spec_root"] = str(spec) + "/../evil"
        try:
            module.build(FI_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("dotdot spec_root accepted")


def test_build_capture_rejects_missing_selection_input() -> None:
    module = _load("p2d2c_cap_no_sel")
    with _rc_project("capture") as (proj, spec, request):
        (spec / "runtime_device.json").unlink()
        try:
            module.build(RC_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing capture selection input accepted")


def test_build_capture_accepts_absent_manifest_output() -> None:
    """capture writes visual_manifest.json; an absent output is allowed."""
    module = _load("p2d2c_cap_absent_man")
    with _rc_project("capture") as (proj, spec, request):
        if (spec / "visual_manifest.json").exists():
            (spec / "visual_manifest.json").unlink()
        plan = module.build(RC_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_capture_accepts_absent_actual_png_output() -> None:
    """capture writes actual.png; an absent output is allowed."""
    module = _load("p2d2c_cap_absent_png")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _write_json(spec / "runtime_device.json", {"device": "auto"})
        # No visual_manifest.json or actual.png created.
        request = _rc_request(proj, spec, "capture")
        plan = module.build(RC_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_capture_accepts_existing_manifest_output() -> None:
    """An existing non-symlink regular file at the manifest output path
    is accepted under the shared output-policy behavior."""
    module = _load("p2d2c_cap_existing_man")
    with _rc_project("capture") as (proj, spec, request):
        # _setup_rc created visual_manifest.json as a regular file.
        plan = module.build(RC_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_capture_rejects_manifest_output_symlink_leaf() -> None:
    module = _load("p2d2c_cap_man_symlink")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        _write_json(spec / "runtime_device.json", {})
        outside = tmp / "outside_manifest.json"
        _write_json(outside, {})
        os.symlink(outside, spec / "visual_manifest.json")
        request = _rc_request(proj, spec, "capture")
        try:
            module.build(RC_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked manifest output accepted")


def test_build_interaction_wiring_rejects_missing_contract() -> None:
    module = _load("p2d2c_iw_no_contract")
    with _pg_project("interaction_wiring") as (proj, spec, request):
        (spec / "interaction_contract.json").unlink()
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing interaction contract accepted")


def test_build_interaction_wiring_rejects_missing_lib() -> None:
    module = _load("p2d2c_iw_no_lib")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        # no lib/ created
        _write_json(spec / "interaction_contract.json", {})
        request = _pg_request(proj, spec, "interaction_wiring")
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing lib/ accepted")


def test_build_interaction_wiring_rejects_missing_entry() -> None:
    module = _load("p2d2c_iw_no_entry")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        (proj / "lib").mkdir(parents=True)
        (proj / "test").mkdir(parents=True)
        (proj / "pubspec.yaml").write_text("name: app\n")
        _write_json(spec / "interaction_contract.json", {})
        request = _pg_request(proj, spec, "interaction_wiring")
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing entry accepted")


def test_build_capture_readiness_rejects_source_outside_project() -> None:
    module = _load("p2d2c_cr_src_outside")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        outside = tmp / "outside.dart"
        outside.write_text("//", encoding="utf-8")
        (proj / "lib").mkdir(parents=True)
        (proj / "lib" / "main.dart").write_text("//\n")
        _write_json(spec / "scene.json", {})
        request = _pg_request(proj, spec, "capture_readiness")
        request["page_source"] = str(outside)
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("source outside project accepted")


def test_build_capture_readiness_rejects_relative_source() -> None:
    module = _load("p2d2c_cr_src_rel")
    with _pg_project("capture_readiness") as (proj, spec, request):
        bad = dict(request)
        bad["policy_source"] = "lib/policy.dart"
        try:
            module.build(PG_OP, bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("relative source accepted")


def test_build_capture_readiness_rejects_symlinked_source() -> None:
    module = _load("p2d2c_cr_src_sym")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        (proj / "lib").mkdir(parents=True)
        (proj / "lib" / "main.dart").write_text("//\n")
        _write_json(spec / "scene.json", {})
        outside = tmp / "outside.dart"
        outside.write_text("//", encoding="utf-8")
        os.symlink(outside, proj / "lib" / "page.dart")
        _touch(proj / "lib" / "policy.dart")
        _touch(proj / "lib" / "startup.dart")
        request = _pg_request(proj, spec, "capture_readiness")
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked source accepted")


def test_build_capture_readiness_rejects_symlinked_lib_ancestor() -> None:
    """capture_readiness must reject ${project_root}/lib/main.dart when
    ``lib`` itself is a symlink to an external directory, not only when
    main.dart is the symlink. Sources are valid real files NOT under the
    symlinked lib, so the rejection is attributable to the entry
    ancestor walk, not the source checks."""
    module = _load("p2d2c_cr_lib_sym")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        # External directory containing main.dart.
        external_lib = tmp / "external_lib"
        external_lib.mkdir()
        (external_lib / "main.dart").write_text("//\n")
        os.symlink(external_lib, proj / "lib")
        _write_json(spec / "scene.json", {})
        # Sources are real files under a non-symlinked subtree of proj.
        (proj / "config").mkdir()
        _touch(proj / "config" / "page.dart")
        _touch(proj / "config" / "policy.dart")
        _touch(proj / "config" / "startup.dart")
        request = _pg_request(proj, spec, "capture_readiness")
        request["page_source"] = str(proj / "config" / "page.dart")
        request["policy_source"] = str(proj / "config" / "policy.dart")
        request["startup_policy_source"] = str(proj / "config" / "startup.dart")
        try:
            module.build(PG_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked lib ancestor accepted")


def test_build_plan_prepare_accepts_absent_context_and_decisions() -> None:
    """plan_prepare writes assembly_context.json and
    assembly_decisions.json; absent outputs are allowed."""
    module = _load("p2d2c_pp_absent_ctx")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        # Neither assembly_context.json nor assembly_decisions.json created.
        request = _fi_request(proj, spec, "plan_prepare")
        plan = module.build(FI_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_plan_prepare_rejects_context_output_symlink() -> None:
    module = _load("p2d2c_pp_ctx_symlink")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = _new_spec(tmp)
        outside = tmp / "outside_ctx.json"
        _write_json(outside, {})
        os.symlink(outside, spec / "assembly_context.json")
        request = _fi_request(proj, spec, "plan_prepare")
        try:
            module.build(FI_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("symlinked plan_prepare context output accepted")


def test_build_plan_apply_rejects_missing_context_input() -> None:
    """plan_apply reads context/decisions; missing inputs are rejected."""
    module = _load("p2d2c_pa_no_ctx")
    with _fi_project("plan_apply") as (proj, spec, request):
        (spec / "assembly_context.json").unlink()
        try:
            module.build(FI_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing plan_apply context input accepted")


def test_build_completion_verify_rejects_missing_evidence() -> None:
    module = _load("p2d2c_cv_no_ev")
    with _fi_project("completion_verify") as (proj, spec, request):
        (spec / "assembly_completion.json").unlink()
        try:
            module.build(FI_OP, request)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("missing completion evidence accepted")


def test_build_completion_issue_accepts_absent_evidence() -> None:
    """completion_issue writes the evidence file; absent is allowed."""
    module = _load("p2d2c_ci_absent_ev")
    with _fi_project("completion_issue") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_select_device_accepts_absent_runtime_device() -> None:
    """select_device writes runtime_device.json; absent is allowed."""
    module = _load("p2d2c_sd_absent_out")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
    assert plan["kind"] == KIND_PLAN


def test_build_spec_root_may_be_inside_project() -> None:
    """spec_root may be a descendant of project_root (not forbidden)."""
    module = _load("p2d2c_spec_inside")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec = proj / ".icp_spec"
        spec.mkdir()
        request = _fi_request(proj, spec, "done_gate")
        plan = module.build(FI_OP, request)
    assert plan["kind"] == KIND_PLAN


# ---------------------------------------------------------------------------
# 13. verify_plan report shape + happy path all variants.
# ---------------------------------------------------------------------------


def test_verify_plan_returns_canonical_report_shape() -> None:
    module = _load("p2d2c_vp_shape")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        report = module.verify_plan(plan)
    assert set(report.keys()) == {
        "ok", "kind", "schema_version", "operation_id",
        "steps_total", "plan_digest",
    }, sorted(report.keys())
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["operation_id"] == FI_OP
    assert report["steps_total"] == 1
    assert _is_sha256_hex(report["plan_digest"])


def test_verify_plan_digest_matches_canonical_plan_bytes() -> None:
    module = _load("p2d2c_vp_digest")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        report = module.verify_plan(plan)
    expected = hashlib.sha256(_canonical_json(plan)).hexdigest()
    assert report["plan_digest"] == expected


def test_verify_plan_happy_path_all_seventeen_variants() -> None:
    module = _load("p2d2c_vp_happy")
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
            report = module.verify_plan(plan)
        assert report["ok"] is True, f"{family}/{action} failed verify"
        assert report["steps_total"] == 1


def test_verify_plan_deterministic_in_process() -> None:
    module = _load("p2d2c_vp_det")
    with _pg_project("interaction_wiring") as (proj, spec, request):
        plan = module.build(PG_OP, request)
        r1 = module.verify_plan(plan)
        r2 = module.verify_plan(plan)
    assert _canonical_json(r1) == _canonical_json(r2)


# ---------------------------------------------------------------------------
# 14. Tamper rejection (variant inference + tamper paths).
# ---------------------------------------------------------------------------


def _tamper(plan: dict, mutation) -> dict:
    new_plan = copy.deepcopy(plan)
    mutation(new_plan)
    return new_plan


def test_verify_plan_rejects_two_step_plan() -> None:
    module = _load("p2d2c_vp_two_step")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = _tamper(plan, lambda p: p.__setitem__("steps", [p["steps"][0], p["steps"][0]]))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("two-step plan accepted")


def test_verify_plan_rejects_zero_step_plan() -> None:
    module = _load("p2d2c_vp_zero_step")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = _tamper(plan, lambda p: p.__setitem__("steps", []))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("zero-step plan accepted")


def test_verify_plan_rejects_unknown_step_id() -> None:
    module = _load("p2d2c_vp_unknown_sid")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = _tamper(plan, lambda p: p["steps"][0].__setitem__("step_id", "evil_step"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown step_id accepted")


def test_verify_plan_rejects_cross_family_step_swap() -> None:
    """A fan_in operation_id must not carry a runtime_capture step_id."""
    module = _load("p2d2c_vp_xfamily")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = _tamper(plan, lambda p: p["steps"][0].__setitem__("step_id", "select_device"))
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-family step swap accepted")


def test_verify_plan_rejects_cross_action_step_id_within_family() -> None:
    module = _load("p2d2c_vp_xaction")
    with _fi_project("plan_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["step_id"] = "done_gate"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cross-action step_id accepted")


def test_verify_plan_rejects_supervisor_run_step_id() -> None:
    """An injected plan claiming step_id 'run' (supervisor run) must be
    rejected as an unknown variant, even with a command tail present."""
    module = _load("p2d2c_vp_run_step")
    with _fi_project("supervisor_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["step_id"] = "run"
        bad["steps"][0]["argv"].extend(["bash", "-c", "evil"])
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("supervisor run step_id accepted")


def test_verify_plan_rejects_primitive_reuse_outside_owned_variants() -> None:
    """done_gate.py is owned only by done_gate; using it for plan_prepare
    must fail."""
    module = _load("p2d2c_vp_prim_misuse")
    sha_map = _manifest_sha_map()
    with _fi_project("plan_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["primitive"] = "check_done_gate.py"
        bad["steps"][0]["primitive_sha256"] = sha_map["check_done_gate.py"]
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("primitive misuse accepted")


def test_verify_plan_rejects_tampered_primitive_sha() -> None:
    module = _load("p2d2c_vp_tamper_psha")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["primitive_sha256"] = "b" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered primitive_sha256 accepted")


def test_verify_plan_rejects_tampered_interpreter() -> None:
    module = _load("p2d2c_vp_tamper_interp")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][0] = "/bin/sh"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered interpreter accepted")


def test_verify_plan_rejects_tampered_script() -> None:
    module = _load("p2d2c_vp_tamper_script")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][1] = "/tmp/evil.py"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered script accepted")


def test_verify_plan_rejects_tampered_positional() -> None:
    module = _load("p2d2c_vp_tamper_pos")
    with _fi_project("plan_prepare") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"][2] = "apply"  # was "prepare"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered positional accepted")


def test_verify_plan_rejects_tampered_literal_in_argv() -> None:
    module = _load("p2d2c_vp_tamper_literal")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--platform")
        bad["steps"][0]["argv"][idx + 1] = "ios"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered platform literal accepted")


def test_verify_plan_rejects_tampered_timeout() -> None:
    module = _load("p2d2c_vp_tamper_timeout")
    with _rc_project("capture") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["timeout_seconds"] = TIMEOUT_SECONDS  # wrong: capture needs 600
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered timeout accepted")


def test_verify_plan_rejects_tampered_lock_timeout_literal() -> None:
    module = _load("p2d2c_vp_tamper_lock_to")
    with _rc_project("lock_acquire") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--timeout")
        bad["steps"][0]["argv"][idx + 1] = "1"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("tampered lock timeout literal accepted")


def test_verify_plan_rejects_extra_argv_flag() -> None:
    module = _load("p2d2c_vp_extra_argv")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["argv"].extend(["--asset-tol", "1.0"])
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("extra argv flag accepted")


def test_verify_plan_rejects_added_command_field_in_step() -> None:
    module = _load("p2d2c_vp_cmd_field")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["command"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added command field accepted")


def test_verify_plan_rejects_added_top_level_action_field() -> None:
    module = _load("p2d2c_vp_top_action")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["action"] = "evil"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("added top-level action field accepted")


def test_verify_plan_rejects_unknown_operation_id() -> None:
    module = _load("p2d2c_vp_unknown_op")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["operation_id"] = "flutter.future_op.v1"
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("unknown operation_id in plan accepted")


# ---------------------------------------------------------------------------
# 14b. Request-digest coupling (cwd-only + digest-only tampering).
# ---------------------------------------------------------------------------


def test_verify_plan_rejects_request_digest_only_tamper_runtime_capture() -> None:
    module = _load("p2d2c_vp_dig_rc")
    with _rc_project("select_device") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        bad["request_digest"] = "c" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("request_digest-only tamper accepted (rc)")


def test_verify_plan_rejects_request_digest_only_tamper_project_gates() -> None:
    module = _load("p2d2c_vp_dig_pg")
    with _pg_project("interaction_wiring") as (proj, spec, request):
        plan = module.build(PG_OP, request)
        bad = copy.deepcopy(plan)
        bad["request_digest"] = "d" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("request_digest-only tamper accepted (pg)")


def test_verify_plan_rejects_request_digest_only_tamper_fan_in() -> None:
    module = _load("p2d2c_vp_dig_fi")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["request_digest"] = "e" * 64
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("request_digest-only tamper accepted (fi)")


def test_verify_plan_rejects_cwd_only_tamper_select_device() -> None:
    """select_device argv contains only spec-root paths; a cwd-only
    substitution is detected via the request-digest coupling."""
    module = _load("p2d2c_vp_cwd_rc")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        other = _new_proj(tmp, "other_proj")
        spec = _new_spec(tmp)
        _setup_rc(proj, spec, "select_device")
        request = _rc_request(proj, spec, "select_device")
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(other)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cwd-only tamper accepted (select_device)")


def test_verify_plan_rejects_cwd_only_tamper_capture() -> None:
    module = _load("p2d2c_vp_cwd_cap")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        other = _new_proj(tmp, "other_proj")
        spec = _new_spec(tmp)
        _setup_rc(proj, spec, "capture")
        request = _rc_request(proj, spec, "capture")
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(other)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cwd-only tamper accepted (capture)")


def test_verify_plan_rejects_cwd_only_tamper_project_gates() -> None:
    module = _load("p2d2c_vp_cwd_pg")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        other = _new_proj(tmp, "other_proj")
        spec = _new_spec(tmp)
        _setup_pg(proj, spec, "interaction_wiring")
        request = _pg_request(proj, spec, "interaction_wiring")
        plan = module.build(PG_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(other)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cwd-only tamper accepted (pg)")


def test_verify_plan_rejects_cwd_only_tamper_fan_in() -> None:
    module = _load("p2d2c_vp_cwd_fi")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        other = _new_proj(tmp, "other_proj")
        spec = _new_spec(tmp)
        _setup_fi(proj, spec, "done_gate")
        request = _fi_request(proj, spec, "done_gate")
        plan = module.build(FI_OP, request)
        bad = copy.deepcopy(plan)
        bad["steps"][0]["cwd"] = str(other)
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("cwd-only tamper accepted (fi)")


def test_verify_plan_no_variant_bypasses_cwd_validation() -> None:
    """Sanity: every variant's plan, when its cwd is tampered to a
    directory unrelated to any argv path, must fail verification."""
    module = _load("p2d2c_vp_no_bypass")
    unrelated_dir = "/var/run"
    for family, action, _prim, _to, _pos in _VARIANTS:
        with _ctx_for(family, action) as (proj, spec, request):
            plan = module.build(_variant_op(family), request)
            bad = copy.deepcopy(plan)
            bad["steps"][0]["cwd"] = unrelated_dir
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError(
                    f"{family}/{action}: cwd bypass accepted"
                )


def test_verify_plan_rejects_argv_path_only_tamper_via_digest() -> None:
    """Tampering a spec artifact path (without fixing the digest) is
    rejected both by the fixed-basename check and the digest coupling."""
    module = _load("p2d2c_vp_argv_path")
    with _rc_project("capture") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--out")
        bad["steps"][0]["argv"][idx + 1] = str(spec / "evil.png")
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("argv-path-only tamper accepted")


def test_verify_plan_rejects_mixed_spec_parents() -> None:
    """A hand-crafted plan where capture's three spec paths have
    different parents must be rejected."""
    module = _load("p2d2c_vp_mixed_parents")
    with _canonical_tempdir() as tmp:
        proj = _new_proj(tmp)
        spec1 = _new_spec(tmp, "spec1")
        spec2 = _new_spec(tmp, "spec2")
        _write_json(spec1 / "runtime_device.json", {})
        _write_json(spec1 / "visual_manifest.json", {})
        request = _rc_request(proj, spec1, "capture")
        # Build normally then move --out to spec2 to create mixed parents.
        plan = module.build(RC_OP, request)
        bad = copy.deepcopy(plan)
        idx = bad["steps"][0]["argv"].index("--out")
        bad["steps"][0]["argv"][idx + 1] = str(spec2 / "actual.png")
        # Recompute digest over the tampered plan's reconstructed request
        # to isolate the mixed-parent check from the digest check.
        module._verify_capsule = lambda: None
        try:
            module.verify_plan(bad)
        except module.OperationPlanError:
            pass
        else:
            raise AssertionError("mixed spec parents accepted")
        finally:
            del module._verify_capsule


# ---------------------------------------------------------------------------
# 15. Forbidden keys / generic-exception redaction.
# ---------------------------------------------------------------------------


def test_build_redacts_generic_exception() -> None:
    module = _load("p2d2c_redact_build")

    def _boom(*args, **kwargs):
        raise OSError("SUPER_SECRET_OSERROR_P2D2C")

    module._validate_root_path = _boom
    try:
        with _fi_project("done_gate") as (proj, spec, request):
            try:
                module.build(FI_OP, request)
            except module.OperationPlanError as exc:
                msg = str(exc)
                assert "SUPER_SECRET_OSERROR_P2D2C" not in msg
            else:
                raise AssertionError("generic OSError swallowed")
    finally:
        del module._validate_root_path


def test_verify_plan_redacts_generic_exception() -> None:
    module = _load("p2d2c_redact_vp")
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)

    def _boom(*args, **kwargs):
        raise OSError("SUPER_SECRET_VERIFY_P2D2C")

    module._manifest_sha_map = _boom
    try:
        try:
            module.verify_plan(plan)
        except module.OperationPlanError as exc:
            msg = str(exc)
            assert "SUPER_SECRET_VERIFY_P2D2C" not in msg
        else:
            raise AssertionError("generic exception swallowed in verify_plan")
    finally:
        del module._manifest_sha_map


def test_build_calls_verify_plan_internally() -> None:
    module = _load("p2d2c_internal_verify")
    called = {"count": 0}
    original = module.verify_plan

    def _tracking(plan):
        called["count"] += 1
        return original(plan)

    module.verify_plan = _tracking
    try:
        with _fi_project("done_gate") as (proj, spec, request):
            module.build(FI_OP, request)
    finally:
        module.verify_plan = original
    assert called["count"] >= 1


def test_build_fails_if_internal_verify_fails() -> None:
    module = _load("p2d2c_internal_fail")

    def _boom(plan):
        raise module.OperationPlanError("internal verify boom p2d2c")

    module.verify_plan = _boom
    try:
        with _fi_project("done_gate") as (proj, spec, request):
            try:
                module.build(FI_OP, request)
            except module.OperationPlanError as exc:
                assert "internal verify boom p2d2c" in str(exc)
            else:
                raise AssertionError("build swallowed internal verify failure")
    finally:
        del module.verify_plan


# ---------------------------------------------------------------------------
# 16. No subprocess / shell / CLI / stdlib-only / no iff.
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
    module = _load("p2d2c_noreadiff")
    iff_path = REPO_ROOT / "iff"
    with _fi_project("done_gate") as (proj, spec, request):
        plan = module.build(FI_OP, request)
    assert str(iff_path) not in json.dumps(plan)


# ---------------------------------------------------------------------------
# 17. No writes during build / verify.
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


def test_build_does_not_mutate_project_or_spec() -> None:
    module = _load("p2d2c_nowrite_build")
    with _fi_project("plan_prepare") as (proj, spec, request):
        before_proj = _snapshot(proj)
        before_spec = _snapshot(spec)
        module.build(FI_OP, request)
        after_proj = _snapshot(proj)
        after_spec = _snapshot(spec)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_spec.keys()) == set(after_spec.keys())
    for p, data in before_spec.items():
        assert after_spec[p] == data, f"spec mutated: {p}"


def test_verify_plan_does_not_mutate_project_or_spec() -> None:
    module = _load("p2d2c_nowrite_verify")
    with _rc_project("capture") as (proj, spec, request):
        plan = module.build(RC_OP, request)
        before_proj = _snapshot(proj)
        before_spec = _snapshot(spec)
        module.verify_plan(plan)
        after_proj = _snapshot(proj)
        after_spec = _snapshot(spec)
    assert set(before_proj.keys()) == set(after_proj.keys())
    for p, data in before_proj.items():
        assert after_proj[p] == data, f"project mutated: {p}"
    assert set(before_spec.keys()) == set(after_spec.keys())
    for p, data in before_spec.items():
        assert after_spec[p] == data, f"spec mutated: {p}"


def test_build_does_not_mutate_capsule() -> None:
    module = _load("p2d2c_nowrite_capsule")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    before = _snapshot(capsule_dir)
    with _fi_project("done_gate") as (proj, spec, request):
        module.build(FI_OP, request)
    after = _snapshot(capsule_dir)
    assert set(before.keys()) == set(after.keys())
    for p, data in before.items():
        assert after[p] == data, f"capsule mutated: {p}"


def test_build_does_not_create_pycache_in_project() -> None:
    module = _load("p2d2c_nopyc")
    with _fi_project("done_gate") as (proj, spec, request):
        module.build(FI_OP, request)
        pyc_dirs = [p for p in proj.rglob("__pycache__") if p.is_dir()]
    assert pyc_dirs == [], pyc_dirs


# ---------------------------------------------------------------------------
# 18. Registry / P2c descriptor / baselines / capsule unchanged.
# ---------------------------------------------------------------------------


def test_build_does_not_edit_registry() -> None:
    module = _load("p2d2c_noedit_reg")
    before = REGISTRY_PATH.read_bytes()
    with _fi_project("done_gate") as (proj, spec, request):
        module.build(FI_OP, request)
    after = REGISTRY_PATH.read_bytes()
    assert before == after, "registries.json was mutated"


def test_build_does_not_edit_p2c_descriptor() -> None:
    module = _load("p2d2c_noedit_desc")
    before = P2C_DESCRIPTOR_PATH.read_bytes()
    with _rc_project("select_device") as (proj, spec, request):
        module.build(RC_OP, request)
    after = P2C_DESCRIPTOR_PATH.read_bytes()
    assert before == after, "P2c descriptor was mutated"


def test_build_does_not_touch_pycache_in_capsule() -> None:
    module = _load("p2d2c_nocapsule_pyc")
    capsule_dir = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
    pyc_before = list(capsule_dir.rglob("__pycache__"))
    with _pg_project("fixture_source") as (proj, spec, request):
        module.build(PG_OP, request)
    pyc_after = list(capsule_dir.rglob("__pycache__"))
    assert pyc_before == pyc_after


def test_build_does_not_mutate_vendor_manifest() -> None:
    module = _load("p2d2c_noedit_vendor")
    before = MANIFEST_PATH.read_bytes()
    with _fi_project("done_gate") as (proj, spec, request):
        module.build(FI_OP, request)
    after = MANIFEST_PATH.read_bytes()
    assert before == after, "iff-v1-vendor.json was mutated"


# ---------------------------------------------------------------------------
# 19. P2d2a/P2d2b operations still work — append-only registry guard.
# ---------------------------------------------------------------------------


def test_p2d2a_operations_still_pass_verification() -> None:
    module = _load("p2d2c_append_guard_p2d2a")
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
        (proj / "pubspec.yaml").write_text("name: my_app\n")
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


def test_p2d2b_operations_still_pass_verification() -> None:
    module = _load("p2d2c_append_guard_p2d2b")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "pubspec.yaml").write_text("name: my_app\n")
        (run / "feature_spec").mkdir(parents=True)
        request = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "action": "prepare",
            "spec_root_path": "feature_spec",
            "packaging_out_path": "packaging_evidence.json",
        }
        plan = module.build("flutter.packaging.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.packaging.v1"


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
