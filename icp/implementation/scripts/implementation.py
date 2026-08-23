#!/usr/bin/env python3
"""Deterministic contract gates for ICP implementation."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from typing import Any


STAGE_ROOT = Path(__file__).resolve().parents[1]
ICP_ROOT = STAGE_ROOT.parent
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
sys.path.insert(0, str(ICP_ROOT / "scripts"))
from stage_checklist import (  # noqa: E402
    ChecklistError,
    complete as complete_checklist_node,
    create as create_checklist,
    load as load_checklist,
    node as checklist_node,
    require_complete as require_checklist_complete,
    require_ready as require_checklist_node_ready,
)
sys.path.insert(0, str(STAGE_ROOT / "scripts"))
from component_layout_derivation import (  # noqa: E402
    LayoutContractError,
    derive_component_layout,
    prepare_component_layout_selection,
    verify_runtime_layout,
)
PLATFORM_RULES = {
    "android-kotlin": STAGE_ROOT
    / "references"
    / "platform-best-practices"
    / "android-kotlin.md"
}
IMPLEMENTATION_PROMPT = STAGE_ROOT / "references" / "codegen-prompt.md"
ANDROID_VISUAL_DRIVER = STAGE_ROOT / "scripts" / "android_visual_driver.py"
RENDERING_CONTENT_ROLES = {
    "static_visual",
    "static_copy",
    "dynamic_content",
    "platform_element",
}
INTERACTION_FIELDS = ("condition", "state", "trigger", "behavior", "result")
COMMON_RULES_PROJECT_PATH = "common-rules.md"
MAX_LAYOUT_DECISION_ATTEMPTS = 3


class ContractError(Exception):
    def __init__(
        self, code: str, message: str, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def logical_scale_density(value: object) -> int:
    try:
        scale = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ContractError(
            "visual_capture_failed", "reference logical scale is invalid"
        ) from exc
    if scale <= 0:
        raise ContractError(
            "visual_capture_failed", "reference logical scale is invalid"
        )
    return round(160 * scale)


def android_test_environment(device_serial: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    if device_serial is None:
        return environment
    if (
        not isinstance(device_serial, str)
        or not device_serial
        or any(ord(character) < 32 or ord(character) == 127 for character in device_serial)
    ):
        raise ContractError("invalid_device_serial", "Android device serial is invalid")
    environment["ANDROID_SERIAL"] = device_serial
    return environment


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError("missing_input", f"file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"invalid JSON at {path}: {exc}") from exc


def require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("invalid_contract", f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError("invalid_contract", f"{label} must be an array")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("invalid_contract", f"{label} must be a non-empty string")
    return value


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write(path, json_bytes(value))


def implementation_dir(project_root: Path) -> Path:
    return project_root / ".icp" / "implementation"


@contextmanager
def implementation_stage_lock(project_root: Path, timeout_seconds: float):
    if timeout_seconds < 0:
        raise ContractError(
            "invalid_lock_timeout", "lock timeout must be zero or greater"
        )
    deadline = time.monotonic() + timeout_seconds
    lock_fd = os.open(project_root, os.O_RDONLY)
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ContractError(
                        "stage_busy",
                        "another implementation command holds the stage write lock",
                    ) from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def implementation_checklist_specs(universe: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        checklist_node("stage.begin", "Freeze the complete Stage 3 implementation universe."),
        checklist_node("plan.record", "Record the complete implementation plan.", ["stage.begin"]),
        checklist_node(
            "build.clean",
            "Remove prior Gradle APK outputs before the first implementation test.",
            ["plan.record"],
        ),
    ]
    green_nodes: list[str] = []
    green_nodes_by_page: dict[str, list[str]] = {
        page_key: [] for page_key in universe["page_keys"]
    }
    for obligation in universe["integration_obligations"]:
        obligation_id = obligation["obligation_id"]
        red_node = f"case:{obligation_id}.red"
        green_node = f"case:{obligation_id}.green"
        specs.extend(
            [
                checklist_node(
                    red_node,
                    f"Observe RED for integration obligation {obligation_id}.",
                    ["build.clean"],
                ),
                checklist_node(
                    green_node,
                    f"Implement and observe GREEN for integration obligation {obligation_id}.",
                    [red_node],
                ),
            ]
        )
        green_nodes.append(green_node)
        green_nodes_by_page[obligation["page_key"]].append(green_node)
    page_coverage_nodes: list[str] = []
    for page_key in universe["page_keys"]:
        node_id = f"implementation.code-coverage:{page_key}"
        specs.append(
            checklist_node(
                node_id,
                f"Verify production code, anchors, and assets for page {page_key}.",
                green_nodes_by_page[page_key] or ["plan.record"],
            )
        )
        page_coverage_nodes.append(node_id)
    specs.append(
        checklist_node(
            "implementation.code-coverage",
            "Verify complete production code, anchors, and assets.",
            page_coverage_nodes or green_nodes or ["plan.record"],
        )
    )
    final_runtime_nodes: list[str] = []
    for page_key in universe["page_keys"]:
        for viewport in ("compact", "expanded"):
            node_id = f"responsive:{page_key}.{viewport}"
            specs.append(
                checklist_node(
                    node_id,
                    f"Verify {viewport} adaptive behavior for page {page_key}.",
                    [f"implementation.code-coverage:{page_key}"],
                )
            )
            final_runtime_nodes.append(node_id)
    for reference in universe["visual_references"]:
        design_name = reference["design_name"]
        capture_node = f"visual:{design_name}.capture"
        verify_node = f"visual:{design_name}.verify"
        specs.extend(
            [
                checklist_node(
                    capture_node,
                    f"Capture the production path for design {design_name}.",
                    [f"implementation.code-coverage:{reference['page_key']}"],
                ),
                checklist_node(
                    verify_node,
                    f"Verify the production capture and runtime probes for design {design_name}.",
                    [f"implementation.code-coverage:{reference['page_key']}", capture_node],
                ),
            ]
        )
        final_runtime_nodes.append(verify_node)
    specs.extend(
        [
            checklist_node(
                "verification.commands",
                "Run every frozen lint, build, and integration command.",
                final_runtime_nodes or ["implementation.code-coverage"],
            ),
            checklist_node(
                "stage.verify",
                "Verify all Stage 3 artifacts and finish ICP.",
                ["verification.commands"],
            ),
        ]
    )
    return specs


def implementation_checklist_input(state: dict[str, Any], universe: dict[str, Any]) -> str:
    return digest(
        {
            "component_lock_sha256": state["component_lock_sha256"],
            "block_component_bindings_sha256": state[
                "block_component_bindings_sha256"
            ],
            "coverage_universe_sha256": state["coverage_universe_sha256"],
            "platform_rules_sha256": state["platform_rules_sha256"],
            "common_rules_sha256": state["common_rules_sha256"],
            "implementation_prompt_sha256": state["implementation_prompt_sha256"],
            "page_keys": universe["page_keys"],
            "obligation_ids": [
                item["obligation_id"] for item in universe["integration_obligations"]
            ],
            "design_names": [
                item["design_name"] for item in universe["visual_references"]
            ],
        }
    )


def implementation_checklist_call(
    stage_dir: Path,
    state: dict[str, Any],
    universe: dict[str, Any],
    operation: str,
    *,
    node_id: str | None = None,
    evidence_sha256: str | None = None,
    exclude: tuple[str, ...] = (),
) -> None:
    parameters = {
        "stage": "implementation",
        "input_sha256": implementation_checklist_input(state, universe),
        "nodes": implementation_checklist_specs(universe),
    }
    try:
        if operation == "ready":
            require_checklist_node_ready(
                stage_dir / "checklist.json", node_id=require_string(node_id, "checklist node"), **parameters
            )
        elif operation == "complete":
            complete_checklist_node(
                stage_dir / "checklist.json",
                node_id=require_string(node_id, "checklist node"),
                evidence_sha256=require_string(evidence_sha256, "checklist evidence"),
                **parameters,
            )
        elif operation == "require-complete":
            require_checklist_complete(
                stage_dir / "checklist.json", exclude=exclude, **parameters
            )
        else:
            raise ContractError("invalid_checklist_operation", operation)
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc


def require_recorded_checklist_evidence(
    stage_dir: Path,
    state: dict[str, Any],
    universe: dict[str, Any],
    *,
    node_id: str,
    evidence_sha256: str,
) -> None:
    try:
        checklist = load_checklist(
            stage_dir / "checklist.json",
            stage="implementation",
            input_sha256=implementation_checklist_input(state, universe),
            nodes=implementation_checklist_specs(universe),
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc
    node = next(item for item in checklist["nodes"] if item["node_id"] == node_id)
    if node["status"] != "completed" or node["evidence_sha256"] != evidence_sha256:
        raise ContractError(
            "runtime_evidence_not_captured",
            f"runtime evidence was not produced by its capture command: {node_id}",
        )


@contextmanager
def exclusive_case_recording(project_root: Path):
    """Serialize run-case read/execute/write cycles so evidence cannot be lost."""
    stage_dir = implementation_dir(project_root)
    stage_dir.mkdir(parents=True, exist_ok=True)
    with (stage_dir / ".case-recording.lock").open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def load_sealed_component_design(
    project_root: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Verify Stage 2's sealed result without reopening any Stage 2 source input."""

    component_dir = project_root / ".icp" / "component-design"
    state = require_dict(
        read_json(component_dir / "state.json"), "component-design state"
    )
    if (
        state.get("schema") != "icp.component-design.state.v2"
        or state.get("state") != "locked"
    ):
        raise ContractError(
            "component_design_incomplete", "component-design is not sealed"
        )
    checklist_path = component_dir / "checklist.json"
    if (
        not checklist_path.is_file()
        or file_sha(checklist_path) != state.get("checklist_sha256")
    ):
        raise ContractError(
            "component_design_incomplete",
            "component-design checklist is missing, incomplete, or changed",
        )
    checklist = require_dict(read_json(checklist_path), "component-design checklist")
    checklist_nodes = require_list(
        checklist.get("nodes"), "component-design checklist nodes"
    )
    if (
        checklist.get("schema") != "icp.stage-checklist"
        or checklist.get("stage") != "component-design"
        or not checklist_nodes
        or any(item.get("status") != "completed" for item in checklist_nodes)
        or checklist_nodes[-1].get("node_id") != "stage.verify"
    ):
        raise ContractError(
            "component_design_incomplete",
            "component-design checklist has unfinished flow nodes",
        )
    result_path = component_dir / "stage-result.json"
    if file_sha(result_path) != state.get("stage_result_sha256"):
        raise ContractError(
            "component_design_incomplete", "component-design result hash changed"
        )
    result = require_dict(read_json(result_path), "component-design result")
    if (
        result.get("schema") != "icp.component-design.stage-result.v8"
        or result.get("status") != "complete"
        or result.get("stage_boundary") != "component-semantics-only"
    ):
        raise ContractError(
            "component_design_incomplete", "component-design result is incomplete"
        )
    artifacts = require_dict(
        result.get("artifacts"), "component-design result artifacts"
    )
    lock_path = component_dir / "component-lock.json"
    bindings_path = component_dir / "block-component-bindings.json"
    lock_sha = file_sha(lock_path)
    bindings_sha = file_sha(bindings_path)
    lock_artifact = require_dict(
        artifacts.get("component_lock"), "component-lock artifact"
    )
    bindings_artifact = require_dict(
        artifacts.get("block_component_bindings"), "Block bindings artifact"
    )
    if (
        lock_sha != state.get("component_lock_sha256")
        or lock_sha != result.get("component_lock_sha256")
        or lock_sha != lock_artifact.get("sha256")
        or lock_artifact.get("path") != "component-lock.json"
        or bindings_sha != state.get("block_component_bindings_sha256")
        or bindings_sha != bindings_artifact.get("sha256")
        or bindings_artifact.get("path") != "block-component-bindings.json"
    ):
        raise ContractError(
            "component_design_incomplete", "component-design artifact hash changed"
        )
    lock = require_dict(read_json(component_dir / "component-lock.json"), "component lock")
    bindings = require_dict(
        read_json(component_dir / "block-component-bindings.json"),
        "block-component bindings",
    )
    if lock.get("schema") != "icp.component-design.lock.v8":
        raise ContractError("component_design_incomplete", "component lock v8 is required")
    if lock.get("stage_boundary") != "component-semantics-only":
        raise ContractError("component_design_incomplete", "component stage boundary changed")
    return component_dir, lock, bindings


def obligation_id(prefix: str, evidence: object) -> str:
    return prefix + "-" + digest(evidence)[:20]


def apk_typography_resource_name(obligation: str, kind: str) -> str:
    if kind not in {"font_size", "line_height"}:
        raise ContractError("invalid_contract", "unsupported APK typography kind")
    return "icp_" + digest({"obligation_id": obligation})[:20] + "_" + kind


def visual_state_id(page_key: str, design_name: str) -> str:
    return "state-" + digest(
        {"page_key": page_key, "design_name": design_name}
    )[:20]


def _visual_values(containers: list[object], keys: tuple[str, ...]) -> list[Any]:
    values: list[Any] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                values.extend(copy.deepcopy(value))
            else:
                values.append(copy.deepcopy(value))
    return values


def project_design_facts(source_fact: object, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Create the sole Stage-3 visual projection from one bound Stage-1 node."""

    fact = source_fact if isinstance(source_fact, dict) else {}
    payload = fact.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    style = payload.get("style")
    style = style if isinstance(style, dict) else {}
    text = payload.get("text")
    text = text if isinstance(text, dict) else {}
    text_style = text.get("style")
    text_style = text_style if isinstance(text_style, dict) else {}
    frame = payload.get("frame")
    return {
        "geometry": copy.deepcopy(frame) if isinstance(frame, dict) else {},
        "backgrounds": _visual_values(
            [payload, style], ("background", "backgrounds", "fill", "fills")
        ),
        "borders": _visual_values(
            [payload, style], ("border", "borders", "stroke", "strokes")
        ),
        "radii": _visual_values(
            [payload, style],
            (
                "radius",
                "radii",
                "cornerRadius",
                "cornerRadii",
                "rectangleCornerRadii",
                "borderRadius",
            ),
        ),
        "typography": copy.deepcopy(text_style),
        "assets": copy.deepcopy(assets),
    }


def reference_bounds(design_facts: object) -> dict[str, int | float] | None:
    facts = design_facts if isinstance(design_facts, dict) else {}
    frame = facts.get("geometry")
    if not isinstance(frame, dict):
        return None
    values = {
        "left": frame.get("left", frame.get("x")),
        "top": frame.get("top", frame.get("y")),
        "width": frame.get("width"),
        "height": frame.get("height"),
    }
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in values.values()
    ):
        return None
    return values


def reference_typography(design_facts: object) -> dict[str, int | float]:
    facts = design_facts if isinstance(design_facts, dict) else {}
    style = facts.get("typography")
    font = style.get("font") if isinstance(style, dict) else None
    if not isinstance(font, dict):
        return {}
    result: dict[str, int | float] = {}
    size = font.get("size")
    if (
        not isinstance(size, bool)
        and isinstance(size, (int, float))
        and math.isfinite(float(size))
        and size > 0
    ):
        result["font_size"] = size
    line_height = font.get("lineHeight")
    line_height_value = (
        line_height.get("value") if isinstance(line_height, dict) else None
    )
    if (
        not isinstance(line_height_value, bool)
        and isinstance(line_height_value, (int, float))
        and math.isfinite(float(line_height_value))
        and line_height_value > 0
    ):
        result["line_height"] = line_height_value
    return result


def reference_color(design_facts: object) -> dict[str, int | float] | None:
    facts = design_facts if isinstance(design_facts, dict) else {}
    text_style = facts.get("typography")
    fill_candidates = [
        text_style.get("fills") if isinstance(text_style, dict) else None,
        facts.get("backgrounds"),
    ]
    for fills in fill_candidates:
        if not isinstance(fills, list):
            continue
        for fill in fills:
            if not isinstance(fill, dict) or fill.get("enabled") is False:
                continue
            color = fill.get("color")
            if isinstance(color, str):
                hexadecimal = color.removeprefix("#")
                if len(hexadecimal) in {6, 8} and all(
                    character in "0123456789abcdefABCDEF"
                    for character in hexadecimal
                ):
                    if len(hexadecimal) == 6:
                        hexadecimal += "FF"
                    return {
                        field: int(hexadecimal[offset : offset + 2], 16)
                        for field, offset in zip(("r", "g", "b", "a"), (0, 2, 4, 6))
                    }
                continue
            if not isinstance(color, dict):
                continue
            normalized = {
                field: color.get(field, 1 if field == "a" else None)
                for field in ("r", "g", "b", "a")
            }
            if all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                and 0 <= float(value) <= 255
                for value in normalized.values()
            ):
                scale = 255 if all(float(value) <= 1 for value in normalized.values()) else 1
                return {
                    field: round(float(value) * scale)
                    for field, value in normalized.items()
                }
    return None


def build_design_element_evidence_channels(
    design_elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Route asset internals to their byte-verified owner instead of fake UI nodes."""

    by_design_and_node = {
        (element["design_name"], element["source_node_id"]): element
        for element in design_elements
    }
    channels: list[dict[str, Any]] = []
    for element in design_elements:
        owner = None
        ancestor_id = element.get("source_parent_node_id")
        visited: set[str] = set()
        while isinstance(ancestor_id, str):
            if ancestor_id in visited:
                raise ContractError(
                    "design_element_identity_invalid",
                    "source parent relation contains a cycle: "
                    + element["source_node_id"],
                )
            visited.add(ancestor_id)
            ancestor = by_design_and_node.get(
                (element["design_name"], ancestor_id)
            )
            if ancestor is None:
                break
            owner = ancestor if ancestor.get("assets") else None
            if owner is not None:
                break
            ancestor_id = ancestor.get("source_parent_node_id")
        channels.append(
            {
                "obligation_id": element["obligation_id"],
                "kind": "asset_internal" if owner is not None else "live_node",
                "owner_obligation_id": (
                    owner["obligation_id"] if owner is not None else None
                ),
            }
        )
    return channels


def build_reference_viewport_assertions(
    design_elements: list[dict[str, Any]],
    layout_selection_inputs: list[dict[str, Any]],
    evidence_channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    frames_by_design: dict[str, dict[str, Any]] = {}
    for value in layout_selection_inputs:
        selection = require_dict(value, "layout selection input")
        design_name = require_string(
            selection.get("design_state_id"), "layout design state ID"
        )
        frames = require_dict(
            selection.get("artboard_frames_by_source_node_id"),
            "layout artboard frames",
        )
        if design_name in frames_by_design:
            raise ContractError(
                "component_layout_input_invalid",
                f"duplicate component layout input: {design_name}",
            )
        frames_by_design[design_name] = frames
    channel_by_obligation = {
        item["obligation_id"]: item for item in evidence_channels
    }
    assertions: list[dict[str, Any]] = []
    for element in design_elements:
        if channel_by_obligation[element["obligation_id"]]["kind"] != "live_node":
            continue
        bounds_mode = (
            "adaptive_at_reference"
            if element["content_role"] in {"static_copy", "dynamic_content"}
            else "exact_at_reference"
        )
        shared = {
            "obligation_id": element["obligation_id"],
            "design_name": element["design_name"],
            "source_node_id": element["source_node_id"],
            "component_instance_id": element["component_instance_id"],
            "probe_tag": "icp-probe-" + element["obligation_id"],
        }
        design_name = element["design_name"]
        if design_name not in frames_by_design:
            raise ContractError(
                "component_layout_input_invalid",
                f"component layout input is missing: {design_name}",
            )
        bounds = frames_by_design[design_name].get(element["source_node_id"])
        if bounds is not None:
            assertions.append(
                {
                    "assertion_id": obligation_id(
                        "visual-assertion",
                        {
                            "obligation_id": element["obligation_id"],
                            "kind": "bounds",
                        },
                    ),
                    **shared,
                    "kind": "bounds",
                    "mode": bounds_mode,
                    "expected": bounds,
                    "evaluation": (
                        {"operator": "finite_nonnegative_rect", "expected": None}
                        if bounds_mode == "adaptive_at_reference"
                        else {"operator": "equals", "expected": bounds}
                    ),
                }
            )
        if element["content_role"] == "static_copy":
            typography = reference_typography(element.get("design_facts"))
            for kind, value in typography.items():
                assertions.append(
                    {
                        "assertion_id": obligation_id(
                            "visual-assertion",
                            {"obligation_id": element["obligation_id"], "kind": kind},
                        ),
                        **shared,
                        "kind": kind,
                        "apk_resource_name": apk_typography_resource_name(
                            element["obligation_id"], kind
                        ),
                        "mode": "exact_at_reference",
                        "expected": value,
                        "evaluation": {
                            "operator": "equals",
                            "expected": value,
                        },
                    }
                )
        color = reference_color(element.get("design_facts"))
        if color is not None:
            assertions.append(
                {
                    "assertion_id": obligation_id(
                        "visual-assertion",
                        {
                            "obligation_id": element["obligation_id"],
                            "kind": "color",
                        },
                    ),
                    **shared,
                    "kind": "color",
                    "mode": "exact_at_reference",
                    "expected": color,
                    "evaluation": {"operator": "equals", "expected": color},
                }
            )
    asserted_obligations = {item["obligation_id"] for item in assertions}
    missing_live_obligations = sorted(
        item["obligation_id"]
        for item in evidence_channels
        if item["kind"] == "live_node"
        and item["obligation_id"] not in asserted_obligations
    )
    if missing_live_obligations:
        raise ContractError(
            "design_evidence_missing",
            "live design elements have no executable reference assertion",
            details={"obligation_ids": missing_live_obligations},
        )
    return assertions


def evaluate_reference_assertion(
    assertion: object, actual: object, logical_scale: object
) -> bool:
    item = assertion if isinstance(assertion, dict) else {}
    evaluation = item.get("evaluation")
    if not isinstance(evaluation, dict):
        return False
    operator = evaluation.get("operator")
    if operator == "equals":
        expected = evaluation.get("expected")
        if item.get("kind") == "bounds":
            if (
                not isinstance(actual, dict)
                or not isinstance(expected, dict)
                or set(actual) != {"left", "top", "width", "height"}
                or set(expected) != set(actual)
            ):
                return False
            try:
                scale = Fraction(logical_scale)
            except (TypeError, ValueError, ZeroDivisionError):
                return False
            if scale <= 0:
                return False
            return all(
                not isinstance(actual[field], bool)
                and isinstance(actual[field], (int, float))
                and math.isfinite(float(actual[field]))
                and not isinstance(expected[field], bool)
                and isinstance(expected[field], (int, float))
                and math.isfinite(float(expected[field]))
                and abs(
                    (Fraction(str(actual[field])) - Fraction(str(expected[field])))
                    * scale
                )
                <= 1
                for field in actual
            )
        return actual == expected
    if operator == "finite_nonnegative_rect":
        return (
            isinstance(actual, dict)
            and set(actual) == {"left", "top", "width", "height"}
            and all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                for value in actual.values()
            )
            and actual["width"] >= 0
            and actual["height"] >= 0
        )
    return False


def build_visual_references(
    bindings: dict[str, Any], design_names: list[str]
) -> list[dict[str, Any]]:
    designs = {
        require_string(item.get("design_name"), "bound design name"): item
        for value in require_list(
            bindings.get("visual_references"), "bound visual references"
        )
        for item in [require_dict(value, "bound visual reference")]
    }
    result: list[dict[str, Any]] = []
    for design_name in design_names:
        design = designs.get(design_name)
        if design is None:
            raise ContractError("visual_reference_missing", f"extract design is missing: {design_name}")
        result.append(
            {
                "design_name": design_name,
                "path": require_relative_path(design.get("path"), "visual reference path"),
                "sha256": design["sha256"],
                "pixel_size": design["pixel_size"],
                "logical_artboard_size": design["logical_artboard_size"],
                "logical_scale": design["logical_scale"],
            }
        )
    return result


def build_graph_interaction_obligations(
    interaction_graphs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    for graph in interaction_graphs:
        page_key = require_string(graph.get("page_key"), "interaction graph page key")
        member_title = require_string(
            graph.get("member_title"), "interaction graph member title"
        )
        edges = require_list(graph.get("edges"), "interaction graph edges")
        terminal_outcomes = require_list(
            graph.get("terminal_outcomes"), "interaction graph terminal outcomes"
        )
        for interaction_value in require_list(
            graph.get("interactions"), "interaction graph interactions"
        ):
            interaction = require_dict(
                interaction_value, "interaction graph interaction"
            )
            interaction_id = require_string(
                interaction.get("interaction_id"), "interaction ID"
            )
            basis_fact_ids: list[str] = []
            component_instance_ids: list[str] = []
            bindings = require_dict(
                interaction.get("component_bindings"),
                "interaction component bindings",
            )
            for field in INTERACTION_FIELDS:
                part_value = interaction.get(field)
                if part_value is not None:
                    part = require_dict(part_value, f"interaction {field}")
                    for fact_id in require_string_list(
                        part.get("fact_ids"),
                        f"interaction {field} fact IDs",
                        nonempty=False,
                    ):
                        if fact_id not in basis_fact_ids:
                            basis_fact_ids.append(fact_id)
                for instance_id in require_string_list(
                    bindings.get(f"{field}_component_instance_ids"),
                    f"interaction {field} component bindings",
                    nonempty=False,
                ):
                    if instance_id not in component_instance_ids:
                        component_instance_ids.append(instance_id)
            if not component_instance_ids:
                raise ContractError(
                    "coverage_incomplete",
                    f"interaction has no component owner: {interaction_id}",
                )
            behavior = interaction.get("behavior")
            kind = (
                require_string(
                    require_dict(behavior, "interaction behavior").get("kind"),
                    "interaction behavior kind",
                )
                if behavior is not None
                else next(
                    field
                    for field in INTERACTION_FIELDS
                    if interaction.get(field) is not None
                )
            )
            obligations.append(
                {
                    "obligation_id": obligation_id(
                        "graph-interaction",
                        {"page_key": page_key, "interaction_id": interaction_id},
                    ),
                    "page_key": page_key,
                    "member_title": member_title,
                    "item_id": interaction_id,
                    "interaction_id": interaction_id,
                    "kind": kind,
                    "fact_id": basis_fact_ids[0] if len(basis_fact_ids) == 1 else None,
                    "basis_fact_ids": basis_fact_ids,
                    "component_instance_id": component_instance_ids[0],
                    "component_instance_ids": component_instance_ids,
                    "meaning": f"Implement the complete frozen interaction {interaction_id}.",
                    "interaction": copy.deepcopy(interaction),
                    "outgoing_edges": [
                        copy.deepcopy(edge)
                        for edge in edges
                        if require_dict(edge, "interaction edge").get(
                            "from_interaction_id"
                        )
                        == interaction_id
                    ],
                    "terminal_outcomes": [
                        copy.deepcopy(terminal)
                        for terminal in terminal_outcomes
                        if require_dict(
                            terminal, "interaction terminal outcome"
                        ).get("interaction_id")
                        == interaction_id
                    ],
                }
            )
    return obligations


def build_coverage_universe(
    project_root: Path, lock: dict[str, Any], bindings: dict[str, Any]
) -> dict[str, Any]:
    contract = require_dict(
        lock.get("implementation_contract"), "closed implementation contract"
    )
    if contract.get("schema") != "icp.component-design.implementation-contract.v1":
        raise ContractError(
            "invalid_component_contract",
            "Stage 3 requires the closed Stage 2 implementation contract",
        )
    page_keys = require_string_list(contract.get("page_keys"), "contract page keys")
    source_identity = require_dict(
        contract.get("source_identity"), "contract source identity"
    )
    expected_page_keys = [
        require_string(member.get("page_key"), "modify member page key")
        for value in require_list(
            source_identity.get("members"), "contract source members"
        )
        for member in [require_dict(value, "contract source member")]
        if member.get("change_scope") == "modify"
    ]
    if page_keys != expected_page_keys:
        raise ContractError(
            "implementation_scope_mismatch",
            "implementation targets must be exactly the ordered modify members",
            details={
                "expected_page_keys": expected_page_keys,
                "actual_page_keys": page_keys,
            },
        )
    page_key_set = set(page_keys)
    pages = [
        require_dict(value, "contract page")
        for value in require_list(contract.get("pages"), "contract pages")
    ]
    pages_by_key = {item["page_key"]: item for item in pages}
    if set(pages_by_key) != page_key_set:
        raise ContractError("coverage_incomplete", "modify pages do not join locked page data")

    component_instances = [
        {
            "component_instance_id": instance["instance_id"],
            "component_id": instance["component_id"],
            "page_key": instance["page_key"],
            "member_title": instance["member_title"],
            "candidate_ids": instance["candidate_ids"],
            "fact_bindings": instance["fact_bindings"],
        }
        for value in require_list(contract.get("component_instances"), "component instances")
        for instance in [require_dict(value, "component instance")]
        if instance.get("page_key") in page_key_set
    ]
    component_ids = {item["component_id"] for item in component_instances}
    component_definitions = [
        require_dict(value, "component definition")
        for value in require_list(contract.get("component_definitions"), "component definitions")
        if require_dict(value, "component definition").get("component_id") in component_ids
    ]
    interaction_graphs = [
        require_dict(value, "locked interaction graph")
        for value in require_list(contract.get("interaction_graphs"), "interaction graphs")
        if require_dict(value, "locked interaction graph").get("page_key")
        in page_key_set
    ]
    if {item.get("page_key") for item in interaction_graphs} != page_key_set:
        raise ContractError(
            "coverage_incomplete",
            "every modify page needs one frozen interaction graph",
        )
    api_contracts = [
        require_dict(value, "frozen API contract")
        for value in require_list(contract.get("api_contracts"), "API contracts")
        if require_dict(value, "frozen API contract").get("page_key") in page_key_set
    ]

    design_elements: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    seen_design_nodes: set[tuple[str, str]] = set()
    for binding_value in require_list(bindings.get("bindings"), "Block bindings"):
        binding = require_dict(binding_value, "Block binding")
        if binding.get("page_key") not in page_key_set:
            continue
        block = require_dict(binding.get("block"), "bound Block")
        block_evidence = {
            "page_key": binding["page_key"],
            "member_title": binding["member_title"],
            "design_name": binding["design_name"],
            "block_id": block["block_id"],
            "design_instance_id": binding["design_instance_id"],
            "component_instance_id": binding["semantic_component_instance_id"],
            "component_id": binding["component_id"],
            "candidate_id": binding["candidate_id"],
            "parent_design_instance_id": binding["parent_design_instance_id"],
            "slot": binding["slot"],
        }
        blocks.append(
            {
                "obligation_id": obligation_id("block", block_evidence),
                **block_evidence,
                "semantic": block["semantic"],
            }
        )
        for node_value in require_list(block.get("source_nodes"), "Block source nodes"):
            node = require_dict(node_value, "Block source node")
            source_fact = require_dict(node.get("source_fact"), "Block source fact")
            source_parent_node_id = source_fact.get("parent_id")
            if source_parent_node_id is not None and not isinstance(
                source_parent_node_id, str
            ):
                raise ContractError(
                    "design_element_identity_invalid",
                    "source parent node ID must be a string or null",
                )
            content_role = node.get("content_role")
            if content_role not in RENDERING_CONTENT_ROLES:
                raise ContractError(
                    "content_role_missing",
                    f"rendering source node has no reviewed content role: {binding['design_name']}/{node.get('source_node_id')}",
                )
            key = (binding["design_name"], require_string(node.get("source_node_id"), "source node ID"))
            if key in seen_design_nodes:
                raise ContractError("coverage_incomplete", f"source node has two Block owners: {key}")
            seen_design_nodes.add(key)
            evidence = {
                **block_evidence,
                "source_node_id": node["source_node_id"],
                "content_role": content_role,
            }
            assets: list[dict[str, Any]] = []
            for asset_value in require_list(node.get("assets"), "source node assets"):
                asset = require_dict(asset_value, "source node asset")
                require_relative_path(
                    asset.get("source_project_path"), "bound source asset path"
                )
                assets.append(copy.deepcopy(asset))
            design_facts = project_design_facts(node.get("source_fact"), assets)
            design_elements.append(
                {
                    "obligation_id": obligation_id("element", evidence),
                    **evidence,
                    "source_parent_node_id": source_parent_node_id,
                    "geometry_basis": node["geometry_basis"],
                    "assets": assets,
                    "design_facts": design_facts,
                }
            )

    semantic_facts = [
        {
            "obligation_id": obligation_id(
                "fact", {"page_key": fact["page_key"], "fact_id": fact["fact_id"]}
            ),
            **fact,
        }
        for value in require_list(contract.get("semantic_facts"), "semantic facts")
        for fact in [require_dict(value, "semantic fact")]
        if fact.get("page_key") in page_key_set
    ]
    interaction_obligations = build_graph_interaction_obligations(interaction_graphs)

    presentation_usages = [
        require_dict(value, "presentation usage")
        for value in require_list(contract.get("presentation_usages"), "presentation usages")
        if require_dict(value, "presentation usage").get("source_page_key") in page_key_set
    ]
    design_names = list(dict.fromkeys(item["design_name"] for item in blocks))
    page_keys_by_design: dict[str, set[str]] = {}
    for block in blocks:
        page_keys_by_design.setdefault(block["design_name"], set()).add(block["page_key"])
    if any(len(keys) != 1 for keys in page_keys_by_design.values()):
        raise ContractError(
            "visual_state_identity_mismatch",
            "every design state must belong to exactly one page",
        )
    visual_references = []
    for reference in build_visual_references(bindings, design_names):
        page_key = next(iter(page_keys_by_design[reference["design_name"]]))
        visual_references.append(
            {
                **reference,
                "page_key": page_key,
                "visual_state_id": visual_state_id(page_key, reference["design_name"]),
            }
        )
    integration_obligations = [
        copy.deepcopy(require_dict(value, "documented integration obligation"))
        for value in require_list(
            contract.get("documented_integration_obligations"),
            "documented integration obligations",
        )
        if require_dict(value, "documented integration obligation").get("page_key")
        in page_key_set
    ]
    for instance in component_instances:
        basis_fact_ids = [
            require_string(binding.get("fact_id"), "inference basis fact ID")
            for binding_value in require_list(
                instance.get("fact_bindings"), "component fact bindings"
            )
            for binding in [require_dict(binding_value, "component fact binding")]
        ]
        instance_id = instance["component_instance_id"]
        integration_obligations.append(
            {
                "obligation_id": obligation_id(
                    "integration",
                    {
                        "page_key": instance["page_key"],
                        "source_kind": "model_inference",
                        "component_instance_id": instance_id,
                    },
                ),
                "source_kind": "model_inference",
                "page_key": instance["page_key"],
                "member_title": instance["member_title"],
                "item_id": "inferred-" + digest({"component_instance_id": instance_id})[:20],
                "kind": "component_contract",
                "fact_id": None,
                "basis_fact_ids": basis_fact_ids,
                "component_instance_id": instance_id,
                "meaning": (
                    "Model derives one integration scenario from this component's "
                    "complete frozen semantic contract and page composition."
                ),
            }
        )
    layout_inputs = [
        require_dict(value, "component layout input")
        for value in require_list(
            bindings.get("layout_inputs"), "component layout inputs"
        )
        if require_dict(value, "component layout input").get("page_key")
        in page_key_set
    ]
    layout_selection_inputs: list[dict[str, Any]] = []
    for value in layout_inputs:
        layout_input = require_dict(value, "component layout input")
        try:
            layout_selection_inputs.append(
                prepare_component_layout_selection(layout_input)
            )
        except LayoutContractError as exc:
            raise ContractError(
                "component_layout_input_invalid",
                str(exc),
                details={"design_state_id": layout_input.get("design_state_id")},
            ) from exc
    if {item.get("design_state_id") for item in layout_selection_inputs} != set(design_names):
        raise ContractError(
            "component_layout_input_invalid",
            "every frozen design state needs one component-bound layout input",
        )
    design_element_evidence_channels = build_design_element_evidence_channels(
        design_elements
    )
    return {
        "schema": "icp.implementation.coverage-universe.v3",
        "source_identity": copy.deepcopy(source_identity),
        "page_keys": page_keys,
        "pages": pages,
        "component_definitions": component_definitions,
        "component_instances": component_instances,
        "interaction_graphs": interaction_graphs,
        "api_contracts": api_contracts,
        "blocks": blocks,
        "design_elements": design_elements,
        "design_element_evidence_channels": design_element_evidence_channels,
        "semantic_facts": semantic_facts,
        "interaction_obligations": interaction_obligations,
        "integration_obligations": integration_obligations,
        "presentation_usages": presentation_usages,
        "visual_references": visual_references,
        "reference_viewport_assertions": build_reference_viewport_assertions(
            design_elements,
            layout_selection_inputs,
            design_element_evidence_channels,
        ),
        "component_layout_inputs": copy.deepcopy(layout_inputs),
        "layout_selection_inputs": layout_selection_inputs,
    }


def build_plan_input(
    state: dict[str, Any],
    universe: dict[str, Any],
    common_rules: str,
    platform_rules: str,
    implementation_prompt: str,
) -> dict[str, Any]:
    return {
        "schema": "icp.implementation.plan.v3",
        "component_lock_sha256": state["component_lock_sha256"],
        "block_component_bindings_sha256": state["block_component_bindings_sha256"],
        "coverage_universe_sha256": state["coverage_universe_sha256"],
        "platform_rules_sha256": state["platform_rules_sha256"],
        "common_rules": {
            "project_path": COMMON_RULES_PROJECT_PATH,
            "sha256": state["common_rules_sha256"],
            "content": common_rules,
        },
        "platform_best_practices": {
            "sha256": state["platform_rules_sha256"],
            "content": platform_rules,
        },
        "implementation_prompt": {
            "sha256": state["implementation_prompt_sha256"],
            "content": implementation_prompt,
        },
        "platform": state["platform"],
        "page_keys": universe["page_keys"],
        "component_definitions": universe["component_definitions"],
        "runtime_probe_provider": None,
        "runtime_entries": [],
        "pages": [],
        "component_mappings": [],
        "interaction_mappings": [],
        "api_contract_mappings": [],
        "design_element_mappings": [],
        "semantic_fact_mappings": [],
        "integration_test_cases": [],
        "presentation_mappings": [],
        "visual_capture_cases": [],
        "layout_decisions": [],
        "layout_contracts": [],
        "execution_nodes": [],
        "file_owners": {},
        "verification_commands": {"lint": [], "build": [], "integration": []},
    }


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContractError(
            "invalid_plan",
            f"{label} fields differ: missing={sorted(expected - set(value))} extra={sorted(set(value) - expected)}",
        )


def require_relative_path(value: object, label: str) -> str:
    text = require_string(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError("invalid_plan", f"{label} must be project-relative")
    return text


def require_string_list(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    items = require_list(value, label)
    if (nonempty and not items) or any(not isinstance(item, str) or not item for item in items):
        raise ContractError("invalid_plan", f"{label} must contain strings")
    return items


def require_identity_coverage(
    actual: list[str],
    expected: list[str],
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> list[str]:
    """Coverage is an identity set: reject duplicates, diff sorted, keep the authoritative order."""

    actual_ids = set(actual)
    expected_ids = set(expected)
    if len(actual) != len(actual_ids) or actual_ids != expected_ids:
        failure: dict[str, Any] = dict(details or {})
        failure.setdefault("missing", sorted(expected_ids - actual_ids))
        failure.setdefault("unexpected", sorted(actual_ids - expected_ids))
        failure["duplicates"] = sorted(
            {item for item in actual if actual.count(item) > 1}
        )
        raise ContractError(code, message, details=failure)
    return list(expected)


def load_live_stage(project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    stage_dir = implementation_dir(project_root)
    state = require_dict(read_json(stage_dir / "state.json"), "implementation state")
    if state.get("schema") != "icp.implementation.state.v1":
        raise ContractError("invalid_state", "implementation state schema is invalid")
    component_dir, _lock, _bindings = load_sealed_component_design(project_root)
    expected_hashes = {
        "component_lock_sha256": file_sha(component_dir / "component-lock.json"),
        "block_component_bindings_sha256": file_sha(
            component_dir / "block-component-bindings.json"
        ),
        "coverage_universe_sha256": file_sha(stage_dir / "coverage-universe.json"),
        "platform_rules_sha256": file_sha(stage_dir / "platform-best-practices.md"),
        "common_rules_sha256": file_sha(stage_dir / "common-rules.md"),
        "implementation_prompt_sha256": file_sha(stage_dir / "implementation-prompt.md"),
    }
    for field, expected in expected_hashes.items():
        if state.get(field) != expected:
            raise ContractError("stage_drift", f"implementation {field} changed")
    project_common_rules = project_root / COMMON_RULES_PROJECT_PATH
    if (
        not project_common_rules.is_file()
        or file_sha(project_common_rules) != state.get("common_rules_sha256")
    ):
        raise ContractError("stage_drift", "project common-rules.md changed")
    universe = require_dict(read_json(stage_dir / "coverage-universe.json"), "coverage universe")
    return stage_dir, state, universe


def validate_command(value: object, label: str) -> list[str]:
    command = require_string_list(value, label)
    if any("\x00" in item for item in command):
        raise ContractError("invalid_plan", f"{label} contains invalid command data")
    return command


def count_runtime_canaries(payload: object) -> int:
    if payload == "__ICP_RUNTIME_CANARY__":
        return 1
    if isinstance(payload, dict):
        return sum(count_runtime_canaries(item) for item in payload.values())
    if isinstance(payload, list):
        return sum(count_runtime_canaries(item) for item in payload)
    return 0


def validate_runtime_ui_test_contract(
    value: object,
    obligation: dict[str, Any],
    universe: dict[str, Any],
) -> dict[str, Any]:
    """Close one integration obligation over the production Android UI surface."""

    contract = require_dict(value, "runtime UI test contract")
    required_contract_keys = {"entry_tag", "preconditions", "actions", "assertions"}
    allowed_contract_keys = required_contract_keys | {
        "network_expectation",
        "mock_expectation",
    }
    if (
        not required_contract_keys.issubset(contract)
        or not set(contract).issubset(allowed_contract_keys)
    ):
        raise ContractError(
            "invalid_plan", "runtime UI test contract fields are invalid"
        )
    entry_tag = require_string(contract.get("entry_tag"), "runtime UI entry tag")
    interaction_id = obligation.get("interaction_id") or obligation.get("item_id")
    interaction = next(
        (
            item
            for graph in universe["interaction_graphs"]
            if graph["page_key"] == obligation["page_key"]
            for item in graph["interactions"]
            if item["interaction_id"] == interaction_id
        ),
        None,
    )
    behavior = interaction.get("behavior") if interaction is not None else None
    direct_api_contract_id = (
        behavior.get("api_contract_id")
        if behavior is not None and behavior.get("kind") == "api_call"
        else None
    )
    incoming_api_outcome = None
    incoming_api_contract_id = None
    for graph in universe["interaction_graphs"]:
        if graph["page_key"] != obligation["page_key"]:
            continue
        interactions_by_id = {
            item["interaction_id"]: item for item in graph["interactions"]
        }
        for edge in graph.get("edges", []):
            target = edge.get("target")
            if (
                isinstance(target, dict)
                and target.get("kind") == "interaction"
                and target.get("to_interaction_id") == interaction_id
            ):
                source_interaction = interactions_by_id.get(
                    edge.get("from_interaction_id")
                )
                source_behavior = (
                    source_interaction.get("behavior")
                    if source_interaction is not None
                    else None
                )
                if (
                    source_behavior is not None
                    and source_behavior.get("kind") == "api_call"
                ):
                    incoming_api_outcome = edge.get("outcome")
                    incoming_api_contract_id = source_behavior.get("api_contract_id")
    api_contract_id = direct_api_contract_id or incoming_api_contract_id
    network_expectation_value = contract.get("network_expectation")
    mock_expectation_value = contract.get("mock_expectation")
    if network_expectation_value is not None and mock_expectation_value is not None:
        raise ContractError(
            "integration_runtime_unproven",
            "one runtime case cannot substitute API and mock inputs together",
        )
    network_expectation = None
    mock_expectation = None
    if api_contract_id is not None:
        if network_expectation_value is None:
            if incoming_api_outcome == "failure":
                raise ContractError(
                    "integration_runtime_unproven",
                    "API failure result requires runtime disconnect observation",
                )
            raise ContractError(
                "integration_runtime_unproven",
                "api_call requires runtime network observation",
            )
        network_expectation_input = require_dict(
            network_expectation_value, "runtime network expectation"
        )
        if (
            network_expectation_input.get("mode") == "response"
            and network_expectation_input.get("response_probe") is None
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "api_call requires a response-derived UI probe",
            )
        require_exact_keys(
            network_expectation_input,
            {
                "api_contract_id",
                "mode",
                "method",
                "path",
                "request_headers",
                "request_body",
                "response_status",
                "response_headers",
                "response_body",
                "response_probe",
            },
            "runtime network expectation",
        )
        frozen_api = next(
            (
                item
                for item in universe["api_contracts"]
                if item["page_key"] == obligation["page_key"]
                and item["api_contract_id"] == api_contract_id
            ),
            None,
        )
        if frozen_api is None:
            raise ContractError(
                "integration_runtime_unproven",
                "api_call runtime network observation has no frozen API contract",
            )
        normalized_api = require_dict(
            frozen_api.get("normalized"), "frozen normalized API contract"
        )
        method = require_string(
            network_expectation_input.get("method"), "runtime network method"
        ).upper()
        path = require_string(
            network_expectation_input.get("path"), "runtime network path"
        )
        mode = require_string(
            network_expectation_input.get("mode"), "runtime network mode"
        )
        if mode not in {"response", "disconnect"}:
            raise ContractError(
                "integration_runtime_unproven", "runtime network mode is invalid"
            )
        if (
            network_expectation_input.get("api_contract_id") != api_contract_id
            or method != normalized_api.get("method")
            or path != normalized_api.get("path")
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime network observation does not match the frozen API request",
            )
        response_status = network_expectation_input.get("response_status")
        allowed_statuses = {
            int(response["status"])
            for response in require_list(
                normalized_api.get("responses"), "frozen API responses"
            )
            if str(response.get("status", "")).isdigit()
        }
        if mode == "response" and (
            not isinstance(response_status, int)
            or isinstance(response_status, bool)
            or response_status not in allowed_statuses
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime network response status is not frozen by the API contract",
            )
        request_headers = require_dict(
            network_expectation_input.get("request_headers"),
            "runtime network request headers",
        )
        response_headers = require_dict(
            network_expectation_input.get("response_headers"),
            "runtime network response headers",
        )
        if any(
            not isinstance(key, str) or not isinstance(header_value, str)
            for headers in (request_headers, response_headers)
            for key, header_value in headers.items()
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime network headers must be string mappings",
            )
        response_probe = None
        if mode == "response":
            response_probe_input = require_dict(
                network_expectation_input.get("response_probe"),
                "runtime network response probe",
            )
            require_exact_keys(
                response_probe_input,
                {"target_tag", "operator"},
                "runtime network response probe",
            )
            response_probe_operator = require_string(
                response_probe_input.get("operator"),
                "runtime network response probe operator",
            )
            if response_probe_operator not in {"text_equals", "text_contains"}:
                raise ContractError(
                    "integration_runtime_unproven",
                    "runtime network response probe must observe production text",
                )
            response_probe_target = require_string(
                response_probe_input.get("target_tag"),
                "runtime network response probe target",
            )
            if count_runtime_canaries(network_expectation_input.get("response_body")) != 1:
                raise ContractError(
                    "integration_runtime_unproven",
                    "api_call requires a response-derived UI probe",
                )
            response_probe = {
                "target_tag": response_probe_target,
                "operator": response_probe_operator,
            }
        elif (
            incoming_api_outcome != "failure"
            or response_status is not None
            or network_expectation_input.get("response_body") is not None
            or network_expectation_input.get("response_probe") is not None
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime disconnect is only valid for an API failure result",
            )
        network_expectation = {
            "api_contract_id": api_contract_id,
            "mode": mode,
            "method": method,
            "path": path,
            "request_headers": dict(request_headers),
            "request_body": network_expectation_input.get("request_body"),
            "response_status": response_status,
            "response_headers": dict(response_headers),
            "response_body": network_expectation_input.get("response_body"),
            "response_probe": response_probe,
        }
    elif network_expectation_value is not None:
        raise ContractError(
            "integration_runtime_unproven",
            "runtime network observation is only valid for api_call",
        )
    if mock_expectation_value is not None:
        mock_expectation_input = require_dict(
            mock_expectation_value, "runtime mock expectation"
        )
        require_exact_keys(
            mock_expectation_input,
            {"body", "response_probe"},
            "runtime mock expectation",
        )
        mock_probe_input = require_dict(
            mock_expectation_input.get("response_probe"),
            "runtime mock response probe",
        )
        require_exact_keys(
            mock_probe_input,
            {"target_tag", "operator"},
            "runtime mock response probe",
        )
        mock_probe_operator = require_string(
            mock_probe_input.get("operator"), "runtime mock response probe operator"
        )
        if (
            mock_probe_operator not in {"text_equals", "text_contains"}
            or count_runtime_canaries(mock_expectation_input.get("body")) != 1
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime mock must carry one response-derived DTO value",
            )
        mock_expectation = {
            "body": mock_expectation_input.get("body"),
            "response_probe": {
                "target_tag": require_string(
                    mock_probe_input.get("target_tag"),
                    "runtime mock response probe target",
                ),
                "operator": mock_probe_operator,
            },
        }
    allowed_operators = {
        "preconditions": {
            "visible",
            "absent",
            "enabled",
            "disabled",
            "selected",
            "unselected",
            "text_equals",
            "text_contains",
        },
        "actions": {"click", "input_text", "press_back"},
        "assertions": {
            "visible",
            "absent",
            "enabled",
            "disabled",
            "selected",
            "unselected",
            "text_equals",
            "text_contains",
        },
    }
    normalized: dict[str, list[dict[str, Any]]] = {}
    covered_fact_ids: list[str] = []
    action_fact_ids: set[str] = set()
    assertion_fact_ids: set[str] = set()
    for phase in ("preconditions", "actions", "assertions"):
        steps: list[dict[str, Any]] = []
        for index, step_value in enumerate(
            require_list(contract.get(phase), f"runtime UI {phase}")
        ):
            label = f"runtime UI {phase}[{index}]"
            step = require_dict(step_value, label)
            require_exact_keys(
                step,
                {"operator", "target_tag", "value", "fact_ids"},
                label,
            )
            operator = require_string(step.get("operator"), f"{label}.operator")
            if operator not in allowed_operators[phase]:
                raise ContractError(
                    "integration_runtime_unproven",
                    f"{label} does not use a closed production UI operator",
                )
            target_tag = step.get("target_tag")
            if operator == "press_back":
                if target_tag is not None:
                    raise ContractError(
                        "integration_runtime_unproven",
                        f"{label}.target_tag must be null for press_back",
                    )
            else:
                target_tag = require_string(target_tag, f"{label}.target_tag")
            runtime_value = step.get("value")
            if operator in {"input_text", "text_equals", "text_contains"}:
                if not isinstance(runtime_value, str):
                    raise ContractError(
                        "integration_runtime_unproven",
                        f"{label}.value must be a string for {operator}",
                    )
            elif runtime_value is not None:
                raise ContractError(
                    "integration_runtime_unproven",
                    f"{label}.value must be null for {operator}",
                )
            fact_ids = require_string_list(
                step.get("fact_ids"), f"{label}.fact_ids", nonempty=False
            )
            if len(fact_ids) != len(set(fact_ids)):
                raise ContractError(
                    "integration_runtime_unproven",
                    f"{label}.fact_ids contains duplicates",
                )
            covered_fact_ids.extend(fact_ids)
            if phase == "actions":
                action_fact_ids.update(fact_ids)
            elif phase == "assertions":
                assertion_fact_ids.update(fact_ids)
            steps.append(
                {
                    "operator": operator,
                    "target_tag": target_tag,
                    "value": runtime_value,
                    "fact_ids": fact_ids,
                }
            )
        normalized[phase] = steps
    if not normalized["assertions"]:
        raise ContractError(
            "integration_runtime_unproven",
            "every integration case needs an observable production UI result",
        )
    if (
        network_expectation is not None
        and network_expectation["response_probe"] is not None
        and network_expectation["response_probe"]["target_tag"]
        not in {step["target_tag"] for step in normalized["assertions"]}
    ):
        raise ContractError(
            "integration_runtime_unproven",
            "response-derived UI probe must belong to the frozen result surface",
        )
    if mock_expectation is not None and mock_expectation["response_probe"][
        "target_tag"
    ] not in {step["target_tag"] for step in normalized["assertions"]}:
        raise ContractError(
            "integration_runtime_unproven",
            "mock-derived UI probe must belong to the frozen result surface",
        )
    expected_fact_ids = require_string_list(
        obligation.get("basis_fact_ids"),
        "integration obligation basis fact IDs",
        nonempty=False,
    )
    if sorted(covered_fact_ids) != sorted(expected_fact_ids):
        raise ContractError(
            "integration_runtime_unproven",
            "runtime UI test does not cover every frozen semantic fact exactly once",
        )
    if obligation.get("source_kind") == "interaction_description" and interaction:
        precondition_ids: set[str] = set()
        for field in ("condition", "state"):
            if interaction.get(field) is not None:
                precondition_ids.update(interaction[field]["fact_ids"])
        trigger_ids = set(
            interaction["trigger"]["fact_ids"]
            if interaction.get("trigger") is not None
            else []
        )
        result_ids: set[str] = set()
        for field in ("behavior", "result"):
            if interaction.get(field) is not None:
                result_ids.update(interaction[field]["fact_ids"])
        precondition_fact_ids = {
            fact_id
            for step in normalized["preconditions"]
            for fact_id in step["fact_ids"]
        }
        if (
            not precondition_ids.issubset(precondition_fact_ids)
            or not trigger_ids.issubset(action_fact_ids)
            or not result_ids.issubset(assertion_fact_ids)
            or precondition_ids & (action_fact_ids | assertion_fact_ids)
            or trigger_ids & (precondition_fact_ids | assertion_fact_ids)
            or result_ids & (precondition_fact_ids | action_fact_ids)
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "runtime UI preconditions, actions, and assertions do not preserve the frozen interaction causality",
            )
    return {
        "entry_tag": entry_tag,
        "preconditions": normalized["preconditions"],
        "actions": normalized["actions"],
        "assertions": normalized["assertions"],
        "network_expectation": network_expectation,
        "mock_expectation": mock_expectation,
    }


def validate_plan(
    value: object, state: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    plan = require_dict(value, "implementation plan")
    require_exact_keys(
        plan,
        {
            "schema",
            "component_lock_sha256",
            "block_component_bindings_sha256",
            "coverage_universe_sha256",
            "platform_rules_sha256",
            "common_rules",
            "platform_best_practices",
            "implementation_prompt",
            "platform",
            "page_keys",
            "component_definitions",
            "runtime_probe_provider",
            "runtime_entries",
            "pages",
            "component_mappings",
            "interaction_mappings",
            "api_contract_mappings",
            "design_element_mappings",
            "semantic_fact_mappings",
            "integration_test_cases",
            "presentation_mappings",
            "visual_capture_cases",
            "layout_decisions",
            "layout_contracts",
            "execution_nodes",
            "file_owners",
            "verification_commands",
        },
        "implementation plan",
    )
    if plan.get("schema") != "icp.implementation.plan.v3":
        raise ContractError("invalid_plan", "implementation plan schema is invalid")
    for field in (
        "component_lock_sha256",
        "block_component_bindings_sha256",
        "coverage_universe_sha256",
        "platform_rules_sha256",
        "platform",
    ):
        if plan.get(field) != state.get(field):
            raise ContractError("input_drift", f"implementation plan {field} changed")
    common_rules = require_dict(plan.get("common_rules"), "common rules")
    require_exact_keys(
        common_rules, {"project_path", "sha256", "content"}, "common rules"
    )
    if (
        common_rules.get("project_path") != COMMON_RULES_PROJECT_PATH
        or common_rules.get("sha256") != state.get("common_rules_sha256")
        or not isinstance(common_rules.get("content"), str)
        or hashlib.sha256(common_rules["content"].encode("utf-8")).hexdigest()
        != state.get("common_rules_sha256")
    ):
        raise ContractError("input_drift", "project common rules changed")
    platform_best_practices = require_dict(
        plan.get("platform_best_practices"), "platform best practices"
    )
    require_exact_keys(
        platform_best_practices,
        {"sha256", "content"},
        "platform best practices",
    )
    if (
        platform_best_practices.get("sha256") != state.get("platform_rules_sha256")
        or not isinstance(platform_best_practices.get("content"), str)
        or hashlib.sha256(
            platform_best_practices["content"].encode("utf-8")
        ).hexdigest()
        != state.get("platform_rules_sha256")
    ):
        raise ContractError("input_drift", "platform best practices changed")
    implementation_prompt = require_dict(
        plan.get("implementation_prompt"), "implementation prompt"
    )
    require_exact_keys(
        implementation_prompt, {"sha256", "content"}, "implementation prompt"
    )
    if (
        implementation_prompt.get("sha256")
        != state.get("implementation_prompt_sha256")
        or not isinstance(implementation_prompt.get("content"), str)
        or hashlib.sha256(implementation_prompt["content"].encode("utf-8")).hexdigest()
        != state.get("implementation_prompt_sha256")
    ):
        raise ContractError("input_drift", "implementation prompt changed")
    if plan.get("page_keys") != universe.get("page_keys"):
        raise ContractError("coverage_incomplete", "implementation page order changed")
    if plan.get("component_definitions") != universe.get("component_definitions"):
        raise ContractError("input_drift", "component definitions changed")

    authored_layouts: dict[str, list[dict[str, Any]]] = {}
    for index, value in enumerate(
        require_list(plan.get("layout_decisions"), "layout decisions")
    ):
        label = f"layout_decisions[{index}]"
        item = require_dict(value, label)
        require_exact_keys(item, {"design_state_id", "decisions"}, label)
        design_state_id = require_string(
            item.get("design_state_id"), f"{label}.design_state_id"
        )
        if design_state_id in authored_layouts:
            raise ContractError(
                "component_layout_decision_invalid",
                f"duplicate layout decision set: {design_state_id}",
            )
        authored_layouts[design_state_id] = [
            require_dict(decision, f"{label}.decisions")
            for decision in require_list(item.get("decisions"), f"{label}.decisions")
        ]
    layout_inputs = {
        require_string(item.get("design_state_id"), "layout input design state"): item
        for value in require_list(
            universe.get("component_layout_inputs"), "component layout inputs"
        )
        for item in [require_dict(value, "component layout input")]
    }
    problems: list[dict[str, Any]] = []
    layout_contracts: list[dict[str, Any]] = []
    for design_state_id, layout_input in layout_inputs.items():
        decisions = authored_layouts.get(design_state_id)
        if decisions is None:
            problems.append(
                {
                    "design_state_id": design_state_id,
                    "code": "layout_decisions_missing",
                    "message": "the design state has no authored layout decisions",
                    "details": {},
                }
            )
            continue
        try:
            layout_contracts.append(
                derive_component_layout(
                    layout_input,
                    lambda _selection, frozen=copy.deepcopy(decisions): frozen,
                )
            )
        except LayoutContractError as exc:
            problems.append(
                {
                    "design_state_id": design_state_id,
                    "code": exc.code,
                    "message": str(exc),
                    "details": copy.deepcopy(exc.details),
                }
            )
    unexpected_layouts = sorted(set(authored_layouts) - set(layout_inputs))
    for design_state_id in unexpected_layouts:
        problems.append(
            {
                "design_state_id": design_state_id,
                "code": "layout_decisions_unexpected",
                "message": "the layout decision set targets an unknown design state",
                "details": {},
            }
        )
    if problems:
        raise ContractError(
            "component_layout_decision_invalid",
            "one or more component pages need new whole-page layout decisions",
            details={"problems": problems},
        )
    submitted_contracts = require_list(
        plan.get("layout_contracts"), "layout contracts"
    )
    if submitted_contracts and submitted_contracts != layout_contracts:
        raise ContractError("input_drift", "derived layout contracts changed")

    expected_instances = {
        item["component_instance_id"]: item for item in universe["component_instances"]
    }
    pages: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    covered_instances: list[str] = []
    for index, page_value in enumerate(require_list(plan.get("pages"), "plan pages")):
        label = f"pages[{index}]"
        page = require_dict(page_value, label)
        require_exact_keys(
            page,
            {
                "page_key",
                "member_title",
                "route",
                "source_file",
                "root_symbol",
                "dto_file",
                "dto_symbol",
                "ui_state_symbol",
                "mock_fixture_path",
                "api_adapter_file",
                "api_adapter_symbol",
                "responsive_strategy",
                "component_instance_ids",
            },
            label,
        )
        page_key = require_string(page.get("page_key"), f"{label}.page_key")
        source_page = next(
            (item for item in universe["pages"] if item["page_key"] == page_key), None
        )
        if source_page is None or page_key in seen_pages or page.get("member_title") != source_page.get("member_title"):
            raise ContractError("coverage_incomplete", f"invalid or duplicate page {page_key}")
        seen_pages.add(page_key)
        source_route = source_page.get("route")
        if page.get("route") != source_route:
            raise ContractError("contract_drift", f"page route changed: {page_key}")
        for field in ("source_file", "dto_file", "mock_fixture_path"):
            require_relative_path(page.get(field), f"{label}.{field}")
        for field in ("root_symbol", "dto_symbol", "ui_state_symbol", "responsive_strategy"):
            require_string(page.get(field), f"{label}.{field}")
        page_has_api_dependency = any(
            contract.get("page_key") == page_key
            for contract in universe["api_contracts"]
        )
        if page_has_api_dependency:
            api_adapter_file = require_relative_path(
                page.get("api_adapter_file"), f"{label}.api_adapter_file"
            )
            if api_adapter_file == page["dto_file"]:
                raise ContractError(
                    "api_implementation_boundary",
                    f"{label} API adapter must be separate from its DTO file",
                )
            require_string(page.get("api_adapter_symbol"), f"{label}.api_adapter_symbol")
        elif (
            page.get("api_adapter_file") is not None
            or page.get("api_adapter_symbol") is not None
        ):
            raise ContractError(
                "invalid_plan",
                f"{label} cannot declare an API adapter without a frozen contract",
            )
        page_instances = require_string_list(
            page.get("component_instance_ids"), f"{label}.component_instance_ids"
        )
        expected_page_instances = [
            item["component_instance_id"]
            for item in universe["component_instances"]
            if item["page_key"] == page_key
        ]
        actual_ids = set(page_instances)
        expected_ids = set(expected_page_instances)
        if len(page_instances) != len(actual_ids) or actual_ids != expected_ids:
            duplicate_ids = sorted(
                {instance_id for instance_id in page_instances if page_instances.count(instance_id) > 1}
            )
            raise ContractError(
                "component_coverage_mismatch",
                f"page component coverage changed: {page_key}",
                details={
                    "page_key": page_key,
                    "missing": sorted(expected_ids - actual_ids),
                    "unexpected": sorted(actual_ids - expected_ids),
                    "duplicates": duplicate_ids,
                },
            )
        normalized_page = page.copy()
        normalized_page["component_instance_ids"] = expected_page_instances
        covered_instances.extend(expected_page_instances)
        pages.append(normalized_page)
    if [item["page_key"] for item in pages] != universe["page_keys"] or set(
        covered_instances
    ) != set(expected_instances):
        raise ContractError("coverage_incomplete", "every modify page and component instance is required")

    plan_pages_by_key = {page["page_key"]: page for page in pages}
    frozen_page_designs = {
        (page["page_key"], design_name)
        for page in universe["pages"]
        for design_name in require_string_list(
            page.get("design_names"), "locked page design names", nonempty=False
        )
    }
    runtime_entries: list[dict[str, Any]] = []
    seen_entry_ids: set[str] = set()
    for index, entry_value in enumerate(
        require_list(plan.get("runtime_entries"), "runtime entries")
    ):
        label = f"runtime_entries[{index}]"
        entry = require_dict(entry_value, label)
        require_exact_keys(
            entry,
            {"entry_id", "source_file", "symbol", "page_key", "design_name"},
            label,
        )
        entry_id = require_string(entry.get("entry_id"), f"{label}.entry_id")
        entry_page_key = require_string(entry.get("page_key"), f"{label}.page_key")
        entry_design = require_string(entry.get("design_name"), f"{label}.design_name")
        entry_page = plan_pages_by_key.get(entry_page_key)
        if (
            entry_id in seen_entry_ids
            or (entry_page_key, entry_design) not in frozen_page_designs
            or entry_page is None
        ):
            raise ContractError(
                "invalid_plan",
                f"runtime entry is not a frozen production identity: {entry_id}",
            )
        seen_entry_ids.add(entry_id)
        entry_source_file = require_relative_path(
            entry.get("source_file"), f"{label}.source_file"
        )
        entry_symbol = require_string(entry.get("symbol"), f"{label}.symbol")
        runtime_entries.append(
            {
                **entry,
                "source_file": entry_source_file,
                "symbol": entry_symbol,
            }
        )
    if not runtime_entries:
        raise ContractError("invalid_plan", "one or more runtime entries are required")

    provider_value = require_dict(
        plan.get("runtime_probe_provider"), "runtime probe provider"
    )
    require_exact_keys(
        provider_value,
        {"source_file", "symbol", "publish_method_symbol", "output_path"},
        "runtime probe provider",
    )
    runtime_probe_provider = {
        "source_file": require_relative_path(
            provider_value.get("source_file"), "runtime probe provider source_file"
        ),
        "symbol": require_string(
            provider_value.get("symbol"), "runtime probe provider symbol"
        ),
        "publish_method_symbol": require_string(
            provider_value.get("publish_method_symbol"),
            "runtime probe provider publish method symbol",
        ),
        "output_path": require_relative_path(
            provider_value.get("output_path"), "runtime probe provider output_path"
        ),
    }
    if runtime_probe_provider["output_path"] != "files/icp-runtime-probes.json":
        raise ContractError(
            "invalid_plan",
            "runtime probe provider must publish the frozen app-private payload path",
        )

    blocks_by_instance: dict[str, list[str]] = {}
    for block in universe["blocks"]:
        blocks_by_instance.setdefault(block["component_instance_id"], []).append(block["obligation_id"])
    component_mappings: list[dict[str, Any]] = []
    seen_instances: set[str] = set()
    for index, mapping_value in enumerate(
        require_list(plan.get("component_mappings"), "component mappings")
    ):
        label = f"component_mappings[{index}]"
        mapping = require_dict(mapping_value, label)
        require_exact_keys(
            mapping,
            {
                "component_instance_id",
                "component_id",
                "page_key",
                "source_file",
                "symbol",
                "platform_primitive",
                "responsive_strategy",
                "block_obligation_ids",
            },
            label,
        )
        instance_id = require_string(mapping.get("component_instance_id"), f"{label}.component_instance_id")
        expected = expected_instances.get(instance_id)
        if expected is None or instance_id in seen_instances:
            raise ContractError("coverage_incomplete", f"invalid component mapping {instance_id}")
        seen_instances.add(instance_id)
        if mapping.get("component_id") != expected["component_id"] or mapping.get("page_key") != expected["page_key"]:
            raise ContractError("coverage_incomplete", f"component identity changed: {instance_id}")
        require_relative_path(mapping.get("source_file"), f"{label}.source_file")
        for field in ("symbol", "platform_primitive", "responsive_strategy"):
            require_string(mapping.get(field), f"{label}.{field}")
        normalized_block_ids = require_identity_coverage(
            require_string_list(
                mapping.get("block_obligation_ids"),
                f"{label}.block_obligation_ids",
                nonempty=False,
            ),
            blocks_by_instance.get(instance_id, []),
            code="coverage_incomplete",
            message=f"component Block coverage changed: {instance_id}",
            details={"component_instance_id": instance_id},
        )
        normalized_mapping = mapping.copy()
        normalized_mapping["block_obligation_ids"] = normalized_block_ids
        component_mappings.append(normalized_mapping)
    if seen_instances != set(expected_instances):
        raise ContractError("coverage_incomplete", "every component instance needs one implementation mapping")

    def validate_obligation_mappings(
        field: str,
        universe_field: str,
        *,
        include_fact_id: bool,
        include_assets: bool = False,
    ) -> list[dict[str, Any]]:
        expected = {item["obligation_id"]: item for item in universe[universe_field]}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected_keys = {"obligation_id", "source_file", "symbol", "implementation_anchor"}
        if include_fact_id:
            expected_keys.add("fact_id")
        if include_assets:
            expected_keys.update({"asset_mappings", "runtime_probe_tag"})
        for index, value in enumerate(require_list(plan.get(field), field)):
            label = f"{field}[{index}]"
            item = require_dict(value, label)
            require_exact_keys(item, expected_keys, label)
            obligation = require_string(item.get("obligation_id"), f"{label}.obligation_id")
            source = expected.get(obligation)
            if source is None or obligation in seen:
                raise ContractError("coverage_incomplete", f"invalid obligation mapping {obligation}")
            seen.add(obligation)
            if include_fact_id and item.get("fact_id") != source.get("fact_id"):
                raise ContractError("coverage_incomplete", f"fact identity changed: {obligation}")
            require_relative_path(item.get("source_file"), f"{label}.source_file")
            require_string(item.get("symbol"), f"{label}.symbol")
            if item.get("implementation_anchor") != "ICP:" + obligation:
                raise ContractError("invalid_plan", f"implementation anchor changed: {obligation}")
            if include_assets:
                assertion_tags = {
                    assertion["probe_tag"]
                    for assertion in universe["reference_viewport_assertions"]
                    if assertion["obligation_id"] == obligation
                }
                expected_probe_tag = (
                    next(iter(assertion_tags)) if assertion_tags else None
                )
                if (
                    len(assertion_tags) > 1
                    or item.get("runtime_probe_tag") != expected_probe_tag
                ):
                    raise ContractError(
                        "visual_render_identity_mismatch",
                        f"design element runtime probe changed: {obligation}",
                    )
                source_assets = {
                    asset["asset_id"]: asset
                    for asset in require_list(source.get("assets"), "design element assets")
                }
                asset_mappings = require_list(
                    item.get("asset_mappings"), f"{label}.asset_mappings"
                )
                if source_assets and not asset_mappings:
                    raise ContractError(
                        "asset_consumption_missing",
                        f"exported asset is not consumed: {obligation}",
                    )
                if not source_assets and asset_mappings:
                    raise ContractError(
                        "asset_consumption_missing",
                        f"asset mapping has no source asset: {obligation}",
                    )
                seen_assets: set[str] = set()
                normalized_assets: list[dict[str, Any]] = []
                for asset_index, asset_value in enumerate(asset_mappings):
                    asset_label = f"{label}.asset_mappings[{asset_index}]"
                    asset_mapping = require_dict(asset_value, asset_label)
                    require_exact_keys(
                        asset_mapping,
                        {
                            "source_asset_id",
                            "source_asset_sha256",
                            "target_resource_path",
                        },
                        asset_label,
                    )
                    asset_id = require_string(
                        asset_mapping.get("source_asset_id"),
                        f"{asset_label}.source_asset_id",
                    )
                    source_asset = source_assets.get(asset_id)
                    if (
                        source_asset is None
                        or asset_id in seen_assets
                        or asset_mapping.get("source_asset_sha256")
                        != source_asset.get("sha256")
                    ):
                        raise ContractError(
                            "asset_consumption_missing",
                            f"asset mapping does not match a frozen source asset: {obligation}",
                        )
                    seen_assets.add(asset_id)
                    require_relative_path(
                        asset_mapping.get("target_resource_path"),
                        f"{asset_label}.target_resource_path",
                    )
                    normalized_assets.append(asset_mapping.copy())
                item = {**item, "asset_mappings": normalized_assets}
            normalized.append(item.copy())
        if seen != set(expected):
            raise ContractError("coverage_incomplete", f"every {universe_field} obligation needs one mapping")
        return normalized

    design_mappings = validate_obligation_mappings(
        "design_element_mappings",
        "design_elements",
        include_fact_id=False,
        include_assets=True,
    )
    fact_mappings = validate_obligation_mappings(
        "semantic_fact_mappings", "semantic_facts", include_fact_id=True
    )

    expected_interactions = {
        (graph["page_key"], interaction["interaction_id"]): interaction
        for graph in universe["interaction_graphs"]
        for interaction in graph["interactions"]
    }
    component_mapping_by_instance = {
        mapping["component_instance_id"]: mapping for mapping in component_mappings
    }
    interaction_mappings: list[dict[str, Any]] = []
    seen_interactions: set[tuple[str, str]] = set()
    for index, mapping_value in enumerate(
        require_list(plan.get("interaction_mappings"), "interaction mappings")
    ):
        label = f"interaction_mappings[{index}]"
        mapping = require_dict(mapping_value, label)
        require_exact_keys(
            mapping,
            {
                "interaction_id",
                "page_key",
                "component_instance_ids",
                "source_file",
                "symbol",
                "implementation_anchor",
            },
            label,
        )
        interaction_id = require_string(
            mapping.get("interaction_id"), f"{label}.interaction_id"
        )
        page_key = require_string(mapping.get("page_key"), f"{label}.page_key")
        key = (page_key, interaction_id)
        interaction = expected_interactions.get(key)
        if interaction is None or key in seen_interactions:
            raise ContractError(
                "interaction_implementation_coverage",
                f"invalid or duplicate interaction mapping {page_key}/{interaction_id}",
            )
        seen_interactions.add(key)
        expected_instance_ids: list[str] = []
        for bound_ids in require_dict(
            interaction.get("component_bindings"), "interaction component bindings"
        ).values():
            for instance_id in require_string_list(
                bound_ids, "interaction component instance IDs", nonempty=False
            ):
                if instance_id not in expected_instance_ids:
                    expected_instance_ids.append(instance_id)
        instance_ids = require_string_list(
            mapping.get("component_instance_ids"),
            f"{label}.component_instance_ids",
        )
        normalized_instance_ids = require_identity_coverage(
            instance_ids,
            expected_instance_ids,
            code="interaction_implementation_coverage",
            message=f"interaction component coverage changed: {page_key}/{interaction_id}",
            details={"page_key": page_key, "interaction_id": interaction_id},
        )
        source_file = require_relative_path(
            mapping.get("source_file"), f"{label}.source_file"
        )
        symbol = require_string(mapping.get("symbol"), f"{label}.symbol")
        if not any(
            component_mapping_by_instance[instance_id]["source_file"] == source_file
            and component_mapping_by_instance[instance_id]["symbol"] == symbol
            for instance_id in normalized_instance_ids
        ):
            raise ContractError(
                "interaction_implementation_coverage",
                f"interaction is not anchored to one bound production component: {interaction_id}",
            )
        if mapping.get("implementation_anchor") != "ICP:interaction:" + interaction_id:
            raise ContractError(
                "invalid_plan", f"interaction anchor changed: {interaction_id}"
            )
        normalized_interaction_mapping = mapping.copy()
        normalized_interaction_mapping["component_instance_ids"] = normalized_instance_ids
        interaction_mappings.append(normalized_interaction_mapping)
    if seen_interactions != set(expected_interactions):
        raise ContractError(
            "interaction_implementation_coverage",
            "every frozen interaction needs one production mapping",
        )

    pages_by_key = {page["page_key"]: page for page in pages}
    expected_api_contracts = {
        (contract["page_key"], contract["api_contract_id"]): contract
        for contract in universe["api_contracts"]
    }
    api_contract_mappings: list[dict[str, Any]] = []
    seen_api_contracts: set[tuple[str, str]] = set()
    seen_api_method_symbols: set[tuple[str, str]] = set()
    for index, mapping_value in enumerate(
        require_list(plan.get("api_contract_mappings"), "API contract mappings")
    ):
        label = f"api_contract_mappings[{index}]"
        mapping = require_dict(mapping_value, label)
        require_exact_keys(
            mapping,
            {
                "api_contract_id",
                "page_key",
                "source_file",
                "adapter_symbol",
                "method_symbol",
                "implementation_anchor",
            },
            label,
        )
        contract_id = require_string(
            mapping.get("api_contract_id"), f"{label}.api_contract_id"
        )
        page_key = require_string(mapping.get("page_key"), f"{label}.page_key")
        key = (page_key, contract_id)
        page = pages_by_key.get(page_key)
        if key not in expected_api_contracts or key in seen_api_contracts or page is None:
            raise ContractError(
                "api_implementation_coverage",
                f"invalid or duplicate API mapping {page_key}/{contract_id}",
            )
        seen_api_contracts.add(key)
        source_file = require_relative_path(
            mapping.get("source_file"), f"{label}.source_file"
        )
        adapter_symbol = require_string(
            mapping.get("adapter_symbol"), f"{label}.adapter_symbol"
        )
        method_symbol = require_string(
            mapping.get("method_symbol"), f"{label}.method_symbol"
        )
        if (
            source_file != page["api_adapter_file"]
            or adapter_symbol != page["api_adapter_symbol"]
            or (source_file, method_symbol) in seen_api_method_symbols
        ):
            raise ContractError(
                "api_implementation_coverage",
                f"API mapping does not use the page adapter boundary: {contract_id}",
            )
        seen_api_method_symbols.add((source_file, method_symbol))
        if mapping.get("implementation_anchor") != "ICP:api:" + contract_id:
            raise ContractError("invalid_plan", f"API anchor changed: {contract_id}")
        api_contract_mappings.append(mapping.copy())
    if seen_api_contracts != set(expected_api_contracts):
        raise ContractError(
            "api_implementation_coverage",
            "every frozen API contract needs one adapter method mapping",
        )
    interaction_mapping_by_key = {
        (mapping["page_key"], mapping["interaction_id"]): mapping
        for mapping in interaction_mappings
    }
    api_mapping_by_key = {
        (mapping["page_key"], mapping["api_contract_id"]): mapping
        for mapping in api_contract_mappings
    }
    for key, interaction in expected_interactions.items():
        behavior = interaction.get("behavior")
        if behavior is None or behavior.get("kind") != "api_call":
            continue
        interaction_mapping = interaction_mapping_by_key[key]
        api_mapping = api_mapping_by_key[
            (key[0], behavior["api_contract_id"])
        ]
        if interaction_mapping["source_file"] == api_mapping["source_file"]:
            raise ContractError(
                "api_implementation_boundary",
                "API adapter must not be declared in its consuming interaction file: "
                + key[1],
            )

    expected_integrations = {
        item["obligation_id"]: item for item in universe["integration_obligations"]
    }
    cases: list[dict[str, Any]] = []
    seen_integrations: set[str] = set()
    case_ids: set[str] = set()
    android_test_identities: set[str] = set()
    android_test_files: set[str] = set()
    for index, case_value in enumerate(
        require_list(plan.get("integration_test_cases"), "integration test cases")
    ):
        label = f"integration_test_cases[{index}]"
        case = require_dict(case_value, label)
        require_exact_keys(
            case,
            {
                "case_id",
                "obligation_id",
                "source_kind",
                "fact_id",
                "basis_fact_ids",
                "component_instance_id",
                "page_key",
                "test_file",
                "test_name",
                "runtime_test",
                "command",
            },
            label,
        )
        case_id = require_string(case.get("case_id"), f"{label}.case_id")
        obligation = require_string(case.get("obligation_id"), f"{label}.obligation_id")
        expected = expected_integrations.get(obligation)
        if (
            expected is None
            or obligation in seen_integrations
            or case_id in case_ids
            or case.get("fact_id") != expected["fact_id"]
            or case.get("source_kind") != expected["source_kind"]
            or case.get("component_instance_id") != expected["component_instance_id"]
            or case.get("page_key") != expected["page_key"]
        ):
            raise ContractError("coverage_incomplete", f"invalid integration case {case_id}")
        normalized_basis_ids = require_identity_coverage(
            require_string_list(
                case.get("basis_fact_ids"), f"{label}.basis_fact_ids", nonempty=False
            ),
            require_string_list(
                expected.get("basis_fact_ids"),
                "integration basis fact IDs",
                nonempty=False,
            ),
            code="coverage_incomplete",
            message=f"integration basis fact coverage changed: {case_id}",
            details={"case_id": case_id, "obligation_id": obligation},
        )
        seen_integrations.add(obligation)
        case_ids.add(case_id)
        test_file = require_relative_path(
            case.get("test_file"), f"{label}.test_file"
        )
        require_string(case.get("test_name"), f"{label}.test_name")
        runtime_test = validate_runtime_ui_test_contract(
            case.get("runtime_test"), expected, universe
        )
        command = validate_command(case.get("command"), f"{label}.command")
        if plan["platform"] == "android-kotlin":
            test_parts = Path(case["test_file"]).parts
            gradle_executable = command[0] == "./gradlew"
            device_tasks = [
                argument
                for argument in command[1:]
                if re.fullmatch(
                    r"(?::[A-Za-z0-9_.-]+:)?connected[A-Za-z0-9_.-]*AndroidTest",
                    argument,
                )
            ]
            selectors = [
                argument.split("=", 1)[1]
                for argument in command[1:]
                if argument.startswith(
                    "-Pandroid.testInstrumentationRunnerArguments.class="
                )
            ]
            exact_case_selected = (
                len(selectors) == 1
                and selectors[0].count("#") == 1
                and selectors[0].split("#", 1)[0] != ""
                and selectors[0].split("#", 1)[1] == case["test_name"]
            )
            test_identity = selectors[0] if selectors else ""
            expected_selector_argument = (
                ANDROID_TEST_SELECTOR_PREFIX + selectors[0]
                if len(selectors) == 1
                else None
            )
            if (
                "androidTest" not in test_parts
                or not gradle_executable
                or len(device_tasks) != 1
                or len(command) != 3
                or command[1] != device_tasks[0]
                or command[2] != expected_selector_argument
                or not exact_case_selected
                or test_identity in android_test_identities
                or test_file in android_test_files
            ):
                raise ContractError(
                    "integration_runtime_unproven",
                    f"Android integration case must execute its exact androidTest production surface: {case_id}",
                )
            android_test_identities.add(test_identity)
            android_test_files.add(test_file)
        normalized_case = case.copy()
        normalized_case["basis_fact_ids"] = normalized_basis_ids
        normalized_case["runtime_test"] = runtime_test
        cases.append(normalized_case)
    if seen_integrations != set(expected_integrations):
        raise ContractError(
            "coverage_incomplete",
            "every IT, interaction-description, and model-inference obligation needs one integration test case",
        )
    mock_probe_pages = [
        case["page_key"]
        for case in cases
        if case["runtime_test"]["mock_expectation"] is not None
    ]
    if sorted(mock_probe_pages) != sorted(universe["page_keys"]):
        raise ContractError(
            "integration_runtime_unproven",
            "every page requires one runtime mock DTO probe",
        )

    expected_presentations = {item["usage_id"] for item in universe["presentation_usages"]}
    seen_presentations: set[str] = set()
    presentations: list[dict[str, Any]] = []
    for index, value in enumerate(require_list(plan.get("presentation_mappings"), "presentation mappings")):
        label = f"presentation_mappings[{index}]"
        item = require_dict(value, label)
        require_exact_keys(item, {"usage_id", "source_file", "symbol", "implementation_anchor"}, label)
        usage_id = require_string(item.get("usage_id"), f"{label}.usage_id")
        if usage_id not in expected_presentations or usage_id in seen_presentations:
            raise ContractError("coverage_incomplete", f"invalid presentation mapping {usage_id}")
        seen_presentations.add(usage_id)
        require_relative_path(item.get("source_file"), f"{label}.source_file")
        require_string(item.get("symbol"), f"{label}.symbol")
        if item.get("implementation_anchor") != "ICP:presentation:" + usage_id:
            raise ContractError("invalid_plan", f"presentation anchor changed: {usage_id}")
        presentations.append(item.copy())
    if seen_presentations != expected_presentations:
        raise ContractError("coverage_incomplete", "every presentation usage needs one implementation mapping")

    references = {
        item["design_name"]: item for item in universe["visual_references"]
    }
    entries_by_id = {entry["entry_id"]: entry for entry in runtime_entries}
    interactions_by_page: dict[str, dict[str, dict[str, Any]]] = {}
    edges_by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for graph in universe["interaction_graphs"]:
        graph_page_key = require_string(graph.get("page_key"), "interaction graph page key")
        interactions_by_page[graph_page_key] = {
            require_string(
                interaction.get("interaction_id"), "interaction ID"
            ): require_dict(interaction, "interaction graph interaction")
            for interaction_value in require_list(
                graph.get("interactions"), "interaction graph interactions"
            )
            for interaction in [require_dict(interaction_value, "graph interaction")]
        }
        for edge_value in require_list(graph.get("edges"), "interaction graph edges"):
            edge = require_dict(edge_value, "interaction edge")
            edge_source = require_string(
                edge.get("from_interaction_id"), "edge from_interaction_id"
            )
            edges_by_source.setdefault((graph_page_key, edge_source), []).append(edge)
    components_by_instance = {
        item["component_instance_id"]: item for item in component_mappings
    }
    cases_by_id = {item["case_id"]: item for item in cases}
    visual_capture_cases: list[dict[str, Any]] = []
    seen_visuals: set[str] = set()
    seen_root_tags: set[str] = set()
    unreachable_states: list[dict[str, str]] = []
    for index, value in enumerate(
        require_list(plan.get("visual_capture_cases"), "visual capture cases")
    ):
        label = f"visual_capture_cases[{index}]"
        item = require_dict(value, label)
        require_exact_keys(
            item,
            {
                "design_name",
                "visual_state_id",
                "page_key",
                "entry_id",
                "package_name",
                "locale",
                "precondition_commands",
                "interaction_trace",
                "production_render",
            },
            label,
        )
        design_name = require_string(item.get("design_name"), f"{label}.design_name")
        if design_name not in references or design_name in seen_visuals:
            raise ContractError(
                "coverage_incomplete", f"invalid visual capture case: {design_name}"
            )
        seen_visuals.add(design_name)
        reference = references[design_name]
        page_key = require_string(item.get("page_key"), f"{label}.page_key")
        if page_key != reference["page_key"]:
            raise ContractError(
                "visual_production_path_unproven",
                f"visual state page changed: {design_name}",
            )
        entry_id = require_string(item.get("entry_id"), f"{label}.entry_id")
        entry = entries_by_id.get(entry_id)
        if entry is None:
            raise ContractError(
                "invalid_plan",
                f"visual capture case names an unknown runtime entry: {design_name}",
                details={"design_name": design_name, "entry_id": entry_id},
            )
        state_id = require_string(
            item.get("visual_state_id"), f"{label}.visual_state_id"
        )
        if state_id != reference["visual_state_id"] or any(
            existing.get("visual_state_id") == state_id
            for existing in visual_capture_cases
        ):
            raise ContractError(
                "visual_state_identity_mismatch",
                f"visual state ID is not the frozen unique identity: {design_name}",
                details={
                    "design_name": design_name,
                    "expected_visual_state_id": references[design_name][
                        "visual_state_id"
                    ],
                    "actual_visual_state_id": state_id,
                },
            )
        require_string(item.get("package_name"), f"{label}.package_name")
        require_string(item.get("locale"), f"{label}.locale")
        commands = require_list(
            item.get("precondition_commands"), f"{label}.precondition_commands"
        )
        for command_index, command in enumerate(commands):
            normalized_command = validate_command(
                command, f"{label}.precondition_commands[{command_index}]"
            )
            if (
                Path(normalized_command[0]).name == "adb"
                or any("icp_state" in argument.casefold() for argument in normalized_command)
            ):
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual precondition may not manipulate the Android production surface: {design_name}",
                )
        current_page_key = entry["page_key"]
        current_design_name = entry["design_name"]
        expected_interaction_id: str | None = None
        trace: list[dict[str, Any]] = []
        for trace_index, trace_value in enumerate(
            require_list(item.get("interaction_trace"), f"{label}.interaction_trace")
        ):
            trace_label = f"{label}.interaction_trace[{trace_index}]"
            step = require_dict(trace_value, trace_label)
            base_step_keys = {
                "source_page_key",
                "case_id",
                "interaction_id",
                "outcome",
            }
            legacy_step_keys = base_step_keys | {"action", "target_tag"}
            canonical_step_keys = base_step_keys | {"actions"}
            step_keys = frozenset(step)
            if step_keys not in {
                frozenset(base_step_keys),
                frozenset(legacy_step_keys),
                frozenset(canonical_step_keys),
            }:
                raise ContractError(
                    "invalid_plan",
                    f"{trace_label} must reference one frozen interaction case",
                )
            source_page_key = require_string(
                step.get("source_page_key"), f"{trace_label}.source_page_key"
            )
            case_id = require_string(step.get("case_id"), f"{trace_label}.case_id")
            interaction_id = require_string(
                step.get("interaction_id"), f"{trace_label}.interaction_id"
            )
            outcome = require_string(step.get("outcome"), f"{trace_label}.outcome")
            if (
                expected_interaction_id is not None
                and interaction_id != expected_interaction_id
            ):
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction trace is disconnected: {design_name}",
                    details={
                        "reason": "disconnected_path",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "expected_interaction_id": expected_interaction_id,
                        "actual_interaction_id": interaction_id,
                    },
                )
            if source_page_key != current_page_key:
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction leaves the entry-rooted path: {design_name}",
                    details={
                        "reason": "wrong_source_page",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "expected_source_page_key": current_page_key,
                        "actual_source_page_key": source_page_key,
                    },
                )
            interaction = interactions_by_page.get(source_page_key, {}).get(
                interaction_id
            )
            case = cases_by_id.get(case_id)
            case_interaction_id = (
                expected_integrations.get(case.get("obligation_id"), {}).get(
                    "interaction_id"
                )
                if case is not None
                else None
            )
            if interaction is None or case is None or case["page_key"] != source_page_key or case_interaction_id != interaction_id:
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction is not the frozen graph interaction case: {design_name}",
                    details={
                        "reason": "missing_relation",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "source_page_key": source_page_key,
                        "interaction_id": interaction_id,
                    },
                )
            runtime_actions = require_list(
                require_dict(
                    case.get("runtime_test"), "visual interaction runtime test"
                ).get("actions"),
                "visual interaction runtime actions",
            )
            if not runtime_actions:
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction case has no executable action: {design_name}",
                    details={
                        "reason": "case_action_missing",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "case_id": case_id,
                    },
                )
            if step_keys == legacy_step_keys and (
                len(runtime_actions) != 1
                or runtime_actions[0].get("operator") != step.get("action")
                or runtime_actions[0].get("target_tag") != step.get("target_tag")
            ):
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction differs from its executable case: {design_name}",
                    details={
                        "reason": "case_action_mismatch",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "case_id": case_id,
                    },
                )
            if step_keys == canonical_step_keys and step.get("actions") != runtime_actions:
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction differs from its executable case: {design_name}",
                    details={
                        "reason": "case_action_mismatch",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "case_id": case_id,
                    },
                )
            outgoing = edges_by_source.get((source_page_key, interaction_id), [])
            matching_edges = [
                edge for edge in outgoing if edge.get("outcome") == outcome
            ]
            if len(matching_edges) != 1:
                raise ContractError(
                    "visual_production_path_unproven",
                    f"visual interaction outcome does not select one frozen edge: {design_name}",
                    details={
                        "reason": "wrong_outcome",
                        "design_name": design_name,
                        "step_index": trace_index,
                        "selected_outcome": outcome,
                        "available_outcomes": sorted(
                            {edge.get("outcome") for edge in outgoing}
                        ),
                    },
                )
            edge_target = require_dict(
                matching_edges[0].get("target"), "interaction edge target"
            )
            if edge_target.get("kind") == "interaction":
                expected_interaction_id = require_string(
                    edge_target.get("to_interaction_id"),
                    "edge target interaction ID",
                )
            else:
                expected_interaction_id = None
                current_page_key = require_string(
                    edge_target.get("page_key"), "edge target page key"
                )
                current_design_name = require_string(
                    edge_target.get("design_name"), "edge target design name"
                )
            trace.append(
                {
                    "source_page_key": source_page_key,
                    "case_id": case_id,
                    "interaction_id": interaction_id,
                    "outcome": outcome,
                    "actions": copy.deepcopy(runtime_actions),
                }
            )
        if not trace and (
            current_page_key != page_key or current_design_name != design_name
        ):
            unreachable_states.append(
                {"design_name": design_name, "page_key": page_key}
            )
        if trace and (current_page_key != page_key or current_design_name != design_name):
            raise ContractError(
                "visual_production_path_unproven",
                f"visual state is not reachable from its runtime entry: {design_name}",
                details={
                    "reason": "unreachable_design",
                    "design_name": design_name,
                    "step_index": len(trace) - 1,
                    "expected_target": {
                        "page_key": page_key,
                        "design_name": design_name,
                    },
                    "reached_target": {
                        "page_key": current_page_key,
                        "design_name": current_design_name,
                    },
                },
            )
        production = require_dict(
            item.get("production_render"), f"{label}.production_render"
        )
        require_exact_keys(
            production,
            {"component_instance_id", "source_file", "symbol", "root_tag"},
            f"{label}.production_render",
        )
        component_instance_id = require_string(
            production.get("component_instance_id"),
            f"{label}.production_render.component_instance_id",
        )
        source_file = require_relative_path(
            production.get("source_file"), f"{label}.production_render.source_file"
        )
        symbol = require_string(
            production.get("symbol"), f"{label}.production_render.symbol"
        )
        root_tag = require_string(
            production.get("root_tag"), f"{label}.production_render.root_tag"
        )
        component = components_by_instance.get(component_instance_id)
        if (
            component is None
            or component["page_key"] != page_key
            or source_file != component["source_file"]
            or symbol != component["symbol"]
            or root_tag in seen_root_tags
        ):
            raise ContractError(
                "visual_render_identity_mismatch",
                f"visual state does not target one frozen production renderer: {design_name}",
            )
        seen_root_tags.add(root_tag)
        visual_capture_cases.append(
            {
                **item,
                "precondition_commands": commands,
                "interaction_trace": trace,
                "production_render": production.copy(),
            }
        )
    if seen_visuals != set(references):
        raise ContractError(
            "coverage_incomplete", "every design state needs one visual capture case"
        )
    if unreachable_states:
        raise ContractError(
            "visual_production_path_unproven",
            "every non-entry visual state needs an entry-rooted production path",
            details={
                "entry_ids": sorted(seen_entry_ids),
                "unreachable": unreachable_states,
            },
        )

    commands = require_dict(plan.get("verification_commands"), "verification commands")
    require_exact_keys(commands, {"lint", "build", "integration"}, "verification commands")
    for kind in ("lint", "build", "integration"):
        values = require_list(commands.get(kind), f"verification commands {kind}")
        if not values:
            raise ContractError("invalid_plan", f"verification commands {kind} cannot be empty")
        for index, command in enumerate(values):
            validate_command(command, f"verification commands {kind}[{index}]")

    raw_nodes = require_list(plan.get("execution_nodes"), "execution nodes")
    nodes: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    page_node_by_key: dict[str, str] = {}
    covered_case_ids: set[str] = set()
    expected_case_ids = {case["case_id"] for case in cases}
    for index, value in enumerate(raw_nodes):
        label = f"execution_nodes[{index}]"
        node = require_dict(value, label)
        require_exact_keys(
            node,
            {"node_id", "kind", "page_keys", "depends_on", "case_ids"},
            label,
        )
        node_id = require_string(node.get("node_id"), f"{label}.node_id")
        if node_id in nodes_by_id:
            raise ContractError("invalid_execution_plan", f"duplicate execution node: {node_id}")
        node_kind = node.get("kind")
        if node_kind not in {"foundation", "page", "flow-integration"}:
            raise ContractError("invalid_execution_plan", f"invalid execution node kind: {node_id}")
        node_pages = require_string_list(
            node.get("page_keys"), f"{label}.page_keys", nonempty=False
        )
        dependencies = require_string_list(
            node.get("depends_on"), f"{label}.depends_on", nonempty=False
        )
        node_case_ids = require_string_list(
            node.get("case_ids"), f"{label}.case_ids", nonempty=False
        )
        if (
            len(node_pages) != len(set(node_pages))
            or len(dependencies) != len(set(dependencies))
            or len(node_case_ids) != len(set(node_case_ids))
        ):
            raise ContractError("invalid_execution_plan", f"duplicate node membership: {node_id}")
        if node_kind == "page":
            if len(node_pages) != 1 or node_pages[0] not in universe["page_keys"]:
                raise ContractError("invalid_execution_plan", f"page node scope is invalid: {node_id}")
            page_key = node_pages[0]
            if page_key in page_node_by_key:
                raise ContractError("invalid_execution_plan", f"page has multiple nodes: {page_key}")
            page_node_by_key[page_key] = node_id
            expected_page_cases = [
                case["case_id"] for case in cases if case["page_key"] == page_key
            ]
            if set(node_case_ids) != set(expected_page_cases):
                raise ContractError(
                    "invalid_execution_plan", f"page test ownership changed: {page_key}"
                )
            node_case_ids = expected_page_cases
        elif node_case_ids:
            raise ContractError(
                "invalid_execution_plan", f"non-page node cannot own page integration cases: {node_id}"
            )
        if any(case_id not in expected_case_ids for case_id in node_case_ids):
            raise ContractError("invalid_execution_plan", f"node owns an unknown case: {node_id}")
        overlap = covered_case_ids.intersection(node_case_ids)
        if overlap:
            raise ContractError(
                "invalid_execution_plan", f"integration case has multiple owners: {sorted(overlap)[0]}"
            )
        covered_case_ids.update(node_case_ids)
        normalized_node = {
            **node,
            "page_keys": node_pages,
            "depends_on": dependencies,
            "case_ids": node_case_ids,
        }
        nodes.append(normalized_node)
        nodes_by_id[node_id] = normalized_node
    if set(page_node_by_key) != set(universe["page_keys"]):
        raise ContractError("invalid_execution_plan", "every implementation page needs one page node")
    if covered_case_ids != expected_case_ids:
        raise ContractError("invalid_execution_plan", "every integration case needs one page-node owner")
    foundation_ids = [node["node_id"] for node in nodes if node["kind"] == "foundation"]
    integration_ids = [
        node["node_id"] for node in nodes if node["kind"] == "flow-integration"
    ]
    if len(foundation_ids) != 1 or len(integration_ids) != 1:
        raise ContractError(
            "invalid_execution_plan", "one foundation and one flow-integration node are required"
        )
    foundation_id = foundation_ids[0]
    integration_id = integration_ids[0]
    if nodes_by_id[foundation_id]["page_keys"] or nodes_by_id[foundation_id]["depends_on"]:
        raise ContractError("invalid_execution_plan", "foundation node must be the DAG root")
    if set(nodes_by_id[integration_id]["page_keys"]) != set(universe["page_keys"]):
        raise ContractError("invalid_execution_plan", "flow-integration page scope is incomplete")
    if not set(page_node_by_key.values()).issubset(
        set(nodes_by_id[integration_id]["depends_on"])
    ):
        raise ContractError("invalid_execution_plan", "flow-integration must depend on every page node")
    seen_node_ids: set[str] = set()
    for node in nodes:
        if any(dependency not in seen_node_ids for dependency in node["depends_on"]):
            raise ContractError(
                "invalid_execution_plan",
                f"execution node dependencies are missing or not topological: {node['node_id']}",
            )
        if node["kind"] == "page" and foundation_id not in node["depends_on"]:
            raise ContractError(
                "invalid_execution_plan", f"page node does not depend on foundation: {node['node_id']}"
            )
        seen_node_ids.add(node["node_id"])

    raw_file_owners = require_dict(plan.get("file_owners"), "file owners")
    if not raw_file_owners:
        raise ContractError("invalid_execution_plan", "file owners are required")
    file_owners: dict[str, str] = {}
    for path_value, owner_value in raw_file_owners.items():
        path = require_relative_path(path_value, "owned file path")
        owner = require_string(owner_value, f"owner for {path}")
        if owner not in nodes_by_id:
            raise ContractError("invalid_execution_plan", f"file owner is unknown: {path}")
        file_owners[path] = owner

    for entry in runtime_entries:
        if entry["source_file"] not in file_owners:
            raise ContractError(
                "file_ownership_mismatch",
                f"runtime entry source has no owner: {entry['source_file']}",
                details={
                    "entry_id": entry["entry_id"],
                    "path": entry["source_file"],
                },
            )

    def require_owner(path: str, owner: str, label: str) -> None:
        actual_owner = file_owners.get(path)
        if actual_owner != owner:
            raise ContractError(
                "file_ownership_mismatch",
                f"{label} must be owned by {owner}: {path}",
                details={"path": path, "expected_owner": owner, "actual_owner": actual_owner},
            )

    require_owner(
        runtime_probe_provider["source_file"],
        foundation_id,
        "runtime probe provider",
    )

    for page in pages:
        owner = page_node_by_key[page["page_key"]]
        for field in ("source_file", "dto_file", "mock_fixture_path"):
            require_owner(page[field], owner, f"page {page['page_key']} {field}")
    for case in cases:
        require_owner(
            case["test_file"], page_node_by_key[case["page_key"]], f"test {case['case_id']}"
        )
    component_groups: dict[str, list[dict[str, Any]]] = {}
    for mapping in component_mappings:
        component_groups.setdefault(mapping["component_id"], []).append(mapping)
    for component_id, mappings in component_groups.items():
        component_pages = {mapping["page_key"] for mapping in mappings}
        if len(component_pages) > 1:
            if len({mapping["source_file"] for mapping in mappings}) != 1 or len(
                {mapping["symbol"] for mapping in mappings}
            ) != 1:
                raise ContractError(
                    "file_ownership_mismatch",
                    f"shared component must have one code implementation: {component_id}",
                )
            require_owner(
                mappings[0]["source_file"], foundation_id, f"shared component {component_id}"
            )
        else:
            mapping = mappings[0]
            require_owner(
                mapping["source_file"],
                page_node_by_key[mapping["page_key"]],
                f"local component {component_id}",
            )
    for field_name, mappings in (
        ("design element", design_mappings),
        ("semantic fact", fact_mappings),
        ("interaction", interaction_mappings),
        ("API contract", api_contract_mappings),
        ("presentation", presentations),
    ):
        for mapping in mappings:
            if mapping["source_file"] not in file_owners:
                raise ContractError(
                    "file_ownership_mismatch",
                    f"{field_name} source has no owner: {mapping['source_file']}",
                )
            for asset in mapping.get("asset_mappings", []):
                if asset["target_resource_path"] not in file_owners:
                    raise ContractError(
                        "file_ownership_mismatch",
                        f"asset target has no owner: {asset['target_resource_path']}",
                    )
    return {
        **plan,
        "layout_decisions": [
            {
                "design_state_id": design_state_id,
                "decisions": copy.deepcopy(authored_layouts[design_state_id]),
            }
            for design_state_id in layout_inputs
        ],
        "layout_contracts": layout_contracts,
        "pages": pages,
        "component_mappings": component_mappings,
        "interaction_mappings": interaction_mappings,
        "api_contract_mappings": api_contract_mappings,
        "design_element_mappings": design_mappings,
        "semantic_fact_mappings": fact_mappings,
        "integration_test_cases": cases,
        "execution_nodes": nodes,
        "file_owners": dict(sorted(file_owners.items())),
        "presentation_mappings": presentations,
        "runtime_entries": runtime_entries,
        "runtime_probe_provider": runtime_probe_provider,
        "visual_capture_cases": visual_capture_cases,
    }


def build_codegen_packet(
    page_key: str, plan: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    page = next(item for item in plan["pages"] if item["page_key"] == page_key)
    instance_ids = set(page["component_instance_ids"])
    fact_ids = {
        binding["fact_id"]
        for instance in universe["component_instances"]
        if instance["component_instance_id"] in instance_ids
        for binding in instance["fact_bindings"]
    }
    component_ids = {
        item["component_id"]
        for item in universe["component_instances"]
        if item["component_instance_id"] in instance_ids
    }
    return {
        "schema": "icp.implementation.codegen-packet.v3",
        "common_rules": plan["common_rules"],
        "platform_best_practices": plan["platform_best_practices"],
        "implementation_prompt": plan["implementation_prompt"],
        "runtime_probe_provider": plan["runtime_probe_provider"],
        "page": page,
        "locked_page": next(item for item in universe["pages"] if item["page_key"] == page_key),
        "component_definitions": [
            item for item in universe["component_definitions"] if item["component_id"] in component_ids
        ],
        "component_instances": [
            item for item in universe["component_instances"] if item["component_instance_id"] in instance_ids
        ],
        "component_mappings": [
            item for item in plan["component_mappings"] if item["component_instance_id"] in instance_ids
        ],
        "interaction_graph": next(
            item for item in universe["interaction_graphs"] if item["page_key"] == page_key
        ),
        "interaction_mappings": [
            item for item in plan["interaction_mappings"] if item["page_key"] == page_key
        ],
        "api_contracts": [
            item for item in universe["api_contracts"] if item["page_key"] == page_key
        ],
        "api_contract_mappings": [
            item for item in plan["api_contract_mappings"] if item["page_key"] == page_key
        ],
        "blocks": [item for item in universe["blocks"] if item["component_instance_id"] in instance_ids],
        "design_elements": [
            item for item in universe["design_elements"] if item["component_instance_id"] in instance_ids
        ],
        "design_element_evidence_channels": [
            item
            for item in universe["design_element_evidence_channels"]
            if item["obligation_id"]
            in {
                value["obligation_id"]
                for value in universe["design_elements"]
                if value["component_instance_id"] in instance_ids
            }
        ],
        "design_element_mappings": [
            item
            for item in plan["design_element_mappings"]
            if item["obligation_id"]
            in {value["obligation_id"] for value in universe["design_elements"] if value["component_instance_id"] in instance_ids}
        ],
        "reference_viewport_assertions": [
            item
            for item in universe["reference_viewport_assertions"]
            if item["component_instance_id"] in instance_ids
        ],
        "semantic_facts": [item for item in universe["semantic_facts"] if item["fact_id"] in fact_ids],
        "semantic_fact_mappings": [item for item in plan["semantic_fact_mappings"] if item["fact_id"] in fact_ids],
        "integration_obligations": [item for item in universe["integration_obligations"] if item["page_key"] == page_key],
        "integration_test_cases": [item for item in plan["integration_test_cases"] if item["page_key"] == page_key],
        "presentation_usages": [item for item in universe["presentation_usages"] if item["source_page_key"] == page_key],
        "presentation_mappings": [
            item
            for item in plan["presentation_mappings"]
            if item["usage_id"] in {value["usage_id"] for value in universe["presentation_usages"] if value["source_page_key"] == page_key}
        ],
        "visual_capture_cases": [
            item
            for item in plan["visual_capture_cases"]
            if item["design_name"]
            in {
                block["design_name"]
                for block in universe["blocks"]
                if block["component_instance_id"] in instance_ids
            }
        ],
        "layout_contracts": [
            item
            for item in plan["layout_contracts"]
            if item["page_key"] == page_key
        ],
    }


def record_plan(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    recovering = plan_path.is_file()
    if state.get("state") != "awaiting_plan" and not recovering:
        raise ContractError("invalid_state", f"implementation state is {state.get('state')}")
    if not recovering:
        implementation_checklist_call(
            stage_dir, state, universe, "ready", node_id="plan.record"
        )
    attempts_path = stage_dir / "layout-decision-attempts.json"
    if attempts_path.is_file():
        attempt_history = require_dict(
            read_json(attempts_path), "layout decision attempts"
        )
    else:
        attempt_history = {
            "schema": "icp.implementation.layout-decision-attempts",
            "max_attempts": MAX_LAYOUT_DECISION_ATTEMPTS,
            "attempts": [],
        }
    attempts = require_list(attempt_history.get("attempts"), "layout decision attempts")
    if len(attempts) >= MAX_LAYOUT_DECISION_ATTEMPTS:
        raise ContractError(
            "component_layout_retry_exhausted",
            "component layout needs Stage 1 or Stage 2 repair after repeated whole-page failures",
            details={"attempts": len(attempts), "max_attempts": MAX_LAYOUT_DECISION_ATTEMPTS},
        )
    raw_plan = read_json(Path(args.plan))
    try:
        plan = validate_plan(raw_plan, state, universe)
    except ContractError as exc:
        if exc.code == "component_layout_decision_invalid":
            problems = require_list(
                require_dict(exc.details, "layout decision failure details").get("problems"),
                "layout decision problems",
            )
            attempts.append(
                {
                    "attempt": len(attempts) + 1,
                    "plan_sha256": digest(raw_plan),
                    "problems": copy.deepcopy(problems),
                }
            )
            attempt_history["attempts"] = attempts
            atomic_write_json(attempts_path, attempt_history)
        raise
    if recovering:
        if read_json(plan_path) != plan:
            raise ContractError(
                "plan_already_recorded",
                "implementation plan is append-only and differs from the retry",
            )
        materialize_android_test_files(project_root, plan, recovering=True)
    else:
        materialize_android_test_files(project_root, plan, recovering=False)
        atomic_write_json(plan_path, plan)
    for page_key in universe["page_keys"]:
        atomic_write_json(
            stage_dir / "codegen-packets" / f"{page_key}.json",
            build_codegen_packet(page_key, plan, universe),
        )
    tdd_path = stage_dir / "tdd-evidence.json"
    initial_tdd_evidence = {
            "schema": "icp.implementation.tdd-evidence.v1",
            "implementation_plan_sha256": file_sha(plan_path),
            "cases": [
                {
                    "case_id": case["case_id"],
                    "obligation_id": case["obligation_id"],
                    "source_kind": case["source_kind"],
                    "fact_id": case["fact_id"],
                    "basis_fact_ids": case["basis_fact_ids"],
                    "component_instance_id": case["component_instance_id"],
                    "page_key": case["page_key"],
                    "command": case["command"],
                    "red": None,
                    "green": None,
                }
                for case in plan["integration_test_cases"]
            ],
        }
    if tdd_path.is_file():
        existing_tdd = require_dict(read_json(tdd_path), "TDD evidence")
        existing_cases = require_list(existing_tdd.get("cases"), "TDD evidence cases")
        expected_case_identity = [
            {
                key: case[key]
                for key in (
                    "case_id",
                    "obligation_id",
                    "source_kind",
                    "fact_id",
                    "basis_fact_ids",
                    "component_instance_id",
                    "page_key",
                    "command",
                )
            }
            for case in initial_tdd_evidence["cases"]
        ]
        actual_case_identity = [
            {key: case.get(key) for key in expected_case_identity[index]}
            for index, case in enumerate(existing_cases)
        ] if len(existing_cases) == len(expected_case_identity) else []
        if (
            existing_tdd.get("schema") != initial_tdd_evidence["schema"]
            or existing_tdd.get("implementation_plan_sha256")
            != initial_tdd_evidence["implementation_plan_sha256"]
            or actual_case_identity != expected_case_identity
        ):
            raise ContractError(
                "stage_drift", "existing TDD evidence differs from the recorded plan"
            )
        validate_tdd_evidence(
            project_root, plan, existing_tdd, require_complete=False
        )
        actual_tdd_sha = file_sha(tdd_path)
        anchored_tdd_sha = state.get("tdd_evidence_sha256")
        if anchored_tdd_sha is None:
            if existing_tdd != initial_tdd_evidence:
                raise ContractError(
                    "stage_drift",
                    "unanchored TDD evidence contains recorded results",
                )
        elif actual_tdd_sha != anchored_tdd_sha:
            validate_case_transaction(
                stage_dir, state, tdd_path, existing_tdd
            )
        tdd_evidence = existing_tdd
    else:
        atomic_write_json(tdd_path, initial_tdd_evidence)
        tdd_evidence = initial_tdd_evidence
    state["implementation_plan_sha256"] = file_sha(plan_path)
    state["tdd_evidence_sha256"] = file_sha(tdd_path)
    if all(case.get("green") is not None for case in tdd_evidence["cases"]):
        state["state"] = "awaiting_verification"
    elif all(case.get("red") is not None for case in tdd_evidence["cases"]):
        state["state"] = "awaiting_implementation"
    else:
        state["state"] = "awaiting_red" if plan["integration_test_cases"] else "awaiting_implementation"
    atomic_write_json(stage_dir / "state.json", state)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id="plan.record",
        evidence_sha256=state["implementation_plan_sha256"],
    )
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "page_count": len(plan["pages"]),
        "integration_case_count": len(plan["integration_test_cases"]),
    }


def run_case(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    with exclusive_case_recording(project_root):
        return run_case_locked(args, project_root)


ANDROID_TEST_SELECTOR_PREFIX = (
    "-Pandroid.testInstrumentationRunnerArguments.class="
)


def kotlin_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def android_test_identity(planned_case: dict[str, Any]) -> tuple[str, str]:
    selectors = [
        argument[len(ANDROID_TEST_SELECTOR_PREFIX) :]
        for argument in planned_case["command"][1:]
        if argument.startswith(ANDROID_TEST_SELECTOR_PREFIX)
    ]
    if len(selectors) != 1 or selectors[0].count("#") != 1:
        raise ContractError(
            "integration_runtime_unproven",
            f"exact Android test selector is missing: {planned_case['case_id']}",
        )
    return tuple(selectors[0].split("#", 1))


def render_runtime_ui_step(step: dict[str, Any], *, assertion: bool) -> list[str]:
    operator = step["operator"]
    tag = kotlin_string(step["target_tag"]) if step["target_tag"] is not None else None
    value = kotlin_string(step["value"]) if step["value"] is not None else None
    if assertion:
        if operator == "absent":
            return [f"        assertNull(waitForNode({tag}, false))"]
        lines = [f"        val node = requireNode({tag})"]
        if operator == "visible":
            lines.append("        assertTrue(node.isVisibleToUser)")
        elif operator == "enabled":
            lines.append("        assertTrue(node.isEnabled)")
        elif operator == "disabled":
            lines.append("        assertFalse(node.isEnabled)")
        elif operator == "selected":
            lines.append("        assertTrue(node.isSelected)")
        elif operator == "unselected":
            lines.append("        assertFalse(node.isSelected)")
        elif operator == "text_equals":
            lines.append(f"        assertEquals({value}, nodeText(node))")
        elif operator == "text_contains":
            lines.append(f"        assertTrue(nodeText(node).contains({value}))")
        return ["        run {", *lines, "        }"]
    if operator == "press_back":
        return [
            "        assertTrue(uiAutomation.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK))",
            "        instrumentation.waitForIdleSync()",
        ]
    lines = [f"        val node = requireNode({tag})"]
    if operator == "click":
        lines.append("        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))")
    elif operator == "input_text":
        lines.extend(
            [
                "        val arguments = Bundle()",
                (
                    "        arguments.putCharSequence("
                    "AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "
                    f"{value})"
                ),
                "        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments))",
            ]
        )
    lines.append("        instrumentation.waitForIdleSync()")
    return ["        run {", *lines, "        }"]


def render_runtime_result_observation(step: dict[str, Any]) -> str:
    tag = kotlin_string(step["target_tag"])
    operator = step["operator"]
    if operator == "absent":
        return f"findNode({tag}) == null"
    if operator == "visible":
        return f"findNode({tag})?.isVisibleToUser == true"
    if operator == "enabled":
        return f"findNode({tag})?.isEnabled == true"
    if operator == "disabled":
        return f"findNode({tag})?.isEnabled == false"
    if operator == "selected":
        return f"findNode({tag})?.isSelected == true"
    if operator == "unselected":
        return f"findNode({tag})?.isSelected == false"
    if operator == "text_equals":
        return f"findNode({tag})?.let(::nodeText) == {kotlin_string(step['value'])}"
    if operator == "text_contains":
        return (
            f"findNode({tag})?.let(::nodeText)?.contains("
            f"{kotlin_string(step['value'])}) == true"
        )
    raise ContractError(
        "integration_runtime_unproven",
        f"unsupported result observation operator: {operator}",
    )


def kotlin_string_map(values: dict[str, str]) -> str:
    if not values:
        return "emptyMap()"
    return "mapOf(" + ", ".join(
        f"{kotlin_string(key)} to {kotlin_string(value)}"
        for key, value in sorted(values.items())
    ) + ")"


def render_android_network_support(expectation: dict[str, Any]) -> str:
    response_body = json.dumps(
        expectation["response_body"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"""
    private data class ObservedRequest(
        val method: String,
        val path: String,
        val headers: Map<String, String>,
        val body: String,
    )

    private class NetworkRecorder(
        private val responseStatus: Int,
        private val responseHeaders: Map<String, String>,
        private val responseBody: String,
        private val disconnectAfterRequest: Boolean,
    ) : AutoCloseable {{
        private val server = ServerSocket(0)
        private val requestReceived = CountDownLatch(1)
        private val responseReleased = CountDownLatch(1)
        private val completed = CountDownLatch(1)
        @Volatile private var observedRequest: ObservedRequest? = null
        @Volatile private var failure: Throwable? = null
        val baseUrl: String = "http://127.0.0.1:${{server.localPort}}"

        fun start() {{
            Thread({{
                try {{
                    server.accept().use {{ socket ->
                        val input = socket.getInputStream()
                        val headerBuffer = ByteArrayOutputStream()
                        var suffix = 0
                        while (suffix != 0x0d0a0d0a) {{
                            val value = input.read()
                            if (value < 0) error("network request ended before headers")
                            headerBuffer.write(value)
                            suffix = (suffix shl 8) or value
                        }}
                        val headerText = headerBuffer.toString(Charsets.ISO_8859_1.name())
                        val lines = headerText.removeSuffix("\\r\\n\\r\\n").split("\\r\\n")
                        val requestLine = lines.first().split(" ")
                        if (requestLine.size < 2) error("invalid HTTP request line")
                        val headers = lines.drop(1).associate {{ line ->
                            val separator = line.indexOf(':')
                            if (separator <= 0) error("invalid HTTP request header")
                            line.substring(0, separator).trim().lowercase() to
                                line.substring(separator + 1).trim()
                        }}
                        val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
                        val bodyBytes = ByteArray(contentLength)
                        var offset = 0
                        while (offset < bodyBytes.size) {{
                            val count = input.read(bodyBytes, offset, bodyBytes.size - offset)
                            if (count < 0) error("network request body ended early")
                            offset += count
                        }}
                        observedRequest = ObservedRequest(
                            method = requestLine[0],
                            path = requestLine[1],
                            headers = headers,
                            body = bodyBytes.toString(Charsets.UTF_8),
                        )
                        requestReceived.countDown()
                        if (!responseReleased.await(10, TimeUnit.SECONDS)) {{
                            error("production API response was not released")
                        }}
                        if (disconnectAfterRequest) return@use
                        val responseBytes = responseBody.toByteArray(Charsets.UTF_8)
                        val output = socket.getOutputStream()
                        val headersText = buildString {{
                            append("HTTP/1.1 $responseStatus ICP\\r\\n")
                            responseHeaders.forEach {{ (name, value) ->
                                append(name).append(": ").append(value).append("\\r\\n")
                            }}
                            append("Content-Length: ").append(responseBytes.size).append("\\r\\n")
                            append("Connection: close\\r\\n\\r\\n")
                        }}
                        output.write(headersText.toByteArray(Charsets.ISO_8859_1))
                        output.write(responseBytes)
                        output.flush()
                    }}
                }} catch (error: Throwable) {{
                    failure = error
                }} finally {{
                    requestReceived.countDown()
                    completed.countDown()
                }}
            }}, "icp-network-recorder").start()
        }}

        fun awaitRequest(): ObservedRequest {{
            assertTrue("production API request was not observed", requestReceived.await(10, TimeUnit.SECONDS))
            failure?.let {{ throw AssertionError("production API observation failed", it) }}
            return observedRequest ?: throw AssertionError("production API request was not recorded")
        }}

        fun releaseResponse() {{
            responseReleased.countDown()
        }}

        override fun close() {{
            responseReleased.countDown()
            server.close()
            completed.await(1, TimeUnit.SECONDS)
        }}
    }}

    private fun canonicalJson(raw: String): String {{
        fun canonical(value: Any?): String = when (value) {{
            null, JSONObject.NULL -> "null"
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(
                prefix = "{{", postfix = "}}"
            ) {{ key -> JSONObject.quote(key) + ":" + canonical(value.get(key)) }}
            is JSONArray -> (0 until value.length()).joinToString(
                prefix = "[", postfix = "]"
            ) {{ index -> canonical(value.get(index)) }}
            is String -> JSONObject.quote(value)
            is Number, is Boolean -> value.toString()
            else -> error("unsupported JSON value")
        }}
        return canonical(JSONTokener(raw).nextValue())
    }}
"""


def render_android_test_source(planned_case: dict[str, Any]) -> bytes:
    class_name, method_name = android_test_identity(planned_case)
    simple_class = class_name.rsplit(".", 1)[-1]
    package_name = class_name.rsplit(".", 1)[0] if "." in class_name else ""
    runtime_test = require_dict(
        planned_case.get("runtime_test"), "runtime UI test contract"
    )
    network_expectation = runtime_test.get("network_expectation")
    mock_expectation = runtime_test.get("mock_expectation")
    response_probe = (
        network_expectation["response_probe"]
        if network_expectation is not None
        else (
            mock_expectation["response_probe"]
            if mock_expectation is not None
            else None
        )
    )
    body = [
        f"        assertTrue(requireNode({kotlin_string(runtime_test['entry_tag'])}).isVisibleToUser)"
    ]
    for step in runtime_test["preconditions"]:
        body.extend(render_runtime_ui_step(step, assertion=True))
    result_observations = [
        render_runtime_result_observation(step)
        for step in runtime_test["assertions"]
    ]
    if runtime_test["actions"]:
        body.extend(
            [
                "        val beforeResultObservations = listOf("
                + ", ".join(result_observations)
                + ")",
                (
                    '        assertFalse("production result already satisfied before trigger", '
                    "beforeResultObservations.any { it })"
                ),
            ]
        )
    for step in runtime_test["actions"]:
        body.extend(render_runtime_ui_step(step, assertion=False))
    if network_expectation is not None:
        expected_request_body = network_expectation["request_body"]
        body.extend(
            [
                "        val observedRequest = networkRecorder.awaitRequest()",
                "        assertEquals("
                + kotlin_string(network_expectation["method"])
                + ", observedRequest.method)",
                "        assertEquals("
                + kotlin_string(network_expectation["path"])
                + ", observedRequest.path)",
            ]
        )
        for name, value in sorted(network_expectation["request_headers"].items()):
            body.append(
                "        assertEquals("
                + kotlin_string(value)
                + ", observedRequest.headers["
                + kotlin_string(name.lower())
                + "])"
            )
        if expected_request_body is None:
            body.append("        assertTrue(observedRequest.body.isEmpty())")
        else:
            expected_body = json.dumps(
                expected_request_body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            body.append(
                "        assertEquals(canonicalJson("
                + kotlin_string(expected_body)
                + "), canonicalJson(observedRequest.body))"
            )
        body.extend(
            [
                "        val beforeApiResponseObservations = listOf("
                + ", ".join(result_observations)
                + ")",
                (
                    '        assertFalse("production result appeared before API '
                    + (
                        "failure"
                        if network_expectation["mode"] == "disconnect"
                        else "response"
                    )
                    + '", '
                    "beforeApiResponseObservations.any { it })"
                ),
                "        networkRecorder.releaseResponse()",
            ]
        )
    for step in runtime_test["assertions"]:
        body.extend(render_runtime_ui_step(step, assertion=True))
    if response_probe is not None:
        probe_source = "API response" if network_expectation is not None else "mock DTO"
        body.append(
            f'        assertTrue("production UI did not render the {probe_source} value", '
            "waitForResponseValue("
            + kotlin_string(response_probe["target_tag"])
            + ", responseCanary, "
            + ("true" if response_probe["operator"] == "text_contains" else "false")
            + "))"
        )
    if runtime_test["actions"]:
        body.extend(
            [
                "        val afterResultObservations = listOf("
                + ", ".join(result_observations)
                + ")",
                (
                    '        assertTrue("production result was not satisfied after trigger", '
                    "afterResultObservations.all { it })"
                ),
            ]
        )
    network_imports = "" if network_expectation is None else """
import java.io.ByteArrayOutputStream
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.After
"""
    canary_import = "" if response_probe is None else "import java.util.UUID\n"
    network_field = (
        "    private lateinit var networkRecorder: NetworkRecorder\n"
        if network_expectation is not None
        else ""
    )
    canary_field = (
        "    private val responseCanary: String = UUID.randomUUID().toString()\n"
        if response_probe is not None
        else ""
    )
    network_setup = ""
    mock_setup = ""
    mock_intent = ""
    network_teardown = ""
    network_support = ""
    if network_expectation is not None:
        disconnect_after_request = network_expectation["mode"] == "disconnect"
        response_body = (
            ""
            if disconnect_after_request
            else json.dumps(
                network_expectation["response_body"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        rendered_response_body = kotlin_string(response_body)
        if response_probe is not None:
            rendered_response_body += '.replace("__ICP_RUNTIME_CANARY__", responseCanary)'
        network_setup = f"""        networkRecorder = NetworkRecorder(
            responseStatus = {network_expectation['response_status'] or 0},
            responseHeaders = {kotlin_string_map(network_expectation['response_headers'])},
            responseBody = {rendered_response_body},
            disconnectAfterRequest = {str(disconnect_after_request).lower()},
        )
        networkRecorder.start()
"""
        network_teardown = """
    @After
    fun stopNetworkRecorder() {
        networkRecorder.close()
    }
"""
        network_support = render_android_network_support(network_expectation)
    if mock_expectation is not None:
        mock_body = json.dumps(
            mock_expectation["body"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        mock_setup = (
            "        val mockPayload = "
            + kotlin_string(mock_body)
            + '.replace("__ICP_RUNTIME_CANARY__", responseCanary)\n'
        )
        mock_intent = 'intent.putExtra("icp_mock_payload", mockPayload)'
    source = f"""package {package_name}

import android.accessibilityservice.AccessibilityService
import android.app.Instrumentation
import android.app.UiAutomation
import android.content.Intent
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.ArrayDeque
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
{network_imports}
{canary_import}

@RunWith(AndroidJUnit4::class)
class {simple_class} {{
    private lateinit var instrumentation: Instrumentation
    private lateinit var uiAutomation: UiAutomation
    private lateinit var productionPackage: String
{network_field}
{canary_field}

    @Before
    fun launchProductionApp() {{
        instrumentation = InstrumentationRegistry.getInstrumentation()
        uiAutomation = instrumentation.uiAutomation
{network_setup}{mock_setup}        val context = instrumentation.targetContext
        productionPackage = context.packageName
        val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)
        assertNotNull("production launcher activity is missing", intent)
        intent!!.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        {"intent.putExtra(\"icp_api_base_url\", networkRecorder.baseUrl)" if network_expectation is not None else ""}
        {mock_intent}
        instrumentation.startActivitySync(intent)
        instrumentation.waitForIdleSync()
    }}
{network_teardown}
{network_support}

    private fun matches(node: AccessibilityNodeInfo, tag: String): Boolean {{
        val belongsToProductionPackage =
            node.packageName?.toString() == productionPackage
        if (!belongsToProductionPackage) return false
        val resource = node.viewIdResourceName.orEmpty()
        val descriptions = node.contentDescription?.toString().orEmpty()
            .split(Regex("\\\\s+"))
        return resource == tag || resource.endsWith("/$tag") || tag in descriptions
    }}

    private fun matchingNodes(tag: String): List<AccessibilityNodeInfo> {{
        val root = uiAutomation.rootInActiveWindow ?: return emptyList()
        val matches = mutableListOf<AccessibilityNodeInfo>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty()) {{
            val node = queue.removeFirst()
            if (matches(node, tag)) matches.add(node)
            repeat(node.childCount) {{ index ->
                node.getChild(index)?.let(queue::addLast)
            }}
        }}
        return matches
    }}

    private fun findNode(tag: String): AccessibilityNodeInfo? {{
        val nodes = matchingNodes(tag)
        assertTrue("production UI tag is not unique: $tag", nodes.size <= 1)
        return nodes.singleOrNull()
    }}

    private fun waitForNode(tag: String, present: Boolean): AccessibilityNodeInfo? {{
        repeat(50) {{
            val node = findNode(tag)
            if ((node != null) == present) return node
            Thread.sleep(100)
        }}
        return findNode(tag)
    }}

    private fun requireNode(tag: String): AccessibilityNodeInfo {{
        val node = waitForNode(tag, true)
        assertNotNull("production UI tag is not reachable: $tag", node)
        return node!!
    }}

    private fun nodeText(node: AccessibilityNodeInfo): String =
        node.text?.toString() ?: node.contentDescription?.toString().orEmpty()

    private fun waitForResponseValue(
        tag: String,
        expected: String,
        contains: Boolean,
    ): Boolean {{
        repeat(50) {{
            val actual = findNode(tag)?.let(::nodeText)
            if (actual != null && (if (contains) actual.contains(expected) else actual == expected)) {{
                return true
            }}
            Thread.sleep(100)
        }}
        return false
    }}

    @Test
    fun {method_name}() {{
{chr(10).join(body)}
    }}
}}
"""
    return source.encode("utf-8")


def materialize_android_test_files(
    project_root: Path, plan: dict[str, Any], *, recovering: bool
) -> None:
    if plan.get("platform") != "android-kotlin":
        return
    for planned_case in plan["integration_test_cases"]:
        path = project_file(
            project_root, planned_case["test_file"], "integration test file"
        )
        expected = render_android_test_source(planned_case)
        if recovering:
            if not path.is_file() or path.read_bytes() != expected:
                raise ContractError(
                    "test_contract_changed",
                    "frozen test differs from its ICP-generated real UI contract: "
                    + planned_case["case_id"],
                )
        else:
            atomic_write(path, expected)


def kotlin_class_declares_method(
    source: str, class_name: str, method_name: str
) -> bool:
    executable = source_without_comments_or_literals(source)
    for class_match in re.finditer(
        rf"\bclass\s+{re.escape(class_name)}\b", executable
    ):
        body_start = executable.find("{", class_match.end())
        if body_start < 0:
            continue
        depth = 0
        body_end = None
        for position in range(body_start, len(executable)):
            token = executable[position]
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                if depth == 0:
                    body_end = position
                    break
        if body_end is None:
            continue
        for method_match in re.finditer(
            rf"\bfun\s+{re.escape(method_name)}\s*\(",
            executable[body_start + 1 : body_end],
        ):
            prefix = executable[body_start + 1 : body_start + 1 + method_match.start()]
            if prefix.count("{") == prefix.count("}"):
                return True
    return False


def exact_android_test_contract(
    project_root: Path, planned_case: dict[str, Any]
) -> dict[str, str]:
    class_name, method_name = android_test_identity(planned_case)
    if not class_name or method_name != planned_case["test_name"]:
        raise ContractError(
            "integration_runtime_unproven",
            f"Android test selector does not match the planned case: {planned_case['case_id']}",
        )
    test_path = project_file(
        project_root, planned_case["test_file"], "integration test file"
    )
    if not test_path.is_file():
        raise ContractError(
            "integration_test_missing",
            f"integration test file does not exist: {planned_case['test_file']}",
        )
    if test_path.read_bytes() != render_android_test_source(planned_case):
        raise ContractError(
            "test_contract_changed",
            "frozen test differs from its ICP-generated real UI contract: "
            + planned_case["case_id"],
        )
    runner_path = project_file(
        project_root, planned_case["command"][0], "Gradle wrapper"
    )
    if not runner_path.is_file() or not os.access(runner_path, os.X_OK):
        raise ContractError(
            "integration_runtime_unproven", "the frozen Gradle wrapper is unavailable"
        )
    repository = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if repository.returncode == 0:
        repository_root = Path(repository.stdout.strip()).resolve()
        try:
            runner_relative = runner_path.resolve().relative_to(repository_root)
        except ValueError as exc:
            raise ContractError(
                "integration_runtime_unproven",
                "the Gradle wrapper is outside the project repository",
            ) from exc
        baseline = subprocess.run(
            ["git", "-C", str(repository_root), "show", f"HEAD:{runner_relative.as_posix()}"],
            check=False,
            capture_output=True,
        )
        if (
            baseline.returncode != 0
            or hashlib.sha256(baseline.stdout).hexdigest() != file_sha(runner_path)
        ):
            raise ContractError(
                "integration_runtime_unproven",
                "the Gradle wrapper differs from its committed repository version",
            )
    source = test_path.read_text(encoding="utf-8")
    package_match = re.search(r"(?m)^\s*package\s+([A-Za-z_][\w.]*)\s*$", source)
    simple_class = class_name.rsplit(".", 1)[-1]
    expected_package = class_name.rsplit(".", 1)[0] if "." in class_name else ""
    if (
        (package_match.group(1) if package_match else "") != expected_package
        or not kotlin_class_declares_method(source, simple_class, method_name)
    ):
        raise ContractError(
            "integration_test_mismatch",
            f"planned Android test is not declared by its test file: {planned_case['case_id']}",
        )
    return {
        "class_name": class_name,
        "method_name": method_name,
        "test_file_sha256": file_sha(test_path),
        "test_runner_sha256": file_sha(runner_path),
        "device_task_path": android_device_task_path(planned_case),
    }


def android_device_task_path(planned_case: dict[str, Any]) -> str:
    test_parts = Path(
        require_relative_path(
            planned_case.get("test_file"), "integration test file"
        )
    ).parts
    try:
        source_index = test_parts.index("src")
    except ValueError as exc:
        raise ContractError(
            "integration_runtime_unproven",
            "Android integration test is outside a Gradle module",
        ) from exc
    module_parts = test_parts[:source_index]
    if not module_parts:
        raise ContractError(
            "integration_runtime_unproven",
            "Android integration test module is missing",
        )
    command = validate_command(
        planned_case.get("command"), "planned Android test command"
    )
    device_tasks = [
        argument
        for argument in command[1:]
        if re.fullmatch(
            r"(?::[A-Za-z0-9_.-]+:)?connected[A-Za-z0-9_.-]*AndroidTest",
            argument,
        )
    ]
    if len(device_tasks) != 1:
        raise ContractError(
            "integration_runtime_unproven", "Android device task is ambiguous"
        )
    simple_task = device_tasks[0].rsplit(":", 1)[-1]
    task_path = ":" + ":".join((*module_parts, simple_task))
    if device_tasks[0].startswith(":") and device_tasks[0] != task_path:
        raise ContractError(
            "integration_runtime_unproven",
            "Android device task targets another Gradle module",
        )
    return task_path


def validate_android_device_task_output(
    stdout: str, contract: dict[str, str]
) -> None:
    task_path = re.escape(contract["device_task_path"])
    path_observed = re.search(rf"(?m)^Path\s*\n\s*{task_path}\s*$", stdout)
    type_observed = re.search(
        r"(?m)^Type\s*\n\s*DeviceProviderInstrumentTestTask "
        r"\(com\.android\.build\.gradle\.internal\.tasks\."
        r"DeviceProviderInstrumentTestTask\)\s*$",
        stdout,
    )
    if path_observed is None or type_observed is None:
        raise ContractError(
            "android_device_task_unproven",
            "Gradle did not attest the selected task as AGP's device provider test task",
        )


def attest_android_runtime_installation(
    project_root: Path,
    plan: dict[str, Any],
    page_key: str,
    *,
    device_serial: str | None,
) -> dict[str, Any]:
    planned_case = next(
        (
            case
            for case in plan["integration_test_cases"]
            if case["page_key"] == page_key
        ),
        None,
    )
    if planned_case is None:
        raise ContractError(
            "android_runtime_install_unproven",
            f"page has no device test able to install its production APK: {page_key}",
        )
    contract = exact_android_test_contract(project_root, planned_case)
    command = validate_command(
        planned_case.get("command"), "planned Android test command"
    )
    build_clean = clean_android_build_outputs(
        project_root,
        command[0],
        device_serial=device_serial,
    )
    executed_command = [
        command[0],
        "help",
        "--task",
        contract["device_task_path"],
        contract["device_task_path"],
    ]
    executed_command.append(command[2])
    clear_android_test_reports(project_root)
    started_ns = time.time_ns()
    try:
        completed = subprocess.run(
            executed_command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
            env=android_test_environment(device_serial),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            "android_runtime_install_unproven",
            f"cannot build, install, and test the production APK: {exc}",
        ) from exc
    validate_android_device_task_output(completed.stdout, contract)
    test_result = exact_android_test_result(project_root, contract, started_ns)
    if (
        completed.returncode != 0
        or test_result is None
        or test_result["status"] != "passed"
        or test_result["device"] not in completed.stdout
    ):
        raise ContractError(
            "android_runtime_install_unproven",
            f"AGP did not install and test the current production APK: {page_key}",
        )
    built_apks = android_build_apk_inventory(project_root)
    if not built_apks:
        raise ContractError(
            "android_runtime_install_unproven",
            "the clean AGP transaction produced no APK",
        )
    return {
        "case_id": planned_case["case_id"],
        "device_task_path": contract["device_task_path"],
        "test_file_sha256": contract["test_file_sha256"],
        "test_runner_sha256": contract["test_runner_sha256"],
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "device_test_result": test_result,
        "build_clean": build_clean,
        "built_apks": built_apks,
    }


def validate_android_runtime_installation(
    value: object,
    project_root: Path,
    plan: dict[str, Any],
    page_key: str,
) -> dict[str, Any]:
    receipt = require_dict(value, "Android runtime installation receipt")
    require_exact_keys(
        receipt,
        {
            "case_id",
            "device_task_path",
            "test_file_sha256",
            "test_runner_sha256",
            "stdout_sha256",
            "stderr_sha256",
            "device_test_result",
            "build_clean",
            "built_apks",
        },
        "Android runtime installation receipt",
    )
    planned_case = next(
        (
            case
            for case in plan["integration_test_cases"]
            if case["case_id"] == receipt.get("case_id")
            and case["page_key"] == page_key
        ),
        None,
    )
    if planned_case is None:
        raise ContractError(
            "android_runtime_install_unproven",
            f"runtime installation targets another page: {page_key}",
        )
    contract = exact_android_test_contract(project_root, planned_case)
    device_result = require_dict(
        receipt.get("device_test_result"), "runtime installation device result"
    )
    if (
        receipt.get("device_task_path") != contract["device_task_path"]
        or receipt.get("test_file_sha256") != contract["test_file_sha256"]
        or receipt.get("test_runner_sha256") != contract["test_runner_sha256"]
        or device_result.get("class_name") != contract["class_name"]
        or device_result.get("test_name") != contract["method_name"]
        or device_result.get("status") != "passed"
        or any(
            not isinstance(receipt.get(field), str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt[field])
            for field in ("stdout_sha256", "stderr_sha256")
        )
    ):
        raise ContractError(
            "android_runtime_install_unproven",
            f"runtime installation is not bound to current production code: {page_key}",
        )
    command = validate_command(
        planned_case.get("command"), "planned Android test command"
    )
    clean = require_dict(receipt.get("build_clean"), "Android build clean receipt")
    require_exact_keys(
        clean,
        {
            "command",
            "exit_code",
            "stdout_sha256",
            "stderr_sha256",
            "stale_apk_paths",
            "stale_apks_absent_after_clean",
        },
        "Android build clean receipt",
    )
    stale_paths = require_string_list(
        clean.get("stale_apk_paths"), "stale APK paths", nonempty=False
    )
    if (
        clean.get("command") != [command[0], "clean"]
        or clean.get("exit_code") != 0
        or clean.get("stale_apks_absent_after_clean") is not True
        or stale_paths != sorted(set(stale_paths))
        or any(
            not isinstance(clean.get(field), str)
            or re.fullmatch(r"[0-9a-f]{64}", clean[field]) is None
            for field in ("stdout_sha256", "stderr_sha256")
        )
    ):
        raise ContractError(
            "android_clean_build_unproven",
            "runtime installation did not begin from a clean Android build",
        )
    built_apks = validate_android_build_apk_inventory(
        receipt.get("built_apks"), project_root
    )
    return {**receipt, "build_clean": clean.copy(), "built_apks": built_apks}


def android_build_apk_inventory(project_root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(
        (
            path
            for path in project_root.rglob("*.apk")
            if "build" in path.relative_to(project_root).parts
        ),
        key=lambda value: value.relative_to(project_root).as_posix(),
    ):
        payload = path.read_bytes()
        result.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return result


def validate_android_build_apk_inventory(
    value: object, project_root: Path
) -> list[dict[str, Any]]:
    entries = require_list(value, "Android build APK inventory")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        label = f"Android build APK inventory[{index}]"
        item = require_dict(raw, label)
        require_exact_keys(item, {"path", "size", "sha256"}, label)
        path = project_file(project_root, item.get("path"), label)
        relative = path.relative_to(project_root)
        if (
            path.suffix != ".apk"
            or "build" not in relative.parts
            or type(item.get("size")) is not int
            or item["size"] <= 0
            or path.stat().st_size != item["size"]
            or not isinstance(item.get("sha256"), str)
            or file_sha(path) != item["sha256"]
        ):
            raise ContractError(
                "android_runtime_install_unproven",
                "built APK inventory changed or is invalid",
            )
        normalized.append(item.copy())
    paths = [item["path"] for item in normalized]
    if not normalized or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ContractError(
            "android_runtime_install_unproven",
            "built APK inventory is empty, unordered, or ambiguous",
        )
    return normalized


def validate_android_execution_transaction(
    installation_value: object,
    package_identity_value: object,
    project_root: Path,
    plan: dict[str, Any],
    page_key: str,
) -> dict[str, Any]:
    installation = validate_android_runtime_installation(
        installation_value, project_root, plan, page_key
    )
    package_names = {
        capture["package_name"]
        for capture in plan["visual_capture_cases"]
        if capture["page_key"] == page_key
    }
    if len(package_names) != 1:
        raise ContractError(
            "android_runtime_identity_unproven",
            f"one page targets multiple Android packages: {page_key}",
        )
    identity = validate_android_package_identity(
        package_identity_value, next(iter(package_names))
    )
    built_by_sha: dict[str, list[str]] = {}
    for item in installation["built_apks"]:
        built_by_sha.setdefault(item["sha256"], []).append(item["path"])
    unmatched = []
    ambiguous = []
    installed_apk_matches: list[dict[str, str]] = []
    for installed in identity["apks"]:
        matches = built_by_sha.get(installed["sha256"], [])
        if not matches:
            unmatched.append(installed["name"])
        elif len(matches) != 1:
            ambiguous.append({"name": installed["name"], "paths": matches})
        else:
            installed_apk_matches.append(
                {
                    "installed_name": installed["name"],
                    "built_path": matches[0],
                    "sha256": installed["sha256"],
                }
            )
    if unmatched or ambiguous:
        raise ContractError(
            "android_runtime_identity_unproven",
            "installed production APKs do not uniquely match this clean build",
            details={"unmatched": unmatched, "ambiguous": ambiguous},
        )
    return {
        "installation": installation,
        "package_identity": identity,
        "installed_apk_matches": installed_apk_matches,
    }


def clean_build_base_apk(
    transaction: dict[str, Any], project_root: Path
) -> tuple[Path, str]:
    matches = [
        item
        for item in transaction.get("installed_apk_matches", [])
        if isinstance(item, dict) and item.get("installed_name") == "base.apk"
    ]
    if len(matches) != 1:
        raise ContractError(
            "android_runtime_identity_unproven",
            "installed base APK does not uniquely match the clean build",
        )
    path = project_file(project_root, matches[0].get("built_path"), "clean-build APK")
    sha256 = matches[0].get("sha256")
    if path.suffix != ".apk" or not isinstance(sha256, str) or file_sha(path) != sha256:
        raise ContractError(
            "android_runtime_identity_unproven",
            "clean-build base APK changed before visual measurement",
        )
    return path, sha256


def clean_android_build_outputs(
    project_root: Path,
    gradle_executable: str,
    *,
    device_serial: str | None,
) -> dict[str, Any]:
    stale_apks = sorted(
        str(path.relative_to(project_root))
        for path in project_root.rglob("*.apk")
        if "build" in path.relative_to(project_root).parts
    )
    clean_command = [gradle_executable, "clean"]
    try:
        clean_result = subprocess.run(
            clean_command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
            env=android_test_environment(device_serial),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            "build_clean_failed", f"cannot clean prior build outputs: {exc}"
        ) from exc
    remaining_apks = [
        path
        for path in project_root.rglob("*.apk")
        if "build" in path.relative_to(project_root).parts
    ]
    if clean_result.returncode != 0 or remaining_apks:
        raise ContractError(
            "build_clean_failed",
            "prior Gradle APK outputs were not removed before Android execution",
        )
    return {
        "command": clean_command,
        "exit_code": clean_result.returncode,
        "stdout_sha256": hashlib.sha256(
            clean_result.stdout.encode("utf-8")
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(
            clean_result.stderr.encode("utf-8")
        ).hexdigest(),
        "stale_apk_paths": stale_apks,
        "stale_apks_absent_after_clean": True,
    }


def validate_android_package_identity(
    value: object, expected_package_name: str
) -> dict[str, Any]:
    identity = require_dict(value, "installed Android package identity")
    require_exact_keys(
        identity,
        {"package_name", "apks", "sha256"},
        "installed Android package identity",
    )
    apks = require_list(identity.get("apks"), "installed Android APK identities")
    normalized: list[dict[str, Any]] = []
    names: list[str] = []
    for index, value in enumerate(apks):
        item = require_dict(value, f"installed Android APK identities[{index}]")
        require_exact_keys(
            item,
            {"name", "size", "sha256"},
            f"installed Android APK identities[{index}]",
        )
        name = require_string(item.get("name"), "installed Android APK name")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not name.endswith(".apk")
            or type(size) is not int
            or size <= 0
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        ):
            raise ContractError(
                "android_runtime_identity_unproven",
                "installed Android APK identity is invalid",
            )
        names.append(name)
        normalized.append(item.copy())
    if (
        identity.get("package_name") != expected_package_name
        or not normalized
        or names != sorted(names)
        or len(names) != len(set(names))
        or identity.get("sha256") != digest(normalized)
    ):
        raise ContractError(
            "android_runtime_identity_unproven",
            "installed Android package identity is not deterministic",
        )
    return {
        "package_name": expected_package_name,
        "apks": normalized,
        "sha256": identity["sha256"],
    }


def validate_android_package_reset(
    value: object, expected_package_name: str
) -> dict[str, Any]:
    reset = require_dict(value, "Android package reset evidence")
    require_exact_keys(
        reset,
        {"package_name", "was_installed", "absent_after_reset"},
        "Android package reset evidence",
    )
    if (
        reset.get("package_name") != expected_package_name
        or type(reset.get("was_installed")) is not bool
        or reset.get("absent_after_reset") is not True
    ):
        raise ContractError(
            "android_clean_install_unproven",
            "previous Android production package was not cleanly removed",
        )
    return reset.copy()


def clear_android_test_reports(project_root: Path) -> None:
    for report in project_root.glob("**/build/outputs/androidTest-results/**/TEST-*.xml"):
        if report.is_file():
            report.unlink()


def exact_android_test_result(
    project_root: Path, contract: dict[str, str], not_before_ns: int
) -> dict[str, Any] | None:
    matches: list[tuple[Path, ET.Element, str]] = []
    for report in project_root.glob("**/build/outputs/androidTest-results/**/TEST-*.xml"):
        if not report.is_file():
            continue
        if report.stat().st_mtime_ns < not_before_ns:
            continue
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, OSError):
            continue
        for suite in root.iter("testsuite"):
            property_devices = {
                property_node.get("value")
                for property_node in suite.findall("./properties/property")
                if property_node.get("name") == "device"
                and isinstance(property_node.get("value"), str)
                and property_node.get("value")
            }
            attribute_device = suite.get("device") or root.get("device")
            if len(property_devices) > 1 or (
                property_devices
                and isinstance(attribute_device, str)
                and attribute_device
                and attribute_device not in property_devices
            ):
                continue
            device = (
                next(iter(property_devices))
                if property_devices
                else attribute_device
            )
            if not isinstance(device, str) or not device:
                report_name = re.fullmatch(
                    r"TEST-(.+)-_[^/]+-", report.stem
                )
                device = report_name.group(1) if report_name else None
            timestamp = suite.get("timestamp") or root.get("timestamp")
            if not timestamp or not isinstance(device, str) or not device:
                continue
            for testcase in suite.findall("testcase"):
                if (
                    testcase.get("classname") == contract["class_name"]
                    and testcase.get("name") == contract["method_name"]
                ):
                    matches.append((report, testcase, device))
    if not matches:
        return None
    outcomes = {
        (
            device,
            "skipped"
            if testcase.find("skipped") is not None
            else (
                "failed"
                if testcase.find("failure") is not None
                or testcase.find("error") is not None
                else "passed"
            ),
        )
        for _report, testcase, device in matches
    }
    if len(outcomes) != 1:
        return None
    report, _testcase, device = max(
        matches, key=lambda item: item[0].stat().st_mtime_ns
    )
    status = next(iter(outcomes))[1]
    return {
        "report_path": str(report.relative_to(project_root)),
        "report_sha256": file_sha(report),
        "class_name": contract["class_name"],
        "test_name": contract["method_name"],
        "device": device,
        "status": status,
    }


def validate_tdd_evidence(
    project_root: Path,
    plan: dict[str, Any],
    evidence: dict[str, Any],
    *,
    require_complete: bool,
) -> None:
    if (
        evidence.get("schema") != "icp.implementation.tdd-evidence.v1"
        or evidence.get("implementation_plan_sha256")
        != hashlib.sha256(json_bytes(plan)).hexdigest()
    ):
        raise ContractError("stage_drift", "TDD evidence targets another plan")
    evidence_cases = require_list(evidence.get("cases"), "TDD evidence cases")
    if len(evidence_cases) != len(plan["integration_test_cases"]):
        raise ContractError("stage_drift", "TDD evidence case coverage changed")
    identity_fields = (
        "case_id",
        "obligation_id",
        "source_kind",
        "fact_id",
        "basis_fact_ids",
        "component_instance_id",
        "page_key",
        "command",
    )
    build_baselines: list[dict[str, Any]] = []
    for planned_case, evidence_value in zip(
        plan["integration_test_cases"], evidence_cases, strict=True
    ):
        evidence_case = require_dict(evidence_value, "TDD evidence case")
        if any(evidence_case.get(key) != planned_case.get(key) for key in identity_fields):
            raise ContractError(
                "stage_drift",
                f"TDD evidence identity changed: {planned_case['case_id']}",
            )
        for phase, expected_status in (("red", "failed"), ("green", "passed")):
            result_value = evidence_case.get(phase)
            if result_value is None:
                if require_complete:
                    raise ContractError(
                        "tdd_incomplete",
                        "every integration case needs RED and GREEN evidence",
                    )
                continue
            result = require_dict(result_value, f"{phase} TDD result")
            exit_code = result.get("exit_code")
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                raise ContractError("tdd_evidence_invalid", "TDD exit code is invalid")
            if (phase == "red" and exit_code == 0) or (
                phase == "green" and exit_code != 0
            ):
                raise ContractError(
                    "tdd_evidence_invalid",
                    f"{phase.upper()} command outcome is invalid: {planned_case['case_id']}",
                )
            baseline_value = result.get("build_baseline")
            if baseline_value is not None:
                if phase != "red":
                    raise ContractError(
                        "tdd_evidence_invalid",
                        "the clean build baseline may only be attached to RED evidence",
                    )
                baseline = require_dict(
                    baseline_value, "clean build baseline"
                )
                require_exact_keys(
                    baseline,
                    {
                        "command",
                        "exit_code",
                        "stdout_sha256",
                        "stderr_sha256",
                        "stale_apk_paths",
                        "stale_apks_absent_after_clean",
                    },
                    "clean build baseline",
                )
                stale_paths = require_string_list(
                    baseline.get("stale_apk_paths"),
                    "stale APK paths",
                    nonempty=False,
                )
                if (
                    baseline.get("command") != ["./gradlew", "clean"]
                    or baseline.get("exit_code") != 0
                    or not isinstance(baseline.get("stdout_sha256"), str)
                    or not isinstance(baseline.get("stderr_sha256"), str)
                    or baseline.get("stale_apks_absent_after_clean") is not True
                    or stale_paths != sorted(set(stale_paths))
                ):
                    raise ContractError(
                        "tdd_evidence_invalid", "clean build baseline is invalid"
                    )
                build_baselines.append(baseline)
            if plan["platform"] != "android-kotlin":
                continue
            test_contract = exact_android_test_contract(project_root, planned_case)
            device_result = require_dict(
                result.get("device_test_result"), f"{phase} device test result"
            )
            if (
                result.get("test_file_sha256")
                != test_contract["test_file_sha256"]
                or result.get("test_runner_sha256")
                != test_contract["test_runner_sha256"]
                or result.get("device_task_path")
                != test_contract["device_task_path"]
                or device_result.get("class_name") != test_contract["class_name"]
                or device_result.get("test_name") != test_contract["method_name"]
                or device_result.get("status") != expected_status
            ):
                raise ContractError(
                    "test_contract_changed",
                    f"frozen device test differs at final verification: {planned_case['case_id']}",
                )
    recorded_reds = [
        item
        for item in evidence_cases
        if isinstance(item, dict) and item.get("red") is not None
    ]
    if recorded_reds and len(build_baselines) != 1:
        raise ContractError(
            "tdd_evidence_invalid",
            "exactly one clean build baseline is required before the first RED",
        )


def validate_case_transaction(
    stage_dir: Path,
    state: dict[str, Any],
    evidence_path: Path,
    evidence: dict[str, Any],
) -> None:
    transaction_path = stage_dir / "case-transaction.json"
    transaction = (
        require_dict(read_json(transaction_path), "case transaction")
        if transaction_path.is_file()
        else {}
    )
    actual_evidence_sha = file_sha(evidence_path)
    evidence_cases = require_list(evidence.get("cases"), "TDD evidence cases")
    recovered_case = next(
        (
            item
            for item in evidence_cases
            if isinstance(item, dict)
            and item.get("case_id") == transaction.get("case_id")
        ),
        None,
    )
    phase = transaction.get("phase")
    recovered_result = (
        recovered_case.get(phase)
        if isinstance(recovered_case, dict) and phase in {"red", "green"}
        else None
    )
    if (
        transaction.get("schema") != "icp.implementation.case-transaction"
        or transaction.get("implementation_plan_sha256")
        != state.get("implementation_plan_sha256")
        or transaction.get("previous_evidence_sha256")
        != state.get("tdd_evidence_sha256")
        or transaction.get("next_evidence_sha256") != actual_evidence_sha
        or not isinstance(recovered_result, dict)
        or digest(recovered_result) != transaction.get("result_sha256")
    ):
        raise ContractError("stage_drift", "TDD evidence changed")


def run_case_locked(
    args: argparse.Namespace, project_root: Path
) -> dict[str, Any]:
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get("implementation_plan_sha256"):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    evidence_path = stage_dir / "tdd-evidence.json"
    transaction_path = stage_dir / "case-transaction.json"
    if not evidence_path.is_file():
        raise ContractError("stage_drift", "TDD evidence is missing")
    actual_evidence_sha = file_sha(evidence_path)
    if actual_evidence_sha != state.get("tdd_evidence_sha256"):
        recovered_evidence = require_dict(read_json(evidence_path), "TDD evidence")
        validate_case_transaction(
            stage_dir, state, evidence_path, recovered_evidence
        )
        transaction = require_dict(read_json(transaction_path), "case transaction")
        recovered_cases = require_list(
            recovered_evidence.get("cases"), "TDD evidence cases"
        )
        recovered_case = next(
            (
                item
                for item in recovered_cases
                if isinstance(item, dict)
                and item.get("case_id") == transaction.get("case_id")
            ),
            None,
        )
        recovered_result = (
            recovered_case.get(transaction.get("phase"))
            if isinstance(recovered_case, dict)
            else None
        )
        state["tdd_evidence_sha256"] = actual_evidence_sha
        if all(item.get("green") is not None for item in recovered_cases):
            state["state"] = "awaiting_verification"
        elif all(item.get("red") is not None for item in recovered_cases):
            state["state"] = "awaiting_implementation"
        else:
            state["state"] = "awaiting_red"
        atomic_write_json(stage_dir / "state.json", state)
    evidence = require_dict(read_json(evidence_path), "TDD evidence")
    validate_tdd_evidence(project_root, plan, evidence, require_complete=False)
    case_id = args.case_id
    planned_case = next(
        (item for item in plan["integration_test_cases"] if item["case_id"] == case_id),
        None,
    )
    evidence_case = next(
        (item for item in evidence["cases"] if item["case_id"] == case_id), None
    )
    if planned_case is None or evidence_case is None:
        raise ContractError("unknown_case", f"unknown integration case: {case_id}")
    phase = args.phase
    checklist_node_id = f"case:{planned_case['obligation_id']}.{phase}"
    recorded_result = evidence_case.get(phase)
    if recorded_result is not None:
        recorded_result = require_dict(recorded_result, f"recorded {phase} result")
        if plan["platform"] == "android-kotlin":
            test_contract = exact_android_test_contract(project_root, planned_case)
            device_result = require_dict(
                recorded_result.get("device_test_result"),
                f"recorded {phase} device test result",
            )
            expected_status = "failed" if phase == "red" else "passed"
            if (
                recorded_result.get("test_file_sha256")
                != test_contract["test_file_sha256"]
                or recorded_result.get("test_runner_sha256")
                != test_contract["test_runner_sha256"]
                or recorded_result.get("device_task_path")
                != test_contract["device_task_path"]
                or device_result.get("class_name") != test_contract["class_name"]
                or device_result.get("test_name") != test_contract["method_name"]
                or device_result.get("status") != expected_status
            ):
                raise ContractError(
                    "stage_drift",
                    f"recorded {phase} result differs from its frozen device test: {case_id}",
                )
        implementation_checklist_call(
            stage_dir,
            state,
            universe,
            "complete",
            node_id=checklist_node_id,
            evidence_sha256=digest(recorded_result),
        )
        if transaction_path.is_file():
            transaction_path.unlink()
        return {
            "ok": True,
            "stage": "implementation",
            "state": state["state"],
            "case_id": case_id,
            "phase": phase,
            "exit_code": recorded_result.get("exit_code"),
            "recovered": True,
        }
    if phase == "red":
        if state.get("state") not in {"awaiting_red", "awaiting_implementation"} or evidence_case.get("red") is not None:
            raise ContractError("invalid_state", f"RED is not pending for {case_id}")
    elif phase == "green":
        if state.get("state") not in {
            "awaiting_red",
            "awaiting_implementation",
            "awaiting_verification",
        }:
            raise ContractError("invalid_state", f"GREEN is not pending for {case_id}")
        if evidence_case.get("red") is None or evidence_case.get("green") is not None:
            raise ContractError("red_required", f"a fresh RED is required for {case_id}")
    else:
        raise ContractError("invalid_phase", f"unsupported TDD phase: {phase}")
    command = validate_command(planned_case.get("command"), "planned test command")
    android_test_contract = (
        exact_android_test_contract(project_root, planned_case)
        if plan["platform"] == "android-kotlin"
        else None
    )
    if (
        phase == "green"
        and android_test_contract is not None
        and (
            evidence_case["red"].get("test_file_sha256")
            != android_test_contract["test_file_sha256"]
            or evidence_case["red"].get("test_runner_sha256")
            != android_test_contract["test_runner_sha256"]
        )
    ):
        raise ContractError(
            "test_contract_changed",
            f"integration test changed between RED and GREEN: {case_id}",
        )
    if android_test_contract is not None:
        clear_android_test_reports(project_root)
    build_baseline = None
    if phase == "red" and all(item.get("red") is None for item in evidence["cases"]):
        implementation_checklist_call(
            stage_dir,
            state,
            universe,
            "ready",
            node_id="build.clean",
        )
        build_baseline = clean_android_build_outputs(
            project_root,
            command[0],
            device_serial=(
                getattr(args, "device_serial", None)
                if android_test_contract is not None
                else None
            ),
        )
        implementation_checklist_call(
            stage_dir,
            state,
            universe,
            "complete",
            node_id="build.clean",
            evidence_sha256=digest(build_baseline),
        )
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "ready",
        node_id=checklist_node_id,
    )
    command_started_ns = time.time_ns()
    executed_command = command
    if android_test_contract is not None:
        executed_command = [
            command[0],
            "help",
            "--task",
            android_test_contract["device_task_path"],
            android_test_contract["device_task_path"],
            command[2],
        ]
    try:
        completed = subprocess.run(
            executed_command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
            env=android_test_environment(
                getattr(args, "device_serial", None)
                if android_test_contract is not None
                else None
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError("test_command_failed", f"cannot execute {case_id}: {exc}") from exc
    result = {
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    if build_baseline is not None:
        result["build_baseline"] = build_baseline
    if android_test_contract is not None:
        validate_android_device_task_output(completed.stdout, android_test_contract)
        test_result = exact_android_test_result(
            project_root, android_test_contract, command_started_ns
        )
        if test_result is None:
            raise ContractError(
                f"{phase}_result_unproven",
                f"exact Android device test result is missing: {case_id}",
            )
        if test_result["device"] not in completed.stdout:
            raise ContractError(
                f"{phase}_result_unproven",
                f"Android device identity is absent from the Gradle execution: {case_id}",
            )
        result["test_file_sha256"] = android_test_contract["test_file_sha256"]
        result["test_runner_sha256"] = android_test_contract[
            "test_runner_sha256"
        ]
        result["device_task_path"] = android_test_contract["device_task_path"]
        result["device_test_result"] = test_result
        expected_status = "failed" if phase == "red" else "passed"
        expected_exit = completed.returncode != 0 if phase == "red" else completed.returncode == 0
        if test_result["status"] != expected_status or not expected_exit:
            code = "red_not_observed" if phase == "red" else "green_not_observed"
            raise ContractError(
                code,
                f"exact Android device test did not {expected_status}: {case_id}",
            )
    elif phase == "red" and completed.returncode == 0:
        raise ContractError("red_not_observed", f"test already passes before implementation: {case_id}")
    elif phase == "green" and completed.returncode != 0:
        raise ContractError("green_not_observed", f"test still fails after implementation: {case_id}")
    evidence_case[phase] = result
    next_evidence_sha = hashlib.sha256(json_bytes(evidence)).hexdigest()
    atomic_write_json(
        transaction_path,
        {
            "schema": "icp.implementation.case-transaction",
            "implementation_plan_sha256": state["implementation_plan_sha256"],
            "case_id": case_id,
            "phase": phase,
            "previous_evidence_sha256": state["tdd_evidence_sha256"],
            "next_evidence_sha256": next_evidence_sha,
            "result_sha256": digest(result),
        },
    )
    atomic_write_json(evidence_path, evidence)
    state["tdd_evidence_sha256"] = file_sha(evidence_path)
    if all(item.get("green") is not None for item in evidence["cases"]):
        state["state"] = "awaiting_verification"
    elif all(item.get("red") is not None for item in evidence["cases"]):
        state["state"] = "awaiting_implementation"
    else:
        state["state"] = "awaiting_red"
    atomic_write_json(stage_dir / "state.json", state)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id=checklist_node_id,
        evidence_sha256=digest(result),
    )
    transaction_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "case_id": case_id,
        "phase": phase,
        "exit_code": completed.returncode,
    }


def project_file(project_root: Path, relative: object, label: str) -> Path:
    text = require_relative_path(relative, label)
    path = (project_root / text).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ContractError("invalid_evidence", f"{label} escapes the project") from exc
    return path


def read_png_rgba(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError("visual_evidence_invalid", f"cannot read PNG: {path}") from exc
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContractError("visual_evidence_invalid", f"not a PNG: {path}")
    position = 8
    width = height = color_type = bit_depth = None
    palette: list[tuple[int, int, int]] = []
    transparency: list[int] = []
    chunks: list[bytes] = []
    while position < len(data):
        if position + 12 > len(data):
            raise ContractError("visual_evidence_invalid", f"truncated PNG: {path}")
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if bit_depth != 8 or interlace != 0:
                raise ContractError(
                    "visual_evidence_invalid", "only 8-bit non-interlaced PNG is supported"
                )
        elif kind == b"PLTE":
            palette = [tuple(body[index : index + 3]) for index in range(0, len(body), 3)]
        elif kind == b"tRNS":
            transparency = list(body)
        elif kind == b"IDAT":
            chunks.append(body)
        elif kind == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ContractError("visual_evidence_invalid", f"PNG missing IHDR: {path}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ContractError("visual_evidence_invalid", f"unsupported PNG color type: {color_type}")
    try:
        raw = zlib.decompress(b"".join(chunks))
    except zlib.error as exc:
        raise ContractError("visual_evidence_invalid", f"invalid PNG compression: {path}") from exc
    stride = width * channels
    rows: list[bytes] = []
    previous = [0] * stride
    offset = 0
    for _ in range(height):
        if offset + stride + 1 > len(raw):
            raise ContractError("visual_evidence_invalid", f"truncated PNG pixels: {path}")
        filter_type = raw[offset]
        offset += 1
        row = list(raw[offset : offset + stride])
        offset += stride
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + up) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                predictor = left + up - up_left
                distances = (abs(predictor - left), abs(predictor - up), abs(predictor - up_left))
                predicted = left if distances[0] <= distances[1] and distances[0] <= distances[2] else up if distances[1] <= distances[2] else up_left
                row[index] = (value + predicted) & 0xFF
            elif filter_type != 0:
                raise ContractError("visual_evidence_invalid", f"unsupported PNG filter: {filter_type}")
        previous = row
        rows.append(bytes(row))
    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            index = x * channels
            if color_type == 0:
                gray = row[index]
                pixels.append((gray, gray, gray, 255))
            elif color_type == 2:
                pixels.append((row[index], row[index + 1], row[index + 2], 255))
            elif color_type == 3:
                palette_index = row[index]
                red, green, blue = palette[palette_index]
                alpha = transparency[palette_index] if palette_index < len(transparency) else 255
                pixels.append((red, green, blue, alpha))
            elif color_type == 4:
                gray, alpha = row[index], row[index + 1]
                pixels.append((gray, gray, gray, alpha))
            else:
                pixels.append((row[index], row[index + 1], row[index + 2], row[index + 3]))
    return width, height, pixels


def image_comparison(
    reference: Path, actual: Path
) -> tuple[int, int, float, dict[str, int] | None]:
    ref_width, ref_height, ref_pixels = read_png_rgba(reference)
    actual_width, actual_height, actual_pixels = read_png_rgba(actual)
    if (ref_width, ref_height) != (actual_width, actual_height):
        raise ContractError(
            "visual_size_mismatch",
            f"actual screenshot {actual_width}x{actual_height} differs from reference {ref_width}x{ref_height}",
        )
    total = 0
    left = top = None
    right = bottom = None
    for index, (reference_pixel, actual_pixel) in enumerate(
        zip(ref_pixels, actual_pixels, strict=True)
    ):
        total += sum(
            abs(reference_pixel[channel] - actual_pixel[channel])
            for channel in range(3)
        )
        if reference_pixel[:3] == actual_pixel[:3]:
            continue
        x = index % ref_width
        y = index // ref_width
        left = x if left is None else min(left, x)
        top = y if top is None else min(top, y)
        right = x + 1 if right is None else max(right, x + 1)
        bottom = y + 1 if bottom is None else max(bottom, y + 1)
    bbox = (
        None
        if left is None
        else {"left": left, "top": top, "right": right, "bottom": bottom}
    )
    return ref_width, ref_height, total / (len(ref_pixels) * 3), bbox


def image_mae(reference: Path, actual: Path) -> tuple[int, int, float]:
    width, height, mae, _bbox = image_comparison(reference, actual)
    return width, height, mae


def validate_color_pixel_evidence(
    reference_screenshot: Path,
    screenshot: Path,
    assertions: list[dict[str, Any]],
    measurements: dict[str, Any],
    logical_scale: object,
) -> list[dict[str, Any]]:
    """Bind opaque colors to the reference footprint and production screenshot."""

    try:
        scale = Fraction(logical_scale)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ContractError(
            "reference_viewport_measurement_failed",
            "captured production pixel scale is invalid",
        ) from exc
    if scale <= 0:
        raise ContractError(
            "reference_viewport_measurement_failed",
            "captured production pixel scale is invalid",
        )
    reference_width, reference_height, reference_pixels = read_png_rgba(
        reference_screenshot
    )
    width, height, pixels = read_png_rgba(screenshot)
    if (reference_width, reference_height) != (width, height):
        raise ContractError(
            "reference_viewport_measurement_failed",
            "reference and production color evidence sizes differ",
        )
    measured = require_list(
        measurements.get("measurements"), "reference viewport measurements"
    )
    by_probe_and_kind = {
        (item.get("probe_tag"), item.get("kind")): item.get("actual")
        for value in measured
        for item in [require_dict(value, "reference viewport measurement")]
    }
    assertions_by_probe_and_kind = {
        (item.get("probe_tag"), item.get("kind")): item for item in assertions
    }

    def pixel_bounds(
        bounds: dict[str, Any], assertion_id: str
    ) -> tuple[int, int, int, int]:
        try:
            left = max(0, math.floor(float(Fraction(str(bounds["left"])) * scale)))
            top = max(0, math.floor(float(Fraction(str(bounds["top"])) * scale)))
            right = min(
                width,
                math.ceil(
                    float(
                        (Fraction(str(bounds["left"])) + Fraction(str(bounds["width"])))
                        * scale
                    )
                ),
            )
            bottom = min(
                height,
                math.ceil(
                    float(
                        (Fraction(str(bounds["top"])) + Fraction(str(bounds["height"])))
                        * scale
                    )
                ),
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ContractError(
                "reference_viewport_measurement_failed",
                f"color pixel bounds are invalid: {assertion_id}",
            ) from exc
        if right <= left or bottom <= top:
            raise ContractError(
                "reference_viewport_measurement_failed",
                f"color pixel bounds are empty: {assertion_id}",
            )
        return left, top, right, bottom

    def matching_pixels(
        image_pixels: list[tuple[int, int, int, int]],
        region: tuple[int, int, int, int],
        target: tuple[int, int, int],
    ) -> list[tuple[int, int, tuple[int, int, int, int]]]:
        left, top, right, bottom = region
        return [
            (x, y, image_pixels[y * width + x])
            for y in range(top, bottom)
            for x in range(left, right)
            if image_pixels[y * width + x][3] >= 250
            and max(
                abs(image_pixels[y * width + x][index] - target[index])
                for index in range(3)
            )
            <= 8
        ]

    observations: list[dict[str, Any]] = []
    for assertion in assertions:
        if assertion.get("kind") != "color":
            continue
        expected = assertion.get("expected")
        if not isinstance(expected, dict) or expected.get("a") != 255:
            continue
        probe_tag = assertion["probe_tag"]
        bounds = by_probe_and_kind.get((probe_tag, "bounds"))
        if (
            not isinstance(bounds, dict)
            or set(bounds) != {"left", "top", "width", "height"}
        ):
            raise ContractError(
                "reference_viewport_measurement_failed",
                f"color has no hierarchy-bound pixel region: {assertion['assertion_id']}",
            )
        bounds_assertion = assertions_by_probe_and_kind.get((probe_tag, "bounds"))
        reference_bounds = (
            bounds_assertion.get("expected")
            if isinstance(bounds_assertion, dict)
            else None
        )
        if (
            not isinstance(reference_bounds, dict)
            or set(reference_bounds) != {"left", "top", "width", "height"}
        ):
            raise ContractError(
                "reference_viewport_measurement_failed",
                f"color has no frozen reference region: {assertion['assertion_id']}",
            )
        target = tuple(expected[channel] for channel in ("r", "g", "b"))
        reference_matches = matching_pixels(
            reference_pixels,
            pixel_bounds(reference_bounds, assertion["assertion_id"]),
            target,
        )
        actual_matches = matching_pixels(
            pixels,
            pixel_bounds(bounds, assertion["assertion_id"]),
            target,
        )
        if not reference_matches:
            raise ContractError(
                "reference_viewport_measurement_failed",
                "claimed color is absent from its frozen reference region: "
                + assertion["assertion_id"],
            )
        if not actual_matches:
            raise ContractError(
                "reference_viewport_measurement_failed",
                "claimed color is absent from captured production pixels: "
                + assertion["assertion_id"],
            )
        exact_footprint = (
            isinstance(bounds_assertion, dict)
            and bounds_assertion.get("mode") == "exact_at_reference"
        )
        if exact_footprint and len(actual_matches) < len(reference_matches):
            raise ContractError(
                "reference_viewport_measurement_failed",
                "captured production pixels do not cover the frozen reference color footprint: "
                + assertion["assertion_id"],
                details={
                    "reference_pixel_count": len(reference_matches),
                    "actual_pixel_count": len(actual_matches),
                },
            )
        x, y, pixel = actual_matches[0]
        observations.append(
            {
                "assertion_id": assertion["assertion_id"],
                "probe_tag": probe_tag,
                "source": "captured_production_pixels",
                "pixel": {
                    "x": x,
                    "y": y,
                    "r": pixel[0],
                    "g": pixel[1],
                    "b": pixel[2],
                    "a": pixel[3],
                },
                "reference_pixel_count": len(reference_matches),
                "actual_pixel_count": len(actual_matches),
            }
        )
    return observations


def write_png_rgba(
    path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]
) -> None:
    if len(pixels) != width * height:
        raise ContractError("visual_capture_failed", "PNG pixel count is invalid")

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray([0])
        for pixel in pixels[y * width : (y + 1) * width]:
            row.extend(pixel)
        rows.append(bytes(row))
    body = b"\x89PNG\r\n\x1a\n"
    body += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    body += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    body += chunk(b"IEND", b"")
    atomic_write(path, body)


def resize_png(reference_size: tuple[int, int], source: Path, target: Path) -> tuple[int, int]:
    source_width, source_height, source_pixels = read_png_rgba(source)
    target_width, target_height = reference_size
    if (source_width, source_height) == reference_size:
        atomic_write(target, source.read_bytes())
        return source_width, source_height
    resized: list[tuple[int, int, int, int]] = []
    for y in range(target_height):
        source_y = (y + 0.5) * source_height / target_height - 0.5
        y0 = max(0, min(source_height - 1, math.floor(source_y)))
        y1 = max(0, min(source_height - 1, y0 + 1))
        y_weight = max(0.0, min(1.0, source_y - y0))
        for x in range(target_width):
            source_x = (x + 0.5) * source_width / target_width - 0.5
            x0 = max(0, min(source_width - 1, math.floor(source_x)))
            x1 = max(0, min(source_width - 1, x0 + 1))
            x_weight = max(0.0, min(1.0, source_x - x0))
            values = []
            for channel in range(4):
                top = (
                    source_pixels[y0 * source_width + x0][channel] * (1 - x_weight)
                    + source_pixels[y0 * source_width + x1][channel] * x_weight
                )
                bottom = (
                    source_pixels[y1 * source_width + x0][channel] * (1 - x_weight)
                    + source_pixels[y1 * source_width + x1][channel] * x_weight
                )
                values.append(round(top * (1 - y_weight) + bottom * y_weight))
            resized.append(tuple(values))
    write_png_rgba(target, target_width, target_height, resized)
    return source_width, source_height


def validate_device_configuration(value: object, label: str) -> dict[str, Any]:
    config = require_dict(value, label)
    require_exact_keys(
        config,
        {
            "size",
            "size_override",
            "density",
            "density_override",
            "locale",
            "font_scale",
            "navigation_mode",
        },
        label,
    )
    size = require_dict(config.get("size"), f"{label}.size")
    require_exact_keys(size, {"width", "height"}, f"{label}.size")
    if (
        type(size.get("width")) is not int
        or type(size.get("height")) is not int
        or size["width"] <= 0
        or size["height"] <= 0
        or type(config.get("density")) is not int
        or config["density"] <= 0
        or type(config.get("size_override")) is not bool
        or type(config.get("density_override")) is not bool
    ):
        raise ContractError("visual_capture_failed", f"{label} geometry is invalid")
    for field in ("locale", "font_scale", "navigation_mode"):
        require_string(config.get(field), f"{label}.{field}")
    return config.copy()


def frozen_device_baseline(
    stage_dir: Path,
    state: dict[str, Any],
    baseline_key: str,
    baseline_path: Path,
    observed: dict[str, Any],
) -> dict[str, Any]:
    baselines = state.setdefault("device_baselines", {})
    if not isinstance(baselines, dict):
        raise ContractError("stage_drift", "device baseline registry changed")
    if baseline_path.is_file():
        expected_sha = baselines.get(baseline_key)
        if not isinstance(expected_sha, str) or file_sha(baseline_path) != expected_sha:
            raise ContractError("stage_drift", "frozen device baseline changed")
        frozen = validate_device_configuration(
            read_json(baseline_path), "frozen device baseline"
        )
        current = validate_device_configuration(
            observed, "observed device baseline"
        )
        if current != frozen:
            raise ContractError(
                "visual_baseline_drift",
                "device configuration drifted from the first frozen baseline",
                details={"frozen": frozen, "observed": current},
            )
        return frozen
    atomic_write_json(baseline_path, observed)
    baselines[baseline_key] = file_sha(baseline_path)
    atomic_write_json(stage_dir / "state.json", state)
    return observed


def run_driver(
    driver: str,
    operation: str,
    package_name: str,
    *,
    device_serial: str | None = None,
    **paths: Path,
) -> subprocess.CompletedProcess[str]:
    command = [driver, operation, "--package", package_name]
    if device_serial is not None:
        command.extend(["--serial", device_serial])
    for field, path in paths.items():
        command.extend(["--" + field.replace("_", "-"), str(path)])
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            "visual_capture_failed", f"cannot run visual driver {operation}: {exc}"
        ) from exc


def require_trusted_android_driver(value: object) -> str:
    driver = Path(require_string(value, "visual driver")).resolve()
    if driver != ANDROID_VISUAL_DRIVER.resolve():
        raise ContractError(
            "untrusted_runtime_driver",
            "runtime evidence must be produced by ICP's Android driver",
        )
    return str(driver)


def complete_code_coverage_preflight(
    project_root: Path,
    stage_dir: Path,
    state: dict[str, Any],
    universe: dict[str, Any],
    plan: dict[str, Any],
    page_key: str,
) -> dict[str, Any]:
    manifest = verify_code_coverage(project_root, plan, universe, page_key)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id=f"implementation.code-coverage:{page_key}",
        evidence_sha256=digest(manifest),
    )
    return manifest


def validate_cold_start_evidence(value: object) -> dict[str, Any]:
    evidence = require_dict(value, "Android cold-start evidence")
    require_exact_keys(
        evidence,
        {
            "activity_resumed",
            "process_alive",
            "no_fatal_exception",
            "fatal_log_tail",
        },
        "Android cold-start evidence",
    )
    if not isinstance(evidence.get("fatal_log_tail"), str):
        raise ContractError(
            "android_cold_start_failed", "Android cold-start fatal log is invalid"
        )
    failed_checks = [
        field
        for field in (
            "activity_resumed",
            "process_alive",
            "no_fatal_exception",
        )
        if evidence.get(field) is not True
    ]
    if failed_checks:
        raise ContractError(
            "android_cold_start_failed",
            "Android cold start did not keep the production application alive",
            details={
                "failed_checks": failed_checks,
                "fatal_log_tail": evidence.get("fatal_log_tail"),
            },
        )
    return evidence.copy()


def driver_json(result: subprocess.CompletedProcess[str], operation: str) -> object:
    if result.returncode != 0:
        raise ContractError(
            "visual_capture_failed",
            f"visual driver {operation} failed: " + result.stderr[-2000:],
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(
            "visual_capture_failed",
            f"visual driver {operation} returned invalid JSON",
        ) from exc


def validate_interaction_evidence(
    value: object, expected_steps: list[dict[str, str]]
) -> dict[str, Any]:
    evidence = require_dict(value, "visual interaction evidence")
    require_exact_keys(
        evidence,
        {
            "schema",
            "steps",
            "initial_state_absent",
            "terminal_state_present",
        },
        "visual interaction evidence",
    )
    steps = require_list(evidence.get("steps"), "visual interaction steps")
    if (
        evidence.get("schema") != "icp.visual-interaction.v1"
        or steps != expected_steps
        or evidence.get("initial_state_absent") is not bool(expected_steps)
        or evidence.get("terminal_state_present") is not True
    ):
        raise ContractError(
            "visual_production_path_unproven",
            "visual driver did not execute the frozen production interaction trace",
        )
    return evidence.copy()


def validate_production_state_evidence(
    value: object, expected_visual_state_id: str, expected_root_tag: str
) -> dict[str, Any]:
    evidence = require_dict(value, "production visual-state evidence")
    require_exact_keys(
        evidence,
        {"visual_state_id", "root_tag", "state_attested", "root_attested"},
        "production visual-state evidence",
    )
    if (
        evidence.get("visual_state_id") != expected_visual_state_id
        or evidence.get("root_tag") != expected_root_tag
        or evidence.get("state_attested") is not True
        or evidence.get("root_attested") is not True
    ):
        raise ContractError(
            "visual_production_path_unproven",
            f"production renderer did not attest visual state {expected_visual_state_id}",
        )
    return evidence.copy()


def validate_measurement_evidence(
    value: object,
    expected_visual_state_id: str,
    expected_root_tag: str,
    assertions: list[dict[str, Any]],
    logical_scale: object,
    expected_apk_sha256: str | None = None,
) -> dict[str, Any]:
    evidence = require_dict(value, "reference viewport measurements")
    require_exact_keys(
        evidence,
        {"schema", "visual_state_id", "root_tag", "measurements"},
        "reference viewport measurements",
    )
    if (
        evidence.get("schema") != "icp.visual-measurements.v1"
        or evidence.get("visual_state_id") != expected_visual_state_id
        or evidence.get("root_tag") != expected_root_tag
    ):
        raise ContractError(
            "reference_viewport_measurement_failed",
            "measurement evidence targets another renderer or visual state",
        )
    expected = {item["assertion_id"]: item for item in assertions}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(
        require_list(evidence.get("measurements"), "reference viewport measurements")
    ):
        label = f"reference viewport measurements[{index}]"
        measurement = require_dict(raw, label)
        assertion_id = require_string(
            measurement.get("assertion_id"), f"{label}.assertion_id"
        )
        assertion = expected.get(assertion_id)
        typography_from_apk = (
            assertion is not None
            and assertion.get("kind") in {"font_size", "line_height"}
            and expected_apk_sha256 is not None
        )
        require_exact_keys(
            measurement,
            {"assertion_id", "probe_tag", "kind", "actual"}
            | ({"source", "apk_sha256"} if typography_from_apk else set()),
            label,
        )
        actual = measurement.get("actual")
        color_payload_shape_valid = (
            assertion is not None
            and assertion.get("kind") == "color"
            and isinstance(assertion.get("expected"), dict)
            and assertion["expected"].get("a") == 255
            and isinstance(actual, dict)
            and set(actual) == {"r", "g", "b", "a"}
            and all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                and 0 <= float(value) <= 255
                for value in actual.values()
            )
        )
        if (
            assertion is None
            or assertion_id in seen
            or measurement.get("probe_tag") != assertion["probe_tag"]
            or measurement.get("kind") != assertion["kind"]
            or (
                typography_from_apk
                and (
                    measurement.get("source") != "clean_build_apk"
                    or measurement.get("apk_sha256") != expected_apk_sha256
                )
            )
            or (
                not color_payload_shape_valid
                and not evaluate_reference_assertion(assertion, actual, logical_scale)
            )
        ):
            raise ContractError(
                "reference_viewport_measurement_failed",
                f"reference viewport assertion failed: {assertion_id}",
                details={
                    "expected": assertion,
                    "actual": measurement,
                },
            )
        seen.add(assertion_id)
        normalized.append(measurement.copy())
    if seen != set(expected):
        raise ContractError(
            "reference_viewport_measurement_failed",
            "not every frozen source-fact assertion was measured",
            details={"missing_assertion_ids": sorted(set(expected) - seen)},
        )
    return {
        "schema": evidence["schema"],
        "visual_state_id": expected_visual_state_id,
        "root_tag": expected_root_tag,
        "measurements": normalized,
    }


def runtime_scroll_obligations(layout_contract: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = layout_contract["component_tree"]["nodes_by_instance_id"]
    obligations: list[dict[str, Any]] = []
    for assertion in layout_contract["responsive_assertions"]:
        if assertion.get("kind") != "scroll_reachability":
            continue
        container_id = assertion["container_instance_id"]
        required_ids: list[str] = []
        for instance_id in nodes:
            current_id: str | None = instance_id
            while current_id is not None:
                if current_id == container_id:
                    required_ids.append(instance_id)
                    break
                current = nodes.get(current_id)
                current_id = (
                    current.get("parent_instance_id")
                    if isinstance(current, dict)
                    else None
                )
        obligations.append(
            {
                "decision_id": assertion["decision_id"],
                "container_instance_id": container_id,
                "axis": assertion["axis"],
                "required_instance_ids": sorted(required_ids),
            }
        )
    return obligations


def capture_visual(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get(
        "implementation_plan_sha256"
    ):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    driver = require_trusted_android_driver(args.driver)
    design_name = args.design_name
    reference = next(
        (item for item in universe["visual_references"] if item["design_name"] == design_name),
        None,
    )
    capture_case = next(
        (item for item in plan["visual_capture_cases"] if item["design_name"] == design_name),
        None,
    )
    if reference is None or capture_case is None:
        raise ContractError("visual_capture_failed", f"unknown design state: {design_name}")
    reference_path = project_file(project_root, reference["path"], "visual reference")
    if file_sha(reference_path) != reference["sha256"]:
        raise ContractError("stage_drift", f"visual reference changed: {design_name}")
    complete_code_coverage_preflight(
        project_root, stage_dir, state, universe, plan, capture_case["page_key"]
    )
    visual_node_id = f"visual:{design_name}.capture"
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "ready",
        node_id=visual_node_id,
    )
    package_name = capture_case["package_name"]
    device_serial = getattr(args, "device_serial", None)

    def call_driver(operation: str, **paths: Path) -> subprocess.CompletedProcess[str]:
        return run_driver(
            driver,
            operation,
            package_name,
            device_serial=device_serial,
            **paths,
        )

    package_reset = validate_android_package_reset(
        driver_json(call_driver("reset-package"), "reset-package"),
        package_name,
    )
    runtime_installation = attest_android_runtime_installation(
        project_root,
        plan,
        capture_case["page_key"],
        device_serial=device_serial,
    )
    package_identity = validate_android_package_identity(
        driver_json(call_driver("package-identity"), "package-identity"),
        package_name,
    )
    execution_transaction = validate_android_execution_transaction(
        runtime_installation,
        package_identity,
        project_root,
        plan,
        capture_case["page_key"],
    )
    clean_apk_path, clean_apk_sha256 = clean_build_base_apk(
        execution_transaction, project_root
    )

    before_result = call_driver("snapshot")
    if before_result.returncode != 0:
        raise ContractError(
            "visual_capture_failed",
            "visual driver snapshot failed: " + before_result.stderr[-2000:],
        )
    try:
        before = validate_device_configuration(
            json.loads(before_result.stdout), "device configuration before capture"
        )
    except json.JSONDecodeError as exc:
        raise ContractError(
            "visual_capture_failed", "visual driver snapshot returned invalid JSON"
        ) from exc
    pixel_size = require_dict(reference.get("pixel_size"), "reference pixel size")
    require_exact_keys(pixel_size, {"width", "height"}, "reference pixel size")
    if any(
        type(pixel_size.get(field)) is not int or pixel_size[field] <= 0
        for field in ("width", "height")
    ):
        raise ContractError("visual_capture_failed", "reference pixel size is invalid")
    logical_scale = reference.get("logical_scale")
    logical_density = logical_scale_density(logical_scale)
    runtime_dir = stage_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stem = digest({"design_name": design_name})[:20]
    before_path = runtime_dir / f"{stem}.before.json"
    applied_path = runtime_dir / f"{stem}.applied.json"
    raw_path = runtime_dir / f"{stem}.raw.png"
    actual_path = runtime_dir / f"{stem}.png"
    evidence_path = runtime_dir / f"{stem}.capture.json"
    trace_path = runtime_dir / f"{stem}.interaction.json"
    measurement_contract_path = runtime_dir / f"{stem}.measurements.contract.json"
    layout_contract_path = runtime_dir / f"{stem}.layout.contract.json"
    before = frozen_device_baseline(
        stage_dir, state, f"visual:{stem}", before_path, before
    )
    applied = {
        "size": {"width": pixel_size["width"], "height": pixel_size["height"]},
        "size_override": True,
        "density": logical_density,
        "density_override": True,
        "locale": capture_case["locale"],
        "font_scale": before["font_scale"],
        "navigation_mode": before["navigation_mode"],
    }
    atomic_write_json(applied_path, applied)
    atomic_write_json(
        trace_path,
        {
            "schema": "icp.visual-interaction-trace.v1",
            "visual_state_id": capture_case["visual_state_id"],
            "steps": capture_case["interaction_trace"],
        },
    )
    assertions = [
        item
        for item in universe["reference_viewport_assertions"]
        if item["design_name"] == design_name
    ]
    atomic_write_json(
        measurement_contract_path,
        {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": capture_case["visual_state_id"],
            "root_tag": capture_case["production_render"]["root_tag"],
            "logical_scale": logical_scale,
            "assertions": assertions,
        },
    )
    layout_contract = next(
        item
        for item in plan["layout_contracts"]
        if item["design_state_id"] == design_name
    )
    atomic_write_json(
        layout_contract_path,
        {
            "schema": "icp.runtime-layout-contract",
            "design_state_id": design_name,
            "visual_state_id": capture_case["visual_state_id"],
            "root_tag": capture_case["production_render"]["root_tag"],
            "logical_scale": logical_scale,
            "require_device_window_insets": True,
            "component_instance_ids": list(
                layout_contract["component_tree"]["nodes_by_instance_id"]
            ),
            "occurrence_ids_by_instance_id": {
                instance_id: instance_id
                for instance_id in layout_contract["component_tree"][
                    "nodes_by_instance_id"
                ]
            },
            "scroll_obligations": runtime_scroll_obligations(layout_contract),
        },
    )
    failure: ContractError | None = None
    raw_size: tuple[int, int] | None = None
    restored: dict[str, Any] | None = None
    cold_start: dict[str, Any] | None = None
    interaction: dict[str, Any] | None = None
    production_state: dict[str, Any] | None = None
    measurements: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    restore_failure: ContractError | None = None
    try:
        applied_result = call_driver("apply", config=applied_path)
        if applied_result.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual driver apply failed: " + applied_result.stderr[-2000:],
            )
        applied_snapshot_result = call_driver("snapshot")
        if applied_snapshot_result.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual applied configuration snapshot failed: "
                + applied_snapshot_result.stderr[-2000:],
            )
        try:
            applied_snapshot = validate_device_configuration(
                json.loads(applied_snapshot_result.stdout),
                "device configuration after visual apply",
            )
        except (json.JSONDecodeError, ContractError) as exc:
            raise ContractError(
                "visual_capture_failed",
                "visual applied configuration snapshot is invalid",
            ) from exc
        if applied_snapshot != applied:
            raise ContractError(
                "visual_configuration_mismatch",
                "device did not apply the frozen reference configuration",
                details={"expected": applied, "actual": applied_snapshot},
            )
        for command in capture_case["precondition_commands"]:
            completed = subprocess.run(
                command,
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            if completed.returncode != 0:
                raise ContractError(
                    "visual_capture_failed",
                    "visual state setup failed: " + completed.stderr[-2000:],
                )
        postcondition_snapshot_result = call_driver("snapshot")
        if postcondition_snapshot_result.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual postcondition configuration snapshot failed: "
                + postcondition_snapshot_result.stderr[-2000:],
            )
        try:
            postcondition_snapshot = validate_device_configuration(
                json.loads(postcondition_snapshot_result.stdout),
                "device configuration after visual preconditions",
            )
        except (json.JSONDecodeError, ContractError) as exc:
            raise ContractError(
                "visual_capture_failed",
                "visual postcondition configuration snapshot is invalid",
            ) from exc
        if postcondition_snapshot != applied:
            raise ContractError(
                "visual_configuration_mismatch",
                "visual preconditions changed the frozen reference configuration",
                details={"expected": applied, "actual": postcondition_snapshot},
            )
        postcondition_package_identity = validate_android_package_identity(
            driver_json(call_driver("package-identity"), "package-identity"),
            package_name,
        )
        if postcondition_package_identity != package_identity:
            raise ContractError(
                "android_runtime_identity_changed",
                "visual preconditions replaced the AGP-tested production APK",
            )
        cold_start_result = call_driver("cold-start")
        try:
            cold_start = validate_cold_start_evidence(
                driver_json(cold_start_result, "cold-start")
            )
        except ContractError as exc:
            if exc.code == "visual_capture_failed":
                raise ContractError("android_cold_start_failed", exc.message) from exc
            raise
        interaction = validate_interaction_evidence(
            driver_json(
                call_driver("interact", trace=trace_path),
                "interact",
            ),
            capture_case["interaction_trace"],
        )
        validate_cold_start_evidence(
            driver_json(call_driver("health"), "health")
        )
        root_tag = capture_case["production_render"]["root_tag"]
        production_state = validate_production_state_evidence(
            driver_json(
                call_driver(
                    "attest",
                    state_id=capture_case["visual_state_id"],
                    root_tag=root_tag,
                ),
                "attest",
            ),
            capture_case["visual_state_id"],
            root_tag,
        )
        measurements = validate_measurement_evidence(
            driver_json(
                call_driver(
                    "measure",
                    contract=measurement_contract_path,
                    state_id=capture_case["visual_state_id"],
                    root_tag=root_tag,
                    apk=clean_apk_path,
                ),
                "measure",
            ),
            capture_case["visual_state_id"],
            root_tag,
            assertions,
            reference["logical_scale"],
            clean_apk_sha256,
        )
        captured = call_driver("capture", output=raw_path)
        if captured.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual driver capture failed: " + captured.stderr[-2000:],
            )
        raw_size = resize_png(
            (pixel_size["width"], pixel_size["height"]), raw_path, actual_path
        )
        validate_color_pixel_evidence(
            reference_path,
            actual_path,
            assertions,
            measurements,
            logical_scale,
        )
        layout = require_dict(
            driver_json(
                call_driver("read-layout", contract=layout_contract_path),
                "read-layout",
            ),
            "production reference layout",
        )
        if (
            layout.pop("visual_state_id", None) != capture_case["visual_state_id"]
            or layout.pop("root_tag", None) != root_tag
        ):
            raise ContractError(
                "reference_viewport_layout_failed",
                f"runtime layout targets another state: {design_name}",
            )
        checked_layout = verify_runtime_layout(layout_contract, layout, "reference")
        if checked_layout["status"] != "pass":
            raise ContractError(
                "reference_viewport_layout_failed",
                f"reference runtime layout failed: {design_name}",
                details={"problems": checked_layout["failures"]},
            )
    except ContractError as exc:
        failure = exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        failure = ContractError("visual_capture_failed", f"visual capture failed: {exc}")
    finally:
        restored_result = call_driver("restore", config=before_path)
        if restored_result.returncode == 0:
            snapshot_result = call_driver("snapshot")
            if snapshot_result.returncode == 0:
                try:
                    restored = validate_device_configuration(
                        json.loads(snapshot_result.stdout),
                        "device configuration after restore",
                    )
                except (json.JSONDecodeError, ContractError):
                    restored = None
        if restored != before:
            restore_failure = ContractError(
                "visual_restore_failed",
                "device size, density, locale, font scale, or navigation mode was not restored",
            )
    if failure is not None:
        if restore_failure is not None:
            failure.details = {
                **(failure.details or {}),
                "restore_error": restore_failure.message,
            }
        raise failure
    if restore_failure is not None:
        raise restore_failure
    if raw_size is None or not actual_path.is_file():
        raise ContractError("visual_capture_failed", "visual capture produced no screenshot")
    evidence = {
        "schema": "icp.implementation.visual-capture-evidence.v3",
        "evaluation_scope": "reference_viewport_visual_fidelity",
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "design_name": design_name,
        "reference_sha256": reference["sha256"],
        "logical_artboard_size": reference["logical_artboard_size"],
        "reference_pixel_size": pixel_size,
        "logical_scale": reference["logical_scale"],
        "capture_strategy": "extended-viewport-full-page",
        "visual_state_id": capture_case["visual_state_id"],
        "package_reset": package_reset,
        "runtime_installation": runtime_installation,
        "package_identity": package_identity,
        "cold_start": cold_start,
        "interaction": interaction,
        "production_state": production_state,
        "measurements": measurements,
        "layout": layout,
        "before": before,
        "applied": applied,
        "raw_pixel_size": list(raw_size),
        "actual_screenshot": str(actual_path.relative_to(project_root)),
        "actual_sha256": file_sha(actual_path),
        "restored": restored,
        "restore_exact": restored == before,
    }
    atomic_write_json(evidence_path, evidence)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id=visual_node_id,
        evidence_sha256=file_sha(evidence_path),
    )
    return {
        "ok": True,
        "stage": "implementation",
        "design_name": design_name,
        "actual_screenshot": str(actual_path.relative_to(project_root)),
        "capture_evidence": str(evidence_path.relative_to(project_root)),
    }


def capture_responsive(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get(
        "implementation_plan_sha256"
    ):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    driver = require_trusted_android_driver(args.driver)
    page_key = require_string(args.page_key, "responsive page key")
    if page_key not in universe["page_keys"]:
        raise ContractError(
            "responsive_evidence_invalid", f"unknown responsive page: {page_key}"
        )
    viewport = require_string(args.viewport, "responsive viewport")
    sizes = {"compact": (360, 800), "expanded": (840, 1200)}
    if viewport not in sizes:
        raise ContractError(
            "responsive_evidence_invalid", f"unknown responsive viewport: {viewport}"
        )
    node_id = f"responsive:{page_key}.{viewport}"
    complete_code_coverage_preflight(
        project_root, stage_dir, state, universe, plan, page_key
    )
    implementation_checklist_call(
        stage_dir, state, universe, "ready", node_id=node_id
    )
    contracts = [
        item for item in plan["layout_contracts"] if item["page_key"] == page_key
    ]
    captures = {item["design_name"]: item for item in plan["visual_capture_cases"]}
    if not contracts or any(item["design_state_id"] not in captures for item in contracts):
        raise ContractError(
            "responsive_evidence_invalid",
            f"responsive states have no production capture path: {page_key}",
        )
    device_serial = getattr(args, "device_serial", None)

    def call_driver(
        operation: str, package_name: str, **paths: Path
    ) -> subprocess.CompletedProcess[str]:
        return run_driver(
            driver,
            operation,
            package_name,
            device_serial=device_serial,
            **paths,
        )

    package_names = {
        captures[contract["design_state_id"]]["package_name"]
        for contract in contracts
    }
    if len(package_names) != 1:
        raise ContractError(
            "android_runtime_identity_unproven",
            f"one page targets multiple Android packages: {page_key}",
        )
    page_package_name = next(iter(package_names))
    package_reset = validate_android_package_reset(
        driver_json(
            call_driver("reset-package", page_package_name),
            "reset-package",
        ),
        page_package_name,
    )
    runtime_installation = attest_android_runtime_installation(
        project_root,
        plan,
        page_key,
        device_serial=device_serial,
    )
    package_identity = validate_android_package_identity(
        driver_json(
            call_driver("package-identity", page_package_name),
            "package-identity",
        ),
        page_package_name,
    )
    validate_android_execution_transaction(
        runtime_installation,
        package_identity,
        project_root,
        plan,
        page_key,
    )

    before_result = call_driver("snapshot", page_package_name)
    if before_result.returncode != 0:
        raise ContractError(
            "responsive_capture_failed",
            "responsive device snapshot failed: " + before_result.stderr[-2000:],
        )
    try:
        before = validate_device_configuration(
            json.loads(before_result.stdout), "device configuration before responsive capture"
        )
    except (json.JSONDecodeError, ContractError) as exc:
        raise ContractError(
            "responsive_capture_failed",
            "responsive device snapshot returned invalid data",
        ) from exc
    width, height = sizes[viewport]
    runtime_dir = stage_dir / "runtime" / "responsive"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    before_path = runtime_dir / f"{page_key}-{viewport}.before.json"
    before = frozen_device_baseline(
        stage_dir,
        state,
        f"responsive:{page_key}:{viewport}",
        before_path,
        before,
    )
    snapshots: list[dict[str, Any]] = []
    failure: ContractError | None = None
    restore_failure: ContractError | None = None
    try:
        for contract in contracts:
            design_state_id = contract["design_state_id"]
            capture_case = captures[design_state_id]
            package_name = capture_case["package_name"]
            applied = {
                "size": {"width": width, "height": height},
                "size_override": True,
                "density": 160,
                "density_override": True,
                "locale": capture_case["locale"],
                "font_scale": before["font_scale"],
                "navigation_mode": before["navigation_mode"],
            }
            stem = digest(
                {
                    "page_key": page_key,
                    "viewport": viewport,
                    "design_state_id": design_state_id,
                }
            )[:20]
            applied_path = runtime_dir / f"{stem}.applied.json"
            trace_path = runtime_dir / f"{stem}.interaction.json"
            contract_path = runtime_dir / f"{stem}.layout.contract.json"
            screenshot_path = runtime_dir / f"{stem}.png"
            atomic_write_json(applied_path, applied)
            atomic_write_json(
                trace_path,
                {
                    "schema": "icp.visual-interaction-trace.v1",
                    "visual_state_id": capture_case["visual_state_id"],
                    "steps": capture_case["interaction_trace"],
                },
            )
            atomic_write_json(
                contract_path,
                {
                    "schema": "icp.runtime-layout-contract",
                    "design_state_id": design_state_id,
                    "visual_state_id": capture_case["visual_state_id"],
                    "root_tag": capture_case["production_render"]["root_tag"],
                    "logical_scale": 1,
                    "require_device_window_insets": True,
                    "component_instance_ids": list(
                        contract["component_tree"]["nodes_by_instance_id"]
                    ),
                    "occurrence_ids_by_instance_id": {
                        instance_id: instance_id
                        for instance_id in contract["component_tree"][
                            "nodes_by_instance_id"
                        ]
                    },
                    "scroll_obligations": runtime_scroll_obligations(contract),
                },
            )
            applied_result = call_driver("apply", package_name, config=applied_path)
            if applied_result.returncode != 0:
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive device apply failed: " + applied_result.stderr[-2000:],
                )
            applied_snapshot_result = call_driver("snapshot", package_name)
            if applied_snapshot_result.returncode != 0:
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive applied configuration snapshot failed: "
                    + applied_snapshot_result.stderr[-2000:],
                )
            try:
                applied_snapshot = validate_device_configuration(
                    json.loads(applied_snapshot_result.stdout),
                    "device configuration after responsive apply",
                )
            except (json.JSONDecodeError, ContractError) as exc:
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive applied configuration snapshot is invalid",
                ) from exc
            if applied_snapshot != applied:
                raise ContractError(
                    "responsive_configuration_mismatch",
                    f"device did not apply the frozen {viewport} configuration",
                    details={"expected": applied, "actual": applied_snapshot},
                )
            for command in capture_case["precondition_commands"]:
                completed = subprocess.run(
                    command,
                    cwd=project_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1200,
                )
                if completed.returncode != 0:
                    raise ContractError(
                        "responsive_capture_failed",
                        "responsive state setup failed: " + completed.stderr[-2000:],
                    )
            postcondition_snapshot_result = call_driver("snapshot", package_name)
            if postcondition_snapshot_result.returncode != 0:
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive postcondition configuration snapshot failed: "
                    + postcondition_snapshot_result.stderr[-2000:],
                )
            try:
                postcondition_snapshot = validate_device_configuration(
                    json.loads(postcondition_snapshot_result.stdout),
                    "device configuration after responsive preconditions",
                )
            except (json.JSONDecodeError, ContractError) as exc:
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive postcondition configuration snapshot is invalid",
                ) from exc
            if postcondition_snapshot != applied:
                raise ContractError(
                    "responsive_configuration_mismatch",
                    "responsive preconditions changed the frozen device configuration",
                    details={"expected": applied, "actual": postcondition_snapshot},
                )
            postcondition_package_identity = validate_android_package_identity(
                driver_json(
                    call_driver("package-identity", package_name),
                    "package-identity",
                ),
                package_name,
            )
            if postcondition_package_identity != package_identity:
                raise ContractError(
                    "android_runtime_identity_changed",
                    "responsive preconditions replaced the AGP-tested production APK",
                )
            validate_cold_start_evidence(
                driver_json(
                    call_driver("cold-start", package_name), "cold-start"
                )
            )
            validate_interaction_evidence(
                driver_json(
                    call_driver("interact", package_name, trace=trace_path),
                    "interact",
                ),
                capture_case["interaction_trace"],
            )
            validate_cold_start_evidence(
                driver_json(call_driver("health", package_name), "health")
            )
            root_tag = capture_case["production_render"]["root_tag"]
            validate_production_state_evidence(
                driver_json(
                    call_driver(
                        "attest",
                        package_name,
                        state_id=capture_case["visual_state_id"],
                        root_tag=root_tag,
                    ),
                    "attest",
                ),
                capture_case["visual_state_id"],
                root_tag,
            )
            captured = call_driver("capture", package_name, output=screenshot_path)
            if captured.returncode != 0 or not screenshot_path.is_file():
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive screenshot failed: " + captured.stderr[-2000:],
                )
            screenshot_width, screenshot_height, _pixels = read_png_rgba(
                screenshot_path
            )
            if (screenshot_width, screenshot_height) != (width, height):
                raise ContractError(
                    "responsive_capture_failed",
                    "responsive screenshot size differs from the applied viewport",
                )
            layout = require_dict(
                driver_json(
                    call_driver(
                        "read-layout",
                        package_name,
                        contract=contract_path,
                    ),
                    "read-layout",
                ),
                "production responsive layout",
            )
            if (
                layout.pop("visual_state_id", None) != capture_case["visual_state_id"]
                or layout.pop("root_tag", None) != root_tag
            ):
                raise ContractError(
                    "responsive_capture_failed",
                    f"runtime layout targets another state: {design_state_id}",
                )
            snapshot = {
                "design_state_id": design_state_id,
                **layout,
                "capture": {
                    "screenshot_path": str(screenshot_path.relative_to(project_root)),
                    "sha256": file_sha(screenshot_path),
                    "device_configuration": {
                        "width": width,
                        "height": height,
                        "density": applied["density"],
                        "locale": applied["locale"],
                        "font_scale": applied["font_scale"],
                        "navigation_mode": applied["navigation_mode"],
                    },
                },
            }
            if verify_runtime_layout(contract, snapshot, "responsive")["status"] != "pass":
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"responsive runtime layout failed: {design_state_id}/{viewport}",
                )
            snapshots.append(snapshot)
    except ContractError as exc:
        failure = exc
    finally:
        package_name = captures[contracts[0]["design_state_id"]]["package_name"]
        restored_result = call_driver("restore", package_name, config=before_path)
        restored = None
        if restored_result.returncode == 0:
            snapshot_result = call_driver("snapshot", package_name)
            if snapshot_result.returncode == 0:
                try:
                    restored = validate_device_configuration(
                        json.loads(snapshot_result.stdout),
                        "device configuration after responsive restore",
                    )
                except (json.JSONDecodeError, ContractError):
                    restored = None
        if restored != before:
            restore_failure = ContractError(
                "visual_restore_failed",
                "device size, density, locale, font scale, or navigation mode was not restored",
            )
    if failure is not None:
        if restore_failure is not None:
            failure.details = {
                **(failure.details or {}),
                "restore_error": restore_failure.message,
            }
        raise failure
    if restore_failure is not None:
        raise restore_failure
    run = {
        "page_key": page_key,
        "viewport": viewport,
        "package_reset": package_reset,
        "runtime_installation": runtime_installation,
        "package_identity": package_identity,
        "snapshots": snapshots,
    }
    evidence_path = runtime_dir / f"{page_key}-{viewport}.capture.json"
    atomic_write_json(evidence_path, run)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id=node_id,
        evidence_sha256=digest(run),
    )
    return {
        "ok": True,
        "stage": "implementation",
        "page_key": page_key,
        "viewport": viewport,
        "responsive_evidence": str(evidence_path.relative_to(project_root)),
    }


def read_required_text(project_root: Path, relative: object, label: str) -> tuple[Path, str]:
    path = project_file(project_root, relative, label)
    try:
        return path, path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError("code_coverage_missing", f"cannot read {label}: {path}") from exc


def source_without_comments_or_literals(source: str) -> str:
    """Keep executable token positions while removing common source trivia."""

    result = list(source)
    index = 0
    length = len(source)
    while index < length:
        if source.startswith("<!--", index):
            end = source.find("-->", index + 4)
            end = length if end < 0 else end + 3
        elif source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
        else:
            delimiter = next(
                (
                    token
                    for token in ('"""', "'''", '"', "'", "`")
                    if source.startswith(token, index)
                ),
                None,
            )
            if delimiter is None:
                index += 1
                continue
            cursor = index + len(delimiter)
            while cursor < length:
                if source.startswith(delimiter, cursor):
                    cursor += len(delimiter)
                    break
                if len(delimiter) == 1 and source[cursor] == "\\":
                    cursor += 2
                else:
                    cursor += 1
            end = min(cursor, length)
        for position in range(index, end):
            if result[position] != "\n":
                result[position] = " "
        index = end
    return "".join(result)


def source_contains_executable_call(source: str, method_symbol: str) -> bool:
    executable = source_without_comments_or_literals(source)
    call_pattern = re.compile(
        rf"(?<![A-Za-z0-9_$]){re.escape(method_symbol)}\s*\("
    )
    declaration_keyword = re.compile(r"(?:\b(?:def|fun|func|function)\s*)$")
    typed_declaration = re.compile(
        r"^\s*"
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:(?:public|private|protected|internal|static|final|open|abstract|"
        r"override|suspend|async|external|native|mutating|nonmutating|inline|"
        r"operator|infix|tailrec|constexpr)\s+)*"
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\s*<[^;={}()]*>)?(?:\s*[?.\[\]])*\s+$"
    )
    control_prefixes = {"await", "new", "return", "throw", "yield"}
    for match in call_pattern.finditer(executable):
        line_start = executable.rfind("\n", 0, match.start()) + 1
        line_prefix = executable[line_start : match.start()]
        if declaration_keyword.search(line_prefix):
            continue
        if typed_declaration.fullmatch(line_prefix):
            prefix_token = line_prefix.strip().split()[-1]
            if prefix_token not in control_prefixes:
                continue
        return True
    return False


def source_call_bodies(source: str, symbol: str) -> list[str]:
    """Return balanced call bodies whose symbol occurs in executable source."""

    executable = source_without_comments_or_literals(source)
    pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(symbol)}\s*\(")
    bodies: list[str] = []
    for match in pattern.finditer(executable):
        opening = executable.find("(", match.start(), match.end())
        depth = 0
        for position in range(opening, len(executable)):
            token = executable[position]
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    bodies.append(source[opening + 1 : position])
                    break
    return bodies


def call_has_string_argument(body: str, name: str, expected: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9_$]){re.escape(name)}\s*=\s*{re.escape(json.dumps(expected))}(?![A-Za-z0-9_$])",
        body,
    ) is not None


def call_has_nullable_string_argument(
    body: str, name: str, expected: str | None
) -> bool:
    if expected is None:
        return re.search(
            rf"(?<![A-Za-z0-9_$]){re.escape(name)}\s*=\s*null(?![A-Za-z0-9_$])",
            body,
        ) is not None
    return call_has_string_argument(body, name, expected)


def call_has_resource_argument(body: str, name: str, resource: str | None) -> bool:
    expected = "null" if resource is None else "R.dimen." + resource
    return re.search(
        rf"(?<![A-Za-z0-9_$]){re.escape(name)}\s*=\s*{re.escape(expected)}(?![A-Za-z0-9_$])",
        body,
    ) is not None


def android_resource_reference(relative_path: str) -> str | None:
    parts = Path(relative_path).parts
    try:
        res_index = max(index for index, part in enumerate(parts) if part == "res")
    except ValueError:
        return None
    if res_index + 2 != len(parts) - 1:
        return None
    resource_type = parts[res_index + 1].split("-", 1)[0]
    resource_name = parts[res_index + 2].split(".", 1)[0]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", resource_type) or not re.fullmatch(
        r"[a-z][a-z0-9_]*", resource_name
    ):
        return None
    return f"R.{resource_type}.{resource_name}"


def call_has_tokens(body: str, tokens: list[str]) -> bool:
    return all(
        re.search(
            rf"(?<![A-Za-z0-9_$]){re.escape(token)}(?![A-Za-z0-9_$])",
            body,
        )
        is not None
        for token in tokens
    )


def verify_code_coverage(
    project_root: Path,
    plan: dict[str, Any],
    universe: dict[str, Any],
    page_key: str | None = None,
) -> dict[str, Any]:
    selected_page_keys = (
        set(universe["page_keys"]) if page_key is None else {page_key}
    )
    if not selected_page_keys.issubset(set(universe["page_keys"])):
        raise ContractError("code_coverage_missing", f"unknown page: {page_key}")
    selected_pages = [
        item for item in plan["pages"] if item["page_key"] in selected_page_keys
    ]
    selected_components = [
        item
        for item in plan["component_mappings"]
        if item["page_key"] in selected_page_keys
    ]
    selected_interactions = [
        item
        for item in plan["interaction_mappings"]
        if item["page_key"] in selected_page_keys
    ]
    selected_api_contracts = [
        item
        for item in plan["api_contract_mappings"]
        if item["page_key"] in selected_page_keys
    ]
    selected_runtime_entries = [
        item
        for item in plan["runtime_entries"]
        if item["page_key"] in selected_page_keys
    ]
    selected_obligation_ids = {
        item["obligation_id"]
        for item in universe["design_elements"]
        if item["page_key"] in selected_page_keys
    }
    selected_fact_ids = {
        item["fact_id"]
        for item in universe["semantic_facts"]
        if item["page_key"] in selected_page_keys
    }
    selected_usage_ids = {
        item["usage_id"]
        for item in universe["presentation_usages"]
        if item["source_page_key"] in selected_page_keys
    }
    texts: dict[str, tuple[Path, str]] = {}
    mock_bodies_by_page = {
        case["page_key"]: case["runtime_test"]["mock_expectation"]["body"]
        for case in plan["integration_test_cases"]
        if case["runtime_test"]["mock_expectation"] is not None
    }

    def text_for(relative: str, label: str) -> tuple[Path, str]:
        if relative not in texts:
            texts[relative] = read_required_text(project_root, relative, label)
        return texts[relative]

    provider = plan["runtime_probe_provider"]
    _, provider_source = text_for(
        provider["source_file"], "runtime probe provider"
    )
    if (
        provider["symbol"] not in provider_source
        or provider["publish_method_symbol"] not in provider_source
        or provider["output_path"] not in provider_source
    ):
        raise ContractError(
            "runtime_probe_provider_missing",
            "production code does not publish the frozen runtime probe payload",
        )

    for page in selected_pages:
        _, source = text_for(page["source_file"], f"page source {page['page_key']}")
        if page["root_symbol"] not in source:
            raise ContractError("code_coverage_missing", f"page root symbol is missing: {page['root_symbol']}")
        _, dto_source = text_for(page["dto_file"], f"page DTO {page['page_key']}")
        for symbol in (page["dto_symbol"], page["ui_state_symbol"]):
            if symbol not in dto_source:
                raise ContractError("code_coverage_missing", f"page data symbol is missing: {symbol}")
        if page["api_adapter_symbol"] is not None:
            _, adapter_source = text_for(
                page["api_adapter_file"], f"page API adapter {page['page_key']}"
            )
            if page["api_adapter_symbol"] not in adapter_source:
                raise ContractError(
                    "code_coverage_missing",
                    f"page API adapter symbol is missing: {page['api_adapter_symbol']}",
                )
        mock_path = project_file(project_root, page["mock_fixture_path"], "page mock fixture")
        try:
            mock_payload = json.loads(mock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError("code_coverage_missing", f"page mock fixture is invalid: {mock_path}") from exc
        if mock_payload != mock_bodies_by_page.get(page["page_key"]):
            raise ContractError(
                "mock_dto_runtime_unproven",
                "mock fixture differs from its runtime DTO input: " + page["page_key"],
            )
    for entry in selected_runtime_entries:
        _, source = text_for(
            entry["source_file"], f"runtime entry {entry['entry_id']}"
        )
        if entry["symbol"] not in source:
            raise ContractError(
                "code_coverage_missing",
                f"runtime entry symbol is missing: {entry['symbol']}",
            )
    for mapping in selected_components:
        _, source = text_for(mapping["source_file"], f"component {mapping['component_instance_id']}")
        if mapping["symbol"] not in source:
            raise ContractError("code_coverage_missing", f"component symbol is missing: {mapping['symbol']}")
    runtime_probe_call_sources = {
        page["source_file"] for page in selected_pages
    } | {
        entry["source_file"] for entry in selected_runtime_entries
    } | {
        mapping["source_file"] for mapping in selected_components
    }
    if not any(
        source_contains_executable_call(
            text_for(relative, "runtime probe publication owner")[1],
            provider["publish_method_symbol"],
        )
        for relative in runtime_probe_call_sources
    ):
        raise ContractError(
            "runtime_probe_provider_missing",
            "production renderer never calls the frozen runtime probe publisher",
        )
    for mapping in selected_interactions:
        _, source = text_for(
            mapping["source_file"], f"interaction {mapping['interaction_id']}"
        )
        if (
            mapping["symbol"] not in source
            or mapping["implementation_anchor"] not in source
        ):
            raise ContractError(
                "code_coverage_missing",
                f"interaction implementation is missing: {mapping['interaction_id']}",
            )
    for mapping in selected_api_contracts:
        _, source = text_for(
            mapping["source_file"], f"API contract {mapping['api_contract_id']}"
        )
        if any(
            token not in source
            for token in (
                mapping["adapter_symbol"],
                mapping["method_symbol"],
                mapping["implementation_anchor"],
            )
        ):
            raise ContractError(
                "code_coverage_missing",
                f"API adapter method is missing: {mapping['api_contract_id']}",
            )
    api_mapping_by_key = {
        (mapping["page_key"], mapping["api_contract_id"]): mapping
        for mapping in plan["api_contract_mappings"]
    }
    graph_interaction_by_key = {
        (graph["page_key"], interaction["interaction_id"]): interaction
        for graph in universe["interaction_graphs"]
        for interaction in graph["interactions"]
    }
    for mapping in plan["interaction_mappings"]:
        interaction = graph_interaction_by_key[
            (mapping["page_key"], mapping["interaction_id"])
        ]
        behavior = interaction.get("behavior")
        if behavior is None or behavior.get("kind") != "api_call":
            continue
        api_mapping = api_mapping_by_key[
            (mapping["page_key"], behavior["api_contract_id"])
        ]
        _, source = text_for(
            mapping["source_file"], f"API interaction {mapping['interaction_id']}"
        )
        if not source_contains_executable_call(source, api_mapping["method_symbol"]):
            raise ContractError(
                "api_interaction_not_implemented",
                "bound API adapter method is not called by interaction: "
                + mapping["interaction_id"],
            )
    for field in ("design_element_mappings", "semantic_fact_mappings", "presentation_mappings"):
        selected_mappings = (
            [
                item
                for item in plan[field]
                if item["obligation_id"] in selected_obligation_ids
            ]
            if field == "design_element_mappings"
            else [
                item
                for item in plan[field]
                if item["fact_id"] in selected_fact_ids
            ]
            if field == "semantic_fact_mappings"
            else [
                item
                for item in plan[field]
                if item["usage_id"] in selected_usage_ids
            ]
        )
        for mapping in selected_mappings:
            _, source = text_for(mapping["source_file"], f"{field} source")
            if mapping["implementation_anchor"] not in source or mapping["symbol"] not in source:
                raise ContractError(
                    "code_coverage_missing",
                    f"code anchor or owner symbol is missing: {mapping['implementation_anchor']}",
                )
            if field == "design_element_mappings":
                typography_resources = {
                    assertion["kind"]: assertion["apk_resource_name"]
                    for assertion in universe["reference_viewport_assertions"]
                    if assertion["obligation_id"] == mapping["obligation_id"]
                    and assertion["kind"] in {"font_size", "line_height"}
                }
                missing_resources = [
                    name
                    for name in typography_resources.values()
                    if "R.dimen." + name not in source
                ]
                if missing_resources:
                    raise ContractError(
                        "apk_typography_not_implemented",
                        "mapped production UI does not consume its frozen APK typography resources: "
                        + mapping["obligation_id"],
                        details={"missing_resources": missing_resources},
                    )
                element = next(
                    item
                    for item in universe["design_elements"]
                    if item["obligation_id"] == mapping["obligation_id"]
                )
                asset_resource_refs: list[str] = []
                for asset_mapping in mapping["asset_mappings"]:
                    reference = android_resource_reference(
                        asset_mapping["target_resource_path"]
                    )
                    if reference is None:
                        raise ContractError(
                            "asset_consumption_missing",
                            "target asset is not an addressable Android resource: "
                            + asset_mapping["target_resource_path"],
                        )
                    asset_resource_refs.append(reference)
                identity_bindings = [
                    body
                    for body in source_call_bodies(source, "IcpBoundElement")
                    if call_has_string_argument(
                        body, "obligationId", mapping["obligation_id"]
                    )
                    and call_has_string_argument(
                        body,
                        "componentInstanceId",
                        element["component_instance_id"],
                    )
                    and call_has_string_argument(
                        body, "ownerSymbol", mapping["symbol"]
                    )
                    and call_has_nullable_string_argument(
                        body, "probeTag", mapping["runtime_probe_tag"]
                    )
                    and call_has_resource_argument(
                        body,
                        "fontSizeRes",
                        typography_resources.get("font_size"),
                    )
                    and call_has_resource_argument(
                        body,
                        "lineHeightRes",
                        typography_resources.get("line_height"),
                    )
                ]
                matching_bindings = [
                    body
                    for body in identity_bindings
                    if call_has_tokens(body, asset_resource_refs)
                ]
                if len(matching_bindings) != 1:
                    message = (
                        "production element binding does not consume its mapped target assets: "
                        if asset_resource_refs and len(identity_bindings) == 1
                        else "mapped design element must have exactly one production element binding: "
                    )
                    raise ContractError(
                        "production_element_binding_missing",
                        message + mapping["obligation_id"],
                        details={
                            "component_instance_id": element[
                                "component_instance_id"
                            ],
                            "owner_symbol": mapping["symbol"],
                            "asset_resource_refs": asset_resource_refs,
                            "matching_bindings": len(matching_bindings),
                        },
                    )
    for capture_case in plan["visual_capture_cases"]:
        if capture_case["page_key"] not in selected_page_keys:
            continue
        production = capture_case["production_render"]
        production_path, source = text_for(
            production["source_file"],
            f"production visual renderer {capture_case['design_name']}",
        )
        if production["symbol"] not in source or production["root_tag"] not in source:
            raise ContractError(
                "visual_render_identity_mismatch",
                "visual capture is not wired to the frozen production renderer: "
                + capture_case["design_name"],
            )
        relative_parts = Path(production["source_file"]).parts
        search_root = project_root / relative_parts[0]
        source_suffixes = {
            ".kt",
            ".kts",
            ".java",
            ".swift",
            ".dart",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".py",
        }
        owners: list[str] = []
        if search_root.is_dir():
            for candidate in search_root.rglob("*"):
                relative_candidate = candidate.relative_to(project_root)
                parts_casefold = [part.casefold() for part in relative_candidate.parts]
                test_source = any(
                    part == "src"
                    and index + 1 < len(parts_casefold)
                    and parts_casefold[index + 1] in {"test", "tests", "androidtest"}
                    for index, part in enumerate(parts_casefold)
                )
                if (
                    not candidate.is_file()
                    or candidate.suffix not in source_suffixes
                    or any(
                        part in {"build", ".gradle", ".git", ".icp"}
                        for part in relative_candidate.parts
                    )
                    or test_source
                ):
                    continue
                try:
                    if production["root_tag"] in candidate.read_text(
                        encoding="utf-8"
                    ):
                        owners.append(str(relative_candidate))
                except (OSError, UnicodeError):
                    continue
        expected_owner = str(production_path.relative_to(project_root))
        if owners != [expected_owner]:
            raise ContractError(
                "visual_render_identity_mismatch",
                "production visual root tag must occur in exactly its frozen source file: "
                + capture_case["design_name"],
                details={"expected_owner": expected_owner, "actual_owners": owners},
            )
    design_elements = {
        item["obligation_id"]: item for item in universe["design_elements"]
    }
    asset_files: dict[str, Path] = {}
    for mapping in plan["design_element_mappings"]:
        if mapping["obligation_id"] not in selected_obligation_ids:
            continue
        source_assets = {
            asset["asset_id"]: asset
            for asset in design_elements[mapping["obligation_id"]]["assets"]
        }
        for asset_mapping in mapping["asset_mappings"]:
            source_asset = source_assets[asset_mapping["source_asset_id"]]
            source_path = project_file(
                project_root, source_asset["source_project_path"], "frozen source asset"
            )
            target_path = project_file(
                project_root,
                asset_mapping["target_resource_path"],
                "target resource asset",
            )
            if (
                not source_path.is_file()
                or file_sha(source_path) != source_asset["sha256"]
                or not target_path.is_file()
                or file_sha(target_path) != source_asset["sha256"]
            ):
                raise ContractError(
                    "asset_consumption_missing",
                    "source asset and target resource hashes differ: "
                    + asset_mapping["source_asset_id"],
                )
            asset_files[str(target_path.relative_to(project_root))] = target_path
    return {
        "schema": "icp.implementation.code-manifest.v1",
        "page_key": page_key,
        "files": [
            {
                "path": str(path.relative_to(project_root)),
                "sha256": file_sha(path),
            }
            for path, _ in sorted(texts.values(), key=lambda item: str(item[0]))
        ]
        + [
            {"path": relative, "sha256": file_sha(path)}
            for relative, path in sorted(asset_files.items())
        ],
    }


def run_verification_commands(project_root: Path, plan: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for kind in ("lint", "build", "integration"):
        for command in plan["verification_commands"][kind]:
            try:
                completed = subprocess.run(
                    command,
                    cwd=project_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ContractError("verification_command_failed", f"cannot run {kind}: {exc}") from exc
            result = {
                "kind": kind,
                "command": command,
                "exit_code": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
            results.append(result)
            if completed.returncode != 0:
                raise ContractError("verification_command_failed", f"{kind} command failed: {command}")
    return results


def validate_runtime_evidence(
    project_root: Path,
    value: object,
    state: dict[str, Any],
    universe: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = require_dict(value, "runtime evidence")
    require_exact_keys(
        evidence,
        {
            "schema",
            "implementation_plan_sha256",
            "responsive_runs",
            "visual_runs",
        },
        "runtime evidence",
    )
    if (
        evidence.get("schema") != "icp.implementation.runtime-evidence.v1"
        or evidence.get("implementation_plan_sha256") != state.get("implementation_plan_sha256")
    ):
        raise ContractError("invalid_evidence", "runtime evidence targets another implementation plan")

    responsive_runs = require_list(evidence.get("responsive_runs"), "responsive runs")
    expected_responsive = {
        (page_key, viewport)
        for page_key in universe["page_keys"]
        for viewport in ("compact", "expanded")
    }
    seen_responsive: set[tuple[str, str]] = set()
    resolved_responsive_runs: list[dict[str, Any]] = []
    captures = {
        item["design_name"]: item for item in plan["visual_capture_cases"]
    }
    layout_contracts_by_page: dict[str, dict[str, dict[str, Any]]] = {}
    for contract_value in require_list(plan.get("layout_contracts"), "layout contracts"):
        contract = require_dict(contract_value, "layout contract")
        layout_contracts_by_page.setdefault(contract["page_key"], {})[
            contract["design_state_id"]
        ] = contract
    for index, value in enumerate(responsive_runs):
        label = f"responsive_runs[{index}]"
        item = require_dict(value, label)
        try:
            require_exact_keys(
                item, {"page_key", "viewport", "capture_evidence"}, label
            )
        except ContractError as exc:
            raise ContractError(
                "responsive_evidence_invalid",
                f"{label} must reference capture-responsive evidence",
            ) from exc
        capture_path = project_file(
            project_root,
            item.get("capture_evidence"),
            f"{label}.capture_evidence",
        )
        try:
            captured_run = require_dict(
                read_json(capture_path), f"{label} captured responsive run"
            )
            require_exact_keys(
                captured_run,
                {
                    "page_key",
                    "viewport",
                    "package_reset",
                    "runtime_installation",
                    "package_identity",
                    "snapshots",
                },
                f"{label} captured responsive run",
            )
        except ContractError as exc:
            raise ContractError(
                "responsive_evidence_invalid",
                f"{label} capture-responsive evidence is invalid",
            ) from exc
        key = (item.get("page_key"), item.get("viewport"))
        if key != (captured_run.get("page_key"), captured_run.get("viewport")):
            raise ContractError(
                "responsive_evidence_invalid",
                f"{label} points to another responsive run",
            )
        item = captured_run
        resolved_responsive_runs.append(captured_run)
        if key not in expected_responsive or key in seen_responsive:
            raise ContractError("responsive_evidence_invalid", f"unexpected responsive run: {key}")
        seen_responsive.add(key)
        page_package_names = {
            captures[contract["design_state_id"]]["package_name"]
            for contract in layout_contracts_by_page.get(key[0], {}).values()
        }
        if len(page_package_names) != 1:
            raise ContractError(
                "android_runtime_identity_unproven",
                f"one page targets multiple Android packages: {key[0]}",
            )
        validate_android_package_reset(
            item.get("package_reset"), next(iter(page_package_names))
        )
        validate_android_execution_transaction(
            item.get("runtime_installation"),
            item.get("package_identity"),
            project_root,
            plan,
            key[0],
        )
        expected_size = (360, 800) if key[1] == "compact" else (840, 1200)
        contracts = layout_contracts_by_page.get(key[0], {})
        snapshots = require_list(item.get("snapshots"), f"{label}.snapshots")
        seen_design_states: set[str] = set()
        for snapshot_index, snapshot_value in enumerate(snapshots):
            snapshot_label = f"{label}.snapshots[{snapshot_index}]"
            snapshot = require_dict(snapshot_value, snapshot_label)
            try:
                require_exact_keys(
                    snapshot,
                    {
                        "design_state_id",
                        "coordinate_space",
                        "viewport_bounds",
                        "safe_insets",
                        "system_bars",
                        "scroll_metrics",
                        "driver_observations",
                        "components",
                        "capture",
                    },
                    snapshot_label,
                )
            except ContractError as exc:
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"{snapshot_label} must contain measurements, not authored pass/fail flags",
                ) from exc
            design_state_id = require_string(
                snapshot.get("design_state_id"), f"{snapshot_label}.design_state_id"
            )
            contract = contracts.get(design_state_id)
            if contract is None or design_state_id in seen_design_states:
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"unexpected responsive design state: {design_state_id}",
                )
            seen_design_states.add(design_state_id)
            viewport_bounds = require_dict(
                snapshot.get("viewport_bounds"), f"{snapshot_label}.viewport_bounds"
            )
            if viewport_bounds != {
                "left": 0,
                "top": 0,
                "width": expected_size[0],
                "height": expected_size[1],
            }:
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"responsive viewport measurement changed: {key}",
                )
            components = require_list(
                snapshot.get("components"), f"{snapshot_label}.components"
            )
            expected_instance_ids = set(
                contract["component_tree"]["nodes_by_instance_id"]
            )
            occurrence_ids: list[str] = []
            measured_ids: list[str] = []
            for component_index, component_value in enumerate(components):
                component = require_dict(
                    component_value,
                    f"{snapshot_label}.components[{component_index}]",
                )
                occurrence_id = require_string(
                    component.get("occurrence_id"), "runtime component occurrence ID"
                )
                instance_id = require_string(
                    component.get("instance_id"), "runtime component instance ID"
                )
                occurrence_ids.append(occurrence_id)
                measured_ids.append(instance_id)
            if (
                len(occurrence_ids) != len(set(occurrence_ids))
                or set(measured_ids) != expected_instance_ids
                or len(measured_ids) != len(expected_instance_ids)
            ):
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"runtime component occurrence coverage changed: {design_state_id}",
                )
            checked = verify_runtime_layout(contract, snapshot, "responsive")
            if checked["status"] != "pass":
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"responsive measurements failed: {design_state_id}/{key[1]}",
                    details={"problems": checked["failures"]},
                )
            capture = require_dict(snapshot.get("capture"), f"{snapshot_label}.capture")
            require_exact_keys(
                capture,
                {"screenshot_path", "sha256", "device_configuration"},
                f"{snapshot_label}.capture",
            )
            screenshot_path = project_root / require_relative_path(
                capture.get("screenshot_path"), f"{snapshot_label}.capture.screenshot_path"
            )
            if (
                not screenshot_path.is_file()
                or file_sha(screenshot_path) != capture.get("sha256")
            ):
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"responsive device capture is missing or changed: {design_state_id}",
                )
            configuration = require_dict(
                capture.get("device_configuration"),
                f"{snapshot_label}.capture.device_configuration",
            )
            require_exact_keys(
                configuration,
                {"width", "height", "density", "locale", "font_scale", "navigation_mode"},
                f"{snapshot_label}.capture.device_configuration",
            )
            if (
                configuration.get("width") != expected_size[0]
                or configuration.get("height") != expected_size[1]
                or type(configuration.get("density")) is not int
                or configuration["density"] <= 0
            ):
                raise ContractError(
                    "responsive_evidence_invalid",
                    f"responsive device geometry changed: {key}",
                )
            for field in ("locale", "font_scale", "navigation_mode"):
                require_string(
                    configuration.get(field),
                    f"{snapshot_label}.capture.device_configuration.{field}",
                )
        if seen_design_states != set(contracts):
            raise ContractError(
                "responsive_evidence_invalid",
                f"every page design state needs one responsive measurement: {key}",
            )
    if seen_responsive != expected_responsive:
        raise ContractError("responsive_evidence_invalid", "every page needs compact and expanded runtime evidence")

    references = {item["design_name"]: item for item in universe["visual_references"]}
    reference_layout_contracts = {
        item["design_state_id"]: item for item in plan["layout_contracts"]
    }
    visual_runs = require_list(evidence.get("visual_runs"), "visual runs")
    seen_designs: set[str] = set()
    results: list[dict[str, Any]] = []
    for index, value in enumerate(visual_runs):
        label = f"visual_runs[{index}]"
        item = require_dict(value, label)
        try:
            require_exact_keys(
                item,
                {
                    "design_name",
                    "actual_screenshot",
                    "capture_evidence",
                },
                label,
            )
        except ContractError as exc:
            raise ContractError(
                "visual_capture_evidence_missing",
                f"{label} must include deterministic capture evidence",
            ) from exc
        design_name = require_string(item.get("design_name"), f"{label}.design_name")
        reference = references.get(design_name)
        if reference is None or design_name in seen_designs:
            raise ContractError("visual_evidence_invalid", f"unexpected visual run: {design_name}")
        seen_designs.add(design_name)
        reference_path = project_file(project_root, reference["path"], "visual reference")
        if file_sha(reference_path) != reference["sha256"]:
            raise ContractError("stage_drift", f"visual reference changed: {design_name}")
        actual_path = project_file(project_root, item.get("actual_screenshot"), "actual screenshot")
        capture_path = project_file(
            project_root, item.get("capture_evidence"), "visual capture evidence"
        )
        capture_case = next(
            value
            for value in plan["visual_capture_cases"]
            if value["design_name"] == design_name
        )
        try:
            capture = require_dict(read_json(capture_path), "visual capture evidence")
            require_exact_keys(
                capture,
                {
                    "schema",
                    "evaluation_scope",
                    "implementation_plan_sha256",
                    "design_name",
                    "reference_sha256",
                    "logical_artboard_size",
                    "reference_pixel_size",
                    "logical_scale",
                    "capture_strategy",
                    "visual_state_id",
                    "package_reset",
                    "runtime_installation",
                    "package_identity",
                    "cold_start",
                    "interaction",
                    "production_state",
                    "measurements",
                    "layout",
                    "before",
                    "applied",
                    "raw_pixel_size",
                    "actual_screenshot",
                    "actual_sha256",
                    "restored",
                    "restore_exact",
                },
                "visual capture evidence",
            )
            before = validate_device_configuration(capture.get("before"), "capture before")
            validate_android_package_reset(
                capture.get("package_reset"), capture_case["package_name"]
            )
            execution_transaction = validate_android_execution_transaction(
                capture.get("runtime_installation"),
                capture.get("package_identity"),
                project_root,
                plan,
                capture_case["page_key"],
            )
            _, clean_apk_sha256 = clean_build_base_apk(
                execution_transaction, project_root
            )
            applied = validate_device_configuration(capture.get("applied"), "capture applied")
            restored = validate_device_configuration(
                capture.get("restored"), "capture restored"
            )
            cold_start = validate_cold_start_evidence(capture.get("cold_start"))
            interaction = validate_interaction_evidence(
                capture.get("interaction"), capture_case["interaction_trace"]
            )
            root_tag = capture_case["production_render"]["root_tag"]
            production_state = validate_production_state_evidence(
                capture.get("production_state"),
                capture_case["visual_state_id"],
                root_tag,
            )
            assertions = [
                assertion
                for assertion in universe["reference_viewport_assertions"]
                if assertion["design_name"] == design_name
            ]
            measurements = validate_measurement_evidence(
                capture.get("measurements"),
                capture_case["visual_state_id"],
                root_tag,
                assertions,
                reference["logical_scale"],
                clean_apk_sha256,
            )
            layout = require_dict(capture.get("layout"), "reference runtime layout")
            require_exact_keys(
                layout,
                {
                    "coordinate_space",
                    "viewport_bounds",
                    "safe_insets",
                    "system_bars",
                    "scroll_metrics",
                    "driver_observations",
                    "components",
                },
                "reference runtime layout",
            )
            layout_contract = reference_layout_contracts.get(design_name)
            if layout_contract is None:
                raise ContractError(
                    "reference_viewport_layout_failed",
                    f"missing frozen layout contract: {design_name}",
                )
            checked_layout = verify_runtime_layout(
                layout_contract, layout, "reference"
            )
            if checked_layout["status"] != "pass":
                raise ContractError(
                    "reference_viewport_layout_failed",
                    f"reference runtime layout failed: {design_name}",
                    details={"problems": checked_layout["failures"]},
                )
        except ContractError as exc:
            if exc.code in {
                "reference_viewport_measurement_failed",
                "reference_viewport_layout_failed",
            }:
                raise
            raise ContractError(
                "visual_capture_evidence_missing",
                f"visual capture evidence is invalid: {design_name}",
            ) from exc
        expected_applied = {
            "size": reference["pixel_size"],
            "size_override": True,
            "density": logical_scale_density(reference.get("logical_scale")),
            "density_override": True,
            "locale": capture_case["locale"],
            "font_scale": before["font_scale"],
            "navigation_mode": before["navigation_mode"],
        }
        if (
            capture.get("schema")
            != "icp.implementation.visual-capture-evidence.v3"
            or capture.get("evaluation_scope")
            != "reference_viewport_visual_fidelity"
            or capture.get("implementation_plan_sha256")
            != state.get("implementation_plan_sha256")
            or capture.get("design_name") != design_name
            or capture.get("reference_sha256") != reference["sha256"]
            or capture.get("logical_artboard_size")
            != reference["logical_artboard_size"]
            or capture.get("reference_pixel_size") != reference["pixel_size"]
            or capture.get("logical_scale") != reference["logical_scale"]
            or capture.get("capture_strategy") != "extended-viewport-full-page"
            or capture.get("visual_state_id") != capture_case["visual_state_id"]
            or interaction.get("steps") != capture_case["interaction_trace"]
            or production_state.get("root_tag")
            != capture_case["production_render"]["root_tag"]
            or applied != expected_applied
            or restored != before
            or capture.get("restore_exact") is not True
            or capture.get("actual_screenshot") != item.get("actual_screenshot")
            or not actual_path.is_file()
            or capture.get("actual_sha256") != file_sha(actual_path)
        ):
            raise ContractError(
                "visual_capture_evidence_missing",
                f"visual capture conversion or restoration is unproven: {design_name}",
            )
        width, height, mae, difference_bbox = image_comparison(
            reference_path, actual_path
        )
        color_pixel_observations = validate_color_pixel_evidence(
            reference_path,
            actual_path,
            assertions,
            measurements,
            reference["logical_scale"],
        )
        result = {
            "design_name": design_name,
            "evaluation_scope": "reference_viewport_visual_fidelity",
            "reference_path": reference["path"],
            "reference_sha256": reference["sha256"],
            "actual_screenshot": str(actual_path.relative_to(project_root)),
            "actual_sha256": file_sha(actual_path),
            "capture_evidence": str(capture_path.relative_to(project_root)),
            "capture_evidence_sha256": file_sha(capture_path),
            "width": width,
            "height": height,
            "mae": mae,
            "mae_role": "diagnostic_only",
            "color_pixel_observations": color_pixel_observations,
            "reference_checks": {
                "exact_total": len(
                    [item for item in assertions if item["mode"] == "exact_at_reference"]
                ),
                "exact_passed": len(
                    [item for item in assertions if item["mode"] == "exact_at_reference"]
                ),
                "adaptive_measured": len(
                    [item for item in assertions if item["mode"] == "adaptive_at_reference"]
                ),
                "by_kind": {
                    kind: len(
                        [
                            item
                            for item in measurements["measurements"]
                            if item["kind"] == kind
                        ]
                    )
                    for kind in ("bounds", "color", "font_size", "line_height")
                },
            },
            "status": "pass",
            "difference_bbox": difference_bbox,
        }
        results.append(result)
    if seen_designs != set(references):
        raise ContractError("visual_evidence_invalid", "every design state needs one visual run")
    resolved_evidence = evidence.copy()
    resolved_evidence["responsive_runs"] = resolved_responsive_runs
    return resolved_evidence, results


def write_visual_difference_artifacts(
    stage_dir: Path,
    state: dict[str, Any],
    universe: dict[str, Any],
    plan: dict[str, Any],
    visual_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapping_by_obligation = {
        item["obligation_id"]: item for item in plan["design_element_mappings"]
    }
    channel_by_obligation = {
        item["obligation_id"]: item
        for item in universe["design_element_evidence_channels"]
    }
    failures: list[dict[str, Any]] = []
    for result in visual_results:
        design_name = result["design_name"]
        failures.append(
            {
                **result,
                "blocks": [
                    item for item in universe["blocks"] if item["design_name"] == design_name
                ],
                "design_elements": [
                    {
                        **item,
                        "code_mapping": mapping_by_obligation[item["obligation_id"]],
                        "evidence_channel": channel_by_obligation[
                            item["obligation_id"]
                        ],
                    }
                    for item in universe["design_elements"]
                    if item["design_name"] == design_name
                ],
            }
        )
    report = {
        "schema": "icp.implementation.visual-difference-report.v1",
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "mae_role": "diagnostic_only",
        "diagnostics": failures,
    }
    report_path = stage_dir / "visual-difference-report.json"
    atomic_write_json(report_path, report)
    return failures


def verify_implementation(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get("implementation_plan_sha256"):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    evidence_path = stage_dir / "tdd-evidence.json"
    if not evidence_path.is_file() or file_sha(evidence_path) != state.get("tdd_evidence_sha256"):
        raise ContractError("stage_drift", "TDD evidence changed")
    tdd_evidence = require_dict(read_json(evidence_path), "TDD evidence")
    validate_tdd_evidence(
        project_root, plan, tdd_evidence, require_complete=True
    )
    if state.get("state") not in {"awaiting_verification", "complete"}:
        if plan["integration_test_cases"] or state.get("state") != "awaiting_implementation":
            raise ContractError("invalid_state", f"implementation state is {state.get('state')}")
    for page_key in universe["page_keys"]:
        page_manifest = verify_code_coverage(
            project_root, plan, universe, page_key
        )
        implementation_checklist_call(
            stage_dir,
            state,
            universe,
            "complete",
            node_id=f"implementation.code-coverage:{page_key}",
            evidence_sha256=digest(page_manifest),
        )
    code_manifest = verify_code_coverage(project_root, plan, universe)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id="implementation.code-coverage",
        evidence_sha256=digest(code_manifest),
    )
    runtime_evidence, visual_results = validate_runtime_evidence(
        project_root, read_json(Path(args.evidence)), state, universe, plan
    )
    for responsive_run in runtime_evidence["responsive_runs"]:
        require_recorded_checklist_evidence(
            stage_dir,
            state,
            universe,
            node_id=(
                f"responsive:{responsive_run['page_key']}."
                f"{responsive_run['viewport']}"
            ),
            evidence_sha256=digest(responsive_run),
        )
    visual_evidence_by_design = {
        item["design_name"]: item for item in runtime_evidence["visual_runs"]
    }
    for visual_result in visual_results:
        visual_run = visual_evidence_by_design[visual_result["design_name"]]
        capture_sha256 = file_sha(project_file(
            project_root,
            visual_run["capture_evidence"],
            "visual capture evidence",
        ))
        require_recorded_checklist_evidence(
            stage_dir,
            state,
            universe,
            node_id=f"visual:{visual_result['design_name']}.capture",
            evidence_sha256=capture_sha256,
        )
        implementation_checklist_call(
            stage_dir,
            state,
            universe,
            "complete",
            node_id=f"visual:{visual_result['design_name']}.verify",
            evidence_sha256=digest(
                {
                    "capture_sha256": capture_sha256,
                    "visual_result": visual_result,
                }
            ),
        )
    write_visual_difference_artifacts(
        stage_dir, state, universe, plan, visual_results
    )
    command_results = run_verification_commands(project_root, plan)
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id="verification.commands",
        evidence_sha256=digest(command_results),
    )
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "require-complete",
        exclude=("stage.verify",),
    )
    atomic_write_json(stage_dir / "implementation-manifest.json", code_manifest)
    atomic_write_json(stage_dir / "runtime-evidence.json", runtime_evidence)
    stage_result = {
        "schema": "icp.implementation.stage-result.v1",
        "status": "complete",
        "component_lock_sha256": state["component_lock_sha256"],
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "tdd_evidence_sha256": state["tdd_evidence_sha256"],
        "implementation_manifest_sha256": file_sha(stage_dir / "implementation-manifest.json"),
        "runtime_evidence_sha256": file_sha(stage_dir / "runtime-evidence.json"),
        "design_element_count": len(universe["design_elements"]),
        "semantic_fact_count": len(universe["semantic_facts"]),
        "integration_case_count": len(plan["integration_test_cases"]),
        "responsive_run_count": len(runtime_evidence["responsive_runs"]),
        "visual_results": visual_results,
        "verification_commands": command_results,
    }
    atomic_write_json(stage_dir / "stage-result.json", stage_result)
    state["implementation_manifest_sha256"] = stage_result["implementation_manifest_sha256"]
    state["runtime_evidence_sha256"] = stage_result["runtime_evidence_sha256"]
    state["stage_result_sha256"] = file_sha(stage_dir / "stage-result.json")
    implementation_checklist_call(
        stage_dir,
        state,
        universe,
        "complete",
        node_id="stage.verify",
        evidence_sha256=state["stage_result_sha256"],
    )
    implementation_checklist_call(
        stage_dir, state, universe, "require-complete"
    )
    state["checklist_sha256"] = file_sha(stage_dir / "checklist.json")
    state["state"] = "complete"
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": "complete",
        "design_element_count": stage_result["design_element_count"],
        "integration_case_count": stage_result["integration_case_count"],
        "visual_results": visual_results,
    }


def begin(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    platform = args.platform
    rules_path = PLATFORM_RULES.get(platform)
    if rules_path is None:
        raise ContractError("unsupported_platform", f"unsupported platform: {platform}")
    stage_dir = implementation_dir(project_root)
    if stage_dir.exists():
        state_path = stage_dir / "state.json"
        if state_path.is_file():
            _stage_dir, state, universe = load_live_stage(project_root)
            if state.get("platform") != platform:
                raise ContractError(
                    "input_drift", "implementation platform changed after begin"
                )
            return {
                "ok": True,
                "stage": "implementation",
                "state": state["state"],
                "resumed": True,
                "page_count": len(universe["page_keys"]),
                "design_element_count": len(universe["design_elements"]),
                "integration_count": len(universe["integration_obligations"]),
                "plan_input": str(stage_dir / "implementation-plan.input.json"),
            }
        for path in stage_dir.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    component_dir, lock, bindings = load_sealed_component_design(project_root)
    universe = build_coverage_universe(project_root, lock, bindings)
    rules = rules_path.read_bytes()
    platform_rules = rules.decode("utf-8")
    prompt_raw = IMPLEMENTATION_PROMPT.read_bytes()
    prompt = prompt_raw.decode("utf-8")
    common_rules_path = project_root / COMMON_RULES_PROJECT_PATH
    try:
        common_rules_raw = common_rules_path.read_bytes()
        common_rules = common_rules_raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(
            "common_rules_missing",
            f"project common rules must be readable UTF-8: {common_rules_path}",
        ) from exc
    if not common_rules.strip():
        raise ContractError("common_rules_missing", "project common-rules.md is empty")
    state = {
        "schema": "icp.implementation.state.v1",
        "state": "awaiting_plan",
        "platform": platform,
        "component_lock_sha256": file_sha(component_dir / "component-lock.json"),
        "block_component_bindings_sha256": file_sha(
            component_dir / "block-component-bindings.json"
        ),
        "coverage_universe_sha256": hashlib.sha256(json_bytes(universe)).hexdigest(),
        "platform_rules_sha256": hashlib.sha256(rules).hexdigest(),
        "common_rules_sha256": hashlib.sha256(common_rules_raw).hexdigest(),
        "implementation_prompt_sha256": hashlib.sha256(prompt_raw).hexdigest(),
    }
    atomic_write_json(stage_dir / "coverage-universe.json", universe)
    atomic_write(stage_dir / "platform-best-practices.md", rules)
    atomic_write(stage_dir / "common-rules.md", common_rules_raw)
    atomic_write(stage_dir / "implementation-prompt.md", prompt_raw)
    atomic_write_json(
        stage_dir / "implementation-plan.input.json",
        build_plan_input(
            state,
            universe,
            common_rules,
            platform_rules,
            prompt,
        ),
    )
    try:
        create_checklist(
            stage_dir / "checklist.json",
            stage="implementation",
            input_sha256=implementation_checklist_input(state, universe),
            nodes=implementation_checklist_specs(universe),
            initially_completed=["stage.begin"],
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "page_count": len(universe["page_keys"]),
        "design_element_count": len(universe["design_elements"]),
        "integration_count": len(universe["integration_obligations"]),
        "plan_input": str(stage_dir / "implementation-plan.input.json"),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    command = commands.add_parser("begin")
    command.add_argument("--project-root", required=True)
    command.add_argument("--platform", required=True)
    command.set_defaults(handler=begin)
    command = commands.add_parser("record-plan")
    command.add_argument("--project-root", required=True)
    command.add_argument("--plan", required=True)
    command.set_defaults(handler=record_plan)
    command = commands.add_parser("run-case")
    command.add_argument("--project-root", required=True)
    command.add_argument("--case-id", required=True)
    command.add_argument("--phase", choices=("red", "green"), required=True)
    command.add_argument("--device-serial")
    command.set_defaults(handler=run_case)
    command = commands.add_parser("capture-visual")
    command.add_argument("--project-root", required=True)
    command.add_argument("--design-name", required=True)
    command.add_argument("--driver", required=True)
    command.add_argument("--device-serial")
    command.set_defaults(handler=capture_visual)
    command = commands.add_parser("capture-responsive")
    command.add_argument("--project-root", required=True)
    command.add_argument("--page-key", required=True)
    command.add_argument("--viewport", choices=("compact", "expanded"), required=True)
    command.add_argument("--driver", required=True)
    command.add_argument("--device-serial")
    command.set_defaults(handler=capture_responsive)
    command = commands.add_parser("verify")
    command.add_argument("--project-root", required=True)
    command.add_argument("--evidence", required=True)
    command.set_defaults(handler=verify_implementation)
    for command_parser in commands.choices.values():
        command_parser.add_argument(
            "--lock-timeout-seconds",
            type=float,
            default=DEFAULT_LOCK_TIMEOUT_SECONDS,
            help="bounded wait for the stage write lock (default: 30)",
        )
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        with implementation_stage_lock(
            Path(args.project_root).resolve(), args.lock_timeout_seconds
        ):
            result = args.handler(args)
    except ContractError as exc:
        error = {"ok": False, "error": exc.code, "message": exc.message}
        if exc.details is not None:
            error["details"] = exc.details
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
