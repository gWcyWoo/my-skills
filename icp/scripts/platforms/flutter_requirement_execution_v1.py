#!/usr/bin/env python3
"""Requirement-scoped Flutter execution facade for ICP P3d."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import requirement_progress_v1 as progress_contract
from platforms import flutter_execution_authorization_v1 as authorization_v1
from platforms import flutter_execution_binding_v1 as binding_v1
from platforms import flutter_execution_executor_v1 as executor_v1
from platforms import flutter_operations_v1 as operations_v1


class FlutterRequirementExecutionError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def document_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


_REQUIREMENT_SCOPE_KEY_ORDER = (
    "kind",
    "schema_version",
    "requirement_id",
    "claim_intent_digest",
    "progress_id",
    "selection_manifest_path",
    "selection_manifest_digest",
    "entry_readiness_path",
    "entry_readiness_digest",
    "platform_package_selection_path",
    "platform_package_selection_digest",
)

_REQUIREMENT_PLAN_KEY_ORDER = (
    "kind",
    "schema_version",
    "operation_id",
    "requirement_scope",
    "operation_plan",
    "operation_plan_digest",
)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _verify_requirement_scope(scope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scope, dict) or tuple(scope) != _REQUIREMENT_SCOPE_KEY_ORDER:
        raise FlutterRequirementExecutionError("requirement scope shape is invalid")
    if scope["kind"] != "icp.platform-requirement-scope.v1" or scope["schema_version"] != 1:
        raise FlutterRequirementExecutionError("requirement scope identity is invalid")
    for field in (
        "requirement_id",
        "claim_intent_digest",
        "progress_id",
        "selection_manifest_digest",
        "entry_readiness_digest",
        "platform_package_selection_digest",
    ):
        if not _is_sha256(scope[field]):
            raise FlutterRequirementExecutionError(f"requirement scope {field} must be SHA-256")
    for path_field, digest_field in (
        ("selection_manifest_path", "selection_manifest_digest"),
        ("entry_readiness_path", "entry_readiness_digest"),
        ("platform_package_selection_path", "platform_package_selection_digest"),
    ):
        path = Path(scope[path_field])
        if not path.is_absolute():
            raise FlutterRequirementExecutionError(f"requirement scope {path_field} must be absolute")
        if path.is_symlink() or not path.is_file():
            raise FlutterRequirementExecutionError(
                f"requirement scope {path_field} must be a non-symlink regular file"
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != scope[digest_field]:
            raise FlutterRequirementExecutionError(f"requirement scope {path_field} digest mismatch")
    return scope


def build_plan(operation_id: str, request: dict, requirement_scope: dict) -> dict:
    scope = _verify_requirement_scope(requirement_scope)
    operation_plan = operations_v1.build(operation_id, request)
    verification = operations_v1.verify_plan(operation_plan)
    return {
        "kind": "icp.flutter-requirement-operation-plan.v1",
        "schema_version": 1,
        "operation_id": operation_id,
        "requirement_scope": json.loads(json.dumps(scope)),
        "operation_plan": operation_plan,
        "operation_plan_digest": verification["plan_digest"],
    }


def verify_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or tuple(plan) != _REQUIREMENT_PLAN_KEY_ORDER:
        raise FlutterRequirementExecutionError("requirement operation plan shape is invalid")
    if plan["kind"] != "icp.flutter-requirement-operation-plan.v1" or plan["schema_version"] != 1:
        raise FlutterRequirementExecutionError("requirement operation plan identity is invalid")
    _verify_requirement_scope(plan["requirement_scope"])
    verification = operations_v1.verify_plan(plan["operation_plan"])
    if plan["operation_id"] != plan["operation_plan"].get("operation_id"):
        raise FlutterRequirementExecutionError("requirement operation id mismatch")
    if plan["operation_plan_digest"] != verification["plan_digest"]:
        raise FlutterRequirementExecutionError("requirement operation plan digest mismatch")
    return plan


def prepare_binding(
    manifest_path: str | Path,
    operation_id: str,
    request: dict,
    requirement_scope: dict,
) -> dict:
    plan = build_plan(operation_id, request, requirement_scope)
    scope = plan["requirement_scope"]
    manifest = str(Path(manifest_path))
    if manifest != scope["selection_manifest_path"]:
        raise FlutterRequirementExecutionError("manifest path differs from requirement scope")
    base = binding_v1.prepare_binding(manifest, operation_id, request)
    verification = binding_v1.verify_binding(base)
    if base.get("plan") != plan["operation_plan"]:
        raise FlutterRequirementExecutionError("binding operation plan differs from requirement plan")
    return {
        "kind": "icp.flutter-requirement-execution-binding.v1",
        "schema_version": 1,
        "requirement_plan": plan,
        "binding": base,
        "binding_digest": verification["binding_digest"],
    }


def verify_binding(binding: dict) -> dict:
    order = ("kind", "schema_version", "requirement_plan", "binding", "binding_digest")
    if not isinstance(binding, dict) or tuple(binding) != order:
        raise FlutterRequirementExecutionError("requirement binding shape is invalid")
    if binding["kind"] != "icp.flutter-requirement-execution-binding.v1" or binding["schema_version"] != 1:
        raise FlutterRequirementExecutionError("requirement binding identity is invalid")
    verify_plan(binding["requirement_plan"])
    verification = binding_v1.verify_binding(binding["binding"])
    if binding["binding"].get("plan") != binding["requirement_plan"]["operation_plan"]:
        raise FlutterRequirementExecutionError("requirement binding operation plan drift")
    if binding["binding_digest"] != verification["binding_digest"]:
        raise FlutterRequirementExecutionError("requirement binding digest mismatch")
    return binding


def prepare_authorization(requirement_binding: dict, *, execution_nonce: str) -> dict:
    verify_binding(requirement_binding)
    scope = requirement_binding["requirement_plan"]["requirement_scope"]
    base = authorization_v1.prepare_authorization(
        requirement_binding["binding"],
        expected_manifest_path=scope["selection_manifest_path"],
        expected_manifest_sha256=scope["selection_manifest_digest"],
        expected_binding_digest=requirement_binding["binding_digest"],
        execution_nonce=execution_nonce,
    )
    authorization_digest = base["authorization_digest"]
    return {
        "kind": "icp.flutter-requirement-execution-authorization.v1",
        "schema_version": 1,
        "requirement_binding": copy.deepcopy(requirement_binding),
        "requirement_binding_digest": document_digest(requirement_binding),
        "authorization": base,
        "authorization_digest": authorization_digest,
    }


def verify_authorization(requirement_authorization: dict) -> dict:
    order = (
        "kind",
        "schema_version",
        "requirement_binding",
        "requirement_binding_digest",
        "authorization",
        "authorization_digest",
    )
    if not isinstance(requirement_authorization, dict) or tuple(requirement_authorization) != order:
        raise FlutterRequirementExecutionError("requirement authorization shape is invalid")
    if (
        requirement_authorization["kind"] != "icp.flutter-requirement-execution-authorization.v1"
        or requirement_authorization["schema_version"] != 1
    ):
        raise FlutterRequirementExecutionError("requirement authorization identity is invalid")
    binding = requirement_authorization["requirement_binding"]
    verify_binding(binding)
    if requirement_authorization["requirement_binding_digest"] != document_digest(binding):
        raise FlutterRequirementExecutionError("requirement binding wrapper digest mismatch")
    scope = binding["requirement_plan"]["requirement_scope"]
    authorization_v1.verify_authorization(
        requirement_authorization["authorization"],
        expected_manifest_path=scope["selection_manifest_path"],
        expected_manifest_sha256=scope["selection_manifest_digest"],
        expected_binding_digest=binding["binding_digest"],
        expected_authorization_digest=requirement_authorization["authorization_digest"],
    )
    return requirement_authorization


def build_checkpoint_receipt(
    requirement_authorization: dict,
    execution_report: dict,
    *,
    progress: dict,
    feature_id: str | None,
    step_id: str,
    execution_mode: str,
) -> dict:
    verify_authorization(requirement_authorization)
    progress_contract.verify_progress(progress)
    scope = requirement_authorization["requirement_binding"]["requirement_plan"]["requirement_scope"]
    if scope["requirement_id"] != progress["requirement_id"] or scope["progress_id"] != progress["progress_id"]:
        raise FlutterRequirementExecutionError("checkpoint progress scope mismatch")
    output_digest = document_digest(execution_report)
    auth_digest = requirement_authorization["authorization_digest"]
    sequence = progress["checkpoint_count"]
    receipt_id = hashlib.sha256(
        b"icp.flutter-checkpoint-receipt.v1\x00"
        + bytes.fromhex(auth_digest)
        + sequence.to_bytes(8, "big")
        + bytes.fromhex(output_digest)
    ).hexdigest()
    receipt = {
        "kind": progress_contract.KIND_CHECKPOINT_RECEIPT,
        "schema_version": 1,
        "receipt_id": receipt_id,
        "requirement_id": progress["requirement_id"],
        "progress_id": progress["progress_id"],
        "claim_ack_digest": progress["claim_ack_digest"],
        "sequence": sequence,
        "previous_receipt_digest": progress["latest_checkpoint_receipt_digest"]
        or progress_contract.GENESIS_RECEIPT_DIGEST,
        "feature_id": feature_id,
        "step_id": step_id,
        "execution_mode": execution_mode,
        "input_artifact_digests": [
            {"id": "authorization", "digest": auth_digest},
            {
                "id": "operation-plan",
                "digest": requirement_authorization["requirement_binding"]["requirement_plan"][
                    "operation_plan_digest"
                ],
            },
        ],
        "output_artifact_digests": [{"id": "execution-report", "digest": output_digest}],
        "producer_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "verifier_digest": hashlib.sha256(Path(executor_v1.__file__).read_bytes()).hexdigest(),
    }
    progress_contract.verify_checkpoint_receipt(receipt)
    return receipt


def execute_authorization(
    requirement_authorization: dict,
    *,
    progress: dict,
    feature_id: str | None,
    step_id: str,
    execution_mode: str,
) -> dict:
    verify_authorization(requirement_authorization)
    binding = requirement_authorization["requirement_binding"]
    scope = binding["requirement_plan"]["requirement_scope"]
    report = executor_v1.execute_authorization(
        requirement_authorization["authorization"],
        expected_manifest_path=scope["selection_manifest_path"],
        expected_manifest_sha256=scope["selection_manifest_digest"],
        expected_binding_digest=binding["binding_digest"],
        expected_authorization_digest=requirement_authorization["authorization_digest"],
    )
    receipt = build_checkpoint_receipt(
        requirement_authorization,
        report,
        progress=progress,
        feature_id=feature_id,
        step_id=step_id,
        execution_mode=execution_mode,
    )
    return {
        "kind": "icp.flutter-requirement-execution-result.v1",
        "schema_version": 1,
        "requirement_id": progress["requirement_id"],
        "execution_report": report,
        "checkpoint_receipt": receipt,
    }


__all__ = [
    "FlutterRequirementExecutionError",
    "build_checkpoint_receipt",
    "build_plan",
    "document_digest",
    "execute_authorization",
    "prepare_authorization",
    "prepare_binding",
    "verify_authorization",
    "verify_binding",
    "verify_plan",
]
