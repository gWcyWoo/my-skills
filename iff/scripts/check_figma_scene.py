#!/usr/bin/env python3
"""Validate that scene.json was compiled from the Figma layer tree."""

from __future__ import annotations

import argparse

from common import load_json


REQUIRED_NODE_FIELDS = (
    "id",
    "path",
    "parent",
    "type",
    "figmaType",
    "bbox",
    "z",
    "depth",
    "visible",
    "effectiveVisible",
    "children",
)


def has_image_source(node: dict) -> bool:
    image = node.get("image") or {}
    if isinstance(image, dict) and (image.get("imageUrl") or image.get("svgUrl")):
        return True
    if node.get("imageFills"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    errors: list[str] = []
    if scene.get("sourceSchema") != "lanhu_figma_json":
        errors.append("sourceSchema must be lanhu_figma_json")
    artboard = scene.get("artboard") or {}
    if not artboard.get("id") or not artboard.get("width") or not artboard.get("height"):
        errors.append("artboard id/width/height are required")
    nodes = scene.get("nodes") or []
    if not nodes:
        errors.append("nodes must not be empty")
    by_id = {}
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("node missing id")
            continue
        if node_id in by_id:
            errors.append(f"duplicate node id: {node_id}")
        by_id[node_id] = node
        for field in REQUIRED_NODE_FIELDS:
            if field not in node:
                errors.append(f"{node_id}: missing {field}")
        bbox = node.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] >= 0 and bbox[3] >= 0):
            errors.append(f"{node_id}: invalid bbox")
        if node.get("visible") is False and node.get("effectiveVisible") is not False:
            errors.append(f"{node_id}: hidden node cannot be effectiveVisible")
        if node.get("opacity") == 0 and node.get("effectiveVisible") is not False:
            errors.append(f"{node_id}: opacity=0 node cannot be effectiveVisible")
        if node.get("exportable") and not (node.get("asset") or has_image_source(node)):
            errors.append(f"{node_id}: exportable node missing asset/image source")
    for node in nodes:
        node_id = node.get("id")
        if node.get("type") == "textlayer" and node.get("text") is None:
            child_has_text = any((by_id.get(child_id) or {}).get("text") for child_id in node.get("children") or [])
            if not child_has_text:
                errors.append(f"{node_id}: textLayer missing text")
        parent = node.get("parent")
        if parent and parent not in by_id:
            errors.append(f"{node_id}: parent missing from scene: {parent}")
        for child_id in node.get("children") or []:
            if child_id not in by_id:
                errors.append(f"{node_id}: child missing from scene: {child_id}")
            elif by_id[child_id].get("parent") != node_id:
                errors.append(f"{node_id}: child parent mismatch: {child_id}")
    if artboard.get("id") and artboard["id"] not in by_id:
        errors.append("artboard node missing from nodes")
    if errors:
        raise SystemExit("ERROR: figma scene invalid:\n" + "\n".join(errors[:80]))
    print(f"ok figma scene nodes={len(nodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
