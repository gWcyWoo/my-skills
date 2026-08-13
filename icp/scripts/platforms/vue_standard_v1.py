"""Inactive Vue/Vite platform-adapter descriptor."""

from __future__ import annotations

from typing import Any

import icp_common as _common


KIND_DESCRIPTOR = "icp.vue-platform-adapter-descriptor.v1"
KIND_VERIFY = "icp.vue-platform-adapter-descriptor-verify.v1"
SCHEMA_VERSION = 1
PLATFORM_ID = "vue"
PROFILE_ID = "vue-vite"
ACTIVATION_STATE = "inactive"

_TOP_LEVEL_KEYS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "activation_state",
    "executable",
    "operations",
)
_OPERATION_KEYS = ("id", "capability_state", "implementation_state")


class VueDescriptorError(ValueError):
    """Raised when the fixed Vue descriptor or registry binding is invalid."""


def _registry_operations() -> tuple[tuple[str, str], ...]:
    try:
        registries = _common.load_registries()
        platform = registries["platforms"][PLATFORM_ID]
        operations = tuple(item["id"] for item in registries["operations"])
        capabilities = registries["capabilities"]
    except (KeyError, TypeError, _common.ConfigError) as exc:
        raise VueDescriptorError("registry contract is invalid") from exc
    if platform.get("profiles") != [PROFILE_ID]:
        raise VueDescriptorError("registry profile contract is invalid")
    if platform.get("default_profile") != PROFILE_ID:
        raise VueDescriptorError("registry default profile is invalid")
    if platform.get("activated") is not True:
        raise VueDescriptorError("registry activation must remain true")
    try:
        return tuple((operation_id, capabilities[operation_id]) for operation_id in operations)
    except KeyError as exc:
        raise VueDescriptorError("registry capability contract is invalid") from exc


def _validate_descriptor(value: Any) -> None:
    if not isinstance(value, dict) or tuple(value) != _TOP_LEVEL_KEYS:
        raise VueDescriptorError("descriptor shape is invalid")
    expected_literals = {
        "kind": KIND_DESCRIPTOR,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
    }
    for key, expected in expected_literals.items():
        if value[key] != expected or (
            key == "schema_version" and isinstance(value[key], bool)
        ):
            raise VueDescriptorError(f"descriptor {key} is invalid")
    operations = value["operations"]
    expected_operations = _registry_operations()
    if not isinstance(operations, list) or len(operations) != len(expected_operations):
        raise VueDescriptorError("descriptor operations are invalid")
    for item, (operation_id, capability_state) in zip(
        operations, expected_operations, strict=True
    ):
        if not isinstance(item, dict) or tuple(item) != _OPERATION_KEYS:
            raise VueDescriptorError("descriptor operation shape is invalid")
        if item != {
            "id": operation_id,
            "capability_state": capability_state,
            "implementation_state": "implemented",
        }:
            raise VueDescriptorError("descriptor operation is invalid")


def describe() -> dict[str, Any]:
    operations = [
        {
            "id": operation_id,
            "capability_state": capability_state,
            "implementation_state": "implemented",
        }
        for operation_id, capability_state in _registry_operations()
    ]
    descriptor: dict[str, Any] = {
        "kind": KIND_DESCRIPTOR,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
        "operations": operations,
    }
    _validate_descriptor(descriptor)
    return descriptor


def verify_descriptor() -> dict[str, Any]:
    descriptor = describe()
    _validate_descriptor(descriptor)
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": ACTIVATION_STATE,
        "executable": False,
        "operations_total": len(descriptor["operations"]),
    }
