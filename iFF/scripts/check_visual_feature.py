#!/usr/bin/env python3
"""Aggregate current per-board visual gates for one feature manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_visual_board import validate_board


def validate_feature(spec_root: Path, manifest: dict) -> list[str]:
    failures: list[str] = []
    states = manifest.get("states") or {}
    if not states:
        failures.append("feature manifest has no states")

    for state, value in sorted(states.items()):
        board_name = value.get("board") if isinstance(value, dict) else None
        board = spec_root / str(board_name or state)
        if not board.is_dir():
            failures.append(f"{state}: board directory missing: {board.name}")
            continue
        for failure in validate_board(board):
            failures.append(f"{state}: {failure}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    spec_root = Path(args.spec_root).expanduser().resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    failures = validate_feature(spec_root, manifest)
    states = manifest.get("states") or {}

    if failures:
        print(f"FAIL visual feature {manifest.get('featureId') or spec_root.name} ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"ok visual feature: {manifest.get('featureId') or spec_root.name} ({len(states)} state(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
