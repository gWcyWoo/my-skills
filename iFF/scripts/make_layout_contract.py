#!/usr/bin/env python3
"""Create a deterministic layout contract from scene and groups."""

from __future__ import annotations

import argparse
import re

from common import dump_json, load_json


def component_name(group: dict, index: int) -> str:
    words = re.split(r"[^a-zA-Z0-9]+", group.get("kind", "component"))
    base = "".join(w[:1].upper() + w[1:] for w in words if w) or "Component"
    return f"{base}{index + 1}"


def widget_for(node: dict) -> str:
    node_type = str(node.get("type", "")).lower()
    name = f"{node.get('name', '')} {node.get('text', '')}".lower()
    if node.get("text") or "text" in node_type:
        return "Text"
    if "button" in name:
        return "Button"
    if node.get("asset"):
        return "Image/SVG"
    return "Container"


def overlap_ratio(node_bbox: list[float], group_bbox: list[float]) -> float:
    x, y, w, h = node_bbox
    gx, gy, gw, gh = group_bbox
    ix1 = max(x, gx)
    iy1 = max(y, gy)
    ix2 = min(x + w, gx + gw)
    iy2 = min(y + h, gy + gh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return ((ix2 - ix1) * (iy2 - iy1)) / max(w * h, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    if scene.get("sourceSchema") == "lanhu_figma_json":
        from make_figma_layout_contract import main as figma_main

        return figma_main()
    groups = load_json(args.groups).get("groups") or []
    nodes = {node["id"]: node for node in scene.get("nodes") or []}
    contract: dict[str, dict] = {}
    for index, group in enumerate(groups):
        gx, gy, gw, gh = group["bbox"]
        widgets = {}
        for node in nodes.values():
            x, y, w, h = node["bbox"]
            contained = gx <= x and gy <= y and x + w <= gx + gw and y + h <= gy + gh
            if contained or overlap_ratio(node["bbox"], group["bbox"]) >= 0.15:
                role = node.get("name") or node.get("text") or node["id"]
                role = re.sub(r"[^a-zA-Z0-9]+", "_", str(role)).strip("_") or node["id"]
                node_key = re.sub(r"[^a-zA-Z0-9]+", "_", str(node["id"])).strip("_") or "node"
                base_key = role[:44] or "node"
                key = f"{base_key}_{node_key[:18]}"[:64]
                counter = 2
                while key in widgets:
                    suffix = f"_{counter}"
                    key = f"{base_key[:64 - len(suffix)]}{suffix}"
                    counter += 1
                widgets[key] = {"node": node["id"], "widget": widget_for(node), "bbox": node["bbox"]}
        if not widgets:
            raise SystemExit(f"ERROR: group {group.get('kind')} has no widget mappings.")
        contract[component_name(group, index)] = {
            "designNode": group.get("node"),
            "kind": group.get("kind"),
            "state": group.get("state"),
            "bbox": group["bbox"],
            "widgets": widgets,
        }
    dump_json(contract, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
