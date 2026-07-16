#!/usr/bin/env python3
"""Compile Lanhu-wrapped Figma JSON into the iFF scene contract."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import colors_of, dump_json, load_json


def figma_root(raw: dict[str, Any]) -> dict[str, Any]:
    figma = raw.get("figma_json") if isinstance(raw, dict) else None
    if not isinstance(figma, dict):
        raise SystemExit("ERROR: raw.json missing figma_json")
    artboard = figma.get("artboard")
    if not isinstance(artboard, dict):
        raise SystemExit("ERROR: figma_json missing artboard")
    return figma


def asset_lookup(manifest: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(manifest, list):
        for item in manifest:
            if not isinstance(item, dict):
                continue
            node_id = item.get("layer_id") or item.get("node") or item.get("id")
            path = item.get("webp_path") or item.get("png_path") or item.get("svg_path") or item.get("path")
            if node_id and path:
                out[str(node_id)] = {
                    "path": path,
                    "png_path": item.get("png_path"),
                    "svg_path": item.get("svg_path"),
                    "webp_path": item.get("webp_path"),
                    "frame": item.get("frame") or {},
                    "source": "assets/manifest.json",
                }
    elif isinstance(manifest, dict):
        for node_id, item in manifest.items():
            if isinstance(item, str):
                out[str(node_id)] = {"path": item, "source": "assets/manifest.json"}
            elif isinstance(item, dict):
                path = item.get("path") or item.get("asset") or item.get("file")
                if path:
                    out[str(node_id)] = dict(item, path=path, source=item.get("source") or "assets/manifest.json")
    return out


def num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bbox_of(layer: dict[str, Any]) -> list[float] | None:
    rotated_real_frame = layer.get("realFrame") if abs(num(layer.get("rotation"))) > 0.01 else None
    frame = rotated_real_frame or layer.get("frame") or layer.get("absoluteBoundingBox") or layer.get("bounds") or {}
    if not isinstance(frame, dict):
        return None
    left = frame.get("left", frame.get("x"))
    top = frame.get("top", frame.get("y"))
    width = frame.get("width", frame.get("w"))
    height = frame.get("height", frame.get("h"))
    if left is None or top is None or width is None or height is None:
        return None
    return [num(left), num(top), num(width), num(height)]


def radius_of(layer: dict[str, Any]) -> Any:
    paths = layer.get("paths") or []
    if paths and isinstance(paths[0], dict) and paths[0].get("radius") not in (None, {}, []):
        return paths[0].get("radius")
    return layer.get("radius")


def style_of(layer: dict[str, Any]) -> dict[str, Any]:
    style = layer.get("style") or {}
    return style if isinstance(style, dict) else {}


def text_payload(layer: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    text = layer.get("text") or {}
    if not isinstance(text, dict):
        return None, {}
    style = text.get("style") or {}
    if not isinstance(style, dict):
        style = {}
    content = style.get("content") or text.get("value")
    return (str(content) if content not in (None, "") else None), style


def fill_buckets(fills: Any) -> tuple[list[Any], list[Any], list[Any]]:
    solid: list[Any] = []
    gradient: list[Any] = []
    image: list[Any] = []
    if not isinstance(fills, list):
        return solid, gradient, image
    for fill in fills:
        if not isinstance(fill, dict):
            solid.append(fill)
            continue
        fill_type = str(fill.get("type") or fill.get("fillType") or "").lower()
        if "gradient" in fill_type or fill.get("gradient") or fill.get("gradientStops"):
            gradient.append(fill)
        elif "image" in fill_type or fill.get("imageRef") or fill.get("imageUrl") or fill.get("scaleMode"):
            image.append(fill)
        else:
            solid.append(fill)
    return solid, gradient, image


def font_payload(text_style: dict[str, Any]) -> dict[str, Any]:
    font = text_style.get("font") or {}
    if not isinstance(font, dict):
        return {}
    out: dict[str, Any] = {}
    mapping = {
        "fontSize": "size",
        "weight": "fontWeight",
        "lineHeight": "lineHeight",
        "letterSpacing": "letterSpacing",
        "fontFamily": "name",
        "postScriptName": "postScriptName",
        "align": "align",
        "verticalAlignment": "verticalAlignment",
        "paragraphSpacing": "paragraphSpacing",
        "fontStyle": "fontStyle",
        "italic": "italic",
        "underline": "underline",
        "linethrough": "linethrough",
    }
    for out_key, in_key in mapping.items():
        value = font.get(in_key)
        if value not in (None, {}, []):
            out[out_key] = value
    return out


def layer_asset(layer: dict[str, Any], assets: dict[str, dict[str, Any]]) -> str | None:
    node_id = str(layer.get("id") or "")
    if node_id in assets:
        return str(assets[node_id]["path"])
    image = layer.get("image") or {}
    if isinstance(image, dict):
        for key in ("imageUrl", "svgUrl"):
            value = image.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def normalize_type(value: Any) -> str:
    return str(value or "groupLayer").lower()


def shape_type(layer: dict[str, Any]) -> str | None:
    paths = layer.get("paths") or []
    if paths and isinstance(paths[0], dict) and paths[0].get("type"):
        return str(paths[0]["type"])
    return None


def walk_layers(
    layer: dict[str, Any],
    *,
    assets: dict[str, dict[str, Any]],
    parent: str | None,
    parent_path: str,
    depth: int,
    state: dict[str, int],
    inherited_visible: bool,
) -> list[dict[str, Any]]:
    node_id = str(layer.get("id") or f"missing_id_{state['z']}")
    name = str(layer.get("name") or "")
    path = f"{parent_path}/{name}" if parent_path else name
    bbox = bbox_of(layer)
    if bbox is None:
        return []
    raw_type = str(layer.get("type") or "")
    node_type = normalize_type(raw_type)
    visible = bool(layer.get("visible", True))
    effective_visible = inherited_visible and visible and num(layer.get("opacity", 1), 1.0) > 0
    style = style_of(layer)
    text, text_style = text_payload(layer)
    asset = layer_asset(layer, assets)
    image = layer.get("image") or {}
    exportable = bool(
        layer.get("hasExportImage")
        or layer.get("hasExportDDSImage")
        or (isinstance(image, dict) and (image.get("imageUrl") or image.get("svgUrl")))
        or asset
    )

    fills_source: list[Any] = []
    fills_source.extend(style.get("fills") or [])
    if text_style.get("color"):
        fills_source.append(text_style["color"])
    solid_fills, gradient_fills, image_fills = fill_buckets(style.get("fills") or [])
    node = {
        "id": node_id,
        "name": name,
        "path": path,
        "parent": parent,
        "children": [str(child.get("id") or "") for child in layer.get("layers") or [] if isinstance(child, dict)],
        "type": node_type,
        "figmaType": raw_type,
        "bbox": bbox,
        "z": state["z"],
        "depth": depth,
        "visible": visible,
        "effectiveVisible": effective_visible,
        "opacity": layer.get("opacity", 1),
        "rotation": layer.get("rotation", 0),
        "blendMode": layer.get("blendMode"),
        "fills": colors_of(fills_source),
        "rawFills": style.get("fills") or [],
        "solidFills": solid_fills,
        "gradientFills": gradient_fills,
        "imageFills": image_fills,
        "border": style.get("borders") or style.get("strokes") or [],
        "radius": radius_of(layer),
        "shadow": style.get("shadows") or layer.get("effects") or [],
        "effects": layer.get("effects") or style.get("effects") or [],
        "blur": style.get("blurs") or [],
        "mask": bool(layer.get("isMask", False)),
        "maskType": layer.get("maskType"),
        "clipsContent": bool(layer.get("clipsContent", False)),
        "constraints": layer.get("constraints") or {},
        "layout": {
            key: layer.get(key)
            for key in ("layoutMode", "primaryAxisSizingMode", "counterAxisSizingMode", "itemSpacing", "paddingLeft", "paddingRight", "paddingTop", "paddingBottom")
            if layer.get(key) is not None
        },
        "shapeType": shape_type(layer),
        "exportable": exportable,
        "exportSettings": layer.get("exportSettings") or layer.get("exportOptions") or [],
        "componentId": layer.get("componentId") or layer.get("component_id"),
        "componentProperties": layer.get("componentProperties") or {},
        "variantProperties": layer.get("variantProperties") or {},
        "isInstance": node_type in {"instance", "instancelayer"} or bool(layer.get("componentId")),
        "absoluteTransform": layer.get("absoluteTransform") or layer.get("transform"),
        "relativeTransform": layer.get("relativeTransform"),
        "image": image if isinstance(image, dict) else {},
    }
    if text is not None:
        node["text"] = text
        node.update(font_payload(text_style))
        node["textStyle"] = text_style
        styles = (layer.get("text") or {}).get("styles")
        if styles:
            node["textRuns"] = styles
    if asset:
        node["asset"] = asset
    state["z"] += 1
    nodes = [node]
    for child in layer.get("layers") or []:
        if isinstance(child, dict):
            nodes.extend(
                walk_layers(
                    child,
                    assets=assets,
                    parent=node_id,
                    parent_path=path,
                    depth=depth + 1,
                    state=state,
                    inherited_visible=effective_visible,
                )
            )
    node["children"] = [child_id for child_id in node["children"] if child_id]
    return nodes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = load_json(args.raw)
    try:
        manifest = load_json(args.assets)
    except FileNotFoundError:
        manifest = {}
    figma = figma_root(raw)
    artboard = figma["artboard"]
    assets = asset_lookup(manifest)
    state = {"z": 0}
    nodes = walk_layers(artboard, assets=assets, parent=None, parent_path="", depth=0, state=state, inherited_visible=True)
    if not nodes:
        raise SystemExit("ERROR: no Figma nodes with frame found")
    artboard_bbox = nodes[0]["bbox"]
    dump_json(
        {
            "sourceSchema": "lanhu_figma_json",
            "designName": raw.get("design_name"),
            "designId": raw.get("design_id"),
            "versionId": raw.get("version_id"),
            "lanhuUrl": raw.get("lanhu_url"),
            "artboard": {
                "id": nodes[0]["id"],
                "name": nodes[0]["name"],
                "bbox": artboard_bbox,
                "width": artboard_bbox[2],
                "height": artboard_bbox[3],
                "meta": figma.get("meta") or {},
            },
            "nodes": nodes,
        },
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
