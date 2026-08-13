#!/usr/bin/env python3
"""ICP P3b1b1 platform package resolver v1 (pure, in-memory, inactive).

Maps an in-memory ``(platform_id, profile_id)`` selection to a fixed
package index row, recomputes every digest from supplied live inputs,
and emits the canonical
``icp.platform-package-resolution.v1`` document.

P3b1b1 is **pure / in-memory**: this module performs zero
filesystem, network, environment, CLI, lock, CAS, claim, writeback,
publish, or delete operations. Every resolution is
``activation_state=inactive`` and ``executable=false``. The caller
supplies validated in-memory documents / bytes; the resolver imports
no package wrapper, no descriptor loader callback, no registry import
path, no command, and no executable payload.

The resolver is **generic**. It contains no platform / toolchain /
language conditional or literal (the test suite enforces this).
Any platform row that satisfies the canonical index schema is
admissible.

P3b1a / P3b1b / P3d boundary:

* P3a owns the canonical platform-package descriptor contract
  (``platforms/platform_package_contract_v1.py``).
* P3b1a owns the canonical entry-readiness / active-first entry gate
  pure contract (``entry_readiness_v1.py``).
* P3b1b1 (this module) owns the fixed package resolver + canonical
  resolution shape.
* P3b1b2 (later, separately approved) owns the canonical selection
  builder + verifier (``freeze_platform_package_selection_v1.py`` /
  ``verify_platform_package_selection_v1.py``).
* P3d (later, separately approved) owns atomic no-clobber
  publication, locking, CAS, claim / writeback, scratch cleanup, and
  platform binding / authorization / executor wiring.

This module imports only the platform-neutral P3a descriptor contract
(``platforms/platform_package_contract_v1.py``) via an ordinary static
private alias (``_package_contract``). No dynamic loading, no
``pathlib`` resolution, no ``sys.path`` mutation.Public Python API (only):

* ``PlatformPackageResolverError`` -- local error class.
* ``document_digest(document) -> str`` -- canonical SHA-256.
* ``verify_package_index(document) -> None``.
* ``verify_resolution(document) -> None``.
* ``resolve_package(*, platform_id, profile_id, registries,
  package_index, package_descriptor, package_module_bytes) -> dict``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Ordinary static import of the one allowed platform-neutral local
# contract module. The module must import cleanly when ``icp/scripts``
# is on ``PYTHONPATH`` (the normal script execution context); no
# dynamic loading, no ``sys.path`` mutation, no ``pathlib``-based
# dependency resolution is permitted.
from platforms import platform_package_contract_v1 as _package_contract

# ---------------------------------------------------------------------------
# Private schema constants.
# ---------------------------------------------------------------------------

_KIND_INDEX = "icp.platform-packages-index.v1"
_KIND_RESOLUTION = "icp.platform-package-resolution.v1"
_SCHEMA_VERSION = 1

# Exact top-level key orders.
_INDEX_KEY_ORDER = ("kind", "schema_version", "packages")
_INDEX_ROW_KEY_ORDER = (
    "platform_id",
    "profile_id",
    "package_module_basename",
    "package_module_sha256",
    "package_descriptor_digest",
)
_RESOLUTION_KEY_ORDER = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "package_module_basename",
    "package_module_sha256",
    "package_index_digest",
    "package_descriptor_digest",
    "registry_digest",
    "selected_profile_digest",
    "activation_state",
    "executable",
)

# Forbidden recursive keys (exact dictionary keys) anywhere in any
# document. Rejection is by exact key only; legitimate identifiers
# that merely contain a forbidden substring (e.g. ``design_url_handler``)
# are NOT rejected.
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

# Lowercase ASCII letters / digits / `.` / `_` / `-`; non-empty; length
# <= 128. Matches the P3b1a / P3a2 controlled safe-ID rule.
_SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")


class PlatformPackageResolverError(ValueError):
    """A local platform-package resolver validation / resolution failure.

    Raised for any shape, type, enum, ordering, duplicate, unknown-key,
    injection, identity, derivation, or content violation. Never
    extends ``icp_common.ALL_ERROR_CODES``.
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


def _is_safe_basename(name: Any) -> bool:
    """A safe Python module basename: non-empty string, no path
    separators, no NUL, not ``.`` / ``..``, ends with ``.py``."""
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    if name in {".", ".."}:
        return False
    return name.endswith(".py")


def _check_keys_exact_order(
    actual: Any, expected_order: tuple, location: str
) -> None:
    if not isinstance(actual, dict):
        raise PlatformPackageResolverError(
            f"{location}: must be an object"
        )
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise PlatformPackageResolverError(
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
                raise PlatformPackageResolverError(
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
        raise PlatformPackageResolverError("document: must be an object")
    return _sha256_bytes(_canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Public API: package-index verifier.
# ---------------------------------------------------------------------------


def _verify_index_row(row: Any, here: str) -> None:
    _check_keys_exact_order(row, _INDEX_ROW_KEY_ORDER, here)
    if not _is_safe_id(row["platform_id"]):
        raise PlatformPackageResolverError(
            f"{here}.platform_id: not a controlled safe ID"
        )
    if not _is_safe_id(row["profile_id"]):
        raise PlatformPackageResolverError(
            f"{here}.profile_id: not a controlled safe ID"
        )
    if not _is_safe_basename(row["package_module_basename"]):
        raise PlatformPackageResolverError(
            f"{here}.package_module_basename: not a safe Python module "
            f"basename"
        )
    if not _is_sha256_hex(row["package_module_sha256"]):
        raise PlatformPackageResolverError(
            f"{here}.package_module_sha256: must be SHA-256 hex "
            f"(64 lowercase)"
        )
    if not _is_sha256_hex(row["package_descriptor_digest"]):
        raise PlatformPackageResolverError(
            f"{here}.package_descriptor_digest: must be SHA-256 hex "
            f"(64 lowercase)"
        )


def verify_package_index(document: dict) -> None:
    """Strict fail-closed validation of the canonical package index.

    Raises :class:`PlatformPackageResolverError` on any violation;
    returns ``None`` on success. Performs no I/O.
    """
    if not isinstance(document, dict):
        raise PlatformPackageResolverError("package_index: must be an object")
    _check_keys_exact_order(document, _INDEX_KEY_ORDER, "package_index")
    if document["kind"] != _KIND_INDEX:
        raise PlatformPackageResolverError(
            f"package_index.kind: must be {_KIND_INDEX!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise PlatformPackageResolverError(
            f"package_index.schema_version: must be "
            f"{_SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    packages = document["packages"]
    if not isinstance(packages, list) or not packages:
        raise PlatformPackageResolverError(
            "package_index.packages: must be a non-empty list"
        )
    last_key: tuple | None = None
    seen_keys: set = set()
    for i, row in enumerate(packages):
        here = f"package_index.packages[{i}]"
        _verify_index_row(row, here)
        key = (row["platform_id"], row["profile_id"])
        if key in seen_keys:
            raise PlatformPackageResolverError(
                f"{here}: duplicate (platform_id, profile_id): {key!r}"
            )
        seen_keys.add(key)
        if last_key is not None and key <= last_key:
            raise PlatformPackageResolverError(
                f"{here}: not strictly sorted by "
                f"(platform_id, profile_id): {key!r}"
            )
        last_key = key
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: resolution verifier.
# ---------------------------------------------------------------------------


def verify_resolution(document: dict) -> None:
    """Strict fail-closed validation of a resolution document.

    Raises :class:`PlatformPackageResolverError` on any violation;
    returns ``None`` on success.
    """
    if not isinstance(document, dict):
        raise PlatformPackageResolverError("resolution: must be an object")
    _check_keys_exact_order(document, _RESOLUTION_KEY_ORDER, "resolution")
    if document["kind"] != _KIND_RESOLUTION:
        raise PlatformPackageResolverError(
            f"resolution.kind: must be {_KIND_RESOLUTION!r}, "
            f"got {document['kind']!r}"
        )
    if document["schema_version"] != _SCHEMA_VERSION:
        raise PlatformPackageResolverError(
            f"resolution.schema_version: must be "
            f"{_SCHEMA_VERSION!r}, got {document['schema_version']!r}"
        )
    if not _is_safe_id(document["platform_id"]):
        raise PlatformPackageResolverError(
            "resolution.platform_id: not a controlled safe ID"
        )
    if not _is_safe_id(document["profile_id"]):
        raise PlatformPackageResolverError(
            "resolution.profile_id: not a controlled safe ID"
        )
    if not _is_safe_basename(document["package_module_basename"]):
        raise PlatformPackageResolverError(
            "resolution.package_module_basename: not a safe Python "
            f"module basename"
        )
    for key in (
        "package_module_sha256",
        "package_index_digest",
        "package_descriptor_digest",
        "registry_digest",
        "selected_profile_digest",
    ):
        if not _is_sha256_hex(document[key]):
            raise PlatformPackageResolverError(
                f"resolution.{key}: must be SHA-256 hex (64 lowercase)"
            )
    activation_executable = {
        _package_contract.ACTIVATION_STATE_INACTIVE: False,
        "active": True,
    }
    expected_executable = activation_executable.get(document["activation_state"])
    if expected_executable is None:
        raise PlatformPackageResolverError(
            f"resolution.activation_state: must be one of "
            f"{tuple(activation_executable)!r}, "
            f"got {document['activation_state']!r}"
        )
    if document["executable"] is not expected_executable:
        raise PlatformPackageResolverError(
            f"resolution.executable: must be exactly {expected_executable!r}, "
            f"got {document['executable']!r}"
        )
    _reject_injection_fields(document, "")


# ---------------------------------------------------------------------------
# Public API: resolve_package.
# ---------------------------------------------------------------------------


def resolve_package(
    *,
    platform_id: str,
    profile_id: str,
    registries: dict,
    package_index: dict,
    package_descriptor: dict,
    package_module_bytes: bytes,
) -> dict:
    """Resolve a fixed package index row for ``(platform_id,
    profile_id)`` and return the canonical
    ``icp.platform-package-resolution.v1`` document.

    Performs, in order:

    1. Validate scalar inputs (safe platform / profile IDs, dict
       registry, bytes-like module bytes).
    2. Verify the index via :func:`verify_package_index` and the
       descriptor via ``platform_package_contract_v1.validate_descriptor``.
    3. Require the descriptor's platform / profile to match the
       request.
    4. Recompute descriptor / module SHA / index digests from live
       inputs and require the index row's recorded values to match.
    5. Recompute the current registry digest and selected-profile
       digest via the P3a contract and require them to match the
       descriptor.
    6. Require the descriptor ``activation_state=inactive`` and
       ``executable=false``.
    7. Build the canonical resolution and self-verify before return.

    Every resolution is ``activation_state=inactive`` and
    ``executable=False``. Unknown platform / profile, duplicate index
    row, index / module / descriptor / registry / profile drift,
    active / executable descriptor, invalid bytes, or any schema /
    order violation fails closed.
    """
    # 1. Scalar input validation.
    if not _is_safe_id(platform_id):
        raise PlatformPackageResolverError(
            "platform_id: not a controlled safe ID"
        )
    if not _is_safe_id(profile_id):
        raise PlatformPackageResolverError(
            "profile_id: not a controlled safe ID"
        )
    if not isinstance(registries, dict):
        raise PlatformPackageResolverError("registries: must be an object")
    if not isinstance(package_module_bytes, (bytes, bytearray)):
        raise PlatformPackageResolverError(
            "package_module_bytes: must be bytes"
        )

    # 2. Verify index + descriptor shape via the platform-neutral P3a
    # contract.
    verify_package_index(package_index)
    _package_contract.validate_descriptor(package_descriptor)

    # 3. Descriptor platform / profile must match the request.
    if package_descriptor["platform_id"] != platform_id:
        raise PlatformPackageResolverError(
            f"descriptor.platform_id mismatch: descriptor="
            f"{package_descriptor['platform_id']!r} "
            f"request={platform_id!r}"
        )
    if package_descriptor["profile_id"] != profile_id:
        raise PlatformPackageResolverError(
            f"descriptor.profile_id mismatch: descriptor="
            f"{package_descriptor['profile_id']!r} "
            f"request={profile_id!r}"
        )

    # 4. Recompute live module SHA / descriptor digest / index digest
    # from supplied inputs and require the index row to match.
    module_sha = _sha256_bytes(bytes(package_module_bytes))
    package_descriptor_digest = _package_contract.compute_descriptor_digest(
        package_descriptor
    )
    package_index_digest = document_digest(package_index)

    matches = [
        row
        for row in package_index["packages"]
        if row["platform_id"] == platform_id
        and row["profile_id"] == profile_id
    ]
    if len(matches) == 0:
        raise PlatformPackageResolverError(
            f"package_index: no row for "
            f"(platform_id={platform_id!r}, profile_id={profile_id!r})"
        )
    if len(matches) > 1:
        raise PlatformPackageResolverError(
            f"package_index: duplicate rows for "
            f"(platform_id={platform_id!r}, profile_id={profile_id!r})"
        )
    row = matches[0]
    if row["package_module_sha256"] != module_sha:
        raise PlatformPackageResolverError(
            f"package_module_sha256 drift: index="
            f"{row['package_module_sha256']} live={module_sha}"
        )
    if row["package_descriptor_digest"] != package_descriptor_digest:
        raise PlatformPackageResolverError(
            f"package_descriptor_digest drift: index="
            f"{row['package_descriptor_digest']} "
            f"live={package_descriptor_digest}"
        )

    # 5. Recompute registry / selected-profile digests and require
    # equality with the descriptor.
    registry_digest = _package_contract.compute_registry_digest(registries)
    selected_profile_digest = _package_contract.compute_selected_profile_digest(
        registries, platform_id, profile_id
    )
    if package_descriptor["registry_digest"] != registry_digest:
        raise PlatformPackageResolverError(
            f"registry_digest drift: descriptor="
            f"{package_descriptor['registry_digest']} "
            f"live={registry_digest}"
        )
    if package_descriptor["selected_profile_digest"] != selected_profile_digest:
        raise PlatformPackageResolverError(
            f"selected_profile_digest drift: descriptor="
            f"{package_descriptor['selected_profile_digest']} "
            f"live={selected_profile_digest}"
        )

    # 7. Build canonical resolution and self-verify.
    resolution = {
        "kind": _KIND_RESOLUTION,
        "schema_version": _SCHEMA_VERSION,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "package_module_basename": row["package_module_basename"],
        "package_module_sha256": module_sha,
        "package_index_digest": package_index_digest,
        "package_descriptor_digest": package_descriptor_digest,
        "registry_digest": registry_digest,
        "selected_profile_digest": selected_profile_digest,
        "activation_state": package_descriptor["activation_state"],
        "executable": package_descriptor["executable"],
    }
    verify_resolution(resolution)
    return resolution
