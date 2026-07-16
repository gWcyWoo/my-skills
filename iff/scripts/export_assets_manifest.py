#!/usr/bin/env python3
"""Create node-id keyed asset manifest with bbox and format."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from common import dump_json, load_json


def format_of(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return ext or "unknown"


def is_pure_vector_svg(scene_path: Path, relative_path: str | None) -> bool:
    if not relative_path or not relative_path.lower().endswith(".svg"):
        return False
    svg_path = scene_path.parent / relative_path
    try:
        source = svg_path.read_text(encoding="utf-8").lower()
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return False
    return "<svg" in source and "<image" not in source and "<foreignobject" not in source


def sidecar_assets(scene_path: Path) -> dict:
    sidecar = scene_path.parent / "assets" / "manifest.json"
    try:
        items = load_json(sidecar)
    except FileNotFoundError:
        return {}
    assets = {}
    for item in items if isinstance(items, list) else []:
        node_id = item.get("layer_id")
        svg_path = item.get("svg_path")
        pure_vector = is_pure_vector_svg(scene_path, svg_path)
        path = svg_path if pure_vector else (
            item.get("webp_path") or item.get("png_path") or svg_path
        )
        if not node_id or not path:
            continue
        assets[node_id] = {
            "path": path,
            "format": format_of(path),
            "resourcePolicy": "pure_vector" if pure_vector else "density_bitmap",
            "availableVariants": {
                key.removesuffix("_path"): item.get(key)
                for key in ("svg_path", "webp_path", "png_path") if item.get(key)
            },
            "bbox": [
                item.get("frame", {}).get("left"),
                item.get("frame", {}).get("top"),
                item.get("frame", {}).get("width"),
                item.get("frame", {}).get("height"),
            ],
            "node": node_id,
            "name": item.get("layer_name"),
            "source": "assets/manifest.json",
        }
    return assets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scene_path = Path(args.scene)
    scene = load_json(scene_path)
    nodes = scene.get("nodes") or []
    design_pixel_scale = float(((scene.get("artboard") or {}).get("meta") or {}).get("sliceScale") or 1)
    if design_pixel_scale <= 0:
        raise SystemExit("ERROR: artboard.meta.sliceScale must be > 0")
    manifest = sidecar_assets(scene_path)
    for node in nodes:
        asset = node.get("asset")
        if not asset:
            continue
        existing = manifest.get(node["id"])
        if existing:
            existing.update({"bbox": node.get("bbox"), "node": node["id"], "name": node.get("name")})
        else:
            manifest[node["id"]] = {
                "path": asset,
                "format": format_of(asset),
                "bbox": node.get("bbox"),
                "node": node["id"],
                "name": node.get("name"),
                "resourcePolicy": "density_bitmap" if format_of(asset) != "svg" else "unverified_svg",
            }
    for record in manifest.values():
        bbox = record.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            logical_width = float(bbox[2]) / design_pixel_scale
            logical_height = float(bbox[3]) / design_pixel_scale
            record["logicalSize"] = [round(logical_width, 3), round(logical_height, 3)]
            record["designPixelScale"] = design_pixel_scale
            if record.get("format") in {"png", "webp", "jpg", "jpeg"}:
                asset_path = scene_path.parent / str(record.get("path"))
                try:
                    with Image.open(asset_path) as image:
                        pixel_width, pixel_height = image.size
                    record["pixelSize"] = [pixel_width, pixel_height]
                    record["sourceDensity"] = [
                        round(pixel_width / logical_width, 3) if logical_width > 0 else 0,
                        round(pixel_height / logical_height, 3) if logical_height > 0 else 0,
                    ]
                except (FileNotFoundError, OSError):
                    record["pixelSize"] = None
                    record["sourceDensity"] = None
    dump_json(manifest, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
