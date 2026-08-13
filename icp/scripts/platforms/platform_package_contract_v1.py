#!/usr/bin/env python3
"""ICP P3a PlatformPackage descriptor contract v1 (platform-neutral).

Pure-data validator for the canonical
``icp.platform-package-descriptor.v1`` descriptor shape. This module
contains **no** platform-specific or toolchain-specific literal,
assumption, command, artifact name, or conditional branch. The only
platform-ish tokens in source are the four canonical
``ACTUAL_SOURCE_TYPES`` capture-class enum values, which are shared
policy, not a platform tool or command name.

Public Python API:

* ``validate_descriptor(descriptor) -> None`` — strict fail-closed
  shape, type, enum, ordered-key, duplicate-key, unknown-key, and
  forbidden-field validation. Returns ``None`` on success; raises
  :class:`PlatformPackageDescriptorError` on any violation. Performs no
  I/O.
* ``compute_descriptor_digest(descriptor) -> str`` — canonical SHA-256
  of the descriptor. The descriptor itself carries no self-referential
  digest.
* ``compute_registry_digest(registry) -> str`` — canonical SHA-256 of a
  registry dict. Package wrappers recompute this from live fixed
  registry bytes and require equality with
  ``descriptor["registry_digest"]``.
* ``compute_selected_profile_digest(registry, platform_id, profile_id)
  -> str`` — canonical SHA-256 of the selected platform / profile block
  from a registry dict.

Locked boundaries:

* Platform-neutral. No ``if platform == ...`` branch, no optional
  field union keyed on platform, no free module path, no free command,
  no per-toolchain literal.
* No CLI, no dynamic module paths, no subprocess, no network, no
  writes, no import-time I/O, no activation override, no registry
  mutation, no selection, no claiming, no worker launch.
* ``profile_id`` must be a non-empty string (``null`` is rejected).
* ``implementation_state`` is exactly ``implemented`` /
  ``not-implemented``; it is independent from the legacy migration
  labels used by the earlier platform-adapter descriptor.
* ``actual_source_types`` accepts only the four canonical
  ``browser_screenshot`` / ``simulator_screenshot`` /
  ``emulator_screenshot`` / ``physical_device_screenshot`` capture-class
  enum values; ``reference``, ``design_image``, ``reference_image``, and
  ``design`` are rejected.
* Entry requirements carry only controlled IDs; never accept arbitrary
  commands, argv, environment maps, shell fragments, prompts,
  filesystem paths, secret values, activation overrides, or free text.
* Only the Python standard library is used.

Local error class is :class:`PlatformPackageDescriptorError`; it never
extends ``icp_common.ALL_ERROR_CODES``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

KIND_DESCRIPTOR = "icp.platform-package-descriptor.v1"
SCHEMA_VERSION = 1
ACTIVATION_STATE_INACTIVE = "inactive"
_ACTIVATION_EXECUTABLE = {
    ACTIVATION_STATE_INACTIVE: False,
    "active": True,
}

# Six component roles, in this exact order.
COMPONENT_ROLES = (
    "descriptor",
    "project_preflight",
    "operation_plans",
    "binding",
    "authorization",
    "executor",
)

# Nine operation port IDs, in this exact order. These match the
# settled registry operation list verbatim and are platform-neutral.
PORT_IDS = (
    "project_preflight",
    "visible_codegen",
    "fixture_codegen",
    "trace_harness",
    "packaging",
    "test_runner",
    "runtime_capture",
    "project_gates",
    "fan_in",
)

# ``capability_state`` controlled vocabulary (matches the registry).
CAPABILITY_STATES = (
    "required",
    "optional-with-shared-policy",
    "unsupported",
)

# ``implementation_state`` controlled vocabulary. v1 values only; this
# does NOT reuse the legacy P2c ``legacy-mapped`` / ``new-port-required``
# migration labels.
IMPLEMENTATION_STATES = (
    "implemented",
    "not-implemented",
)

# Entry-requirement ``owner`` controlled vocabulary.
ENTRY_REQUIREMENT_OWNERS = (
    "user",
    "source",
    "environment",
    "platform",
)

# ``actual_source_types`` controlled vocabulary: the only four
# canonical capture-class enum values allowed in shared contract.
# Reference / design image types are explicitly forbidden.
ACTUAL_SOURCE_TYPES = (
    "browser_screenshot",
    "simulator_screenshot",
    "emulator_screenshot",
    "physical_device_screenshot",
)

# Reference / design image tokens that must never appear as an actual
# source type. Listed explicitly so future enum growth does not silently
# re-admit them.
_FORBIDDEN_ACTUAL_SOURCE_TYPES = frozenset(
    {
        "reference",
        "reference_image",
        "design",
        "design_image",
        "design_screenshot",
    }
)

# Controlled task / design source IDs. These are the registry's
# cross-platform source vocabulary, not platform toolchain literals.
ALLOWED_TASK_SOURCE_IDS = ("csv",)
ALLOWED_DESIGN_SOURCE_IDS = ("lanhu-figma",)

# Exact top-level key order for the canonical descriptor.
TOP_LEVEL_KEY_ORDER = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "activation_state",
    "executable",
    "registry_digest",
    "selected_profile_digest",
    "supported_task_sources",
    "supported_design_sources",
    "actual_source_types",
    "entry_requirements",
    "components",
    "ports",
)

# Exact entry-requirement key order.
ENTRY_REQUIREMENT_KEY_ORDER = (
    "id",
    "owner",
    "required",
    "sensitive",
    "probe_id",
    "accepted_shape_id",
    "remediation_id",
)

# Exact component key order.
COMPONENT_KEY_ORDER = (
    "role",
    "module_basename",
    "module_sha256",
    "contract_kind",
    "public_api",
)

# Exact port key order.
PORT_KEY_ORDER = (
    "id",
    "capability_state",
    "implementation_state",
    "provider_component_role",
    "artifact_contracts",
)

# Forbidden injection field names anywhere in the descriptor. These
# would re-introduce an executable / injection surface.
_INJECTION_FIELD_NAMES = frozenset(
    {
        "command",
        "argv",
        "shell",
        "interpreter",
        "env",
        "runner",
        "args",
        "program",
        "cmd",
        "subprocess",
        "exec",
        "run",
        "script_path",
        "script_runner",
        "activate",
        "activation_command",
        "activation_override",
        "prompt",
        "prompt_template",
    }
)

# Characters never allowed in a controlled ID (used for entry-requirement
# IDs, probe IDs, accepted-shape IDs, remediation IDs, artifact-contract
# IDs, supported source IDs). Rejects whitespace, path separators,
# shell metacharacters, secret-bearing patterns, and control chars.
_FORBIDDEN_ID_CHARS = frozenset(
    {
        " ", "\t", "\n", "\r", "\x00",
        "/", "\\", "$", "`", "\"", "'",
        "&", "|", ";", "<", ">", "*",
        "?", "(", ")", "{", "}", "[", "]",
        "=", "!", "#", "@", ":", ",", "~",
    }
)


class PlatformPackageDescriptorError(ValueError):
    """A local PlatformPackage descriptor validation failure.

    Raised for any shape, type, enum, ordering, duplicate, unknown-key,
    injection, or content mismatch violation. Never extends
    ``icp_common.ALL_ERROR_CODES``.
    """


# ---------------------------------------------------------------------------
# Small deterministic helpers (canonical JSON, digests, strict decode).
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
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_safe_id(value: Any) -> bool:
    """A controlled identifier: non-empty, no path / shell / secret
    metacharacters, no whitespace."""
    if not isinstance(value, str) or not value:
        return False
    for c in value:
        if c in _FORBIDDEN_ID_CHARS:
            return False
        if ord(c) < 0x20 or ord(c) == 0x7F:
            return False
    return True


def _is_safe_basename(name: Any) -> bool:
    """A safe Python module basename: non-empty, no path separators,
    ends in ``.py``."""
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    if name in {".", ".."}:
        return False
    return name.endswith(".py")


def _is_public_api_name(value: Any) -> bool:
    """A public Python identifier (no leading underscore)."""
    if not isinstance(value, str) or not value:
        return False
    if not value.isidentifier():
        return False
    return not value.startswith("_")


def _is_bool(value: Any) -> bool:
    return value is True or value is False


def _check_keys_exact_order(
    actual: Any, expected_order: tuple, location: str
) -> None:
    if not isinstance(actual, dict):
        raise PlatformPackageDescriptorError(
            f"{location}: must be an object"
        )
    actual_keys = list(actual.keys())
    expected_keys = list(expected_order)
    if actual_keys != expected_keys:
        actual_set = set(actual_keys)
        expected_set = set(expected_keys)
        extra = sorted(actual_set - expected_set)
        missing = sorted(expected_set - actual_set)
        raise PlatformPackageDescriptorError(
            f"{location}: key order mismatch: "
            f"extra={extra} missing={missing}"
        )


def _reject_injection_fields(obj: Any, location: str) -> None:
    """Walk ``obj`` and reject any forbidden command/argv/env/shell/
    prompt / activation-override field anywhere."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{location}/{key}" if location else key
            if key in _INJECTION_FIELD_NAMES:
                raise PlatformPackageDescriptorError(
                    f"forbidden injection field: {here}"
                )
            _reject_injection_fields(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_injection_fields(item, f"{location}[{i}]")


# ---------------------------------------------------------------------------
# Public API: validate_descriptor.
# ---------------------------------------------------------------------------


def validate_descriptor(descriptor: Any) -> None:
    """Strict fail-closed validation of the canonical descriptor shape.

    Raises :class:`PlatformPackageDescriptorError` on any violation;
    returns ``None`` on success. Performs no I/O.

    Rejects: non-dict root; wrong / missing / extra / reordered
    top-level keys; wrong ``kind`` / ``schema_version`` /
    ``activation_state`` / ``executable``; empty / null platform /
    profile IDs; malformed SHA-256 digests; unknown / duplicate
    supported source IDs; unknown / duplicate / forbidden actual-source
    types; entry requirements with extra / missing / reordered keys,
    bad owner / required / sensitive types, or unsafe / duplicate IDs;
    components with wrong count, order, role, basename, SHA-256,
    contract_kind, or public_api; ports with wrong count, order, id,
    capability_state, implementation_state (including the legacy
    ``legacy-mapped`` / ``new-port-required`` migration labels),
    provider_component_role, or artifact_contracts; and any forbidden
    command / argv / env / shell / prompt / path / activation-override
    field anywhere in the descriptor.
    """
    if not isinstance(descriptor, dict):
        raise PlatformPackageDescriptorError(
            "descriptor: must be an object"
        )

    _check_keys_exact_order(descriptor, TOP_LEVEL_KEY_ORDER, "descriptor")

    if descriptor["kind"] != KIND_DESCRIPTOR:
        raise PlatformPackageDescriptorError(
            f"descriptor.kind: must be {KIND_DESCRIPTOR!r}, "
            f"got {descriptor['kind']!r}"
        )
    if descriptor["schema_version"] != SCHEMA_VERSION:
        raise PlatformPackageDescriptorError(
            f"descriptor.schema_version: must be {SCHEMA_VERSION!r}, "
            f"got {descriptor['schema_version']!r}"
        )
    if not _is_non_empty_str(descriptor["platform_id"]):
        raise PlatformPackageDescriptorError(
            "descriptor.platform_id: must be a non-empty string"
        )
    if not _is_non_empty_str(descriptor["profile_id"]):
        raise PlatformPackageDescriptorError(
            "descriptor.profile_id: must be a non-empty string "
            "(null is not permitted in v1)"
        )
    expected_executable = _ACTIVATION_EXECUTABLE.get(descriptor["activation_state"])
    if expected_executable is None:
        raise PlatformPackageDescriptorError(
            f"descriptor.activation_state: must be one of "
            f"{tuple(_ACTIVATION_EXECUTABLE)!r}, "
            f"got {descriptor['activation_state']!r}"
        )
    if descriptor["executable"] is not expected_executable:
        raise PlatformPackageDescriptorError(
            f"descriptor.executable: must be exactly {expected_executable!r}, "
            f"got {descriptor['executable']!r}"
        )
    if not _is_sha256_hex(descriptor["registry_digest"]):
        raise PlatformPackageDescriptorError(
            "descriptor.registry_digest: must be SHA-256 hex (64 lowercase)"
        )
    if not _is_sha256_hex(descriptor["selected_profile_digest"]):
        raise PlatformPackageDescriptorError(
            "descriptor.selected_profile_digest: must be SHA-256 hex "
            "(64 lowercase)"
        )

    _validate_supported_source_ids(
        descriptor["supported_task_sources"],
        ALLOWED_TASK_SOURCE_IDS,
        "descriptor.supported_task_sources",
    )
    _validate_supported_source_ids(
        descriptor["supported_design_sources"],
        ALLOWED_DESIGN_SOURCE_IDS,
        "descriptor.supported_design_sources",
    )
    _validate_actual_source_types(descriptor["actual_source_types"])
    _validate_entry_requirements(descriptor["entry_requirements"])
    _validate_components(descriptor["components"])
    _validate_ports(descriptor["ports"])

    # Final defense-in-depth pass: reject injection fields anywhere.
    _reject_injection_fields(descriptor, "")


def _validate_supported_source_ids(
    value: Any, allowed: tuple, location: str
) -> None:
    if not isinstance(value, list):
        raise PlatformPackageDescriptorError(
            f"{location}: must be a list"
        )
    seen: set = set()
    for i, item in enumerate(value):
        if not _is_safe_id(item) or item not in allowed:
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: not a controlled source ID: {item!r}"
            )
        if item in seen:
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: duplicate: {item!r}"
            )
        seen.add(item)


def _validate_actual_source_types(value: Any) -> None:
    location = "descriptor.actual_source_types"
    if not isinstance(value, list):
        raise PlatformPackageDescriptorError(
            f"{location}: must be a list"
        )
    seen: set = set()
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: must be a string, got "
                f"{type(item).__name__}"
            )
        if item in _FORBIDDEN_ACTUAL_SOURCE_TYPES:
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: reference / design image type "
                f"forbidden: {item!r}"
            )
        if item not in ACTUAL_SOURCE_TYPES:
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: not a controlled actual-source "
                f"type: {item!r}"
            )
        if item in seen:
            raise PlatformPackageDescriptorError(
                f"{location}[{i}]: duplicate: {item!r}"
            )
        seen.add(item)


def _validate_entry_requirements(value: Any) -> None:
    location = "descriptor.entry_requirements"
    if not isinstance(value, list):
        raise PlatformPackageDescriptorError(
            f"{location}: must be a list"
        )
    seen_ids: set = set()
    for i, er in enumerate(value):
        here = f"{location}[{i}]"
        _check_keys_exact_order(er, ENTRY_REQUIREMENT_KEY_ORDER, here)
        er_id = er["id"]
        if not _is_safe_id(er_id):
            raise PlatformPackageDescriptorError(
                f"{here}.id: not a controlled ID: {er_id!r}"
            )
        if er_id in seen_ids:
            raise PlatformPackageDescriptorError(
                f"{here}.id: duplicate: {er_id!r}"
            )
        seen_ids.add(er_id)
        if er["owner"] not in ENTRY_REQUIREMENT_OWNERS:
            raise PlatformPackageDescriptorError(
                f"{here}.owner: not a controlled owner: {er['owner']!r}"
            )
        if not _is_bool(er["required"]):
            raise PlatformPackageDescriptorError(
                f"{here}.required: must be a bool, got "
                f"{type(er['required']).__name__}"
            )
        if not _is_bool(er["sensitive"]):
            raise PlatformPackageDescriptorError(
                f"{here}.sensitive: must be a bool, got "
                f"{type(er['sensitive']).__name__}"
            )
        for key in ("probe_id", "accepted_shape_id", "remediation_id"):
            if not _is_safe_id(er[key]):
                raise PlatformPackageDescriptorError(
                    f"{here}.{key}: not a controlled ID: {er[key]!r}"
                )


def _validate_components(value: Any) -> None:
    location = "descriptor.components"
    if not isinstance(value, list):
        raise PlatformPackageDescriptorError(
            f"{location}: must be a list"
        )
    if len(value) != len(COMPONENT_ROLES):
        raise PlatformPackageDescriptorError(
            f"{location}: must have exactly {len(COMPONENT_ROLES)} "
            f"entries, got {len(value)}"
        )
    seen_roles: set = set()
    for i, comp in enumerate(value):
        here = f"{location}[{i}]"
        _check_keys_exact_order(comp, COMPONENT_KEY_ORDER, here)
        expected_role = COMPONENT_ROLES[i]
        if comp["role"] != expected_role:
            raise PlatformPackageDescriptorError(
                f"{here}.role: must be {expected_role!r} in order, "
                f"got {comp['role']!r}"
            )
        if comp["role"] in seen_roles:
            raise PlatformPackageDescriptorError(
                f"{here}.role: duplicate: {comp['role']!r}"
            )
        seen_roles.add(comp["role"])
        if not _is_safe_basename(comp["module_basename"]):
            raise PlatformPackageDescriptorError(
                f"{here}.module_basename: not a safe Python module "
                f"basename: {comp['module_basename']!r}"
            )
        if not _is_sha256_hex(comp["module_sha256"]):
            raise PlatformPackageDescriptorError(
                f"{here}.module_sha256: must be SHA-256 hex "
                f"(64 lowercase)"
            )
        if not _is_non_empty_str(comp["contract_kind"]):
            raise PlatformPackageDescriptorError(
                f"{here}.contract_kind: must be a non-empty string"
            )
        pa = comp["public_api"]
        if not isinstance(pa, list) or not pa:
            raise PlatformPackageDescriptorError(
                f"{here}.public_api: must be a non-empty list"
            )
        seen_pa: set = set()
        for j, name in enumerate(pa):
            if not _is_public_api_name(name):
                raise PlatformPackageDescriptorError(
                    f"{here}.public_api[{j}]: not a public identifier: "
                    f"{name!r}"
                )
            if name in seen_pa:
                raise PlatformPackageDescriptorError(
                    f"{here}.public_api[{j}]: duplicate: {name!r}"
                )
            seen_pa.add(name)


def _validate_ports(value: Any) -> None:
    location = "descriptor.ports"
    if not isinstance(value, list):
        raise PlatformPackageDescriptorError(
            f"{location}: must be a list"
        )
    if len(value) != len(PORT_IDS):
        raise PlatformPackageDescriptorError(
            f"{location}: must have exactly {len(PORT_IDS)} entries, "
            f"got {len(value)}"
        )
    seen_ids: set = set()
    for i, port in enumerate(value):
        here = f"{location}[{i}]"
        _check_keys_exact_order(port, PORT_KEY_ORDER, here)
        expected_id = PORT_IDS[i]
        if port["id"] != expected_id:
            raise PlatformPackageDescriptorError(
                f"{here}.id: must be {expected_id!r} in order, "
                f"got {port['id']!r}"
            )
        if port["id"] in seen_ids:
            raise PlatformPackageDescriptorError(
                f"{here}.id: duplicate: {port['id']!r}"
            )
        seen_ids.add(port["id"])
        if port["capability_state"] not in CAPABILITY_STATES:
            raise PlatformPackageDescriptorError(
                f"{here}.capability_state: not controlled: "
                f"{port['capability_state']!r}"
            )
        if port["implementation_state"] not in IMPLEMENTATION_STATES:
            raise PlatformPackageDescriptorError(
                f"{here}.implementation_state: not controlled v1 "
                f"value (got {port['implementation_state']!r}); "
                f"legacy-mapped / new-port-required are not permitted"
            )
        if port["provider_component_role"] not in COMPONENT_ROLES:
            raise PlatformPackageDescriptorError(
                f"{here}.provider_component_role: not a component "
                f"role: {port['provider_component_role']!r}"
            )
        ac = port["artifact_contracts"]
        if not isinstance(ac, list):
            raise PlatformPackageDescriptorError(
                f"{here}.artifact_contracts: must be a list"
            )
        seen_ac: set = set()
        for j, name in enumerate(ac):
            if not _is_safe_id(name):
                raise PlatformPackageDescriptorError(
                    f"{here}.artifact_contracts[{j}]: not a controlled "
                    f"ID: {name!r}"
                )
            if name in seen_ac:
                raise PlatformPackageDescriptorError(
                    f"{here}.artifact_contracts[{j}]: duplicate: {name!r}"
                )
            seen_ac.add(name)


# ---------------------------------------------------------------------------
# Public API: digests.
# ---------------------------------------------------------------------------


def compute_descriptor_digest(descriptor: dict) -> str:
    """Canonical SHA-256 of the descriptor.

    The descriptor itself carries no self-referential digest; this
    function is the canonical recomputation used by package wrappers
    and verifiers.
    """
    if not isinstance(descriptor, dict):
        raise PlatformPackageDescriptorError(
            "descriptor: must be an object"
        )
    return _sha256_bytes(_canonical_json_bytes(descriptor))


def compute_registry_digest(registry: dict) -> str:
    """Canonical SHA-256 of a registry dict.

    Package wrappers load the live fixed registry, canonicalize it, and
    recompute this digest to require equality with the descriptor's
    ``registry_digest`` field.
    """
    if not isinstance(registry, dict):
        raise PlatformPackageDescriptorError(
            "registry: must be an object"
        )
    return _sha256_bytes(_canonical_json_bytes(registry))


def compute_selected_profile_digest(
    registry: dict, platform_id: str, profile_id: str
) -> str:
    """Canonical SHA-256 of the selected platform / profile block.

    Raises :class:`PlatformPackageDescriptorError` if the platform or
    profile is not registered. The digest is computed over the
    canonical JSON of ``{"platform_id": ..., "profile_id": ...,
    "platform_block": ...}`` so that the platform block's full
    ``{"profiles": [...], "default_profile": ..., "activated": ...}``
    identity is bound.
    """
    if not _is_non_empty_str(platform_id):
        raise PlatformPackageDescriptorError(
            "platform_id: must be a non-empty string"
        )
    if not _is_non_empty_str(profile_id):
        raise PlatformPackageDescriptorError(
            "profile_id: must be a non-empty string"
        )
    if not isinstance(registry, dict):
        raise PlatformPackageDescriptorError(
            "registry: must be an object"
        )
    platforms = registry.get("platforms")
    if not isinstance(platforms, dict):
        raise PlatformPackageDescriptorError(
            "registry.platforms: must be an object"
        )
    platform_block = platforms.get(platform_id)
    if not isinstance(platform_block, dict):
        raise PlatformPackageDescriptorError(
            f"registry.platforms.{platform_id}: missing"
        )
    profiles = platform_block.get("profiles")
    if not isinstance(profiles, list) or profile_id not in profiles:
        raise PlatformPackageDescriptorError(
            f"registry.platforms.{platform_id}.profiles: "
            f"profile {profile_id!r} not registered"
        )
    payload = {
        "platform_id": platform_id,
        "profile_id": profile_id,
        "platform_block": platform_block,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))
