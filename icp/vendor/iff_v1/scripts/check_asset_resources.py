#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(manifest: dict, min_bitmap_density: float) -> list[str]:
    failures: list[str] = []
    if not isinstance(manifest, dict):
        return ["assets manifest must be an object keyed by node id"]
    for node_id, record in manifest.items():
        if not isinstance(record, dict):
            failures.append(f"{node_id}: asset record must be an object")
            continue
        logical = record.get("logicalSize")
        if not isinstance(logical, list) or len(logical) != 2 or any(float(value) <= 0 for value in logical):
            failures.append(f"{node_id}: explicit positive logicalSize is required")
        policy = record.get("resourcePolicy")
        asset_format = str(record.get("format") or "").lower()
        if policy == "pure_vector":
            if asset_format != "svg":
                failures.append(f"{node_id}: pure_vector resource must use SVG")
        elif policy == "density_bitmap":
            density = record.get("sourceDensity")
            if not isinstance(density, list) or len(density) != 2:
                failures.append(f"{node_id}: bitmap sourceDensity evidence is required")
            elif min(float(value) for value in density) < min_bitmap_density:
                failures.append(
                    f"{node_id}: low-resolution bitmap density={density}, requires >= {min_bitmap_density}x"
                )
        else:
            failures.append(f"{node_id}: resourcePolicy must be pure_vector or density_bitmap")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-manifest", required=True)
    parser.add_argument("--min-bitmap-density", type=float, default=3.0)
    args = parser.parse_args()
    manifest = json.loads(Path(args.assets_manifest).read_text(encoding="utf-8"))
    failures = validate(manifest, args.min_bitmap_density)
    if failures:
        print(f"FAIL asset resource contract ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"PASS asset resource contract: {len(manifest)} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
