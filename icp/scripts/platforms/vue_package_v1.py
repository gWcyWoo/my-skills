"""Inactive Vue/Vite PlatformPackage descriptor and conformance verifier."""

from __future__ import annotations

import ast
import hashlib
import stat
from pathlib import Path
from typing import Any

import icp_common as _common
from platforms import platform_package_contract_v1 as _contract
from platforms import vue_standard_v1 as _adapter_descriptor


PLATFORM_ID = "vue"
PROFILE_ID = "vue-vite"
_PLATFORM_ROOT = Path(__file__).parent
_COMPONENT_SPECS = (
    (
        "descriptor",
        "vue_standard_v1.py",
        "icp.vue-platform-adapter-descriptor.v1",
        ("describe", "verify_descriptor"),
    ),
    (
        "project_preflight",
        "vue_project_preflight_v1.py",
        "icp.vue-project-preflight.v1",
        ("preflight", "inspect_entry_requirements"),
    ),
    (
        "operation_plans",
        "vue_operations_v1.py",
        "icp.vue-operation-plan.v1",
        ("build", "verify_plan"),
    ),
    (
        "binding",
        "vue_execution_binding_v1.py",
        "icp.vue-execution-binding.v1",
        ("prepare_binding", "verify_binding"),
    ),
    (
        "authorization",
        "vue_execution_authorization_v1.py",
        "icp.vue-execution-authorization-candidate.v1",
        ("prepare_authorization", "verify_authorization"),
    ),
    (
        "executor",
        "vue_execution_executor_v1.py",
        "icp.vue-execution-report.v1",
        ("execute_authorization",),
    ),
)
_ENTRY_REQUIREMENTS = tuple(
    {
        "id": requirement_id,
        "owner": owner,
        "required": True,
        "sensitive": False,
        "probe_id": f"vue.project_preflight.{requirement_id}",
        "accepted_shape_id": accepted_shape_id,
        "remediation_id": remediation_id,
    }
    for requirement_id, owner, accepted_shape_id, remediation_id in (
        ("project_root", "user", "shape.existing_directory_under_workspace", "remediation.supply_project_root"),
        ("project_materials", "user", "shape.vue_vite_project_materials", "remediation.supply_vue_project_materials"),
        ("toolchain", "environment", "shape.node_npm_toolchain", "remediation.install_node_lts"),
        ("dependencies", "environment", "shape.vue_installed_dependencies", "remediation.run_npm_ci"),
        ("runtime_config", "user", "shape.vue_fixed_runtime_config", "remediation.none"),
        ("runtime_target", "environment", "shape.chrome_runtime_target", "remediation.install_chrome"),
    )
)


class VuePackageError(ValueError):
    """Raised when the fixed Vue PlatformPackage fails conformance."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VuePackageError("component file is unreadable") from exc
    return digest.hexdigest()


def _component_path(basename: str) -> Path:
    if Path(basename).name != basename or not basename.endswith("_v1.py"):
        raise VuePackageError("component basename is invalid")
    path = _PLATFORM_ROOT / basename
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_root = _PLATFORM_ROOT.resolve(strict=True)
    except OSError as exc:
        raise VuePackageError("component file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise VuePackageError("component must be a regular non-symlink file")
    if resolved.parent != resolved_root or resolved.name != basename:
        raise VuePackageError("component escaped the fixed platform root")
    return path


def _assert_public_api(path: Path, names: tuple[str, ...]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise VuePackageError("component source is invalid") from exc
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if any(name not in functions for name in names):
        raise VuePackageError("component public API is missing")


def _registry() -> dict[str, Any]:
    try:
        registries = _common.load_registries()
        platform = registries["platforms"][PLATFORM_ID]
    except (KeyError, TypeError, _common.ConfigError) as exc:
        raise VuePackageError("registry is invalid") from exc
    if platform != {
        "profiles": [PROFILE_ID],
        "default_profile": PROFILE_ID,
        "activated": True,
    }:
        raise VuePackageError("Vue registry profile must remain active and fixed")
    return registries


def _components() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role, basename, contract_kind, public_api in _COMPONENT_SPECS:
        path = _component_path(basename)
        result.append(
            {
                "role": role,
                "module_basename": basename,
                "module_sha256": _sha256(path),
                "contract_kind": contract_kind,
                "public_api": list(public_api),
            }
        )
    return result


def describe_package() -> dict[str, Any]:
    registries = _registry()
    adapter = _adapter_descriptor.describe()
    descriptor = {
        "kind": _contract.KIND_DESCRIPTOR,
        "schema_version": _contract.SCHEMA_VERSION,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": "active",
        "executable": True,
        "registry_digest": _contract.compute_registry_digest(registries),
        "selected_profile_digest": _contract.compute_selected_profile_digest(
            registries, PLATFORM_ID, PROFILE_ID
        ),
        "supported_task_sources": ["csv"],
        "supported_design_sources": ["lanhu-figma"],
        "actual_source_types": ["browser_screenshot"],
        "entry_requirements": [dict(item) for item in _ENTRY_REQUIREMENTS],
        "components": _components(),
        "ports": [
            {
                "id": item["id"],
                "capability_state": item["capability_state"],
                "implementation_state": item["implementation_state"],
                "provider_component_role": (
                    "project_preflight"
                    if item["id"] == "project_preflight"
                    else "operation_plans"
                ),
                "artifact_contracts": [],
            }
            for item in adapter["operations"]
        ],
    }
    _contract.validate_descriptor(descriptor)
    return descriptor


def verify_package() -> dict[str, Any]:
    descriptor = describe_package()
    _contract.validate_descriptor(descriptor)
    adapter_report = _adapter_descriptor.verify_descriptor()
    if adapter_report.get("ok") is not True:
        raise VuePackageError("Vue adapter descriptor verification failed")
    for _, basename, _, public_api in _COMPONENT_SPECS:
        _assert_public_api(_component_path(basename), public_api)
    current = describe_package()
    if current != descriptor:
        raise VuePackageError("Vue package changed during verification")
    return {
        "ok": True,
        "kind": "icp.platform-package-descriptor-verify.v1",
        "schema_version": 1,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "activation_state": "active",
        "executable": True,
        "package_digest": _contract.compute_descriptor_digest(descriptor),
        "registry_digest": descriptor["registry_digest"],
        "selected_profile_digest": descriptor["selected_profile_digest"],
        "components_total": len(descriptor["components"]),
        "ports_total": len(descriptor["ports"]),
        "entry_requirements_total": len(descriptor["entry_requirements"]),
    }
