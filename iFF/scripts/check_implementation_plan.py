#!/usr/bin/env python3
"""Validate the iFF worker planning artifact before tests or production code."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import load_json


REQUIRED_PLAN_KEYS = (
    "artifactInventory",
    "designAlignment",
    "projectAlignment",
    "fixtureAlignment",
    "traceAndRepair",
    "forbiddenShortcuts",
)

REQUIRED_ARTIFACTS = (
    "design_classification.json",
    "scene.json",
    "groups.json",
    "tokens.json",
    "assets_manifest.json",
    "layout_contract.json",
    "render_plan.json",
    "design_artifacts_report.json",
    "interaction_contract.json",
    "interaction_test_plan.json",
)


def has_artifact(inventory: Any, name: str) -> bool:
    if isinstance(inventory, dict):
        if name in inventory:
            return True
        return any(has_artifact(value, name) for value in inventory.values())
    if isinstance(inventory, list):
        return any(has_artifact(item, name) for item in inventory)
    if isinstance(inventory, str):
        return inventory == name or inventory.endswith("/" + name)
    return False


def unique_design_states(spec_dir: Path) -> list[str]:
    states: list[str] = []
    try:
        classification = load_json(spec_dir / "design_classification.json")
    except FileNotFoundError:
        classification = {}
    for state in classification.get("states") or []:
        value = str(state)
        if value not in states:
            states.append(value)

    try:
        groups = load_json(spec_dir / "groups.json").get("groups") or []
    except FileNotFoundError:
        groups = []
    for group in groups:
        if group.get("kind") != "loan_card":
            continue
        state = group.get("state")
        if state:
            value = str(state)
            if value not in states:
                states.append(value)
    return states


def planned_state_count(fixture_alignment: Any) -> int | None:
    if not isinstance(fixture_alignment, dict):
        return None
    for key in ("runtimeStateCount", "stateCount", "runtime_state_count", "statesCount"):
        value = fixture_alignment.get(key)
        if isinstance(value, int):
            return value
    for key in ("states", "runtimeStates", "runtime_states"):
        value = fixture_alignment.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def count_render_nodes(spec_dir: Path) -> dict[str, int]:
    try:
        render_plan = load_json(spec_dir / "render_plan.json")
    except FileNotFoundError:
        return {}
    nodes = render_plan.get("nodes") or {}
    counts = {
        "required": 0,
        "text": 0,
        "image": 0,
        "shape": 0,
        "covered": 0,
        "atomicAsset": 0,
    }
    for node in nodes.values():
        implementation = node.get("implementation")
        if node.get("required"):
            counts["required"] += 1
        if implementation == "text":
            counts["text"] += 1
        elif implementation in {"image_png", "image_webp", "image", "svg", "asset", "image_fill"}:
            counts["image"] += 1
        elif implementation in {"shape", "oval_shape", "gradient_shape", "vector_shape", "shape_container"}:
            counts["shape"] += 1
        elif implementation in {"covered_by_asset", "covered_by_text", "covered_by_shared_component"}:
            counts["covered"] += 1
        if implementation in {"image_png", "image_webp", "image", "svg", "asset"}:
            counts["atomicAsset"] += 1
    return counts


def int_field(value: Any, keys: tuple[str, ...]) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        found = value.get(key)
        if isinstance(found, int):
            return found
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", nargs="?", help="Path to implementation_plan.json")
    parser.add_argument("--plan", dest="plan_flag", help="Path to implementation_plan.json")
    parser.add_argument("--spec-dir", help="Spec dir containing design artifacts.")
    args = parser.parse_args()

    plan_path = Path(args.plan_flag or args.plan or "")
    if not plan_path:
        raise SystemExit("ERROR: missing implementation plan path")
    spec_dir = Path(args.spec_dir) if args.spec_dir else plan_path.parent
    plan = load_json(plan_path)

    errors: list[str] = []
    for key in REQUIRED_PLAN_KEYS:
        if key not in plan:
            errors.append(f"missing top-level key: {key}")

    # prefill_implementation_plan.py leaves "__MODEL__" placeholders for the judgment
    # fields; an unfilled placeholder means the model skipped its part of the plan.
    todo_count = plan_path.read_text(encoding="utf-8").count("__MODEL__")
    if todo_count:
        errors.append(f"{todo_count} unfilled __MODEL__ placeholder(s) — fill every modelFields entry first")

    inventory = plan.get("artifactInventory")
    for artifact in REQUIRED_ARTIFACTS:
        if not has_artifact(inventory, artifact):
            errors.append(f"artifactInventory missing {artifact}")

    design_states = unique_design_states(spec_dir)
    if design_states:
        count = planned_state_count(plan.get("fixtureAlignment"))
        if count is None:
            errors.append("fixtureAlignment missing runtime state count or states list")
        elif count < len(design_states):
            errors.append(
                f"fixtureAlignment has {count} runtime states but design has {len(design_states)} states"
            )

    project_alignment = plan.get("projectAlignment")
    if isinstance(project_alignment, dict):
        if "fanoutOwnedFiles" not in project_alignment and "fanoutOwnedPaths" not in project_alignment:
            errors.append("projectAlignment missing fanoutOwnedFiles/fanoutOwnedPaths")
        if "faninRequests" not in project_alignment:
            errors.append("projectAlignment missing faninRequests")

    trace_and_repair = plan.get("traceAndRepair")
    if not isinstance(trace_and_repair, dict):
        errors.append("traceAndRepair must be an object")
    else:
        repair_budget = (
            trace_and_repair.get("singleRepairBudget")
            or trace_and_repair.get("repairPassLimit")
            or trace_and_repair.get("maxRepairPasses")
        )
        if repair_budget != 1:
            errors.append("traceAndRepair must set singleRepairBudget/repairPassLimit/maxRepairPasses to 1")

    design_alignment = plan.get("designAlignment")
    if isinstance(design_alignment, dict):
        if "nodeCoveragePlan" not in design_alignment and "regionNodeCoverage" not in design_alignment:
            errors.append("designAlignment missing nodeCoveragePlan/regionNodeCoverage")
        if "coordinateRenderStrategy" not in design_alignment:
            errors.append("designAlignment missing coordinateRenderStrategy")
        try:
            scene = load_json(spec_dir / "scene.json")
        except FileNotFoundError:
            scene = {}
        if scene.get("sourceSchema") == "lanhu_figma_json":
            source_value = (
                design_alignment.get("sourceSchema")
                or design_alignment.get("sceneSourceSchema")
                or design_alignment.get("figmaSourceSchema")
            )
            if source_value != "lanhu_figma_json":
                errors.append("designAlignment must record scene sourceSchema=lanhu_figma_json")
        render_counts = count_render_nodes(spec_dir)
        if render_counts:
            required_count = int_field(design_alignment, ("requiredVisibleNodeCount", "visibleNodeCount"))
            if required_count is None:
                errors.append("designAlignment missing requiredVisibleNodeCount/visibleNodeCount")
            elif required_count < render_counts["required"]:
                errors.append(
                    "designAlignment visible node count below render_plan required nodes: "
                    f"{required_count} < {render_counts['required']}"
                )
            for label, keys in {
                "text": ("textNodeCount", "textRenderNodeCount"),
                "image": ("imageNodeCount", "imageRenderNodeCount", "assetNodeCount"),
                "shape": ("shapeNodeCount", "shapeRenderNodeCount"),
            }.items():
                value = int_field(design_alignment, keys)
                if value is None:
                    errors.append(f"designAlignment missing {label} render node count")
                elif value < render_counts[label]:
                    errors.append(f"designAlignment {label} count below render_plan: {value} < {render_counts[label]}")
            if "assetAtomicNodes" not in design_alignment and "atomicAssetNodes" not in design_alignment:
                errors.append("designAlignment missing assetAtomicNodes/atomicAssetNodes")
            if "coveredNodes" not in design_alignment and "coveredByAssetNodes" not in design_alignment:
                errors.append("designAlignment missing coveredNodes/coveredByAssetNodes")
            if "renderImplementationTypes" not in design_alignment:
                errors.append("designAlignment missing renderImplementationTypes")

    if errors:
        raise SystemExit("ERROR: invalid implementation plan:\n" + "\n".join(f"- {e}" for e in errors))
    print(f"ok implementation plan {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
