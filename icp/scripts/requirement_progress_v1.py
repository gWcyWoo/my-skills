#!/usr/bin/env python3
"""ICP P3a2 requirement progress / resume / cleanup pure contract v1.

Freezes the canonical schema, locked SHA-256 derivations, and pure
decision state machines for the per-requirement lifecycle:

* ``icp.active-requirement.v1`` -- the immutable state-root active
  pointer. Created only after a claim ack is verified/reconstructed;
  binds a stable ``progress_id``; never stores the changing
  progress-document digest, a mutable lifecycle flag, a path, or any
  task content.
* ``icp.requirement-progress.v1`` -- the mutable progress cursor.
* ``icp.checkpoint-receipt.v1`` -- the immutable per-step receipt that
  forms an ordered hash chain rooted at ``GENESIS_RECEIPT_DIGEST``.
* ``icp.requirement-resume-decision.v1`` -- the controlled decision
  returned by the pure ``decide_resume`` state machine.
* ``icp.requirement-cleanup-plan.v1`` and
  ``icp.requirement-cleanup-report.v1`` -- the terminal-cleanup
  planning and verified-cleanup contracts.

P3a2 is TaskSource-neutral. This module performs zero filesystem I/O,
locking, CAS, subprocess, network, write, or unlink/cleanup. It does
not import a CSV parser, ``csv_task_source``, ``csv_row_status_v1``,
``prepare_selection``, platform modules, production publishers, or
``iff``. ``exclusive_lock_acquired`` is a verified P3d input; this
module never inspects a filesystem or acquires a lock itself. P3d
executes the fixed terminal-cleanup action IDs and feeds verified
observations back to ``verify_terminal_cleanup``.

Public API (no CLI, no import-time I/O, only stdlib ``hashlib`` /
``json`` / ``typing``):

* ``derive_requirement_id(selection_manifest_digest, row_identity_digest) -> str``
* ``derive_progress_id(requirement_id, claim_ack_digest) -> str``
* ``document_digest(document) -> str``
* ``verify_active_requirement(document) -> None``
* ``verify_progress(document) -> None``
* ``verify_checkpoint_receipt(document) -> None``
* ``verify_checkpoint_chain(receipts, *, active, progress) -> None``
* ``decide_resume(active_pointers, *, progress, receipts,
   expected_identities, exclusive_lock_acquired, prerequisites_status,
   observed_row_status) -> dict``
* ``plan_terminal_cleanup(active, progress, *, terminal_status,
   writeback_ack_digest, expected_writeback_ack_digest,
   sealed_evidence_digest) -> dict``
* ``verify_terminal_cleanup(cleanup_plan, *, active_present,
   progress_present, scratch_present, checkpoint_chain_digest_before,
   checkpoint_chain_digest_after, sealed_evidence_digest_after) -> dict``

Local error class: ``RequirementResumeError(ValueError)``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

KIND_ACTIVE_REQUIREMENT = "icp.active-requirement.v1"
KIND_PROGRESS = "icp.requirement-progress.v1"
KIND_CHECKPOINT_RECEIPT = "icp.checkpoint-receipt.v1"
KIND_RESUME_DECISION = "icp.requirement-resume-decision.v1"
KIND_CLEANUP_PLAN = "icp.requirement-cleanup-plan.v1"
KIND_CLEANUP_REPORT = "icp.requirement-cleanup-report.v1"
SCHEMA_VERSION = 1

GENESIS_RECEIPT_DIGEST = hashlib.sha256(
    b"icp.checkpoint-receipt.v1.genesis"
).hexdigest()

# Domain-separated derivation tags. Locked formulas; mirror the
# reference exactly.
_REQUIREMENT_ID_TAG = b"icp.requirement.v1\x00"
_PROGRESS_ID_TAG = b"icp.requirement-progress.v1\x00"

# Exact ordered top-level keys for the active-requirement document.
ACTIVE_REQUIREMENT_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "selection_manifest_digest",
    "row_identity_digest",
    "claim_intent_digest",
    "claim_ack_digest",
    "progress_id",
)

# Exact ordered top-level keys for the progress document.
PROGRESS_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "progress_id",
    "claim_ack_digest",
    "verified_operation_plan_digest",
    "revision",
    "phase",
    "latest_checkpoint_receipt_digest",
    "checkpoint_count",
    "feature_positions",
)

# Exact ordered keys for each feature position.
FEATURE_POSITION_KEY_ORDER = (
    "feature_id",
    "state",
    "inflight_step_id",
    "next_step_id",
    "replay_policy",
    "recovery_verifier_digest",
    "last_checkpoint_receipt_digest",
)

# Exact ordered top-level keys for a checkpoint receipt.
CHECKPOINT_RECEIPT_KEY_ORDER = (
    "kind",
    "schema_version",
    "receipt_id",
    "requirement_id",
    "progress_id",
    "claim_ack_digest",
    "sequence",
    "previous_receipt_digest",
    "feature_id",
    "step_id",
    "execution_mode",
    "input_artifact_digests",
    "output_artifact_digests",
    "producer_digest",
    "verifier_digest",
)

# Exact ordered keys for each artifact digest pair.
ARTIFACT_DIGEST_KEY_ORDER = ("id", "digest")

# Exact ordered top-level keys for the resume-decision report.
RESUME_DECISION_KEY_ORDER = (
    "kind",
    "schema_version",
    "decision",
    "reason_code",
    "requirement_id",
    "progress_id",
    "feature_id",
    "step_id",
    "checkpoint_receipt_digest",
)

# Exact ordered top-level keys for the cleanup plan.
CLEANUP_PLAN_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "terminal_status",
    "writeback_ack_digest",
    "sealed_evidence_digest",
    "actions",
    "next_requirement_allowed",
)

# Exact ordered top-level keys for the cleanup report.
CLEANUP_REPORT_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "terminal_status",
    "cleanup_verified",
    "checkpoint_evidence_retained",
    "sealed_evidence_retained",
    "next_requirement_allowed",
)

# Exact ordered keys for the ``expected_identities`` argument to
# ``decide_resume``.
EXPECTED_IDENTITIES_KEY_ORDER = (
    "requirement_id",
    "selection_manifest_digest",
    "row_identity_digest",
    "claim_intent_digest",
    "claim_ack_digest",
    "progress_id",
    "verified_operation_plan_digest",
)

# Controlled enums.
PROGRESS_PHASES = ("claimed", "running", "terminal-pending")
FEATURE_STATES = ("pending", "started", "checkpointed", "done", "failed")
REPLAY_POLICIES = ("none", "idempotent", "deterministic-recovery")
EXECUTION_MODES = (
    "first-run",
    "idempotent-replay",
    "deterministic-recovery",
)
TERMINAL_STATUSES = ("done", "error")
PREREQUISITES_STATUSES = ("met", "missing", "blocked")
OBSERVED_ROW_STATUSES = ("empty", "doing", "done", "error", "unknown")

RESUME_DECISIONS = (
    "new-selection-allowed",
    "resume-step",
    "replay-step",
    "run-recovery-verifier",
    "needs-user-input",
    "terminal-cleanup-required",
    "blocked",
)
RESUME_REASON_CODES = (
    "no-active-state",
    "active-present",
    "multiple-active-pointers",
    "lock-not-acquired",
    "prerequisites-missing",
    "prerequisites-blocked",
    "identity-mismatch",
    "progress-missing",
    "progress-tamper",
    "receipt-chain-tamper",
    "row-not-doing",
    "row-terminal",
    "started-without-replay",
    "resume-next-step",
    "replay-idempotent",
    "recovery-verifier-required",
    "terminal-pending",
)

# Fixed cleanup action IDs in the canonical order. P3d executes them in
# this order; the verifier requires the plan to carry exactly this
# ordered tuple.
CLEANUP_ACTIONS = (
    "remove-active-pointer",
    "remove-progress",
    "remove-scratch",
    "verify-cleanup",
)

# Identity/digest fields of each document. The verifier requires each to
# be a bare 64-char lowercase SHA-256 hex string.
_ACTIVE_REQUIREMENT_DIGEST_FIELDS = (
    "requirement_id",
    "selection_manifest_digest",
    "row_identity_digest",
    "claim_intent_digest",
    "claim_ack_digest",
    "progress_id",
)
_PROGRESS_DIGEST_FIELDS = (
    "requirement_id",
    "progress_id",
    "claim_ack_digest",
    "verified_operation_plan_digest",
)
_RECEIPT_DIGEST_FIELDS = (
    "receipt_id",
    "requirement_id",
    "progress_id",
    "claim_ack_digest",
    "previous_receipt_digest",
    "producer_digest",
    "verifier_digest",
)

# Forbidden injection field names anywhere in any document.
_INJECTION_FIELD_NAMES = frozenset(
    {
        "command", "argv", "shell", "interpreter", "env", "runner",
        "args", "program", "cmd", "subprocess", "exec", "run",
        "script_path", "script_runner", "activate",
        "activation_command", "activation_override", "prompt",
        "prompt_template", "path", "task_ref", "row_title",
        "design_url", "secret", "token", "password", "credential",
        "api_key",
    }
)


class RequirementResumeError(ValueError):
    """A local requirement-resume validation / decision failure.

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
    # The character set already excludes uppercase letters, so the
    # explicit ``all(c in ...)`` check subsumes the lowercase
    # requirement (and correctly accepts all-digit hex strings).
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_bool(value: Any) -> bool:
    return value is True or value is False


def _is_non_negative_int(value: Any) -> bool:
    """Non-negative int that is NOT a boolean."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


_SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-"
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
        raise RequirementResumeError(f"{location}: must be an object")
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise RequirementResumeError(
            f"{location}: key order mismatch: "
            f"extra={extra} missing={missing}"
        )


def _reject_injection_fields(obj: Any, location: str) -> None:
    """Recursively reject forbidden command/argv/env/shell/prompt/path/
    task_ref/secret/credential fields anywhere in the document."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key in _INJECTION_FIELD_NAMES:
                raise RequirementResumeError(
                    f"forbidden injection field: {here}"
                )
            _reject_injection_fields(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_injection_fields(item, f"{location}[{i}]")


# ---------------------------------------------------------------------------
# Public API: locked identity derivations.
# ---------------------------------------------------------------------------


def derive_requirement_id(
    selection_manifest_digest: str, row_identity_digest: str
) -> str:
    """Locked SHA-256 derivation of ``requirement_id`` from the
    selection-manifest digest and row-identity digest."""
    if not _is_sha256_hex(selection_manifest_digest):
        raise RequirementResumeError(
            "selection_manifest_digest: must be SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(row_identity_digest):
        raise RequirementResumeError(
            "row_identity_digest: must be SHA-256 hex (64 lowercase)"
        )
    h = hashlib.sha256()
    h.update(_REQUIREMENT_ID_TAG)
    h.update(bytes.fromhex(selection_manifest_digest))
    h.update(bytes.fromhex(row_identity_digest))
    return h.hexdigest()


def derive_progress_id(
    requirement_id: str, claim_ack_digest: str
) -> str:
    """Locked SHA-256 derivation of ``progress_id`` from the
    requirement id and claim-ack digest."""
    if not _is_sha256_hex(requirement_id):
        raise RequirementResumeError(
            "requirement_id: must be SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(claim_ack_digest):
        raise RequirementResumeError(
            "claim_ack_digest: must be SHA-256 hex (64 lowercase)"
        )
    h = hashlib.sha256()
    h.update(_PROGRESS_ID_TAG)
    h.update(bytes.fromhex(requirement_id))
    h.update(bytes.fromhex(claim_ack_digest))
    return h.hexdigest()


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
        raise RequirementResumeError("document: must be an object")
    return _sha256_bytes(_canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Public API: active-requirement verifier.
# ---------------------------------------------------------------------------


def verify_active_requirement(document: dict) -> None:
    """Strict fail-closed validation of ``icp.active-requirement.v1``.

    Enforces the exact ordered key shape, kind/schema_version, bare
    64-char lowercase SHA-256 hex on every identity/digest field, and
    the locked derivation of ``requirement_id`` and ``progress_id``.
    The active pointer is immutable: no progress-document digest,
    lifecycle flag, path, or task content may be carried.
    """
    if not isinstance(document, dict):
        raise RequirementResumeError("active_requirement: must be an object")
    _check_keys_exact_order(
        document, ACTIVE_REQUIREMENT_KEY_ORDER, "active_requirement"
    )
    if document["kind"] != KIND_ACTIVE_REQUIREMENT:
        raise RequirementResumeError(
            f"active_requirement.kind: must be "
            f"{KIND_ACTIVE_REQUIREMENT!r}, got {document['kind']!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"active_requirement.schema_version: must be "
            f"{SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    for key in _ACTIVE_REQUIREMENT_DIGEST_FIELDS:
        if not _is_sha256_hex(document[key]):
            raise RequirementResumeError(
                f"active_requirement.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )
    expected_req = derive_requirement_id(
        document["selection_manifest_digest"],
        document["row_identity_digest"],
    )
    if document["requirement_id"] != expected_req:
        raise RequirementResumeError(
            "active_requirement.requirement_id: does not match the "
            "locked derivation from selection_manifest_digest + "
            "row_identity_digest"
        )
    expected_progress = derive_progress_id(
        document["requirement_id"], document["claim_ack_digest"]
    )
    if document["progress_id"] != expected_progress:
        raise RequirementResumeError(
            "active_requirement.progress_id: does not match the "
            "locked derivation from requirement_id + claim_ack_digest"
        )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: progress verifier.
# ---------------------------------------------------------------------------


def _verify_feature_position(fp: Any, location: str) -> None:
    _check_keys_exact_order(fp, FEATURE_POSITION_KEY_ORDER, location)
    fid = fp["feature_id"]
    if not _is_safe_id(fid):
        raise RequirementResumeError(
            f"{location}.feature_id: not a controlled safe ID"
        )
    if fp["state"] not in FEATURE_STATES:
        raise RequirementResumeError(
            f"{location}.state: not controlled: {fp['state']!r}"
        )
    inflight = fp["inflight_step_id"]
    if fp["state"] == "started":
        if not _is_safe_id(inflight):
            raise RequirementResumeError(
                f"{location}.inflight_step_id: started requires a "
                f"controlled safe ID"
            )
    else:
        if inflight is not None and not _is_safe_id(inflight):
            raise RequirementResumeError(
                f"{location}.inflight_step_id: must be null or a "
                f"controlled safe ID"
            )
    next_step = fp["next_step_id"]
    if next_step is not None and not _is_safe_id(next_step):
        raise RequirementResumeError(
            f"{location}.next_step_id: must be null or a controlled "
            f"safe ID"
        )
    if fp["replay_policy"] not in REPLAY_POLICIES:
        raise RequirementResumeError(
            f"{location}.replay_policy: not controlled: "
            f"{fp['replay_policy']!r}"
        )
    rvd = fp["recovery_verifier_digest"]
    if fp["replay_policy"] == "deterministic-recovery":
        if not _is_sha256_hex(rvd):
            raise RequirementResumeError(
                f"{location}.recovery_verifier_digest: "
                f"deterministic-recovery requires SHA-256 hex"
            )
    else:
        if rvd is not None:
            raise RequirementResumeError(
                f"{location}.recovery_verifier_digest: must be null "
                f"for non-deterministic-recovery replay policy"
            )
    lcrid = fp["last_checkpoint_receipt_digest"]
    if lcrid is not None and not _is_sha256_hex(lcrid):
        raise RequirementResumeError(
            f"{location}.last_checkpoint_receipt_digest: must be "
            f"null or SHA-256 hex"
        )


def verify_progress(document: dict) -> None:
    """Strict fail-closed validation of ``icp.requirement-progress.v1``."""
    if not isinstance(document, dict):
        raise RequirementResumeError("progress: must be an object")
    _check_keys_exact_order(document, PROGRESS_KEY_ORDER, "progress")
    if document["kind"] != KIND_PROGRESS:
        raise RequirementResumeError(
            f"progress.kind: must be {KIND_PROGRESS!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"progress.schema_version: must be {SCHEMA_VERSION!r}, "
            f"got {document['schema_version']!r}"
        )
    for key in _PROGRESS_DIGEST_FIELDS:
        if not _is_sha256_hex(document[key]):
            raise RequirementResumeError(
                f"progress.{key}: must be SHA-256 hex (64 lowercase)"
            )
    if not _is_non_negative_int(document["revision"]):
        raise RequirementResumeError(
            "progress.revision: must be a non-negative integer "
            "(booleans rejected)"
        )
    if not _is_non_negative_int(document["checkpoint_count"]):
        raise RequirementResumeError(
            "progress.checkpoint_count: must be a non-negative integer "
            "(booleans rejected)"
        )
    if document["phase"] not in PROGRESS_PHASES:
        raise RequirementResumeError(
            f"progress.phase: not controlled: {document['phase']!r}"
        )
    latest = document["latest_checkpoint_receipt_digest"]
    if document["checkpoint_count"] == 0:
        if latest is not None:
            raise RequirementResumeError(
                "progress.latest_checkpoint_receipt_digest: must be "
                "null when checkpoint_count=0"
            )
    else:
        if not _is_sha256_hex(latest):
            raise RequirementResumeError(
                "progress.latest_checkpoint_receipt_digest: must be "
                "SHA-256 hex (64 lowercase) when checkpoint_count>0"
            )
    fps = document["feature_positions"]
    if not isinstance(fps, list) or not fps:
        raise RequirementResumeError(
            "progress.feature_positions: must be a non-empty list"
        )
    last_id: str | None = None
    seen_ids: set = set()
    for i, fp in enumerate(fps):
        here = f"progress.feature_positions[{i}]"
        _verify_feature_position(fp, here)
        fid = fp["feature_id"]
        if fid in seen_ids:
            raise RequirementResumeError(
                f"{here}.feature_id: duplicate: {fid!r}"
            )
        if last_id is not None and fid <= last_id:
            raise RequirementResumeError(
                f"{here}.feature_id: not strictly sorted by feature_id"
            )
        seen_ids.add(fid)
        last_id = fid
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: checkpoint-receipt verifier.
# ---------------------------------------------------------------------------


def _verify_artifact_digests(value: Any, location: str) -> None:
    if not isinstance(value, list):
        raise RequirementResumeError(f"{location}: must be a list")
    last_id: str | None = None
    seen_ids: set = set()
    for i, ad in enumerate(value):
        here = f"{location}[{i}]"
        _check_keys_exact_order(ad, ARTIFACT_DIGEST_KEY_ORDER, here)
        aid = ad["id"]
        if not _is_safe_id(aid):
            raise RequirementResumeError(
                f"{here}.id: not a controlled safe ID"
            )
        if aid in seen_ids:
            raise RequirementResumeError(f"{here}.id: duplicate: {aid!r}")
        if last_id is not None and aid <= last_id:
            raise RequirementResumeError(
                f"{here}.id: not strictly sorted by id"
            )
        seen_ids.add(aid)
        last_id = aid
        if not _is_sha256_hex(ad["digest"]):
            raise RequirementResumeError(
                f"{here}.digest: must be SHA-256 hex (64 lowercase)"
            )


def verify_checkpoint_receipt(document: dict) -> None:
    """Strict fail-closed validation of ``icp.checkpoint-receipt.v1``."""
    if not isinstance(document, dict):
        raise RequirementResumeError(
            "checkpoint_receipt: must be an object"
        )
    _check_keys_exact_order(
        document, CHECKPOINT_RECEIPT_KEY_ORDER, "checkpoint_receipt"
    )
    if document["kind"] != KIND_CHECKPOINT_RECEIPT:
        raise RequirementResumeError(
            f"checkpoint_receipt.kind: must be "
            f"{KIND_CHECKPOINT_RECEIPT!r}, got {document['kind']!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"checkpoint_receipt.schema_version: must be "
            f"{SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    for key in _RECEIPT_DIGEST_FIELDS:
        if not _is_sha256_hex(document[key]):
            raise RequirementResumeError(
                f"checkpoint_receipt.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )
    if not _is_non_negative_int(document["sequence"]):
        raise RequirementResumeError(
            "checkpoint_receipt.sequence: must be a non-negative "
            "integer (booleans rejected)"
        )
    feature_id = document["feature_id"]
    if feature_id is not None and not _is_safe_id(feature_id):
        raise RequirementResumeError(
            "checkpoint_receipt.feature_id: must be null or a "
            "controlled safe ID"
        )
    if not _is_safe_id(document["step_id"]):
        raise RequirementResumeError(
            "checkpoint_receipt.step_id: must be a controlled safe ID"
        )
    if document["execution_mode"] not in EXECUTION_MODES:
        raise RequirementResumeError(
            f"checkpoint_receipt.execution_mode: not controlled: "
            f"{document['execution_mode']!r}"
        )
    _verify_artifact_digests(
        document["input_artifact_digests"],
        "checkpoint_receipt.input_artifact_digests",
    )
    _verify_artifact_digests(
        document["output_artifact_digests"],
        "checkpoint_receipt.output_artifact_digests",
    )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: checkpoint-chain verifier.
# ---------------------------------------------------------------------------


def verify_checkpoint_chain(
    receipts: list[dict], *, active: dict, progress: dict
) -> None:
    """Strict fail-closed validation of an ordered checkpoint chain.

    Requires that ``active`` and ``progress`` each pass their verifier,
    that their identities agree, that the chain length matches
    ``progress.checkpoint_count``, that every receipt passes its
    verifier and binds to the same identities, that ``receipt_id``
    values are unique, that ``sequence`` starts at 0 and is contiguous
    in input order (rejecting reorder / gap / duplicate), that the
    ``previous_receipt_digest`` chain is rooted at
    :data:`GENESIS_RECEIPT_DIGEST` and links via
    :func:`document_digest`, and that
    ``progress.latest_checkpoint_receipt_digest`` matches
    :func:`document_digest` of the last receipt (or null when empty).
    """
    if not isinstance(receipts, list):
        raise RequirementResumeError("receipts: must be a list")
    verify_active_requirement(active)
    verify_progress(progress)

    # Cross-document identity agreement.
    if active["requirement_id"] != progress["requirement_id"]:
        raise RequirementResumeError(
            "active/progress identity mismatch: requirement_id"
        )
    if active["progress_id"] != progress["progress_id"]:
        raise RequirementResumeError(
            "active/progress identity mismatch: progress_id"
        )
    if active["claim_ack_digest"] != progress["claim_ack_digest"]:
        raise RequirementResumeError(
            "active/progress identity mismatch: claim_ack_digest"
        )

    # Count consistency.
    if progress["checkpoint_count"] != len(receipts):
        raise RequirementResumeError(
            f"progress.checkpoint_count={progress['checkpoint_count']} "
            f"does not match receipts length={len(receipts)}"
        )

    # Per-receipt validation + identity binding + unique receipt_id.
    seen_receipt_ids: set = set()
    for i, r in enumerate(receipts):
        verify_checkpoint_receipt(r)
        for field, active_field in (
            ("requirement_id", "requirement_id"),
            ("progress_id", "progress_id"),
            ("claim_ack_digest", "claim_ack_digest"),
        ):
            if r[field] != active[active_field]:
                raise RequirementResumeError(
                    f"receipts[{i}].{field} does not match active"
                )
        rid = r["receipt_id"]
        if rid in seen_receipt_ids:
            raise RequirementResumeError(
                f"receipts[{i}].receipt_id: duplicate: {rid!r}"
            )
        seen_receipt_ids.add(rid)

    # Sequence + chain integrity.
    for i, r in enumerate(receipts):
        if r["sequence"] != i:
            raise RequirementResumeError(
                f"receipts[{i}].sequence: expected {i}, "
                f"got {r['sequence']} (reorder or gap)"
            )
        if i == 0:
            if r["previous_receipt_digest"] != GENESIS_RECEIPT_DIGEST:
                raise RequirementResumeError(
                    "receipts[0].previous_receipt_digest must equal "
                    "GENESIS_RECEIPT_DIGEST"
                )
        else:
            expected = document_digest(receipts[i - 1])
            if r["previous_receipt_digest"] != expected:
                raise RequirementResumeError(
                    f"receipts[{i}].previous_receipt_digest: chain "
                    f"tamper (does not equal digest of previous "
                    f"receipt)"
                )

    # Latest checkpoint receipt digest consistency.
    latest = progress["latest_checkpoint_receipt_digest"]
    if not receipts:
        if latest is not None:
            raise RequirementResumeError(
                "progress.latest_checkpoint_receipt_digest: must be "
                "null when receipts is empty"
            )
    else:
        expected_latest = document_digest(receipts[-1])
        if latest != expected_latest:
            raise RequirementResumeError(
                "progress.latest_checkpoint_receipt_digest: must "
                "equal document_digest(receipts[-1])"
            )


# ---------------------------------------------------------------------------
# Internal: resume-decision verifier (defense in depth on return).
# ---------------------------------------------------------------------------


def _verify_resume_decision(document: dict) -> None:
    if not isinstance(document, dict):
        raise RequirementResumeError(
            "resume_decision: must be an object"
        )
    _check_keys_exact_order(
        document, RESUME_DECISION_KEY_ORDER, "resume_decision"
    )
    if document["kind"] != KIND_RESUME_DECISION:
        raise RequirementResumeError(
            f"resume_decision.kind: must be {KIND_RESUME_DECISION!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"resume_decision.schema_version: must be "
            f"{SCHEMA_VERSION!r}"
        )
    if document["decision"] not in RESUME_DECISIONS:
        raise RequirementResumeError(
            f"resume_decision.decision: not controlled: "
            f"{document['decision']!r}"
        )
    if document["reason_code"] not in RESUME_REASON_CODES:
        raise RequirementResumeError(
            f"resume_decision.reason_code: not controlled: "
            f"{document['reason_code']!r}"
        )
    for key in ("requirement_id", "progress_id", "checkpoint_receipt_digest"):
        v = document[key]
        if v is not None and not _is_sha256_hex(v):
            raise RequirementResumeError(
                f"resume_decision.{key}: must be null or SHA-256 hex"
            )
    for key in ("feature_id", "step_id"):
        v = document[key]
        if v is not None and not _is_safe_id(v):
            raise RequirementResumeError(
                f"resume_decision.{key}: must be null or a controlled "
                f"safe ID"
            )
    _reject_injection_fields(document, "")


def _verify_expected_identities(value: dict) -> None:
    if not isinstance(value, dict):
        raise RequirementResumeError(
            "expected_identities: must be an object"
        )
    _check_keys_exact_order(
        value, EXPECTED_IDENTITIES_KEY_ORDER, "expected_identities"
    )
    for key in EXPECTED_IDENTITIES_KEY_ORDER:
        if not _is_sha256_hex(value[key]):
            raise RequirementResumeError(
                f"expected_identities.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )


def _build_resume_decision(
    *,
    decision: str,
    reason: str,
    requirement_id: str | None = None,
    progress_id: str | None = None,
    feature_id: str | None = None,
    step_id: str | None = None,
    checkpoint_receipt_digest: str | None = None,
) -> dict:
    report = {
        "kind": KIND_RESUME_DECISION,
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "reason_code": reason,
        "requirement_id": requirement_id,
        "progress_id": progress_id,
        "feature_id": feature_id,
        "step_id": step_id,
        "checkpoint_receipt_digest": checkpoint_receipt_digest,
    }
    _verify_resume_decision(report)
    return report


# ---------------------------------------------------------------------------
# Public API: resume decision state machine.
# ---------------------------------------------------------------------------


def decide_resume(
    active_pointers: list[dict],
    *,
    progress: dict | None,
    receipts: list[dict],
    expected_identities: dict,
    exclusive_lock_acquired: bool,
    prerequisites_status: str,
    observed_row_status: str,
) -> dict:
    """Pure resume decision state machine.

    See the reference (``icp/references/requirement-resume-v1.md``
    section 6.2) for the full ordering and rationale. This function
    never inspects a filesystem or acquires a lock; it consumes the
    verified P3d input ``exclusive_lock_acquired`` and chooses a
    controlled decision. Every returned report passes the internal
    verifier before return.
    """
    if not isinstance(active_pointers, list):
        raise RequirementResumeError(
            "active_pointers: must be a list"
        )
    if receipts is not None and not isinstance(receipts, list):
        raise RequirementResumeError("receipts: must be a list")
    if not _is_bool(exclusive_lock_acquired):
        raise RequirementResumeError(
            "exclusive_lock_acquired: must be a bool"
        )
    if prerequisites_status not in PREREQUISITES_STATUSES:
        raise RequirementResumeError(
            f"prerequisites_status: not controlled: "
            f"{prerequisites_status!r}"
        )
    if observed_row_status not in OBSERVED_ROW_STATUSES:
        raise RequirementResumeError(
            f"observed_row_status: not controlled: "
            f"{observed_row_status!r}"
        )
    _verify_expected_identities(expected_identities)

    n = len(active_pointers)

    # Step 1: zero active pointers.
    if n == 0:
        if progress is not None or receipts:
            return _build_resume_decision(
                decision="blocked", reason="no-active-state"
            )
        return _build_resume_decision(
            decision="new-selection-allowed", reason="no-active-state"
        )

    # Step 2: multiple active pointers.
    if n > 1:
        return _build_resume_decision(
            decision="blocked", reason="multiple-active-pointers"
        )

    # Exactly one active pointer.
    active = active_pointers[0]

    # Step 3: lock not acquired.
    if not exclusive_lock_acquired:
        return _build_resume_decision(
            decision="blocked", reason="lock-not-acquired"
        )

    # Step 4: active shape + identity match against expected_identities.
    try:
        verify_active_requirement(active)
    except RequirementResumeError:
        return _build_resume_decision(
            decision="blocked", reason="progress-tamper"
        )

    active_identities_match = (
        active["requirement_id"] == expected_identities["requirement_id"]
        and active["selection_manifest_digest"]
        == expected_identities["selection_manifest_digest"]
        and active["row_identity_digest"]
        == expected_identities["row_identity_digest"]
        and active["claim_intent_digest"]
        == expected_identities["claim_intent_digest"]
        and active["claim_ack_digest"]
        == expected_identities["claim_ack_digest"]
        and active["progress_id"] == expected_identities["progress_id"]
    )
    if not active_identities_match:
        return _build_resume_decision(
            decision="blocked",
            reason="identity-mismatch",
            requirement_id=active["requirement_id"],
            progress_id=active["progress_id"],
        )

    req_id = active["requirement_id"]
    prog_id = active["progress_id"]

    # Step 5: row terminal requires cleanup; row not doing blocks.
    if observed_row_status in ("done", "error"):
        return _build_resume_decision(
            decision="terminal-cleanup-required",
            reason="row-terminal",
            requirement_id=req_id,
            progress_id=prog_id,
        )
    if observed_row_status != "doing":
        return _build_resume_decision(
            decision="blocked",
            reason="row-not-doing",
            requirement_id=req_id,
            progress_id=prog_id,
        )

    # Step 6: prerequisites.
    if prerequisites_status == "missing":
        return _build_resume_decision(
            decision="needs-user-input",
            reason="prerequisites-missing",
            requirement_id=req_id,
            progress_id=prog_id,
        )
    if prerequisites_status == "blocked":
        return _build_resume_decision(
            decision="blocked",
            reason="prerequisites-blocked",
            requirement_id=req_id,
            progress_id=prog_id,
        )

    # Step 7: progress required.
    if progress is None:
        return _build_resume_decision(
            decision="blocked",
            reason="progress-missing",
            requirement_id=req_id,
        )

    # Step 8: progress shape + identity binding.
    try:
        verify_progress(progress)
    except RequirementResumeError:
        return _build_resume_decision(
            decision="blocked",
            reason="progress-tamper",
            requirement_id=req_id,
        )

    progress_identities_match = (
        progress["requirement_id"] == req_id
        and progress["progress_id"] == prog_id
        and progress["claim_ack_digest"] == active["claim_ack_digest"]
        and progress["verified_operation_plan_digest"]
        == expected_identities["verified_operation_plan_digest"]
    )
    if not progress_identities_match:
        return _build_resume_decision(
            decision="blocked",
            reason="identity-mismatch",
            requirement_id=req_id,
            progress_id=prog_id,
        )

    # Step 9: receipt chain.
    try:
        verify_checkpoint_chain(receipts, active=active, progress=progress)
    except RequirementResumeError:
        return _build_resume_decision(
            decision="blocked",
            reason="receipt-chain-tamper",
            requirement_id=req_id,
            progress_id=prog_id,
        )

    # Step 10: terminal-pending phase.
    if progress["phase"] == "terminal-pending":
        return _build_resume_decision(
            decision="terminal-cleanup-required",
            reason="terminal-pending",
            requirement_id=req_id,
            progress_id=prog_id,
        )

    # Step 11: choose the next step from the first non-done feature.
    for fp in progress["feature_positions"]:
        state = fp["state"]
        if state == "done":
            continue
        if state == "started":
            replay = fp["replay_policy"]
            step_id = fp["inflight_step_id"]
            if replay == "none":
                return _build_resume_decision(
                    decision="blocked",
                    reason="started-without-replay",
                    requirement_id=req_id,
                    progress_id=prog_id,
                    feature_id=fp["feature_id"],
                    step_id=step_id,
                )
            if replay == "idempotent":
                return _build_resume_decision(
                    decision="replay-step",
                    reason="replay-idempotent",
                    requirement_id=req_id,
                    progress_id=prog_id,
                    feature_id=fp["feature_id"],
                    step_id=step_id,
                )
            # deterministic-recovery
            return _build_resume_decision(
                decision="run-recovery-verifier",
                reason="recovery-verifier-required",
                requirement_id=req_id,
                progress_id=prog_id,
                feature_id=fp["feature_id"],
                step_id=step_id,
            )
        if state == "failed":
            return _build_resume_decision(
                decision="blocked",
                reason="active-present",
                requirement_id=req_id,
                progress_id=prog_id,
                feature_id=fp["feature_id"],
            )
        # pending or checkpointed: resume from the exact next_step_id.
        next_step = fp["next_step_id"]
        if not _is_safe_id(next_step):
            return _build_resume_decision(
                decision="blocked",
                reason="active-present",
                requirement_id=req_id,
                progress_id=prog_id,
                feature_id=fp["feature_id"],
            )
        cprd = (
            fp["last_checkpoint_receipt_digest"]
            if state == "checkpointed"
            else None
        )
        return _build_resume_decision(
            decision="resume-step",
            reason="resume-next-step",
            requirement_id=req_id,
            progress_id=prog_id,
            feature_id=fp["feature_id"],
            step_id=next_step,
            checkpoint_receipt_digest=cprd,
        )

    # All features done but phase is not terminal-pending: inconsistent
    # active state, no authorized next action.
    return _build_resume_decision(
        decision="blocked",
        reason="active-present",
        requirement_id=req_id,
        progress_id=prog_id,
    )


# ---------------------------------------------------------------------------
# Internal: cleanup-plan and cleanup-report verifiers.
# ---------------------------------------------------------------------------


def _verify_cleanup_plan(plan: dict) -> None:
    if not isinstance(plan, dict):
        raise RequirementResumeError("cleanup_plan: must be an object")
    _check_keys_exact_order(plan, CLEANUP_PLAN_KEY_ORDER, "cleanup_plan")
    if plan["kind"] != KIND_CLEANUP_PLAN:
        raise RequirementResumeError(
            f"cleanup_plan.kind: must be {KIND_CLEANUP_PLAN!r}"
        )
    if plan["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"cleanup_plan.schema_version: must be {SCHEMA_VERSION!r}"
        )
    for key in (
        "requirement_id",
        "writeback_ack_digest",
        "sealed_evidence_digest",
    ):
        if not _is_sha256_hex(plan[key]):
            raise RequirementResumeError(
                f"cleanup_plan.{key}: must be SHA-256 hex (64 lowercase)"
            )
    if plan["terminal_status"] not in TERMINAL_STATUSES:
        raise RequirementResumeError(
            f"cleanup_plan.terminal_status: not controlled: "
            f"{plan['terminal_status']!r}"
        )
    if not isinstance(plan["actions"], list):
        raise RequirementResumeError(
            "cleanup_plan.actions: must be a list"
        )
    if tuple(plan["actions"]) != CLEANUP_ACTIONS:
        raise RequirementResumeError(
            "cleanup_plan.actions: must equal the fixed ordered tuple "
            f"{CLEANUP_ACTIONS!r}"
        )
    if plan["next_requirement_allowed"] is not False:
        raise RequirementResumeError(
            "cleanup_plan.next_requirement_allowed: must be exactly False"
        )
    _reject_injection_fields(plan, "")


def _verify_cleanup_report(report: dict) -> None:
    if not isinstance(report, dict):
        raise RequirementResumeError(
            "cleanup_report: must be an object"
        )
    _check_keys_exact_order(
        report, CLEANUP_REPORT_KEY_ORDER, "cleanup_report"
    )
    if report["kind"] != KIND_CLEANUP_REPORT:
        raise RequirementResumeError(
            f"cleanup_report.kind: must be {KIND_CLEANUP_REPORT!r}"
        )
    if report["schema_version"] != SCHEMA_VERSION:
        raise RequirementResumeError(
            f"cleanup_report.schema_version: must be {SCHEMA_VERSION!r}"
        )
    if not _is_sha256_hex(report["requirement_id"]):
        raise RequirementResumeError(
            "cleanup_report.requirement_id: must be SHA-256 hex"
        )
    if report["terminal_status"] not in TERMINAL_STATUSES:
        raise RequirementResumeError(
            f"cleanup_report.terminal_status: not controlled: "
            f"{report['terminal_status']!r}"
        )
    for key in (
        "cleanup_verified",
        "checkpoint_evidence_retained",
        "sealed_evidence_retained",
        "next_requirement_allowed",
    ):
        if report[key] is not True:
            raise RequirementResumeError(
                f"cleanup_report.{key}: must be exactly True"
            )
    _reject_injection_fields(report, "")


# ---------------------------------------------------------------------------
# Public API: terminal-cleanup planning and verification.
# ---------------------------------------------------------------------------


def plan_terminal_cleanup(
    active: dict,
    progress: dict,
    *,
    terminal_status: str,
    writeback_ack_digest: str,
    expected_writeback_ack_digest: str,
    sealed_evidence_digest: str | None,
) -> dict:
    """Build the immutable ``icp.requirement-cleanup-plan.v1``.

    Fails closed unless:

    * ``active`` and ``progress`` each pass their verifier and share
      ``requirement_id``;
    * ``progress.phase`` is ``terminal-pending``;
    * ``terminal_status`` is ``done`` or ``error``;
    * ``writeback_ack_digest`` is bare SHA-256 hex and equals
      ``expected_writeback_ack_digest``;
    * ``sealed_evidence_digest`` is bare SHA-256 hex (not null).

    The returned plan always carries the fixed action order and
    ``next_requirement_allowed = false``. This function performs no
    unlink or deletion.
    """
    verify_active_requirement(active)
    verify_progress(progress)
    if active["requirement_id"] != progress["requirement_id"]:
        raise RequirementResumeError(
            "plan_terminal_cleanup: active/progress requirement_id "
            "mismatch"
        )
    if progress["phase"] != "terminal-pending":
        raise RequirementResumeError(
            "plan_terminal_cleanup: progress.phase must be "
            "'terminal-pending'"
        )
    if terminal_status not in TERMINAL_STATUSES:
        raise RequirementResumeError(
            f"plan_terminal_cleanup.terminal_status: not controlled: "
            f"{terminal_status!r}"
        )
    if not _is_sha256_hex(writeback_ack_digest):
        raise RequirementResumeError(
            "plan_terminal_cleanup.writeback_ack_digest: must be "
            "SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(expected_writeback_ack_digest):
        raise RequirementResumeError(
            "plan_terminal_cleanup.expected_writeback_ack_digest: "
            "must be SHA-256 hex (64 lowercase)"
        )
    if writeback_ack_digest != expected_writeback_ack_digest:
        raise RequirementResumeError(
            "plan_terminal_cleanup: writeback_ack_digest does not "
            "match the trusted expected_writeback_ack_digest"
        )
    if sealed_evidence_digest is None:
        raise RequirementResumeError(
            "plan_terminal_cleanup.sealed_evidence_digest: must "
            "exist (not null)"
        )
    if not _is_sha256_hex(sealed_evidence_digest):
        raise RequirementResumeError(
            "plan_terminal_cleanup.sealed_evidence_digest: must be "
            "SHA-256 hex (64 lowercase)"
        )
    plan = {
        "kind": KIND_CLEANUP_PLAN,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": active["requirement_id"],
        "terminal_status": terminal_status,
        "writeback_ack_digest": writeback_ack_digest,
        "sealed_evidence_digest": sealed_evidence_digest,
        "actions": list(CLEANUP_ACTIONS),
        "next_requirement_allowed": False,
    }
    _verify_cleanup_plan(plan)
    return plan


def verify_terminal_cleanup(
    cleanup_plan: dict,
    *,
    active_present: bool,
    progress_present: bool,
    scratch_present: bool,
    checkpoint_chain_digest_before: str,
    checkpoint_chain_digest_after: str,
    sealed_evidence_digest_after: str | None,
) -> dict:
    """Verify P3d's observed cleanup outcome against the plan.

    Returns the immutable ``icp.requirement-cleanup-report.v1`` with
    every boolean true and ``next_requirement_allowed = true`` only
    when ``active``, ``progress``, and scratch are all absent, the
    checkpoint-chain digest is unchanged (immutable audit trail), and
    the sealed evidence digest after cleanup equals the plan's
    ``sealed_evidence_digest``. Otherwise raises
    :class:`RequirementResumeError`; never claims next-requirement.
    Performs no unlink or deletion itself.
    """
    _verify_cleanup_plan(cleanup_plan)
    if not _is_bool(active_present):
        raise RequirementResumeError(
            "active_present: must be a bool"
        )
    if not _is_bool(progress_present):
        raise RequirementResumeError(
            "progress_present: must be a bool"
        )
    if not _is_bool(scratch_present):
        raise RequirementResumeError(
            "scratch_present: must be a bool"
        )
    if not _is_sha256_hex(checkpoint_chain_digest_before):
        raise RequirementResumeError(
            "checkpoint_chain_digest_before: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if not _is_sha256_hex(checkpoint_chain_digest_after):
        raise RequirementResumeError(
            "checkpoint_chain_digest_after: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if active_present or progress_present or scratch_present:
        raise RequirementResumeError(
            "cleanup incomplete: active/progress/scratch still present"
        )
    if checkpoint_chain_digest_before != checkpoint_chain_digest_after:
        raise RequirementResumeError(
            "cleanup failed: checkpoint-chain digest drifted "
            "(audit trail must be immutable)"
        )
    if sealed_evidence_digest_after != cleanup_plan["sealed_evidence_digest"]:
        raise RequirementResumeError(
            "cleanup failed: sealed_evidence_digest_after does not "
            "match the plan's sealed_evidence_digest"
        )
    report = {
        "kind": KIND_CLEANUP_REPORT,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": cleanup_plan["requirement_id"],
        "terminal_status": cleanup_plan["terminal_status"],
        "cleanup_verified": True,
        "checkpoint_evidence_retained": True,
        "sealed_evidence_retained": True,
        "next_requirement_allowed": True,
    }
    _verify_cleanup_report(report)
    return report
