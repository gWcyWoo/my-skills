#!/usr/bin/env python3
"""Decide how every design node must be rendered in Flutter."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump_json, load_json


def asset_strategy(asset_path: str) -> str:
    ext = Path(asset_path).suffix.lower()
    if ext == ".webp":
        return "image_webp"
    if ext == ".png":
        return "image_png"
    if ext == ".svg":
        return "svg"
    return "asset"


def implementation_for(node: dict) -> str:
    name = f"{node.get('name', '')} {node.get('text', '')}".lower()
    if node.get("text"):
        return "text"
    if "button" in name or "input" in name or "field" in name:
        return "interactive_hit_area"
    if node.get("asset"):
        return asset_strategy(str(node["asset"]))
    if node.get("fills") or node.get("radius") is not None or node.get("border"):
        return "shape"
    return "shape"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    try:
        assets = load_json(args.assets)
    except FileNotFoundError:
        assets = {}
    layout = load_json(args.layout)
    nodes = scene.get("nodes") or []
    if not nodes:
        raise SystemExit("ERROR: scene has no nodes")

    max_area = max(n["bbox"][2] * n["bbox"][3] for n in nodes)
    plan = {"nodes": {}, "assetStrategy": "webP > png; svg only for simple vectors"}
    errors = []
    for node in nodes:
        bbox = node["bbox"]
        mode = implementation_for(node)
        if mode.startswith("image") or mode == "svg" or mode == "asset":
            asset = node.get("asset")
            if not asset:
                errors.append(f"asset node missing asset path: {node['id']}")
        if node.get("asset") and bbox[2] * bbox[3] >= max_area * 0.98:
            errors.append(f"full-artboard asset is forbidden: {node['id']}")
        plan["nodes"][node["id"]] = {
            "name": node.get("name"),
            "bbox": bbox,
            "implementation": mode,
            "asset": node.get("asset"),
            "widgetTraceRequired": True,
        }

    mapped = set()
    for component in layout.values():
        for widget in component.get("widgets", {}).values():
            if widget.get("node"):
                mapped.add(widget["node"])
    missing_mappings = [
        node["id"] for node in nodes
        if node["bbox"][2] * node["bbox"][3] >= 64 and node["id"] not in mapped
    ]
    if missing_mappings:
        errors.append("nodes missing layout widget mapping: " + ", ".join(missing_mappings[:20]))
    if errors:
        raise SystemExit("ERROR: render plan failed:\n" + "\n".join(errors))
    dump_json(plan, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
