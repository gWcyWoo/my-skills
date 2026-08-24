#!/usr/bin/env python3
"""Step 1: 蓝图提取 — enriched.json + design.json → layout-blueprint.json

从 Stage 1 产物提取布局意图,保留设计值原样,不转换单位。

用法:
    python3 blueprint.py --enriched <path> --design <path> --output <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_artboard_meta(design: dict) -> dict:
    meta = design.get("meta", {})
    device = meta.get("device", "")
    scale = "1x"
    if "@" in device:
        parts = device.split("@")
        scale = parts[-1].strip()
    artboard_node = design.get("artboard", {})
    frame = artboard_node.get("frame", {})
    return {
        "width": frame.get("width", 0),
        "height": frame.get("height", 0),
        "scale": scale,
        "device": device,
        "host": meta.get("host", {}).get("name", ""),
    }


def _count_distinct_bands(values: list[float], tolerance: float = 4) -> int:
    """Count distinct bands — groups of values within tolerance of each other."""
    if not values:
        return 0
    sorted_v = sorted(values)
    bands = 1
    for i in range(1, len(sorted_v)):
        if sorted_v[i] - sorted_v[i - 1] > tolerance:
            bands += 1
    return bands


def infer_layout(children_frames: list[dict]) -> str:
    if len(children_frames) <= 1:
        return "single"
    overlaps = 0
    n = len(children_frames)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = children_frames[i], children_frames[j]
            v_overlap = not (a["top"] + a["height"] <= b["top"] or b["top"] + b["height"] <= a["top"])
            h_overlap = not (a["left"] + a["width"] <= b["left"] or b["left"] + b["width"] <= a["left"])
            if v_overlap and h_overlap:
                overlaps += 1
    total_pairs = n * (n - 1) // 2
    if total_pairs > 0 and overlaps / total_pairs > 0.5:
        return "stack"
    top_bands = _count_distinct_bands([f["top"] for f in children_frames])
    left_bands = _count_distinct_bands([f["left"] for f in children_frames])
    if top_bands >= left_bands:
        return "column"
    return "row"


def compute_padding(child_frame: dict, parent_frame: dict) -> dict:
    return {
        "start": round(child_frame["left"] - parent_frame["left"], 1),
        "top": round(child_frame["top"] - parent_frame["top"], 1),
        "end": round(
            (parent_frame["left"] + parent_frame["width"])
            - (child_frame["left"] + child_frame["width"]),
            1,
        ),
        "bottom": round(
            (parent_frame["top"] + parent_frame["height"])
            - (child_frame["top"] + child_frame["height"]),
            1,
        ),
    }


def compute_spacing(frames: list[dict], layout: str) -> list[float]:
    if len(frames) < 2:
        return []
    if layout == "column":
        sorted_f = sorted(frames, key=lambda f: f["top"])
        return [
            round(sorted_f[i + 1]["top"] - (sorted_f[i]["top"] + sorted_f[i]["height"]), 1)
            for i in range(len(sorted_f) - 1)
        ]
    elif layout == "row":
        sorted_f = sorted(frames, key=lambda f: f["left"])
        return [
            round(sorted_f[i + 1]["left"] - (sorted_f[i]["left"] + sorted_f[i]["width"]), 1)
            for i in range(len(sorted_f) - 1)
        ]
    return []


def infer_width_constraint(child_frame: dict, parent_frame: dict) -> str:
    if abs(child_frame["width"] - parent_frame["width"]) < 2:
        return "fill"
    pad_start = child_frame["left"] - parent_frame["left"]
    pad_end = (parent_frame["left"] + parent_frame["width"]) - (child_frame["left"] + child_frame["width"])
    if pad_start >= 0 and pad_end >= 0 and abs(pad_start - pad_end) < 4:
        return "fill"
    return "fixed"


def extract_text(member: dict) -> dict | None:
    text = member.get("text")
    if not text:
        return None
    result = {"value": text["value"], "frame": member.get("frame")}
    spans = text.get("spans", [])
    if spans:
        s = spans[0]
        result["style"] = {
            "font": s.get("font"),
            "size": s.get("size"),
            "weight": s.get("weight"),
            "color": s.get("color"),
            "line_height": s.get("line_height"),
            "align": s.get("align"),
            "letter_spacing": s.get("letter_spacing"),
        }
    return result


def extract_fill(member: dict) -> dict | None:
    fills = member.get("fills")
    if not fills:
        return None
    f = fills[0]
    fill_type = f.get("type", "solid")
    if fill_type == "gradient":
        return {
            "type": "gradient",
            "gradient_type": f.get("gradient_type"),
            "stops": f.get("stops", []),
        }
    return {"type": fill_type, "color": f.get("color")}


def extract_asset_ref(member: dict) -> dict | None:
    if member.get("type") == "symbolInstence":
        return {"id": member["id"], "name": member["name"], "frame": member.get("frame")}
    return None


def find_container_frame(members: list[dict]) -> tuple[dict | None, list[dict]]:
    """Separate container frame from content members.

    If the first member is an artboard/symbolInstence wrapping others, it's the container.
    If the component has only one member, that member is both container and content.
    """
    if not members:
        return None, []
    if len(members) == 1:
        return members[0].get("frame"), members
    first = members[0]
    if first.get("type") in ("artboard", "symbolInstence"):
        return first.get("frame"), members[1:]
    return first.get("frame"), members


def is_background_layer(member: dict, container_frame: dict) -> bool:
    """An artboard whose frame matches the container is a background, not a layout child."""
    if member.get("type") != "artboard":
        return False
    f = member.get("frame")
    if not f or not container_frame:
        return False
    return (abs(f["width"] - container_frame["width"]) < 2
            and abs(f["height"] - container_frame["height"]) < 2)


def classify_members(
    members: list[dict], container_frame: dict
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split members into content, background layers, and pure wrappers."""
    content = []
    backgrounds = []
    for m in members:
        if m.get("type") == "artboard" and not m.get("text"):
            if not m.get("fills") and not m.get("shared_style"):
                continue
            if is_background_layer(m, container_frame):
                backgrounds.append(m)
                continue
        content.append(m)
    if not content:
        return members, backgrounds, []
    return content, backgrounds, []


def build_component_blueprint(component: dict, artboard_frame: dict) -> dict:
    members = component.get("members", [])
    if not members:
        return {
            "name": component["name"],
            "role": component["role"],
            "description": component.get("description", ""),
            "layout": "empty",
            "children": [],
        }

    container_frame, child_members = find_container_frame(members)
    if not container_frame:
        container_frame = artboard_frame

    content_members, bg_layers, _ = classify_members(child_members, container_frame)

    texts = []
    fills = []
    assets = []
    child_frames = []

    for m in content_members:
        f = m.get("frame")
        if f:
            child_frames.append(f)
        t = extract_text(m)
        if t:
            texts.append(t)
        fl = extract_fill(m)
        if fl and m.get("type") != "textLayer":
            fills.append({"name": m["name"], **fl})
        a = extract_asset_ref(m)
        if a:
            assets.append(a)

    for bg in bg_layers:
        fl = extract_fill(bg)
        if fl:
            fills.insert(0, {"name": bg["name"], "layer": "background", **fl})

    layout = infer_layout(child_frames) if child_frames else "single"
    width = infer_width_constraint(container_frame, artboard_frame)

    inner_padding = {}
    if child_frames and container_frame:
        child_lefts = [f["left"] for f in child_frames]
        child_tops = [f["top"] for f in child_frames]
        child_rights = [f["left"] + f["width"] for f in child_frames]
        child_bottoms = [f["top"] + f["height"] for f in child_frames]
        inner_padding = {
            "start": round(min(child_lefts) - container_frame["left"], 1),
            "top": round(min(child_tops) - container_frame["top"], 1),
            "end": round((container_frame["left"] + container_frame["width"]) - max(child_rights), 1),
            "bottom": round((container_frame["top"] + container_frame["height"]) - max(child_bottoms), 1),
        }

    spacing = compute_spacing(child_frames, layout)

    container_fill = extract_fill(members[0]) if len(members) > 1 else None

    result = {
        "name": component["name"],
        "role": component["role"],
        "description": component.get("description", ""),
        "frame": container_frame,
        "layout": layout,
        "width": width,
        "padding": inner_padding,
        "texts": texts,
    }
    if spacing:
        result["spacing"] = spacing
    if container_fill:
        result["fill"] = container_fill
    if fills:
        result["child_fills"] = fills
    if assets:
        result["assets"] = assets

    return result


def build_blueprint(enriched: dict, design: dict) -> dict:
    artboard = parse_artboard_meta(design)
    components = enriched.get("components", [])

    root_frame = {"left": 0, "top": 0, "width": artboard["width"], "height": artboard["height"]}
    if components:
        root_member = components[0].get("members", [{}])[0]
        rf = root_member.get("frame", {})
        if rf.get("width"):
            root_frame["width"] = rf["width"]
            root_frame["height"] = rf["height"]

    page_components = components[1:]
    comp_frames = []
    for c in page_components:
        ms = c.get("members", [])
        if ms and ms[0].get("frame"):
            comp_frames.append(ms[0]["frame"])

    page_layout = infer_layout(comp_frames) if comp_frames else "column"
    page_spacing = compute_spacing(comp_frames, page_layout)

    component_blueprints = []
    for c in page_components:
        bp = build_component_blueprint(c, root_frame)
        component_blueprints.append(bp)

    all_texts = []
    all_assets = []
    layout_types = {}
    for bp in component_blueprints:
        all_texts.extend(bp.get("texts", []))
        all_assets.extend(bp.get("assets", []))
        lt = bp.get("layout", "single")
        layout_types[lt] = layout_types.get(lt, 0) + 1

    blueprint = {
        "artboard": artboard,
        "page_layout": page_layout,
        "page_spacing": page_spacing,
        "components": component_blueprints,
        "metrics": {
            "blueprint_components": len(component_blueprints),
            "blueprint_texts": len(all_texts),
            "blueprint_assets": len(all_assets),
            "blueprint_layouts": layout_types,
        },
    }
    return blueprint


def main():
    parser = argparse.ArgumentParser(description="Step 1: 蓝图提取")
    parser.add_argument("--enriched", required=True, help="enriched.json path")
    parser.add_argument("--design", required=True, help="design.json path")
    parser.add_argument("--output", required=True, help="output layout-blueprint.json path")
    args = parser.parse_args()

    with open(args.enriched) as f:
        enriched = json.load(f)
    with open(args.design) as f:
        design = json.load(f)

    blueprint = build_blueprint(enriched, design)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)

    m = blueprint["metrics"]
    print(json.dumps({"ok": True, **m}, ensure_ascii=False))


if __name__ == "__main__":
    main()
