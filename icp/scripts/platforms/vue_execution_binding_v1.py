"""Read-only Vue execution binding over current frozen evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import icp_common as _common
import platform_package_resolver_v1 as _resolver
import verify_selection_manifest_v1 as _selection
from platforms import vue_operations_v1 as _operations
from platforms import vue_package_v1 as _package
from platforms import vue_project_preflight_v1 as _preflight


KIND_BINDING = "icp.vue-execution-binding.v1"
KIND_VERIFY = "icp.vue-execution-binding-verify.v1"
SCHEMA_VERSION = 1
PLATFORM_ID = "vue"
PROFILE_ID = "vue-vite"
_ICP_ROOT = Path(__file__).parent.parent.parent
_INDEX_PATH = _ICP_ROOT / "references" / "platform_packages_v1.json"
_PACKAGE_PATH = Path(__file__).parent / "vue_package_v1.py"
_BINDING_KEYS = (
    "kind",
    "schema_version",
    "platform_id",
    "profile_id",
    "activation_state",
    "executable",
    "selection_manifest_path",
    "selection_manifest_sha256",
    "entry_readiness_path",
    "entry_readiness_sha256",
    "package_selection_path",
    "package_selection_sha256",
    "operation_id",
    "selection_verification",
    "package_resolution",
    "package_verification",
    "project_preflight",
    "request",
    "plan",
    "plan_verification",
)


class VueExecutionBindingError(ValueError):
    """Raised when current Vue evidence cannot produce an exact binding."""


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VueExecutionBindingError("package index contains duplicate keys")
        result[key] = value
    return result


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
        raise VueExecutionBindingError("binding data is not canonical JSON") from exc


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def document_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _adjacent_identity(manifest_path: str) -> tuple[Path, Path]:
    run_root = Path(manifest_path).resolve(strict=True).parent
    readiness_path = run_root / "entry-readiness.json"
    package_path = run_root / "platform-package-selection.json"
    for path, role in ((readiness_path, "entry readiness"), (package_path, "package selection")):
        if path.is_symlink() or not path.is_file():
            raise VueExecutionBindingError(f"{role} must be an adjacent regular file")
    try:
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
        package_selection = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VueExecutionBindingError("adjacent execution identity is invalid") from exc
    if readiness.get("kind") != "icp.entry-readiness-report.v1" or readiness.get("status") != "ready":
        raise VueExecutionBindingError("entry readiness is not ready")
    if (
        package_selection.get("kind") != "icp.platform-package-selection.v1"
        or package_selection.get("platform_id") != PLATFORM_ID
        or package_selection.get("profile_id") != PROFILE_ID
    ):
        raise VueExecutionBindingError("package selection identity is invalid")
    return readiness_path, package_path


def _load_index() -> dict[str, Any]:
    try:
        value = json.loads(
            _INDEX_PATH.read_text(encoding="utf-8"), object_pairs_hook=_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VueExecutionBindingError("fixed package index is invalid") from exc
    _resolver.verify_package_index(value)
    return value


def prepare_binding(
    *, manifest_path: str, operation_id: str, request: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(manifest_path, str) or not manifest_path:
        raise VueExecutionBindingError("manifest_path is invalid")
    if not isinstance(operation_id, str) or operation_id not in _operations.list_operation_ids():
        raise VueExecutionBindingError("operation_id is invalid")
    if not isinstance(request, dict):
        raise VueExecutionBindingError("request is invalid")
    try:
        selection = _selection.verify(manifest_path)
    except Exception as exc:  # noqa: BLE001 - normalize the fixed verifier boundary
        raise VueExecutionBindingError("selection manifest verification failed") from exc
    if selection.get("platform_id") != PLATFORM_ID or selection.get("profile_id") != PROFILE_ID:
        raise VueExecutionBindingError("selection manifest targets another platform")
    descriptor = _package.describe_package()
    package_verify = _package.verify_package()
    try:
        package_bytes = _PACKAGE_PATH.read_bytes()
    except OSError as exc:
        raise VueExecutionBindingError("fixed package module is unreadable") from exc
    resolution = _resolver.resolve_package(
        platform_id=PLATFORM_ID,
        profile_id=PROFILE_ID,
        registries=_common.load_registries(),
        package_index=_load_index(),
        package_descriptor=descriptor,
        package_module_bytes=package_bytes,
    )
    if resolution["activation_state"] != "active" or resolution["executable"] is not True:
        raise VueExecutionBindingError("Vue package must be active and executable")
    if request.get("project_root") != selection["project_root"]:
        raise VueExecutionBindingError("request project_root differs from selection")
    if request.get("run_root") != selection["run_root"]:
        raise VueExecutionBindingError("request run_root differs from selection")
    project_preflight = _preflight.preflight(selection["project_root"])
    plan = _operations.build(operation_id, _clone(request))
    plan_verify = _operations.verify_plan(plan)
    readiness_path, package_path = _adjacent_identity(selection["manifest_path"])
    return {
        "kind": KIND_BINDING,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": resolution["activation_state"],
        "executable": resolution["executable"],
        "selection_manifest_path": selection["manifest_path"],
        "selection_manifest_sha256": selection["manifest_sha256"],
        "entry_readiness_path": str(readiness_path),
        "entry_readiness_sha256": hashlib.sha256(readiness_path.read_bytes()).hexdigest(),
        "package_selection_path": str(package_path),
        "package_selection_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "operation_id": operation_id,
        "selection_verification": _clone(selection),
        "package_resolution": _clone(resolution),
        "package_verification": _clone(package_verify),
        "project_preflight": _clone(project_preflight),
        "request": _clone(request),
        "plan": _clone(plan),
        "plan_verification": _clone(plan_verify),
    }


def verify_binding(binding: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, dict) or tuple(binding) != _BINDING_KEYS:
        raise VueExecutionBindingError("binding shape is invalid")
    if binding.get("kind") != KIND_BINDING or binding.get("schema_version") != 1:
        raise VueExecutionBindingError("binding identity is invalid")
    if binding.get("platform_id") != PLATFORM_ID or binding.get("profile_id") != PROFILE_ID:
        raise VueExecutionBindingError("binding platform identity is invalid")
    if binding.get("activation_state") != "active" or binding.get("executable") is not True:
        raise VueExecutionBindingError("binding must be active and executable")
    rebuilt = prepare_binding(
        manifest_path=binding["selection_manifest_path"],
        operation_id=binding["operation_id"],
        request=_clone(binding["request"]),
    )
    if rebuilt != binding:
        raise VueExecutionBindingError("binding differs from current verified evidence")
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "operation_id": binding["operation_id"],
        "binding_digest": document_digest(binding),
    }
