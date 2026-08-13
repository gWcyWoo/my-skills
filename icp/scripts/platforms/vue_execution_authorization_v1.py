"""Unsigned Vue authorization candidate bound to supervisor expectations."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import copy
from typing import Any

from platforms import vue_execution_binding_v1 as _binding


KIND_AUTHORIZATION = "icp.vue-execution-authorization-candidate.v1"
KIND_VERIFY = "icp.vue-execution-authorization-verify.v1"
SCHEMA_VERSION = 1
_NONCE = re.compile(r"[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{64}")
_AUTH_KEYS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "activation_state",
    "executable",
    "execution_nonce",
    "selection_manifest_path",
    "selection_manifest_sha256",
    "binding_digest",
    "plan_digest",
    "binding",
    "step_authorizations",
    "authorization_digest",
)


class VueExecutionAuthorizationError(ValueError):
    """Raised when a Vue authorization candidate is not exactly trusted."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VueExecutionAuthorizationError("authorization data is invalid") from exc


def _clone(value: Any) -> Any:
    _canonical_bytes(value)
    return copy.deepcopy(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _expected_sha(value: Any, *, role: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise VueExecutionAuthorizationError(f"{role} is invalid")
    return value


def _step_authorizations(binding: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in binding["plan"]["steps"]:
        item = {
            "step_id": step["step_id"],
            "action": step["action"],
            "inputs_digest": _digest(step["inputs"]),
            "outputs_digest": _digest(step["outputs"]),
        }
        item["step_authorization_digest"] = _digest(item)
        result.append(item)
    return result


def prepare_authorization(
    binding: dict[str, Any],
    *,
    expected_manifest_path: str,
    expected_manifest_sha256: str,
    expected_binding_digest: str,
    execution_nonce: str,
) -> dict[str, Any]:
    binding_verify = _binding.verify_binding(binding)
    if not isinstance(expected_manifest_path, str) or not expected_manifest_path:
        raise VueExecutionAuthorizationError("expected_manifest_path is invalid")
    manifest_sha = _expected_sha(
        expected_manifest_sha256, role="expected_manifest_sha256"
    )
    binding_digest = _expected_sha(
        expected_binding_digest, role="expected_binding_digest"
    )
    if not isinstance(execution_nonce, str) or _NONCE.fullmatch(execution_nonce) is None:
        raise VueExecutionAuthorizationError("execution_nonce is invalid")
    checks = (
        (expected_manifest_path, binding["selection_manifest_path"]),
        (manifest_sha, binding["selection_manifest_sha256"]),
        (binding_digest, binding_verify["binding_digest"]),
    )
    if any(not hmac.compare_digest(left, right) for left, right in checks):
        raise VueExecutionAuthorizationError("supervisor expectation mismatch")
    candidate = {
        "kind": KIND_AUTHORIZATION,
        "schema_version": SCHEMA_VERSION,
        "platform_id": "vue",
        "profile_id": "vue-vite",
        "activation_state": "inactive",
        "executable": False,
        "execution_nonce": execution_nonce,
        "selection_manifest_path": expected_manifest_path,
        "selection_manifest_sha256": manifest_sha,
        "binding_digest": binding_digest,
        "plan_digest": binding["plan_verification"]["plan_digest"],
        "binding": _clone(binding),
        "step_authorizations": _step_authorizations(binding),
    }
    candidate["authorization_digest"] = _digest(candidate)
    return candidate


def verify_authorization(
    authorization: dict[str, Any],
    *,
    expected_manifest_path: str,
    expected_manifest_sha256: str,
    expected_binding_digest: str,
    expected_authorization_digest: str,
) -> dict[str, Any]:
    if not isinstance(authorization, dict) or tuple(authorization) != _AUTH_KEYS:
        raise VueExecutionAuthorizationError("authorization shape is invalid")
    if authorization.get("kind") != KIND_AUTHORIZATION:
        raise VueExecutionAuthorizationError("authorization kind is invalid")
    if authorization.get("schema_version") != 1 or isinstance(
        authorization.get("schema_version"), bool
    ):
        raise VueExecutionAuthorizationError("authorization schema is invalid")
    if authorization.get("platform_id") != "vue" or authorization.get("profile_id") != "vue-vite":
        raise VueExecutionAuthorizationError("authorization platform is invalid")
    if authorization.get("activation_state") != "inactive" or authorization.get("executable") is not False:
        raise VueExecutionAuthorizationError("authorization must remain inactive")
    expected_auth = _expected_sha(
        expected_authorization_digest, role="expected_authorization_digest"
    )
    rebuilt = prepare_authorization(
        authorization["binding"],
        expected_manifest_path=expected_manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_binding_digest=expected_binding_digest,
        execution_nonce=authorization["execution_nonce"],
    )
    if rebuilt != authorization:
        raise VueExecutionAuthorizationError("authorization differs from current evidence")
    if not hmac.compare_digest(expected_auth, authorization["authorization_digest"]):
        raise VueExecutionAuthorizationError("authorization digest expectation mismatch")
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": "vue",
        "profile_id": "vue-vite",
        "authorization_digest": authorization["authorization_digest"],
        "binding_digest": authorization["binding_digest"],
        "steps_total": len(authorization["step_authorizations"]),
    }
