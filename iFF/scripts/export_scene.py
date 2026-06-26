#!/usr/bin/env python3
"""Export a deterministic machine-readable visual scene tree."""

from __future__ import annotations

import argparse

from common import collect_scene_nodes, dump_json, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = load_json(args.raw)
    try:
        assets = load_json(args.assets)
    except FileNotFoundError:
        assets = {}
    if isinstance(raw, dict) and isinstance(raw.get("figma_json"), dict) and raw["figma_json"].get("artboard"):
        from export_figma_scene import main as figma_main

        return figma_main()
    nodes = collect_scene_nodes(raw, assets)
    if not nodes:
        raise SystemExit("ERROR: no nodes with bbox found in raw design.")
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        x, y, w, h = node["bbox"]
        children = []
        for child in nodes:
            if child is node:
                continue
            cx, cy, cw, ch = child["bbox"]
            if x <= cx and y <= cy and cx + cw <= x + w and cy + ch <= y + h:
                children.append(child["id"])
        node["children"] = children[:200]
    dump_json({"nodes": list(by_id.values())}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
