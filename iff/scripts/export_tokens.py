#!/usr/bin/env python3
"""Export deterministic visual tokens from scene.json."""

from __future__ import annotations

import argparse

from common import dump_json, load_json


def sorted_nums(values):
    flat = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, dict):
            # radius may be a per-corner dict {topLeft,topRight,bottomLeft,bottomRight}
            flat.extend(x for x in v.values() if isinstance(x, (int, float)))
        elif isinstance(v, (int, float)):
            flat.append(v)
    return sorted(set(flat))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    nodes = load_json(args.scene).get("nodes") or []
    colors = []
    font_sizes = []
    radii = []
    borders = []
    shadows = []
    for node in nodes:
        colors.extend(node.get("fills") or [])
        if node.get("fontSize") is not None:
            font_sizes.append(node.get("fontSize"))
        if node.get("radius") is not None:
            radii.append(node.get("radius"))
        if node.get("border"):
            borders.append(node["border"])
        shadows.extend(node.get("shadow") or [])
    tokens = {
        "colors": sorted(set(colors)),
        "fontSizes": sorted_nums(font_sizes),
        "radii": sorted_nums(radii),
        "borders": borders,
        "shadows": shadows,
    }
    dump_json(tokens, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
