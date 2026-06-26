#!/usr/bin/env python3
"""Group scene nodes into deterministic page structures."""

from __future__ import annotations

import argparse

from common import dump_json, load_json


def _inside(node: dict, bbox: list[float], *, pad: float = 0.0) -> bool:
    x, y, w, h = node["bbox"]
    gx, gy, gw, gh = bbox
    return gx - pad <= x and gy - pad <= y and x + w <= gx + gw + pad and y + h <= gy + gh + pad


def _visual_text(nodes: list[dict], bbox: list[float]) -> str:
    texts = []
    for node in nodes:
        text = node.get("text")
        if text and _inside(node, bbox, pad=2):
            texts.append(str(text).lower())
    return " ".join(texts)


def _state_for(nodes: list[dict], bbox: list[float], index: int) -> str:
    text = _visual_text(nodes, bbox)
    if "overdue" in text:
        return "overdue_9"
    if "repayment date" in text:
        return "repayment_8"
    if "please be patient" in text or "disbursing" in text:
        return "disbursing_6"
    if "payment failed" in text:
        return "payment_failed_7"
    if "withdraw your funds before they expire" in text:
        return "withdraw_5"
    if "as little as 1 minute" in text:
        return "review_wait_11"
    if "feedback" in text:
        return "rejected_4"
    if "give 5 stars" in text or "currently under review" in text:
        return "review_3"
    if "apply" in text:
        return "apply_0_1_2_10"
    return f"state_{index}"


def _priority(node: dict) -> tuple[int, int]:
    node_id = str(node.get("id", ""))
    node_type = str(node.get("type", ""))
    generated = 1 if node_id.startswith("figma_json.") else 0
    semantic_type = 0 if node_type in {"group", "grouplayer", "shapelayer"} else 1
    return generated, semantic_type


def _dedupe_by_bbox(nodes: list[dict], *, tolerance: float = 1.0) -> list[dict]:
    selected: list[dict] = []
    seen: set[tuple[int, int, int, int]] = set()
    for node in sorted(nodes, key=lambda n: (n["bbox"][1], n["bbox"][0], _priority(n))):
        key = tuple(round(v / tolerance) for v in node["bbox"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(node)
    return selected


def _card_candidates(nodes: list[dict], artboard_height: float) -> list[dict]:
    result = []
    for node in nodes:
        x, y, w, h = node["bbox"]
        if not (45 <= x <= 55 and 640 <= w <= 660 and h >= 300 and 120 <= y <= artboard_height - 700):
            continue
        if not node.get("fills"):
            continue
        if str(node.get("id", "")).startswith("figma_json."):
            continue
        result.append(node)
    return _dedupe_by_bbox(result)


def _support_candidates(nodes: list[dict], after_y: float, artboard_height: float) -> list[dict]:
    result = []
    for node in nodes:
        x, y, w, h = node["bbox"]
        if not (45 <= x <= 55 and 640 <= w <= 660 and 120 <= h <= 220 and y > after_y and y < artboard_height - 250):
            continue
        if not node.get("fills"):
            continue
        if str(node.get("id", "")).startswith("figma_json."):
            continue
        result.append(node)
    return _dedupe_by_bbox(result)


def _bottom_bbox(nodes: list[dict], artboard_width: float, artboard_height: float) -> list[float] | None:
    starts = []
    for node in nodes:
        x, y, w, h = node["bbox"]
        if x <= 1 and w >= artboard_width - 1 and y >= artboard_height - 260 and h >= 80:
            starts.append(y)
    if not starts:
        return None
    y = min(starts)
    return [0.0, y, artboard_width, artboard_height - y]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene = load_json(args.scene)
    if scene.get("sourceSchema") == "lanhu_figma_json":
        from group_figma_layout import main as figma_main

        return figma_main()
    nodes = scene.get("nodes") or []
    if not nodes:
        raise SystemExit("ERROR: scene has no nodes.")

    artboard = scene.get("artboard") or {}
    artboard_nodes = [node for node in nodes if node.get("type") == "artboard" and node.get("bbox")]
    artboard_width = float(
        artboard.get("width")
        or (artboard_nodes[0]["bbox"][2] if artboard_nodes else max(n["bbox"][0] + n["bbox"][2] for n in nodes))
    )
    artboard_height = float(
        artboard.get("height")
        or (artboard_nodes[0]["bbox"][3] if artboard_nodes else max(n["bbox"][1] + n["bbox"][3] for n in nodes))
    )

    groups: list[dict] = []
    cards = _card_candidates(nodes, artboard_height)
    first_card_y = cards[0]["bbox"][1] if cards else 0.0
    if first_card_y > 0:
        groups.append({"kind": "header", "node": "__header__", "bbox": [0.0, 0.0, artboard_width, first_card_y]})

    for index, node in enumerate(cards, start=1):
        groups.append(
            {
                "kind": "loan_card",
                "node": node["id"],
                "bbox": node["bbox"],
                "state": _state_for(nodes, node["bbox"], index),
            }
        )

    after_cards = max((card["bbox"][1] + card["bbox"][3] for card in cards), default=first_card_y)
    support_nodes = _support_candidates(nodes, after_cards, artboard_height)
    if support_nodes and support_nodes[0]["bbox"][1] - after_cards >= 24:
        groups.append(
            {
                "kind": "support_section",
                "node": "__support_header__",
                "bbox": [50.0, after_cards, artboard_width - 100.0, support_nodes[0]["bbox"][1] - after_cards],
                "state": "support_header",
            }
        )
    for index, node in enumerate(support_nodes, start=1):
        groups.append({"kind": "support_section", "node": node["id"], "bbox": node["bbox"], "state": f"support_{index}"})

    bottom = _bottom_bbox(nodes, artboard_width, artboard_height)
    if bottom:
        groups.append({"kind": "bottom_tabs", "node": "__bottom_tabs__", "bbox": bottom})

    if not groups:
        raise SystemExit("ERROR: no layout groups detected.")
    dump_json({"groups": groups}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
