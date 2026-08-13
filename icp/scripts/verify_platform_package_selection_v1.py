#!/usr/bin/env python3
"""ICP P3b1b1 verify platform package selection v1 (pure, in-memory).

Verifies a canonical
``icp.platform-package-selection.v1`` document against an
already-verified
``icp.platform-package-resolution.v1``, the three expected
adjacent artifact digests, and the four fixed producer script bytes,
then returns the canonical
``icp.platform-package-selection-verification.v1`` document.

P3b1b1 is **pure / in-memory**: this module performs zero
filesystem, network, environment, CLI, lock, CAS, claim, writeback,
publish, or delete operations. The verifier never reads producer
files itself (the caller supplies their bytes) and never publishes
anything.

Every verification is ``verified=true`` only when every copied field
and producer digest is identical to its recomputed value, the
selection's ``activation_state=inactive`` and ``executable=false``,
and the three adjacent artifact digests match the caller's expected
values.

P3b1a / P3b1b / P3d boundary:

* P3a owns the canonical descriptor contract.
* P3b1a owns the canonical entry-readiness contract.
* P3b1b1 (this module + the resolver + the freezer) owns the
  canonical resolution / selection / verification shapes.
* P3d (later, separately approved) owns atomic no-clobber
  publication, locking, CAS, claim / writeback, scratch cleanup, and
  platform binding / authorization / executor wiring.

This module imports only the resolver and the freezer via ordinary
static private aliases. No dynamic loading, no ``pathlib``
resolution, no ``sys.path`` mutation.

Public Python API (only):

* ``PlatformPackageSelectionVerificationError`` -- local error class.
* ``document_digest(document) -> str`` -- canonical SHA-256.
* ``verify_selection(document, *, resolution,
  expected_entry_readiness_report_digest,
  expected_selection_manifest_digest,
  expected_package_verification_digest, producer_script_bytes) -> dict``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import freeze_platform_package_selection_v1 as _freezer
import platform_package_resolver_v1 as _resolver

# ---------------------------------------------------------------------------
# Private schema constants.
# ---------------------------------------------------------------------------

_KIND_VERIFICATION = "icp.platform-package-selection-verification.v1"
_SCHEMA_VERSION = 1

_VERIFICATION_KEY_ORDER = (
    "kind",
    "schema_version",
    "selection_digest",
    "platform_id",
    "profile_id",
    "verified",
)

# Mirrored selection-key order (must match the freezer's binding
# canonical shape).
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

# Mirrored producer spec / key order (must match the freezer's binding
# canonical shape).
_PRODUCER_SPECS = (
    ("entry-readiness-v1", "entry_readiness_v1.py"),
    ("platform-package-resolver-v1", "platform_package_resolver_v1.py"),
    ("freeze-platform-package-selection-v1",
     "freeze_platform_package_selection_v1.py"),
    ("verify-platform-package-selection-v1",
     "verify_platform_package_selection_v1.py"),
)
_PRODUCER_IDS = tuple(spec[0] for spec in _PRODUCER_SPECS)
_PRODUCER_KEY_ORDER = ("id", "basename", "sha256")

# Forbidden recursive keys (exact dictionary keys) anywhere in any
# document. Mirrors the resolver's and the freezer's forbidden-key set
# verbatim.
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


class PlatformPackageSelectionVerificationError(ValueError):
    """A local platform-package selection verification failure.

    Raised for any shape, type, ordering, unknown-key, injection,
    copied-field drift, producer-digest drift / tamper, adjacent
    digest drift, or activation / executable tamper. Never extends
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
        raise PlatformPackageSelectionVerificationError(
            f"{location}: must be an object"
        )
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise PlatformPackageSelectionVerificationError(
            f"{location}: key order mismatch: "
            f"extra={extra} missing={missing}"
        )


def _reject_injection_fields(obj: Any, location: str) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key in _INJECTION_FIELD_NAMES:
                raise PlatformPackageSelectionVerificationError(
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
    """
    if not isinstance(document, dict):
        raise PlatformPackageSelectionVerificationError(
            "document: must be an object"
        )
    return _sha256_bytes(_canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Internal: validate producer_script_bytes mapping.
# ---------------------------------------------------------------------------


def _validate_producer_script_bytes(producer_script_bytes: Any) -> None:
    if not isinstance(producer_script_bytes, dict):
        raise PlatformPackageSelectionVerificationError(
            "producer_script_bytes: must be a dict"
        )
    expected_ids = set(_PRODUCER_IDS)
    actual_ids = set(producer_script_bytes.keys())
    if actual_ids != expected_ids:
        extra = sorted(actual_ids - expected_ids)
        missing = sorted(expected_ids - actual_ids)
        raise PlatformPackageSelectionVerificationError(
            f"producer_script_bytes: extra={extra} missing={missing}"
        )
    for pid in _PRODUCER_IDS:
        value = producer_script_bytes[pid]
        if not isinstance(value, (bytes, bytearray)):
            raise PlatformPackageSelectionVerificationError(
                f"producer_script_bytes[{pid!r}]: must be bytes"
            )


# ---------------------------------------------------------------------------
# Public API: verify_selection.
# ---------------------------------------------------------------------------


def verify_selection(
    document: dict,
    *,
    resolution: dict,
    expected_entry_readiness_report_digest: str,
    expected_selection_manifest_digest: str,
    expected_package_verification_digest: str,
    producer_script_bytes: dict,
) -> dict:
    """Verify a canonical
    ``icp.platform-package-selection.v1`` document and return the
    canonical
    ``icp.platform-package-selection-verification.v1`` document.

    Performs, in order:

    1. Verify the resolution via the resolver.
    2. Verify the selection document shape (exact ordered keys,
       kind, schema_version, all digest fields well-formed,
       activation_state=inactive, executable=false).
    3. Recompute every copied resolution field and require equality
       with the selection's recorded values.
    4. Recompute every producer digest from ``producer_script_bytes``
       and require order / id / basename / sha256 equality with the
       selection's recorded producer rows.
    5. Compare the three expected adjacent artifact digests with the
       selection's recorded values.
    6. Recompute the canonical ``selection_digest``.
    7. Build and return the canonical verification document.

    Shape violations, copied-field drift, producer digest drift /
    tamper / reorder / missing / extra / unknown-field, adjacent
    digest drift, activation / executable tamper, or any forbidden
    injection key fails closed.
    """
    # 1. Verify the resolution.
    _resolver.verify_resolution(resolution)

    # 2. Validate producer_script_bytes (must be supplied exactly and
    #    as bytes).
    _validate_producer_script_bytes(producer_script_bytes)

    # 3. Verify the three expected adjacent digests.
    for name, value in (
        ("expected_entry_readiness_report_digest",
         expected_entry_readiness_report_digest),
        ("expected_selection_manifest_digest",
         expected_selection_manifest_digest),
        ("expected_package_verification_digest",
         expected_package_verification_digest),
    ):
        if not _is_sha256_hex(value):
            raise PlatformPackageSelectionVerificationError(
                f"{name}: must be SHA-256 hex (64 lowercase)"
            )

    # 4. Selection shape: exact ordered keys.
    if not isinstance(document, dict):
        raise PlatformPackageSelectionVerificationError(
            "selection: must be an object"
        )
    _check_keys_exact_order(document, _SELECTION_KEY_ORDER, "selection")
    if document["kind"] != _freezer._KIND_SELECTION:
        raise PlatformPackageSelectionVerificationError(
            f"selection.kind: must be "
            f"{_freezer._KIND_SELECTION!r}, got {document['kind']!r}"
        )
    if document["schema_version"] != _freezer._SCHEMA_VERSION:
        raise PlatformPackageSelectionVerificationError(
            f"selection.schema_version: must be "
            f"{_freezer._SCHEMA_VERSION!r}, "
            f"got {document['schema_version']!r}"
        )

    # 5. All digest fields well-formed.
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
        if not _is_sha256_hex(document[key]):
            raise PlatformPackageSelectionVerificationError(
                f"selection.{key}: must be SHA-256 hex (64 lowercase)"
            )

    # 6. Activation / executable invariants.
    expected_executable = _freezer._ACTIVATION_EXECUTABLE.get(
        document["activation_state"]
    )
    if expected_executable is None:
        raise PlatformPackageSelectionVerificationError(
            f"selection.activation_state: must be one of "
            f"{tuple(_freezer._ACTIVATION_EXECUTABLE)!r}, "
            f"got {document['activation_state']!r}"
        )
    if document["executable"] is not expected_executable:
        raise PlatformPackageSelectionVerificationError(
            f"selection.executable: must be exactly {expected_executable!r}, "
            f"got {document['executable']!r}"
        )

    # 7. Copied resolution fields must match exactly.
    for key in (
        "platform_id",
        "profile_id",
        "package_index_digest",
        "package_descriptor_digest",
        "registry_digest",
        "selected_profile_digest",
        "package_module_basename",
        "package_module_sha256",
    ):
        if document[key] != resolution[key]:
            raise PlatformPackageSelectionVerificationError(
                f"selection.{key}: drift: selection={document[key]!r} "
                f"resolution={resolution[key]!r}"
            )

    # 8. Producer rows: exact count, order, id, basename, sha256.
    producers = document["producer_script_digests"]
    if not isinstance(producers, list):
        raise PlatformPackageSelectionVerificationError(
            "selection.producer_script_digests: must be a list"
        )
    if len(producers) != len(_PRODUCER_SPECS):
        raise PlatformPackageSelectionVerificationError(
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
            raise PlatformPackageSelectionVerificationError(
                f"selection.producer_script_digests[{i}].id: must be "
                f"{pid!r}, got {row['id']!r}"
            )
        if row["basename"] != basename:
            raise PlatformPackageSelectionVerificationError(
                f"selection.producer_script_digests[{i}].basename: must "
                f"be {basename!r}, got {row['basename']!r}"
            )
        if not _is_sha256_hex(row["sha256"]):
            raise PlatformPackageSelectionVerificationError(
                f"selection.producer_script_digests[{i}].sha256: must "
                f"be SHA-256 hex (64 lowercase)"
            )
        expected_sha = _sha256_bytes(
            bytes(producer_script_bytes[pid])
        )
        if row["sha256"] != expected_sha:
            raise PlatformPackageSelectionVerificationError(
                f"selection.producer_script_digests[{i}].sha256: drift: "
                f"selection={row['sha256']} recomputed={expected_sha}"
            )

    # 9. Adjacent digests must match the caller's expected values.
    if document["entry_readiness_report_digest"] != \
            expected_entry_readiness_report_digest:
        raise PlatformPackageSelectionVerificationError(
            "selection.entry_readiness_report_digest: drift: selection="
            f"{document['entry_readiness_report_digest']} expected="
            f"{expected_entry_readiness_report_digest}"
        )
    if document["selection_manifest_digest"] != \
            expected_selection_manifest_digest:
        raise PlatformPackageSelectionVerificationError(
            "selection.selection_manifest_digest: drift: selection="
            f"{document['selection_manifest_digest']} expected="
            f"{expected_selection_manifest_digest}"
        )
    if document["package_verification_digest"] != \
            expected_package_verification_digest:
        raise PlatformPackageSelectionVerificationError(
            "selection.package_verification_digest: drift: selection="
            f"{document['package_verification_digest']} expected="
            f"{expected_package_verification_digest}"
        )

    # 10. Final defense-in-depth: no forbidden injection key anywhere.
    _reject_injection_fields(document, "")

    # 11. Recompute canonical selection_digest and build verification.
    selection_digest = document_digest(document)
    verification = {
        "kind": _KIND_VERIFICATION,
        "schema_version": _SCHEMA_VERSION,
        "selection_digest": selection_digest,
        "platform_id": document["platform_id"],
        "profile_id": document["profile_id"],
        "verified": True,
    }
    _check_keys_exact_order(
        verification, _VERIFICATION_KEY_ORDER, "verification"
    )
    return verification
