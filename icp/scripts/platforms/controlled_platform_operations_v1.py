"""Deterministic operation plans for controlled ICP platform adapters."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ControlledOperationPlanError(ValueError):
    pass


PORTS = (
    "visible_codegen",
    "fixture_codegen",
    "trace_harness",
    "packaging",
    "test_runner",
    "runtime_capture",
    "project_gates",
    "fan_in",
)
_SAFE_ID = re.compile(r"[a-z][a-z0-9._-]{0,127}")
_REQUEST_KEYS = ("project_root", "run_root", "feature_id", "inputs", "outputs")
_PLAN_KEYS = (
    "kind",
    "schema_version",
    "operation_id",
    "platform_id",
    "profile_id",
    "request_digest",
    "execution_context",
    "steps",
)
_CONTEXT_KEYS = ("project_root", "run_root", "feature_id")
_STEP_KEYS = ("step_id", "action", "inputs", "outputs")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def document_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ordinary_root(value: Any, role: str) -> Path:
    if not isinstance(value, str):
        raise ControlledOperationPlanError(f"{role} must be a string")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ControlledOperationPlanError(f"{role} must be an absolute non-symlink directory")
    resolved = path.resolve(strict=True)
    if str(path) != str(resolved):
        raise ControlledOperationPlanError(f"{role} must be canonical")
    return path


def _safe_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ControlledOperationPlanError("artifact path must be a non-empty POSIX path")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ControlledOperationPlanError("artifact path must be normalized and relative")
    return relative


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_output_path(path: Path, root: Path) -> None:
    if not _inside(path, root):
        raise ControlledOperationPlanError("output escapes its declared root")
    cursor = path.parent
    while cursor != root:
        if cursor.is_symlink():
            raise ControlledOperationPlanError("output ancestor must not be a symlink")
        cursor = cursor.parent
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ControlledOperationPlanError("output must be absent or a regular file")


def _artifacts(
    value: Any,
    *,
    project_root: Path,
    run_root: Path,
    output: bool,
) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ControlledOperationPlanError("artifact map must be a non-empty object")
    if tuple(value) != tuple(sorted(value)):
        raise ControlledOperationPlanError("artifact ids must be sorted")
    result: dict[str, str] = {}
    for artifact_id, specification in value.items():
        if not isinstance(artifact_id, str) or not _SAFE_ID.fullmatch(artifact_id):
            raise ControlledOperationPlanError("artifact id is invalid")
        if not isinstance(specification, dict) or tuple(specification) != ("root", "path"):
            raise ControlledOperationPlanError("artifact specification shape is invalid")
        root_name = specification["root"]
        if root_name not in {"project", "run"}:
            raise ControlledOperationPlanError("artifact root is invalid")
        root = project_root if root_name == "project" else run_root
        path = root / _safe_relative(specification["path"])
        if output:
            _check_output_path(path, root)
        elif path.is_symlink() or not path.is_file():
            raise ControlledOperationPlanError("input must be a non-symlink regular file")
        result[artifact_id] = str(path)
    return result


def list_operation_ids(platform_id: str) -> tuple[str, ...]:
    if not isinstance(platform_id, str) or not _SAFE_ID.fullmatch(platform_id):
        raise ControlledOperationPlanError("platform id is invalid")
    return tuple(f"{platform_id}.{port}.v1" for port in PORTS)


def build_plan(
    platform_id: str,
    profile_id: str,
    operation_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    if operation_id not in list_operation_ids(platform_id):
        raise ControlledOperationPlanError("operation id is unsupported")
    if not isinstance(profile_id, str) or not _SAFE_ID.fullmatch(profile_id):
        raise ControlledOperationPlanError("profile id is invalid")
    if not isinstance(request, dict) or tuple(request) != _REQUEST_KEYS:
        raise ControlledOperationPlanError("operation request shape is invalid")
    project_root = _ordinary_root(request["project_root"], "project_root")
    run_root = _ordinary_root(request["run_root"], "run_root")
    if run_root.parent != project_root / ".icp" / "runs":
        raise ControlledOperationPlanError("run_root must be the fixed project .icp/runs child")
    feature_id = request["feature_id"]
    if not isinstance(feature_id, str) or not _SAFE_ID.fullmatch(feature_id):
        raise ControlledOperationPlanError("feature id is invalid")
    inputs = _artifacts(
        request["inputs"], project_root=project_root, run_root=run_root, output=False
    )
    outputs = _artifacts(
        request["outputs"], project_root=project_root, run_root=run_root, output=True
    )
    port = operation_id[len(platform_id) + 1 : -3]
    plan = {
        "kind": f"icp.{platform_id}-operation-plan.v1",
        "schema_version": 1,
        "operation_id": operation_id,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "request_digest": document_digest(request),
        "execution_context": {
            "project_root": str(project_root),
            "run_root": str(run_root),
            "feature_id": feature_id,
        },
        "steps": [
            {
                "step_id": port,
                "action": f"{platform_id.replace('-', '_')}_{port}",
                "inputs": inputs,
                "outputs": outputs,
            }
        ],
    }
    verify_plan(platform_id, profile_id, plan)
    return plan


def _verify_artifact_paths(
    value: Any,
    *,
    roots: tuple[Path, Path],
    output: bool,
) -> None:
    if not isinstance(value, dict) or not value or tuple(value) != tuple(sorted(value)):
        raise ControlledOperationPlanError("plan artifact map is invalid")
    for artifact_id, path_value in value.items():
        if not _SAFE_ID.fullmatch(artifact_id) or not isinstance(path_value, str):
            raise ControlledOperationPlanError("plan artifact is invalid")
        path = Path(path_value)
        owner = next((root for root in roots if _inside(path, root)), None)
        if owner is None or not path.is_absolute():
            raise ControlledOperationPlanError("plan artifact escapes controlled roots")
        if output:
            _check_output_path(path, owner)
        elif path.is_symlink() or not path.is_file():
            raise ControlledOperationPlanError("plan input is not a regular file")


def verify_plan(platform_id: str, profile_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or tuple(plan) != _PLAN_KEYS:
        raise ControlledOperationPlanError("operation plan shape is invalid")
    if plan["kind"] != f"icp.{platform_id}-operation-plan.v1" or plan["schema_version"] != 1:
        raise ControlledOperationPlanError("operation plan identity is invalid")
    if plan["platform_id"] != platform_id or plan["profile_id"] != profile_id:
        raise ControlledOperationPlanError("operation plan scope is invalid")
    if plan["operation_id"] not in list_operation_ids(platform_id):
        raise ControlledOperationPlanError("operation id is unsupported")
    if not isinstance(plan["request_digest"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", plan["request_digest"]
    ):
        raise ControlledOperationPlanError("request digest is invalid")
    context = plan["execution_context"]
    if not isinstance(context, dict) or tuple(context) != _CONTEXT_KEYS:
        raise ControlledOperationPlanError("execution context shape is invalid")
    project_root = _ordinary_root(context["project_root"], "project_root")
    run_root = _ordinary_root(context["run_root"], "run_root")
    if run_root.parent != project_root / ".icp" / "runs":
        raise ControlledOperationPlanError("execution run_root is not the fixed project .icp/runs child")
    if not isinstance(context["feature_id"], str) or not _SAFE_ID.fullmatch(context["feature_id"]):
        raise ControlledOperationPlanError("execution feature id is invalid")
    steps = plan["steps"]
    if not isinstance(steps, list) or len(steps) != 1:
        raise ControlledOperationPlanError("operation plan must have one step")
    step = steps[0]
    if not isinstance(step, dict) or tuple(step) != _STEP_KEYS:
        raise ControlledOperationPlanError("operation step shape is invalid")
    port = plan["operation_id"][len(platform_id) + 1 : -3]
    if step["step_id"] != port or step["action"] != f"{platform_id.replace('-', '_')}_{port}":
        raise ControlledOperationPlanError("operation step identity is invalid")
    roots = (project_root, run_root)
    _verify_artifact_paths(step["inputs"], roots=roots, output=False)
    _verify_artifact_paths(step["outputs"], roots=roots, output=True)
    return {
        "kind": f"icp.{platform_id}-operation-plan-verify.v1",
        "schema_version": 1,
        "plan_digest": document_digest(plan),
    }


__all__ = [
    "ControlledOperationPlanError",
    "build_plan",
    "document_digest",
    "list_operation_ids",
    "verify_plan",
]
