#!/usr/bin/env python3
"""ICP P3b1a entry-readiness + active-first gate focused RED -> GREEN self-test.

Covers the pure P3b1a module ``entry_readiness_v1.py`` and the
canonical contract reference ``icp/references/entry-readiness-v1.md``.
Every platform remains inactive; this self-test performs zero
filesystem I/O, locking, CAS, claim, writeback, probe execution, or
package selection. It uses one short subprocess only for the
import-freshness smoke check.

RED -> GREEN discipline:

1. This self-test was created BEFORE ``entry_readiness_v1.py``. The
   first time it runs, every test that loads the module fails for
   module-absence (``FileNotFoundError``) -- that is the recorded RED
   reason.
2. After ``entry_readiness_v1.py`` is created with the approved
   minimum contract, this self-test must pass cleanly (GREEN).

Coverage matrix (table-driven where possible):

* module absence is RED before implementation; later clean import in a
  fresh subprocess;
* exact closed public API;
* exact ordered schemas for observation / readiness-report /
  entry-gate-decision; missing/extra/reordered keys, kinds, versions,
  enums, digests, safe IDs;
* recursive exact-key injection rejection without substring false
  positives;
* valid core + descriptor happy path;
* absent required observations, multiple missing inputs, stable
  sorting, optional-missing behavior;
* sensitive redaction and secure channel IDs;
* blocked / missing / deferred / no-work / ready precedence;
* invalid deferred dependency and extra / duplicate / reordered
  observations;
* descriptor validation, descriptor/core ID collision, unsupported
  task/design source blockers;
* evidence digest requirements and identity digest drift;
* active-first zero / one / multiple active cases;
* orphan state, lock, identity, row state, terminal cleanup, progress
  tamper, receipt-chain tamper;
* started feature replay-policy mapping and exact step identities;
* ``no-work`` with an active pointer fails closed rather than selecting
  new;
* repeated calls are deterministic and inputs are not mutated;
* AST/source checks: no filesystem/CLI/subprocess/network/environment/
  credential access, no platform-specific imports/literals/branches,
  no import-time I/O, no dynamic import/eval/exec;
* reference and SKILL pointers are truthful.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 \\
        python3 icp/scripts/selftest_p3b1_entry_readiness.py
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
ENTRY_READINESS_PATH = ICP_SCRIPTS / "entry_readiness_v1.py"
REFERENCE_PATH = ICP_ROOT / "references" / "entry-readiness-v1.md"
SKILL_PATH = ICP_ROOT / "SKILL.md"
CONTRACT_PATH = ICP_SCRIPTS / "platforms" / "platform_package_contract_v1.py"
PROGRESS_PATH = ICP_SCRIPTS / "requirement_progress_v1.py"

# Canonical kinds (re-stated independently so a divergence in the
# module under test is caught).
KIND_OBSERVATION = "icp.entry-readiness-observation.v1"
KIND_READINESS_REPORT = "icp.entry-readiness-report.v1"
KIND_ENTRY_GATE_DECISION = "icp.entry-gate-decision.v1"
SCHEMA_VERSION = 1

OBSERVATION_KEYS = (
    "kind", "schema_version", "probe_id", "status",
    "evidence_digest", "reason_code", "blocked_by",
)
READINESS_REPORT_KEYS = (
    "kind", "schema_version", "status",
    "resolved_config_digest", "package_descriptor_digest",
    "task_source_snapshot_digest", "candidate_identity_digest",
    "checks", "missing_user_inputs", "deferred_checks", "blockers",
)
CHECK_KEYS = ("id", "owner", "status", "evidence_digest")
MISSING_USER_INPUT_KEYS = (
    "id", "reason_code", "accepted_shape_id",
    "secure_supply_channel", "sensitive",
)
DEFERRED_CHECK_KEYS = ("id", "blocked_by")
BLOCKER_KEYS = ("code", "scope", "evidence_digest", "remediation_id")
ENTRY_GATE_DECISION_KEYS = (
    "kind", "schema_version", "decision", "reason_code",
    "readiness_report_digest", "resume_decision_digest",
    "requirement_id", "progress_id",
    "feature_id", "step_id", "checkpoint_receipt_digest",
)

OBSERVATION_STATUSES = ("pass", "missing", "blocked", "deferred")
REPORT_STATUSES = ("needs-user-input", "blocked", "no-work", "ready")
ENTRY_DECISIONS = (
    "select-new", "resume-step", "replay-step",
    "run-recovery-verifier", "needs-user-input",
    "terminal-cleanup-required", "blocked", "no-work",
)
OWNERS = ("user", "source", "environment", "platform")

# Fixed digest fixtures: bare 64-char lowercase SHA-256 hex.
DIGEST_RESOLVED_CONFIG = "a" * 64
DIGEST_DESCRIPTOR = "b" * 64
DIGEST_TASKSOURCE_SNAPSHOT = "c" * 64
DIGEST_CANDIDATE_IDENTITY = "d" * 64
DIGEST_EVIDENCE_PASS = "11" * 32
DIGEST_EVIDENCE_PASS_2 = "22" * 32
DIGEST_EVIDENCE_BLOCKED = "33" * 32
DIGEST_SEL_MANIFEST = "44" * 32
DIGEST_ROW_IDENTITY = "55" * 32
DIGEST_CLAIM_ACK = "66" * 32
DIGEST_CLAIM_INTENT = "77" * 32
DIGEST_OP_PLAN = "88" * 32
DIGEST_SEALED_EVIDENCE = "99" * 32

# Substring bearers that must NOT be rejected as injection keys --
# they exist to prove the rejection is exact-key, not substring scan.
LEGIT_VALUE_WITH_SUBSTRING = "design_url_handler"

INJECTION_FIELDS = (
    "command", "argv", "shell", "interpreter", "env", "runner", "args",
    "program", "cmd", "subprocess", "exec", "run", "script_path",
    "script_runner", "activate", "activation_command",
    "activation_override", "prompt", "prompt_template", "path",
    "task_ref", "row_title", "design_url", "secret", "token",
    "password", "credential", "api_key", "claim_ack", "writeback_ack",
    "row_payload",
)

# Fixed core requirement IDs (mirror of the module's private tuple).
# Sorted alphabetically so the default observation list is already in
# the strictly-sorted order required by the aggregator.
CORE_REQUIREMENT_IDS = (
    "core.design_source.access",
    "core.project_root.access",
    "core.state_root.atomic_write",
    "core.task_source.access",
)
CORE_PROBE_IDS = CORE_REQUIREMENT_IDS  # one-to-one in the fixed core.

# Controlled secure-supply channel IDs.
CHANNEL_CREDENTIAL = "channel.credential_supply"
CHANNEL_USER = "channel.user_supply"

# Platform-literal bearers that must NOT appear in the module source.
PLATFORM_LITERALS = (
    "flutter", "dart", "vue", "nextjs", "next.js", "ios", "android",
    "swift", "objc", "kotlin", "java", "gradle", "xcode", "simctl",
    "adb", "pubspec", "lanhu", "figma",
)


# ---------------------------------------------------------------------------
# Module loader and tiny helpers.
# ---------------------------------------------------------------------------


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


def _load_entry_readiness():
    return _load("entry_readiness_v1_selftest", ENTRY_READINESS_PATH)


def _load_contract():
    return _load("platform_package_contract_v1_selftest", CONTRACT_PATH)


def _load_progress():
    return _load("requirement_progress_v1_selftest_b", PROGRESS_PATH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _expect_reject(callable_: Callable, label: str) -> None:
    try:
        callable_()
    except Exception:
        return
    raise AssertionError(f"{label}: expected rejection, got success")


def _reordered(src: dict, key_order: tuple) -> dict:
    out: dict = {}
    for key in reversed(key_order):
        out[key] = src[key]
    return out


# ---------------------------------------------------------------------------
# Independent builders (do not import the module under test).
# ---------------------------------------------------------------------------


def _observation(
    *,
    probe_id: str,
    status: str,
    evidence_digest: str | None = None,
    reason_code: str | None = None,
    blocked_by: list[str] | None = None,
) -> dict:
    if blocked_by is None:
        blocked_by = []
    return {
        "kind": KIND_OBSERVATION,
        "schema_version": SCHEMA_VERSION,
        "probe_id": probe_id,
        "status": status,
        "evidence_digest": evidence_digest,
        "reason_code": reason_code,
        "blocked_by": list(blocked_by),
    }


def _pass_obs(probe_id: str, *, evidence: str = DIGEST_EVIDENCE_PASS) -> dict:
    return _observation(
        probe_id=probe_id, status="pass",
        evidence_digest=evidence, reason_code=None, blocked_by=[],
    )


def _missing_obs(probe_id: str, *, reason: str = "reason.missing") -> dict:
    return _observation(
        probe_id=probe_id, status="missing",
        evidence_digest=None, reason_code=reason, blocked_by=[],
    )


def _blocked_obs(
    probe_id: str, *, reason: str = "reason.blocked",
    evidence: str | None = None,
) -> dict:
    return _observation(
        probe_id=probe_id, status="blocked",
        evidence_digest=evidence, reason_code=reason, blocked_by=[],
    )


def _deferred_obs(
    probe_id: str, *, blocked_by: list[str],
    reason: str = "reason.deferred",
) -> dict:
    return _observation(
        probe_id=probe_id, status="deferred",
        evidence_digest=None, reason_code=reason,
        blocked_by=sorted(set(blocked_by)),
    )


_VALID_HEX = "ab" * 32  # 64-char lowercase hex with at least one letter


def _minimal_descriptor(
    *,
    entry_requirements: list[dict] | None = None,
    supported_task_sources: tuple = ("csv",),
    supported_design_sources: tuple = ("lanhu-figma",),
) -> dict:
    """Build a valid synthetic descriptor for tests."""
    contract = _load_contract()
    if entry_requirements is None:
        entry_requirements = []
    components = []
    for role in contract.COMPONENT_ROLES:
        components.append({
            "role": role,
            "module_basename": f"synthetic_{role}.py",
            "module_sha256": _VALID_HEX,
            "contract_kind": f"icp.synthetic.{role}.v1",
            "public_api": ["describe"]
            if role == "descriptor"
            else ["probe"],
        })
    ports = []
    for pid in contract.PORT_IDS:
        ports.append({
            "id": pid,
            "capability_state": "required",
            "implementation_state": "not-implemented",
            "provider_component_role": "operation_plans",
            "artifact_contracts": [],
        })
    return {
        "kind": contract.KIND_DESCRIPTOR,
        "schema_version": contract.SCHEMA_VERSION,
        "platform_id": "synthetic",
        "profile_id": "synthetic-default",
        "activation_state": contract.ACTIVATION_STATE_INACTIVE,
        "executable": False,
        "registry_digest": _VALID_HEX,
        "selected_profile_digest": _VALID_HEX,
        "supported_task_sources": list(supported_task_sources),
        "supported_design_sources": list(supported_design_sources),
        "actual_source_types": [],
        "entry_requirements": entry_requirements,
        "components": components,
        "ports": ports,
    }


def _descriptor_req(
    rid: str,
    *,
    probe_id: str | None = None,
    owner: str = "user",
    required: bool = True,
    sensitive: bool = False,
    accepted_shape_id: str = "shape.user_input",
    remediation_id: str = "remediation.supply_input",
) -> dict:
    if probe_id is None:
        probe_id = rid
    return {
        "id": rid,
        "owner": owner,
        "required": required,
        "sensitive": sensitive,
        "probe_id": probe_id,
        "accepted_shape_id": accepted_shape_id,
        "remediation_id": remediation_id,
    }


def _aggregate_kwargs(
    *,
    descriptor: dict | None = None,
    task_source_id: str = "csv",
    design_source_id: str = "lanhu-figma",
    candidate_count: int = 1,
    observations: list[dict] | None = None,
    resolved_config_digest: str = DIGEST_RESOLVED_CONFIG,
    task_source_snapshot_digest: str = DIGEST_TASKSOURCE_SNAPSHOT,
    candidate_identity_digest: str = DIGEST_CANDIDATE_IDENTITY,
) -> dict:
    if descriptor is None:
        descriptor = _minimal_descriptor()
    if observations is None:
        observations = _pass_obs_for(sorted(CORE_PROBE_IDS))
    return dict(
        resolved_config_digest=resolved_config_digest,
        package_descriptor=descriptor,
        task_source_id=task_source_id,
        design_source_id=design_source_id,
        task_source_snapshot_digest=task_source_snapshot_digest,
        candidate_identity_digest=candidate_identity_digest,
        candidate_count=candidate_count,
        observations=observations,
    )


def _pass_obs_for(probe_ids) -> list[dict]:
    """Build pass observations for the given probe_ids, sorted by
    probe_id (the aggregator requires strictly-sorted input)."""
    return [_pass_obs(pid) for pid in sorted(probe_ids)]


def _sorted_obs(observations: list[dict]) -> list[dict]:
    """Return a copy of ``observations`` sorted by ``probe_id``. Use
    when a test mixes pass/missing/blocked/deferred observations for
    different probe_ids and needs the list to satisfy the
    aggregator's strict-sort contract."""
    return sorted(observations, key=lambda o: o["probe_id"])


def _ready_report(mod, **over) -> dict:
    """Build a verified readiness report with overall status ``ready``
    using the module under test (used as ``decide_entry`` input)."""
    return mod.aggregate_readiness(**{**_aggregate_kwargs(), **over})


def _requirement_id(selection: str, row_id: str) -> str:
    return hashlib.sha256(
        b"icp.requirement.v1\x00"
        + bytes.fromhex(selection)
        + bytes.fromhex(row_id)
    ).hexdigest()


def _progress_id(requirement_id: str, claim_ack: str) -> str:
    return hashlib.sha256(
        b"icp.requirement-progress.v1\x00"
        + bytes.fromhex(requirement_id)
        + bytes.fromhex(claim_ack)
    ).hexdigest()


def _active(progress_module) -> dict:
    rid = progress_module.derive_requirement_id(
        DIGEST_SEL_MANIFEST, DIGEST_ROW_IDENTITY
    )
    pid = progress_module.derive_progress_id(rid, DIGEST_CLAIM_ACK)
    return {
        "kind": "icp.active-requirement.v1",
        "schema_version": 1,
        "requirement_id": rid,
        "selection_manifest_digest": DIGEST_SEL_MANIFEST,
        "row_identity_digest": DIGEST_ROW_IDENTITY,
        "claim_intent_digest": DIGEST_CLAIM_INTENT,
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "progress_id": pid,
    }


def _feature(
    *,
    fid: str = "artboard.login",
    state: str = "pending",
    inflight: str | None = None,
    next_step: str | None = "step.login.build",
    replay: str = "none",
    recovery_verifier: str | None = None,
    last_receipt: str | None = None,
) -> dict:
    return {
        "feature_id": fid,
        "state": state,
        "inflight_step_id": inflight,
        "next_step_id": next_step,
        "replay_policy": replay,
        "recovery_verifier_digest": recovery_verifier,
        "last_checkpoint_receipt_digest": last_receipt,
    }


def _progress(
    progress_module,
    *,
    features: list[dict] | None = None,
    phase: str = "running",
    latest: str | None = None,
    count: int | None = None,
) -> dict:
    if features is None:
        features = [_feature()]
    if count is None:
        count = 0 if latest is None else 1
    active = _active(progress_module)
    return {
        "kind": "icp.requirement-progress.v1",
        "schema_version": 1,
        "requirement_id": active["requirement_id"],
        "progress_id": active["progress_id"],
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "verified_operation_plan_digest": DIGEST_OP_PLAN,
        "revision": 0,
        "phase": phase,
        "latest_checkpoint_receipt_digest": latest,
        "checkpoint_count": count,
        "feature_positions": features,
    }


def _expected_identities(progress_module) -> dict:
    active = _active(progress_module)
    return {
        "requirement_id": active["requirement_id"],
        "selection_manifest_digest": DIGEST_SEL_MANIFEST,
        "row_identity_digest": DIGEST_ROW_IDENTITY,
        "claim_intent_digest": DIGEST_CLAIM_INTENT,
        "claim_ack_digest": DIGEST_CLAIM_ACK,
        "progress_id": active["progress_id"],
        "verified_operation_plan_digest": DIGEST_OP_PLAN,
    }


def _decide_entry_kwargs(
    mod,
    *,
    readiness_report: dict | None = None,
    active_pointers: list[dict] | None = None,
    progress: dict | None = None,
    receipts: list[dict] | None = None,
    expected_identities: dict | None = None,
    exclusive_lock_acquired: bool = True,
    observed_row_status: str = "doing",
) -> dict:
    progress_module = _load_progress()
    if readiness_report is None:
        readiness_report = _ready_report(mod)
    if active_pointers is None:
        active_pointers = []
    if receipts is None:
        receipts = []
    if expected_identities is None:
        expected_identities = _expected_identities(progress_module)
    return dict(
        readiness_report=readiness_report,
        active_pointers=active_pointers,
        progress=progress,
        receipts=receipts,
        expected_identities=expected_identities,
        exclusive_lock_acquired=exclusive_lock_acquired,
        observed_row_status=observed_row_status,
    )


# ---------------------------------------------------------------------------
# 1. Module presence + clean import.
# ---------------------------------------------------------------------------


def test_module_absence_red_then_present_green() -> None:
    """If the module file is missing, every loader call raises
    FileNotFoundError; once it exists, it loads cleanly in a fresh
    subprocess."""
    if not ENTRY_READINESS_PATH.exists():
        # This is the recorded RED state.
        _expect_reject(
            lambda: _load_entry_readiness(),
            "module absence should raise",
        )
        return
    mod = _load_entry_readiness()
    assert hasattr(mod, "EntryReadinessError")
    assert hasattr(mod, "aggregate_readiness")
    # Fresh-subprocess import smoke check. The production module now
    # takes ordinary static imports of ``requirement_progress_v1`` and
    # ``platforms.platform_package_contract_v1``; ``icp/scripts`` must
    # be on ``PYTHONPATH`` for that resolution to succeed without any
    # path/bootstrap logic inside the module itself.
    code = "import entry_readiness_v1 as m; print('IMPORT_OK');"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ICP_SCRIPTS),
        },
    )
    assert result.returncode == 0, (
        f"fresh import failed: rc={result.returncode} "
        f"stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK"


# ---------------------------------------------------------------------------
# 2. Closed public API.
# ---------------------------------------------------------------------------


def test_public_api_surface_is_closed() -> None:
    import inspect
    mod = _load_entry_readiness()
    expected_funcs = {
        "document_digest", "verify_observation",
        "verify_readiness_report", "verify_entry_gate_decision",
        "aggregate_readiness", "decide_entry",
    }
    funcs = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isfunction(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert funcs == expected_funcs, (
        f"unexpected public functions: {sorted(funcs - expected_funcs)} "
        f"or missing: {sorted(expected_funcs - funcs)}"
    )
    classes = {
        n for n in dir(mod)
        if not n.startswith("_")
        and inspect.isclass(getattr(mod, n))
        and getattr(mod, n).__module__ == mod.__name__
    }
    assert classes == {"EntryReadinessError"}, (
        f"unexpected public classes: {sorted(classes)}"
    )
    # No locally-defined public constants (no UPPER_CASE public names
    # defined at module top level). Imported module names (``hashlib``,
    # ``json``, ``sys``, ...) are allowed and do not count.
    source = ENTRY_READINESS_PATH.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and not target.id.startswith("_")):
                    raise AssertionError(
                        f"entry_readiness_v1: public constant: "
                        f"{target.id}"
                    )
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and not node.target.id.startswith("_")):
                raise AssertionError(
                    f"entry_readiness_v1: public constant: "
                    f"{node.target.id}"
                )


# ---------------------------------------------------------------------------
# 3. document_digest canonical.
# ---------------------------------------------------------------------------


def test_document_digest_matches_canonical_bytes() -> None:
    mod = _load_entry_readiness()
    sample = {"b": 1, "a": [1, 2], "c": "x"}
    expected = _sha256_bytes(_canonical_json_bytes(sample))
    assert mod.document_digest(sample) == expected
    # Order-independence + determinism.
    assert mod.document_digest({"a": 1, "b": 2}) == \
        mod.document_digest({"b": 2, "a": 1})
    _expect_reject(lambda: mod.document_digest("not a dict"), "digest non-dict")


# ---------------------------------------------------------------------------
# 4. Observation schema + status rules + injection.
# ---------------------------------------------------------------------------


def test_observation_accepts_valid_for_each_status() -> None:
    mod = _load_entry_readiness()
    cases = [
        _pass_obs("p1"),
        _missing_obs("p1", reason="reason.x"),
        _blocked_obs("p1", reason="reason.y", evidence=DIGEST_EVIDENCE_BLOCKED),
        _blocked_obs("p1", reason="reason.y", evidence=None),
        _deferred_obs("p1", blocked_by=["other.req"]),
    ]
    for i, obs in enumerate(cases):
        mod.verify_observation(obs)


def test_observation_rejects_shape_and_status_violations() -> None:
    mod = _load_entry_readiness()
    base = _pass_obs("p1")
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, OBSERVATION_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_schema", {**base, "schema_version": 2}),
        ("bad_probe", {**base, "probe_id": "Bad Probe"}),
        ("bad_status", {**base, "status": "weird"}),
        ("bad_evidence", {**base, "evidence_digest": "g" * 64}),
        ("upper_evidence", {**base, "evidence_digest": "A" * 64}),
        ("bad_reason", {**base, "reason_code": "Bad Reason"}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_observation(d),
            f"observation accepts {label}",
        )
    # Missing required keys.
    for key in OBSERVATION_KEYS:
        bad = {k: v for k, v in base.items() if k != key}
        _expect_reject(
            lambda d=bad: mod.verify_observation(d),
            f"observation accepts missing {key}",
        )
    # Status-rule violations.
    status_cases: list[tuple[str, dict]] = [
        ("pass_no_evidence", _observation(
            probe_id="p1", status="pass", evidence_digest=None,
            reason_code=None, blocked_by=[])),
        ("pass_with_reason", _observation(
            probe_id="p1", status="pass",
            evidence_digest=DIGEST_EVIDENCE_PASS,
            reason_code="reason.x", blocked_by=[])),
        ("pass_with_blocked_by", _observation(
            probe_id="p1", status="pass",
            evidence_digest=DIGEST_EVIDENCE_PASS,
            reason_code=None, blocked_by=["other.req"])),
        ("missing_with_evidence", _observation(
            probe_id="p1", status="missing",
            evidence_digest=DIGEST_EVIDENCE_PASS,
            reason_code="reason.x", blocked_by=[])),
        ("missing_no_reason", _observation(
            probe_id="p1", status="missing",
            evidence_digest=None, reason_code=None, blocked_by=[])),
        ("missing_with_blocked_by", _observation(
            probe_id="p1", status="missing",
            evidence_digest=None, reason_code="reason.x",
            blocked_by=["other.req"])),
        ("blocked_no_reason", _observation(
            probe_id="p1", status="blocked",
            evidence_digest=None, reason_code=None, blocked_by=[])),
        ("blocked_with_blocked_by", _observation(
            probe_id="p1", status="blocked",
            evidence_digest=None, reason_code="r.x",
            blocked_by=["other.req"])),
        ("deferred_with_evidence", _observation(
            probe_id="p1", status="deferred",
            evidence_digest=DIGEST_EVIDENCE_PASS,
            reason_code="r.x", blocked_by=["other.req"])),
        ("deferred_no_reason", _observation(
            probe_id="p1", status="deferred",
            evidence_digest=None, reason_code=None,
            blocked_by=["other.req"])),
        ("deferred_empty_blocked_by", _observation(
            probe_id="p1", status="deferred",
            evidence_digest=None, reason_code="r.x", blocked_by=[])),
        ("deferred_unsorted_blocked_by", {
            **_deferred_obs("p1", blocked_by=["b.req", "a.req"]),
            "blocked_by": ["b.req", "a.req"],
        }),
        ("deferred_dup_blocked_by", {
            **_deferred_obs("p1", blocked_by=["a.req"]),
            "blocked_by": ["a.req", "a.req"],
        }),
        ("deferred_bad_blocked_by_id", _observation(
            probe_id="p1", status="deferred",
            evidence_digest=None, reason_code="r.x",
            blocked_by=["Bad ID"])),
    ]
    for label, doc in status_cases:
        _expect_reject(
            lambda d=doc: mod.verify_observation(d),
            f"observation accepts status violation {label}",
        )


def test_observation_rejects_injection_keys_at_every_level() -> None:
    mod = _load_entry_readiness()
    base = _pass_obs("p1")
    for key in INJECTION_FIELDS:
        _expect_reject(
            lambda k=key: mod.verify_observation({**base, k: "x"}),
            f"observation accepts injection {key}",
        )
        nested_blocked = {
            **base,
            "blocked_by_with_nested": [{key: "x"}],
        }
        # Even an unknown wrapper key must fail; injection walker
        # recurses through unknown structures too.
        _expect_reject(
            lambda d=nested_blocked: mod.verify_observation(d),
            f"observation accepts nested injection {key}",
        )


def test_injection_rejection_is_exact_key_not_substring() -> None:
    """A legitimate controlled value that merely contains a forbidden
    substring as part of a different identifier must NOT be rejected.
    Only exact dictionary key matches fail."""
    mod = _load_entry_readiness()
    # ``reason_code`` carries a value containing 'design_url' as a
    # substring of a larger identifier; this is legitimate.
    obs = _missing_obs("p1", reason=LEGIT_VALUE_WITH_SUBSTRING)
    mod.verify_observation(obs)


# ---------------------------------------------------------------------------
# 5. Readiness report schema + sorted uniqueness.
# ---------------------------------------------------------------------------


def _build_canonical_report_for_shape(mod) -> dict:
    """Use the aggregator to obtain a verified report we can shape-tamper."""
    return mod.aggregate_readiness(**_aggregate_kwargs())


def test_readiness_report_has_exact_shape_and_status_enum() -> None:
    mod = _load_entry_readiness()
    report = _build_canonical_report_for_shape(mod)
    assert tuple(report.keys()) == READINESS_REPORT_KEYS
    assert report["kind"] == KIND_READINESS_REPORT
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["status"] in REPORT_STATUSES
    for key in ("resolved_config_digest", "package_descriptor_digest",
                "task_source_snapshot_digest", "candidate_identity_digest"):
        assert isinstance(report[key], str) and len(report[key]) == 64
    # Each nested object has the exact ordered keys.
    for c in report["checks"]:
        assert tuple(c.keys()) == CHECK_KEYS
        assert c["owner"] in OWNERS
        assert c["status"] in OBSERVATION_STATUSES
    for m in report["missing_user_inputs"]:
        assert tuple(m.keys()) == MISSING_USER_INPUT_KEYS
    for d in report["deferred_checks"]:
        assert tuple(d.keys()) == DEFERRED_CHECK_KEYS
    for b in report["blockers"]:
        assert tuple(b.keys()) == BLOCKER_KEYS


def test_readiness_report_rejects_shape_and_sorting_violations() -> None:
    mod = _load_entry_readiness()
    base = _build_canonical_report_for_shape(mod)
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, READINESS_REPORT_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_status", {**base, "status": "weird"}),
        ("bad_digest", {**base, "resolved_config_digest": "g" * 64}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_readiness_report(d),
            f"report accepts {label}",
        )
    # Nested-array sorting / uniqueness violations.
    if len(base["checks"]) >= 2:
        dup_checks = list(base["checks"])
        dup_checks.append(copy.deepcopy(dup_checks[0]))
        bad = {**base, "checks": dup_checks}
        _expect_reject(
            lambda d=bad: mod.verify_readiness_report(d),
            "report accepts duplicate check ids",
        )
        rev_checks = list(reversed(base["checks"]))
        bad = {**base, "checks": rev_checks}
        _expect_reject(
            lambda d=bad: mod.verify_readiness_report(d),
            "report accepts unsorted checks",
        )
    # Extra unknown key in a check.
    bad_check = {**base["checks"][0], "extra": "x"}
    bad = {**base, "checks": [bad_check] + list(base["checks"][1:])}
    _expect_reject(
        lambda d=bad: mod.verify_readiness_report(d),
        "report accepts check with unknown key",
    )
    # Injection anywhere.
    for key in INJECTION_FIELDS:
        bad = {**base, key: "x"}
        _expect_reject(
            lambda d=bad, k=key: mod.verify_readiness_report(d),
            f"report accepts injection {key}",
        )


# ---------------------------------------------------------------------------
# 6. Entry-gate-decision schema.
# ---------------------------------------------------------------------------


def _build_canonical_decision(mod) -> dict:
    return mod.decide_entry(**_decide_entry_kwargs(mod))


def test_entry_gate_decision_has_exact_shape_and_decision_enum() -> None:
    mod = _load_entry_readiness()
    decision = _build_canonical_decision(mod)
    assert tuple(decision.keys()) == ENTRY_GATE_DECISION_KEYS
    assert decision["kind"] == KIND_ENTRY_GATE_DECISION
    assert decision["schema_version"] == SCHEMA_VERSION
    assert decision["decision"] in ENTRY_DECISIONS
    assert isinstance(decision["reason_code"], str)
    for key in ("readiness_report_digest", "resume_decision_digest"):
        assert isinstance(decision[key], str) and len(decision[key]) == 64
    for key in ("requirement_id", "progress_id",
                "checkpoint_receipt_digest"):
        v = decision[key]
        assert v is None or (isinstance(v, str) and len(v) == 64)
    for key in ("feature_id", "step_id"):
        v = decision[key]
        assert v is None or (isinstance(v, str) and v.replace(".", "").replace(
            "_", "").replace("-", "").isalnum())


def test_entry_gate_decision_rejects_shape_violations() -> None:
    mod = _load_entry_readiness()
    base = _build_canonical_decision(mod)
    bad_cases: list[tuple[str, dict]] = [
        ("reordered", _reordered(base, ENTRY_GATE_DECISION_KEYS)),
        ("unknown", {**base, "extra": "x"}),
        ("bad_kind", {**base, "kind": "icp.something.else.v1"}),
        ("bad_decision", {**base, "decision": "weird"}),
        ("bad_digest", {**base, "readiness_report_digest": "g" * 64}),
        ("bad_reason", {**base, "reason_code": "Bad Reason"}),
    ]
    for label, doc in bad_cases:
        _expect_reject(
            lambda d=doc: mod.verify_entry_gate_decision(d),
            f"decision accepts {label}",
        )
    for key in INJECTION_FIELDS:
        bad = {**base, key: "x"}
        _expect_reject(
            lambda d=bad, k=key: mod.verify_entry_gate_decision(d),
            f"decision accepts injection {key}",
        )


# ---------------------------------------------------------------------------
# 7. aggregate_readiness happy path + descriptor/core interpretation.
# ---------------------------------------------------------------------------


def test_aggregate_happy_path_core_and_descriptor() -> None:
    mod = _load_entry_readiness()
    contract = _load_contract()
    # Build a descriptor with one extra descriptor-level required
    # requirement satisfied by its own probe_id.
    desc_req = _descriptor_req("desc.toolchain", probe_id="desc.toolchain")
    descriptor = _minimal_descriptor(entry_requirements=[desc_req])
    observations = [
        _pass_obs(pid) for pid in CORE_PROBE_IDS
    ] + [_pass_obs("desc.toolchain")]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor, observations=observations,
        candidate_count=3,
    ))
    assert report["status"] == "ready"
    # Every requirement produced a check; sorted unique by id.
    check_ids = [c["id"] for c in report["checks"]]
    assert check_ids == sorted(check_ids)
    assert len(check_ids) == len(set(check_ids))
    assert set(check_ids) == set(CORE_REQUIREMENT_IDS) | {"desc.toolchain"}
    # Evidence carried on every pass check.
    for c in report["checks"]:
        assert c["status"] == "pass"
        assert c["evidence_digest"] == DIGEST_EVIDENCE_PASS
    # The descriptor digest is computed by the module itself and bound.
    assert report["package_descriptor_digest"] == \
        contract.compute_descriptor_digest(descriptor)


def test_aggregate_descriptor_requirement_can_share_probe_id() -> None:
    mod = _load_entry_readiness()
    # Two descriptor requirements with the same probe_id; one
    # observation satisfies both.
    desc_reqs = [
        _descriptor_req("desc.a", probe_id="desc.shared"),
        _descriptor_req("desc.b", probe_id="desc.shared"),
    ]
    descriptor = _minimal_descriptor(entry_requirements=desc_reqs)
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS] + [
        _pass_obs("desc.shared")
    ]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor, observations=observations,
    ))
    assert report["status"] == "ready"
    check_ids = [c["id"] for c in report["checks"]]
    assert "desc.a" in check_ids and "desc.b" in check_ids


# ---------------------------------------------------------------------------
# 8. Absent required observations + multi-missing sort + optional missing.
# ---------------------------------------------------------------------------


def test_aggregate_synthesizes_missing_for_absent_required_observations() -> None:
    mod = _load_entry_readiness()
    # Drop one core observation entirely.
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS[1:]]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "needs-user-input"
    # The missing core requirement appears as a synthetic missing check.
    missing_ids = [m["id"] for m in report["missing_user_inputs"]]
    assert CORE_REQUIREMENT_IDS[0] in missing_ids
    # Exactly one missing_user_inputs entry per missing required check.
    target = [c for c in report["checks"]
              if c["id"] == CORE_REQUIREMENT_IDS[0]][0]
    assert target["status"] == "missing"
    assert target["evidence_digest"] is None
    # The synthetic reason is observation-missing.
    mis = [m for m in report["missing_user_inputs"]
           if m["id"] == CORE_REQUIREMENT_IDS[0]][0]
    assert mis["reason_code"] == "observation-missing"


def test_aggregate_multiple_missing_inputs_stable_sorted() -> None:
    mod = _load_entry_readiness()
    # Drop two core observations -- the report must list both missing
    # in stable sorted order.
    drop = {CORE_PROBE_IDS[0], CORE_PROBE_IDS[2]}
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS
                    if pid not in drop]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "needs-user-input"
    missing_ids = [m["id"] for m in report["missing_user_inputs"]]
    assert set(drop) == {CORE_REQUIREMENT_IDS[0], CORE_REQUIREMENT_IDS[2]}
    assert CORE_REQUIREMENT_IDS[0] in missing_ids
    assert CORE_REQUIREMENT_IDS[2] in missing_ids
    assert missing_ids == sorted(missing_ids)


def test_aggregate_optional_missing_does_not_block() -> None:
    mod = _load_entry_readiness()
    # Descriptor declares an optional requirement; we provide no
    # observation for it. The check is visible but does not trigger
    # needs-user-input, and ready / no-work still attainable.
    desc_req = _descriptor_req(
        "desc.optional", probe_id="desc.optional", required=False,
    )
    descriptor = _minimal_descriptor(entry_requirements=[desc_req])
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor, observations=observations,
        candidate_count=1,
    ))
    assert report["status"] == "ready"
    opt = [c for c in report["checks"] if c["id"] == "desc.optional"][0]
    assert opt["status"] == "missing"
    assert all(m["id"] != "desc.optional"
               for m in report["missing_user_inputs"])


# ---------------------------------------------------------------------------
# 9. Sensitive redaction + secure supply channel IDs.
# ---------------------------------------------------------------------------


def test_aggregate_sensitive_redaction_and_secure_channels() -> None:
    mod = _load_entry_readiness()
    # Sensitive core requirement (design source) is missing -- the
    # report must use the credential-safe channel and never echo any
    # supplied secret-bearing value.
    observations = _sorted_obs(
        [_pass_obs(pid) for pid in CORE_PROBE_IDS
         if pid != "core.design_source.access"]
        + [
            # Inject a bearer value into a *legitimate-looking*
            # reason_code to confirm the report does not leak it as a
            # credential echo. The report only carries controlled IDs;
            # never the user's value.
            _missing_obs(
                "core.design_source.access",
                reason="reason.credential_slot_empty",
            ),
        ]
    )
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "needs-user-input"
    des = [m for m in report["missing_user_inputs"]
           if m["id"] == "core.design_source.access"][0]
    assert des["sensitive"] is True
    assert des["secure_supply_channel"] == CHANNEL_CREDENTIAL
    # Non-sensitive missing uses the user supply channel.
    observations2 = _sorted_obs(
        [_pass_obs(pid) for pid in CORE_PROBE_IDS
         if pid != "core.project_root.access"]
        + [_missing_obs("core.project_root.access")]
    )
    report2 = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations2,
    ))
    proot = [m for m in report2["missing_user_inputs"]
             if m["id"] == "core.project_root.access"][0]
    assert proot["sensitive"] is False
    assert proot["secure_supply_channel"] == CHANNEL_USER
    # No secret/token/credential value is ever embedded anywhere in
    # the report. Structured recursive check (no substring scan).
    for blob in (report, report2):
        _assert_no_secret_echo(blob)


def _assert_no_secret_echo(obj: Any) -> None:
    forbidden_value_substrings = (
        "Bearer ", "sk-", "password=", "secret=",
    )
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_no_secret_echo(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_secret_echo(v)
    elif isinstance(obj, str):
        for sub in forbidden_value_substrings:
            assert sub not in obj, (
                f"report leaks secret-looking value: {obj!r}"
            )


# ---------------------------------------------------------------------------
# 10. Precedence: blocked / invalid-deferred / missing / no-work / ready.
# ---------------------------------------------------------------------------


def test_aggregate_blocked_precedence_over_missing() -> None:
    mod = _load_entry_readiness()
    # One observation blocked + one observation missing -> blocked wins.
    observations = _sorted_obs(
        [_pass_obs(pid) for pid in CORE_PROBE_IDS[2:]]
        + [
            _blocked_obs(CORE_PROBE_IDS[0], reason="reason.env"),
            _missing_obs(CORE_PROBE_IDS[1]),
        ]
    )
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "blocked"
    codes = [b["code"] for b in report["blockers"]]
    assert "blocked-observation" in codes


def test_aggregate_invalid_deferred_dependency_blocks() -> None:
    mod = _load_entry_readiness()
    # Deferred check pointing at an unknown requirement ID.
    observations = _sorted_obs(
        [_pass_obs(pid) for pid in CORE_PROBE_IDS[1:]]
        + [
            _deferred_obs(CORE_PROBE_IDS[0],
                          blocked_by=["nonexistent.requirement"]),
        ]
    )
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "blocked"
    codes = [b["code"] for b in report["blockers"]]
    assert "invalid-deferred-dependency" in codes


def test_aggregate_deferred_blocked_by_missing_is_needs_user_input() -> None:
    mod = _load_entry_readiness()
    # Deferred check whose blocked_by points only to a missing
    # requirement in this same report -> needs-user-input.
    target_req = "core.design_source.access"
    observations = _sorted_obs(
        [_pass_obs(pid) for pid in CORE_PROBE_IDS
         if pid != target_req and pid != "core.task_source.access"]
        + [
            _missing_obs(target_req),
            _deferred_obs("core.task_source.access",
                          blocked_by=[target_req]),
        ]
    )
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "needs-user-input"
    # Deferred check is listed (valid blocked_by).
    deferred_ids = [d["id"] for d in report["deferred_checks"]]
    assert "core.task_source.access" in deferred_ids


def test_aggregate_no_work_when_zero_candidates_and_all_satisfied() -> None:
    mod = _load_entry_readiness()
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        candidate_count=0,
    ))
    assert report["status"] == "no-work"
    # No blockers / missing inputs.
    assert report["missing_user_inputs"] == []
    assert report["blockers"] == []


def test_aggregate_ready_when_satisfied_and_candidates_exist() -> None:
    mod = _load_entry_readiness()
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        candidate_count=2,
    ))
    assert report["status"] == "ready"


def test_aggregate_optional_missing_does_not_prevent_no_work() -> None:
    mod = _load_entry_readiness()
    desc_req = _descriptor_req(
        "desc.opt", probe_id="desc.opt", required=False,
    )
    descriptor = _minimal_descriptor(entry_requirements=[desc_req])
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor,
        candidate_count=0,
    ))
    assert report["status"] == "no-work"
    opt = [c for c in report["checks"] if c["id"] == "desc.opt"][0]
    assert opt["status"] == "missing"


# ---------------------------------------------------------------------------
# 11. Reject extra / duplicate / unsorted / unknown observations.
# ---------------------------------------------------------------------------


def test_aggregate_rejects_extra_duplicate_unsorted_unknown_observations() -> None:
    mod = _load_entry_readiness()
    base_obs = [_pass_obs(pid) for pid in CORE_PROBE_IDS]
    # Extra unknown probe_id.
    extra = list(base_obs) + [_pass_obs("unknown.probe")]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=extra,
        )),
        "aggregate accepts unknown probe_id",
    )
    # Duplicate probe_id (input no longer strictly unique).
    dup = list(base_obs) + [_pass_obs(CORE_PROBE_IDS[0])]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=dup,
        )),
        "aggregate accepts duplicate probe_id",
    )
    # Unsorted input.
    unsorted = [base_obs[1], base_obs[0]] + base_obs[2:]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=unsorted,
        )),
        "aggregate accepts unsorted observations",
    )
    # Malformed observation.
    bad_obs = list(base_obs)
    bad_obs[0] = {**bad_obs[0], "kind": "icp.x.v1"}
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=bad_obs,
        )),
        "aggregate accepts malformed observation",
    )


# ---------------------------------------------------------------------------
# 12. Descriptor validation + core/descriptor ID collision + source compat.
# ---------------------------------------------------------------------------


def test_aggregate_rejects_invalid_descriptor_shape() -> None:
    mod = _load_entry_readiness()
    contract = _load_contract()
    bad_descriptor = _minimal_descriptor()
    # Tamper the kind so the shared validator rejects.
    bad_descriptor["kind"] = "icp.something.else.v1"
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            descriptor=bad_descriptor,
        )),
        "aggregate accepts bad descriptor kind",
    )
    # Drop a required key.
    bad2 = _minimal_descriptor()
    del bad2["components"]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            descriptor=bad2,
        )),
        "aggregate accepts descriptor missing components",
    )


def test_aggregate_rejects_core_descriptor_id_collision() -> None:
    mod = _load_entry_readiness()
    # A descriptor requirement whose id collides with a core id.
    desc_req = _descriptor_req(CORE_REQUIREMENT_IDS[0])
    descriptor = _minimal_descriptor(entry_requirements=[desc_req])
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            descriptor=descriptor, observations=observations,
        )),
        "aggregate accepts core/descriptor id collision",
    )


def test_aggregate_unsupported_sources_become_blockers() -> None:
    mod = _load_entry_readiness()
    # Request a task source not declared as supported by the descriptor.
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        task_source_id="unsupported.source",
    ))
    assert report["status"] == "blocked"
    codes = [b["code"] for b in report["blockers"]]
    assert "unsupported-task-source" in codes
    # Now an unsupported design source.
    report2 = mod.aggregate_readiness(**_aggregate_kwargs(
        design_source_id="unsupported.design",
    ))
    assert report2["status"] == "blocked"
    codes2 = [b["code"] for b in report2["blockers"]]
    assert "unsupported-design-source" in codes2
    # Both unsupported at once -- still blocked, with both blockers.
    report3 = mod.aggregate_readiness(**_aggregate_kwargs(
        task_source_id="unsupported.source",
        design_source_id="unsupported.design",
    ))
    assert report3["status"] == "blocked"
    codes3 = [b["code"] for b in report3["blockers"]]
    assert "unsupported-task-source" in codes3
    assert "unsupported-design-source" in codes3


# ---------------------------------------------------------------------------
# 13. Evidence digest requirements + identity digest drift.
# ---------------------------------------------------------------------------


def test_aggregate_pass_check_evidence_digest_required() -> None:
    mod = _load_entry_readiness()
    # Pass observation without evidence is rejected by verify_observation,
    # so aggregate_readiness also rejects it.
    bad_obs = list(_pass_obs(pid) for pid in CORE_PROBE_IDS)
    bad_obs[0] = _observation(
        probe_id=CORE_PROBE_IDS[0], status="pass",
        evidence_digest=None, reason_code=None, blocked_by=[],
    )
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=bad_obs,
        )),
        "aggregate accepts pass without evidence",
    )


def test_aggregate_identity_digest_drift_changes_report_digest() -> None:
    mod = _load_entry_readiness()
    base = mod.aggregate_readiness(**_aggregate_kwargs())
    # Different resolved_config_digest -> different report bytes.
    drift = mod.aggregate_readiness(**_aggregate_kwargs(
        resolved_config_digest="e" * 64,
    ))
    assert base["resolved_config_digest"] != drift["resolved_config_digest"]
    assert mod.document_digest(base) != mod.document_digest(drift)
    # Different candidate_identity_digest -> different report bytes.
    drift2 = mod.aggregate_readiness(**_aggregate_kwargs(
        candidate_identity_digest="f" * 64,
    ))
    assert mod.document_digest(base) != mod.document_digest(drift2)
    # Malformed digests rejected.
    for bad in ("", "x" * 30, "A" * 64, "g" * 64, None, 1):
        _expect_reject(
            lambda b=bad: mod.aggregate_readiness(**_aggregate_kwargs(
                resolved_config_digest=b,
            )),
            f"aggregate accepts bad resolved_config_digest {bad!r}",
        )


# ---------------------------------------------------------------------------
# 14. Determinism + non-mutation.
# ---------------------------------------------------------------------------


def test_aggregate_is_deterministic_and_does_not_mutate_inputs() -> None:
    mod = _load_entry_readiness()
    descriptor = _minimal_descriptor()
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS]
    obs_snapshot = copy.deepcopy(observations)
    desc_snapshot = copy.deepcopy(descriptor)
    r1 = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor, observations=observations,
    ))
    r2 = mod.aggregate_readiness(**_aggregate_kwargs(
        descriptor=descriptor, observations=observations,
    ))
    assert mod.document_digest(r1) == mod.document_digest(r2)
    # Inputs untouched.
    assert observations == obs_snapshot
    assert descriptor == desc_snapshot


# ---------------------------------------------------------------------------
# 15. Injection in descriptor or observations.
# ---------------------------------------------------------------------------


def test_aggregate_rejects_injection_keys_in_descriptor_or_observations() -> None:
    mod = _load_entry_readiness()
    # Injection key in descriptor entry_requirement is caught by the
    # shared descriptor validator, which the aggregator must call.
    bad_desc = _minimal_descriptor()
    bad_desc = copy.deepcopy(bad_desc)
    bad_desc["entry_requirements"] = [{
        "id": "desc.x", "owner": "user", "required": True,
        "sensitive": False, "probe_id": "desc.x",
        "accepted_shape_id": "shape.x", "remediation_id": "rem.x",
        "command": "echo pwned",
    }]
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            descriptor=bad_desc,
        )),
        "aggregate accepts descriptor with injection key",
    )
    # Injection key in observation.
    bad_obs = [_pass_obs(pid) for pid in CORE_PROBE_IDS]
    bad_obs[0] = {**bad_obs[0], "secret": "x"}
    _expect_reject(
        lambda: mod.aggregate_readiness(**_aggregate_kwargs(
            observations=bad_obs,
        )),
        "aggregate accepts observation with injection key",
    )


# ---------------------------------------------------------------------------
# 16. decide_entry active-first table: zero / one / multiple active cases.
# ---------------------------------------------------------------------------


def test_decide_entry_zero_active_new_selection_table() -> None:
    """Table-driven: zero active + report status -> entry decision."""
    mod = _load_entry_readiness()
    # ready -> select-new; needs-user-input -> needs-user-input;
    # blocked -> blocked; no-work -> no-work.
    ready_report = _ready_report(mod)
    drop = {CORE_PROBE_IDS[0]}
    nui_report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=[_pass_obs(pid) for pid in CORE_PROBE_IDS
                      if pid not in drop],
    ))
    assert nui_report["status"] == "needs-user-input"
    blocked_report = mod.aggregate_readiness(**_aggregate_kwargs(
        task_source_id="unsupported.source",
    ))
    assert blocked_report["status"] == "blocked"
    no_work_report = mod.aggregate_readiness(**_aggregate_kwargs(
        candidate_count=0,
    ))
    assert no_work_report["status"] == "no-work"
    cases: list[tuple[str, dict, str]] = [
        ("ready", ready_report, "select-new"),
        ("needs_user_input", nui_report, "needs-user-input"),
        ("blocked", blocked_report, "blocked"),
        ("no_work", no_work_report, "no-work"),
    ]
    for label, report, exp_decision in cases:
        decision = mod.decide_entry(**_decide_entry_kwargs(
            mod, active_pointers=[], readiness_report=report,
        ))
        assert decision["decision"] == exp_decision, (
            f"{label}: expected {exp_decision} got {decision['decision']}"
        )
        assert decision["requirement_id"] is None
        assert decision["progress_id"] is None


def test_decide_entry_one_active_ready_report_resumes() -> None:
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    prog = _progress(
        progress_module,
        features=[_feature(state="pending", next_step="step.first")],
    )
    decision = mod.decide_entry(**_decide_entry_kwargs(
        mod,
        active_pointers=[active], progress=prog,
        readiness_report=_ready_report(mod),
    ))
    # Active state wins over new selection -> resume-step.
    assert decision["decision"] == "resume-step"
    assert decision["reason_code"] == "resume-next-step"
    assert decision["step_id"] == "step.first"
    assert decision["requirement_id"] == active["requirement_id"]
    assert decision["progress_id"] == active["progress_id"]


def test_decide_entry_blocks_table() -> None:
    """Table-driven: various fail-closed decide_entry scenarios --
    multiple active, orphan state, lock not acquired, identity
    mismatch, row terminal, progress tamper, receipt-chain tamper."""
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    identities = _expected_identities(progress_module)
    ready = _ready_report(mod)
    prog_running = _progress(
        progress_module,
        features=[_feature(state="pending", next_step="step.x")],
    )

    # (label, decision, reason)
    expected = [
        ("multiple_active",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[active, active],
             readiness_report=ready,
         )),
         "blocked", "multiple-active-pointers"),
        ("orphan_state",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[],
             progress=_progress(progress_module),
             readiness_report=ready,
         )),
         "blocked", "no-active-state"),
        ("lock_not_acquired",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[active],
             exclusive_lock_acquired=False,
             readiness_report=ready,
         )),
         "blocked", "lock-not-acquired"),
        ("identity_mismatch",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[active],
             expected_identities=dict(identities,
                                      requirement_id="0" * 64),
             readiness_report=ready,
         )),
         "blocked", "identity-mismatch"),
        ("row_terminal",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[active],
             observed_row_status="done",
             readiness_report=ready,
         )),
         "terminal-cleanup-required", "row-terminal"),
        ("progress_tamper",
         mod.decide_entry(**_decide_entry_kwargs(
             mod, active_pointers=[active],
             progress=dict(prog_running, phase="weird"),
             readiness_report=ready,
         )),
         "blocked", "progress-tamper"),
    ]
    for label, decision, exp_decision, exp_reason in expected:
        assert decision["decision"] == exp_decision, (
            f"{label}: expected {exp_decision} got {decision['decision']}"
        )
        assert decision["reason_code"] == exp_reason, (
            f"{label}: expected {exp_reason} got {decision['reason_code']}"
        )

    # Receipt-chain tamper: progress claims count=1 but no receipts
    # supplied -> chain verification fails.
    prog_checkpoint = _progress(
        progress_module,
        features=[_feature(state="checkpointed",
                           next_step="step.green",
                           last_receipt="0" * 64)],
        latest="0" * 64, count=1,
    )
    decision = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active],
        progress=prog_checkpoint, receipts=[],
        readiness_report=ready,
    ))
    assert decision["decision"] == "blocked"
    assert decision["reason_code"] == "receipt-chain-tamper"


def test_decide_entry_started_feature_replay_policy_table() -> None:
    """Table-driven: feature state x replay policy -> entry decision +
    exact step identity fields."""
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    cases: list[tuple[str, dict, str, str, str | None]] = [
        ("started_no_replay",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="none"),
         "blocked", "started-without-replay", "step.mid"),
        ("started_idempotent",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="idempotent"),
         "replay-step", "replay-idempotent", "step.mid"),
        ("started_deterministic",
         _feature(state="started", inflight="step.mid",
                  next_step="step.mid", replay="deterministic-recovery",
                  recovery_verifier="0a" * 32),
         "run-recovery-verifier", "recovery-verifier-required",
         "step.mid"),
        ("pending",
         _feature(state="pending", next_step="step.first"),
         "resume-step", "resume-next-step", "step.first"),
        ("failed",
         _feature(state="failed", next_step=None),
         "blocked", "active-present", None),
    ]
    for label, feat, exp_decision, exp_reason, exp_step in cases:
        prog = _progress(progress_module, features=[feat])
        d = mod.decide_entry(**_decide_entry_kwargs(
            mod,
            active_pointers=[active], progress=prog,
            readiness_report=_ready_report(mod),
        ))
        assert d["decision"] == exp_decision, (
            f"{label}: expected {exp_decision} got {d['decision']}"
        )
        assert d["reason_code"] == exp_reason, (
            f"{label}: expected {exp_reason} got {d['reason_code']}"
        )
        if exp_step is not None:
            assert d["step_id"] == exp_step, (
                f"{label}: expected step {exp_step} got {d['step_id']}"
            )
        assert d["requirement_id"] == active["requirement_id"]
        assert d["progress_id"] == active["progress_id"]


def test_decide_entry_no_work_with_active_pointer_fails_closed() -> None:
    """``no-work`` + active pointer is contradictory. The entry must
    fail closed via blocked prerequisite handling rather than selecting
    a new row or resuming."""
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        candidate_count=0,
    ))
    assert report["status"] == "no-work"
    decision = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active], readiness_report=report,
    ))
    assert decision["decision"] == "blocked"
    assert decision["reason_code"] == "prerequisites-blocked"


def test_decide_entry_needs_user_input_preserves_active_state() -> None:
    """With active state and a needs-user-input readiness report, the
    entry returns needs-user-input/prerequisites-missing and never
    selects a new row."""
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    drop = {CORE_PROBE_IDS[0]}
    observations = [_pass_obs(pid) for pid in CORE_PROBE_IDS
                    if pid not in drop]
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        observations=observations,
    ))
    assert report["status"] == "needs-user-input"
    decision = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active], readiness_report=report,
    ))
    assert decision["decision"] == "needs-user-input"
    assert decision["reason_code"] == "prerequisites-missing"
    assert decision["requirement_id"] == active["requirement_id"]


def test_decide_entry_blocked_report_with_active_blocks() -> None:
    """Blocked readiness + active pointer -> blocked/prerequisites-blocked
    (no resume)."""
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    report = mod.aggregate_readiness(**_aggregate_kwargs(
        task_source_id="unsupported.source",
    ))
    assert report["status"] == "blocked"
    decision = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active], readiness_report=report,
    ))
    assert decision["decision"] == "blocked"
    assert decision["reason_code"] == "prerequisites-blocked"


def test_decide_entry_is_deterministic_and_does_not_mutate_inputs() -> None:
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    active = _active(progress_module)
    prog = _progress(
        progress_module,
        features=[_feature(state="pending", next_step="step.first")],
    )
    report = _ready_report(mod)
    active_snap = copy.deepcopy(active)
    prog_snap = copy.deepcopy(prog)
    report_snap = copy.deepcopy(report)
    d1 = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active], progress=prog,
        readiness_report=report,
    ))
    d2 = mod.decide_entry(**_decide_entry_kwargs(
        mod, active_pointers=[active], progress=prog,
        readiness_report=report,
    ))
    assert mod.document_digest(d1) == mod.document_digest(d2)
    assert active == active_snap
    assert prog == prog_snap
    assert report == report_snap


def test_decide_entry_rejects_unverified_readiness_report() -> None:
    mod = _load_entry_readiness()
    progress_module = _load_progress()
    bad_report = _ready_report(mod)
    bad_report = dict(bad_report, kind="icp.something.else.v1")
    _expect_reject(
        lambda: mod.decide_entry(**_decide_entry_kwargs(
            mod, active_pointers=[],
            readiness_report=bad_report,
        )),
        "decide_entry accepts unverified readiness_report",
    )


# ---------------------------------------------------------------------------
# 17. AST / source checks: no I/O, no platform literals, no dynamic import.
# ---------------------------------------------------------------------------


# Stdlib imports the production module is allowed to take. Note this
# set deliberately excludes ``importlib``, ``pathlib``, and ``sys``:
# P3b1a forbids dynamic import, path-based dependency resolution, and
# any interpreter/path mutation in the production module.
_ALLOWED_STDLIB = {
    "__future__", "hashlib", "json", "typing",
}
_ALLOWED_LOCAL_MODULES = {
    "platform_package_contract_v1", "requirement_progress_v1",
}
# The local package ``platforms/`` is the parent of one allowed local
# module (``platform_package_contract_v1``). Production may import that
# one leaf via ``from platforms import platform_package_contract_v1``;
# the private-alias check below still enforces a private ``as`` name.
_ALLOWED_LOCAL_PARENT_PACKAGES = {
    "platforms",
}
# Module roots whose presence (as ``import X`` / ``from X import ...``)
# is forbidden at every AST nesting level in the production source.
_FORBIDDEN_IMPORT_ROOTS = {
    "importlib", "pathlib", "sys",
}
# Dynamic-loader primitives + eval/exec family. Banned as bare-name
# calls (``__import__(...)``, ``eval(...)``) and as attribute access
# (``importlib.util.spec_from_file_location(...)``,
# ``spec.loader.exec_module(...)``) at every AST nesting level.
_FORBIDDEN_DYNAMIC_NAMES = {
    "spec_from_file_location", "module_from_spec", "exec_module",
    "__import__", "eval", "exec", "compile",
}
_FORBIDDEN_TOP_NAME_CALLS = {
    "open", "system", "popen", "execv", "execve", "execl",
    "spawnv", "spawnve", "fork", "urlopen", "eval", "exec",
    "__import__",
}
_FORBIDDEN_TOP_ATTR_CALLS = {
    "open", "resolve", "stat", "lstat", "exists", "is_file", "is_dir",
    "is_symlink", "readlink", "iterdir", "glob", "rglob", "read_text",
    "read_bytes", "write_text", "write_bytes", "mkdir", "unlink",
    "replace", "rename", "touch", "chmod", "symlink_to", "hardlink_to",
}
_FORBIDDEN_TOP_ATTR_CHAINS = {
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.execv", "os.spawnv", "os.fork",
    "os.execve", "os.execl", "os.getenv", "os.environ",
    "urllib.request.urlopen", "urllib.urlopen", "socket.socket",
    "fcntl.flock", "msvcrt.locking",
}


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            names.append(node.module)
    return names


def _attr_chain(node: ast.AST) -> str:
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _top_level_io_violations(tree: ast.Module) -> list:
    violations = []

    def check(node: ast.Call) -> None:
        f = node.func
        if isinstance(f, ast.Name) and f.id in _FORBIDDEN_TOP_NAME_CALLS:
            violations.append(f.id)
        elif isinstance(f, ast.Attribute):
            chain = _attr_chain(f)
            last = chain.rsplit(".", 1)[-1]
            if chain in _FORBIDDEN_TOP_ATTR_CHAINS:
                violations.append(chain)
            elif last in _FORBIDDEN_TOP_ATTR_CALLS:
                violations.append(chain)

    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                check(node)
    return violations


def _all_dynamic_import_violations(tree: ast.Module) -> list:
    """Walk every node in ``tree`` and return every P3b1a purity
    violation: forbidden import roots (``importlib`` / ``pathlib`` /
    ``sys``), forbidden dynamic-loader / eval primitives at any
    nesting level, ``Path(...)`` constructor calls, and
    ``sys.path[...]`` mutation/access. Unlike :func:
    ``_top_level_io_violations`` this walks function / class bodies
    too -- the contract is "no dynamic import at any nesting level".
    """
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(
                        f"from {node.module} import ..."
                    )
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in _FORBIDDEN_DYNAMIC_NAMES:
                    violations.append(f"call name {f.id}")
                elif f.id == "Path":
                    violations.append("call Path(...)")
            elif isinstance(f, ast.Attribute):
                if f.attr in _FORBIDDEN_DYNAMIC_NAMES:
                    violations.append(f"attr .{f.attr}")
                elif f.attr == "path":
                    # ``sys.path`` attribute access (append / insert /
                    # subscript mutation handled below).
                    chain = _attr_chain(f)
                    if chain.endswith("sys.path"):
                        violations.append(f"attr {chain}")
        elif isinstance(node, ast.Subscript):
            # ``sys.path[0] = ...`` etc. -- detect the underlying
            # ``sys.path`` attribute chain.
            chain = _attr_chain(node.value)
            if chain.endswith("sys.path"):
                violations.append(f"subscript {chain}")
    return violations


def test_module_source_ast_checks() -> None:
    """Combined AST / source-level checks: stdlib + named-local imports
    only (no ``importlib`` / ``pathlib`` / ``sys`` at any nesting
    level), no dynamic-loader primitives (``spec_from_file_location``,
    ``module_from_spec``, ``exec_module``, ``__import__``, ``eval``,
    ``exec``, ``compile``) at any nesting level, no ``Path(...)``
    constructor, no ``sys.path`` mutation, no top-level I/O calls, no
    public constants, no local-module public attribute leak, and clean
    import in a fresh subprocess with ``icp/scripts`` on
    ``PYTHONPATH`` (the normal script execution context)."""
    source = ENTRY_READINESS_PATH.read_text()
    # Allowed imports.
    for name in _imports_of(ENTRY_READINESS_PATH):
        top = name.split(".")[0]
        assert top in (
            _ALLOWED_STDLIB
            | _ALLOWED_LOCAL_MODULES
            | _ALLOWED_LOCAL_PARENT_PACKAGES
        ), (
            f"entry_readiness_v1: forbidden import: {name}"
        )
    tree = ast.parse(source)
    # No top-level I/O calls.
    v = _top_level_io_violations(tree)
    assert v == [], (
        f"entry_readiness_v1: top-level I/O calls: {v}"
    )
    # No dynamic import / pathlib / sys / loader primitives at any
    # nesting level. This is the strengthened RED-first check: the
    # production module must take ordinary static imports only.
    dyn = _all_dynamic_import_violations(tree)
    assert dyn == [], (
        f"entry_readiness_v1: dynamic import / path / loader "
        f"violations: {dyn}"
    )
    # No top-level __import__/eval/exec/compile.
    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in (
                    "__import__", "eval", "exec", "compile",
                ):
                    raise AssertionError(
                        f"entry_readiness_v1: forbidden top-level call: "
                        f"{f.id}"
                    )
    # No locally-defined public constants + no local-module public
    # attribute leak (must use private aliases).
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and not target.id.startswith("_")):
                    raise AssertionError(
                        f"entry_readiness_v1: public constant: "
                        f"{target.id}"
                    )
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and not node.target.id.startswith("_")):
                raise AssertionError(
                    f"entry_readiness_v1: public constant: "
                    f"{node.target.id}"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _ALLOWED_LOCAL_MODULES:
                    bind = alias.asname or alias.name
                    assert bind.startswith("_"), (
                        f"entry_readiness_v1: local module imported "
                        f"without private alias: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if top in _ALLOWED_LOCAL_MODULES:
                for alias in node.names:
                    bind = alias.asname or alias.name
                    assert bind.startswith("_"), (
                        f"entry_readiness_v1: local module imported "
                        f"without private alias: {node.module}.{alias.name}"
                    )
    # Clean import in a fresh subprocess with ``icp/scripts`` on
    # ``PYTHONPATH``. The production module now takes ordinary static
    # imports of ``requirement_progress_v1`` and
    # ``platforms.platform_package_contract_v1``; that resolution must
    # succeed without any path/bootstrap logic inside the module itself.
    code = "import entry_readiness_v1 as m; print('IMPORT_OK');"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ICP_SCRIPTS),
        },
    )
    assert result.returncode == 0, (
        f"fresh import failed: rc={result.returncode} "
        f"stderr={result.stderr}"
    )
    assert result.stdout.strip() == "IMPORT_OK"


def test_module_source_is_platform_neutral() -> None:
    """The module source must contain no platform / toolchain literal,
    identifier, branch, or import.``"""
    source = ENTRY_READINESS_PATH.read_text()
    lowered = source.lower()
    for lit in PLATFORM_LITERALS:
        assert lit not in lowered, (
            f"entry_readiness_v1: forbidden platform literal: {lit!r}"
        )
    # No ``if platform == ...`` / ``if platform_id == ...`` branch.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            if isinstance(left, ast.Name) and left.id in (
                "platform", "platform_id", "platform_name",
            ):
                raise AssertionError(
                    "entry_readiness_v1: forbidden platform branch"
                )
            for comp in node.comparators:
                if isinstance(comp, ast.Name) and comp.id in (
                    "platform", "platform_id", "platform_name",
                ):
                    raise AssertionError(
                        "entry_readiness_v1: forbidden platform branch"
                    )


# ---------------------------------------------------------------------------
# 18. Reference document and SKILL pointer.
# ---------------------------------------------------------------------------


def test_reference_document_contains_kinds_apis_matrix_boundary_stop_rules() -> None:
    """Single table-driven check covering: every canonical kind, every
    public API name, the fixed core requirement matrix, the closed
    channel IDs, owner / status / decision vocabularies, decision
    mapping, fail-closed behavior, and boundary / stop rules."""
    assert REFERENCE_PATH.exists()
    text = REFERENCE_PATH.read_text()
    for kind in (KIND_OBSERVATION, KIND_READINESS_REPORT,
                 KIND_ENTRY_GATE_DECISION):
        assert kind in text, f"reference missing kind {kind}"
    for api in (
        "EntryReadinessError", "document_digest", "verify_observation",
        "verify_readiness_report", "verify_entry_gate_decision",
        "aggregate_readiness", "decide_entry",
    ):
        assert api in text, f"reference missing API {api}"
    for token in (
        # Core requirement matrix.
        "core.task_source.access", "core.design_source.access",
        "core.project_root.access", "core.state_root.atomic_write",
        # Closed channel mapping.
        "channel.credential_supply", "channel.user_supply",
        # Owner vocabulary.
        "user", "source", "environment", "platform",
        # Precedence keywords.
        "needs-user-input", "blocked", "no-work", "ready",
        "ready -> select-new", "select-new",
        # Decision mapping / fail-closed.
        "new-selection-allowed", "no-work", "prerequisites-blocked",
        # Boundary & stop rules.
        "P3b1a", "P3b1b", "P3d", "Stop", "boundary",
        # Schema tokens.
        "observation-missing", "unsupported-task-source",
        "unsupported-design-source", "invalid-deferred-dependency",
        "blocked-observation",
    ):
        assert token in text, f"reference missing token {token!r}"


def test_skill_pointer_truthful() -> None:
    text = SKILL_PATH.read_text()
    # The SKILL must mention P3b1a as inactive and explicitly defer
    # P3b1b package resolver/selection, production entry wiring, and
    # P3d filesystem I/O.
    assert "P3b1a" in text, "SKILL missing P3b1a pointer"
    for token in (
        "P3b1b", "P3d",
        "entry_readiness_v1.py",
        "selftest_p3b1_entry_readiness.py",
        "entry-readiness-v1.md",
    ):
        assert token in text, f"SKILL missing token {token!r}"
    # The focused selftest command must appear verbatim.
    assert (
        "python3 icp/scripts/selftest_p3b1_entry_readiness.py" in text
    ), "SKILL missing focused selftest command"
    # Truthful: production entry wiring remains unimplemented.
    assert "inactive" in text.lower() or "尚未实现" in text or \
        "unimplemented" in text.lower(), (
            "SKILL does not mark P3b1a inactive / unimplemented"
        )


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
