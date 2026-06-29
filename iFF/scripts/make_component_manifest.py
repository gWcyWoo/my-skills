#!/usr/bin/env python3
"""Compile a component manifest (Track B) from the deterministic design artifacts.

generate_canvas.py produces the keyed, data-driven visible layer from render_plan. This script
reads render_plan.json (per-node geometry / implementation / text) + design_classification and
emits component_manifest.json — the component tree + dynamic_text_slot node ids that
generate_canvas binds to injected data (and bind_data_slots maps to OAS fields).

It does NOT decide data bindings (that is bind_data_slots.py + model judgment against the real
OAS). It only establishes deterministic STRUCTURE:
  - which components exist (header band / loan_card variants / bottom band),
  - each component's bbox and member render nodes,
  - per visible node a role: static_asset / static_shape / static_text / dynamic_text_slot,
    where dynamic_text_slot is a HEURISTIC candidate confirmed later by bind_data_slots.py.

Card components are reconstructed from render_plan geometry (650-ish wide subtrees, one per
y-band) rather than groups.json, whose kinds are noisy (pill backgrounds tagged 'header', the
whole artboard tagged 'region'). Fidelity stays guaranteed by check_render_fidelity (real render
trace vs render_plan), so coarse static-region structure here is safe; the manifest drives
decomposition + which text nodes are data-driven, not pixels.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# Text whose content looks data-driven (amount / percent / date / day-count / pure number).
_DYNAMIC_TEXT = re.compile(
    r"(₦|\$|\d[\d,]*\b|\d+\s*(day|days|minute|minutes)\b|\d+%|\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)
_ASSET_IMPL = {"image", "image_png", "image_webp", "image_fill", "svg", "asset"}
_SHAPE_IMPL = {"shape", "oval_shape", "gradient_shape", "vector_shape", "shape_container"}
_NON_VISIBLE = {"covered_by_asset", "covered_by_text", "hidden"}

# Loan cards are >=300 tall in this design family; 150-300 tall full-width rows are
# support/list rows, not loan cards, and fall through to the bottom region.
CARD_MIN_W, CARD_MAX_W, CARD_MIN_H = 600, 720, 300
# Two card roots within this many vertical px are nested frames of ONE visual card.
CARD_YBAND = 40


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def node_role(node: dict) -> str:
    impl = node.get("implementation")
    if impl in _NON_VISIBLE:
        return "non_visible"
    if impl in _ASSET_IMPL:
        return "static_asset"
    if impl == "text":
        text = (node.get("text") or "").strip()
        return "dynamic_text_slot" if _DYNAMIC_TEXT.search(text) else "static_text"
    return "static_shape"


# 真正的 UI chrome / 动作标签:卡片/列表区里它们保持静态;其它文本(产品名/银行名/状态文案等)
# 视为接口数据候选(不变量④/IMPL-DATA-1b)。纯数字/金额/日期已由 node_role 标过。
_CHROME_LABEL = re.compile(
    r"^\s*(apply|withdraw|repayment|repay|continue|cancel|confirm|ok|submit|next|back|done|close|"
    r"feedback|wait\s*a\s*moment|give\s*5\s*stars?|borrow\s*max|max|all\s*read|view|see\s*all|"
    r"details?|history|settings|add|edit|delete|save|retry|got\s*it|change|select|choose|verify|"
    r"send|resend|pay|remove|clear|skip|ok|yes|no|agree|got\s*it)\s*$", re.I)


def is_chrome_label(text: str) -> bool:
    t = (text or "").strip()
    return len(t) <= 2 or bool(_CHROME_LABEL.match(t))


def promote_region_text_slots(members: list) -> None:
    """卡片/列表区里非 chrome 的静态文本 → 动态槽候选(模型据 OAS 确认绑定或回退静态)。
    宽网:漏标一个接口字段(画死)比多审一个候选代价更大(IMPL-DATA-1b)。"""
    for m in members:
        if (m.get("role") == "static_text" and m.get("text")
                and not is_chrome_label(m["text"])):
            m["role"] = "dynamic_text_slot"
            m["promotedByRegion"] = True  # 候选:须 bind_data_slots/模型确认绑到 OAS,否则回退 static


def within(outer: list, inner: list, pad: float = 1.0) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (ix >= ox - pad and iy >= oy - pad
            and ix + iw <= ox + ow + pad and iy + ih <= oy + oh + pad)


def cluster_cards(nodes: dict) -> list:
    """650-ish wide subtrees → one card per y-band (image- OR shape-backed; impl-agnostic)."""
    cand = []
    for nid, n in nodes.items():
        bx = n.get("bbox")
        if bx and CARD_MIN_W <= bx[2] <= CARD_MAX_W and bx[3] >= CARD_MIN_H:
            cand.append((nid, bx))
    # widest-first within each top → keep the outermost frame, drop nested/dup frames.
    cand.sort(key=lambda t: (t[1][1], -t[1][2]))
    cards = []
    for nid, bx in cand:
        if cards and bx[1] - cards[-1]["bbox"][1] < CARD_YBAND:
            continue
        cards.append({"node": nid, "bbox": [round(v, 2) for v in bx]})
    return cards


def collect_member_nodes(nodes: dict, bbox: list, exclude_root: str | None = None) -> list:
    members = []
    for nid, n in nodes.items():
        if nid == exclude_root:
            continue
        nb = n.get("bbox")
        if not nb or nb == bbox:
            continue
        if within(bbox, nb):
            role = node_role(n)
            if role == "non_visible":
                continue
            members.append({
                "node": nid,
                "bbox": [round(v, 2) for v in nb],
                "implementation": n.get("implementation"),
                "role": role,
                "text": (n.get("text") or "") if n.get("implementation") == "text" else None,
                "asset": n.get("asset"),
            })
    members.sort(key=lambda m: (m["bbox"][1], m["bbox"][0]))
    return members


def band_component(name: str, kind: str, nodes: dict, y0: float, y1: float, artboard_w: float) -> dict:
    bbox = [0.0, round(y0, 2), artboard_w, round(y1 - y0, 2)]
    return {
        "name": name,
        "kind": kind,
        "bbox": bbox,
        "variant": False,
        "repeated": False,
        "nodes": collect_member_nodes(nodes, bbox),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-plan", required=True)
    ap.add_argument("--classification", required=True)
    ap.add_argument("--groups", required=False, help="optional; kinds are advisory only")
    ap.add_argument("--scene", required=False)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    nodes = load(args.render_plan).get("nodes", {})
    classification = load(args.classification)
    artboard = classification.get("artboard", {})
    artboard_w = float(artboard.get("width", 750))
    artboard_h = float(artboard.get("height", 0))
    states = classification.get("states", [])

    cards = cluster_cards(nodes)
    components = []

    if cards:
        first_top = min(c["bbox"][1] for c in cards)
        last_bottom = max(c["bbox"][1] + c["bbox"][3] for c in cards)
        # Header band: everything above the first card.
        components.append(band_component("HeaderComponent", "header", nodes, 0.0, first_top, artboard_w))
        # Loan-card variant components.
        for i, c in enumerate(cards):
            members = collect_member_nodes(nodes, c["bbox"], exclude_root=c["node"])
            promote_region_text_slots(members)  # 卡片区文本字段宽网为动态候选(IMPL-DATA-1b)
            components.append({
                "name": "LoanCardComponent",
                "kind": "loan_card",
                "variantIndex": i,
                "variantState": states[i] if i < len(states) else None,
                "rootNode": c["node"],
                "bbox": c["bbox"],
                "variant": True,
                "repeated": True,
                "nodeCount": len(members),
                "nodes": members,
                "dynamicSlots": [m for m in members if m["role"] == "dynamic_text_slot"],
                "staticTextLabels": [m["text"] for m in members if m["role"] == "static_text"],
            })
        # Bottom band: support section + tab bar below the last card.
        if artboard_h > last_bottom:
            components.append(
                band_component("BottomRegionComponent", "bottom_region", nodes, last_bottom, artboard_h, artboard_w))

    manifest = {
        "source": "make_component_manifest.py",
        "classificationType": classification.get("type"),
        "artboard": artboard,
        "designStates": states,
        "componentCount": len(components),
        "loanCardVariantCount": sum(1 for c in components if c["kind"] == "loan_card"),
        "components": components,
        "notes": [
            "Cards reconstructed from render_plan geometry (impl-agnostic y-band clustering), not groups.json.",
            "role=dynamic_text_slot is a HEURISTIC candidate; confirm bindings via bind_data_slots.py + real OAS.",
            "Static-region structure (header/bottom) is coarse by design; pixel fidelity is enforced by "
            "check_render_fidelity.py (real render trace vs render_plan), not by this manifest.",
            "designStates only labels the first len(states) cards; remaining variants need model labelling in "
            "bind_data_slots.py against apply_status semantics.",
        ],
    }
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok component manifest components={len(components)} "
          f"loan_card_variants={manifest['loanCardVariantCount']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
