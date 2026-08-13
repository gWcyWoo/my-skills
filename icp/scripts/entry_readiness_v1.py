#!/usr/bin/env python3
"""ICP P3b1a entry readiness + active-first gate pure contract v1.

Freezes the canonical schema, fail-closed verifiers, the pure
readiness aggregator, and the pure active-first entry gate state
machine for the P3b1a entry slice:

* ``icp.entry-readiness-observation.v1`` -- the normalized observation
  fed to ``aggregate_readiness``.
* ``icp.entry-readiness-report.v1`` -- the aggregated readiness
  report produced by ``aggregate_readiness``.
* ``icp.entry-gate-decision.v1`` -- the active-first entry gate
  decision produced by ``decide_entry``.

P3b1a is platform-neutral and pure in-memory. It performs zero
filesystem I/O, locking, CAS, subprocess, network, write,
TaskSource access, probe execution, or package selection. It does
not import a CSV parser, platform module, vendor capsule, or
production publisher. ``exclusive_lock_acquired`` and
``observed_row_status`` are verified P3b1b / P3d inputs.

P3b1a / P3b1b / P3d boundary:

* P3b1a owns the canonical schemas, ordered keys, enums, digests,
  pure fail-closed verifiers, the pure readiness aggregator, and the
  pure active-first entry gate state machine.
* P3b1b (later, separately approved) owns the package resolver /
  selection, production entry wiring, probe execution, and
  source-snapshot / candidate identity derivation.
* P3d (later, separately approved) owns filesystem publishing,
  locking, CAS, claim / writeback, scratch cleanup, and platform
  binding / authorization / executor wiring.

This module imports only the platform-neutral P3a descriptor contract
(``platforms/platform_package_contract_v1.py``) and the P3a2
requirement-progress contract (``requirement_progress_v1.py``) via
ordinary static private aliases (``_package_contract`` /
``_progress``); it does not re-export them and uses no dynamic loading,
``pathlib`` resolution, or ``sys.path`` mutation.

Public API (no CLI, no import-time I/O):

* ``EntryReadinessError`` -- local error class.
* ``document_digest(document) -> str`` -- canonical SHA-256.
* ``verify_observation(document) -> None``.
* ``verify_readiness_report(document) -> None``.
* ``verify_entry_gate_decision(document) -> None``.
* ``aggregate_readiness(*, resolved_config_digest, package_descriptor,
  task_source_id, design_source_id, task_source_snapshot_digest,
  candidate_identity_digest, candidate_count, observations) -> dict``.
* ``decide_entry(*, readiness_report, active_pointers, progress,
  receipts, expected_identities, exclusive_lock_acquired,
  observed_row_status) -> dict``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Ordinary static imports of the two allowed platform-neutral local
# contract modules. The module must import cleanly when ``icp/scripts``
# is on ``PYTHONPATH`` (the normal script execution context); no
# dynamic loading, no ``sys.path`` mutation, no ``pathlib``-based
# dependency resolution is permitted.
import requirement_progress_v1 as _progress
from platforms import platform_package_contract_v1 as _package_contract

# ---------------------------------------------------------------------------
# Private schema constants.
# ---------------------------------------------------------------------------

_KIND_OBSERVATION = "icp.entry-readiness-observation.v1"
_KIND_READINESS_REPORT = "icp.entry-readiness-report.v1"
_KIND_ENTRY_GATE_DECISION = "icp.entry-gate-decision.v1"
_SCHEMA_VERSION = 1

# Closed status / decision / owner vocabularies.
_OBSERVATION_STATUSES = ("pass", "missing", "blocked", "deferred")
_REPORT_STATUSES = ("needs-user-input", "blocked", "no-work", "ready")
_ENTRY_DECISIONS = (
    "select-new",
    "resume-step",
    "replay-step",
    "run-recovery-verifier",
    "needs-user-input",
    "terminal-cleanup-required",
    "blocked",
    "no-work",
)
_OWNERS = ("user", "source", "environment", "platform")

# Closed entry-decision reason codes. The P3a2 reason codes are mirrored
# here so the verifier accepts both inherited P3a2 reasons (for non
# new-selection-allowed decisions) and the P3b1a-specific entry reasons
# (for new-selection-allowed mappings).
_P3A2_REASON_CODES = (
    "no-active-state", "active-present",
    "multiple-active-pointers", "lock-not-acquired",
    "prerequisites-missing", "prerequisites-blocked",
    "identity-mismatch", "progress-missing", "progress-tamper",
    "receipt-chain-tamper", "row-not-doing", "row-terminal",
    "started-without-replay", "resume-next-step",
    "replay-idempotent", "recovery-verifier-required",
    "terminal-pending",
)
_ENTRY_NEW_SELECTION_REASON_CODES = (
    "entry-ready",
    "entry-needs-user-input",
    "entry-blocked",
    "entry-no-work",
)
_ENTRY_REASON_CODES = _P3A2_REASON_CODES + _ENTRY_NEW_SELECTION_REASON_CODES

# Closed blocker codes / scopes.
_BLOCKER_CODES = (
    "unsupported-task-source",
    "unsupported-design-source",
    "invalid-deferred-dependency",
    "blocked-observation",
)
_BLOCKER_SCOPES = (
    "task-source",
    "design-source",
    "source-compat",
    "requirement",
)

# Closed secure-supply channel mapping. Sensitive inputs use a
# credential-safe channel; non-sensitive inputs use a normal user-supply
# channel. No other channel IDs exist.
_CHANNEL_CREDENTIAL_SAFE = "channel.credential_supply"
_CHANNEL_USER_SUPPLY = "channel.user_supply"

# Closed remediation IDs for source-compatibility blockers.
_REMEDIATION_UNSUPPORTED_TASK_SOURCE = "remediation.unsupported_task_source"
_REMEDIATION_UNSUPPORTED_DESIGN_SOURCE = (
    "remediation.unsupported_design_source"
)

# Synthetic missing-reason code emitted when a required check has no
# matching observation in the input list.
_REASON_OBSERVATION_MISSING = "observation-missing"

# Exact ordered top-level keys for each canonical document.
_OBSERVATION_KEY_ORDER = (
    "kind",
    "schema_version",
    "probe_id",
    "status",
    "evidence_digest",
    "reason_code",
    "blocked_by",
)
_READINESS_REPORT_KEY_ORDER = (
    "kind",
    "schema_version",
    "status",
    "resolved_config_digest",
    "package_descriptor_digest",
    "task_source_snapshot_digest",
    "candidate_identity_digest",
    "checks",
    "missing_user_inputs",
    "deferred_checks",
    "blockers",
)
_ENTRY_GATE_DECISION_KEY_ORDER = (
    "kind",
    "schema_version",
    "decision",
    "reason_code",
    "readiness_report_digest",
    "resume_decision_digest",
    "requirement_id",
    "progress_id",
    "feature_id",
    "step_id",
    "checkpoint_receipt_digest",
)

# Exact ordered keys for each nested object.
_CHECK_KEY_ORDER = ("id", "owner", "status", "evidence_digest")
_MISSING_USER_INPUT_KEY_ORDER = (
    "id",
    "reason_code",
    "accepted_shape_id",
    "secure_supply_channel",
    "sensitive",
)
_DEFERRED_CHECK_KEY_ORDER = ("id", "blocked_by")
_BLOCKER_KEY_ORDER = ("code", "scope", "evidence_digest", "remediation_id")

# Fixed core readiness requirements. Each entry has the exact ordered
# keys of a descriptor entry_requirement (id / owner / required /
# sensitive / probe_id / accepted_shape_id / remediation_id) so the
# same metadata-driven rendering path covers core and descriptor
# requirements uniformly. Core probe_ids are one-to-one with core
# requirement ids; both are platform-neutral and source-neutral.
_CORE_REQUIREMENTS = (
    {
        "id": "core.task_source.access",
        "owner": "source",
        "required": True,
        "sensitive": False,
        "probe_id": "core.task_source.access",
        "accepted_shape_id": "shape.task_source_readable",
        "remediation_id": "remediation.supply_task_source_access",
    },
    {
        "id": "core.design_source.access",
        "owner": "source",
        "required": True,
        "sensitive": True,
        "probe_id": "core.design_source.access",
        "accepted_shape_id": "shape.design_source_credential_slot",
        "remediation_id": "remediation.supply_design_source_credential",
    },
    {
        "id": "core.project_root.access",
        "owner": "user",
        "required": True,
        "sensitive": False,
        "probe_id": "core.project_root.access",
        "accepted_shape_id": "shape.existing_directory_under_workspace",
        "remediation_id": "remediation.supply_project_root",
    },
    {
        "id": "core.state_root.atomic_write",
        "owner": "environment",
        "required": True,
        "sensitive": False,
        "probe_id": "core.state_root.atomic_write",
        "accepted_shape_id": "shape.atomic_write_capability",
        "remediation_id": "remediation.supply_state_root_atomic_write",
    },
)

# Forbidden injection field names anywhere in any P3b1a document. These
# would re-introduce an executable / injection surface. Rejection is by
# exact dictionary key only; a forbidden word appearing as part of a
# larger identifier (e.g. ``design_url_handler``) is NOT rejected.
_INJECTION_FIELD_NAMES = frozenset(
    {
        "command", "argv", "shell", "interpreter", "env", "runner",
        "args", "program", "cmd", "subprocess", "exec", "run",
        "script_path", "script_runner", "activate",
        "activation_command", "activation_override", "prompt",
        "prompt_template", "path", "task_ref", "row_title",
        "design_url", "secret", "token", "password", "credential",
        "api_key", "claim_ack", "writeback_ack", "row_payload",
    }
)

_SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-"
)


class EntryReadinessError(ValueError):
    """A local entry-readiness validation / decision failure.

    Raised for any shape, type, enum, ordering, duplicate, unknown-key,
    injection, identity, derivation, or content violation.
    """


# ---------------------------------------------------------------------------
# Small deterministic helpers.
# ---------------------------------------------------------------------------


def _canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_bool(value: Any) -> bool:
    return value is True or value is False


def _is_non_negative_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _is_safe_id(value: Any) -> bool:
    """Controlled safe ID: lowercase ASCII letters, digits, `.`, `_`,
    `-`; non-empty; length <= 128."""
    if not isinstance(value, str) or not value:
        return False
    if len(value) > 128:
        return False
    for c in value:
        if c not in _SAFE_ID_CHARS:
            return False
    return True


def _check_keys_exact_order(
    actual: Any, expected_order: tuple, location: str
) -> None:
    if not isinstance(actual, dict):
        raise EntryReadinessError(f"{location}: must be an object")
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise EntryReadinessError(
            f"{location}: key order mismatch: "
            f"extra={extra} missing={missing}"
        )


def _reject_injection_fields(obj: Any, location: str) -> None:
    """Recursively reject forbidden command / argv / env / shell /
    prompt / path / task_ref / secret / credential / ack / row-payload
    fields anywhere. Rejection is by exact dictionary key only."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key in _INJECTION_FIELD_NAMES:
                raise EntryReadinessError(
                    f"forbidden injection field: {here}"
                )
            _reject_injection_fields(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_injection_fields(item, f"{location}[{i}]")


# ---------------------------------------------------------------------------
# Public API: canonical document digest.
# ---------------------------------------------------------------------------


def document_digest(document: dict) -> str:
    """Canonical SHA-256 of a document.

    Canonical bytes are::

        (json.dumps(document, ensure_ascii=False, indent=2,
                    sort_keys=True) + "\\n").encode("utf-8")

    Documents carry no self-referential digest field.
    """
    if not isinstance(document, dict):
        raise EntryReadinessError("document: must be an object")
    return _sha256_bytes(_canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Public API: observation verifier.
# ---------------------------------------------------------------------------


def _verify_safe_id_list(value: Any, location: str) -> None:
    """Strict-sorted unique safe-ID list (used for ``blocked_by``)."""
    if not isinstance(value, list):
        raise EntryReadinessError(f"{location}: must be a list")
    last: str | None = None
    seen: set = set()
    for i, item in enumerate(value):
        here = f"{location}[{i}]"
        if not _is_safe_id(item):
            raise EntryReadinessError(
                f"{here}: not a controlled safe ID"
            )
        if item in seen:
            raise EntryReadinessError(
                f"{here}: duplicate: {item!r}"
            )
        seen.add(item)
        if last is not None and item <= last:
            raise EntryReadinessError(
                f"{here}: not strictly sorted"
            )
        last = item


def verify_observation(document: dict) -> None:
    """Strict fail-closed validation of an observation document."""
    if not isinstance(document, dict):
        raise EntryReadinessError("observation: must be an object")
    _check_keys_exact_order(
        document, _OBSERVATION_KEY_ORDER, "observation"
    )
    if document["kind"] != _KIND_OBSERVATION:
        raise EntryReadinessError(
            f"observation.kind: must be {_KIND_OBSERVATION!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise EntryReadinessError(
            f"observation.schema_version: must be "
            f"{_SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    if not _is_safe_id(document["probe_id"]):
        raise EntryReadinessError(
            "observation.probe_id: not a controlled safe ID"
        )
    status = document["status"]
    if status not in _OBSERVATION_STATUSES:
        raise EntryReadinessError(
            f"observation.status: not controlled: {status!r}"
        )
    evidence = document["evidence_digest"]
    if evidence is not None and not _is_sha256_hex(evidence):
        raise EntryReadinessError(
            "observation.evidence_digest: must be null or "
            "SHA-256 hex (64 lowercase)"
        )
    reason = document["reason_code"]
    if reason is not None and not _is_safe_id(reason):
        raise EntryReadinessError(
            "observation.reason_code: must be null or a "
            "controlled safe ID"
        )
    _verify_safe_id_list(document["blocked_by"], "observation.blocked_by")
    # Status-specific rules.
    if status == "pass":
        if evidence is None:
            raise EntryReadinessError(
                "observation pass: evidence_digest must be non-null"
            )
        if reason is not None:
            raise EntryReadinessError(
                "observation pass: reason_code must be null"
            )
        if document["blocked_by"]:
            raise EntryReadinessError(
                "observation pass: blocked_by must be empty"
            )
    elif status == "missing":
        if evidence is not None:
            raise EntryReadinessError(
                "observation missing: evidence_digest must be null"
            )
        if reason is None:
            raise EntryReadinessError(
                "observation missing: reason_code must be non-null"
            )
        if document["blocked_by"]:
            raise EntryReadinessError(
                "observation missing: blocked_by must be empty"
            )
    elif status == "blocked":
        if reason is None:
            raise EntryReadinessError(
                "observation blocked: reason_code must be non-null"
            )
        if document["blocked_by"]:
            raise EntryReadinessError(
                "observation blocked: blocked_by must be empty"
            )
        # evidence may be sha or null
    else:  # deferred
        if evidence is not None:
            raise EntryReadinessError(
                "observation deferred: evidence_digest must be null"
            )
        if reason is None:
            raise EntryReadinessError(
                "observation deferred: reason_code must be non-null"
            )
        if not document["blocked_by"]:
            raise EntryReadinessError(
                "observation deferred: blocked_by must be non-empty"
            )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Internal: nested-object verifiers used by verify_readiness_report.
# ---------------------------------------------------------------------------


def _verify_check_entry(value: Any, location: str) -> None:
    _check_keys_exact_order(value, _CHECK_KEY_ORDER, location)
    if not _is_safe_id(value["id"]):
        raise EntryReadinessError(
            f"{location}.id: not a controlled safe ID"
        )
    if value["owner"] not in _OWNERS:
        raise EntryReadinessError(
            f"{location}.owner: not controlled: {value['owner']!r}"
        )
    if value["status"] not in _OBSERVATION_STATUSES:
        raise EntryReadinessError(
            f"{location}.status: not controlled: {value['status']!r}"
        )
    ev = value["evidence_digest"]
    if ev is not None and not _is_sha256_hex(ev):
        raise EntryReadinessError(
            f"{location}.evidence_digest: must be null or "
            f"SHA-256 hex (64 lowercase)"
        )
    if value["status"] == "pass" and ev is None:
        raise EntryReadinessError(
            f"{location}: pass check must carry evidence_digest"
        )


def _verify_missing_user_input(value: Any, location: str) -> None:
    _check_keys_exact_order(
        value, _MISSING_USER_INPUT_KEY_ORDER, location
    )
    if not _is_safe_id(value["id"]):
        raise EntryReadinessError(
            f"{location}.id: not a controlled safe ID"
        )
    if not _is_safe_id(value["reason_code"]):
        raise EntryReadinessError(
            f"{location}.reason_code: not a controlled safe ID"
        )
    if not _is_safe_id(value["accepted_shape_id"]):
        raise EntryReadinessError(
            f"{location}.accepted_shape_id: not a controlled safe ID"
        )
    if value["secure_supply_channel"] not in (
        _CHANNEL_CREDENTIAL_SAFE,
        _CHANNEL_USER_SUPPLY,
    ):
        raise EntryReadinessError(
            f"{location}.secure_supply_channel: not a controlled "
            f"channel id"
        )
    if not _is_bool(value["sensitive"]):
        raise EntryReadinessError(
            f"{location}.sensitive: must be a bool"
        )


def _verify_deferred_check(value: Any, location: str) -> None:
    _check_keys_exact_order(
        value, _DEFERRED_CHECK_KEY_ORDER, location
    )
    if not _is_safe_id(value["id"]):
        raise EntryReadinessError(
            f"{location}.id: not a controlled safe ID"
        )
    _verify_safe_id_list(value["blocked_by"], f"{location}.blocked_by")
    if not value["blocked_by"]:
        raise EntryReadinessError(
            f"{location}.blocked_by: must be non-empty"
        )


def _verify_blocker(value: Any, location: str) -> None:
    _check_keys_exact_order(value, _BLOCKER_KEY_ORDER, location)
    if value["code"] not in _BLOCKER_CODES:
        raise EntryReadinessError(
            f"{location}.code: not controlled: {value['code']!r}"
        )
    if value["scope"] not in _BLOCKER_SCOPES:
        raise EntryReadinessError(
            f"{location}.scope: not controlled: {value['scope']!r}"
        )
    ev = value["evidence_digest"]
    if ev is not None and not _is_sha256_hex(ev):
        raise EntryReadinessError(
            f"{location}.evidence_digest: must be null or "
            f"SHA-256 hex (64 lowercase)"
        )
    if not _is_safe_id(value["remediation_id"]):
        raise EntryReadinessError(
            f"{location}.remediation_id: not a controlled safe ID"
        )


def _verify_strictly_sorted_unique(
    values: Any, *, key: str, label: str
) -> None:
    """Verify ``values`` is a list of dicts, each carrying ``key``,
    strictly sorted and unique by ``key``."""
    if not isinstance(values, list):
        raise EntryReadinessError(f"{label}: must be a list")
    last: str | None = None
    seen: set = set()
    for i, item in enumerate(values):
        if not isinstance(item, dict):
            raise EntryReadinessError(
                f"{label}[{i}]: must be an object"
            )
        if key not in item:
            raise EntryReadinessError(
                f"{label}[{i}]: missing key {key!r}"
            )
        identity = item[key]
        if identity in seen:
            raise EntryReadinessError(
                f"{label}[{i}].{key}: duplicate: {identity!r}"
            )
        seen.add(identity)
        if last is not None and identity <= last:
            raise EntryReadinessError(
                f"{label}[{i}].{key}: not strictly sorted"
            )
        last = identity


def _verify_blockers_sorted_unique(values: Any, label: str) -> None:
    """Blockers have no single id key; uniqueness and strict ordering
    are by the full content tuple (code, scope, evidence_digest,
    remediation_id)."""
    if not isinstance(values, list):
        raise EntryReadinessError(f"{label}: must be a list")
    last: tuple | None = None
    seen: set = set()
    for i, item in enumerate(values):
        if not isinstance(item, dict):
            raise EntryReadinessError(
                f"{label}[{i}]: must be an object"
            )
        identity = (
            item.get("code"),
            item.get("scope"),
            item.get("evidence_digest"),
            item.get("remediation_id"),
        )
        if identity in seen:
            raise EntryReadinessError(
                f"{label}[{i}]: duplicate blocker: {identity!r}"
            )
        seen.add(identity)
        if last is not None and identity <= last:
            raise EntryReadinessError(
                f"{label}[{i}]: not strictly sorted"
            )
        last = identity


# ---------------------------------------------------------------------------
# Public API: readiness-report verifier.
# ---------------------------------------------------------------------------


def verify_readiness_report(document: dict) -> None:
    """Strict fail-closed validation of the readiness report."""
    if not isinstance(document, dict):
        raise EntryReadinessError(
            "readiness_report: must be an object"
        )
    _check_keys_exact_order(
        document, _READINESS_REPORT_KEY_ORDER, "readiness_report"
    )
    if document["kind"] != _KIND_READINESS_REPORT:
        raise EntryReadinessError(
            f"readiness_report.kind: must be "
            f"{_KIND_READINESS_REPORT!r}, got {document['kind']!r}"
        )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise EntryReadinessError(
            f"readiness_report.schema_version: must be "
            f"{_SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    if document["status"] not in _REPORT_STATUSES:
        raise EntryReadinessError(
            f"readiness_report.status: not controlled: "
            f"{document['status']!r}"
        )
    for key in (
        "resolved_config_digest",
        "package_descriptor_digest",
        "task_source_snapshot_digest",
        "candidate_identity_digest",
    ):
        if not _is_sha256_hex(document[key]):
            raise EntryReadinessError(
                f"readiness_report.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )
    # checks[]: each entry has exact ordered keys + controlled values;
    # strictly sorted unique by id.
    checks = document["checks"]
    if not isinstance(checks, list):
        raise EntryReadinessError(
            "readiness_report.checks: must be a list"
        )
    for i, c in enumerate(checks):
        _verify_check_entry(c, f"readiness_report.checks[{i}]")
    _verify_strictly_sorted_unique(
        checks, key="id", label="readiness_report.checks"
    )
    # missing_user_inputs[]: exact keys + controlled channel; strictly
    # sorted unique by id.
    muis = document["missing_user_inputs"]
    if not isinstance(muis, list):
        raise EntryReadinessError(
            "readiness_report.missing_user_inputs: must be a list"
        )
    for i, m in enumerate(muis):
        _verify_missing_user_input(
            m, f"readiness_report.missing_user_inputs[{i}]"
        )
    _verify_strictly_sorted_unique(
        muis, key="id", label="readiness_report.missing_user_inputs"
    )
    # deferred_checks[]: exact keys + non-empty strictly-sorted-unique
    # blocked_by; strictly sorted unique by id.
    dcs = document["deferred_checks"]
    if not isinstance(dcs, list):
        raise EntryReadinessError(
            "readiness_report.deferred_checks: must be a list"
        )
    for i, d in enumerate(dcs):
        _verify_deferred_check(
            d, f"readiness_report.deferred_checks[{i}]"
        )
    _verify_strictly_sorted_unique(
        dcs, key="id", label="readiness_report.deferred_checks"
    )
    # blockers[]: exact keys + controlled code/scope; strictly sorted
    # unique by full content tuple.
    blockers = document["blockers"]
    if not isinstance(blockers, list):
        raise EntryReadinessError(
            "readiness_report.blockers: must be a list"
        )
    for i, b in enumerate(blockers):
        _verify_blocker(b, f"readiness_report.blockers[{i}]")
    _verify_blockers_sorted_unique(
        blockers, "readiness_report.blockers"
    )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: entry-gate-decision verifier.
# ---------------------------------------------------------------------------


def verify_entry_gate_decision(document: dict) -> None:
    """Strict fail-closed validation of the entry gate decision."""
    if not isinstance(document, dict):
        raise EntryReadinessError(
            "entry_gate_decision: must be an object"
        )
    _check_keys_exact_order(
        document, _ENTRY_GATE_DECISION_KEY_ORDER, "entry_gate_decision"
    )
    if document["kind"] != _KIND_ENTRY_GATE_DECISION:
        raise EntryReadinessError(
            f"entry_gate_decision.kind: must be "
            f"{_KIND_ENTRY_GATE_DECISION!r}, got {document['kind']!r}"
        )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise EntryReadinessError(
            f"entry_gate_decision.schema_version: must be "
            f"{_SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    if document["decision"] not in _ENTRY_DECISIONS:
        raise EntryReadinessError(
            f"entry_gate_decision.decision: not controlled: "
            f"{document['decision']!r}"
        )
    if document["reason_code"] not in _ENTRY_REASON_CODES:
        raise EntryReadinessError(
            f"entry_gate_decision.reason_code: not controlled: "
            f"{document['reason_code']!r}"
        )
    for key in ("readiness_report_digest", "resume_decision_digest"):
        if not _is_sha256_hex(document[key]):
            raise EntryReadinessError(
                f"entry_gate_decision.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )
    for key in (
        "requirement_id", "progress_id", "checkpoint_receipt_digest",
    ):
        v = document[key]
        if v is not None and not _is_sha256_hex(v):
            raise EntryReadinessError(
                f"entry_gate_decision.{key}: must be null or "
                f"SHA-256 hex (64 lowercase)"
            )
    for key in ("feature_id", "step_id"):
        v = document[key]
        if v is not None and not _is_safe_id(v):
            raise EntryReadinessError(
                f"entry_gate_decision.{key}: must be null or a "
                f"controlled safe ID"
            )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Internal: requirement / observation matching helpers.
# ---------------------------------------------------------------------------


def _verify_observations_sorted_unique(observations: Any) -> None:
    """The input observation list must be strictly sorted and unique
    by ``probe_id`` (after each observation passes its verifier)."""
    if not isinstance(observations, list):
        raise EntryReadinessError("observations: must be a list")
    last: str | None = None
    seen: set = set()
    for i, obs in enumerate(observations):
        try:
            verify_observation(obs)
        except EntryReadinessError as exc:
            raise EntryReadinessError(
                f"observations[{i}]: {exc}"
            ) from exc
        pid = obs["probe_id"]
        if pid in seen:
            raise EntryReadinessError(
                f"observations[{i}].probe_id: duplicate: {pid!r}"
            )
        seen.add(pid)
        if last is not None and pid <= last:
            raise EntryReadinessError(
                f"observations[{i}].probe_id: not strictly sorted"
            )
        last = pid


def _build_requirement_view(
    descriptor: dict,
) -> tuple[list[dict], set[str], set[str]]:
    """Build the combined (core + descriptor) requirement view.

    Returns ``(all_reqs, all_ids, all_probe_ids)``. Raises on id
    collision between core and descriptor requirements.
    """
    core_reqs = [dict(r) for r in _CORE_REQUIREMENTS]
    core_ids = {r["id"] for r in core_reqs}
    descriptor_reqs: list[dict] = []
    for er in descriptor["entry_requirements"]:
        # The shared descriptor validator already verified the
        # entry-requirement key shape; copy the values into the
        # canonical metadata-driven view.
        descriptor_reqs.append(
            {
                "id": er["id"],
                "owner": er["owner"],
                "required": er["required"],
                "sensitive": er["sensitive"],
                "probe_id": er["probe_id"],
                "accepted_shape_id": er["accepted_shape_id"],
                "remediation_id": er["remediation_id"],
            }
        )
        if er["id"] in core_ids:
            raise EntryReadinessError(
                f"requirement id collision between core and "
                f"descriptor: {er['id']!r}"
            )
    all_reqs = core_reqs + descriptor_reqs
    all_ids = {r["id"] for r in all_reqs}
    all_probe_ids = {r["probe_id"] for r in all_reqs}
    return all_reqs, all_ids, all_probe_ids


def _channel_for(sensitive: bool) -> str:
    if sensitive:
        return _CHANNEL_CREDENTIAL_SAFE
    return _CHANNEL_USER_SUPPLY


# ---------------------------------------------------------------------------
# Public API: aggregate_readiness.
# ---------------------------------------------------------------------------


def aggregate_readiness(
    *,
    resolved_config_digest: str,
    package_descriptor: dict,
    task_source_id: str,
    design_source_id: str,
    task_source_snapshot_digest: str,
    candidate_identity_digest: str,
    candidate_count: int,
    observations: list[dict],
) -> dict:
    """Aggregate normalized observations into a readiness report.

    Performs the following, in order:

    1. Validate the basic scalar inputs (digests are bare SHA-256 hex;
       ``task_source_id`` / ``design_source_id`` are controlled safe
       IDs; ``candidate_count`` is a non-negative integer;
       ``observations`` is a list).
    2. Validate the package descriptor using the existing
       platform-neutral P3a descriptor validator; compute its digest
       itself.
    3. Validate each observation via :func:`verify_observation` and
       require the input list to be strictly sorted and unique by
       ``probe_id``.
    4. Build the combined core + descriptor requirement view; reject
       any id collision between core and descriptor requirements.
    5. Reject any observation whose ``probe_id`` is not referenced by
       at least one requirement (extra / unknown observation).
    6. For each requirement, match exactly one observation by
       ``probe_id``. Absence becomes a deterministic synthetic
       ``missing / observation-missing`` check.
    7. Derive ``blockers``, ``missing_user_inputs``, ``deferred_checks``
       and the overall report status from the closed precedence.
    8. Build the canonical report and re-verify it before return.

    Unsupported ``task_source_id`` / ``design_source_id`` (relative to
    the descriptor's ``supported_*`` lists) become deterministic
    blocker entries (and an overall ``blocked`` status), not an
    exception -- the exception path is reserved for malformed basic
    schemas only.
    """
    # 1. Basic scalar input validation.
    if not _is_sha256_hex(resolved_config_digest):
        raise EntryReadinessError(
            "resolved_config_digest: must be SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(task_source_snapshot_digest):
        raise EntryReadinessError(
            "task_source_snapshot_digest: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if not _is_sha256_hex(candidate_identity_digest):
        raise EntryReadinessError(
            "candidate_identity_digest: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if not _is_safe_id(task_source_id):
        raise EntryReadinessError(
            "task_source_id: not a controlled safe ID"
        )
    if not _is_safe_id(design_source_id):
        raise EntryReadinessError(
            "design_source_id: not a controlled safe ID"
        )
    if not _is_non_negative_int(candidate_count):
        raise EntryReadinessError(
            "candidate_count: must be a non-negative integer "
            "(booleans rejected)"
        )
    if not isinstance(observations, list):
        raise EntryReadinessError("observations: must be a list")

    # 2. Validate descriptor + compute its digest.
    if not isinstance(package_descriptor, dict):
        raise EntryReadinessError(
            "package_descriptor: must be an object"
        )
    _package_contract.validate_descriptor(package_descriptor)
    package_descriptor_digest = _package_contract.compute_descriptor_digest(
        package_descriptor
    )

    # 3. Validate observations + strict sort / uniqueness.
    _verify_observations_sorted_unique(observations)

    # 4. Build combined requirement view; reject id collisions.
    all_reqs, all_ids, all_probe_ids = _build_requirement_view(
        package_descriptor
    )

    # 5. Reject unknown probe_ids in observations.
    obs_by_probe: dict[str, dict] = {}
    for obs in observations:
        pid = obs["probe_id"]
        if pid not in all_probe_ids:
            raise EntryReadinessError(
                f"observations: probe_id not referenced by any "
                f"requirement: {pid!r}"
            )
        obs_by_probe[pid] = obs

    # 6. Build per-requirement check entries.
    check_entries: list[dict] = []
    for req in all_reqs:
        obs = obs_by_probe.get(req["probe_id"])
        if obs is None:
            check_entries.append(
                {
                    "requirement": req,
                    "status": "missing",
                    "evidence_digest": None,
                    "reason_code": _REASON_OBSERVATION_MISSING,
                    "obs_blocked_by": [],
                }
            )
        else:
            check_entries.append(
                {
                    "requirement": req,
                    "status": obs["status"],
                    "evidence_digest": obs["evidence_digest"],
                    "reason_code": obs["reason_code"],
                    "obs_blocked_by": list(obs["blocked_by"]),
                }
            )

    # Sort the entries by requirement id so the output checks list is
    # canonical and stable.
    check_entries.sort(key=lambda c: c["requirement"]["id"])

    # 7a. Build blockers / detect invalid-deferred-dependency / blocked.
    blockers: list[dict] = []
    has_invalid_deferred = False

    # Source-compatibility blockers (deterministic; not exceptions).
    supported_task_sources = package_descriptor["supported_task_sources"]
    supported_design_sources = package_descriptor[
        "supported_design_sources"
    ]
    if task_source_id not in supported_task_sources:
        blockers.append(
            {
                "code": "unsupported-task-source",
                "scope": "source-compat",
                "evidence_digest": None,
                "remediation_id": _REMEDIATION_UNSUPPORTED_TASK_SOURCE,
            }
        )
    if design_source_id not in supported_design_sources:
        blockers.append(
            {
                "code": "unsupported-design-source",
                "scope": "source-compat",
                "evidence_digest": None,
                "remediation_id": _REMEDIATION_UNSUPPORTED_DESIGN_SOURCE,
            }
        )

    # Per-check blockers + invalid-deferred-dependency detection.
    for entry in check_entries:
        status = entry["status"]
        if status == "blocked":
            blockers.append(
                {
                    "code": "blocked-observation",
                    "scope": "requirement",
                    "evidence_digest": entry["evidence_digest"],
                    "remediation_id": entry["requirement"][
                        "remediation_id"
                    ],
                }
            )
        elif status == "deferred":
            for bid in entry["obs_blocked_by"]:
                if bid not in all_ids:
                    blockers.append(
                        {
                            "code": "invalid-deferred-dependency",
                            "scope": "requirement",
                            "evidence_digest": entry["evidence_digest"],
                            "remediation_id": entry["requirement"][
                                "remediation_id"
                            ],
                        }
                    )
                    has_invalid_deferred = True

    # Dedup + sort blockers by full content tuple.
    blockers = _dedup_and_sort_blockers(blockers)

    # 7b. Determine missing requirement ids and required-missing flag.
    missing_req_ids = {
        e["requirement"]["id"]
        for e in check_entries
        if e["status"] == "missing"
    }
    has_required_missing = any(
        e["status"] == "missing" and e["requirement"]["required"]
        for e in check_entries
    )

    # 7c. Detect deferred checks whose blocked_by points only to a
    # missing requirement in this same report. Those, alongside any
    # required missing check, escalate the report to
    # ``needs-user-input``.
    has_deferred_only_missing = False
    for entry in check_entries:
        if entry["status"] != "deferred":
            continue
        # Skip if any blocked_by id is unknown -- that already produced
        # an invalid-deferred-dependency blocker above.
        if not all(bid in all_ids for bid in entry["obs_blocked_by"]):
            continue
        if entry["obs_blocked_by"] and all(
            bid in missing_req_ids for bid in entry["obs_blocked_by"]
        ):
            has_deferred_only_missing = True

    has_blocker = bool(blockers)

    # 7d. Overall precedence.
    if has_blocker or has_invalid_deferred:
        overall_status = "blocked"
    elif has_required_missing or has_deferred_only_missing:
        overall_status = "needs-user-input"
    elif candidate_count == 0:
        overall_status = "no-work"
    else:
        overall_status = "ready"

    # 7e. Build the canonical checks / missing_user_inputs /
    # deferred_checks lists.
    checks_out: list[dict] = []
    missing_user_inputs: list[dict] = []
    deferred_checks_out: list[dict] = []
    for entry in check_entries:
        req = entry["requirement"]
        checks_out.append(
            {
                "id": req["id"],
                "owner": req["owner"],
                "status": entry["status"],
                "evidence_digest": entry["evidence_digest"],
            }
        )
        if (
            entry["status"] == "missing"
            and req["required"]
        ):
            missing_user_inputs.append(
                {
                    "id": req["id"],
                    "reason_code": entry["reason_code"],
                    "accepted_shape_id": req["accepted_shape_id"],
                    "secure_supply_channel": _channel_for(
                        req["sensitive"]
                    ),
                    "sensitive": req["sensitive"],
                }
            )
        if entry["status"] == "deferred":
            # Include only deferred checks whose blocked_by are all
            # valid -- invalid-deferred-dependency checks are already
            # represented as blockers.
            if all(bid in all_ids for bid in entry["obs_blocked_by"]):
                deferred_checks_out.append(
                    {
                        "id": req["id"],
                        "blocked_by": list(entry["obs_blocked_by"]),
                    }
                )

    # All three lists are already sorted by id (because check_entries
    # was sorted by requirement id). Blockers are sorted above.

    # 8. Build the report and re-verify before return.
    report = {
        "kind": _KIND_READINESS_REPORT,
        "schema_version": _SCHEMA_VERSION,
        "status": overall_status,
        "resolved_config_digest": resolved_config_digest,
        "package_descriptor_digest": package_descriptor_digest,
        "task_source_snapshot_digest": task_source_snapshot_digest,
        "candidate_identity_digest": candidate_identity_digest,
        "checks": checks_out,
        "missing_user_inputs": missing_user_inputs,
        "deferred_checks": deferred_checks_out,
        "blockers": blockers,
    }
    verify_readiness_report(report)
    return report


def _dedup_and_sort_blockers(blockers: list[dict]) -> list[dict]:
    """Dedup by full content tuple and sort by (code, scope,
    evidence_digest, remediation_id). ``evidence_digest`` may be
    ``None``; ``None`` compares less than any string, which keeps the
    sort stable and deterministic."""
    seen: set = set()
    unique: list[dict] = []
    for b in blockers:
        key = (
            b["code"],
            b["scope"],
            b["evidence_digest"],
            b["remediation_id"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)

    def sort_key(b: dict) -> tuple:
        ev = b["evidence_digest"]
        return (
            b["code"],
            b["scope"],
            "" if ev is None else ev,
            b["remediation_id"],
        )

    unique.sort(key=sort_key)
    return unique


# ---------------------------------------------------------------------------
# Public API: decide_entry.
# ---------------------------------------------------------------------------


def _prerequisites_from_report(
    report_status: str, active_pointer_count: int
) -> str:
    """Derive the P3a2 ``prerequisites_status`` solely from the verified
    readiness report's overall status.

    * ``ready`` -> ``met``
    * ``needs-user-input`` -> ``missing``
    * ``blocked`` -> ``blocked``
    * ``no-work`` -> ``met`` only when there are zero active pointers;
      with any active pointer it is a contradictory active-readiness
      state and is mapped to ``blocked`` so the P3a2 state machine
      fails closed.
    """
    if report_status == "ready":
        return "met"
    if report_status == "needs-user-input":
        return "missing"
    if report_status == "blocked":
        return "blocked"
    if report_status == "no-work":
        if active_pointer_count == 0:
            return "met"
        return "blocked"
    # The report verifier already restricts this to the closed enum;
    # defensive guard for safety.
    raise EntryReadinessError(
        f"unknown readiness status: {report_status!r}"
    )


def decide_entry(
    *,
    readiness_report: dict,
    active_pointers: list[dict],
    progress: dict | None,
    receipts: list[dict],
    expected_identities: dict,
    exclusive_lock_acquired: bool,
    observed_row_status: str,
) -> dict:
    """Pure active-first entry gate state machine.

    Verifies the readiness report, derives the P3a2
    ``prerequisites_status`` from its overall status, and calls the
    existing P3a2 ``decide_resume`` state machine with the raw
    active / progress / receipt inputs.

    Active-first mapping:

    * Any P3a2 decision other than ``new-selection-allowed`` wins over
      a new selection and is mapped without changing its reason or
      step-identity fields.
    * Only P3a2 ``new-selection-allowed`` consults the report for a
      new route: ``ready -> select-new``, ``needs-user-input ->
      needs-user-input``, ``blocked -> blocked``, ``no-work ->
      no-work``.

    The returned entry gate decision embeds only digests and
    controlled identity fields. It never embeds the full readiness or
    resume documents.
    """
    # Verify the readiness report.
    verify_readiness_report(readiness_report)
    if not isinstance(active_pointers, list):
        raise EntryReadinessError(
            "active_pointers: must be a list"
        )

    report_status = readiness_report["status"]
    prerequisites_status = _prerequisites_from_report(
        report_status, len(active_pointers)
    )

    # Call P3a2 decide_resume with the raw inputs and the derived
    # prerequisites status.
    resume_decision = _progress.decide_resume(
        active_pointers,
        progress=progress,
        receipts=receipts,
        expected_identities=expected_identities,
        exclusive_lock_acquired=exclusive_lock_acquired,
        prerequisites_status=prerequisites_status,
        observed_row_status=observed_row_status,
    )

    resume_decision_digest = _progress.document_digest(
        resume_decision
    )
    readiness_report_digest = document_digest(readiness_report)

    # Map P3a2 decision to entry decision.
    p3a2_decision = resume_decision["decision"]
    if p3a2_decision != "new-selection-allowed":
        # Keep the same decision literal + reason + step identity
        # fields.
        entry_decision = p3a2_decision
        entry_reason = resume_decision["reason_code"]
        requirement_id = resume_decision["requirement_id"]
        progress_id = resume_decision["progress_id"]
        feature_id = resume_decision["feature_id"]
        step_id = resume_decision["step_id"]
        checkpoint_receipt_digest = resume_decision[
            "checkpoint_receipt_digest"
        ]
    else:
        # Only P3a2 new-selection-allowed may consult the report for a
        # new route.
        if report_status == "ready":
            entry_decision = "select-new"
            entry_reason = "entry-ready"
        elif report_status == "needs-user-input":
            entry_decision = "needs-user-input"
            entry_reason = "entry-needs-user-input"
        elif report_status == "blocked":
            entry_decision = "blocked"
            entry_reason = "entry-blocked"
        elif report_status == "no-work":
            entry_decision = "no-work"
            entry_reason = "entry-no-work"
        else:
            raise EntryReadinessError(
                f"unknown readiness status: {report_status!r}"
            )
        requirement_id = None
        progress_id = None
        feature_id = None
        step_id = None
        checkpoint_receipt_digest = None

    decision = {
        "kind": _KIND_ENTRY_GATE_DECISION,
        "schema_version": _SCHEMA_VERSION,
        "decision": entry_decision,
        "reason_code": entry_reason,
        "readiness_report_digest": readiness_report_digest,
        "resume_decision_digest": resume_decision_digest,
        "requirement_id": requirement_id,
        "progress_id": progress_id,
        "feature_id": feature_id,
        "step_id": step_id,
        "checkpoint_receipt_digest": checkpoint_receipt_digest,
    }
    verify_entry_gate_decision(decision)
    return decision
