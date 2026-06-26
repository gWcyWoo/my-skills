#!/usr/bin/env python3
"""Validate cross-artifact consistency before implementation planning."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import bbox_of, dump_json, load_json, png_size


REQUIRED_FILES = (
    "raw.json",
    "reference.png",
    "design_classification.json",
    "scene.json",
    "groups.json",
    "tokens.json",
    "assets_manifest.json",
    "layout_contract.json",
    "render_plan.json",
)

DESIGN_TYPES = {"screen", "variant_board", "component_sheet", "flow_board"}
VISIBLE_IMPLEMENTATIONS = {
    "asset",
    "gradient_shape",
    "image",
    "image_fill",
    "image_png",
    "image_webp",
    "oval_shape",
    "shape",
    "shape_container",
    "svg",
    "text",
    "vector_shape",
}


def close(a: float, b: float, tolerance: float = 1.0) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def require_file(spec_dir: Path, name: str, errors: list[str]) -> Path:
    path = spec_dir / name
    if not path.is_file():
        errors.append(f"missing required artifact: {name}")
    return path


def raw_artboard_bbox(raw: dict[str, Any]) -> list[float] | None:
    figma = raw.get("figma_json") if isinstance(raw, dict) else None
    if not isinstance(figma, dict):
        return None
    artboard = figma.get("artboard")
    if not isinstance(artboard, dict):
        return None
    return bbox_of(artboard)


def node_ids_from_layout(layout: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(layout, dict):
        node = layout.get("designNode") or layout.get("node")
        if isinstance(node, str):
            found.add(node)
        for value in layout.values():
            found.update(node_ids_from_layout(value))
    elif isinstance(layout, list):
        for item in layout:
            found.update(node_ids_from_layout(item))
    return found


def mapped_widget_nodes(layout: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for component in layout.values():
        if not isinstance(component, dict):
            continue
        widgets = component.get("widgets") or {}
        if not isinstance(widgets, dict):
            continue
        for widget in widgets.values():
            if isinstance(widget, dict) and isinstance(widget.get("node"), str):
                found.add(widget["node"])
    return found


def inside_artboard(bbox: list[Any], width: float, height: float, tolerance: float = 2.0) -> bool:
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return False
    x, y, w, h = [float(value) for value in bbox]
    if w <= 0 or h <= 0:
        return False
    # Require the top-left origin to sit inside the artboard (this catches
    # un-normalized raw Figma coordinates such as the root artboard's
    # [-669, -27202, ...]). Allow the far edge to bleed off the artboard:
    # real designs place decorations/icons that the frame clips, and frame
    # bboxes can be padded/stale relative to their in-bounds children.
    return -tolerance <= x <= width + tolerance and -tolerance <= y <= height + tolerance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--out", help="Defaults to spec_dir/design_artifacts_report.json")
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir)
    errors: list[str] = []
    for name in REQUIRED_FILES:
        require_file(spec_dir, name, errors)
    if errors:
        raise SystemExit("ERROR: design artifact audit failed:\n" + "\n".join(f"- {e}" for e in errors))

    raw = load_json(spec_dir / "raw.json")
    classification = load_json(spec_dir / "design_classification.json")
    scene = load_json(spec_dir / "scene.json")
    groups_doc = load_json(spec_dir / "groups.json")
    assets = load_json(spec_dir / "assets_manifest.json")
    layout = load_json(spec_dir / "layout_contract.json")
    render_plan = load_json(spec_dir / "render_plan.json")

    reference_width, reference_height = png_size(spec_dir / "reference.png")
    raw_bbox = raw_artboard_bbox(raw)
    if raw_bbox is None:
        errors.append("raw.json missing figma_json.artboard bbox")
    elif not (close(raw_bbox[2], reference_width) and close(raw_bbox[3], reference_height)):
        errors.append(
            "reference.png size does not match raw artboard: "
            f"reference={reference_width}x{reference_height} raw={raw_bbox[2]}x{raw_bbox[3]}"
        )

    if scene.get("sourceSchema") != "lanhu_figma_json":
        errors.append("scene.sourceSchema must be lanhu_figma_json")
    scene_artboard = scene.get("artboard") or {}
    if not (close(scene_artboard.get("width", -1), reference_width) and close(scene_artboard.get("height", -1), reference_height)):
        errors.append(
            "scene artboard size does not match reference.png: "
            f"scene={scene_artboard.get('width')}x{scene_artboard.get('height')} "
            f"reference={reference_width}x{reference_height}"
        )

    classification_type = classification.get("type")
    if classification_type not in DESIGN_TYPES:
        errors.append(f"invalid design_classification.type: {classification_type}")
    classification_artboard = classification.get("artboard") or {}
    if not (
        close(classification_artboard.get("width", -1), reference_width)
        and close(classification_artboard.get("height", -1), reference_height)
    ):
        errors.append("design_classification artboard size does not match reference.png")

    nodes = scene.get("nodes") or []
    by_id = {node.get("id"): node for node in nodes if isinstance(node, dict) and node.get("id")}
    if scene_artboard.get("id") not in by_id:
        errors.append("scene.artboard.id missing from scene.nodes")

    groups = groups_doc.get("groups") or []
    if not groups:
        errors.append("groups.json has no groups")
    group_states = [group.get("state") for group in groups if isinstance(group, dict) and group.get("state")]
    states = classification.get("states") or []
    if classification_type == "variant_board":
        if not states:
            errors.append("variant_board classification must list states")
        if len(groups) < len(states):
            errors.append(f"variant_board has {len(states)} states but only {len(groups)} groups")
        if group_states and len(set(group_states)) < len(states):
            errors.append(f"variant_board group states {len(set(group_states))} below classified states {len(states)}")

    for group in groups:
        if not isinstance(group, dict):
            errors.append("groups.json contains non-object group")
            continue
        node_id = group.get("node")
        if node_id not in by_id:
            errors.append(f"group references missing scene node: {node_id}")
        if not inside_artboard(group.get("bbox"), reference_width, reference_height):
            errors.append(f"group bbox outside artboard: {node_id}")

    layout_node_ids = node_ids_from_layout(layout)
    missing_layout_nodes = sorted(node_id for node_id in layout_node_ids if node_id not in by_id)
    if missing_layout_nodes:
        errors.append("layout_contract references missing scene nodes: " + ", ".join(missing_layout_nodes[:20]))

    widget_nodes = mapped_widget_nodes(layout if isinstance(layout, dict) else {})
    render_nodes = render_plan.get("nodes") or {}
    if not isinstance(render_nodes, dict) or not render_nodes:
        errors.append("render_plan.nodes must be a non-empty object")
    missing_render_scene = sorted(node_id for node_id in render_nodes if node_id not in by_id)
    if missing_render_scene:
        errors.append("render_plan references missing scene nodes: " + ", ".join(missing_render_scene[:20]))

    required_render_nodes = {
        node_id
        for node_id, item in render_nodes.items()
        if isinstance(item, dict) and (item.get("required") is True or item.get("implementation") in VISIBLE_IMPLEMENTATIONS)
    }
    if not required_render_nodes:
        errors.append("render_plan has no required visible nodes")
    missing_widget_nodes = sorted(required_render_nodes - widget_nodes)
    if missing_widget_nodes:
        errors.append("required render nodes missing layout widget mapping: " + ", ".join(missing_widget_nodes[:20]))

    asset_keys = set(assets) if isinstance(assets, dict) else set()
    if isinstance(assets, dict):
        missing_asset_nodes = sorted(node_id for node_id in asset_keys if node_id not in by_id)
        if missing_asset_nodes:
            errors.append("assets_manifest references missing scene nodes: " + ", ".join(missing_asset_nodes[:20]))
    else:
        errors.append("assets_manifest.json must be an object keyed by scene node id")

    atomic_asset_nodes = {
        node_id
        for node_id, item in render_nodes.items()
        if isinstance(item, dict) and item.get("implementation") in {"image_png", "image_webp", "image", "svg", "asset"}
    }
    missing_asset_manifest = sorted(node_id for node_id in atomic_asset_nodes if node_id not in asset_keys)
    if missing_asset_manifest:
        errors.append("atomic render asset nodes missing assets_manifest entries: " + ", ".join(missing_asset_manifest[:20]))

    report = {
        "ok": not errors,
        "referenceSize": {"width": reference_width, "height": reference_height},
        "sceneNodeCount": len(nodes),
        "groupCount": len(groups),
        "classificationType": classification_type,
        "stateCount": len(states),
        "requiredRenderNodeCount": len(required_render_nodes),
        "layoutMappedNodeCount": len(widget_nodes),
        "assetCount": len(assets) if isinstance(assets, dict) else 0,
        "errors": errors,
    }
    out = Path(args.out) if args.out else spec_dir / "design_artifacts_report.json"
    dump_json(report, out)
    if errors:
        raise SystemExit("ERROR: design artifact audit failed:\n" + "\n".join(f"- {e}" for e in errors[:80]))
    print(
        "ok design artifacts "
        f"nodes={len(nodes)} groups={len(groups)} required_render_nodes={len(required_render_nodes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
