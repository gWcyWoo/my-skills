#!/usr/bin/env python3
"""Group scene nodes into deterministic page structures."""

from __future__ import annotations

import argparse

from common import dump_json, load_json


def kind_for(node: dict, artboard_height: float) -> str:
    name = f"{node.get('name', '')} {node.get('text', '')}".lower()
    x, y, w, h = node["bbox"]
    if "tab" in name or y > artboard_height * 0.88:
        return "bottom_tabs"
    if "support" in name:
        return "support_section"
    if y < artboard_height * 0.12 and h < 160:
        return "header"
    if "card" in name or "loan" in name or h >= 120:
        return "loan_card"
    if "row" in name:
        return "row"
    if "column" in name:
        return "column"
    return "stack"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    nodes = scene.get("nodes") or []
    if not nodes:
        raise SystemExit("ERROR: scene has no nodes.")
    max_y = max(n["bbox"][1] + n["bbox"][3] for n in nodes)
    candidates = [
        n for n in nodes if n["bbox"][2] >= 100 and n["bbox"][3] >= 40
    ]
    candidates.sort(key=lambda n: (n["bbox"][1], n["bbox"][0], -n["bbox"][2] * n["bbox"][3]))
    groups = []
    state_index = 0
    for node in candidates:
        kind = kind_for(node, max_y)
        item = {"kind": kind, "node": node["id"], "bbox": node["bbox"]}
        if kind == "loan_card":
            item["state"] = f"state_{state_index + 1}"
            state_index += 1
        groups.append(item)
    if not groups:
        raise SystemExit("ERROR: no layout groups detected.")
    dump_json({"groups": groups}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
