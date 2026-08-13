"""Fixed-digest binding for controlled ICP platform operation plans."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any


class ControlledExecutionBindingError(ValueError):
    pass


_KEYS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "manifest_path",
    "manifest_digest",
    "entry_readiness_path",
    "entry_readiness_digest",
    "package_selection_path",
    "package_selection_digest",
    "platform_config_path",
    "platform_config_digest",
    "operation_module_basename",
    "operation_module_sha256",
    "operation_id",
    "request",
    "operation_plan",
    "operation_plan_digest",
    "input_digests",
    "binding_digest",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def document_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _regular_file(value: str | Path, role: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ControlledExecutionBindingError(f"{role} must be an absolute non-symlink file")
    if str(path) != str(path.resolve(strict=True)):
        raise ControlledExecutionBindingError(f"{role} must be canonical")
    return path


def _module_identity(module: ModuleType) -> tuple[str, str]:
    path = _regular_file(module.__file__ or "", "operation module")
    if path.parent != Path(__file__).resolve().parent:
        raise ControlledExecutionBindingError("operation module is outside fixed platform root")
    return path.name, hashlib.sha256(path.read_bytes()).hexdigest()


def _input_digests(plan: dict[str, Any]) -> dict[str, str]:
    inputs = plan["steps"][0]["inputs"]
    return {
        artifact_id: hashlib.sha256(_regular_file(path, "operation input").read_bytes()).hexdigest()
        for artifact_id, path in inputs.items()
    }


def _json_object(path: Path, role: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ControlledExecutionBindingError(f"{role} contains duplicate keys")
            document[key] = value
        return document

    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except ControlledExecutionBindingError:
        raise
    except Exception as exc:
        raise ControlledExecutionBindingError(f"{role} is invalid") from exc
    if not isinstance(document, dict):
        raise ControlledExecutionBindingError(f"{role} must be an object")
    return document


def _platform_config(request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    project_root = request.get("project_root")
    if not isinstance(project_root, str) or not project_root:
        raise ControlledExecutionBindingError("request project root is invalid")
    root = Path(project_root).resolve(strict=True)
    config_path = _regular_file(root / ".icp" / "platform-config.json", "platform config")
    return config_path, _json_object(config_path, "platform config")


def _verify_runtime_projection(plan: dict[str, Any], platform_config: dict[str, Any]) -> None:
    runtime_path = plan["steps"][0]["inputs"].get("runtime")
    if runtime_path is None:
        return
    runtime = _json_object(_regular_file(runtime_path, "runtime input"), "runtime input")
    if any(key not in platform_config or platform_config[key] != value for key, value in runtime.items()):
        raise ControlledExecutionBindingError("runtime input differs from selected platform config")


def _entry_runtime_config_digest(readiness: dict[str, Any]) -> str:
    if readiness.get("kind") != "icp.entry-readiness-report.v1" or readiness.get("status") != "ready":
        raise ControlledExecutionBindingError("entry readiness is not ready")
    checks = readiness.get("checks")
    if not isinstance(checks, list):
        raise ControlledExecutionBindingError("entry readiness checks are invalid")
    matches = [
        check
        for check in checks
        if isinstance(check, dict) and check.get("id") == "runtime_config"
    ]
    if len(matches) != 1 or matches[0].get("status") != "pass":
        raise ControlledExecutionBindingError("entry runtime config evidence is missing")
    digest = matches[0].get("evidence_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ControlledExecutionBindingError("entry runtime config digest is invalid")
    return digest


def prepare_binding(
    *,
    platform_id: str,
    profile_id: str,
    operations_module: ModuleType,
    manifest_path: str | Path,
    operation_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    manifest = _regular_file(manifest_path, "selection manifest")
    module_basename, module_sha = _module_identity(operations_module)
    plan = operations_module.build(operation_id, copy.deepcopy(request))
    verification = operations_module.verify_plan(plan)
    platform_config_path, platform_config = _platform_config(request)
    _verify_runtime_projection(plan, platform_config)
    readiness_path = _regular_file(manifest.parent / "entry-readiness.json", "entry readiness")
    package_selection_path = _regular_file(
        manifest.parent / "platform-package-selection.json", "package selection"
    )
    readiness = _json_object(readiness_path, "entry readiness")
    package_selection = _json_object(package_selection_path, "package selection")
    if (
        package_selection.get("kind") != "icp.platform-package-selection.v1"
        or package_selection.get("platform_id") != platform_id
        or package_selection.get("profile_id") != profile_id
    ):
        raise ControlledExecutionBindingError("package selection identity is invalid")
    if _entry_runtime_config_digest(readiness) != document_digest(platform_config):
        raise ControlledExecutionBindingError("platform config differs from entry readiness")
    body = {
        "kind": "icp.controlled-execution-binding.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "manifest_path": str(manifest),
        "manifest_digest": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "entry_readiness_path": str(readiness_path),
        "entry_readiness_digest": hashlib.sha256(readiness_path.read_bytes()).hexdigest(),
        "package_selection_path": str(package_selection_path),
        "package_selection_digest": hashlib.sha256(package_selection_path.read_bytes()).hexdigest(),
        "platform_config_path": str(platform_config_path),
        "platform_config_digest": document_digest(platform_config),
        "operation_module_basename": module_basename,
        "operation_module_sha256": module_sha,
        "operation_id": operation_id,
        "request": copy.deepcopy(request),
        "operation_plan": copy.deepcopy(plan),
        "operation_plan_digest": verification["plan_digest"],
        "input_digests": _input_digests(plan),
    }
    return {**body, "binding_digest": document_digest(body)}


def verify_binding(
    binding: dict[str, Any],
    *,
    platform_id: str,
    profile_id: str,
    operations_module: ModuleType,
) -> dict[str, Any]:
    if not isinstance(binding, dict) or tuple(binding) != _KEYS:
        raise ControlledExecutionBindingError("binding shape is invalid")
    if binding["kind"] != "icp.controlled-execution-binding.v1" or binding["schema_version"] != 1:
        raise ControlledExecutionBindingError("binding identity is invalid")
    if binding["platform_id"] != platform_id or binding["profile_id"] != profile_id:
        raise ControlledExecutionBindingError("binding platform scope is invalid")
    manifest = _regular_file(binding["manifest_path"], "selection manifest")
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != binding["manifest_digest"]:
        raise ControlledExecutionBindingError("selection manifest digest mismatch")
    readiness_path = _regular_file(binding["entry_readiness_path"], "entry readiness")
    if hashlib.sha256(readiness_path.read_bytes()).hexdigest() != binding["entry_readiness_digest"]:
        raise ControlledExecutionBindingError("entry readiness digest mismatch")
    package_selection_path = _regular_file(binding["package_selection_path"], "package selection")
    if hashlib.sha256(package_selection_path.read_bytes()).hexdigest() != binding["package_selection_digest"]:
        raise ControlledExecutionBindingError("package selection digest mismatch")
    package_selection = _json_object(package_selection_path, "package selection")
    if (
        package_selection.get("kind") != "icp.platform-package-selection.v1"
        or package_selection.get("platform_id") != platform_id
        or package_selection.get("profile_id") != profile_id
    ):
        raise ControlledExecutionBindingError("package selection identity is invalid")
    platform_config_path, platform_config = _platform_config(binding["request"])
    if str(platform_config_path) != binding["platform_config_path"]:
        raise ControlledExecutionBindingError("platform config path mismatch")
    if document_digest(platform_config) != binding["platform_config_digest"]:
        raise ControlledExecutionBindingError("platform config digest mismatch")
    readiness = _json_object(readiness_path, "entry readiness")
    if _entry_runtime_config_digest(readiness) != binding["platform_config_digest"]:
        raise ControlledExecutionBindingError("platform config differs from entry readiness")
    module_basename, module_sha = _module_identity(operations_module)
    if binding["operation_module_basename"] != module_basename or binding["operation_module_sha256"] != module_sha:
        raise ControlledExecutionBindingError("operation module identity mismatch")
    rebuilt = operations_module.build(binding["operation_id"], copy.deepcopy(binding["request"]))
    if rebuilt != binding["operation_plan"]:
        raise ControlledExecutionBindingError("operation plan differs from bound request")
    _verify_runtime_projection(binding["operation_plan"], platform_config)
    verification = operations_module.verify_plan(binding["operation_plan"])
    if binding["operation_plan_digest"] != verification["plan_digest"]:
        raise ControlledExecutionBindingError("operation plan digest mismatch")
    if binding["input_digests"] != _input_digests(binding["operation_plan"]):
        raise ControlledExecutionBindingError("operation input digest mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", binding["binding_digest"]):
        raise ControlledExecutionBindingError("binding digest is invalid")
    body = {key: copy.deepcopy(binding[key]) for key in _KEYS[:-1]}
    if binding["binding_digest"] != document_digest(body):
        raise ControlledExecutionBindingError("binding digest mismatch")
    return copy.deepcopy(binding)


__all__ = [
    "ControlledExecutionBindingError",
    "document_digest",
    "prepare_binding",
    "verify_binding",
]
