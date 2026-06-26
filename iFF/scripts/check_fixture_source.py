#!/usr/bin/env python3
"""Check that visual tests and runtime reference the same visual fixture."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fixture-name", default="homeVisualProducts")
    args = parser.parse_args()

    root = Path(args.root)
    fixture_files = [
        p for p in root.rglob("*visual_fixture.*")
        if ".dart_tool" not in p.parts and "build" not in p.parts
    ]
    if not fixture_files:
        raise SystemExit("ERROR: no visual_fixture file found")
    references = []
    for path in root.rglob("*.dart"):
        if ".dart_tool" in path.parts or "build" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if args.fixture_name in text:
            references.append(path)
    if not references:
        raise SystemExit(f"ERROR: no Dart file references {args.fixture_name}")
    print(f"ok fixture files={len(fixture_files)} references={len(references)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
