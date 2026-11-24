#!/usr/bin/env python3
"""Step 1: 蓝图提取 — enriched.json + design.json + slices.json → layout-blueprint.json

从 Stage 1 产物提取布局意图,保留设计值原样,不转换单位。

用法:
    python3 blueprint.py --enriched <path> --design <path> --output <path> --slices <path>
"""
from __future__ import annotations

import argparse
import json
import re
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
    if overlaps / total_pairs > 0.5:
        return "stack"
    top_bands = _count_distinct_bands([f["top"] for f in children_frames])
    left_bands = _count_distinct_bands([f["left"] for f in children_frames])
    if top_bands >= left_bands:
        return "column"
    return "row"


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
    if (pad_start >= 0 and pad_end >= 0 and abs(pad_start - pad_end) < 4
            and child_frame["width"] > parent_frame["width"] * 0.5):
        return "fill"
    return "fixed"


def extract_text(member: dict) -> dict | None:
    text = member.get("text")
    if not text:
        return None
    result = {"value": text["value"]}
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
    if len(fills) > 1:
        layers = [extract_fill({"fills": [fill]}) for fill in fills]
        # Keep the legacy first-fill summary; layers is the complete ordered fill.
        return {**layers[0], "layers": layers}
    f = fills[0]
    fill_type = f.get("type", "solid")
    if fill_type == "gradient":
        return {
            "type": "gradient",
            "gradient_type": f.get("gradient_type"),
            "stops": f.get("stops", []),
            **{key: f[key] for key in ("from", "to", "transform") if key in f},
        }
    if fill_type == "image":
        return {"type": "image", "url": f.get("url")}
    return {"type": fill_type, "color": f.get("value")}


def _to_resource_name(name: str, member_id: str = "") -> str:
    """icon/navbar_back → icon_navbar_back (平台资源文件名)。"""
    stem = re.sub(r'\.(png|svg|jpg|jpeg|webp)$', '', name, flags=re.IGNORECASE)
    result = stem.lower().replace("/", "_").replace("-", "_").replace(" ", "_")
    result = re.sub(r'[^a-z0-9_]', '', result)
    result = re.sub(r'_+', '_', result).strip('_')
    if not result and member_id:
        sanitized = re.sub(r'[^a-z0-9]', '', member_id.lower())
        if sanitized:
            result = "ic_" + sanitized
    if result and result[0].isdigit():
        result = "ic_" + result
    return result


def _extract_slice_asset(member: dict, slice_map: dict,
                         text_ancestor_ids: set | None = None) -> dict | None:
    """member 在 slice_map 中有对应导出切图且有本地文件时,返回资产条目。"""
    if member.get("text"):
        return None
    if text_ancestor_ids and member.get("id") in text_ancestor_ids:
        return None
    sl = slice_map.get(member.get("id"))
    if not sl:
        return None
    local = sl.get("local_png") or sl.get("local_svg")
    if not local:
        return None
    name = sl.get("name") or member.get("name") or ""
    f = member.get("frame")
    result = {"id": member["id"], "name": name, "file": local}
    if f:
        result["size"] = {"width": f["width"], "height": f["height"]}
    rn = _to_resource_name(name, member.get("id", ""))
    if rn:
        result["resource_name"] = rn
    return result


def _build_parent_map(artboard: dict) -> tuple[dict, set]:
    """递归建 {child_id: parent_id} + 含 textLayer 子孙的节点 id 集合。"""
    parent_map = {}
    text_ancestor_ids = set()

    def walk(node, parent_id=None):
        nid = node.get("id")
        if not nid:
            return False
        parent_map[nid] = parent_id
        has_text = node.get("type") == "textLayer"
        for child in node.get("layers", []):
            if walk(child, nid):
                has_text = True
        if has_text and node.get("type") != "textLayer":
            text_ancestor_ids.add(nid)
        return has_text

    walk(artboard)
    return parent_map, text_ancestor_ids


def _dedup_ancestor_assets(assets: list[dict], parent_map: dict) -> list[dict]:
    """祖先已在 assets 中时,移除子孙条目。"""
    if len(assets) <= 1 or not parent_map:
        return assets
    asset_ids = {a["id"] for a in assets}
    result = []
    for a in assets:
        cur = parent_map.get(a["id"])
        skip = False
        while cur:
            if cur in asset_ids:
                skip = True
                break
            cur = parent_map.get(cur)
        if not skip:
            result.append(a)
    return result


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
) -> tuple[list[dict], list[dict]]:
    """Split members into content and background layers."""
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
        return members, []
    return content, backgrounds


def build_component_blueprint(component: dict, artboard_frame: dict,
                              slice_map: dict | None = None,
                              text_ancestor_ids: set | None = None) -> dict:
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

    content_members, bg_layers = classify_members(child_members, container_frame)
    content_members = [m for m in content_members if m.get("visible", True)]
    bg_layers = [m for m in bg_layers if m.get("visible", True)]

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

    if slice_map:
        for m in members:
            if m.get("is_system") or not m.get("visible", True):
                continue
            a = _extract_slice_asset(m, slice_map, text_ancestor_ids)
            if a:
                assets.append(a)

    covered_ids = {a["id"] for a in assets}
    for m in members:
        if m.get("is_system") or not m.get("visible", True):
            continue
        if m.get("text") or (text_ancestor_ids and m.get("id") in text_ancestor_ids):
            continue
        ap = m.get("asset_path")
        if ap and m.get("id") and m["id"] not in covered_ids:
            f = m.get("frame")
            entry = {"id": m["id"], "name": m.get("name") or "", "file": ap}
            if f:
                entry["size"] = {"width": f["width"], "height": f["height"]}
            rn = _to_resource_name(m.get("name") or "", m["id"])
            if rn:
                entry["resource_name"] = rn
            assets.append(entry)
            covered_ids.add(m["id"])

    for bg in bg_layers:
        fl = extract_fill(bg)
        if fl:
            fills.insert(0, {"name": bg["name"], "layer": "background", **fl})

    layout = infer_layout(child_frames)
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

    children_widths = []
    if container_frame and len(child_frames) > 1:
        padded = [f for f in child_frames
                  if container_frame["width"] - f["width"] >= 2
                  and f["left"] - container_frame["left"] >= 0
                  and (container_frame["left"] + container_frame["width"])
                      - (f["left"] + f["width"]) >= 0]
        if padded:
            min_ps = min(f["left"] - container_frame["left"] for f in padded)
            min_pe = min((container_frame["left"] + container_frame["width"])
                         - (f["left"] + f["width"]) for f in padded)
        else:
            min_ps = inner_padding.get("start", 0)
            min_pe = inner_padding.get("end", 0)
        for m in content_members:
            f = m.get("frame")
            if f:
                if abs(f["width"] - container_frame["width"]) < 2:
                    cw = "fill"
                else:
                    ps = f["left"] - container_frame["left"]
                    pe = (container_frame["left"] + container_frame["width"]) - (f["left"] + f["width"])
                    if (abs(ps - min_ps) < 4 and abs(pe - min_pe) < 4
                            and f["width"] > container_frame["width"] * 0.5):
                        cw = "fill"
                    else:
                        cw = "fixed"
                children_widths.append({"name": m.get("name") or "", "width": cw})

    spacing = compute_spacing(child_frames, layout)

    container_fill = None
    if (len(members) > 1 and members[0].get("visible", True)
            and members[0].get("type") != "textLayer"):
        container_fill = extract_fill(members[0])

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
    if children_widths:
        result["children_widths"] = children_widths

    return result


def build_blueprint(enriched: dict, design: dict,
                    slices: list | None = None) -> dict:
    artboard = parse_artboard_meta(design)
    slice_map = {s["id"]: s for s in slices if s.get("id")} if slices else {}
    parent_map, text_ancestor_ids = _build_parent_map(design.get("artboard", {}))
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
        bp = build_component_blueprint(c, root_frame, slice_map, text_ancestor_ids)
        component_blueprints.append(bp)

    if parent_map:
        all_assets_flat = []
        for bp in component_blueprints:
            all_assets_flat.extend(bp.get("assets", []))
        if len(all_assets_flat) > 1:
            surviving = _dedup_ancestor_assets(all_assets_flat, parent_map)
            surviving_ids = {a["id"] for a in surviving}
            for bp in component_blueprints:
                if "assets" in bp:
                    bp["assets"] = [a for a in bp["assets"] if a["id"] in surviving_ids]
                    if not bp["assets"]:
                        del bp["assets"]

    all_assets_for_dedup = []
    for bp in component_blueprints:
        all_assets_for_dedup.extend(bp.get("assets", []))
    name_files: dict[str, set] = {}
    for a in all_assets_for_dedup:
        rn = a.get("resource_name", "")
        if rn:
            name_files.setdefault(rn, set()).add(a.get("file", ""))
    collisions = {rn for rn, files in name_files.items() if len(files) > 1}
    if collisions:
        taken = set(name_files)
        file_to_name: dict[str, dict[str, str]] = {}
        for a in all_assets_for_dedup:
            rn = a.get("resource_name", "")
            if rn not in collisions:
                continue
            bucket = file_to_name.setdefault(rn, {})
            f = a.get("file", "")
            if f in bucket:
                a["resource_name"] = bucket[f]
            elif not bucket:
                bucket[f] = rn
            else:
                idx = len(bucket) + 1
                cand = f"{rn}_{idx}"
                while cand in taken:
                    idx += 1
                    cand = f"{rn}_{idx}"
                taken.add(cand)
                bucket[f] = cand
                a["resource_name"] = cand

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
    parser.add_argument("--slices", required=True, help="slices.json path")
    args = parser.parse_args()

    with open(args.enriched) as f:
        enriched = json.load(f)
    with open(args.design) as f:
        design = json.load(f)

    with open(args.slices) as f:
        slices = json.load(f).get("slices", [])

    blueprint = build_blueprint(enriched, design, slices)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)

    m = blueprint["metrics"]
    print(json.dumps({"ok": True, **m}, ensure_ascii=False))


if __name__ == "__main__":
    main()
