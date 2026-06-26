#!/usr/bin/env python3
"""Create layout contract from Figma hierarchy groups and scene nodes."""

from __future__ import annotations

import argparse
import re

from common import dump_json, load_json


def descendants(node_id: str, by_id: dict[str, dict], seen: set[str] | None = None) -> list[str]:
    seen = seen or set()
    result: list[str] = []
    for child_id in by_id.get(node_id, {}).get("children") or []:
        if child_id in seen:
            continue
        seen.add(child_id)
        result.append(child_id)
        result.extend(descendants(child_id, by_id, seen))
    return result


def role_key(node: dict) -> str:
    raw = node.get("name") or node.get("text") or node["id"]
    key = re.sub(r"[^a-zA-Z0-9]+", "_", str(raw)).strip("_")
    node_key = re.sub(r"[^a-zA-Z0-9]+", "_", str(node["id"])).strip("_")
    return f"{(key or 'node')[:42]}_{node_key[:18]}"[:64]


def widget_for(node: dict) -> str:
    node_type = str(node.get("type", "")).lower()
    name = f"{node.get('name', '')} {node.get('path', '')}".lower()
    if node.get("text") or node_type == "textlayer":
        return "Text"
    if node.get("asset") or node.get("exportable"):
        return "Image/SVG"
    if "button" in name or "btn" in name:
        return "ButtonHitArea"
    if "input" in name or "field" in name:
        return "InputHitArea"
    if node_type == "shapelayer":
        return "Shape"
    return "Stack/Container"


def relative_bbox(node_bbox: list[float], group_bbox: list[float]) -> list[float]:
    x, y, w, h = node_bbox
    gx, gy, _, _ = group_bbox
    return [x - gx, y - gy, w, h]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    if scene.get("sourceSchema") != "lanhu_figma_json":
        raise SystemExit("ERROR: make_figma_layout_contract requires scene.sourceSchema=lanhu_figma_json")
    groups = load_json(args.groups).get("groups") or []
    by_id = {node["id"]: node for node in scene.get("nodes") or []}
    contract: dict[str, dict] = {}
    for index, group in enumerate(groups, start=1):
        node_id = group.get("node")
        group_node = by_id.get(node_id)
        if not group_node:
            raise SystemExit(f"ERROR: group node missing from scene: {node_id}")
        widget_ids = [node_id, *descendants(node_id, by_id)]
        widgets = {}
        for child_id in widget_ids:
            node = by_id.get(child_id)
            if not node or node.get("effectiveVisible") is False:
                continue
            key = role_key(node)
            counter = 2
            base = key
            while key in widgets:
                suffix = f"_{counter}"
                key = f"{base[:64 - len(suffix)]}{suffix}"
                counter += 1
            widgets[key] = {
                "node": child_id,
                "path": node.get("path"),
                "widget": widget_for(node),
                "bbox": node["bbox"],
                "relativeBbox": relative_bbox(node["bbox"], group["bbox"]),
                "figmaType": node.get("figmaType"),
                "renderSource": "figma_hierarchy",
            }
        if not widgets:
            raise SystemExit(f"ERROR: group {node_id} has no visible widget mappings")
        component = group.get("id") or f"FigmaRegion{index}"
        contract[component] = {
            "designNode": node_id,
            "path": group.get("path"),
            "kind": group.get("kind"),
            "state": group.get("state"),
            "bbox": group["bbox"],
            "source": "figma_hierarchy",
            "widgets": widgets,
        }
    dump_json(contract, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
