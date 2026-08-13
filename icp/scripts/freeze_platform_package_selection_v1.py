#!/usr/bin/env python3
"""ICP P3b1b1 freeze platform package selection v1 (pure, in-memory).

Builds the canonical ``icp.platform-package-selection.v1`` bytes from
an already-verified
``icp.platform-package-resolution.v1`` and the three
adjacent artifact digests plus the four fixed producer script bytes.

P3b1b1 is **pure / in-memory**: this module performs zero
filesystem, network, environment, CLI, lock, CAS, claim, writeback,
publish, or delete operations. The selection builder is named
``freeze_*`` for the approved architecture but only builds canonical
bytes in memory; P3d owns atomic no-clobber publication.

Every selection is ``activation_state=inactive`` and
``executable=false``. The producer list has exact fixed order and
fixed basenames; no caller controls either.

P3b1a / P3b1b / P3d boundary:

* P3a owns the canonical descriptor contract.
* P3b1a owns the canonical entry-readiness contract.
* P3b1b1 (this module + the resolver + the verifier) owns the
  canonical resolution / selection / verification shapes.
* P3d (later, separately approved) owns atomic no-clobber
  publication, locking, CAS, claim / writeback, scratch cleanup, and
  platform binding / authorization / executor wiring.

This module imports only the resolver
(``platform_package_resolver_v1``) via an ordinary static private
alias (``_resolver``). No dynamic loading, no ``pathlib``
resolution, no ``sys.path`` mutation.

Public Python API (only):

* ``PlatformPackageSelectionBuildError`` -- local error class.
* ``canonical_bytes(document) -> bytes`` -- canonical UTF-8 bytes.
* ``build_selection(*, resolution, entry_readiness_report_digest,
  selection_manifest_digest, package_verification_digest,
  producer_script_bytes) -> dict``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import platform_package_resolver_v1 as _resolver

# ---------------------------------------------------------------------------
# Private schema constants.
# ---------------------------------------------------------------------------

_KIND_SELECTION = "icp.platform-package-selection.v1"
_SCHEMA_VERSION = 1
_ACTIVATION_STATE_INACTIVE = "inactive"
_ACTIVATION_EXECUTABLE = {
    _ACTIVATION_STATE_INACTIVE: False,
    "active": True,
}

# Fixed producer spec: (id, basename). Canonical order is binding;
# callers cannot reorder or rename. The basename is the fixed expected
# basename of the installed producer script; no caller controls it.
_PRODUCER_SPECS = (
    ("entry-readiness-v1", "entry_readiness_v1.py"),
    ("platform-package-resolver-v1", "platform_package_resolver_v1.py"),
    ("freeze-platform-package-selection-v1",
     "freeze_platform_package_selection_v1.py"),
    ("verify-platform-package-selection-v1",
     "verify_platform_package_selection_v1.py"),
)
_PRODUCER_IDS = tuple(spec[0] for spec in _PRODUCER_SPECS)

# Exact ordered top-level keys for the canonical selection document.
_SELECTION_KEY_ORDER = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "entry_readiness_report_digest",
    "selection_manifest_digest",
    "package_index_digest",
    "package_descriptor_digest",
    "package_verification_digest",
    "registry_digest",
    "selected_profile_digest",
    "package_module_basename",
    "package_module_sha256",
    "activation_state",
    "executable",
    "producer_script_digests",
)

# Exact ordered keys for each producer entry.
_PRODUCER_KEY_ORDER = ("id", "basename", "sha256")

# Forbidden recursive keys (exact dictionary keys) anywhere in any
# document. Mirrors the resolver's forbidden-key set verbatim.
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


class PlatformPackageSelectionBuildError(ValueError):
    """A local platform-package selection build failure.

    Raised for any shape, type, ordering, unknown-key, injection,
    drift, or producer-input violation. Never extends
    ``icp_common.ALL_ERROR_CODES``.
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


def _check_keys_exact_order(
    actual: Any, expected_order: tuple, location: str
) -> None:
    if not isinstance(actual, dict):
        raise PlatformPackageSelectionBuildError(
            f"{location}: must be an object"
        )
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise PlatformPackageSelectionBuildError(
            f"{location}: key order mismatch: "
            f"extra={extra} missing={missing}"
        )


def _reject_injection_fields(obj: Any, location: str) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key in _INJECTION_FIELD_NAMES:
                raise PlatformPackageSelectionBuildError(
                    f"forbidden injection field: {here}"
                )
            _reject_injection_fields(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_injection_fields(item, f"{location}[{i}]")


# ---------------------------------------------------------------------------
# Public API: canonical bytes.
# ---------------------------------------------------------------------------


def canonical_bytes(document: dict) -> bytes:
    """Canonical UTF-8 bytes of a document.

    Equivalent to::

        (json.dumps(document, ensure_ascii=False, indent=2,
                    sort_keys=True) + "\\n").encode("utf-8")
    """
    if not isinstance(document, dict):
        raise PlatformPackageSelectionBuildError(
            "document: must be an object"
        )
    return _canonical_json_bytes(document)


# ---------------------------------------------------------------------------
# Internal: validate producer_script_bytes mapping.
# ---------------------------------------------------------------------------


def _validate_producer_script_bytes(producer_script_bytes: Any) -> None:
    if not isinstance(producer_script_bytes, dict):
        raise PlatformPackageSelectionBuildError(
            "producer_script_bytes: must be a dict"
        )
    expected_ids = set(_PRODUCER_IDS)
    actual_ids = set(producer_script_bytes.keys())
    if actual_ids != expected_ids:
        extra = sorted(actual_ids - expected_ids)
        missing = sorted(expected_ids - actual_ids)
        raise PlatformPackageSelectionBuildError(
            f"producer_script_bytes: extra={extra} missing={missing}"
        )
    for pid in _PRODUCER_IDS:
        value = producer_script_bytes[pid]
        if not isinstance(value, (bytes, bytearray)):
            raise PlatformPackageSelectionBuildError(
                f"producer_script_bytes[{pid!r}]: must be bytes"
            )


def _build_producer_script_digests(
    producer_script_bytes: dict,
) -> list:
    """Build the canonical producer_script_digests[] list in fixed
    order with fixed basenames; SHAs are recomputed from the supplied
    bytes."""
    out: list = []
    for pid, basename in _PRODUCER_SPECS:
        sha = _sha256_bytes(bytes(producer_script_bytes[pid]))
        out.append(
            {
                "id": pid,
                "basename": basename,
                "sha256": sha,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Internal: self-verify the canonical selection shape.
# ---------------------------------------------------------------------------


def _verify_selection_invariants(selection: dict) -> None:
    if not isinstance(selection, dict):
        raise PlatformPackageSelectionBuildError(
            "selection: must be an object"
        )
    _check_keys_exact_order(selection, _SELECTION_KEY_ORDER, "selection")
    if selection["kind"] != _KIND_SELECTION:
        raise PlatformPackageSelectionBuildError(
            f"selection.kind: must be {_KIND_SELECTION!r}"
        )
    if selection["schema_version"] != _SCHEMA_VERSION:
        raise PlatformPackageSelectionBuildError(
            f"selection.schema_version: must be {_SCHEMA_VERSION!r}"
        )
    for key in (
        "entry_readiness_report_digest",
        "selection_manifest_digest",
        "package_index_digest",
        "package_descriptor_digest",
        "package_verification_digest",
        "registry_digest",
        "selected_profile_digest",
        "package_module_sha256",
    ):
        if not _is_sha256_hex(selection[key]):
            raise PlatformPackageSelectionBuildError(
                f"selection.{key}: must be SHA-256 hex (64 lowercase)"
            )
    expected_executable = _ACTIVATION_EXECUTABLE.get(selection["activation_state"])
    if expected_executable is None:
        raise PlatformPackageSelectionBuildError(
            f"selection.activation_state: must be one of "
            f"{tuple(_ACTIVATION_EXECUTABLE)!r}"
        )
    if selection["executable"] is not expected_executable:
        raise PlatformPackageSelectionBuildError(
            f"selection.executable: must be exactly {expected_executable!r}"
        )
    producers = selection["producer_script_digests"]
    if not isinstance(producers, list):
        raise PlatformPackageSelectionBuildError(
            "selection.producer_script_digests: must be a list"
        )
    if len(producers) != len(_PRODUCER_SPECS):
        raise PlatformPackageSelectionBuildError(
            f"selection.producer_script_digests: must have exactly "
            f"{len(_PRODUCER_SPECS)} entries, got {len(producers)}"
        )
    for i, (pid, basename) in enumerate(_PRODUCER_SPECS):
        row = producers[i]
        _check_keys_exact_order(
            row, _PRODUCER_KEY_ORDER,
            f"selection.producer_script_digests[{i}]",
        )
        if row["id"] != pid:
            raise PlatformPackageSelectionBuildError(
                f"selection.producer_script_digests[{i}].id: must be "
                f"{pid!r}, got {row['id']!r}"
            )
        if row["basename"] != basename:
            raise PlatformPackageSelectionBuildError(
                f"selection.producer_script_digests[{i}].basename: must "
                f"be {basename!r}, got {row['basename']!r}"
            )
        if not _is_sha256_hex(row["sha256"]):
            raise PlatformPackageSelectionBuildError(
                f"selection.producer_script_digests[{i}].sha256: must "
                f"be SHA-256 hex (64 lowercase)"
            )
    _reject_injection_fields(selection, "")


# ---------------------------------------------------------------------------
# Public API: build_selection.
# ---------------------------------------------------------------------------


def build_selection(
    *,
    resolution: dict,
    entry_readiness_report_digest: str,
    selection_manifest_digest: str,
    package_verification_digest: str,
    producer_script_bytes: dict,
) -> dict:
    """Build the canonical
    ``icp.platform-package-selection.v1`` document from an
    already-verified resolution and the three adjacent artifact
    digests plus the four fixed producer script bytes.

    Performs, in order:

    1. Verify the resolution via the resolver.
    2. Validate the three adjacent digests as bare SHA-256 hex.
    3. Validate ``producer_script_bytes``: exactly the four
       controlled IDs, each mapping to bytes.
    4. Build ``producer_script_digests[]`` in fixed order with fixed
       basenames and recomputed SHAs.
    5. Build the canonical selection document and self-verify.

    Missing / extra / reordered producer inputs, malformed adjacent
    digests, an unverified / tampered resolution, or any forbidden
    injection key fails closed.
    """
    _resolver.verify_resolution(resolution)

    for name, value in (
        ("entry_readiness_report_digest", entry_readiness_report_digest),
        ("selection_manifest_digest", selection_manifest_digest),
        ("package_verification_digest", package_verification_digest),
    ):
        if not _is_sha256_hex(value):
            raise PlatformPackageSelectionBuildError(
                f"{name}: must be SHA-256 hex (64 lowercase)"
            )

    _validate_producer_script_bytes(producer_script_bytes)
    producer_digests = _build_producer_script_digests(producer_script_bytes)

    selection = {
        "kind": _KIND_SELECTION,
        "schema_version": _SCHEMA_VERSION,
        "platform_id": resolution["platform_id"],
        "profile_id": resolution["profile_id"],
        "entry_readiness_report_digest": entry_readiness_report_digest,
        "selection_manifest_digest": selection_manifest_digest,
        "package_index_digest": resolution["package_index_digest"],
        "package_descriptor_digest": resolution["package_descriptor_digest"],
        "package_verification_digest": package_verification_digest,
        "registry_digest": resolution["registry_digest"],
        "selected_profile_digest": resolution["selected_profile_digest"],
        "package_module_basename": resolution["package_module_basename"],
        "package_module_sha256": resolution["package_module_sha256"],
        "activation_state": resolution["activation_state"],
        "executable": resolution["executable"],
        "producer_script_digests": producer_digests,
    }
    _verify_selection_invariants(selection)
    return selection
