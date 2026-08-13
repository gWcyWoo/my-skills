"""Deterministic, non-executable Vue/Vite operation plans."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


KIND_PLAN = "icp.vue-operation-plan.v1"
KIND_VERIFY = "icp.vue-operation-plan-verify.v1"
SCHEMA_VERSION = 1
PLATFORM_ID = "vue"
PROFILE_ID = "vue-vite"
_VISIBLE_OPERATION = "vue.visible_codegen.v1"
_FIXTURE_OPERATION = "vue.fixture_codegen.v1"
_OPERATION_IDS = (
    _VISIBLE_OPERATION,
    _FIXTURE_OPERATION,
    "vue.trace_harness.v1",
    "vue.packaging.v1",
    "vue.test_runner.v1",
    "vue.runtime_capture.v1",
    "vue.project_gates.v1",
    "vue.fan_in.v1",
)
_SAFE_ID = re.compile(r"[a-z][a-z0-9_]*")
_BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_FORBIDDEN_KEYS = frozenset(
    {
        "args",
        "argv",
        "command",
        "env",
        "environment",
        "executable",
        "interpreter",
        "prompt",
        "runner",
        "script",
        "shell",
    }
)
_PLAN_KEYS = (
    "kind",
    "schema_version",
    "operation_id",
    "platform_id",
    "profile_id",
    "request_digest",
    "steps",
)
_STEP_KEYS = ("step_id", "action", "inputs", "outputs")
_VISIBLE_REQUEST_KEYS = frozenset(
    {
        "project_root",
        "run_root",
        "feature_id",
        "design_bundle",
        "requirement_contract",
        "sfc_out",
        "css_out",
    }
)
_FIXTURE_REQUEST_KEYS = frozenset(
    {
        "project_root",
        "run_root",
        "feature_id",
        "visual_contract",
        "fixture_out",
    }
)
_REQUEST_KEYS = {
    _VISIBLE_OPERATION: _VISIBLE_REQUEST_KEYS,
    _FIXTURE_OPERATION: _FIXTURE_REQUEST_KEYS,
    "vue.trace_harness.v1": frozenset(
        {"project_root", "run_root", "route", "dom_trace_out"}
    ),
    "vue.packaging.v1": frozenset(
        {"project_root", "run_root", "assets_manifest", "receipt_out"}
    ),
    "vue.test_runner.v1": frozenset(
        {"project_root", "run_root", "phase", "evidence_out"}
    ),
    "vue.runtime_capture.v1": frozenset(
        {
            "project_root",
            "run_root",
            "route",
            "viewport",
            "actual_out",
            "provenance_out",
        }
    ),
    "vue.project_gates.v1": frozenset(
        {"project_root", "run_root", "report_out"}
    ),
    "vue.fan_in.v1": frozenset(
        {"project_root", "run_root", "mutation_manifest", "receipt_out"}
    ),
}
_VARIANT_SHAPES = {
    _VISIBLE_OPERATION: (
        "render_vue_feature",
        "render_vue_feature",
        ("design_bundle", "requirement_contract"),
        ("sfc", "css"),
    ),
    _FIXTURE_OPERATION: (
        "render_vue_fixture",
        "render_vue_fixture",
        ("visual_contract",),
        ("fixture",),
    ),
    "vue.trace_harness.v1": (
        "capture_dom_trace",
        "capture_dom_trace",
        ("route",),
        ("trace",),
    ),
    "vue.packaging.v1": (
        "prepare_vue_packaging",
        "prepare_vue_packaging",
        ("assets_manifest",),
        ("receipt",),
    ),
    "vue.test_runner.v1": (
        "run_vue_tests",
        "run_vue_tests",
        ("phase",),
        ("evidence",),
    ),
    "vue.runtime_capture.v1": (
        "capture_browser_screenshot",
        "capture_browser_screenshot",
        ("route", "viewport"),
        ("actual", "provenance"),
    ),
    "vue.project_gates.v1": (
        "run_vue_project_gates",
        "run_vue_project_gates",
        (),
        ("report",),
    ),
    "vue.fan_in.v1": (
        "apply_vue_fan_in",
        "apply_vue_fan_in",
        ("mutation_manifest",),
        ("receipt",),
    ),
}


class VueOperationPlanError(ValueError):
    """Raised when a Vue operation request or plan is invalid."""


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
        raise VueOperationPlanError("value is not canonical JSON data") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise VueOperationPlanError("request contains a forbidden key")
            _reject_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        _canonical_bytes(value)
    else:
        raise VueOperationPlanError("request contains unsupported data")


def _canonical_directory(value: Any, *, role: str) -> Path:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        raise VueOperationPlanError(f"{role} must be an absolute directory")
    lexical = Path(os.path.abspath(value))
    if str(lexical) != value:
        raise VueOperationPlanError(f"{role} must be lexically normalized")
    try:
        resolved = lexical.resolve(strict=True)
        metadata = lexical.lstat()
    except OSError as exc:
        raise VueOperationPlanError(f"{role} is unavailable") from exc
    if resolved != lexical or stat.S_ISLNK(metadata.st_mode):
        raise VueOperationPlanError(f"{role} must not use symlinks")
    if not stat.S_ISDIR(metadata.st_mode):
        raise VueOperationPlanError(f"{role} must be a directory")
    return lexical


def _validate_roots(project_root: Path, run_root: Path) -> None:
    if project_root == run_root:
        raise VueOperationPlanError("project_root and run_root must differ")
    try:
        relative = run_root.relative_to(project_root)
    except ValueError:
        try:
            project_root.relative_to(run_root)
        except ValueError:
            return
        raise VueOperationPlanError("project_root must not be inside run_root")
    parts = relative.parts
    if len(parts) != 3 or parts[:2] != (".icp", "runs"):
        raise VueOperationPlanError("internal run_root is not canonical")
    if _BATCH_ID.fullmatch(parts[2]) is None:
        raise VueOperationPlanError("internal run_root batch id is invalid")


def _relative_path(value: Any, *, extension: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise VueOperationPlanError("relative path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise VueOperationPlanError("relative path is invalid")
    if path.suffix != extension:
        raise VueOperationPlanError("relative path extension is invalid")
    return path


def _existing_input(root: Path, value: Any, *, extension: str) -> Path:
    relative = _relative_path(value, extension=extension)
    target = root.joinpath(*relative.parts)
    try:
        resolved = target.resolve(strict=True)
        metadata = target.lstat()
    except OSError as exc:
        raise VueOperationPlanError("required input is unavailable") from exc
    if resolved != target or stat.S_ISLNK(metadata.st_mode):
        raise VueOperationPlanError("required input must not use symlinks")
    if not stat.S_ISREG(metadata.st_mode):
        raise VueOperationPlanError("required input must be a regular file")
    return target


def _safe_output(root: Path, value: Any, *, extension: str) -> Path:
    relative = _relative_path(value, extension=extension)
    target = root.joinpath(*relative.parts)
    if target.exists() or target.is_symlink():
        try:
            resolved = target.resolve(strict=True)
            metadata = target.lstat()
        except OSError as exc:
            raise VueOperationPlanError("output path is invalid") from exc
        if resolved != target or not stat.S_ISREG(metadata.st_mode):
            raise VueOperationPlanError("output path is invalid")
        return target
    ancestor = target.parent
    try:
        resolved_parent = ancestor.resolve(strict=True)
        metadata = ancestor.lstat()
    except OSError as exc:
        raise VueOperationPlanError("output parent is unavailable") from exc
    if resolved_parent != ancestor or not stat.S_ISDIR(metadata.st_mode):
        raise VueOperationPlanError("output parent is invalid")
    return target


def _route(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"/[A-Za-z0-9_./-]*", value) is None:
        raise VueOperationPlanError("route is invalid")
    if ".." in PurePosixPath(value).parts or "//" in value:
        raise VueOperationPlanError("route is invalid")
    return value


def _viewport(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or tuple(value) != ("width", "height"):
        raise VueOperationPlanError("viewport is invalid")
    for dimension in ("width", "height"):
        item = value[dimension]
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 4096:
            raise VueOperationPlanError("viewport is invalid")
    return {"width": value["width"], "height": value["height"]}


def list_operation_ids() -> tuple[str, ...]:
    return _OPERATION_IDS


def build(operation_id: str, request: dict[str, Any]) -> dict[str, Any]:
    if operation_id not in _OPERATION_IDS:
        raise VueOperationPlanError("operation_id is unsupported")
    expected_keys = _REQUEST_KEYS[operation_id]
    if not isinstance(request, dict) or set(request) != expected_keys:
        raise VueOperationPlanError("operation request shape is invalid")
    _reject_forbidden(request)
    project_root = _canonical_directory(request["project_root"], role="project_root")
    run_root = _canonical_directory(request["run_root"], role="run_root")
    _validate_roots(project_root, run_root)
    if operation_id == _VISIBLE_OPERATION:
        feature_id = request["feature_id"]
        if not isinstance(feature_id, str) or _SAFE_ID.fullmatch(feature_id) is None:
            raise VueOperationPlanError("feature_id is invalid")
        design_bundle = _existing_input(
            run_root, request["design_bundle"], extension=".json"
        )
        requirement = _existing_input(
            run_root, request["requirement_contract"], extension=".json"
        )
        sfc = _safe_output(project_root, request["sfc_out"], extension=".vue")
        css = _safe_output(project_root, request["css_out"], extension=".css")
        steps = [
            {
                "step_id": "render_vue_feature",
                "action": "render_vue_feature",
                "inputs": {
                    "design_bundle": str(design_bundle),
                    "requirement_contract": str(requirement),
                },
                "outputs": {"sfc": str(sfc), "css": str(css)},
            }
        ]
    elif operation_id == _FIXTURE_OPERATION:
        feature_id = request["feature_id"]
        if not isinstance(feature_id, str) or _SAFE_ID.fullmatch(feature_id) is None:
            raise VueOperationPlanError("feature_id is invalid")
        visual = _existing_input(
            run_root, request["visual_contract"], extension=".json"
        )
        fixture = _safe_output(project_root, request["fixture_out"], extension=".js")
        steps = [
            {
                "step_id": "render_vue_fixture",
                "action": "render_vue_fixture",
                "inputs": {"visual_contract": str(visual)},
                "outputs": {"fixture": str(fixture)},
            }
        ]
    elif operation_id == "vue.trace_harness.v1":
        steps = [{
            "step_id": "capture_dom_trace",
            "action": "capture_dom_trace",
            "inputs": {"route": _route(request["route"])},
            "outputs": {
                "trace": str(_safe_output(run_root, request["dom_trace_out"], extension=".json"))
            },
        }]
    elif operation_id == "vue.packaging.v1":
        steps = [{
            "step_id": "prepare_vue_packaging",
            "action": "prepare_vue_packaging",
            "inputs": {
                "assets_manifest": str(
                    _existing_input(run_root, request["assets_manifest"], extension=".json")
                )
            },
            "outputs": {
                "receipt": str(_safe_output(run_root, request["receipt_out"], extension=".json"))
            },
        }]
    elif operation_id == "vue.test_runner.v1":
        phase = request["phase"]
        if phase not in ("red", "green"):
            raise VueOperationPlanError("test phase is invalid")
        steps = [{
            "step_id": "run_vue_tests",
            "action": "run_vue_tests",
            "inputs": {"phase": phase},
            "outputs": {
                "evidence": str(_safe_output(run_root, request["evidence_out"], extension=".json"))
            },
        }]
    elif operation_id == "vue.runtime_capture.v1":
        steps = [{
            "step_id": "capture_browser_screenshot",
            "action": "capture_browser_screenshot",
            "inputs": {
                "route": _route(request["route"]),
                "viewport": _viewport(request["viewport"]),
            },
            "outputs": {
                "actual": str(_safe_output(run_root, request["actual_out"], extension=".png")),
                "provenance": str(
                    _safe_output(run_root, request["provenance_out"], extension=".json")
                ),
            },
        }]
    elif operation_id == "vue.project_gates.v1":
        steps = [{
            "step_id": "run_vue_project_gates",
            "action": "run_vue_project_gates",
            "inputs": {},
            "outputs": {
                "report": str(_safe_output(run_root, request["report_out"], extension=".json"))
            },
        }]
    else:
        steps = [{
            "step_id": "apply_vue_fan_in",
            "action": "apply_vue_fan_in",
            "inputs": {
                "mutation_manifest": str(
                    _existing_input(
                        run_root, request["mutation_manifest"], extension=".json"
                    )
                )
            },
            "outputs": {
                "receipt": str(_safe_output(run_root, request["receipt_out"], extension=".json"))
            },
        }]
    plan = {
        "kind": KIND_PLAN,
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        "request_digest": _digest({"operation_id": operation_id, "steps": steps}),
        "steps": steps,
    }
    verify_plan(plan)
    return plan


def verify_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or tuple(plan) != _PLAN_KEYS:
        raise VueOperationPlanError("plan shape is invalid")
    expected = {
        "kind": KIND_PLAN,
        "schema_version": SCHEMA_VERSION,
        "operation_id": plan.get("operation_id"),
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
    }
    for key, value in expected.items():
        if plan[key] != value or (
            key == "schema_version" and isinstance(plan[key], bool)
        ):
            raise VueOperationPlanError(f"plan {key} is invalid")
    steps = plan["steps"]
    if not isinstance(steps, list) or len(steps) != 1:
        raise VueOperationPlanError("plan steps are invalid")
    step = steps[0]
    if not isinstance(step, dict) or tuple(step) != _STEP_KEYS:
        raise VueOperationPlanError("plan step shape is invalid")
    if plan["operation_id"] not in _VARIANT_SHAPES:
        raise VueOperationPlanError("plan operation_id is invalid")
    step_id, action, expected_inputs, expected_outputs = _VARIANT_SHAPES[
        plan["operation_id"]
    ]
    if (step["step_id"], step["action"]) != (step_id, action):
        raise VueOperationPlanError("plan step identity is invalid")
    if not isinstance(step["inputs"], dict) or tuple(step["inputs"]) != expected_inputs:
        raise VueOperationPlanError("plan inputs are invalid")
    if not isinstance(step["outputs"], dict) or tuple(step["outputs"]) != expected_outputs:
        raise VueOperationPlanError("plan outputs are invalid")
    for key, path_value in {**step["inputs"], **step["outputs"]}.items():
        if key in ("route", "phase", "viewport"):
            continue
        if not isinstance(path_value, str) or not os.path.isabs(path_value):
            raise VueOperationPlanError("plan path is invalid")
        if str(Path(os.path.abspath(path_value))) != path_value:
            raise VueOperationPlanError("plan path is not normalized")
    if "route" in step["inputs"]:
        _route(step["inputs"]["route"])
    if "phase" in step["inputs"] and step["inputs"]["phase"] not in ("red", "green"):
        raise VueOperationPlanError("plan phase is invalid")
    if "viewport" in step["inputs"]:
        _viewport(step["inputs"]["viewport"])
    digest = _digest({"operation_id": plan["operation_id"], "steps": steps})
    if plan["request_digest"] != digest:
        raise VueOperationPlanError("plan request digest is invalid")
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "operation_id": plan["operation_id"],
        "steps_total": len(steps),
        "plan_digest": _digest(plan),
    }


def not_implemented(*_args: Any, **_kwargs: Any) -> None:
    """Fixed inactive placeholder for execution-chain component roles."""
    raise VueOperationPlanError("Vue execution chain is not implemented in P3b2")
