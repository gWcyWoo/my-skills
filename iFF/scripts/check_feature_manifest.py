#!/usr/bin/env python3
"""Validate ownership and state isolation in one iFF feature manifest."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def validate_manifest(manifest: dict, feature: str) -> list[str]:
    failures: list[str] = []
    by_canvas: dict[str, list[str]] = defaultdict(list)
    states_by_generated_file: dict[str, list[str]] = defaultdict(list)
    for state, value in (manifest.get("states") or {}).items():
        if not isinstance(value, dict):
            failures.append(f"{feature}: {state} must be an object")
            continue
        canvas = value.get("canvasPath") if isinstance(value, dict) else None
        if not canvas:
            failures.append(f"{feature}: {state} has no canvasPath")
        else:
            by_canvas[str(canvas)].append(str(state))
        generated_files = value.get("generatedFiles")
        if not isinstance(generated_files, list) or not generated_files:
            failures.append(
                f"{feature}: {state} generatedFiles must be a non-empty list"
            )
        else:
            for path in generated_files:
                states_by_generated_file[str(path)].append(str(state))
    for canvas, states in sorted(by_canvas.items()):
        if len(states) > 1:
            failures.append(f"{feature}: states share canvasPath {canvas}: {', '.join(states)}")
    for path, states in sorted(states_by_generated_file.items()):
        if len(states) > 1:
            failures.append(
                f"{feature}: states share generated file {path}: {', '.join(states)}"
            )

    protected = {str(path) for path in manifest.get("protectedFiles") or []}
    generated = {str(path) for path in manifest.get("generatedFiles") or []}
    for path in sorted(protected & generated):
        failures.append(f"{feature}: file is both protected and generated: {path}")
    for path in sorted(protected & set(states_by_generated_file)):
        for state in states_by_generated_file[path]:
            failures.append(f"{feature}: {state} generates protected file: {path}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--manifest-root")
    args = parser.parse_args()

    paths: list[Path] = []
    if args.manifest:
        paths.append(Path(args.manifest))
    if args.manifest_root:
        paths.extend(sorted(Path(args.manifest_root).glob("*.json")))
    if not paths:
        print("ERROR: provide --manifest or --manifest-root")
        return 1

    failures: list[str] = []
    routes: dict[str, list[str]] = defaultdict(list)
    manifests: list[dict] = []
    for manifest_path in paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifests.append(manifest)
        feature = str(manifest.get("featureId") or manifest_path.stem)
        route = manifest.get("route")
        if route:
            routes[str(route)].append(feature)

        failures.extend(validate_manifest(manifest, feature))

    for route, features in sorted(routes.items()):
        if len(features) > 1:
            failures.append(f"route {route} is claimed by multiple features: {', '.join(features)}")
    if failures:
        print("FAIL feature manifest:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"ok feature manifest: {len(manifests)} feature(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
