#!/usr/bin/env python3
"""ICP P3a2 requirement claim-intent pure contract v1.

Freezes the canonical schema and pure decision state machine for the
claim crash-window recovery window:

* ``icp.requirement-claim-intent.v1`` -- the immutable document
  published before a TaskSource CAS to close the pre-claim crash
  window. The active pointer is created only AFTER a claim ack is
  verified/reconstructed; the immutable claim-intent document is what
  represents the pre-claim crash window.
* ``icp.claim-recovery-report.v1`` -- the controlled decision report
  returned by the pure ``decide_claim_recovery`` state machine. No
  report embeds the full claim ack or any task path; P3d's
  TaskSource-specific recovery API reconstructs and persists the ack
  when this report says ``reconstruct-claim-ack``.

P3a2 is TaskSource-neutral. This module performs zero filesystem I/O,
locking, CAS, subprocess, network, write, or unlink/cleanup. It does
not import a CSV parser, ``csv_task_source``, ``csv_row_status_v1``,
``prepare_selection``, platform modules, production publishers, or
``iff``.

Public API (no CLI, no import-time I/O, only stdlib ``hashlib``/``json``/
``typing``):

* ``document_digest(document) -> str``
* ``verify_claim_intent(document) -> None``
* ``verify_claim_recovery_report(document) -> None``
* ``decide_claim_recovery(intent, *, expected_requirement_id,
   expected_selection_manifest_digest, expected_row_identity_digest,
   observed_status, observed_source_sha256) -> dict``

Local error class: ``ClaimIntentError(ValueError)``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

KIND_CLAIM_INTENT = "icp.requirement-claim-intent.v1"
KIND_CLAIM_RECOVERY_REPORT = "icp.claim-recovery-report.v1"
SCHEMA_VERSION = 1

# Fixed value of ``expected_status_before``. The crash-window recovery
# contract only supports the empty->doing CAS transition.
EXPECTED_STATUS_BEFORE = "empty"

# Controlled ``observed_status`` enum.
OBSERVED_STATUSES = ("empty", "doing", "done", "error", "unknown")

# Controlled decision enum for the recovery report.
RECOVERY_DECISIONS = (
    "retry-cas",
    "reconstruct-claim-ack",
    "blocked",
)

# Controlled ``reason_code`` enum for the recovery report.
RECOVERY_REASONS = (
    "row-empty-before-sha-match",
    "row-doing-after-sha-match",
    "intent-identity-mismatch",
    "source-sha-mismatch",
    "unexpected-row-status",
)

# Exact ordered top-level keys for the claim-intent document.
CLAIM_INTENT_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "selection_manifest_digest",
    "row_identity_digest",
    "task_source_snapshot_digest",
    "candidate_identity_digest",
    "expected_status_before",
    "source_sha256_before",
    "expected_source_sha256_after",
)

# Exact ordered top-level keys for the recovery report.
CLAIM_RECOVERY_REPORT_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "intent_digest",
    "decision",
    "reason_code",
    "observed_status",
    "observed_source_sha256",
)

# Identity/digest fields of the claim-intent document. The verifier
# requires each to be a bare 64-char lowercase SHA-256 hex string. The
# claim-intent document does not derive ``requirement_id``; the locked
# derivation is enforced by ``icp.active-requirement.v1`` after a claim
# ack is verified or reconstructed.
_CLAIM_INTENT_DIGEST_FIELDS = (
    "requirement_id",
    "selection_manifest_digest",
    "row_identity_digest",
    "task_source_snapshot_digest",
    "candidate_identity_digest",
    "source_sha256_before",
    "expected_source_sha256_after",
)

# Forbidden injection field names anywhere in any document. These would
# re-introduce an executable / injection surface, leak source contents,
# or carry secrets.
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


class ClaimIntentError(ValueError):
    """A local claim-intent / recovery-report validation failure.

    Raised for any shape, type, enum, ordering, duplicate, unknown-key,
    injection, identity-mismatch, or content violation. The
    ``decide_claim_recovery`` state machine also raises this for
    invalid inputs (it never produces an actionable report from a
    malformed input).
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


def _check_keys_exact_order(
    actual: Any, expected_order: tuple, location: str
) -> None:
    if not isinstance(actual, dict):
        raise ClaimIntentError(f"{location}: must be an object")
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise ClaimIntentError(
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
                raise ClaimIntentError(
                    f"forbidden injection field: {here}"
                )
            _reject_injection_fields(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_injection_fields(item, f"{location}[{i}]")


# ---------------------------------------------------------------------------
# Public API: document digest.
# ---------------------------------------------------------------------------


def document_digest(document: dict) -> str:
    """Canonical SHA-256 of a document.

    Canonical bytes are::

        (json.dumps(document, ensure_ascii=False, indent=2,
                    sort_keys=True) + "\\n").encode("utf-8")

    Documents carry no self-referential digest field. This function
    does not validate the document; callers must run the appropriate
    ``verify_*`` first when the document is untrusted.
    """
    if not isinstance(document, dict):
        raise ClaimIntentError("document: must be an object")
    return _sha256_bytes(_canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Public API: claim-intent verifier.
# ---------------------------------------------------------------------------


def verify_claim_intent(document: dict) -> None:
    """Strict fail-closed validation of ``icp.requirement-claim-intent.v1``.

    Returns ``None`` on success; raises :class:`ClaimIntentError` on any
    shape, type, enum, ordering, duplicate, unknown-key, injection, or
    content violation. ``requirement_id`` is required to be a bare
    64-char lowercase SHA-256 hex string; the locked derivation is
    enforced by ``icp.active-requirement.v1`` after a claim ack exists.
    """
    if not isinstance(document, dict):
        raise ClaimIntentError("claim_intent: must be an object")

    _check_keys_exact_order(document, CLAIM_INTENT_KEY_ORDER, "claim_intent")

    if document["kind"] != KIND_CLAIM_INTENT:
        raise ClaimIntentError(
            f"claim_intent.kind: must be {KIND_CLAIM_INTENT!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise ClaimIntentError(
            f"claim_intent.schema_version: must be {SCHEMA_VERSION!r}, "
            f"got {document['schema_version']!r}"
        )
    if document["expected_status_before"] != EXPECTED_STATUS_BEFORE:
        raise ClaimIntentError(
            f"claim_intent.expected_status_before: must be "
            f"{EXPECTED_STATUS_BEFORE!r}, got "
            f"{document['expected_status_before']!r}"
        )
    for key in _CLAIM_INTENT_DIGEST_FIELDS:
        if not _is_sha256_hex(document[key]):
            raise ClaimIntentError(
                f"claim_intent.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )

    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: recovery-report verifier.
# ---------------------------------------------------------------------------


def verify_claim_recovery_report(document: dict) -> None:
    """Strict fail-closed validation of
    ``icp.claim-recovery-report.v1``."""
    if not isinstance(document, dict):
        raise ClaimIntentError("claim_recovery_report: must be an object")

    _check_keys_exact_order(
        document, CLAIM_RECOVERY_REPORT_KEY_ORDER, "claim_recovery_report"
    )

    if document["kind"] != KIND_CLAIM_RECOVERY_REPORT:
        raise ClaimIntentError(
            f"claim_recovery_report.kind: must be "
            f"{KIND_CLAIM_RECOVERY_REPORT!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise ClaimIntentError(
            f"claim_recovery_report.schema_version: must be "
            f"{SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    for key in ("requirement_id", "intent_digest", "observed_source_sha256"):
        if not _is_sha256_hex(document[key]):
            raise ClaimIntentError(
                f"claim_recovery_report.{key}: must be SHA-256 hex "
                f"(64 lowercase)"
            )
    if document["decision"] not in RECOVERY_DECISIONS:
        raise ClaimIntentError(
            f"claim_recovery_report.decision: not controlled: "
            f"{document['decision']!r}"
        )
    if document["reason_code"] not in RECOVERY_REASONS:
        raise ClaimIntentError(
            f"claim_recovery_report.reason_code: not controlled: "
            f"{document['reason_code']!r}"
        )
    if document["observed_status"] not in OBSERVED_STATUSES:
        raise ClaimIntentError(
            f"claim_recovery_report.observed_status: not controlled: "
            f"{document['observed_status']!r}"
        )

    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: crash-window recovery decision state machine.
# ---------------------------------------------------------------------------


def decide_claim_recovery(
    intent: dict,
    *,
    expected_requirement_id: str,
    expected_selection_manifest_digest: str,
    expected_row_identity_digest: str,
    observed_status: str,
    observed_source_sha256: str,
) -> dict:
    """Pure crash-window recovery decision state machine.

    Decision rules, in order:

    1. Invalid intent or expected-identity mismatch -> raise
       :class:`ClaimIntentError`; never produce an actionable report.
    2. ``observed_status="empty"`` and observed SHA equals
       ``source_sha256_before`` -> ``retry-cas``.
    3. ``observed_status="doing"`` and observed SHA equals
       ``expected_source_sha256_after`` -> ``reconstruct-claim-ack``.
    4. SHA mismatch (empty or doing, observed SHA does not equal the
       matching expected) -> ``blocked / source-sha-mismatch``.
    5. ``done | error | unknown`` -> ``blocked / unexpected-row-status``.

    The returned ``icp.claim-recovery-report.v1`` never carries the
    full claim ack, a path, a task reference, row title, source
    contents, or a secret. P3d's TaskSource-specific recovery API
    reconstructs and persists the ack when this report says
    ``reconstruct-claim-ack``.
    """
    # Step 1: verify intent shape and expected identities. Identity
    # mismatch must never produce an actionable report.
    verify_claim_intent(intent)

    if not _is_sha256_hex(expected_requirement_id):
        raise ClaimIntentError(
            "expected_requirement_id: must be SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(expected_selection_manifest_digest):
        raise ClaimIntentError(
            "expected_selection_manifest_digest: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if not _is_sha256_hex(expected_row_identity_digest):
        raise ClaimIntentError(
            "expected_row_identity_digest: must be SHA-256 hex "
            "(64 lowercase)"
        )
    if intent["requirement_id"] != expected_requirement_id:
        raise ClaimIntentError(
            "intent-identity-mismatch: requirement_id does not match"
        )
    if intent["selection_manifest_digest"] != expected_selection_manifest_digest:
        raise ClaimIntentError(
            "intent-identity-mismatch: selection_manifest_digest mismatch"
        )
    if intent["row_identity_digest"] != expected_row_identity_digest:
        raise ClaimIntentError(
            "intent-identity-mismatch: row_identity_digest mismatch"
        )

    # Validate observed inputs before choosing a branch.
    if observed_status not in OBSERVED_STATUSES:
        raise ClaimIntentError(
            f"observed_status: not controlled: {observed_status!r}"
        )
    if not _is_sha256_hex(observed_source_sha256):
        raise ClaimIntentError(
            "observed_source_sha256: must be SHA-256 hex (64 lowercase)"
        )

    # Steps 2-5: choose (decision, reason).
    if observed_status == "empty":
        if observed_source_sha256 == intent["source_sha256_before"]:
            decision, reason = "retry-cas", "row-empty-before-sha-match"
        else:
            decision, reason = "blocked", "source-sha-mismatch"
    elif observed_status == "doing":
        if observed_source_sha256 == intent["expected_source_sha256_after"]:
            decision, reason = (
                "reconstruct-claim-ack",
                "row-doing-after-sha-match",
            )
        else:
            decision, reason = "blocked", "source-sha-mismatch"
    else:
        # observed_status in (done, error, unknown).
        decision, reason = "blocked", "unexpected-row-status"

    intent_digest = document_digest(intent)
    report = {
        "kind": KIND_CLAIM_RECOVERY_REPORT,
        "schema_version": SCHEMA_VERSION,
        "requirement_id": intent["requirement_id"],
        "intent_digest": intent_digest,
        "decision": decision,
        "reason_code": reason,
        "observed_status": observed_status,
        "observed_source_sha256": observed_source_sha256,
    }
    # Defense in depth: the returned report must itself verify.
    verify_claim_recovery_report(report)
    return report
