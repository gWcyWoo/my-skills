"""Read-only Vue/Vite project and Node toolchain preflight."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


KIND_REPORT = "icp.vue-project-preflight.v1"
SCHEMA_VERSION = 1
OPERATION_ID = "vue.project_preflight.v1"
PLATFORM_ID = "vue"
PROFILE_ID = "vue-vite"
_MAX_PACKAGE_JSON_BYTES = 2 * 1024 * 1024
_MAX_VERSION_BYTES = 1024 * 1024
_REQUIRED_SCRIPTS = ("dev", "build", "test:unit", "test:e2e")


class VueProjectPreflightError(ValueError):
    """Raised when the selected project cannot safely run the Vue profile."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VueProjectPreflightError("package.json contains duplicate keys")
        result[key] = value
    return result


def _canonical_directory(value: str | os.PathLike[str], *, role: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or not os.path.isabs(raw):
        raise VueProjectPreflightError(f"{role} must be an absolute directory")
    lexical = Path(os.path.abspath(raw))
    if str(lexical) != raw:
        raise VueProjectPreflightError(f"{role} must be lexically normalized")
    try:
        resolved = lexical.resolve(strict=True)
        metadata = lexical.lstat()
    except OSError as exc:
        raise VueProjectPreflightError(f"{role} is unavailable") from exc
    if resolved != lexical or stat.S_ISLNK(metadata.st_mode):
        raise VueProjectPreflightError(f"{role} must not use symlinks")
    if not stat.S_ISDIR(metadata.st_mode):
        raise VueProjectPreflightError(f"{role} must be a directory")
    return lexical


def _safe_child(root: Path, relative: str, *, directory: bool) -> Path:
    target = root / relative
    try:
        resolved = target.resolve(strict=True)
        metadata = target.lstat()
    except OSError as exc:
        raise VueProjectPreflightError(f"required project artifact is unavailable: {relative}") from exc
    if resolved != target or stat.S_ISLNK(metadata.st_mode):
        raise VueProjectPreflightError(f"required project artifact uses a symlink: {relative}")
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected:
        raise VueProjectPreflightError(f"required project artifact has wrong type: {relative}")
    return target


def _load_package_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise VueProjectPreflightError("package.json is unreadable") from exc
    if len(data) > _MAX_PACKAGE_JSON_BYTES:
        raise VueProjectPreflightError("package.json is too large")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VueProjectPreflightError("package.json is invalid") from exc
    if not isinstance(value, dict):
        raise VueProjectPreflightError("package.json root must be an object")
    return value, data


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VueProjectPreflightError(f"package.json {field} is invalid")
    return value


def _validate_package(value: dict[str, Any]) -> str:
    package_name = _nonempty_string(value.get("name"), field="name")
    scripts = value.get("scripts")
    if not isinstance(scripts, dict):
        raise VueProjectPreflightError("package.json scripts is invalid")
    for script_name in _REQUIRED_SCRIPTS:
        _nonempty_string(scripts.get(script_name), field=f"scripts.{script_name}")
    dependencies = value.get("dependencies")
    dev_dependencies = value.get("devDependencies")
    if not isinstance(dependencies, dict) or "vue" not in dependencies:
        raise VueProjectPreflightError("package.json must declare vue")
    if not isinstance(dev_dependencies, dict):
        raise VueProjectPreflightError("package.json devDependencies is invalid")
    for dependency in ("vite", "vitest", "@playwright/test"):
        if dependency not in dev_dependencies:
            raise VueProjectPreflightError(f"package.json must declare {dependency}")
    return package_name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VueProjectPreflightError("toolchain executable is unreadable") from exc
    return digest.hexdigest()


def _probe_tool(name: str, project_root: Path) -> tuple[str, str, str]:
    located = shutil.which(name)
    if not located:
        raise VueProjectPreflightError(f"required toolchain executable is missing: {name}")
    try:
        executable = Path(located).resolve(strict=True)
        metadata = executable.stat()
    except OSError as exc:
        raise VueProjectPreflightError(f"required toolchain executable is invalid: {name}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(executable, os.X_OK):
        raise VueProjectPreflightError(f"required toolchain executable is invalid: {name}")
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            cwd=project_root,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VueProjectPreflightError(f"toolchain version probe failed: {name}") from exc
    if completed.returncode != 0 or len(completed.stdout) > _MAX_VERSION_BYTES:
        raise VueProjectPreflightError(f"toolchain version probe failed: {name}")
    try:
        version = completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise VueProjectPreflightError(f"toolchain version probe failed: {name}") from exc
    if not version or "\n" in version or "\r" in version:
        raise VueProjectPreflightError(f"toolchain version probe failed: {name}")
    return str(executable), _sha256_file(executable), version


def inspect_entry_requirements(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    missing: list[dict[str, str]] = []
    try:
        root = _canonical_directory(project_root, role="project root")
    except Exception:
        root = None
        missing.append(
            {
                "id": "project_root",
                "owner": "user",
                "remediation": "supply a canonical Vue project directory",
                "detail": "project root is missing, invalid, or symlinked",
            }
        )
    report = None
    if root is not None:
        project_files = ("package.json", "index.html", "src")
        absent_project = [name for name in project_files if not (root / name).exists()]
        if absent_project:
            missing.append(
                {
                    "id": "project_materials",
                    "owner": "user",
                    "remediation": "supply the complete Vue/Vite project",
                    "detail": "missing: " + ", ".join(absent_project),
                }
            )
        absent_tools = [name for name in ("node", "npm") if shutil.which(name) is None]
        if absent_tools:
            missing.append(
                {
                    "id": "toolchain",
                    "owner": "environment",
                    "remediation": "install Node.js and npm",
                    "detail": "missing tools: " + ", ".join(absent_tools),
                }
            )
        dependency_files = (
            "package-lock.json",
            "node_modules/vue/package.json",
            "node_modules/vite/package.json",
            "node_modules/vitest/package.json",
            "node_modules/@playwright/test/package.json",
        )
        absent_dependencies = [name for name in dependency_files if not (root / name).is_file()]
        if absent_dependencies:
            missing.append(
                {
                    "id": "dependencies",
                    "owner": "environment",
                    "remediation": "run npm ci in project_root",
                    "detail": "missing: " + ", ".join(absent_dependencies),
                }
            )
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome.is_file():
            missing.append(
                {
                    "id": "runtime_target",
                    "owner": "environment",
                    "remediation": "install Google Chrome",
                    "detail": "Google Chrome executable is unavailable",
                }
            )
        if not missing:
            try:
                report = preflight(root)
            except Exception:
                missing.append(
                    {
                        "id": "project_materials",
                        "owner": "user",
                        "remediation": "repair the selected Vue project",
                        "detail": "Vue project validation failed",
                    }
                )
    return {
        "kind": "icp.vue-entry-requirements-inspection.v1",
        "schema_version": 1,
        "platform_id": "vue",
        "profile_id": "vue-vite",
        "platform_report": report,
        "missing_inputs": sorted(missing, key=lambda item: item["id"]),
    }


def preflight(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = _canonical_directory(project_root, role="project_root")
    package_path = _safe_child(root, "package.json", directory=False)
    _safe_child(root, "index.html", directory=False)
    _safe_child(root, "src", directory=True)
    _safe_child(root, "src/main.js", directory=False)
    _safe_child(root, "src/App.vue", directory=False)
    _safe_child(root, "tests/unit", directory=True)
    _safe_child(root, "tests/e2e", directory=True)
    package, package_bytes = _load_package_json(package_path)
    package_name = _validate_package(package)
    node_path, node_sha, node_version = _probe_tool("node", root)
    npm_path, npm_sha, npm_version = _probe_tool("npm", root)
    return {
        "kind": KIND_REPORT,
        "schema_version": SCHEMA_VERSION,
        "operation_id": OPERATION_ID,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "project_root": str(root),
        "project": {
            "package_json": "package.json",
            "package_json_sha256": hashlib.sha256(package_bytes).hexdigest(),
            "package_name": package_name,
            "source_directory": "src",
            "unit_test_directory": "tests/unit",
            "e2e_test_directory": "tests/e2e",
        },
        "toolchain": {
            "node_executable": node_path,
            "node_executable_sha256": node_sha,
            "node_version": node_version,
            "npm_executable": npm_path,
            "npm_executable_sha256": npm_sha,
            "npm_version": npm_version,
        },
    }
