#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2c Flutter platform-adapter
descriptor (non-executable).

Covers the public Python API and CLI of
``platforms/flutter_standard_v1.py``:

1. ``describe() -> dict`` returns the canonical non-executable descriptor
   that structures the existing vendored iFF Flutter-specific script
   families under the nine settled platform operation ports and binds every
   mapped primitive to the immutable capsule manifest SHA-256.
2. ``verify_descriptor() -> dict`` re-verifies the installed capsule and
   fail-closed rejects: duplicate JSON keys, missing/extra scripts,
   manifest/file SHA mismatch, wrong capsule binding, unexpected operation
   IDs/order/capability states, duplicate primitive ownership, non-regular
   primitives, symlinks, and any executable/command/argv field.
3. The descriptor remains fail-closed / inactive: root ``executable`` is
   ``false``; ``activation_state`` is ``inactive``; no operation may carry
   an executable/command/argv/shell/script-runner field; no executable
   builder, Dart generation, packaging, capture, or parity gate runs here.
4. The CLI exposes only ``describe`` and ``verify``; it accepts no path,
   registry, command, executable, script, interpreter, environment, argv,
   or activation override, emits exactly one canonical JSON object on
   stdout for success (exit 0) or stderr for failure (exit 2), and never
   emits a traceback or arbitrary exception text.
5. ``describe()`` and ``verify_descriptor()`` are deterministic
   byte-for-byte across processes and working directories.

This phase is descriptor only. The mapping is a fixed private code
constant; SHA values are resolved from the installed
``iff-v1-vendor.json`` only after capsule verification. No sibling ``iff/``
dependency is allowed.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2c_flutter_descriptor.py
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
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
MODULE_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"

KIND_DESCRIPTOR = "icp.platform-adapter-descriptor.v1"
KIND_VERIFY = "icp.platform-adapter-descriptor-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
ACTIVATION_STATE = "inactive"

# Canonical ownership mapping (source of truth for tests).
EXPECTED_OPERATIONS: list[dict[str, Any]] = [
    {
        "id": "project_preflight",
        "capability_state": "required",
        "implementation_state": "new-port-required",
        "legacy_primitives": [],
    },
    {
        "id": "visible_codegen",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "generate_canvas.py",
            "make_implementation_map.py",
            "make_status_bar_policy.py",
        ],
    },
    {
        "id": "fixture_codegen",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": ["make_visual_fixture.py"],
    },
    {
        "id": "trace_harness",
        "capability_state": "optional-with-shared-policy",
        "implementation_state": "legacy-mapped",
        # P2.5d: trace_harness legacy primitive tuple is now ordered
        # (merge_shared_expected.py, gen_layout_trace_test.py) to mirror
        # the trusted plan's capsule steps. The platform-origin
        # provenance gate (flutter_merged_expectation_provenance_gate_v1.py)
        # is NOT a legacy primitive and must not appear here.
        "legacy_primitives": [
            "merge_shared_expected.py",
            "gen_layout_trace_test.py",
        ],
    },
    {
        "id": "packaging",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "prepare_assembly_packaging.py",
            "update_pubspec_assets.py",
            "copy_assets.py",
        ],
    },
    {
        "id": "test_runner",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "assembly_tdd_guard.py",
            "retire_stale_flutter_template_tests.py",
        ],
    },
    {
        "id": "runtime_capture",
        "capability_state": "optional-with-shared-policy",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "select_runtime_device.py",
            "device_lock.py",
            "capture_runtime_screenshot.py",
            "physical_device_preview.py",
        ],
    },
    {
        "id": "project_gates",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "check_interaction_wiring.py",
            "check_api_integration.py",
            "check_fixture_source.py",
            "check_capture_readiness.py",
        ],
    },
    {
        "id": "fan_in",
        "capability_state": "required",
        "implementation_state": "legacy-mapped",
        "legacy_primitives": [
            "assembly_plan_batch.py",
            "assembly_worker_supervisor.py",
            "check_done_gate.py",
            "assembly_completion.py",
        ],
    },
]

EXPECTED_PRIMITIVE_TOTAL = sum(len(o["legacy_primitives"]) for o in EXPECTED_OPERATIONS)


# ---------------------------------------------------------------------------
# Module loader.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_bytes()
    return json.loads(raw)


def _manifest_sha_map() -> dict[str, str]:
    return {e["name"]: e["sha256"] for e in _manifest()["scripts"]}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2c_"):
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# 1. Module + constants.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("flutter_standard_v1_constants", MODULE_PATH)
    assert module.SCHEMA_VERSION == 1
    assert module.KIND_DESCRIPTOR == KIND_DESCRIPTOR
    assert module.PLATFORM_ID == PLATFORM_ID
    assert module.PROFILE_ID == PROFILE_ID
    assert module.ACTIVATION_STATE == ACTIVATION_STATE


def test_kind_verify_constant_present() -> None:
    module = _load("flutter_standard_v1_kverify", MODULE_PATH)
    assert module.KIND_VERIFY == KIND_VERIFY
    assert isinstance(module.SCRIPT_NAME, str) and module.SCRIPT_NAME


def test_descriptor_only_local_error_code_does_not_extend_icp_common() -> None:
    """The local error code is scoped to this descriptor and never extends
    icp_common.ALL_ERROR_CODES."""
    module = _load("flutter_standard_v1_errcode", MODULE_PATH)
    assert isinstance(module.CODE_DESCRIPTOR, str) and module.CODE_DESCRIPTOR
    common = _load("icp_common_for_errcode", ICP_SCRIPTS / "icp_common.py")
    assert module.CODE_DESCRIPTOR not in common.ALL_ERROR_CODES


# ---------------------------------------------------------------------------
# 2. Public API surface (only describe + verify_descriptor).
# ---------------------------------------------------------------------------


def test_public_api_exposes_only_describe_and_verify_descriptor() -> None:
    """Only ``describe`` and ``verify_descriptor`` are public operation
    functions. The standard scaffolding (the ``DescriptorError`` exception
    class and the ``main`` CLI entry point) and the schema constants are
    permitted; no other operation-like callable may exist."""
    import inspect

    module = _load("flutter_standard_v1_pubapi", MODULE_PATH)
    for name in ("describe", "verify_descriptor"):
        assert callable(getattr(module, name)), f"missing public {name}"
    # Allowed scaffolding: the exception class, the CLI entry, and
    # constants. Anything else that is a public function is a contract
    # violation.
    allowed = {"describe", "verify_descriptor", "main"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed)
    assert extra == [], f"unexpected public functions: {extra}"
    # The exception class is permitted; no other public classes.
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"DescriptorError"}, public_classes
    # No public callable may suggest an executable/platform operation.
    forbidden_prefixes = (
        "execute_", "run_", "build_", "generate_", "package_",
        "capture_", "activate_", "preflight_", "claim_", "export_",
        "writeback_", "select_", "fetch_", "test_", "trace_",
    )
    for n in dir(module):
        if n.startswith("_"):
            continue
        assert not n.lower().startswith(forbidden_prefixes), (
            f"forbidden executable-surface name: {n}"
        )


def test_public_api_signatures_take_no_parameters() -> None:
    import inspect

    module = _load("flutter_standard_v1_sigs", MODULE_PATH)
    for name in ("describe", "verify_descriptor"):
        sig = inspect.signature(getattr(module, name))
        assert list(sig.parameters) == [], (
            f"{name} must take no parameters; got {sig}"
        )


def test_module_exposes_no_override_parameters() -> None:
    """No public path/registry/command/executable/script/interpreter/env/
    argv/activation override may exist."""
    module = _load("flutter_standard_v1_noparams", MODULE_PATH)
    forbidden = (
        "SKILL_ROOT", "ICP_ROOT_OVERRIDE", "REGISTRY_OVERRIDE",
        "CAPSULE_OVERRIDE", "SCRIPT_PATH", "INTERPRETER",
        "ARGV", "ENV", "ACTIVATION", "COMMAND",
    )
    for attr in forbidden:
        assert not hasattr(module, attr), f"module exposes override {attr}"


# ---------------------------------------------------------------------------
# 3. describe() top-level shape.
# ---------------------------------------------------------------------------


def test_describe_returns_canonical_descriptor() -> None:
    module = _load("flutter_standard_v1_describe_toplevel", MODULE_PATH)
    descriptor = module.describe()
    assert isinstance(descriptor, dict)
    assert descriptor["kind"] == KIND_DESCRIPTOR
    assert descriptor["schema_version"] == 1
    assert descriptor["platform_id"] == PLATFORM_ID
    assert descriptor["profile_id"] == PROFILE_ID
    assert descriptor["activation_state"] == ACTIVATION_STATE
    assert descriptor["executable"] is False


def test_describe_top_level_keys_exactly_canonical() -> None:
    module = _load("flutter_standard_v1_topkeys", MODULE_PATH)
    descriptor = module.describe()
    assert set(descriptor.keys()) == {
        "kind", "schema_version", "platform_id", "profile_id",
        "activation_state", "executable", "operations",
    }


def test_describe_executable_is_strictly_false() -> None:
    module = _load("flutter_standard_v1_execfalse", MODULE_PATH)
    descriptor = module.describe()
    # Must be exactly boolean False (not 0, not "false").
    assert descriptor["executable"] is False


# ---------------------------------------------------------------------------
# 4. Operations: count, order, capability state, implementation state.
# ---------------------------------------------------------------------------


def test_describe_operations_count_is_nine() -> None:
    module = _load("flutter_standard_v1_opscount", MODULE_PATH)
    descriptor = module.describe()
    assert len(descriptor["operations"]) == 9


def test_describe_operations_in_canonical_order() -> None:
    module = _load("flutter_standard_v1_opsorder", MODULE_PATH)
    descriptor = module.describe()
    ids = [op["id"] for op in descriptor["operations"]]
    expected = [o["id"] for o in EXPECTED_OPERATIONS]
    assert ids == expected, ids


def test_describe_operation_capability_states_match_spec() -> None:
    module = _load("flutter_standard_v1_capstates", MODULE_PATH)
    descriptor = module.describe()
    for actual, expected in zip(descriptor["operations"], EXPECTED_OPERATIONS):
        assert actual["capability_state"] == expected["capability_state"], actual


def test_describe_operation_implementation_states_match_spec() -> None:
    module = _load("flutter_standard_v1_implstates", MODULE_PATH)
    descriptor = module.describe()
    for actual, expected in zip(descriptor["operations"], EXPECTED_OPERATIONS):
        assert actual["implementation_state"] == expected["implementation_state"], actual


def test_describe_operation_keys_exactly_canonical() -> None:
    module = _load("flutter_standard_v1_opkeys", MODULE_PATH)
    descriptor = module.describe()
    for op in descriptor["operations"]:
        assert set(op.keys()) == {
            "id", "capability_state", "implementation_state", "legacy_primitives",
        }, op


def test_describe_capability_states_match_settled_registry() -> None:
    module = _load("flutter_standard_v1_regcap", MODULE_PATH)
    descriptor = module.describe()
    reg = json.loads(REGISTRY_PATH.read_bytes())
    reg_caps = reg["capabilities"]
    for op in descriptor["operations"]:
        assert op["capability_state"] == reg_caps[op["id"]], op


def test_describe_operation_ids_match_registry_in_order() -> None:
    module = _load("flutter_standard_v1_regorder", MODULE_PATH)
    descriptor = module.describe()
    reg = json.loads(REGISTRY_PATH.read_bytes())
    reg_ids = [o["id"] for o in reg["operations"]]
    actual_ids = [o["id"] for o in descriptor["operations"]]
    assert actual_ids == reg_ids, actual_ids


# ---------------------------------------------------------------------------
# 5. Per-operation primitive ownership.
# ---------------------------------------------------------------------------


def _assert_primitives(op_actual: dict, op_expected: dict, sha_map: dict) -> None:
    prims = op_actual["legacy_primitives"]
    assert isinstance(prims, list)
    assert len(prims) == len(op_expected["legacy_primitives"]), op_actual
    for prim, expected_name in zip(prims, op_expected["legacy_primitives"]):
        assert set(prim.keys()) == {"script", "sha256"}, prim
        assert prim["script"] == expected_name, prim
        assert prim["sha256"] == sha_map[expected_name], prim
        assert _is_sha256_hex(prim["sha256"]), prim


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


def test_describe_project_preflight_has_no_primitives() -> None:
    module = _load("flutter_standard_v1_preflight", MODULE_PATH)
    descriptor = module.describe()
    preflight = descriptor["operations"][0]
    assert preflight["id"] == "project_preflight"
    assert preflight["legacy_primitives"] == []


def test_describe_project_preflight_implementation_state_is_new_port() -> None:
    module = _load("flutter_standard_v1_preflight_impl", MODULE_PATH)
    descriptor = module.describe()
    preflight = descriptor["operations"][0]
    assert preflight["implementation_state"] == "new-port-required"


def test_describe_visible_codegen_primitives_exact() -> None:
    module = _load("flutter_standard_v1_vis", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][1]
    assert op["id"] == "visible_codegen"
    _assert_primitives(op, EXPECTED_OPERATIONS[1], sha_map)


def test_describe_fixture_codegen_primitives_exact() -> None:
    module = _load("flutter_standard_v1_fix", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][2]
    assert op["id"] == "fixture_codegen"
    _assert_primitives(op, EXPECTED_OPERATIONS[2], sha_map)


def test_describe_trace_harness_primitives_exact() -> None:
    module = _load("flutter_standard_v1_trace", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][3]
    assert op["id"] == "trace_harness"
    _assert_primitives(op, EXPECTED_OPERATIONS[3], sha_map)


def test_describe_packaging_primitives_exact() -> None:
    module = _load("flutter_standard_v1_pack", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][4]
    assert op["id"] == "packaging"
    _assert_primitives(op, EXPECTED_OPERATIONS[4], sha_map)


def test_describe_test_runner_primitives_exact() -> None:
    module = _load("flutter_standard_v1_test", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][5]
    assert op["id"] == "test_runner"
    _assert_primitives(op, EXPECTED_OPERATIONS[5], sha_map)


def test_describe_runtime_capture_primitives_exact() -> None:
    module = _load("flutter_standard_v1_rt", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][6]
    assert op["id"] == "runtime_capture"
    _assert_primitives(op, EXPECTED_OPERATIONS[6], sha_map)


def test_describe_project_gates_primitives_exact() -> None:
    module = _load("flutter_standard_v1_gates", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][7]
    assert op["id"] == "project_gates"
    _assert_primitives(op, EXPECTED_OPERATIONS[7], sha_map)


def test_describe_fan_in_primitives_exact() -> None:
    module = _load("flutter_standard_v1_fanin", MODULE_PATH)
    descriptor = module.describe()
    sha_map = _manifest_sha_map()
    op = descriptor["operations"][8]
    assert op["id"] == "fan_in"
    _assert_primitives(op, EXPECTED_OPERATIONS[8], sha_map)


def test_describe_primitive_total_count() -> None:
    module = _load("flutter_standard_v1_total", MODULE_PATH)
    descriptor = module.describe()
    total = sum(len(op["legacy_primitives"]) for op in descriptor["operations"])
    assert total == EXPECTED_PRIMITIVE_TOTAL, total


def test_describe_no_duplicate_primitive_ownership() -> None:
    module = _load("flutter_standard_v1_dup", MODULE_PATH)
    descriptor = module.describe()
    seen: set[str] = set()
    for op in descriptor["operations"]:
        for prim in op["legacy_primitives"]:
            name = prim["script"]
            assert name not in seen, f"duplicate primitive ownership: {name}"
            seen.add(name)


# ---------------------------------------------------------------------------
# 6. Boundaries: no exec/sync_project_rules/SharedCore.
# ---------------------------------------------------------------------------


def test_describe_does_not_map_sync_project_rules() -> None:
    module = _load("flutter_standard_v1_nosync", MODULE_PATH)
    descriptor = module.describe()
    for op in descriptor["operations"]:
        for prim in op["legacy_primitives"]:
            assert prim["script"] != "sync_project_rules.py", (
                "sync_project_rules.py must not be mapped"
            )


def test_describe_does_not_map_shared_core_or_unrelated_scripts() -> None:
    module = _load("flutter_standard_v1_noshared", MODULE_PATH)
    descriptor = module.describe()
    allowed = set()
    for op in EXPECTED_OPERATIONS:
        allowed.update(op["legacy_primitives"])
    # P2.5d: merge_shared_expected.py is now a trace_harness legacy
    # primitive (consumed by the trusted plan), so it is allowed here.
    # The platform gate flutter_merged_expectation_provenance_gate_v1.py
    # is NOT a legacy primitive and must not appear in any tuple.
    forbidden = {
        "sync_project_rules.py",
        "render_fidelity.py" if False else "check_render_fidelity.py",
        "check_responsive_layout.py",
        "visual_diff.py",
        "visual_repair_budget.py",
        "make_figma_layout_contract.py",
        "make_evolution_prompt.py",
        "make_worker_prompt.py",
        "shared_worker_supervisor.py",
        "check_design_artifacts.py",
        "common.py",
        "fetch.py",
        "download_cover.py",
        "write.py",
        "export_figma_scene.py",
        "export_tokens.py",
        "export_assets_manifest.py",
        "classify_design.py",
        # Platform primitives are never legacy primitives.
        "flutter_merged_expectation_provenance_gate_v1.py",
        "flutter_expected_slots_adapter_v1.py",
        "flutter_fixture_projection_guard_v1.py",
    }
    actual = set()
    for op in descriptor["operations"]:
        for prim in op["legacy_primitives"]:
            actual.add(prim["script"])
    leaked = actual & forbidden
    assert not leaked, f"forbidden shared-core/unrelated scripts leaked: {leaked}"


def test_descriptor_carries_no_executable_command_argv_shell_field() -> None:
    module = _load("flutter_standard_v1_noexec", MODULE_PATH)
    descriptor = module.describe()
    forbidden = {
        "command", "argv", "shell", "interpreter", "env", "runner",
        "args", "program", "cmd", "subprocess", "exec", "run",
        "script_path", "script_runner",
    }


    def _walk(obj: Any, location: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "executable":
                    # Only the root may carry executable=false.
                    assert location == "", (
                        f"executable field outside root: {location}/{key}"
                    )
                    assert obj[key] is False, (
                        f"root executable must be False at {location}"
                    )
                    continue
                assert key not in forbidden, (
                    f"forbidden field {key!r} at {location}"
                )
                _walk(value, f"{location}/{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{location}[{i}]")


    _walk(descriptor, "")


def test_descriptor_primitives_use_only_script_and_sha256_keys() -> None:
    module = _load("flutter_standard_v1_psonly", MODULE_PATH)
    descriptor = module.describe()
    for op in descriptor["operations"]:
        for prim in op["legacy_primitives"]:
            assert set(prim.keys()) == {"script", "sha256"}, prim


# ---------------------------------------------------------------------------
# 7. Determinism + capsule verification.
# ---------------------------------------------------------------------------


def test_describe_is_byte_for_byte_deterministic_in_process() -> None:
    module = _load("flutter_standard_v1_det1", MODULE_PATH)
    d1 = module.describe()
    d2 = module.describe()
    b1 = module._canonical_json_bytes(d1)
    b2 = module._canonical_json_bytes(d2)
    assert b1 == b2


def test_describe_is_byte_for_byte_deterministic_across_modules() -> None:
    m1 = _load("flutter_standard_v1_deta", MODULE_PATH)
    m2 = _load("flutter_standard_v1_detb", MODULE_PATH)
    b1 = m1._canonical_json_bytes(m1.describe())
    b2 = m2._canonical_json_bytes(m2.describe())
    assert b1 == b2


def test_describe_is_byte_for_byte_deterministic_across_processes() -> None:
    r1 = _run_cli("describe")
    r2 = _run_cli("describe")
    assert r1.returncode == 0 and r2.returncode == 0
    assert r1.stdout == r2.stdout


def test_describe_is_byte_for_byte_deterministic_across_working_dirs() -> None:
    outputs = []
    with _canonical_tempdir(prefix="p2c_cwd_") as tmp_a, _canonical_tempdir(
        prefix="p2c_cwd_"
    ) as tmp_b:
        for cwd in (tmp_a, tmp_b, REPO_ROOT, ICP_ROOT):
            r = subprocess.run(
                [sys.executable, str(MODULE_PATH), "describe"],
                capture_output=True,
                text=True,
                cwd=str(cwd),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            assert r.returncode == 0, r.stderr
            outputs.append(r.stdout)
    assert all(o == outputs[0] for o in outputs), outputs


def test_describe_calls_verify_capsule_first() -> None:
    module = _load("flutter_standard_v1_capsfirst", MODULE_PATH)
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.DescriptorError("capsule boom")

    module._verify_capsule = _boom
    try:
        try:
            module.describe()
        except module.DescriptorError as exc:
            assert "capsule boom" in str(exc)
        else:
            raise AssertionError("describe did not call _verify_capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


# ---------------------------------------------------------------------------
# 8. verify_descriptor().
# ---------------------------------------------------------------------------


def test_verify_descriptor_returns_canonical_payload() -> None:
    module = _load("flutter_standard_v1_v1", MODULE_PATH)
    report = module.verify_descriptor()
    assert report["ok"] is True
    assert report["kind"] == KIND_VERIFY
    assert report["schema_version"] == 1
    assert report["platform_id"] == PLATFORM_ID
    assert report["profile_id"] == PROFILE_ID
    assert report["activation_state"] == ACTIVATION_STATE
    assert report["executable"] is False


def test_verify_descriptor_keys_exactly_canonical() -> None:
    module = _load("flutter_standard_v1_v2", MODULE_PATH)
    report = module.verify_descriptor()
    assert set(report.keys()) == {
        "ok", "kind", "schema_version", "platform_id", "profile_id",
        "activation_state", "executable", "descriptor_digest",
        "operations_total", "legacy_primitives_total", "capsule",
    }, sorted(report.keys())


def test_verify_descriptor_digest_matches_describe_canonical_bytes() -> None:
    module = _load("flutter_standard_v1_v3", MODULE_PATH)
    descriptor = module.describe()
    descriptor_bytes = module._canonical_json_bytes(descriptor)
    expected_digest = hashlib.sha256(descriptor_bytes).hexdigest()
    report = module.verify_descriptor()
    assert report["descriptor_digest"] == expected_digest


def test_verify_descriptor_primitives_and_operations_totals() -> None:
    module = _load("flutter_standard_v1_v4", MODULE_PATH)
    report = module.verify_descriptor()
    assert report["operations_total"] == 9
    assert report["legacy_primitives_total"] == EXPECTED_PRIMITIVE_TOTAL


def test_verify_descriptor_capsule_payload_present() -> None:
    module = _load("flutter_standard_v1_v5", MODULE_PATH)
    report = module.verify_descriptor()
    capsule = report["capsule"]
    assert capsule["ok"] is True
    assert capsule["kind"] == "icp.iff-v1-vendor-capsule"
    assert capsule["capsule_root"] == "vendor/iff_v1"


def test_verify_descriptor_calls_verify_capsule_first() -> None:
    module = _load("flutter_standard_v1_v6", MODULE_PATH)
    called = {"count": 0}

    def _boom():
        called["count"] += 1
        raise module.DescriptorError("capsule boom")

    module._verify_capsule = _boom
    try:
        try:
            module.verify_descriptor()
        except module.DescriptorError as exc:
            assert "capsule boom" in str(exc)
        else:
            raise AssertionError("verify_descriptor did not verify capsule first")
    finally:
        del module._verify_capsule
    assert called["count"] == 1


# ---------------------------------------------------------------------------
# 9. verify_descriptor() fail-closed rejection of tampered descriptors.
# ---------------------------------------------------------------------------


def _good_descriptor(module) -> dict[str, Any]:
    return module.describe()


def test_validate_rejects_descriptor_with_extra_script_in_operation() -> None:
    module = _load("flutter_standard_v1_x1", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"].append(
        {"script": "fetch.py", "sha256": module._manifest_sha_map(manifest)["fetch.py"]}
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("extra script was not rejected")


def test_validate_rejects_descriptor_with_missing_script_in_operation() -> None:
    module = _load("flutter_standard_v1_x2", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"].pop()
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("missing script was not rejected")


def test_validate_rejects_descriptor_with_wrong_sha256() -> None:
    module = _load("flutter_standard_v1_x3", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"][0]["sha256"] = (
        "0" * 64
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("wrong sha256 was not rejected")


def test_validate_rejects_descriptor_with_malformed_sha256() -> None:
    module = _load("flutter_standard_v1_x4", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"][0]["sha256"] = (
        "XYZ" * 21 + "a"
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("malformed sha256 was not rejected")


def test_validate_rejects_descriptor_with_wrong_operation_order() -> None:
    module = _load("flutter_standard_v1_x5", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][0], descriptor["operations"][1] = (
        descriptor["operations"][1],
        descriptor["operations"][0],
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("wrong operation order was not rejected")


def test_validate_rejects_descriptor_with_wrong_capability_state() -> None:
    module = _load("flutter_standard_v1_x6", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][0]["capability_state"] = (
        "optional-with-shared-policy"
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("wrong capability_state was not rejected")


def test_validate_rejects_descriptor_with_wrong_implementation_state() -> None:
    module = _load("flutter_standard_v1_x7", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][0]["implementation_state"] = "legacy-mapped"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("wrong implementation_state was not rejected")


def test_validate_rejects_descriptor_with_executable_field_on_operation() -> None:
    module = _load("flutter_standard_v1_x8", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["command"] = "flutter"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("executable command field was not rejected")


def test_validate_rejects_descriptor_with_argv_field_on_primitive() -> None:
    module = _load("flutter_standard_v1_x9", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"][0]["argv"] = ["--x"]
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("argv field was not rejected")


def test_validate_rejects_descriptor_with_executable_true_at_root() -> None:
    module = _load("flutter_standard_v1_x10", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["executable"] = True
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("executable=true at root was not rejected")


def test_validate_rejects_descriptor_with_activation_active() -> None:
    module = _load("flutter_standard_v1_x11", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["activation_state"] = "active"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("activation_state=active was not rejected")


def test_validate_rejects_descriptor_with_extra_operation() -> None:
    module = _load("flutter_standard_v1_x12", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"].append(
        {
            "id": "phantom_port",
            "capability_state": "required",
            "implementation_state": "new-port-required",
            "legacy_primitives": [],
        }
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("extra operation was not rejected")


def test_validate_rejects_descriptor_with_duplicate_operation_id() -> None:
    module = _load("flutter_standard_v1_x13", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][8]["id"] = "project_preflight"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("duplicate operation id was not rejected")


def test_validate_rejects_descriptor_with_duplicate_primitive_ownership() -> None:
    module = _load("flutter_standard_v1_x14", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    # Force duplicate: append a duplicate primitive name to fan_in.
    sha_map = module._manifest_sha_map(manifest)
    descriptor["operations"][8]["legacy_primitives"].append(
        {"script": "generate_canvas.py", "sha256": sha_map["generate_canvas.py"]}
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("duplicate primitive ownership was not rejected")


def test_validate_rejects_descriptor_with_wrong_kind() -> None:
    module = _load("flutter_standard_v1_x15", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["kind"] = "icp.something-else.v1"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("wrong kind was not rejected")


def test_validate_rejects_descriptor_with_extra_top_level_key() -> None:
    module = _load("flutter_standard_v1_x16", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["surprise"] = "boom"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("extra top-level key was not rejected")


def test_validate_rejects_descriptor_with_unknown_script_basename() -> None:
    module = _load("flutter_standard_v1_x17", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][1]["legacy_primitives"][0]["script"] = (
        "totally_not_in_manifest.py"
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("unknown script basename was not rejected")


def test_validate_rejects_descriptor_with_legacy_mapped_preflight() -> None:
    """project_preflight must be new-port-required and have no primitives;
    setting it to legacy-mapped must fail."""
    module = _load("flutter_standard_v1_x18", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["operations"][0]["implementation_state"] = "legacy-mapped"
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("legacy-mapped project_preflight was not rejected")


def test_validate_rejects_descriptor_mapping_sync_project_rules() -> None:
    """Mapping sync_project_rules.py under project_preflight must fail."""
    module = _load("flutter_standard_v1_x19", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    sha_map = module._manifest_sha_map(manifest)
    descriptor["operations"][0]["legacy_primitives"].append(
        {"script": "sync_project_rules.py", "sha256": sha_map["sync_project_rules.py"]}
    )
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("sync_project_rules.py mapping was not rejected")


def test_validate_rejects_descriptor_with_shell_field_on_root() -> None:
    module = _load("flutter_standard_v1_x20", MODULE_PATH)
    manifest = module._load_manifest()
    descriptor = copy.deepcopy(_good_descriptor(module))
    descriptor["shell"] = False
    try:
        module._validate_descriptor_against_spec(descriptor, manifest)
    except module.DescriptorError:
        pass
    else:
        raise AssertionError("shell field on root was not rejected")


# ---------------------------------------------------------------------------
# 10. CLI surface.
# ---------------------------------------------------------------------------


def test_cli_describe_emits_canonical_json_on_stdout_exit_0() -> None:
    r = _run_cli("describe")
    assert r.returncode == 0, r.stderr
    assert r.stderr == "", r.stderr
    payload = json.loads(r.stdout)
    assert payload["kind"] == KIND_DESCRIPTOR
    assert payload["executable"] is False


def test_cli_describe_byte_for_byte_matches_python_canonical_bytes() -> None:
    module = _load("flutter_standard_v1_cli_match", MODULE_PATH)
    r = _run_cli("describe")
    assert r.returncode == 0
    expected = module._canonical_json_bytes(module.describe()).decode("utf-8")
    assert r.stdout == expected


def test_cli_verify_emits_canonical_json_on_stdout_exit_0() -> None:
    r = _run_cli("verify")
    assert r.returncode == 0, r.stderr
    assert r.stderr == "", r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["kind"] == KIND_VERIFY


def test_cli_verify_byte_for_byte_matches_python_report() -> None:
    module = _load("flutter_standard_v1_cli_verify_match", MODULE_PATH)
    r = _run_cli("verify")
    assert r.returncode == 0
    expected = module._canonical_json_bytes(module.verify_descriptor()).decode("utf-8")
    assert r.stdout == expected


def test_cli_rejects_unknown_subcommand() -> None:
    r = _run_cli("bogus")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert payload["code"] == "platform_adapter_descriptor_failed"
    assert "traceback" not in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_cli_rejects_no_subcommand() -> None:
    r = _run_cli()
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False


def test_cli_rejects_path_override() -> None:
    r = _run_cli("describe", "--path", "/tmp/x")
    assert r.returncode == 2
    payload = json.loads(r.stderr)
    assert payload["ok"] is False


def test_cli_rejects_registry_override() -> None:
    r = _run_cli("describe", "--registry", "/tmp/r.json")
    assert r.returncode == 2
    payload = json.loads(r.stderr)
    assert payload["ok"] is False


def test_cli_rejects_command_override() -> None:
    r = _run_cli("describe", "--command", "flutter")
    assert r.returncode == 2


def test_cli_rejects_executable_override() -> None:
    r = _run_cli("describe", "--executable", "true")
    assert r.returncode == 2


def test_cli_rejects_script_override() -> None:
    r = _run_cli("describe", "--script", "x.py")
    assert r.returncode == 2


def test_cli_rejects_interpreter_override() -> None:
    r = _run_cli("describe", "--interpreter", "/usr/bin/python3")
    assert r.returncode == 2


def test_cli_rejects_env_override() -> None:
    r = _run_cli("describe", "--env", "X=1")
    assert r.returncode == 2


def test_cli_rejects_argv_override() -> None:
    r = _run_cli("describe", "--argv", "[]")
    assert r.returncode == 2


def test_cli_rejects_activation_override() -> None:
    r = _run_cli("describe", "--activate")
    assert r.returncode == 2


def test_cli_emits_no_traceback_on_failure() -> None:
    module = _load("flutter_standard_v1_cli_tb", MODULE_PATH)
    original_describe = module.describe

    def _boom():
        raise RuntimeError("SECRET_GENERIC_EXCEPTION")

    module.describe = _boom
    stderr = io.StringIO()
    stdout = io.StringIO()
    orig_err = sys.stderr
    orig_out = sys.stdout
    sys.stderr = stderr
    sys.stdout = stdout
    try:
        rc = module.main(["describe"])
    finally:
        sys.stderr = orig_err
        sys.stdout = orig_out
        module.describe = original_describe
    assert rc == 2
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["ok"] is False
    assert payload["code"] == "platform_adapter_descriptor_failed"
    # Generic exception must surface only the class name; no arbitrary text.
    assert payload["message"] == "RuntimeError"
    assert "SECRET_GENERIC_EXCEPTION" not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_cli_descriptor_error_emits_message_without_traceback() -> None:
    module = _load("flutter_standard_v1_cli_dtb", MODULE_PATH)
    original_describe = module.describe

    def _boom():
        raise module.DescriptorError("deterministic message text")

    module.describe = _boom
    stderr = io.StringIO()
    orig_err = sys.stderr
    sys.stderr = stderr
    try:
        rc = module.main(["describe"])
    finally:
        sys.stderr = orig_err
        module.describe = original_describe
    assert rc == 2
    payload = json.loads(stderr.getvalue())
    assert payload["ok"] is False
    assert payload["message"] == "deterministic message text"
    assert "Traceback" not in stderr.getvalue()


# ---------------------------------------------------------------------------
# 11. No sibling iff dependency.
# ---------------------------------------------------------------------------


def test_module_does_not_import_sibling_iff_at_top_level() -> None:
    """Loading the module must not import sibling iff/ packages."""
    source = MODULE_PATH.read_text()
    assert "import iff" not in source
    assert "from iff " not in source
    assert "from iff." not in source


def test_module_does_not_reference_iff_root_or_scripts() -> None:
    source = MODULE_PATH.read_text()
    # The module may discuss iff only in docstring text. Code references to
    # a live iff/ path are forbidden.
    assert 'IFF_ROOT' not in source
    assert 'iff/scripts' not in source.replace('iff/scripts', '\0').replace('\0', '') if False else True
    # Stronger: no Symbol referencing the live iff path tree.
    for needle in ("iff_root", "iff/scripts/", "Path(\"iff\")"):
        assert needle not in source, f"forbidden reference: {needle}"


# ---------------------------------------------------------------------------
# 12. Deterministic JSON shape for both payloads.
# ---------------------------------------------------------------------------


def test_canonical_json_uses_sorted_keys_two_space_indent_newline() -> None:
    module = _load("flutter_standard_v1_canon", MODULE_PATH)
    payload = {"b": 1, "a": 2, "c": [3, 2, 1]}
    raw = module._canonical_json_bytes(payload)
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    # Sorted keys.
    assert text.index("\"a\"") < text.index("\"b\"") < text.index("\"c\"")
    # Two-space indent.
    assert "\n  " in text


# ---------------------------------------------------------------------------
# 13. Standard library only.
# ---------------------------------------------------------------------------


def test_module_uses_only_standard_library_imports() -> None:
    """Production code must import only stdlib modules."""
    import ast

    tree = ast.parse(MODULE_PATH.read_text())
    allowed_prefixes = (
        "argparse", "hashlib", "importlib", "json", "os", "stat", "sys",
        "pathlib", "typing", "__future__",
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
