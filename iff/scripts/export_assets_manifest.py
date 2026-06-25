#!/usr/bin/env python3
"""Create node-id keyed asset manifest with bbox and format."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump_json, load_json


def format_of(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return ext or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    nodes = load_json(args.scene).get("nodes") or []
    manifest = {}
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
