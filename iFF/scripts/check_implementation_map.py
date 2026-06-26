#!/usr/bin/env python3
"""Validate that implementation_map.json covers visible render-plan nodes."""

from __future__ import annotations

import argparse
from typing import Any

from common import load_json


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
COORDINATE_RENDER_MODES = {"absolute_positioned", "absolute_bbox", "render_plan_bbox", "coordinate_canvas"}


def mapped_node_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        node = value.get("node")
        if isinstance(node, str):
            found.add(node)
        for key in ("nodes", "nodeMap", "nodeMappings", "widgets", "regions"):
            if key in value:
                found.update(mapped_node_ids(value[key]))
        for child in value.values():
            if isinstance(child, (dict, list)):
                found.update(mapped_node_ids(child))
    elif isinstance(value, list):
        for item in value:
            found.update(mapped_node_ids(item))
    return found


def node_mapping_entries(value: Any) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    if isinstance(value, dict):
        node = value.get("node")
        if isinstance(node, str):
            found.setdefault(node, []).append(value)
        for child in value.values():
            if isinstance(child, (dict, list)):
                for child_node, entries in node_mapping_entries(child).items():
                    found.setdefault(child_node, []).extend(entries)
    elif isinstance(value, list):
        for item in value:
            for child_node, entries in node_mapping_entries(item).items():
                found.setdefault(child_node, []).extend(entries)
    return found


def has_coordinate_render_mode(entries: list[dict[str, Any]]) -> bool:
    for entry in entries:
        mode = entry.get("renderMode") or entry.get("positioning") or entry.get("layoutMode")
        bbox = entry.get("bbox")
        if mode in COORDINATE_RENDER_MODES and isinstance(bbox, list) and len(bbox) == 4:
            return True
    return False


def has_widget_and_implementation(entries: list[dict[str, Any]]) -> bool:
    for entry in entries:
        if (entry.get("widget") or entry.get("widgetType")) and entry.get("implementation"):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--implementation-map", required=True)
    parser.add_argument("--min-coverage", type=float, default=0.98)
    args = parser.parse_args()

    render_plan = load_json(args.render_plan)
    implementation_map = load_json(args.implementation_map)

    render_nodes = render_plan.get("nodes") or {}
    visible = {
        node_id
        for node_id, node in render_nodes.items()
        if node.get("required") is True or node.get("implementation") in VISIBLE_IMPLEMENTATIONS
    }
    mapped = mapped_node_ids(implementation_map)
    mapped_entries = node_mapping_entries(implementation_map)
    covered = visible & mapped
    coverage = (len(covered) / len(visible)) if visible else 1.0

    missing_images = [
        node_id
        for node_id, node in render_nodes.items()
        if node.get("implementation") in {"image_png", "image_webp", "image", "svg", "asset"} and node_id not in mapped
    ]
    missing_text = [
        node_id
        for node_id, node in render_nodes.items()
        if node.get("implementation") == "text" and node_id not in mapped
    ]

    errors: list[str] = []
    if coverage < args.min_coverage:
        errors.append(
            f"visible node coverage {coverage:.3f} below {args.min_coverage:.3f} "
            f"({len(covered)}/{len(visible)})"
        )
    if missing_images:
        errors.append(f"missing image node mappings: {', '.join(missing_images[:20])}")
    if missing_text:
        errors.append(f"missing text node mappings: {', '.join(missing_text[:20])}")
    missing_coordinate = [
        node_id for node_id in sorted(covered) if not has_coordinate_render_mode(mapped_entries.get(node_id, []))
    ]
    if missing_coordinate:
        errors.append(f"missing coordinate render mode for visible node mappings: {', '.join(missing_coordinate[:20])}")
    missing_details = [
        node_id for node_id in sorted(covered) if not has_widget_and_implementation(mapped_entries.get(node_id, []))
    ]
    if missing_details:
        errors.append(f"missing widget/implementation detail for visible node mappings: {', '.join(missing_details[:20])}")
    if errors:
        raise SystemExit("ERROR: invalid implementation map:\n" + "\n".join(f"- {e}" for e in errors))

    print(f"ok implementation map visible_node_coverage={coverage:.3f} nodes={len(covered)}/{len(visible)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
