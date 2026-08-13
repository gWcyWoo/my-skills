#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from export_assets_manifest import sidecar_assets


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-vector-assets-") as raw_tmp:
        root = Path(raw_tmp)
        scene = root / "scene.json"
        assets = root / "assets"
        assets.mkdir()
        scene.write_text(json.dumps({"artboard": {"meta": {"sliceScale": 2}}, "nodes": [
            {"id": "icon", "name": "Simple logo", "bbox": [0, 0, 48, 48],
             "asset": "assets/icon.png"},
            {"id": "photo", "name": "Network-like photo", "bbox": [0, 0, 300, 200],
             "asset": "assets/photo.webp"},
        ]}), encoding="utf-8")
        (assets / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h24v24H0z"/></svg>',
            encoding="utf-8",
        )
        (assets / "photo.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="photo.png"/></svg>',
            encoding="utf-8",
        )
        Image.new("RGB", (400, 200), "#335577").save(assets / "photo.webp")
        (assets / "manifest.json").write_text(json.dumps([
            {
                "layer_id": "icon", "layer_name": "Simple logo", "frame": {},
                "svg_path": "assets/icon.svg", "png_path": "assets/icon.png",
            },
            {
                "layer_id": "photo", "layer_name": "Network-like photo", "frame": {},
                "svg_path": "assets/photo.svg", "webp_path": "assets/photo.webp",
                "png_path": "assets/photo.png",
            },
        ]), encoding="utf-8")
        selected = sidecar_assets(scene)
        if selected["icon"]["path"] != "assets/icon.svg":
            raise AssertionError("pure vector icon must prefer SVG")
        if selected["photo"]["path"] != "assets/photo.webp":
            raise AssertionError("SVG containing a bitmap must prefer WebP")
        if selected["icon"].get("resourcePolicy") != "pure_vector":
            raise AssertionError(selected["icon"])
        if selected["photo"].get("resourcePolicy") != "density_bitmap":
            raise AssertionError(selected["photo"])
        out = root / "assets_manifest.json"
        exported = subprocess.run([
            sys.executable, str(Path(__file__).resolve().parent / "export_assets_manifest.py"),
            "--scene", str(scene), "--out", str(out),
        ], text=True, capture_output=True, check=False)
        if exported.returncode != 0:
            raise AssertionError(exported.stderr or exported.stdout)
        final = json.loads(out.read_text(encoding="utf-8"))
        if final["icon"]["path"] != "assets/icon.svg" or final["icon"]["bbox"] != [0, 0, 48, 48]:
            raise AssertionError(final["icon"])
        if final["photo"].get("logicalSize") != [150, 100]:
            raise AssertionError(final["photo"])
        if final["photo"].get("pixelSize") != [400, 200]:
            raise AssertionError(final["photo"])
        if final["photo"].get("sourceDensity") != [round(400 / 150, 3), 2.0]:
            raise AssertionError(final["photo"])
    print("ok asset vector priority selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
