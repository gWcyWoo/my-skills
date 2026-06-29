#!/usr/bin/env python3
"""Decide how every design node must be rendered in Flutter."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump_json, load_json


VISIBLE_IMPLEMENTATIONS = {
    "asset",
    "gradient_shape",
    "image",
    "image_fill",
    "image_png",
    "image_webp",
    "oval_shape",
    "shape",
    "shape_container",
    "svg",
    "text",
    "vector_shape",
}


def asset_strategy(asset_path: str) -> str:
    ext = Path(asset_path).suffix.lower()
    if ext == ".webp":
        return "image_webp"
    if ext == ".png":
        return "image_png"
    if ext == ".svg":
        return "svg"
    return "asset"


def node_type(node: dict) -> str:
    return str(node.get("type") or "").lower()


def shape_type(node: dict) -> str:
    return str(node.get("shapeType") or "").lower()


def is_group(node: dict) -> bool:
    return node_type(node) in {"group", "grouplayer", "frame", "framelayer", "component", "componentlayer", "instance", "instancelayer", "artboard"}


def is_shape(node: dict) -> bool:
    return node_type(node) in {"shape", "shapelayer", "rectangle", "rect", "ellipse", "vector", "vectorlayer", "path", "line", "polygon", "star"}


def has_gradient(node: dict) -> bool:
    return bool(node.get("gradientFills"))


def has_image_fill(node: dict) -> bool:
    image = node.get("image") or {}
    return bool(node.get("imageFills") or (isinstance(image, dict) and (image.get("imageUrl") or image.get("svgUrl"))))


def has_container_visual(node: dict) -> bool:
    return bool(
        node.get("fills")
        or node.get("rawFills")
        or node.get("border")
        or node.get("shadow")
        or node.get("effects")
        or node.get("radius") is not None
    )


def has_complex_vector(node: dict) -> bool:
    if has_gradient(node) or has_image_fill(node):
        return True
    if node.get("mask") or node.get("maskType"):
        return True
    if node.get("blur"):
        return True
    if node.get("effects") and node_type(node) in {"vector", "vectorlayer", "shape", "shapelayer", "path"}:
        return True
    return shape_type(node) in {"vector", "path", "star", "polygon"}


def has_visual_signal(node: dict) -> bool:
    if node.get("effectiveVisible") is False or node.get("visible") is False:
        return False
    if node.get("type") == "artboard":
        return False
    return bool(
        node.get("text")
        or node.get("asset")
        or node.get("fills")
        or node.get("rawFills")
        or node.get("gradientFills")
        or node.get("imageFills")
        or node.get("border")
        or node.get("shadow")
        or node.get("effects")
        or node.get("radius") is not None
        or node.get("exportable")
        or node.get("mask")
    )


def implementation_for(node: dict, text_layer_wrappers: set[str], covered_by_asset: set[str]) -> str:
    name = f"{node.get('name', '')} {node.get('text', '')}".lower()
    if node.get("effectiveVisible") is False or node.get("visible") is False:
        return "hidden"
    if node.get("id") in covered_by_asset:
        return "covered_by_asset"
    if node.get("id") in text_layer_wrappers:
        return "covered_by_text"
    if node.get("text"):
        return "text"
    if node.get("mask"):
        return "mask_group"
    if node.get("clipsContent") and node.get("children"):
        return "clip_group"
    if has_image_fill(node):
        return "image_fill"
    if has_gradient(node):
        return "gradient_shape"
    if has_complex_vector(node):
        return "vector_shape"
    current_shape_type = shape_type(node)
    if str(node.get("name", "")).lower().startswith("ellipse") or current_shape_type in {"ellipse", "oval"}:
        return "oval_shape"
    if "button" in name or "input" in name or "field" in name:
        return "interactive_hit_area"
    if node.get("asset"):
        return asset_strategy(str(node["asset"]))
    if is_group(node) and has_container_visual(node):
        return "shape_container"
    if not has_visual_signal(node):
        return "container"
    return "shape"


def collect_descendants(node_id: str, by_id: dict[str, dict], seen: set[str] | None = None) -> set[str]:
    seen = seen or set()
    node = by_id.get(node_id) or {}
    for child_id in node.get("children") or []:
        if child_id in seen:
            continue
        seen.add(child_id)
        seen.update(collect_descendants(child_id, by_id, seen))
    return seen


def render_reason(node: dict, mode: str, covered_by_asset: dict[str, str]) -> str:
    if mode == "hidden":
        return "node is hidden or fully transparent"
    if mode == "covered_by_asset":
        return f"descendant is rendered by atomic asset {covered_by_asset.get(str(node.get('id')), '')}"
    if mode == "covered_by_text":
        return "textLayer wrapper is represented by its child text node"
    if mode == "image_fill":
        return "node has Figma image fill"
    if mode == "gradient_shape":
        return "node has Figma gradient fill"
    if mode == "vector_shape":
        return "node has complex vector/mask/effect semantics"
    if mode == "shape_container":
        return "Figma group/frame has visible fill, border, radius, or shadow"
    return "direct render node"


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

    by_id = {node["id"]: node for node in nodes}
    asset_ids = set(assets.keys()) if isinstance(assets, dict) else set()
    covered_by_asset: dict[str, str] = {}
    for asset_id in asset_ids:
        for descendant_id in collect_descendants(asset_id, by_id):
            if descendant_id != asset_id:
                covered_by_asset[descendant_id] = asset_id

    text_layer_wrappers = {
        node["id"]
        for node in nodes
        if node.get("type") == "textlayer"
        and any((by_id.get(child_id) or {}).get("text") for child_id in node.get("children") or [])
    }

    max_area = max(n["bbox"][2] * n["bbox"][3] for n in nodes)
    plan = {
        "nodes": {},
        "assetStrategy": "webP > png; svg only for simple vectors",
        "visibleImplementations": sorted(VISIBLE_IMPLEMENTATIONS),
    }
    errors = []
    for node in nodes:
        bbox = node["bbox"]
        manifest_asset = assets.get(node["id"]) if isinstance(assets, dict) else None
        asset_path = node.get("asset") or (manifest_asset.get("path") if isinstance(manifest_asset, dict) else None)
        mode = asset_strategy(str(asset_path)) if asset_path else implementation_for(node, text_layer_wrappers, set(covered_by_asset))
        required = mode in VISIBLE_IMPLEMENTATIONS
        # 1D 描边分隔线(Figma Line / 零厚度 shapeLayer)bbox 的宽或高为 0。作为可见节点
        # 必须有正的厚度才能被坐标画布渲染并通过 render_plan 的正 bbox 校验,否则一条设计
        # 里真实存在的分隔线会被判为非法零尺寸。用其描边宽度(缺省 1 设计px)补齐缺失维度,
        # 既忠实于"1px 细线"的设计语义,又不影响其它有正尺寸的节点。
        if required and isinstance(bbox, list) and len(bbox) == 4 and (bbox[2] <= 0 or bbox[3] <= 0):
            stroke = 1.0
            for stroke_spec in (node.get("border") or []):
                if isinstance(stroke_spec, dict):
                    try:
                        stroke = max(stroke, float(stroke_spec.get("width") or 0))
                    except (TypeError, ValueError):
                        pass
            bbox = list(bbox)
            if bbox[2] <= 0:
                bbox[2] = stroke
            if bbox[3] <= 0:
                bbox[3] = stroke
        if node.get("exportable") and not asset_path:
            errors.append(f"exportable node missing asset path: {node['id']}")
        if mode.startswith("image") or mode == "svg" or mode == "asset":
            if not asset_path:
                if mode != "image_fill":
                    errors.append(f"asset node missing asset path: {node['id']}")
        if asset_path and bbox[2] * bbox[3] >= max_area * 0.98:
            errors.append(f"full-artboard asset is forbidden: {node['id']}")
        plan["nodes"][node["id"]] = {
            "name": node.get("name"),
            "bbox": bbox,
            "implementation": mode,
            "asset": asset_path,
            "text": node.get("text"),
            "fontSize": node.get("fontSize"),
            "weight": node.get("weight"),
            "lineHeight": node.get("lineHeight"),
            "letterSpacing": node.get("letterSpacing"),
            "align": node.get("align"),
            "verticalAlignment": node.get("verticalAlignment"),
            "textRuns": node.get("textRuns") or [],
            "rotation": node.get("rotation") or 0,
            "absoluteTransform": node.get("absoluteTransform"),
            "fills": node.get("fills") or [],
            "rawFills": node.get("rawFills") or [],
            "solidFills": node.get("solidFills") or [],
            "gradientFills": node.get("gradientFills") or [],
            "imageFills": node.get("imageFills") or [],
            "border": node.get("border") or [],
            "radius": node.get("radius"),
            "shadow": node.get("shadow") or [],
            "effects": node.get("effects") or [],
            "opacity": node.get("opacity", 1),
            "path": node.get("path"),
            "parent": node.get("parent"),
            "children": node.get("children") or [],
            "figmaType": node.get("figmaType"),
            "shapeType": node.get("shapeType"),
            "visible": bool(node.get("effectiveVisible", True) and node.get("visible", True)),
            "required": required,
            "renderMode": "absolute_positioned" if required else None,
            "coveredBy": covered_by_asset.get(node["id"]) if mode == "covered_by_asset" else None,
            "reason": render_reason(node, mode, covered_by_asset),
            "sourceSchema": scene.get("sourceSchema"),
            "widgetTraceRequired": True,
        }

    mapped = set()
    for component in layout.values():
        for widget in component.get("widgets", {}).values():
            if widget.get("node"):
                mapped.add(widget["node"])
    missing_mappings = [
        node["id"] for node in nodes
        if plan["nodes"][node["id"]]["required"] and node["bbox"][2] * node["bbox"][3] >= 64 and node["id"] not in mapped
    ]
    if missing_mappings:
        errors.append("nodes missing layout widget mapping: " + ", ".join(missing_mappings[:20]))
    if errors:
        raise SystemExit("ERROR: render plan failed:\n" + "\n".join(errors))
    dump_json(plan, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
