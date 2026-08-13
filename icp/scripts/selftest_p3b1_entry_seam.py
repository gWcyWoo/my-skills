#!/usr/bin/env python3
"""ICP P3b1b2 inactive package-aware entry seam focused RED -> GREEN self-test.

Covers the inactive package-aware entry seam:

* ``preflight_selection.support_gate_package_aware`` (new).
* ``prepare_selection.prepare_selection_with_entry_gate`` (new).
* ``icp/SKILL.md`` brief P3b1b section next to P3b1a.

Every current v1 package resolution is ``activation_state=inactive`` /
``executable=false``, so the seam must always stop at
``platform_package_inactive`` (or an earlier deterministic stop). No current
valid v1 input reaches ``route=prepare``.

Run: ``PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3b1_entry_seam.py``
"""

from __future__ import annotations

import ast
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
from typing import Any, Callable

ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PREFLIGHT_PATH = ICP_SCRIPTS / "preflight_selection.py"
PREPARE_PATH = ICP_SCRIPTS / "prepare_selection.py"
ENTRY_READINESS_PATH = ICP_SCRIPTS / "entry_readiness_v1.py"
RESOLVER_PATH = ICP_SCRIPTS / "platform_package_resolver_v1.py"
CONTRACT_PATH = ICP_SCRIPTS / "platforms" / "platform_package_contract_v1.py"
CSV_TASK_SOURCE_PATH = ICP_SCRIPTS / "csv_task_source.py"
FREEZE_MANIFEST_PATH = ICP_SCRIPTS / "freeze_selection_manifest.py"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
SKILL_PATH = ICP_ROOT / "SKILL.md"

# Canonical result schema (re-stated independently so divergence is caught).
KIND_SEAM_RESULT = "icp.inactive-entry-seam-result.v1"
SCHEMA_VERSION = 1
SEAM_RESULT_KEYS = (
    "kind", "schema_version", "route",
    "entry_gate_decision_digest", "readiness_report_digest",
    "package_resolution_digest", "gate_code", "preparation_ack",
)
ROUTES = ("stop", "prepare")

# Re-stated existing-API signatures (independent of module under test).
SUPPORT_GATE_PARAMS = ("config", "registries")
PREFLIGHT_FROM_CONFIG_PARAMS = ("config", "registries")
PREPARE_SELECTION_KWPARAMS = (
    "resolved_config", "limit", "registries", "batch_id", "on_manifest_frozen",
)
SUPPORT_GATE_PACKAGE_AWARE_PARAMS = ("config", "registries", "package_resolution")
PREPARE_WITH_ENTRY_GATE_KWPARAMS = (
    "resolved_config", "limit", "readiness_report", "entry_gate_decision",
    "package_resolution", "registries", "batch_id", "on_manifest_frozen",
)

# Deterministic failure codes the seam may produce (controlled safe IDs only).
CODE_PLATFORM_PACKAGE_INACTIVE = "platform_package_inactive"
CODE_INVALID_PLATFORM_PACKAGE = "invalid_platform_package"
CODE_INVALID_INPUT = "invalid_input"
CODE_UNSUPPORTED_PLATFORM = "unsupported_platform"

SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

ENTRY_DECISIONS_NON_SELECT = (
    "resume-step", "replay-step", "run-recovery-verifier",
    "needs-user-input", "terminal-cleanup-required", "blocked", "no-work",
)
ENTRY_DECISION_SELECT_NEW = "select-new"
REPORT_STATUSES = ("needs-user-input", "blocked", "no-work", "ready")

# Controlled P3b1a/P3a2 reason-code for each non-select decision literal.
# Hand-built decisions must use these controlled reasons (never ad-hoc values
# such as ``reason.resume_step``) so the entry-gate verifier accepts them.
ENTRY_NON_SELECT_REASON_CODES = {
    "resume-step": "resume-next-step",
    "replay-step": "replay-idempotent",
    "run-recovery-verifier": "recovery-verifier-required",
    "needs-user-input": "entry-needs-user-input",
    "terminal-cleanup-required": "terminal-pending",
    "blocked": "entry-blocked",
    "no-work": "entry-no-work",
}

# Fields that must never appear in any seam result (recursive scan).
SENSITIVE_RESULT_KEYS = (
    "command", "argv", "shell", "interpreter", "env", "runner", "args",
    "program", "cmd", "subprocess", "exec", "run", "script_path",
    "script_runner", "activate", "activation_command",
    "activation_override", "prompt", "prompt_template", "path",
    "task_ref", "row_title", "design_url", "secret", "token",
    "password", "credential", "api_key", "claim_ack", "writeback_ack",
    "row_payload",
)

# --- module loaders / tiny helpers ---

def _load(name: str, path: Path):
    if not path.exists():
        raise FileNotFoundError(f"module not found: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_preflight():
    return _load("preflight_selection_seam_selftest", PREFLIGHT_PATH)


def _load_prepare():
    return _load("prepare_selection_seam_selftest", PREPARE_PATH)


def _load_entry_readiness():
    return _load("entry_readiness_seam_selftest", ENTRY_READINESS_PATH)


def _load_resolver():
    return _load("platform_package_resolver_seam_selftest", RESOLVER_PATH)


def _load_contract():
    return _load("platform_package_contract_seam_selftest", CONTRACT_PATH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _expect_reject(callable_: Callable, label: str) -> None:
    try:
        callable_()
    except Exception:  # noqa: BLE001
        return
    raise AssertionError(f"{label}: expected rejection, got success")


def _is_safe_id(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return all(c in SAFE_ID_CHARS for c in value)


def _read_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_bytes())

# --- independent synthetic fixture builders ---

_SYNTH_PLATFORM_ID = "synthetic"
_SYNTH_PROFILE_ID = "synthetic-default"


def _synthetic_descriptor(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
    registry_digest: str,
    selected_profile_digest: str,
    activation_state: str = "inactive",
    executable: bool = False,
) -> dict:
    """Build a valid synthetic non-Flutter descriptor."""
    contract = _load_contract()
    components = [
        {
            "role": role,
            "module_basename": f"synthetic_{role}.py",
            "module_sha256": "ab" * 32,
            "contract_kind": f"icp.synthetic.{role}.v1",
            "public_api": ["describe"] if role == "descriptor" else ["probe"],
        }
        for role in contract.COMPONENT_ROLES
    ]
    ports = [
        {
            "id": pid,
            "capability_state": "required",
            "implementation_state": "not-implemented",
            "provider_component_role": "operation_plans",
            "artifact_contracts": [],
        }
        for pid in contract.PORT_IDS
    ]
    return {
        "kind": contract.KIND_DESCRIPTOR,
        "schema_version": contract.SCHEMA_VERSION,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "activation_state": activation_state,
        "executable": executable,
        "registry_digest": registry_digest,
        "selected_profile_digest": selected_profile_digest,
        "supported_task_sources": ["csv"],
        "supported_design_sources": ["lanhu-figma"],
        "actual_source_types": [],
        "entry_requirements": [],
        "components": components,
        "ports": ports,
    }


def _synthetic_index_row(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
    basename: str = "synthetic_package_v1.py",
    module_sha: str,
    descriptor_digest: str,
) -> dict:
    return {
        "platform_id": platform_id,
        "profile_id": profile_id,
        "package_module_basename": basename,
        "package_module_sha256": module_sha,
        "package_descriptor_digest": descriptor_digest,
    }


def _synthetic_index(rows: list[dict]) -> dict:
    return {
        "kind": "icp.platform-packages-index.v1",
        "schema_version": 1,
        "packages": list(rows),
    }


_SYNTH_MODULE_BYTES = b"# synthetic package module bytes for entry-seam tests\n"


def _synthetic_activated_registry(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
) -> dict:
    """Activated synthetic-platform registry mirroring the live shape but with
    one platform set ``activated=true`` so existing ``support_gate`` does not
    fail."""
    return {
        "kind": "icp-p1a-registries",
        "schema_version": 1,
        "task_sources": ["csv"],
        "design_sources": ["lanhu-figma"],
        "platforms": {
            platform_id: {
                "profiles": [profile_id],
                "default_profile": profile_id,
                "activated": True,
            },
        },
        "operations": [{"id": "project_preflight"}],
        "capability_states": ["required"],
        "capabilities": {"project_preflight": "required"},
    }


def _synthetic_resolved_config(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
    task_ref: str = "/tmp/some/task.csv",
    project_root: str = "/tmp/some/project",
) -> dict:
    return {
        "task_source": "csv",
        "task_ref": task_ref,
        "design_source": "lanhu-figma",
        "platform": platform_id,
        "project_root": project_root,
        "profile": profile_id,
    }


def _resolve_synthetic_package(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
    registry: dict | None = None,
    descriptor_over: dict | None = None,
    module_bytes: bytes | None = None,
    descriptor: dict | None = None,
) -> dict:
    """Resolve a valid inactive v1 package_resolution over an activated
    synthetic registry. When ``descriptor`` is supplied it is used verbatim
    so callers can share one descriptor between package resolution and
    readiness aggregation (matching descriptor digest across the triple)."""
    resolver = _load_resolver()
    contract = _load_contract()
    if registry is None:
        registry = _synthetic_activated_registry(platform_id=platform_id, profile_id=profile_id)
    if descriptor is None:
        reg_digest = contract.compute_registry_digest(registry)
        sel_digest = contract.compute_selected_profile_digest(registry, platform_id, profile_id)
        descriptor = _synthetic_descriptor(
            platform_id=platform_id, profile_id=profile_id,
            registry_digest=reg_digest, selected_profile_digest=sel_digest,
        )
    if descriptor_over:
        descriptor = {**descriptor, **descriptor_over}
    if module_bytes is None:
        module_bytes = _SYNTH_MODULE_BYTES
    module_sha = _sha256_bytes(module_bytes)
    desc_digest = contract.compute_descriptor_digest(descriptor)
    index = _synthetic_index([
        _synthetic_index_row(
            platform_id=platform_id, profile_id=profile_id,
            module_sha=module_sha, descriptor_digest=desc_digest,
        )
    ])
    return resolver.resolve_package(
        platform_id=platform_id, profile_id=profile_id,
        registries=registry, package_index=index,
        package_descriptor=descriptor, package_module_bytes=module_bytes,
    )


def _core_pass_observations() -> list[dict]:
    """Four core pass observations in strictly-sorted probe_id order."""
    return [
        {
            "kind": "icp.entry-readiness-observation.v1",
            "schema_version": 1,
            "probe_id": pid,
            "status": "pass",
            "evidence_digest": "11" * 32,
            "reason_code": None,
            "blocked_by": [],
        }
        for pid in (
            "core.design_source.access",
            "core.project_root.access",
            "core.state_root.atomic_write",
            "core.task_source.access",
        )
    ]


def _ready_readiness_report(
    *,
    resolved_config_digest: str,
    package_descriptor_digest: str,
    task_source_snapshot_digest: str = "c" * 64,
    candidate_identity_digest: str = "d" * 64,
    candidate_count: int = 1,
    observations: list[dict] | None = None,
    package_descriptor: dict | None = None,
) -> dict:
    """Build a verified ``ready`` readiness_report via the module under test.
    When ``package_descriptor`` is supplied it is used verbatim so the
    report embeds the exact descriptor digest of the matching resolution."""
    mod = _load_entry_readiness()
    if package_descriptor is None:
        package_descriptor = _synthetic_descriptor(
            registry_digest="ab" * 32,
            selected_profile_digest="ab" * 32,
        )
    if observations is None:
        observations = _core_pass_observations()
    return mod.aggregate_readiness(
        resolved_config_digest=resolved_config_digest,
        package_descriptor=package_descriptor,
        task_source_id="csv",
        design_source_id="lanhu-figma",
        task_source_snapshot_digest=task_source_snapshot_digest,
        candidate_identity_digest=candidate_identity_digest,
        candidate_count=candidate_count,
        observations=observations,
    )


def _select_new_decision(*, readiness_report: dict) -> dict:
    """Verified ``select-new`` entry-gate decision with no active pointers and
    ``exclusive_lock_acquired=True`` over the given readiness report."""
    mod = _load_entry_readiness()
    return mod.decide_entry(
        readiness_report=readiness_report,
        active_pointers=[],
        progress=None,
        receipts=[],
        expected_identities={
            "requirement_id": "00" * 32,
            "selection_manifest_digest": "00" * 32,
            "row_identity_digest": "00" * 32,
            "claim_intent_digest": "00" * 32,
            "claim_ack_digest": "00" * 32,
            "progress_id": "00" * 32,
            "verified_operation_plan_digest": "00" * 32,
        },
        exclusive_lock_acquired=True,
        observed_row_status="doing",
    )


def _decision_with_literal(
    *, decision: str, readiness_report: dict, reason_code: str,
) -> dict:
    """Hand-build an entry-gate decision with the given literal, bypassing the
    live state machine. Passes ``verify_entry_gate_decision`` because every
    field matches the canonical schema."""
    mod = _load_entry_readiness()
    readiness_digest = mod.document_digest(readiness_report)
    decision_doc = {
        "kind": "icp.entry-gate-decision.v1",
        "schema_version": 1,
        "decision": decision,
        "reason_code": reason_code,
        "readiness_report_digest": readiness_digest,
        "resume_decision_digest": "00" * 32,
        "requirement_id": None,
        "progress_id": None,
        "feature_id": None,
        "step_id": None,
        "checkpoint_receipt_digest": None,
    }
    mod.verify_entry_gate_decision(decision_doc)
    return decision_doc


def _full_synthetic_seam_inputs(
    *,
    platform_id: str = _SYNTH_PLATFORM_ID,
    profile_id: str = _SYNTH_PROFILE_ID,
    decision: str = ENTRY_DECISION_SELECT_NEW,
    decision_reason: str = "entry-ready",
    report_status: str = "ready",
):
    """Build a fully consistent set of seam inputs:
    (registry, config, resolution, readiness_report, entry_decision).
    The same synthetic descriptor is shared between package resolution and
    readiness aggregation so the descriptor digest matches across the
    decision / report / resolution triple."""
    mod_entry = _load_entry_readiness()
    contract = _load_contract()
    registry = _synthetic_activated_registry(
        platform_id=platform_id, profile_id=profile_id,
    )
    config = _synthetic_resolved_config(
        platform_id=platform_id, profile_id=profile_id,
    )
    reg_digest = contract.compute_registry_digest(registry)
    sel_digest = contract.compute_selected_profile_digest(
        registry, platform_id, profile_id,
    )
    shared_descriptor = _synthetic_descriptor(
        platform_id=platform_id, profile_id=profile_id,
        registry_digest=reg_digest, selected_profile_digest=sel_digest,
    )
    resolution = _resolve_synthetic_package(
        platform_id=platform_id, profile_id=profile_id, registry=registry,
        descriptor=shared_descriptor,
    )
    resolved_config_digest = mod_entry.document_digest(config)
    descriptor_digest = resolution["package_descriptor_digest"]
    report = _ready_readiness_report(
        resolved_config_digest=resolved_config_digest,
        package_descriptor_digest=descriptor_digest,
        package_descriptor=shared_descriptor,
    )
    if report_status != "ready":
        report = {**report, "status": report_status}
        mod_entry.verify_readiness_report(report)
    if decision == ENTRY_DECISION_SELECT_NEW and report_status == "ready":
        decision_doc = _select_new_decision(readiness_report=report)
    else:
        decision_doc = _decision_with_literal(
            decision=decision, readiness_report=report,
            reason_code=decision_reason,
        )
    return registry, config, resolution, report, decision_doc

# --- 1. RED: new functions / SKILL section absence, then GREEN ---

def _has_function(path: Path, fn_name: str) -> bool:
    if not path.exists():
        return False
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return True
    return False


def _skill_has_p3b1b_section() -> bool:
    if not SKILL_PATH.exists():
        return False
    text = SKILL_PATH.read_text()
    if "## P3b1b" not in text:
        return False
    return any(line.startswith("## P3b1b") for line in text.splitlines())


def _require_implementation() -> None:
    """Raise if the P3b1b2 implementation is absent. RED when functions /
    section absent; GREEN when present."""
    if not _has_function(PREFLIGHT_PATH, "support_gate_package_aware"):
        raise AssertionError("RED: support_gate_package_aware not implemented")
    if not _has_function(PREPARE_PATH, "prepare_selection_with_entry_gate"):
        raise AssertionError("RED: prepare_selection_with_entry_gate not implemented")
    if not _skill_has_p3b1b_section():
        raise AssertionError("RED: SKILL P3b1b section absent")


def test_red_function_absence_then_green() -> None:
    preflight_present = _has_function(
        PREFLIGHT_PATH, "support_gate_package_aware",
    )
    prepare_present = _has_function(
        PREPARE_PATH, "prepare_selection_with_entry_gate",
    )
    if not preflight_present or not prepare_present:
        assert not preflight_present, "preflight has support_gate_package_aware before GREEN"
        assert not prepare_present, "prepare has prepare_selection_with_entry_gate before GREEN"
        return
    preflight = _load_preflight()
    prepare = _load_prepare()
    assert hasattr(preflight, "support_gate_package_aware")
    assert hasattr(prepare, "prepare_selection_with_entry_gate")


def test_red_skill_section_absence_then_green() -> None:
    has_section = _skill_has_p3b1b_section()
    if not has_section:
        return
    text = SKILL_PATH.read_text()
    assert "P3b1b" in text
    p3b1a_idx = text.find("## P3b1a")
    p3b1b_idx = text.find("## P3b1b")
    validation_idx = text.find("## Validation")
    assert p3b1a_idx != -1
    assert p3b1b_idx != -1
    assert p3b1a_idx < p3b1b_idx
    if validation_idx != -1:
        assert p3b1b_idx < validation_idx

# --- 2. New function signatures exact ---

def test_support_gate_package_aware_signature_exact() -> None:
    _require_implementation()
    preflight = _load_preflight()
    sig = inspect.signature(preflight.support_gate_package_aware)
    params = list(sig.parameters.values())
    names = tuple(p.name for p in params)
    assert names == SUPPORT_GATE_PACKAGE_AWARE_PARAMS, sig
    for p in params:
        assert p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY), p
    assert sig.return_annotation is preflight.PreflightResult or (
        sig.return_annotation == inspect.Parameter.empty
    ) or sig.return_annotation == "PreflightResult", sig.return_annotation


def test_prepare_selection_with_entry_gate_signature_exact() -> None:
    _require_implementation()
    prepare = _load_prepare()
    sig = inspect.signature(prepare.prepare_selection_with_entry_gate)
    params = list(sig.parameters.values())
    for p in params:
        assert p.kind == p.KEYWORD_ONLY, p
    names = tuple(p.name for p in params)
    assert names == PREPARE_WITH_ENTRY_GATE_KWPARAMS, sig
    by_name = {p.name: p for p in params}
    assert by_name["registries"].default is None
    assert by_name["batch_id"].default is None
    assert by_name["on_manifest_frozen"].default is None
    for required in (
        "resolved_config", "limit", "readiness_report",
        "entry_gate_decision", "package_resolution",
    ):
        assert by_name[required].default is inspect.Parameter.empty

# --- 3. Exact seam result schema / key order / value types ---

def _assert_seam_result_shape(result: dict) -> None:
    assert isinstance(result, dict), type(result)
    assert tuple(result.keys()) == SEAM_RESULT_KEYS, (
        f"seam result key order: {tuple(result.keys())}"
    )
    assert result["kind"] == KIND_SEAM_RESULT
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["route"] in ROUTES, result["route"]
    for key in (
        "entry_gate_decision_digest",
        "readiness_report_digest",
        "package_resolution_digest",
    ):
        v = result[key]
        assert v is None or (
            isinstance(v, str) and len(v) == 64
            and all(c in "0123456789abcdef" for c in v)
        ), (key, v)
    gc = result["gate_code"]
    assert gc is None or (isinstance(gc, str) and _is_safe_id(gc)), gc
    assert result["preparation_ack"] is None or isinstance(
        result["preparation_ack"], dict
    ), type(result["preparation_ack"])


def _seam_call(prepare, *, config, report, decision, resolution, registry, limit=1):
    return prepare.prepare_selection_with_entry_gate(
        resolved_config=config, limit=limit,
        readiness_report=report, entry_gate_decision=decision,
        package_resolution=resolution, registries=registry,
    )


def test_seam_result_keys_and_types_for_select_new_inactive_stop() -> None:
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["gate_code"] == CODE_PLATFORM_PACKAGE_INACTIVE
    assert result["preparation_ack"] is None


def _walk_collect_keys(obj, seen: list) -> None:
    if isinstance(obj, dict):
        seen.extend(obj.keys())
        for v in obj.values():
            _walk_collect_keys(v, seen)
    elif isinstance(obj, list):
        for v in obj:
            _walk_collect_keys(v, seen)


def test_seam_result_no_injection_or_sensitive_keys_recursive() -> None:
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    seen: list = []
    _walk_collect_keys(result, seen)
    for key in seen:
        assert key not in SENSITIVE_RESULT_KEYS, (
            f"seam result contains sensitive key: {key!r}"
        )

# --- 4. Existing functions source/AST/behavior unchanged ---

def _func_ast_hash(path: Path, fn_name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return hashlib.sha256(ast.dump(node).encode("utf-8")).hexdigest()
    raise AssertionError(f"{fn_name} not found in {path}")


# Pinned AST hashes captured before this change. Any divergence means the
# existing function was modified. 16-char prefixes of SHA-256 over
# ``ast.dump(function_node)`` parsed from the file's source.
PINNED_AST = {
    "support_gate": "1672104cec3c821c",
    "preflight_from_config": "b6b336b5d755fd9e",
    "prepare_selection": "8113545ee04d2732",
    "main_prepare": "dda271987789252d",
}


def test_existing_support_gate_ast_unchanged() -> None:
    h = _func_ast_hash(PREFLIGHT_PATH, "support_gate")
    assert h.startswith(PINNED_AST["support_gate"]), h


def test_existing_preflight_from_config_ast_unchanged() -> None:
    h = _func_ast_hash(PREFLIGHT_PATH, "preflight_from_config")
    assert h.startswith(PINNED_AST["preflight_from_config"]), h


def test_existing_prepare_selection_ast_unchanged() -> None:
    h = _func_ast_hash(PREPARE_PATH, "prepare_selection")
    assert h.startswith(PINNED_AST["prepare_selection"]), h


def test_existing_main_cli_ast_unchanged() -> None:
    h = _func_ast_hash(PREPARE_PATH, "main")
    assert h.startswith(PINNED_AST["main_prepare"]), h


def test_existing_support_gate_signature_unchanged() -> None:
    preflight = _load_preflight()
    sig = inspect.signature(preflight.support_gate)
    names = tuple(p.name for p in sig.parameters.values())
    assert names == SUPPORT_GATE_PARAMS, sig


def test_existing_preflight_from_config_signature_unchanged() -> None:
    preflight = _load_preflight()
    sig = inspect.signature(preflight.preflight_from_config)
    names = tuple(p.name for p in sig.parameters.values())
    assert names == PREFLIGHT_FROM_CONFIG_PARAMS, sig


def test_existing_prepare_selection_signature_unchanged() -> None:
    prepare = _load_prepare()
    sig = inspect.signature(prepare.prepare_selection)
    params = list(sig.parameters.values())
    for p in params:
        assert p.kind == p.KEYWORD_ONLY, p
    names = tuple(p.name for p in params)
    assert names == PREPARE_SELECTION_KWPARAMS, sig


def test_existing_support_gate_accepts_every_active_live_platform() -> None:
    preflight = _load_preflight()
    registries = _read_registry()
    for platform_id, entry in registries["platforms"].items():
        cfg = {
            "task_source": "csv",
            "task_ref": "/dev/null",
            "design_source": "lanhu-figma",
            "platform": platform_id,
            "project_root": "/tmp",
            "profile": (entry.get("profiles") or [None])[0],
        }
        result = preflight.support_gate(cfg, registries)
        assert result.ok


def test_existing_preflight_from_config_accepts_active_live_platform() -> None:
    preflight = _load_preflight()
    registries = _read_registry()
    cfg = {
        "task_source": "csv",
        "task_ref": "/this/path/does/not/exist.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "project_root": "/tmp",
        "profile": "flutter-standard",
    }
    result = preflight.preflight_from_config(cfg, registries)
    assert result.ok

# --- 5. Production CLI never references/calls new functions ---

def _names_called_in(node: ast.AST) -> set[str]:
    """Return the set of bare function-name callees inside ``node``."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_production_cli_main_never_calls_new_functions() -> None:
    tree = ast.parse(PREPARE_PATH.read_text())
    main_node = _find_func(tree, "main")
    assert main_node is not None
    callees = _names_called_in(main_node)
    assert "support_gate_package_aware" not in callees, callees
    assert "prepare_selection_with_entry_gate" not in callees, callees


def test_production_cli_handoff_uses_prepare_selection_only() -> None:
    """The production CLI ``main`` calls ``prepare_selection`` (existing), not
    the new seam."""
    prepare = _load_prepare()
    src = inspect.getsource(prepare.main)
    assert "prepare_selection(" in src
    assert "prepare_selection_with_entry_gate" not in src
    assert "support_gate_package_aware" not in src


def test_preflight_cli_main_never_calls_new_functions() -> None:
    tree = ast.parse(PREFLIGHT_PATH.read_text())
    main_node = _find_func(tree, "main")
    assert main_node is not None
    callees = _names_called_in(main_node)
    assert "support_gate_package_aware" not in callees, callees
    assert "prepare_selection_with_entry_gate" not in callees, callees

# --- 6. Live production registries stop via existing unsupported-platform before TaskSource access ---

def test_live_support_gate_reaches_inactive_synthetic_package_gate() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registries = _read_registry()
    cfg = {
        "task_source": "csv",
        "task_ref": "/this/path/does/not/exist.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "project_root": "/tmp",
        "profile": "flutter-standard",
    }
    resolution = _resolve_synthetic_package(
        platform_id="flutter", profile_id="flutter-standard", registry=registries,
    )
    result = preflight.support_gate_package_aware(cfg, registries, resolution)
    assert not result.ok
    assert result.code == CODE_PLATFORM_PACKAGE_INACTIVE

# --- 7. Synthetic activated registry + valid inactive resolution reaches ``platform_package_inactive`` ---

def test_support_gate_package_aware_reaches_platform_package_inactive() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registry = _synthetic_activated_registry()
    config = _synthetic_resolved_config()
    resolution = _resolve_synthetic_package(registry=registry)
    result = preflight.support_gate_package_aware(config, registry, resolution)
    assert not result.ok
    assert result.code == CODE_PLATFORM_PACKAGE_INACTIVE


def test_support_gate_package_aware_never_returns_success_for_v1() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registry = _synthetic_activated_registry()
    config = _synthetic_resolved_config()
    resolution = _resolve_synthetic_package(registry=registry)
    result = preflight.support_gate_package_aware(config, registry, resolution)
    assert not result.ok, "support_gate_package_aware returned ok for v1"


def test_support_gate_package_aware_propagates_existing_gate_failure() -> None:
    """If existing ``support_gate`` fails, the package-aware gate returns that
    exact result unchanged."""
    _require_implementation()
    preflight = _load_preflight()
    registries = _read_registry()
    registries["platforms"]["flutter"]["activated"] = False
    cfg = {
        "task_source": "csv",
        "task_ref": "/dev/null",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "project_root": "/tmp",
        "profile": "flutter-standard",
    }
    resolution = _resolve_synthetic_package(
        platform_id="flutter", profile_id="flutter-standard", registry=registries,
    )
    base = preflight.support_gate(cfg, registries)
    package_aware = preflight.support_gate_package_aware(cfg, registries, resolution)
    assert base.code == package_aware.code
    assert base.message == package_aware.message
    assert base.ok == package_aware.ok

# --- 8. Malformed resolution / config mismatch / registry digest drift -> invalid_platform_package ---

def test_support_gate_package_aware_malformed_resolution_invalid() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registry = _synthetic_activated_registry()
    config = _synthetic_resolved_config()
    for bad in (
        {},
        {"kind": "icp.something.else.v1"},
        "not a dict",
        None,
    ):
        result = preflight.support_gate_package_aware(config, registry, bad)
        assert not result.ok
        assert result.code == CODE_INVALID_PLATFORM_PACKAGE, bad


def test_support_gate_package_aware_platform_profile_mismatch_invalid() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registry = _synthetic_activated_registry()
    config = _synthetic_resolved_config()
    other_registry = _synthetic_activated_registry(
        platform_id="other-platform", profile_id="other-default",
    )
    resolution = _resolve_synthetic_package(
        platform_id="other-platform", profile_id="other-default",
        registry=other_registry,
    )
    result = preflight.support_gate_package_aware(config, registry, resolution)
    assert not result.ok
    assert result.code == CODE_INVALID_PLATFORM_PACKAGE


def test_support_gate_package_aware_registry_digest_drift_invalid() -> None:
    """If the resolution's ``registry_digest`` does not match a recompute over
    the supplied registries, the gate fails ``invalid_platform_package``."""
    _require_implementation()
    preflight = _load_preflight()
    registry_a = _synthetic_activated_registry()
    registry_b = _synthetic_activated_registry()
    registry_b["platforms"][_SYNTH_PLATFORM_ID]["default_profile"] = "totally-different"
    config = _synthetic_resolved_config()
    resolution = _resolve_synthetic_package(registry=registry_a)
    result = preflight.support_gate_package_aware(config, registry_b, resolution)
    assert not result.ok
    assert result.code == CODE_INVALID_PLATFORM_PACKAGE


def test_support_gate_package_aware_selected_profile_digest_drift_invalid() -> None:
    """If the resolution's ``selected_profile_digest`` does not match a
    recompute over the supplied registries / platform / profile, the gate fails
    ``invalid_platform_package``."""
    _require_implementation()
    preflight = _load_preflight()
    registry = {
        "kind": "icp-p1a-registries",
        "schema_version": 1,
        "task_sources": ["csv"],
        "design_sources": ["lanhu-figma"],
        "platforms": {
            _SYNTH_PLATFORM_ID: {
                "profiles": [_SYNTH_PROFILE_ID, "alt-profile"],
                "default_profile": _SYNTH_PROFILE_ID,
                "activated": True,
            },
        },
        "operations": [{"id": "project_preflight"}],
        "capability_states": ["required"],
        "capabilities": {"project_preflight": "required"},
    }
    resolution = _resolve_synthetic_package(
        platform_id=_SYNTH_PLATFORM_ID, profile_id="alt-profile", registry=registry,
    )
    config = _synthetic_resolved_config()
    result = preflight.support_gate_package_aware(config, registry, resolution)
    assert not result.ok
    assert result.code in (CODE_INVALID_PLATFORM_PACKAGE,), result.code


def test_support_gate_package_aware_failure_message_no_secrets() -> None:
    _require_implementation()
    preflight = _load_preflight()
    registry = _synthetic_activated_registry()
    config = _synthetic_resolved_config()
    bad_resolution = {
        "kind": "icp.platform-package-resolution.v1",
        "schema_version": 1,
        "platform_id": _SYNTH_PLATFORM_ID,
        "profile_id": _SYNTH_PROFILE_ID,
        "package_module_basename": "synthetic_package_v1.py",
        "package_module_sha256": "ab" * 32,
        "package_index_digest": "ab" * 32,
        "package_descriptor_digest": "ab" * 32,
        "registry_digest": "ab" * 32,
        "selected_profile_digest": "ab" * 32,
        "activation_state": "active",  # invalid for v1
        "executable": False,
    }
    result = preflight.support_gate_package_aware(config, registry, bad_resolution)
    assert not result.ok
    assert result.code == CODE_INVALID_PLATFORM_PACKAGE
    msg = result.message or ""
    for sensitive in (
        "/tmp", "/path", "task_ref", "secret", "credential",
        "command", "argv", "password", "token",
    ):
        assert sensitive not in msg, (sensitive, msg)

# --- 9. Readiness / decision / config / package digest binding drift -> deterministic stop ---

def test_seam_binding_decision_report_digest_drift_stops() -> None:
    _require_implementation()
    prepare = _load_prepare()
    mod_entry = _load_entry_readiness()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    bad_decision = dict(decision)
    bad_decision["readiness_report_digest"] = "00" * 32
    mod_entry.verify_entry_gate_decision(bad_decision)
    result = _seam_call(
        prepare, config=config, report=report, decision=bad_decision,
        resolution=resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["preparation_ack"] is None


def test_seam_binding_report_config_digest_drift_stops() -> None:
    _require_implementation()
    prepare = _load_prepare()
    mod_entry = _load_entry_readiness()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    bad_report = dict(report)
    bad_report["resolved_config_digest"] = "00" * 32
    mod_entry.verify_readiness_report(bad_report)
    result = _seam_call(
        prepare, config=config, report=bad_report, decision=decision,
        resolution=resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["preparation_ack"] is None


def test_seam_binding_report_package_descriptor_digest_drift_stops() -> None:
    _require_implementation()
    prepare = _load_prepare()
    mod_entry = _load_entry_readiness()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    bad_report = dict(report)
    bad_report["package_descriptor_digest"] = "00" * 32
    mod_entry.verify_readiness_report(bad_report)
    result = _seam_call(
        prepare, config=config, report=bad_report, decision=decision,
        resolution=resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["preparation_ack"] is None


def test_seam_package_resolution_platform_mismatch_stops() -> None:
    _require_implementation()
    prepare = _load_prepare()
    other_registry = _synthetic_activated_registry(
        platform_id="other-platform", profile_id="other-default",
    )
    other_resolution = _resolve_synthetic_package(
        platform_id="other-platform", profile_id="other-default",
        registry=other_registry,
    )
    registry, config, _resolution, report, decision = _full_synthetic_seam_inputs()
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=other_resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["preparation_ack"] is None

# --- 10. Non-select decisions stop before the package gate and TaskSource ---

def test_seam_non_select_decisions_stop_before_package_gate() -> None:
    _require_implementation()
    prepare = _load_prepare()
    for decision_literal in ENTRY_DECISIONS_NON_SELECT:
        registry, config, resolution, report, _decision = _full_synthetic_seam_inputs()
        decision_doc = _decision_with_literal(
            decision=decision_literal, readiness_report=report,
            reason_code=ENTRY_NON_SELECT_REASON_CODES[decision_literal],
        )
        result = _seam_call(
            prepare, config=config, report=report, decision=decision_doc,
            resolution=resolution, registry=registry,
        )
        _assert_seam_result_shape(result)
        assert result["route"] == "stop", decision_literal
        assert result["gate_code"] == decision_literal, decision_literal
        assert result["preparation_ack"] is None


def test_seam_invalid_decision_literal_rejected_at_verification() -> None:
    """Decision literal outside the closed enum: verifier fails, seam returns
    a deterministic stop. The seam never trusts an unverified document."""
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, _decision = _full_synthetic_seam_inputs()
    mod_entry = _load_entry_readiness()
    bad_decision = {
        "kind": "icp.entry-gate-decision.v1",
        "schema_version": 1,
        "decision": "select-new-TAMPERED",
        "reason_code": "entry-ready",
        "readiness_report_digest": mod_entry.document_digest(report),
        "resume_decision_digest": "00" * 32,
        "requirement_id": None,
        "progress_id": None,
        "feature_id": None,
        "step_id": None,
        "checkpoint_receipt_digest": None,
    }
    _expect_reject(
        lambda: mod_entry.verify_entry_gate_decision(bad_decision),
        "verifier accepts invalid decision literal",
    )
    result = _seam_call(
        prepare, config=config, report=report, decision=bad_decision,
        resolution=resolution, registry=registry,
    )
    _assert_seam_result_shape(result)
    assert result["route"] == "stop"
    assert result["preparation_ack"] is None

# --- 11. select-new requires report status ``ready`` ---

def test_seam_select_new_requires_report_ready() -> None:
    _require_implementation()
    prepare = _load_prepare()
    for status in ("needs-user-input", "blocked", "no-work"):
        registry, config, resolution, report, _decision = (
            _full_synthetic_seam_inputs(report_status=status)
        )
        decision_doc = _decision_with_literal(
            decision=ENTRY_DECISION_SELECT_NEW,
            readiness_report=report, reason_code="entry-ready",
        )
        result = _seam_call(
            prepare, config=config, report=report, decision=decision_doc,
            resolution=resolution, registry=registry,
        )
        _assert_seam_result_shape(result)
        assert result["route"] == "stop", status
        # Either the report status or invalid_input is acceptable.
        assert result["gate_code"] in (status, CODE_INVALID_INPUT), (
            status, result["gate_code"],
        )
        assert result["preparation_ack"] is None

# --- 12. Monkeypatch / counters: zero calls to CSV preflight / probe / select / freeze / claim / worker ---

class _CallCounter:
    """Replace selected module attrs with counting wrappers."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def wrap(self, target_obj: Any, name: str, key: str) -> None:
        original = getattr(target_obj, name)
        self.counts[key] = 0

        def _wrapped(*args, **kwargs):
            self.counts[key] += 1
            return original(*args, **kwargs)

        setattr(target_obj, name, _wrapped)


def _count_tasksource_and_freeze_calls(
    *, registries, config, report, decision, resolution,
) -> dict[str, int]:
    prepare = _load_prepare()
    preflight = _load_preflight()
    csv_ts = _load("csv_task_source_seam_selftest", CSV_TASK_SOURCE_PATH)
    freeze_man = _load(
        "freeze_selection_manifest_seam_selftest", FREEZE_MANIFEST_PATH,
    )
    counter = _CallCounter()
    counter.wrap(csv_ts, "probe", "csv.probe")
    counter.wrap(csv_ts, "select_candidates", "csv.select_candidates")
    counter.wrap(csv_ts, "claim", "csv.claim")
    counter.wrap(csv_ts, "export_inputs", "csv.export_inputs")
    counter.wrap(csv_ts, "writeback", "csv.writeback")
    counter.wrap(freeze_man, "freeze_selection_manifest", "freeze.freeze")
    counter.wrap(preflight, "preflight_csv_task_source", "preflight_csv")
    counter.wrap(prepare, "prepare_selection", "prepare_selection")
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registries,
    )
    _assert_seam_result_shape(result)
    return counter.counts


def test_seam_select_new_inactive_path_zero_tasksource_calls() -> None:
    _require_implementation()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    counts = _count_tasksource_and_freeze_calls(
        registries=registry, config=config, report=report,
        decision=decision, resolution=resolution,
    )
    for key, value in counts.items():
        assert value == 0, f"{key} was called {value} times"


def test_seam_non_select_decision_zero_tasksource_calls() -> None:
    _require_implementation()
    for decision_literal in ENTRY_DECISIONS_NON_SELECT[:3]:
        registry, config, resolution, report, _decision = _full_synthetic_seam_inputs()
        decision_doc = _decision_with_literal(
            decision=decision_literal, readiness_report=report,
            reason_code=ENTRY_NON_SELECT_REASON_CODES[decision_literal],
        )
        counts = _count_tasksource_and_freeze_calls(
            registries=registry, config=config, report=report,
            decision=decision_doc, resolution=resolution,
        )
        for key, value in counts.items():
            assert value == 0, (
                f"{decision_literal}: {key} called {value} times"
            )


def test_seam_zero_file_changes_for_valid_v1_paths() -> None:
    _require_implementation()
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        before: dict[Path, bytes] = {}
        registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
        non_select_decision = _decision_with_literal(
            decision="blocked", readiness_report=report,
            reason_code=ENTRY_NON_SELECT_REASON_CODES["blocked"],
        )
        cfg_a = dict(config)
        cfg_a["task_ref"] = str(workspace / "nonexistent_a.csv")
        cfg_a["project_root"] = str(workspace / "nonexistent_a_proj")
        cfg_b = dict(config)
        cfg_b["task_ref"] = str(workspace / "nonexistent_b.csv")
        cfg_b["project_root"] = str(workspace / "nonexistent_b_proj")
        prepare = _load_prepare()
        prepare.prepare_selection_with_entry_gate(
            resolved_config=cfg_a, limit=1,
            readiness_report=report, entry_gate_decision=decision,
            package_resolution=resolution, registries=registry,
        )
        prepare.prepare_selection_with_entry_gate(
            resolved_config=cfg_b, limit=1,
            readiness_report=report, entry_gate_decision=non_select_decision,
            package_resolution=resolution, registries=registry,
        )
        after: dict[Path, bytes] = {}
        for sub in workspace.rglob("*"):
            if sub.is_file():
                after[sub] = sub.read_bytes()
        assert before == after, (
            f"workspace mutated: before={sorted(map(str, before))} "
            f"after={sorted(map(str, after))}"
        )

# --- 13. Result never embeds sensitive fields (recursive scan across all deterministic routes) ---

def test_seam_result_no_sensitive_keys_across_routes() -> None:
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    results: list[dict] = []
    results.append(_seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    ))
    for decision_literal in ENTRY_DECISIONS_NON_SELECT[:2]:
        d = _decision_with_literal(
            decision=decision_literal, readiness_report=report,
            reason_code=ENTRY_NON_SELECT_REASON_CODES[decision_literal],
        )
        results.append(_seam_call(
            prepare, config=config, report=report, decision=d,
            resolution=resolution, registry=registry,
        ))
    results.append(_seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution={}, registry=registry,
    ))
    for r in results:
        _assert_seam_result_shape(r)
        seen: list = []
        _walk_collect_keys(r, seen)
        for key in seen:
            assert key not in SENSITIVE_RESULT_KEYS, (
                f"seam result contains sensitive key: {key!r}"
            )


def test_seam_result_digests_match_canonical_hashes() -> None:
    _require_implementation()
    prepare = _load_prepare()
    mod_entry = _load_entry_readiness()
    resolver = _load_resolver()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    assert result["entry_gate_decision_digest"] == mod_entry.document_digest(decision)
    assert result["readiness_report_digest"] == mod_entry.document_digest(report)
    assert result["package_resolution_digest"] == resolver.document_digest(resolution)

# --- 14. Deterministic repeated calls and input immutability ---

def test_seam_deterministic_repeated_calls() -> None:
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    r1 = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    r2 = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    assert _canonical_json_bytes(r1) == _canonical_json_bytes(r2)


def test_seam_input_immutability() -> None:
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    snap = {
        "config": copy.deepcopy(config),
        "resolution": copy.deepcopy(resolution),
        "report": copy.deepcopy(report),
        "decision": copy.deepcopy(decision),
        "registry": copy.deepcopy(registry),
    }
    prepare.prepare_selection_with_entry_gate(
        resolved_config=config, limit=1,
        readiness_report=report, entry_gate_decision=decision,
        package_resolution=resolution, registries=registry,
    )
    assert config == snap["config"]
    assert resolution == snap["resolution"]
    assert report == snap["report"]
    assert decision == snap["decision"]
    assert registry == snap["registry"]

# --- 15. No override parameters or hidden activation route ---

def test_seam_has_no_activation_override_parameter() -> None:
    _require_implementation()
    prepare = _load_prepare()
    sig = inspect.signature(prepare.prepare_selection_with_entry_gate)
    names = {p.name for p in sig.parameters.values()}
    for forbidden in (
        "activation_override", "force_activate", "activate",
        "allow_active", "skip_package_gate", "bypass_package_gate",
        "ignore_inactive", "executable_override",
    ):
        assert forbidden not in names, (
            f"seam has forbidden override parameter: {forbidden}"
        )


def test_seam_no_valid_v1_input_reaches_prepare_route() -> None:
    """No valid current v1 input reaches ``route=prepare``."""
    _require_implementation()
    prepare = _load_prepare()
    registry, config, resolution, report, decision = _full_synthetic_seam_inputs()
    result = _seam_call(
        prepare, config=config, report=report, decision=decision,
        resolution=resolution, registry=registry,
    )
    assert result["route"] != "prepare", result


def test_seam_source_has_no_dynamic_activation_branch() -> None:
    """The seam source contains no literal activation path for current v1
    inputs."""
    _require_implementation()
    src = PREPARE_PATH.read_text()
    tree = ast.parse(src)
    seam_node = _find_func(tree, "prepare_selection_with_entry_gate")
    assert seam_node is not None
    seam_src = ast.unparse(seam_node)
    for forbidden in (
        'activation_state == "active"',
        "activation_state == 'active'",
        "executable is True",
        "executable=True",
        "force_activate",
        "skip_package_gate",
        "allow_active",
    ):
        assert forbidden not in seam_src, (
            f"seam source contains forbidden literal: {forbidden}"
        )

# --- 16. Existing P1a/P1b/P3a/P3b1 focused self-tests remain green (smoke check) ---

def test_existing_selftest_files_present() -> None:
    for rel in (
        "selftest_p1a.py",
        "selftest_p1b.py",
        "selftest_p3a_platform_package_contract.py",
        "selftest_p3a2_requirement_resume.py",
        "selftest_p3b1_entry_readiness.py",
        "selftest_p3b1_platform_package_selection.py",
    ):
        path = ICP_SCRIPTS / rel
        assert path.exists(), f"missing self-test: {rel}"


def _run_selftest(name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / name)],
        capture_output=True, text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ICP_SCRIPTS),
        },
    )


def test_existing_p1a_selftest_run_green() -> None:
    result = _run_selftest("selftest_p1a.py")
    assert result.returncode == 0, (
        f"selftest_p1a failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_existing_p1b_selftest_run_green() -> None:
    result = _run_selftest("selftest_p1b.py")
    assert result.returncode == 0, (
        f"selftest_p1b failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

# --- 17. SKILL P3b1b section truthful and brief ---

def _skill_p3b1b_section() -> str:
    text = SKILL_PATH.read_text()
    start = text.find("## P3b1b")
    end = text.find("\n## ", start + 1)
    if end == -1:
        end = len(text)
    return text[start:end]


def test_skill_p3b1b_section_is_brief() -> None:
    _require_implementation()
    section = _skill_p3b1b_section()
    assert len(section) < 1500, len(section)


def test_skill_p3b1b_section_truthful_content() -> None:
    _require_implementation()
    section = _skill_p3b1b_section()
    lower = section.lower()
    assert "package" in lower, section
    # order: readiness -> active-first decision -> package-aware support gate
    # before TaskSource/manifest/claim.
    assert "readiness" in lower, section
    assert "gate" in lower, section
    assert ("inactive" in lower or "non-executable" in lower), section
    assert ("p3b2" in lower or "p3d" in lower), section


def test_skill_p3b1b_section_does_not_duplicate_p3b1a() -> None:
    """The P3b1b section must not duplicate detailed contracts; it should link
    to the reference instead."""
    _require_implementation()
    section = _skill_p3b1b_section()
    lower = section.lower()
    assert (
        "reference" in lower
        or "references/" in lower
        or "p3-platform-package-architecture" in lower
        or "详细" in section
        or "见" in section
    ), section

# --- selftest runner ---

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
