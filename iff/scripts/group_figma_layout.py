#!/usr/bin/env python3
"""Group layout regions from the Figma layer tree before bbox heuristics."""

from __future__ import annotations

import argparse
import re

from common import dump_json, load_json


GROUP_TYPES = {"artboard", "grouplayer", "frame", "component", "instance", "section"}


def kind_for(node: dict, artboard: dict, siblings: list[dict]) -> str:
    name = f"{node.get('name', '')} {node.get('path', '')}".lower()
    x, y, w, h = node["bbox"]
    height = float(artboard.get("height") or 0)
    if "tab" in name or "nav" in name or (height and y >= height * 0.88):
        return "bottom_tabs"
    if "header" in name or "top" in name or (height and y <= height * 0.12 and h <= 180):
        return "header"
    if "support" in name or "help" in name:
        return "support_section"
    if "form" in name or "input" in name or "field" in name:
        return "form"
    if "button" in name or "btn" in name:
        return "button_group"
    if "list" in name:
        return "list"
    if any(token in name for token in ("card", "loan", "product", "order", "item")):
        return "loan_card"
    similar = [
        other for other in siblings
        if other is not node
        and abs(other["bbox"][0] - x) <= 4
        and abs(other["bbox"][2] - w) <= 8
        and abs(other["bbox"][3] - h) <= 16
    ]
    if len(similar) >= 1 and h >= 80:
        return "repeated_region"
    return "region"


def state_for(node: dict, index: int) -> str | None:
    text = f"{node.get('name', '')} {node.get('path', '')}".lower()
    for token, state in (
        ("apply", "apply"),
        ("review", "review"),
        ("reject", "reject"),
        ("withdraw", "withdraw"),
        ("overdue", "overdue"),
        ("pending", "pending"),
        ("support", "support"),
    ):
        if token in text:
            return f"{state}_{index}"
    return None


def component_name(kind: str, index: int) -> str:
    words = re.split(r"[^a-zA-Z0-9]+", kind)
    base = "".join(word[:1].upper() + word[1:] for word in words if word) or "Region"
    return f"{base}{index}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    nodes = scene.get("nodes") or []
    artboard = scene.get("artboard") or {}
    if scene.get("sourceSchema") != "lanhu_figma_json":
        raise SystemExit("ERROR: group_figma_layout requires scene.sourceSchema=lanhu_figma_json")
    by_id = {node["id"]: node for node in nodes}
    root_id = artboard.get("id")
    candidates = [
        node for node in nodes
        if node.get("id") != root_id
        and node.get("effectiveVisible") is not False
        and node.get("type") in GROUP_TYPES
        and node.get("children")
        and node["bbox"][2] >= 24
        and node["bbox"][3] >= 24
    ]
    direct_children = [by_id[child_id] for child_id in (by_id.get(root_id, {}).get("children") or []) if child_id in by_id]
    sibling_scope = direct_children or candidates

    groups = []
    for index, node in enumerate(sorted(candidates, key=lambda item: (item.get("depth", 0), item["bbox"][1], item["bbox"][0])), start=1):
        kind = kind_for(node, artboard, sibling_scope)
        state = state_for(node, index)
        groups.append(
            {
                "id": component_name(kind, index),
                "kind": kind,
                "node": node["id"],
                "path": node.get("path"),
                "parent": node.get("parent"),
                "children": node.get("children") or [],
                "bbox": node["bbox"],
                "state": state,
                "source": "figma_hierarchy",
                "depth": node.get("depth", 0),
            }
        )
    # Always include the screen root as a coverage region so leaf nodes placed
    # directly on the artboard (loose header/card content not wrapped in a
    # sub-frame) are mapped by the layout contract and pass the render-plan
    # widget-mapping audit. Use the artboard-local origin so relative bboxes
    # stay consistent with the sub-frame groups above.
    root_node = by_id.get(root_id)
    if root_node and root_node.get("children"):
        local_bbox = [
            0.0,
            0.0,
            float(artboard.get("width") or root_node["bbox"][2]),
            float(artboard.get("height") or root_node["bbox"][3]),
        ]
        groups.append(
            {
                "id": component_name("region", len(groups) + 1),
                "kind": "region",
                "node": root_id,
                "path": root_node.get("path"),
                "parent": root_node.get("parent"),
                "children": root_node.get("children") or [],
                "bbox": local_bbox,
                "state": None,
                "source": "figma_hierarchy",
                "depth": root_node.get("depth", 0),
            }
        )
    if not groups:
        raise SystemExit("ERROR: no Figma layout groups detected")
    dump_json({"source": "figma_hierarchy", "groups": groups}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
