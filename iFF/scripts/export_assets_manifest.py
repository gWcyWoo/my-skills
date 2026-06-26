#!/usr/bin/env python3
"""Create node-id keyed asset manifest with bbox and format."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump_json, load_json


def format_of(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return ext or "unknown"


def sidecar_assets(scene_path: Path) -> dict:
    sidecar = scene_path.parent / "assets" / "manifest.json"
    try:
        items = load_json(sidecar)
    except FileNotFoundError:
        return {}
    assets = {}
    for item in items if isinstance(items, list) else []:
        node_id = item.get("layer_id")
        path = item.get("webp_path") or item.get("png_path") or item.get("svg_path")
        if not node_id or not path:
            continue
        assets[node_id] = {
            "path": path,
            "format": format_of(path),
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
    nodes = load_json(scene_path).get("nodes") or []
    manifest = sidecar_assets(scene_path)
    for node in nodes:
        asset = node.get("asset")
        if not asset:
            continue
        manifest[node["id"]] = {
            "path": asset,
            "format": format_of(asset),
            "bbox": node.get("bbox"),
            "node": node["id"],
            "name": node.get("name"),
        }
    dump_json(manifest, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
