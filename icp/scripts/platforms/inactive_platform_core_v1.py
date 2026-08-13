#!/usr/bin/env python3
"""Shared factories for selectable but deliberately inactive ICP platform packages."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from platforms import platform_package_contract_v1 as package_contract


class InactivePlatformError(ValueError):
    def __init__(self, message: str, *, missing_requirements: tuple[str, ...] = ()):
        super().__init__(message)
        self.missing_requirements = missing_requirements


PORTS = (
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
CAPABILITY_STATES = {
    "project_preflight": "required",
    "visible_codegen": "required",
    "fixture_codegen": "required",
    "trace_harness": "optional-with-shared-policy",
    "packaging": "required",
    "test_runner": "required",
    "runtime_capture": "optional-with-shared-policy",
    "project_gates": "required",
    "fan_in": "required",
}
OPERATION_PORTS = PORTS[1:]
_SAFE_ID = re.compile(r"[a-z][a-z0-9_.-]{0,127}")


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _platform_slug(platform_id: str) -> str:
    return platform_id.replace("-", "_")


def describe_adapter(
    platform_id: str,
    profile_id: str,
    *,
    activation_state: str = "inactive",
    executable: bool = False,
) -> dict:
    return {
        "kind": f"icp.{platform_id}-platform-adapter-descriptor.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "activation_state": activation_state,
        "executable": executable,
        "operations": [
            {
                "id": port,
                "capability_state": CAPABILITY_STATES[port],
                "implementation_state": "implemented",
            }
            for port in PORTS
        ],
    }


def verify_adapter(
    document: dict,
    platform_id: str,
    profile_id: str,
    *,
    activation_state: str = "inactive",
    executable: bool = False,
) -> None:
    if document != describe_adapter(
        platform_id,
        profile_id,
        activation_state=activation_state,
        executable=executable,
    ):
        raise InactivePlatformError("platform adapter descriptor drift")


def _ordinary_root(project_root: Path | str) -> Path:
    root = Path(project_root)
    if not root.is_absolute():
        raise InactivePlatformError("project_root must be absolute")
    try:
        canonical = root.resolve(strict=True)
    except OSError as exc:
        raise InactivePlatformError("project_root is unavailable") from exc
    if canonical != root or root.is_symlink() or not root.is_dir():
        raise InactivePlatformError("project_root must be canonical, non-symlinked directory")
    return root


def _has_extension(root: Path, suffixes: tuple[str, ...]) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix in suffixes:
            return True
    return False


def _platform_config(root: Path, platform_id: str) -> tuple[dict, str]:
    path = root / ".icp" / "platform-config.json"
    if path.is_symlink() or not path.is_file():
        raise InactivePlatformError("missing entry requirements: .icp/platform-config.json")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InactivePlatformError("platform config is invalid") from exc
    if not isinstance(document, dict):
        raise InactivePlatformError("platform config must be an object")
    expected_keys = {
        "nextjs": ("route", "viewport_width", "viewport_height"),
        "ios-swift": ("project", "scheme", "simulator_udid", "app_product", "bundle_id"),
        "ios-objc": ("project", "scheme", "simulator_udid", "app_product", "bundle_id"),
        "android-kotlin": ("module", "variant", "device_serial", "application_id", "activity", "apk_path"),
        "android-java": ("module", "variant", "device_serial", "application_id", "activity", "apk_path"),
    }[platform_id]
    if tuple(document) != expected_keys:
        raise InactivePlatformError("platform config shape is invalid")
    return document, _sha(document)


def _probe_next_runtime(
    root: Path,
    config: dict,
    missing: list[str],
    toolchain: list[dict[str, str]],
) -> None:
    if not isinstance(config["route"], str) or not config["route"].startswith("/"):
        missing.append("platform-config:route")
    for field in ("viewport_width", "viewport_height"):
        value = config[field]
        if type(value) is not int or not 240 <= value <= 4096:
            missing.append("platform-config:" + field)
    chrome = next(
        (
            path
            for path in (
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            )
            if path.is_file() and os.access(path, os.X_OK)
        ),
        None,
    )
    if chrome is None:
        missing.append("tool:chrome")
    else:
        toolchain.append({"id": "chrome", "path": str(chrome.resolve(strict=True))})
    for relative in ("package-lock.json", "node_modules/next", "node_modules/react"):
        path = root / relative
        if not path.exists() or path.is_symlink():
            missing.append(relative)


def _probe_ios_runtime(
    root: Path,
    config: dict,
    missing: list[str],
    tools: dict[str, str],
) -> None:
    project = config["project"]
    if not isinstance(project, str) or not project.endswith(".xcodeproj") or not (root / project).is_dir():
        missing.append("platform-config:project")
    for field in ("scheme", "simulator_udid", "app_product", "bundle_id"):
        if not isinstance(config[field], str) or not config[field] or "\n" in config[field]:
            missing.append("platform-config:" + field)
    if "xcrun" in tools and isinstance(config["simulator_udid"], str):
        result = subprocess.run(
            [tools["xcrun"], "simctl", "list", "devices", "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        if result.returncode != 0 or config["simulator_udid"].encode() not in result.stdout:
            missing.append("runtime:simulator_udid")


def _probe_android_runtime(
    root: Path,
    config: dict,
    missing: list[str],
    tools: dict[str, str],
) -> None:
    for field in ("module", "variant", "device_serial", "application_id", "activity", "apk_path"):
        if not isinstance(config[field], str) or not config[field] or "\n" in config[field]:
            missing.append("platform-config:" + field)
    apk = Path(config["apk_path"]) if isinstance(config["apk_path"], str) else Path("/")
    if apk.is_absolute() or ".." in apk.parts or apk.suffix != ".apk":
        missing.append("platform-config:apk_path")
    gradlew = root / "gradlew"
    if gradlew.is_file() and not os.access(gradlew, os.X_OK):
        missing.append("gradlew:executable")
    if "adb" in tools and isinstance(config["device_serial"], str):
        result = subprocess.run(
            [tools["adb"], "devices"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        expected = (config["device_serial"] + "\tdevice").encode()
        if result.returncode != 0 or expected not in result.stdout:
            missing.append("runtime:device_serial")


def preflight(platform_id: str, profile_id: str, project_root: Path | str) -> dict:
    root = _ordinary_root(project_root)
    missing: list[str] = []
    toolchain: list[dict[str, str]] = []
    resolved_tools: dict[str, str] = {}
    try:
        config, platform_config_digest = _platform_config(root, platform_id)
    except InactivePlatformError as exc:
        config = None
        platform_config_digest = None
        detail = str(exc)
        missing.append(
            ".icp/platform-config.json"
            if ".icp/platform-config.json" in detail
            else "platform-config:invalid"
        )
    if platform_id == "nextjs":
        markers = ("package.json", "next.config.js")
        tools = ("node", "npm")
    elif platform_id in {"ios-swift", "ios-objc"}:
        markers = ()
        tools = ("xcodebuild", "xcrun")
        if not any(path.suffix == ".xcodeproj" and path.is_dir() for path in root.iterdir()):
            missing.append("*.xcodeproj")
        extension = (".swift",) if platform_id == "ios-swift" else (".m", ".mm")
        if not _has_extension(root, extension):
            missing.append("source:" + "/".join(extension))
    else:
        markers = ("gradlew",)
        tools = ("java", "adb")
        if not any((root / name).is_file() for name in ("settings.gradle", "settings.gradle.kts")):
            missing.append("settings.gradle|settings.gradle.kts")
        extension = (".java",) if platform_id == "android-java" else (".kt",)
        if not _has_extension(root, extension):
            missing.append("source:" + extension[0])
    for marker in markers:
        path = root / marker
        if not path.exists() or path.is_symlink():
            missing.append(marker)
    for tool in tools:
        executable = shutil.which(tool)
        if executable is None:
            missing.append("tool:" + tool)
        else:
            canonical = str(Path(executable).resolve(strict=True))
            resolved_tools[tool] = canonical
            toolchain.append({"id": tool, "path": canonical})
    if config is None:
        missing.append("deferred:runtime_target")
    elif platform_id in {"ios-swift", "ios-objc"} and "xcrun" not in resolved_tools:
        missing.append("deferred:runtime_target")
    elif platform_id in {"android-java", "android-kotlin"} and "adb" not in resolved_tools:
        missing.append("deferred:runtime_target")
    if platform_id == "nextjs" and (root / "package.json").is_file():
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except Exception:
            package = None
            missing.append("package.json:invalid")
        if package is not None:
            dependencies = package.get("dependencies", {})
            if not isinstance(dependencies, dict) or "next" not in dependencies or "react" not in dependencies:
                missing.append("dependencies:next+react")
            scripts = package.get("scripts", {})
            for script in ("dev", "test", "build"):
                if not isinstance(scripts, dict) or not isinstance(scripts.get(script), str) or not scripts[script]:
                    missing.append("script:" + script)
    if platform_id == "nextjs":
        for installed in (
            "package-lock.json",
            "node_modules/next/package.json",
            "node_modules/react/package.json",
        ):
            if not (root / installed).is_file():
                missing.append("installation:" + installed)
        if config is not None:
            _probe_next_runtime(root, config, missing, toolchain)
    elif platform_id in {"ios-swift", "ios-objc"}:
        if config is not None:
            _probe_ios_runtime(root, config, missing, resolved_tools)
    else:
        if config is not None:
            _probe_android_runtime(root, config, missing, resolved_tools)
        for wrapper_file in (
            "gradle/wrapper/gradle-wrapper.jar",
            "gradle/wrapper/gradle-wrapper.properties",
        ):
            if not (root / wrapper_file).is_file():
                missing.append("installation:" + wrapper_file)
    if missing:
        ordered_missing = tuple(sorted(set(missing)))
        raise InactivePlatformError(
            "missing entry requirements: " + ", ".join(ordered_missing),
            missing_requirements=ordered_missing,
        )
    assert platform_config_digest is not None
    return {
        "kind": f"icp.{platform_id}-project-preflight.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "project_root": str(root),
        "platform_config_digest": platform_config_digest,
        "toolchain": toolchain,
        "status": "pass",
    }


def inspect_entry_requirements(
    platform_id: str, profile_id: str, project_root: Path | str
) -> dict:
    try:
        report = preflight(platform_id, profile_id, project_root)
    except InactivePlatformError as exc:
        raw_missing = exc.missing_requirements
        if not raw_missing:
            raw_missing = ("project_root",)
        grouped: dict[str, list[str]] = {}
        for item in raw_missing:
            if "platform-config" in item:
                requirement_id = "runtime_config"
            elif item.startswith("tool:"):
                requirement_id = "toolchain"
            elif item.startswith(("device:", "simulator:", "browser:", "deferred:runtime_target")):
                requirement_id = "runtime_target"
            elif item.startswith(("dependencies:", "script:", "installation:")):
                requirement_id = "dependencies"
            elif item == "project_root":
                requirement_id = "project_root"
            else:
                requirement_id = "project_materials"
            grouped.setdefault(requirement_id, []).append(item)
        missing_inputs = []
        for requirement_id in sorted(grouped):
            owner = "environment" if requirement_id in {"toolchain", "dependencies", "runtime_target"} else "user"
            missing_inputs.append(
                {
                    "id": requirement_id,
                    "owner": owner,
                    "remediation": f"resolve selected {platform_id} {requirement_id}",
                    "detail": ", ".join(sorted(grouped[requirement_id])),
                }
            )
        return {
            "kind": f"icp.{platform_id}-entry-requirements-inspection.v1",
            "schema_version": 1,
            "platform_id": platform_id,
            "profile_id": profile_id,
            "platform_report": None,
            "missing_inputs": missing_inputs,
        }
    return {
        "kind": f"icp.{platform_id}-entry-requirements-inspection.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "platform_report": report,
        "missing_inputs": [],
    }


def operation_ids(platform_id: str) -> tuple[str, ...]:
    return tuple(f"{platform_id}.{port}.v1" for port in OPERATION_PORTS)


def _safe_artifacts(root: Path, values: dict, *, output: bool) -> dict[str, str]:
    if not isinstance(values, dict) or not values:
        raise InactivePlatformError("artifact map must be non-empty")
    result: dict[str, str] = {}
    for artifact_id in sorted(values):
        spec = values[artifact_id]
        if not _SAFE_ID.fullmatch(artifact_id) or not isinstance(spec, dict) or tuple(spec) != ("root", "path"):
            raise InactivePlatformError("artifact specification is invalid")
        relative = Path(spec["path"])
        if spec["root"] not in {"project", "run"} or relative.is_absolute() or ".." in relative.parts:
            raise InactivePlatformError("artifact path is unsafe")
        base = root[0] if spec["root"] == "project" else root[1]
        target = base / relative
        parent = target.parent.resolve(strict=True)
        if base not in (parent, *parent.parents):
            raise InactivePlatformError("artifact path escapes its root")
        if not output:
            metadata = target.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise InactivePlatformError("input artifact is not a regular file")
        elif target.exists() and (target.is_symlink() or not target.is_file()):
            raise InactivePlatformError("output artifact target is unsafe")
        result[artifact_id] = str(target)
    return result


def build_plan(platform_id: str, profile_id: str, operation_id: str, request: dict) -> dict:
    if operation_id not in operation_ids(platform_id):
        raise InactivePlatformError("operation id is unsupported")
    if not isinstance(request, dict) or tuple(request) != (
        "project_root",
        "run_root",
        "feature_id",
        "inputs",
        "outputs",
    ):
        raise InactivePlatformError("operation request shape is invalid")
    project_root = _ordinary_root(request["project_root"])
    run_root = _ordinary_root(request["run_root"])
    if not _SAFE_ID.fullmatch(request["feature_id"]):
        raise InactivePlatformError("feature id is invalid")
    inputs = _safe_artifacts((project_root, run_root), request["inputs"], output=False)
    outputs = _safe_artifacts((project_root, run_root), request["outputs"], output=True)
    port = operation_id[len(platform_id) + 1 : -3]
    return {
        "kind": f"icp.{platform_id}-operation-plan.v1",
        "schema_version": 1,
        "operation_id": operation_id,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "request_digest": _sha(request),
        "steps": [
            {
                "step_id": port,
                "action": f"{_platform_slug(platform_id)}_{port}",
                "inputs": inputs,
                "outputs": outputs,
            }
        ],
    }


def verify_plan(platform_id: str, profile_id: str, plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("platform_id") != platform_id or plan.get("profile_id") != profile_id:
        raise InactivePlatformError("operation plan scope is invalid")
    if plan.get("kind") != f"icp.{platform_id}-operation-plan.v1" or plan.get("schema_version") != 1:
        raise InactivePlatformError("operation plan identity is invalid")
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or plan.get("operation_id") not in operation_ids(platform_id):
        raise InactivePlatformError("operation plan steps are invalid")
    return {
        "kind": f"icp.{platform_id}-operation-plan-verify.v1",
        "schema_version": 1,
        "plan_digest": _sha(plan),
    }


def _component(basename: str, role: str, contract_kind: str, public_api: list[str]) -> dict:
    path = Path(__file__).resolve().parent / basename
    return {
        "role": role,
        "module_basename": basename,
        "module_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "contract_kind": contract_kind,
        "public_api": public_api,
    }


def describe_package(
    *,
    platform_id: str,
    profile_id: str,
    stem: str,
    actual_source_type: str,
    toolchain_shape: str,
    activation_state: str = "inactive",
    executable: bool = False,
    binding_basename: str = "inactive_execution_binding_v1.py",
    authorization_basename: str = "inactive_execution_authorization_v1.py",
    executor_basename: str = "inactive_execution_executor_v1.py",
) -> dict:
    registry_path = Path(__file__).resolve().parents[2] / "references" / "registries.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    descriptor = {
        "kind": "icp.platform-package-descriptor.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "activation_state": activation_state,
        "executable": executable,
        "registry_digest": package_contract.compute_registry_digest(registry),
        "selected_profile_digest": package_contract.compute_selected_profile_digest(
            registry, platform_id, profile_id
        ),
        "supported_task_sources": ["csv"],
        "supported_design_sources": ["lanhu-figma"],
        "actual_source_types": [actual_source_type],
        "entry_requirements": [
            {
                "id": requirement_id,
                "owner": owner,
                "required": True,
                "sensitive": False,
                "probe_id": f"{platform_id}.project_preflight.{requirement_id}",
                "accepted_shape_id": accepted_shape_id,
                "remediation_id": remediation_id,
            }
            for requirement_id, owner, accepted_shape_id, remediation_id in (
                ("project_root", "user", "shape.existing_directory_under_workspace", "remediation.supply_project_root"),
                ("project_materials", "user", f"shape.{_platform_slug(platform_id)}_project_materials", f"remediation.supply_{_platform_slug(platform_id)}_project_materials"),
                ("toolchain", "environment", toolchain_shape, f"remediation.install_{_platform_slug(platform_id)}_toolchain"),
                ("dependencies", "environment", f"shape.{_platform_slug(platform_id)}_installed_dependencies", f"remediation.install_{_platform_slug(platform_id)}_dependencies"),
                ("runtime_config", "user", f"shape.{_platform_slug(platform_id)}_runtime_config", f"remediation.supply_{_platform_slug(platform_id)}_runtime_config"),
                ("runtime_target", "environment", f"shape.{_platform_slug(platform_id)}_runtime_target", f"remediation.prepare_{_platform_slug(platform_id)}_runtime_target"),
            )
        ],
        "components": [
            _component(f"{stem}_standard_v1.py", "descriptor", f"icp.{platform_id}-platform-adapter-descriptor.v1", ["describe", "verify_descriptor"]),
            _component(f"{stem}_project_preflight_v1.py", "project_preflight", f"icp.{platform_id}-project-preflight.v1", ["preflight", "inspect_entry_requirements"]),
            _component(f"{stem}_operations_v1.py", "operation_plans", f"icp.{platform_id}-operation-plan.v1", ["build", "verify_plan"]),
            _component(binding_basename, "binding", f"icp.{platform_id}-execution-binding.v1", ["prepare_binding", "verify_binding"]),
            _component(authorization_basename, "authorization", f"icp.{platform_id}-execution-authorization.v1", ["prepare_authorization", "verify_authorization"]),
            _component(executor_basename, "executor", f"icp.{platform_id}-execution-report.v1", ["execute_authorization"]),
        ],
        "ports": [
            {
                "id": port,
                "capability_state": CAPABILITY_STATES[port],
                "implementation_state": "implemented",
                "provider_component_role": "project_preflight" if port == "project_preflight" else "operation_plans",
                "artifact_contracts": [],
            }
            for port in PORTS
        ],
    }
    package_contract.validate_descriptor(descriptor)
    return descriptor


def verify_package(document: dict) -> dict:
    package_contract.validate_descriptor(document)
    return {
        "ok": True,
        "kind": "icp.platform-package-descriptor-verify.v1",
        "schema_version": 1,
        "platform_id": document["platform_id"],
        "profile_id": document["profile_id"],
        "activation_state": document["activation_state"],
        "executable": document["executable"],
        "package_digest": package_contract.compute_descriptor_digest(document),
    }
