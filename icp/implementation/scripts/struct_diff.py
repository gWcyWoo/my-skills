#!/usr/bin/env python3
"""Step 6: 结构对照 — view_tree.xml + layout-blueprint.json → struct-diff.json

确定性对照:文案覆盖、组件出现性、层级匹配。

用法:
    python3 struct_diff.py --view-tree <path> --blueprint <path> --output <path>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_view_tree(xml_path: Path) -> list[dict]:
    tree = ET.parse(xml_path)
    nodes = []
    for elem in tree.iter("node"):
        node = {
            "class": elem.get("class", ""),
            "text": elem.get("text", ""),
            "resource_id": elem.get("resource-id", ""),
            "content_desc": elem.get("content-desc", ""),
            "clickable": elem.get("clickable") == "true",
            "bounds": elem.get("bounds", ""),
            "children": [],
        }
        nodes.append(node)
    return nodes


def extract_view_texts(nodes: list[dict]) -> list[str]:
    texts = []
    for n in nodes:
        t = n.get("text", "").strip()
        if t:
            texts.append(t)
        desc = n.get("content_desc", "").strip()
        if desc:
            texts.append(desc)
    return texts


def normalize_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def match_texts(expected: list[str], actual: list[str]) -> dict:
    actual_normalized = {normalize_text(t) for t in actual}
    matched = []
    missing = []
    for exp in expected:
        exp_n = normalize_text(exp)
        if not exp_n:
            continue
        if exp_n in actual_normalized:
            matched.append(exp)
        else:
            missing.append(exp)
    return {"matched": matched, "missing": missing}


def count_interactive(nodes: list[dict]) -> int:
    return sum(1 for n in nodes if n.get("clickable"))


def check_hierarchy(blueprint: dict, nodes: list[dict]) -> dict:
    """Basic hierarchy check: components appear in expected order (top-to-bottom)."""
    component_names = [c["name"] for c in blueprint.get("components", [])]
    all_texts_by_component = {}
    for c in blueprint.get("components", []):
        texts = [t["value"] for t in c.get("texts", [])]
        if texts:
            all_texts_by_component[c["name"]] = texts

    actual_texts = extract_view_texts(nodes)
    actual_normalized = [normalize_text(t) for t in actual_texts]

    first_positions = {}
    for comp_name, comp_texts in all_texts_by_component.items():
        for ct in comp_texts:
            ct_n = normalize_text(ct)
            for i, at_n in enumerate(actual_normalized):
                if ct_n == at_n:
                    if comp_name not in first_positions or i < first_positions[comp_name]:
                        first_positions[comp_name] = i
                    break

    ordered_components = [c for c in component_names if c in first_positions]
    positions = [first_positions[c] for c in ordered_components]
    is_ordered = positions == sorted(positions)

    return {
        "components_with_text": list(first_positions.keys()),
        "order_correct": is_ordered,
        "order": ordered_components,
    }


def _match_textless_components(blueprint: dict, nodes: list[dict]) -> list[str]:
    """Match components with no texts by resource-id or content-desc in the view tree."""
    view_ids = set()
    view_descs = set()
    for n in nodes:
        rid = n.get("resource_id", "").strip()
        if rid:
            view_ids.add(rid.lower())
        desc = n.get("content_desc", "").strip()
        if desc:
            view_descs.add(desc.lower())

    found = []
    for c in blueprint.get("components", []):
        if c.get("texts"):
            continue
        name = c["name"].lower()
        if any(name in rid for rid in view_ids) or any(name in desc for desc in view_descs):
            found.append(c["name"])
    return found


def build_diff(blueprint: dict, view_tree_nodes: list[dict]) -> dict:
    bp_texts = []
    for c in blueprint.get("components", []):
        for t in c.get("texts", []):
            bp_texts.append(t["value"])

    actual_texts = extract_view_texts(view_tree_nodes)

    text_result = match_texts(bp_texts, actual_texts)
    hierarchy = check_hierarchy(blueprint, view_tree_nodes)
    interactive_actual = count_interactive(view_tree_nodes)

    bp_interactive = sum(
        1 for c in blueprint.get("components", [])
        if c.get("role") == "action"
    )

    found_by_id = _match_textless_components(blueprint, view_tree_nodes)
    found_by_id_set = set(found_by_id)
    text_comp_set = set(hierarchy["components_with_text"])
    all_matched_comps = text_comp_set | found_by_id_set

    diff = {
        "texts": {
            "expected": len(bp_texts),
            "matched": len(text_result["matched"]),
            "missing": text_result["missing"],
            "matched_list": text_result["matched"],
        },
        "components": {
            "expected": len(blueprint.get("components", [])),
            "found_by_text": len(hierarchy["components_with_text"]),
            "found_by_id": found_by_id,
            "missing": [
                c["name"] for c in blueprint.get("components", [])
                if c["name"] not in all_matched_comps
            ],
        },
        "hierarchy": hierarchy,
        "interactive": {
            "blueprint_action_components": bp_interactive,
            "view_clickable_nodes": interactive_actual,
        },
        "metrics": {
            "struct_texts_expected": len(bp_texts),
            "struct_texts_matched": len(text_result["matched"]),
            "struct_texts_missing": text_result["missing"],
            "struct_components_expected": len(blueprint.get("components", [])),
            "struct_components_matched": len(all_matched_comps),
            "struct_components_missing": [
                c["name"] for c in blueprint.get("components", [])
                if c["name"] not in all_matched_comps
            ],
            "struct_hierarchy_ok": hierarchy["order_correct"],
        },
    }
    return diff


def main():
    parser = argparse.ArgumentParser(description="Step 6: 结构对照")
    parser.add_argument("--view-tree", required=True, help="view_tree.xml path")
    parser.add_argument("--blueprint", required=True, help="layout-blueprint.json path")
    parser.add_argument("--output", required=True, help="output struct-diff.json path")
    parser.add_argument("--threshold", type=float, default=0.8,
                        help="文案覆盖率阈值 (0.0-1.0), 低于此值 → FAIL, 默认 0.8")
    args = parser.parse_args()

    view_tree_path = Path(args.view_tree)
    nodes = parse_view_tree(view_tree_path)

    with open(args.blueprint) as f:
        blueprint = json.load(f)

    diff = build_diff(blueprint, nodes)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)

    m = diff["metrics"]
    expected = m["struct_texts_expected"]
    matched = m["struct_texts_matched"]
    coverage = matched / expected if expected > 0 else 1.0
    ok = coverage >= args.threshold and m["struct_hierarchy_ok"]

    diff["gate"] = {
        "ok": ok,
        "coverage": round(coverage, 3),
        "threshold": args.threshold,
        "hierarchy_ok": m["struct_hierarchy_ok"],
    }
    with open(args.output, "w") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": ok,
        "texts": f"{matched}/{expected} ({round(coverage*100)}%)",
        "threshold": f"{round(args.threshold*100)}%",
        "components": f"{m['struct_components_matched']}/{m['struct_components_expected']}",
        "hierarchy_ok": m["struct_hierarchy_ok"],
        "missing_texts": m["struct_texts_missing"][:5],
    }, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
