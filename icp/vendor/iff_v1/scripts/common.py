#!/usr/bin/env python3
"""Shared deterministic helpers for the iFF visual pipeline."""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct
from typing import Any, Iterable


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(data: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def png_size(path: str | Path) -> tuple[int, int]:
    data = Path(path).read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG file: {path}")
    return struct.unpack(">II", data[16:24])


def walk_json(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from walk_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from walk_json(child, child_path)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _num_from_keys(obj: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in obj:
            value = _num(obj[key])
            if value is not None:
                return value
    return None


def bbox_of(node: Any) -> list[float] | None:
    if not isinstance(node, dict):
        return None
    direct = node.get("bbox")
    if isinstance(direct, list) and len(direct) == 4:
        nums = [_num(v) for v in direct]
        if all(v is not None for v in nums):
            x, y, w, h = [float(v) for v in nums]
            return [x, y, w, h]

    for key in ("absoluteBoundingBox", "absoluteRenderBounds", "bounds", "frame", "rect"):
        box = node.get(key)
        if isinstance(box, dict):
            x = _num_from_keys(box, "x", "left", "l")
            y = _num_from_keys(box, "y", "top", "t")
            w = _num_from_keys(box, "width", "w")
            h = _num_from_keys(box, "height", "h")
            if None not in (x, y, w, h):
                return [float(x), float(y), float(w), float(h)]

    x = _num_from_keys(node, "x", "left")
    y = _num_from_keys(node, "y", "top")
    w = _num_from_keys(node, "width", "w")
    h = _num_from_keys(node, "height", "h")
    if None not in (x, y, w, h):
        return [float(x), float(y), float(w), float(h)]
    return None


def node_id(node: dict[str, Any], fallback: str) -> str:
    for key in ("id", "node_id", "nodeId", "guid"):
        value = node.get(key)
        if value is not None and str(value):
            return str(value)
    return fallback


def node_name(node: dict[str, Any]) -> str:
    for key in ("name", "title", "label"):
        value = node.get(key)
        if value is not None:
            return str(value)
    return ""


def node_type(node: dict[str, Any]) -> str:
    for key in ("type", "nodeType", "class", "kind"):
        value = node.get(key)
        if value is not None:
            return str(value).lower()
    if text_of(node):
        return "text"
    return "group"


def text_of(node: dict[str, Any]) -> str | None:
    for key in ("text", "characters", "content", "value"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _hex_from_rgb(r: float, g: float, b: float) -> str:
    vals = []
    for v in (r, g, b):
        if 0 <= v <= 1:
            v = v * 255
        vals.append(max(0, min(255, int(round(v)))))
    return "#{:02X}{:02X}{:02X}".format(*vals)


def colors_of(value: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(color: str) -> None:
        if color not in seen:
            seen.add(color)
            found.append(color)

    for _, item in walk_json(value):
        if isinstance(item, str):
            text = item.strip()
            if len(text) in (4, 7) and text.startswith("#"):
                add(text.upper())
        elif isinstance(item, dict):
            r = _num_from_keys(item, "r", "red")
            g = _num_from_keys(item, "g", "green")
            b = _num_from_keys(item, "b", "blue")
            if None not in (r, g, b):
                add(_hex_from_rgb(float(r), float(g), float(b)))
    return found


def radius_of(node: dict[str, Any]) -> float | None:
    return _num_from_keys(node, "radius", "borderRadius", "cornerRadius")


def border_of(node: dict[str, Any]) -> dict[str, Any] | None:
    width = _num_from_keys(node, "borderWidth", "strokeWeight", "strokeWidth")
    colors = colors_of(node.get("border") or node.get("stroke") or node.get("strokes") or {})
    if width is None and not colors:
        return None
    return {"color": colors[0] if colors else None, "width": width or 0}


def font_of(node: dict[str, Any]) -> dict[str, Any]:
    font: dict[str, Any] = {}
    for out_key, keys in {
        "fontSize": ("fontSize", "font_size", "size"),
        "weight": ("weight", "fontWeight", "font_weight"),
        "lineHeight": ("lineHeight", "line_height", "lineHeightPx"),
    }.items():
        value = _num_from_keys(node, *keys)
        if value is not None:
            font[out_key] = value
    return font


def shadows_of(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = node.get("shadow") or node.get("shadows") or node.get("effects") or []
    if isinstance(value, dict):
        value = [value]
    shadows = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            colors = colors_of(item)
            shadow = {
                "color": colors[0] if colors else None,
                "x": _num_from_keys(item, "x", "offsetX") or 0,
                "y": _num_from_keys(item, "y", "offsetY") or 0,
                "blur": _num_from_keys(item, "blur", "radius") or 0,
                "spread": _num_from_keys(item, "spread") or 0,
            }
            shadows.append(shadow)
    return shadows


def asset_ref(node: dict[str, Any], manifest: Any | None = None) -> str | None:
    for key in ("asset", "asset_path", "assetPath", "image", "image_url", "url", "src"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    nid = node_id(node, "")
    if isinstance(manifest, dict):
        value = manifest.get(nid)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("path", "asset", "file"):
                if isinstance(value.get(key), str):
                    return value[key]
    return None


def collect_scene_nodes(raw: Any, assets_manifest: Any | None = None) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for path, value in walk_json(raw):
        if not isinstance(value, dict):
            continue
        bbox = bbox_of(value)
        if not bbox:
            continue
        nid = node_id(value, path or f"node_{len(nodes)}")
        text = text_of(value)
        colors = colors_of(value.get("fills") or value.get("fill") or value)
        node: dict[str, Any] = {
            "id": nid,
            "name": node_name(value),
            "type": node_type(value),
            "bbox": bbox,
            "z": len(nodes),
            "fills": colors,
            "radius": radius_of(value),
            "border": border_of(value),
            "shadow": shadows_of(value),
            "children": [],
        }
        if text:
            node["text"] = text
            node.update(font_of(value))
        asset = asset_ref(value, assets_manifest)
        if asset:
            node["asset"] = asset
        nodes.append(node)
    return nodes


def intersects(a: list[float], b: list[float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
