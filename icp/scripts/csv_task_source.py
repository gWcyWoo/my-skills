#!/usr/bin/env python3
"""ICP P1b CSV TaskSource wrapper.

This module is the only ICP runtime surface that mutates a CSV task source.
It wraps the byte-frozen local primitive
``icp/scripts/task_sources/csv_row_status_v1.py`` (a byte-for-byte copy of the
proven ``iff`` CSV row-status implementation, pinned by SHA-256) and exposes
five versioned/kinded JSON-serializable operations:

* ``probe(task_ref)`` -> ``task_source_probe.v1`` ack
* ``select_candidates(task_ref, limit)`` -> list of candidate row dicts
* ``claim(task_ref, row_identity, expected_status='')`` -> ``icp.claim.v1`` ack
* ``export_inputs(task_ref, claim_ack, run_root)`` -> ``icp.export_inputs.v1`` ack
* ``writeback(task_ref, claim_ack, *, outcome, expected_status='doing')`` ->
  ``icp.writeback.v1`` ack

Hard rules:

* ``row_identity`` is the semantic unique ``title``; ``rowIndex`` is evidence,
  not the CAS key. The frozen primitive matches rows by NFC-normalized title.
* P1b accepts the frozen primitive's semantic headers/aliases (English and the
  Chinese forms); selection candidates are rows whose status is exactly empty.
* ``limit`` is a positive integer and selection preserves CSV order.
* ``claim`` is exactly CAS ``empty -> doing`` under the frozen primitive's
  exclusive ``flock`` + same-directory atomic replace. A losing concurrent
  claimant fails visibly and is not counted as claimed.
* ``writeback`` supports only ``done`` or ``error`` outcomes and never performs
  an unconditional write.
* ``export_inputs`` writes canonical ``row.json``, ``interaction.txt``,
  ``ui_notes.txt``, ``api.txt`` under a row-specific directory beneath the
  batch run root via the frozen exporter's atomic file writes. The row
  directory name is derived from a SHA-256 of the title so no path traversal
  from a title is possible.

The wrapper has no runtime dependency on any ``iff`` path: it imports only the
local frozen copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

# Resolve the sibling ``task_sources`` package without polluting sys.path. The
# frozen primitive has no ``iff`` import; importing it locally satisfies the
# P1b "no runtime iff dependency" rule.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from task_sources import csv_row_status_v1 as _rs  # noqa: E402
import requirement_claim_intent_v1 as _claim_intent  # noqa: E402
import requirement_progress_v1 as _requirement_progress  # noqa: E402

# Re-export the SHA-256 of the frozen primitive so callers/tests can verify it
# without re-hashing the file.
FROZEN_PRIMITIVE_PATH = _HERE / "task_sources" / "csv_row_status_v1.py"
FROZEN_PRIMITIVE_SHA256 = (
    "d5a1f418694d002335671694c8fa419368b36919f168cfd93a33b3c2479105ae"
)

CLAIM_TARGET_STATUS = "doing"
WRITEBACK_OUTCOMES = frozenset({"done", "error"})
EMPTY_STATUS = ""

# Sanitized row directory prefix; the body is the first 32 hex chars of the
# SHA-256 of the NFC-normalized title so identical titles map deterministically
# and no path traversal from a title is possible.
_ROW_DIR_PREFIX = "row-"
_SLASH_OR_DOTDOT = re.compile(r"[/\\]|\.\.")


class CsvTaskSourceError(RuntimeError):
    """Structured, code-bearing wrapper failure.

    ``code`` is always one of the public :mod:`icp_common` error codes (a
    member of ``icp_common.ALL_ERROR_CODES``). TaskSource path/parse/primitive
    failures are normalized to ``task_preflight_failed``. ``ack`` is the
    canonical JSON-serializable failure ack so callers can emit it directly.
    """

    def __init__(self, code: str, message: str, *, ack: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.ack = ack if ack is not None else _failure_ack(code, message)


def _failure_ack(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _is_posint(limit: Any) -> bool:
    return isinstance(limit, int) and not isinstance(limit, bool) and limit > 0


def _nfc(value: str) -> str:
    return _rs.normalized(value)


def _assert_regular_task_file(path: Path) -> None:
    """Reject symlink, missing, or non-regular task paths before any read or
    mutation.

    Raises :class:`CsvTaskSourceError` with code ``task_preflight_failed`` so a
    symlinked or special-file task source can never reach the frozen
    primitive's read or atomic-replace path. Mirrors the read-only
    ``preflight_csv_task_source`` symlink/non-regular gate so direct
    TaskSource operations and the hard-ordered prepare pipeline share one
    invariant.
    """
    if path.is_symlink():
        raise CsvTaskSourceError(
            "task_preflight_failed", f"task path must not be a symlink: {path}"
        )
    try:
        st = path.stat()
    except FileNotFoundError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"task file not found: {path}"
        ) from exc
    except OSError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"cannot stat task file: {exc}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise CsvTaskSourceError(
            "task_preflight_failed", f"task path is not a regular file: {path}"
        )


def _row_directory(run_root: Path, title: str) -> Path:
    """Deterministic, traversal-safe row directory beneath ``run_root``.

    The directory name is ``row-`` + the first 32 hex chars of the SHA-256 of
    the NFC-normalized title. Title bytes never become path components, so a
    title containing ``/``, ``..`` or shell metacharacters cannot escape the
    run root or be executed.
    """
    digest = hashlib.sha256(_nfc(title).encode("utf-8")).hexdigest()[:32]
    return Path(run_root) / f"{_ROW_DIR_PREFIX}{digest}"


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def probe(task_ref: Path | str) -> dict[str, Any]:
    """Read-only CSV TaskSource probe -> ``task_source_probe.v1`` ack.

    Parses the CSV via the frozen primitive, records format/column evidence
    and per-status row counts. Never mutates task bytes. Rejects symlink and
    non-regular task paths before reading. Raises
    :class:`CsvTaskSourceError` (code ``task_preflight_failed``) on any
    structural or IO failure.
    """
    path = Path(task_ref)
    _assert_regular_task_file(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"task file not found: {path}"
        ) from exc
    except OSError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"cannot read task file: {exc}"
        ) from exc

    try:
        document = _rs.parse_document(raw)
    except _rs.CsvStatusError as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc

    status_idx = document.status_index
    title_idx = document.title_index
    counts: dict[str, int] = {"": 0, "doing": 0, "done": 0, "error": 0}
    for record in document.records[1:]:
        value = record[status_idx].value
        counts[value] = counts.get(value, 0) + 1

    return {
        "kind": "task_source_probe.v1",
        "schema_version": 1,
        "ok": True,
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "format": {
            "encoding": "UTF-8",
            "bom": document.bom,
            "delimiter": document.delimiter.decode("ascii"),
            "line_endings": _rs.line_endings(document.raw),
        },
        "columns": {
            "title": document.headers[title_idx],
            "status": document.headers[status_idx],
            "header_count": len(document.headers),
        },
        "rows_total": len(document.records) - 1,
        "statuses": counts,
    }


def probe_write_readiness(task_ref: Path | str) -> dict[str, Any]:
    """Prove same-directory create/replace/fsync/cleanup without touching CSV bytes."""
    path = Path(task_ref)
    _assert_regular_task_file(path)
    parent = path.parent
    source: Path | None = None
    target: Path | None = None
    source_fd: int | None = None
    target_fd: int | None = None
    cleanup_errors: list[str] = []
    try:
        source_fd, source_name = tempfile.mkstemp(prefix=".icp-readiness-", suffix=".tmp", dir=parent)
        source = Path(source_name)
        target_fd, target_name = tempfile.mkstemp(prefix=".icp-readiness-", suffix=".probe", dir=parent)
        target = Path(target_name)
        payload = b"icp.task-source.atomic-write.v1\n"
        os.write(source_fd, payload)
        os.fsync(source_fd)
        os.close(source_fd)
        source_fd = None
        os.close(target_fd)
        target_fd = None
        os.replace(source, target)
        source = None
        if target.read_bytes() != payload:
            raise OSError("atomic replacement verification failed")
        target.unlink()
        target = None
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception as exc:
        failure = exc
    else:
        failure = None
    finally:
        for fd in (source_fd, target_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:
                    cleanup_errors.append(type(exc).__name__)
        for temporary in (source, target):
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_errors.append(type(exc).__name__)
    if failure is not None or cleanup_errors:
        raise CsvTaskSourceError(
            "task_preflight_failed",
            "task source atomic-write readiness failed",
        ) from failure
    return {
        "kind": "task_source_write_readiness.v1",
        "ok": True,
        "evidence_digest": hashlib.sha256(
            b"icp.task-source.atomic-write.v1\x00create+replace+fsync+cleanup"
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# select_candidates
# ---------------------------------------------------------------------------


def _row_dict(document: "_rs.Document", record: list["_rs.Field"], row_index: int) -> dict[str, Any]:
    """Build a JSON-serializable candidate row dict from a parsed record."""

    def _value(name: str, aliases: tuple[str, ...]) -> str:
        idx = _rs.optional_semantic_index(document.headers, aliases, name)
        if idx is None:
            return ""
        return record[idx].value

    out: dict[str, Any] = {
        "row_index": row_index,
        "title": record[document.title_index].value,
        "status": record[document.status_index].value,
        "design_url": _value("design_url", _rs.DESIGN_URL_ALIASES),
        "ui_notes": _value("ui_notes", _rs.UI_NOTES_ALIASES),
        "interaction": _value("interaction", _rs.INTERACTION_ALIASES),
        "api": _value("api", _rs.API_ALIASES),
    }
    # Optional semantic columns are surfaced as evidence when present.
    optional = {
        "id": _rs.ID_ALIASES,
        "error": _rs.ERROR_ALIASES,
        "spec_dir": _rs.SPEC_DIR_ALIASES,
    }
    for name, aliases in optional.items():
        idx = _rs.optional_semantic_index(document.headers, aliases, name)
        if idx is not None:
            out[name] = record[idx].value
    return out


def select_candidates(task_ref: Path | str, limit: int) -> list[dict[str, Any]]:
    """Return up to ``limit`` empty-status candidate rows in CSV order.

    Selection candidates are rows whose status cell is exactly empty. The
    frozen primitive's semantic headers/aliases are accepted. ``limit`` must
    be a positive integer; CSV order is preserved.

    Raises :class:`CsvTaskSourceError` (code ``task_preflight_failed``) if the
    CSV cannot be parsed, or code ``invalid_input`` if ``limit`` is not a
    positive integer. Duplicate active (empty-status) titles are rejected here
    so they can never reach the freeze boundary.
    """
    if not _is_posint(limit):
        raise CsvTaskSourceError(
            "invalid_input", f"limit must be a positive integer, got {limit!r}"
        )

    path = Path(task_ref)
    _assert_regular_task_file(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"task file not found: {path}"
        ) from exc
    except OSError as exc:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"cannot read task file: {exc}"
        ) from exc

    try:
        document = _rs.parse_document(raw)
    except _rs.CsvStatusError as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc

    candidates: list[dict[str, Any]] = []
    seen_titles: dict[str, int] = {}
    for offset, record in enumerate(document.records[1:], start=1):
        if record[document.status_index].value != EMPTY_STATUS:
            continue
        candidate = _row_dict(document, record, offset)
        norm = _nfc(candidate["title"])
        if norm in seen_titles:
            raise CsvTaskSourceError(
                "task_preflight_failed",
                (
                    "duplicate active title before freeze: "
                    f"{candidate['title']!r} at rows {seen_titles[norm]} and {offset}"
                ),
            )
        seen_titles[norm] = offset
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def claim(
    task_ref: Path | str,
    row_identity: str,
    expected_status: str = EMPTY_STATUS,
) -> dict[str, Any]:
    """CAS ``expected_status -> doing`` claim -> ``icp.claim.v1`` ack.

    ``row_identity`` is the semantic title of the row (the CAS key).
    ``expected_status`` defaults to the empty string (the only legal initial
    state for a fresh selection). Delegates to the frozen primitive's
    exclusive-``flock`` + same-directory atomic-replace update, so a losing
    concurrent claimant fails visibly and is not counted as claimed.

    Rejects symlink and non-regular task paths before any read or mutation.
    Raises :class:`CsvTaskSourceError` (code ``task_preflight_failed``) on any
    CAS drift, missing/ambiguous title, or primitive-level rejection.
    """
    if not isinstance(row_identity, str) or row_identity == "":
        raise CsvTaskSourceError(
            "invalid_input", "row_identity (title) must be a non-empty string"
        )
    if expected_status not in _rs.VALID_STATUSES:
        raise CsvTaskSourceError(
            "invalid_input",
            f"expected_status must be one of {sorted(_rs.VALID_STATUSES)}, "
            f"got {expected_status!r}",
        )

    path = Path(task_ref)
    _assert_regular_task_file(path)

    try:
        result = _rs.update_csv(
            path=path,
            title=row_identity,
            expected_status=expected_status,
            status_value=CLAIM_TARGET_STATUS,
        )
    except _rs.CsvStatusError as exc:
        # CAS drift / ambiguous title / primitive rejection. The frozen
        # primitive has already released its lock and left task bytes intact.
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc

    return {
        "kind": "icp.claim.v1",
        "schema_version": 1,
        "ok": True,
        "task_ref": str(path),
        "row_identity": row_identity,
        "row_index": result["rowIndex"],
        "previous_status": expected_status,
        "status": CLAIM_TARGET_STATUS,
        "sha256_before": result["sha256Before"],
        "sha256_after": result["sha256After"],
    }


def _preview_claim_transition(path: Path, row_identity: str) -> dict[str, Any]:
    _assert_regular_task_file(path)
    try:
        document = _rs.parse_document(path.read_bytes())
        matches = _rs.matching_rows(document, row_identity)
    except (OSError, _rs.CsvStatusError) as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc
    if len(matches) != 1:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"expected exactly one row for identity {row_identity!r}"
        )
    row_index, record = matches[0]
    status_field = record[document.status_index]
    if status_field.value != EMPTY_STATUS:
        raise CsvTaskSourceError(
            "task_preflight_failed", f"row status must be empty before claim, got {status_field.value!r}"
        )
    replacement = _rs.encoded_replacement(status_field, CLAIM_TARGET_STATUS, document.delimiter)
    updated = document.raw[: status_field.start] + replacement + document.raw[status_field.end :]
    return {
        "row_index": row_index,
        "sha256_before": hashlib.sha256(document.raw).hexdigest(),
        "sha256_after": hashlib.sha256(updated).hexdigest(),
    }


def prepare_claim_intent(
    task_ref: Path | str,
    row_identity: str,
    *,
    requirement_id: str,
    selection_manifest_digest: str,
    row_identity_digest: str,
    task_source_snapshot_digest: str,
    candidate_identity_digest: str,
) -> dict[str, Any]:
    """Build the immutable intent that must be persisted before the claim CAS."""
    expected_requirement_id = _requirement_progress.derive_requirement_id(
        selection_manifest_digest, row_identity_digest
    )
    if requirement_id != expected_requirement_id:
        raise CsvTaskSourceError("claim_intent_identity_mismatch", "requirement identity derivation mismatch")
    preview = _preview_claim_transition(Path(task_ref), row_identity)
    intent = {
        "kind": _claim_intent.KIND_CLAIM_INTENT,
        "schema_version": _claim_intent.SCHEMA_VERSION,
        "requirement_id": requirement_id,
        "selection_manifest_digest": selection_manifest_digest,
        "row_identity_digest": row_identity_digest,
        "task_source_snapshot_digest": task_source_snapshot_digest,
        "candidate_identity_digest": candidate_identity_digest,
        "expected_status_before": _claim_intent.EXPECTED_STATUS_BEFORE,
        "source_sha256_before": preview["sha256_before"],
        "expected_source_sha256_after": preview["sha256_after"],
    }
    _claim_intent.verify_claim_intent(intent)
    return intent


def _observe_claim_state(path: Path, row_identity: str) -> tuple[str, str, int | None]:
    _assert_regular_task_file(path)
    try:
        raw = path.read_bytes()
        document = _rs.parse_document(raw)
        matches = _rs.matching_rows(document, row_identity)
    except (OSError, _rs.CsvStatusError) as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if len(matches) != 1:
        return "unknown", source_sha256, None
    row_index, record = matches[0]
    raw_status = record[document.status_index].value
    observed_status = "empty" if raw_status == EMPTY_STATUS else raw_status
    if observed_status not in _claim_intent.OBSERVED_STATUSES:
        observed_status = "unknown"
    return observed_status, source_sha256, row_index


def claim_with_intent(task_ref: Path | str, row_identity: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute the legacy claim only when the persisted intent still authorizes it."""
    _claim_intent.verify_claim_intent(intent)
    path = Path(task_ref)
    observed_status, observed_sha256, _ = _observe_claim_state(path, row_identity)
    report = _claim_intent.decide_claim_recovery(
        intent,
        expected_requirement_id=intent["requirement_id"],
        expected_selection_manifest_digest=intent["selection_manifest_digest"],
        expected_row_identity_digest=intent["row_identity_digest"],
        observed_status=observed_status,
        observed_source_sha256=observed_sha256,
    )
    if report["decision"] != "retry-cas":
        raise CsvTaskSourceError(
            "claim_intent_not_actionable", f"claim intent decision is {report['decision']}"
        )
    ack = claim(path, row_identity, expected_status=EMPTY_STATUS)
    if (
        ack.get("sha256_before") != intent["source_sha256_before"]
        or ack.get("sha256_after") != intent["expected_source_sha256_after"]
    ):
        raise CsvTaskSourceError("claim_ack_identity_mismatch", "claim ack does not match claim intent")
    return ack


def recover_claim_with_intent(
    task_ref: Path | str, row_identity: str, intent: dict[str, Any]
) -> dict[str, Any]:
    """Retry a pre-CAS crash or reconstruct the exact post-CAS legacy ack."""
    _claim_intent.verify_claim_intent(intent)
    path = Path(task_ref)
    observed_status, observed_sha256, row_index = _observe_claim_state(path, row_identity)
    report = _claim_intent.decide_claim_recovery(
        intent,
        expected_requirement_id=intent["requirement_id"],
        expected_selection_manifest_digest=intent["selection_manifest_digest"],
        expected_row_identity_digest=intent["row_identity_digest"],
        observed_status=observed_status,
        observed_source_sha256=observed_sha256,
    )
    if report["decision"] == "retry-cas":
        ack = claim_with_intent(path, row_identity, intent)
    elif report["decision"] == "reconstruct-claim-ack":
        if row_index is None:
            raise CsvTaskSourceError("claim_ack_reconstruction_failed", "claimed row is unavailable")
        ack = {
            "kind": "icp.claim.v1",
            "schema_version": 1,
            "ok": True,
            "task_ref": str(path),
            "row_identity": row_identity,
            "row_index": row_index,
            "previous_status": EMPTY_STATUS,
            "status": CLAIM_TARGET_STATUS,
            "sha256_before": intent["source_sha256_before"],
            "sha256_after": intent["expected_source_sha256_after"],
        }
    else:
        ack = None
    return {"recovery_report": report, "claim_ack": ack}


def prepare_writeback_intent(
    task_ref: Path | str, claim_ack: dict[str, Any], *, outcome: str
) -> dict[str, Any]:
    """Preview and freeze the exact terminal status CAS before mutation."""
    if outcome not in WRITEBACK_OUTCOMES:
        raise CsvTaskSourceError("invalid_input", "outcome must be done or error")
    if not isinstance(claim_ack, dict) or claim_ack.get("kind") != "icp.claim.v1" or claim_ack.get("ok") is not True:
        raise CsvTaskSourceError("invalid_input", "claim_ack must be a successful icp.claim.v1 ack")
    path = Path(task_ref)
    if claim_ack.get("task_ref") != str(path):
        raise CsvTaskSourceError("invalid_input", "claim_ack task_ref mismatch")
    row_identity = claim_ack.get("row_identity")
    if not isinstance(row_identity, str) or not row_identity:
        raise CsvTaskSourceError("invalid_input", "claim_ack row identity is invalid")
    _assert_regular_task_file(path)
    try:
        document = _rs.parse_document(path.read_bytes())
        matches = _rs.matching_rows(document, row_identity)
    except (OSError, _rs.CsvStatusError) as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc
    if len(matches) != 1:
        raise CsvTaskSourceError("task_preflight_failed", "writeback row must be unique")
    row_index, record = matches[0]
    status_field = record[document.status_index]
    if status_field.value != CLAIM_TARGET_STATUS:
        raise CsvTaskSourceError("task_preflight_failed", "writeback row must remain doing")
    replacement = _rs.encoded_replacement(status_field, outcome, document.delimiter)
    updated = document.raw[: status_field.start] + replacement + document.raw[status_field.end :]
    return {
        "kind": "icp.writeback-intent.v1",
        "schema_version": 1,
        "claim_ack_digest": hashlib.sha256(ack_to_json_bytes(claim_ack)).hexdigest(),
        "task_ref": str(path),
        "row_identity": row_identity,
        "row_index": row_index,
        "expected_status_before": CLAIM_TARGET_STATUS,
        "outcome": outcome,
        "source_sha256_before": hashlib.sha256(document.raw).hexdigest(),
        "expected_source_sha256_after": hashlib.sha256(updated).hexdigest(),
    }


def recover_writeback_with_intent(
    task_ref: Path | str,
    claim_ack: dict[str, Any],
    intent: dict[str, Any],
) -> dict[str, Any]:
    """Execute or reconstruct one terminal CAS from its immutable intent."""
    expected_order = (
        "kind",
        "schema_version",
        "claim_ack_digest",
        "task_ref",
        "row_identity",
        "row_index",
        "expected_status_before",
        "outcome",
        "source_sha256_before",
        "expected_source_sha256_after",
    )
    if not isinstance(intent, dict) or tuple(intent) != expected_order:
        raise CsvTaskSourceError("invalid_input", "writeback intent shape is invalid")
    if intent["kind"] != "icp.writeback-intent.v1" or intent["schema_version"] != 1:
        raise CsvTaskSourceError("invalid_input", "writeback intent identity is invalid")
    if intent["outcome"] not in WRITEBACK_OUTCOMES or intent["expected_status_before"] != CLAIM_TARGET_STATUS:
        raise CsvTaskSourceError("invalid_input", "writeback intent status transition is invalid")
    if hashlib.sha256(ack_to_json_bytes(claim_ack)).hexdigest() != intent["claim_ack_digest"]:
        raise CsvTaskSourceError("invalid_input", "writeback intent claim ack mismatch")
    path = Path(task_ref)
    if str(path) != intent["task_ref"] or claim_ack.get("row_identity") != intent["row_identity"]:
        raise CsvTaskSourceError("invalid_input", "writeback intent scope mismatch")
    observed_status, observed_sha256, row_index = _observe_claim_state(path, intent["row_identity"])
    if observed_status == CLAIM_TARGET_STATUS and observed_sha256 == intent["source_sha256_before"]:
        ack = writeback(path, claim_ack, outcome=intent["outcome"], expected_status=CLAIM_TARGET_STATUS)
        if ack["sha256_after"] != intent["expected_source_sha256_after"]:
            raise CsvTaskSourceError("writeback_ack_identity_mismatch", "writeback ack does not match intent")
        return {"decision": "writeback-cas", "writeback_ack": ack}
    if observed_status == intent["outcome"] and observed_sha256 == intent["expected_source_sha256_after"]:
        if row_index != intent["row_index"]:
            raise CsvTaskSourceError("writeback_ack_reconstruction_failed", "writeback row index drift")
        ack = {
            "kind": "icp.writeback.v1",
            "schema_version": 1,
            "ok": True,
            "task_ref": str(path),
            "row_identity": intent["row_identity"],
            "row_index": intent["row_index"],
            "previous_status": CLAIM_TARGET_STATUS,
            "status": intent["outcome"],
            "sha256_before": intent["source_sha256_before"],
            "sha256_after": intent["expected_source_sha256_after"],
        }
        return {"decision": "reconstruct-writeback-ack", "writeback_ack": ack}
    return {"decision": "blocked", "writeback_ack": None}


# ---------------------------------------------------------------------------
# export_inputs
# ---------------------------------------------------------------------------


def export_inputs(
    task_ref: Path | str,
    claim_ack: dict[str, Any],
    run_root: Path | str,
) -> dict[str, Any]:
    """Export canonical row inputs -> ``icp.export_inputs.v1`` ack.

    Writes exactly four files beneath a row-specific directory under
    ``run_root``: ``row.json``, ``interaction.txt``, ``ui_notes.txt``,
    ``api.txt``. The row directory name is derived from a SHA-256 of the
    NFC-normalized title so no path traversal from a title is possible. The
    frozen primitive's atomic-replace writer is used for every file.

    ``claim_ack`` must be a successful ``icp.claim.v1`` ack; its
    ``row_identity`` and ``status`` are used as the CAS gate for the export.
    """
    if not isinstance(claim_ack, dict) or not claim_ack.get("ok"):
        raise CsvTaskSourceError(
            "invalid_input", "claim_ack must be a successful icp.claim.v1 ack"
        )
    title = claim_ack.get("row_identity")
    if not isinstance(title, str) or title == "":
        raise CsvTaskSourceError(
            "invalid_input", "claim_ack.row_identity must be a non-empty string"
        )
    expected_status = claim_ack.get("status") or CLAIM_TARGET_STATUS
    if expected_status not in _rs.VALID_STATUSES:
        raise CsvTaskSourceError(
            "invalid_input",
            f"claim_ack.status must be one of {sorted(_rs.VALID_STATUSES)}, "
            f"got {expected_status!r}",
        )

    # Validate the task path BEFORE touching run_root or creating any row
    # directory, so a symlink/non-regular failure leaves the supplied run root
    # absent/unchanged.
    path = Path(task_ref)
    _assert_regular_task_file(path)

    run_root_path = Path(run_root)
    # Defensive: the row directory name is fully derived from a hash; this
    # check documents the invariant and guards against future regressions.
    row_dir = _row_directory(run_root_path, title)
    if _SLASH_OR_DOTDOT.search(row_dir.name):
        # Pure defense-in-depth: the hex digest body never contains slashes.
        raise CsvTaskSourceError(
            "invalid_input", f"row directory name is not traversal-safe: {row_dir.name!r}"
        )
    row_dir.mkdir(parents=True, exist_ok=True)

    row_json_path = row_dir / "row.json"
    interaction_path = row_dir / "interaction.txt"
    ui_notes_path = row_dir / "ui_notes.txt"
    api_path = row_dir / "api.txt"

    try:
        result = _rs.export_csv(
            path=path,
            title=title,
            expect_status=expected_status,
            output=row_json_path,
            interaction_output=interaction_path,
            ui_notes_output=ui_notes_path,
            api_output=api_path,
        )
    except _rs.CsvStatusError as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc

    produced = sorted(p.name for p in row_dir.iterdir())
    return {
        "kind": "icp.export_inputs.v1",
        "schema_version": 1,
        "ok": True,
        "task_ref": str(path),
        "row_identity": title,
        "row_directory": str(row_dir),
        "files": {
            "row_json": "row.json",
            "interaction_txt": "interaction.txt",
            "ui_notes_txt": "ui_notes.txt",
            "api_txt": "api.txt",
        },
        "produced": produced,
        "lengths": result["lengths"],
        "status_at_export": result["status"],
    }


# ---------------------------------------------------------------------------
# writeback
# ---------------------------------------------------------------------------


def writeback(
    task_ref: Path | str,
    claim_ack: dict[str, Any],
    *,
    outcome: str,
    expected_status: str = CLAIM_TARGET_STATUS,
) -> dict[str, Any]:
    """CAS ``expected_status -> outcome`` writeback -> ``icp.writeback.v1`` ack.

    ``outcome`` must be exactly ``done`` or ``error``; no other terminal
    status is accepted. The frozen primitive's CAS update is used, so a stale
    writeback (status drift) fails visibly and the task bytes are never
    unconditionally rewritten.
    """
    if outcome not in WRITEBACK_OUTCOMES:
        raise CsvTaskSourceError(
            "invalid_input",
            f"outcome must be one of {sorted(WRITEBACK_OUTCOMES)}, got {outcome!r}",
        )
    if not isinstance(claim_ack, dict) or not claim_ack.get("ok"):
        raise CsvTaskSourceError(
            "invalid_input", "claim_ack must be a successful icp.claim.v1 ack"
        )
    title = claim_ack.get("row_identity")
    if not isinstance(title, str) or title == "":
        raise CsvTaskSourceError(
            "invalid_input", "claim_ack.row_identity must be a non-empty string"
        )
    if expected_status not in _rs.VALID_STATUSES:
        raise CsvTaskSourceError(
            "invalid_input",
            f"expected_status must be one of {sorted(_rs.VALID_STATUSES)}, "
            f"got {expected_status!r}",
        )

    path = Path(task_ref)
    _assert_regular_task_file(path)
    try:
        result = _rs.update_csv(
            path=path,
            title=title,
            expected_status=expected_status,
            status_value=outcome,
        )
    except _rs.CsvStatusError as exc:
        raise CsvTaskSourceError("task_preflight_failed", str(exc)) from exc

    return {
        "kind": "icp.writeback.v1",
        "schema_version": 1,
        "ok": True,
        "task_ref": str(path),
        "row_identity": title,
        "row_index": result["rowIndex"],
        "previous_status": expected_status,
        "status": outcome,
        "sha256_before": result["sha256Before"],
        "sha256_after": result["sha256After"],
    }


def ack_to_json_bytes(ack: dict[str, Any]) -> bytes:
    """Canonical JSON encoding for an ack (sorted keys, two-space indent)."""
    return (json.dumps(ack, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
