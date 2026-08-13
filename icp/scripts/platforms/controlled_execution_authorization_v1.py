"""Nonce-bound authorization for controlled ICP platform bindings."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from types import ModuleType
from typing import Any


class ControlledExecutionAuthorizationError(ValueError):
    pass


_KEYS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "execution_nonce",
    "verified_binding",
    "binding_digest",
    "step_authorizations",
    "authorization_digest",
)


def _digest(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _nonce(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ControlledExecutionAuthorizationError("execution nonce must be SHA-256 hex")
    return value


def prepare_authorization(
    binding: dict[str, Any],
    *,
    execution_nonce: str,
    platform_id: str,
    profile_id: str,
    binding_module: ModuleType,
    operations_module: ModuleType,
) -> dict[str, Any]:
    verified = binding_module.verify_binding(copy.deepcopy(binding))
    _nonce(execution_nonce)
    steps = verified["operation_plan"]["steps"]
    step_authorizations = [
        {
            "step_id": step["step_id"],
            "step_digest": _digest(step),
            "authorization_id": _digest(
                {
                    "binding_digest": verified["binding_digest"],
                    "execution_nonce": execution_nonce,
                    "step_id": step["step_id"],
                    "step_digest": _digest(step),
                }
            ),
        }
        for step in steps
    ]
    body = {
        "kind": "icp.controlled-execution-authorization.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "execution_nonce": execution_nonce,
        "verified_binding": verified,
        "binding_digest": verified["binding_digest"],
        "step_authorizations": step_authorizations,
    }
    return {**body, "authorization_digest": _digest(body)}


def verify_authorization(
    authorization: dict[str, Any],
    *,
    execution_nonce: str,
    platform_id: str,
    profile_id: str,
    binding_module: ModuleType,
    operations_module: ModuleType,
) -> dict[str, Any]:
    del operations_module
    if not isinstance(authorization, dict) or tuple(authorization) != _KEYS:
        raise ControlledExecutionAuthorizationError("authorization shape is invalid")
    if authorization["kind"] != "icp.controlled-execution-authorization.v1" or authorization["schema_version"] != 1:
        raise ControlledExecutionAuthorizationError("authorization identity is invalid")
    if authorization["platform_id"] != platform_id or authorization["profile_id"] != profile_id:
        raise ControlledExecutionAuthorizationError("authorization platform scope is invalid")
    if authorization["execution_nonce"] != _nonce(execution_nonce):
        raise ControlledExecutionAuthorizationError("execution nonce mismatch")
    verified = binding_module.verify_binding(copy.deepcopy(authorization["verified_binding"]))
    if authorization["binding_digest"] != verified["binding_digest"]:
        raise ControlledExecutionAuthorizationError("binding digest mismatch")
    expected_steps = [
        {
            "step_id": step["step_id"],
            "step_digest": _digest(step),
            "authorization_id": _digest(
                {
                    "binding_digest": verified["binding_digest"],
                    "execution_nonce": execution_nonce,
                    "step_id": step["step_id"],
                    "step_digest": _digest(step),
                }
            ),
        }
        for step in verified["operation_plan"]["steps"]
    ]
    if authorization["step_authorizations"] != expected_steps:
        raise ControlledExecutionAuthorizationError("step authorization mismatch")
    body = {key: copy.deepcopy(authorization[key]) for key in _KEYS[:-1]}
    if authorization["authorization_digest"] != _digest(body):
        raise ControlledExecutionAuthorizationError("authorization digest mismatch")
    return copy.deepcopy(authorization)


__all__ = [
    "ControlledExecutionAuthorizationError",
    "prepare_authorization",
    "verify_authorization",
]
