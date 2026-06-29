#!/usr/bin/env python3
"""Classify a Lanhu artboard before iFF implementation starts."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import collect_scene_nodes, dump_json, load_json, png_size


STATE_WORDS = {
    "apply": "apply_0",
    "review": "review_3",
    "reject": "reject_4",
    "withdraw": "withdraw_5",
    "approved": "approved",
    "pending": "pending",
}


def infer_states(nodes: list[dict]) -> list[str]:
    states: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        text = f"{node.get('name', '')} {node.get('text', '')}".lower()
        for token, state in STATE_WORDS.items():
            if token in text and state not in seen:
                seen.add(state)
                states.append(state)
    return states


def repeated_large_groups(nodes: list[dict], artboard_width: int) -> list[dict]:
    groups = []
    for node in nodes:
        x, y, w, h = node["bbox"]
        if w >= artboard_width * 0.45 and h >= 80:
            groups.append(node)
    return sorted(groups, key=lambda n: (n["bbox"][1], n["bbox"][0]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = load_json(args.raw)
    width, height = png_size(args.reference)
    nodes = collect_scene_nodes(raw)
    groups = repeated_large_groups(nodes, width)
    states = infer_states(nodes)

    scale = 2 if width >= 700 else 1
    viewport = {"width": round(width / scale), "height": 812 if height > 1200 else round(height / scale)}

    # 判类先看画板是否就是"单台设备一屏":宽高都≈一个视口 ⇒ 单 screen(再多页内分区也只是一屏)。
    # 多屏布局必然在某一维显著超过一个视口:纵向堆叠多态=variant_board / 纵向长目录=component_sheet /
    # 横向并排多屏=flow_board。用"整页级组块"(近满宽且≥半视口高、且非整张画板本身)数量区分前两者。
    vp_w_px = viewport["width"] * scale
    vp_h_px = viewport["height"] * scale
    tall = height > vp_h_px * 1.4
    wide = width > vp_w_px * 1.4
    page_groups = [g for g in groups
                   if g["bbox"][2] >= width * 0.85
                   and vp_h_px * 0.55 <= g["bbox"][3] <= height * 0.9]

    if not tall and not wide:
        design_type = "screen"
        reason = "artboard is a single device viewport"
    elif tall and len(page_groups) >= 2:
        design_type = "variant_board"
        reason = "long artboard stacking multiple full-page states"
        if not states:
            states = [f"state_{i + 1}" for i in range(len(page_groups))]
    elif tall and len(groups) >= 8:
        design_type = "component_sheet"
        reason = "tall catalog of many independent components (no full-page states)"
    elif len(page_groups) >= 2:
        design_type = "flow_board"
        reason = "multiple page-like screens in one artboard"
    else:
        design_type = "screen"
        reason = "single page-like artboard"

    result = {
        "type": design_type,
        "artboard": {"width": width, "height": height, "scale": scale},
        "viewport": viewport,
        "states": states,
        "reason": reason,
        "raw": str(Path(args.raw)),
        "reference": str(Path(args.reference)),
    }
    dump_json(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
