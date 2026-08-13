#!/usr/bin/env python3
"""ICP P1b hard-ordered selection orchestrator + production CLI.

Production entry surface:

    prepare_selection.py --config RESOLVED.json --limit N

The hard order is:

1. strict-decode and validate resolved config;
2. load only internal registries;
3. support gate first;
4. read-only ``preflight_csv_task_source`` (symlink/non-regular gate, parse
   probe, atomic-replace directory access) — before manifest/run-root
   creation and before any mutation;
5. TaskSource wrapper probe/select;
6. candidate design locator syntax checks and generic project-root preflight;
7. generate internal batch id and freeze manifest;
8. only after freeze success, claim candidates sequentially with CAS;
9. export inputs only for successful claims.

In P1b all seven registered platforms are still inactive, so the production
CLI returns ``unsupported_platform`` before touching the task path. A
lower-level orchestrator function (``prepare_selection``) accepts an
in-memory registry so unit tests can exercise the post-gate behavior; the CLI
exposes no registry, batch id, root, script, or command override.

The CLI always emits exactly one canonical JSON object and never a traceback.
A manifest conflict leaves every candidate row blank. A failed claim is
reported as failed and is excluded from successful claims; success is never
faked. Every emitted ``code`` belongs to ``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Callable

import icp_common
import preflight_selection
import csv_task_source
import freeze_selection_manifest

import entry_readiness_v1 as _entry_readiness
import platform_package_resolver_v1 as _package_resolver

SCRIPT_NAME = "prepare_selection.py"

# A claim callback receives the freeze ack and the candidate about to be
# claimed; it runs after the manifest is durably present and before the CAS
# claim. Returning False aborts the run with a structured failure.
ClaimProbe = Callable[[dict[str, Any], dict[str, Any]], bool]


# ---------------------------------------------------------------------------
# Internal batch id generation. Never read from run-config.
# ---------------------------------------------------------------------------


def generate_batch_id() -> str:
    """Generate an internal, path-safe batch id.

    Form: ``batch-<seconds>-<8 hex chars>``. Time is included only for human
    readability of run directories; the random tail guarantees uniqueness
    even across same-second invocations. The orchestrator never accepts a
    batch id from run-config; tests may pass an explicit one to the
    lower-level orchestrator function.
    """
    return f"batch-{int(time.time())}-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------
# Config-shape validation (re-uses P1a strict surfaces; rejects overrides).
# ---------------------------------------------------------------------------


# Run-config fields that must never be accepted as resolved-config additions.
_FORBIDDEN_OVERRIDE_KEYS = frozenset(
    {
        "state_root",
        "run_root",
        "registry",
        "registry_path",
        "script",
        "script_path",
        "scripts_dir",
        "command",
        "cmd",
        "shell",
        "env",
        "executable",
        "argv",
        "batch_id",
        "manifest_path",
        "subprocess",
    }
)


def _validate_resolved(config: Any) -> preflight_selection.PreflightResult | None:
    """Strict resolved-config validation, with P1b override-key rejection."""
    base = preflight_selection.validate_resolved_config(config)
    if base is not None:
        return base
    assert isinstance(config, dict)
    unexpected_override = sorted(set(config.keys()) & _FORBIDDEN_OVERRIDE_KEYS)
    if unexpected_override:
        return preflight_selection._fail(
            icp_common.INVALID_INPUT,
            f"resolved config must not override internal field(s): {unexpected_override}",
        )
    return None


# ---------------------------------------------------------------------------
# Low-level orchestrator (testable post-gate behavior).
# ---------------------------------------------------------------------------


def prepare_selection(
    *,
    resolved_config: dict[str, Any],
    limit: int,
    registries: dict[str, Any] | None = None,
    batch_id: str | None = None,
    on_manifest_frozen: ClaimProbe | None = None,
) -> dict[str, Any]:
    """Low-level hard-ordered orchestrator. Returns one canonical ack dict.

    Hard order: validate -> registries -> support gate -> probe/select ->
    design + project preflight -> freeze manifest -> claim sequentially ->
    export successes.

    ``registries`` may be supplied in tests to activate a platform and
    exercise the post-gate behavior; production callers must omit it so the
    internal immutable registries are loaded. ``batch_id`` may be supplied in
    tests for deterministic run roots; production callers must omit it.
    ``on_manifest_frozen`` is invoked after the manifest is durably written
    and before each claim, so tests can assert the manifest's presence.

    Failures surface as a single ``{"ok": False, "code": ..., "message": ...}``
    ack; successes surface as ``{"ok": True, "kind": "icp.prepare.v1", ...}``
    with per-candidate claim/export evidence.
    """
    # 1. Strict resolved-config validation (also rejects override keys).
    validation = _validate_resolved(resolved_config)
    if validation is not None:
        return _ack_fail(validation.code, validation.message)

    # 2. Load only internal registries when none supplied (tests may inject).
    if registries is None:
        try:
            registries = icp_common.load_registries()
        except icp_common.ConfigError as exc:
            return _ack_fail(exc.code, exc.message)

    # 3. Support gate first (fail-closed for every P1b platform in production).
    gate = preflight_selection.support_gate(resolved_config, registries)
    if not gate.ok:
        return _ack_fail(gate.code, gate.message)

    # 4. Hard order: read-only CSV TaskSource preflight (symlink/non-regular
    #    gate, parse probe, atomic-replace directory access) BEFORE any wrapper
    #    probe/select and BEFORE manifest/run-root creation or mutation.
    if not csv_task_source._is_posint(limit):
        return _ack_fail(
            icp_common.INVALID_INPUT, f"limit must be a positive integer, got {limit!r}"
        )
    task_ref = resolved_config["task_ref"]
    task_preflight = preflight_selection.preflight_csv_task_source(task_ref)
    if not task_preflight.ok:
        return _ack_fail(task_preflight.code, task_preflight.message)

    # 5. TaskSource read-only probe + select.
    try:
        probe_ack = csv_task_source.probe(task_ref)
    except csv_task_source.CsvTaskSourceError as exc:
        return _ack_fail(exc.code, exc.message)
    try:
        candidates = csv_task_source.select_candidates(task_ref, limit)
    except csv_task_source.CsvTaskSourceError as exc:
        return _ack_fail(exc.code, exc.message)

    # 6. Candidate design locator syntax checks + generic project-root preflight.
    for cand in candidates:
        design_url = cand.get("design_url", "")
        design_check = preflight_selection.preflight_design_locator(design_url)
        if not design_check.ok:
            return _ack_fail(
                design_check.code,
                f"candidate {cand.get('title')!r}: {design_check.message}",
            )
    project_check = preflight_selection.preflight_project_root(resolved_config["project_root"])
    if not project_check.ok:
        return _ack_fail(project_check.code, project_check.message)

    # 7. Generate internal batch id (or honor the test-supplied one) and freeze.
    chosen_batch_id = batch_id if batch_id is not None else generate_batch_id()
    try:
        freeze_ack = freeze_selection_manifest.freeze_selection_manifest(
            resolved_config=resolved_config,
            candidates=candidates,
            batch_id=chosen_batch_id,
            registries=registries,
        )
    except freeze_selection_manifest.ManifestFreezeError as exc:
        # Manifest conflict/failure occurs before any claim; candidate rows
        # are untouched.
        return _ack_fail(exc.code, exc.message)

    # The manifest is now durably present. Probe callback (used by tests and
    # later phases to assert the contract) runs before any claim.
    if on_manifest_frozen is not None:
        for cand in candidates:
            try:
                ok = on_manifest_frozen(freeze_ack, cand)
            except Exception as exc:  # noqa: BLE001
                return _ack_fail(
                    icp_common.INVALID_INPUT,
                    f"on_manifest_frozen callback raised: {type(exc).__name__}: {exc}",
                )
            if ok is False:
                return _ack_fail(
                    icp_common.SELECTION_MANIFEST_CONFLICT,
                    "on_manifest_frozen callback refused the candidate after freeze",
                )

    # 8. Claim sequentially with CAS. One failed claim is reported as failed
    #    and excluded from successful claims; never pretend success.
    run_root = Path(freeze_ack["run_root"])
    claim_results: list[dict[str, Any]] = []
    successes: list[dict[str, Any]] = []
    for cand in candidates:
        title = cand["title"]
        claim_entry: dict[str, Any] = {
            "row_identity": title,
            "row_index": cand.get("row_index"),
            "ok": False,
        }
        try:
            claim_ack = csv_task_source.claim(task_ref, title)
        except csv_task_source.CsvTaskSourceError as exc:
            claim_entry["code"] = exc.code
            claim_entry["message"] = exc.message
            claim_results.append(claim_entry)
            continue

        # 9. Export inputs only for successful claims.
        try:
            export_ack = csv_task_source.export_inputs(task_ref, claim_ack, run_root)
        except csv_task_source.CsvTaskSourceError as exc:
            # Claim succeeded but export failed; the claim is real (status is
            # 'doing' on disk). Surface the failure honestly without faking
            # success; the row remains claimed.
            claim_entry.update(
                {
                    "ok": True,
                    "claim_ack": claim_ack,
                    "export_failed": True,
                    "export_code": exc.code,
                    "export_message": exc.message,
                }
            )
            claim_results.append(claim_entry)
            continue

        claim_entry.update(
            {
                "ok": True,
                "claim_ack": claim_ack,
                "export_ack": export_ack,
            }
        )
        claim_results.append(claim_entry)
        successes.append(
            {
                "row_identity": title,
                "row_index": cand.get("row_index"),
                "claim_ack": claim_ack,
                "export_ack": export_ack,
            }
        )

    return {
        "ok": True,
        "kind": "icp.prepare.v1",
        "schema_version": 1,
        "batch_id": chosen_batch_id,
        "freeze_ack": freeze_ack,
        "probe": probe_ack,
        "actual_batch_size": len(candidates),
        "successful_count": len(successes),
        "failed_count": len(candidates) - len(successes),
        "claims": claim_results,
        "successes": successes,
    }


# ---------------------------------------------------------------------------
# P3b1b2 inactive entry seam (package-aware gate before TaskSource / freeze /
# claim). The production CLI never calls this function; it is a sibling seam
# used by future phase wiring and exercised directly by the focused self-test.
# ---------------------------------------------------------------------------

_SEAM_KIND = "icp.inactive-entry-seam-result.v1"
_SEAM_SCHEMA_VERSION = 1
_SEAM_DECISION_SELECT_NEW = "select-new"
_SEAM_REPORT_READY = "ready"
_SEAM_CODE_INVALID_INPUT = "invalid_input"


def _seam_digest(value: Any) -> str | None:
    try:
        if isinstance(value, dict):
            return _entry_readiness.document_digest(value)
    except Exception:  # noqa: BLE001
        return None
    return None


def _seam_resolution_digest(value: Any) -> str | None:
    try:
        if isinstance(value, dict):
            return _package_resolver.document_digest(value)
    except Exception:  # noqa: BLE001
        return None
    return None


def _seam_stop(
    *,
    entry_gate_decision_digest,
    readiness_report_digest,
    package_resolution_digest,
    gate_code,
) -> dict[str, Any]:
    return {
        "kind": _SEAM_KIND,
        "schema_version": _SEAM_SCHEMA_VERSION,
        "route": "stop",
        "entry_gate_decision_digest": entry_gate_decision_digest,
        "readiness_report_digest": readiness_report_digest,
        "package_resolution_digest": package_resolution_digest,
        "gate_code": gate_code,
        "preparation_ack": None,
    }


def prepare_selection_with_entry_gate(
    *,
    resolved_config: dict[str, Any],
    limit: int,
    readiness_report: dict[str, Any],
    entry_gate_decision: dict[str, Any],
    package_resolution: dict[str, Any],
    registries: dict[str, Any] | None = None,
    batch_id: str | None = None,
    on_manifest_frozen: ClaimProbe | None = None,
) -> dict[str, Any]:
    """Inactive package-aware entry seam (P3b1b2).

    Hard-ordered entry surface that validates the readiness / decision /
    package-resolution triple BEFORE any call to existing
    :func:`prepare_selection`, TaskSource probe/select, freeze, claim, or
    worker access. Every current v1 resolution is inactive / non-executable,
    so the seam always stops at ``platform_package_inactive`` (or earlier
    deterministic stop) for valid v1 inputs.

    Hard order:

    1. Use the existing internal registry loader when ``registries`` is None.
    2. Validate ``resolved_config`` shape (no override fields).
    3. Verify the readiness report and entry-gate decision documents.
    4. Bind decision -> readiness digest; readiness -> resolved-config digest;
       readiness package descriptor digest -> resolution; and config platform /
       profile -> resolution.
    5. Non-``select-new`` decisions stop immediately (no package-aware probe,
       no TaskSource access).
    6. ``select-new`` requires report status ``ready``; otherwise stop.
    7. Invoke the package-aware gate. Current v1 always fails inactive, so
       the seam always stops; only a future ok gate may call existing
       :func:`prepare_selection` unchanged.

    Returns the canonical inactive-entry-seam result. The result never embeds
    full input documents, paths, acks, prompts, commands, secrets, tokens, or
    credentials.
    """
    decision_digest = _seam_digest(entry_gate_decision)
    report_digest = _seam_digest(readiness_report)
    resolution_digest = _seam_resolution_digest(package_resolution)

    # 1. Load only internal registries when none supplied.
    loaded_registries: dict[str, Any] | None
    if registries is None:
        try:
            loaded_registries = icp_common.load_registries()
        except icp_common.ConfigError as exc:
            return _seam_stop(
                entry_gate_decision_digest=decision_digest,
                readiness_report_digest=report_digest,
                package_resolution_digest=resolution_digest,
                gate_code=exc.code,
            )
    else:
        loaded_registries = registries

    # 2. Validate resolved-config shape (also rejects override keys).
    validation = _validate_resolved(resolved_config)
    if validation is not None:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=validation.code,
        )

    # 3-4. Verify + bind the readiness / decision / resolution triple. Any
    # failure here stops deterministically with ``invalid_input``.
    try:
        _entry_readiness.verify_readiness_report(readiness_report)
        _entry_readiness.verify_entry_gate_decision(entry_gate_decision)
        _package_resolver.verify_resolution(package_resolution)
    except Exception:  # noqa: BLE001
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=_SEAM_CODE_INVALID_INPUT,
        )

    if entry_gate_decision.get("readiness_report_digest") != report_digest:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=_SEAM_CODE_INVALID_INPUT,
        )

    expected_resolved_config_digest = _entry_readiness.document_digest(resolved_config)
    if readiness_report.get("resolved_config_digest") != expected_resolved_config_digest:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=_SEAM_CODE_INVALID_INPUT,
        )

    if (
        readiness_report.get("package_descriptor_digest")
        != package_resolution.get("package_descriptor_digest")
    ):
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=_SEAM_CODE_INVALID_INPUT,
        )

    if (
        package_resolution.get("platform_id") != resolved_config.get("platform")
        or package_resolution.get("profile_id") != resolved_config.get("profile")
    ):
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=_SEAM_CODE_INVALID_INPUT,
        )

    # 5. Non-select-new decisions stop immediately, before any package-aware
    # probe or TaskSource access. The decision literal is a controlled safe
    # id, so it is a valid gate_code.
    decision_literal = entry_gate_decision.get("decision")
    if decision_literal != _SEAM_DECISION_SELECT_NEW:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=decision_literal,
        )

    # 6. select-new requires report status ``ready``.
    if readiness_report.get("status") != _SEAM_REPORT_READY:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=readiness_report.get("status"),
        )

    # 7. Invoke the package-aware gate. Current v1 always fails inactive, so
    # the seam stops here for every valid v1 input. Only a future ok gate
    # may call existing prepare_selection unchanged.
    gate = preflight_selection.support_gate_package_aware(
        resolved_config, loaded_registries, package_resolution,
    )
    if not gate.ok:
        return _seam_stop(
            entry_gate_decision_digest=decision_digest,
            readiness_report_digest=report_digest,
            package_resolution_digest=resolution_digest,
            gate_code=gate.code,
        )

    # Future-only path: only a future approved ok gate reaches existing
    # prepare_selection. Current v1 never reaches here.
    preparation_ack = prepare_selection(
        resolved_config=resolved_config,
        limit=limit,
        registries=loaded_registries,
        batch_id=batch_id,
        on_manifest_frozen=on_manifest_frozen,
    )
    return {
        "kind": _SEAM_KIND,
        "schema_version": _SEAM_SCHEMA_VERSION,
        "route": "prepare",
        "entry_gate_decision_digest": decision_digest,
        "readiness_report_digest": report_digest,
        "package_resolution_digest": resolution_digest,
        "gate_code": None,
        "preparation_ack": preparation_ack,
    }


# ---------------------------------------------------------------------------
# Failure helpers.
# ---------------------------------------------------------------------------


def _ack_fail(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


# ---------------------------------------------------------------------------
# Production CLI.
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = _OneJsonObjectArgumentParser(
        prog=SCRIPT_NAME,
        description="Hard-ordered ICP P1b selection orchestrator.",
        add_help=False,
    )
    parser.add_argument(
        "--config", required=True, help="Path to a resolved ICP run-config JSON file."
    )
    parser.add_argument(
        "--limit",
        required=True,
        type=int,
        help="Positive integer batch size.",
    )
    return parser


class _OneJsonObjectArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that surfaces CLI usage errors as one JSON object.

    Overrides ``error`` and ``exit`` so a malformed CLI invocation emits
    exactly one canonical JSON failure on stderr (no usage text, no
    traceback), preserving the P1b contract.
    """

    def error(self, message: str) -> None:  # noqa: A003 - argparse API
        raise _CLIError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0:
            return
        raise _CLIError(message or f"cli exit status {status}")


class _CLIError(SystemExit):
    """Internal signal that the CLI argv was invalid; carries a message."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.cli_message = message


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _CLIError as exc:
        # One canonical JSON object; no usage text, no traceback.
        sys.stderr.write(
            icp_common.failure_json(
                icp_common.INVALID_INPUT,
                f"invalid command-line arguments: {exc.cli_message}",
            ).decode("utf-8")
        )
        return 2
    except SystemExit as exit_:
        sys.stderr.write(
            icp_common.failure_json(
                icp_common.INVALID_INPUT, "invalid command-line arguments"
            ).decode("utf-8")
        )
        return int(exit_.code) if isinstance(exit_.code, int) else 2

    try:
        config_path = Path(args.config).expanduser()
        raw = config_path.read_bytes()
    except FileNotFoundError as exc:
        return _emit_fail(icp_common.INVALID_INPUT, f"config not found: {exc}")
    except OSError as exc:
        return _emit_fail(icp_common.INVALID_INPUT, f"cannot read config: {exc}")

    try:
        config = icp_common.decode_strict_config(raw)
    except icp_common.ConfigError as exc:
        return _emit_fail(exc.code, exc.message)

    ack = prepare_selection(resolved_config=config, limit=args.limit)
    if ack.get("ok"):
        sys.stdout.write(icp_common.canonical_json_bytes(ack).decode("utf-8"))
        return 0
    return _emit_fail(ack.get("code", icp_common.INVALID_INPUT), ack.get("message", ""))


def _emit_fail(code: str, message: str) -> int:
    sys.stderr.write(icp_common.failure_json(code, message).decode("utf-8"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
