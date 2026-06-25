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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    groups = load_json(args.groups).get("groups") or []
    nodes = {node["id"]: node for node in scene.get("nodes") or []}
    contract: dict[str, dict] = {}
    for index, group in enumerate(groups):
        gx, gy, gw, gh = group["bbox"]
        widgets = {}
        for node in nodes.values():
            x, y, w, h = node["bbox"]
            if gx <= x and gy <= y and x + w <= gx + gw and y + h <= gy + gh:
                role = node.get("name") or node.get("text") or node["id"]
                role = re.sub(r"[^a-zA-Z0-9]+", "_", str(role)).strip("_") or node["id"]
                widgets[role[:64]] = {"node": node["id"], "widget": widget_for(node), "bbox": node["bbox"]}
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
