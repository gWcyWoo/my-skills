#!/usr/bin/env python3
"""Fail if required iFF deterministic pipeline scripts are missing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REQUIRED = [
    "classify_design.py",
    "fetch.py",
    "write.py",
    "download_cover.py",
    "export_scene.py",
    "export_tokens.py",
    "export_assets_manifest.py",
    "group_layout.py",
    "make_layout_contract.py",
    "make_render_plan.py",
    "make_visual_fixture.py",
    "parse_interactions.py",
    "make_interaction_tests_plan.py",
    "copy_assets.py",
    "update_pubspec_assets.py",
    "capture_runtime_screenshot.py",
    "visual_diff.py",
    "check_visual_manifest.py",
    "check_fixture_source.py",
    "check_render_plan.py",
    "check_interaction_coverage.py",
    "make_worker_prompt.py",
    "check_worker_compliance.py",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the iff skill directory.",
    )
    args = parser.parse_args()

    scripts_dir = Path(args.skill_dir).expanduser().resolve() / "scripts"
    missing = [name for name in REQUIRED if not (scripts_dir / name).is_file()]
    outside = [path for path in scripts_dir.glob("*.py") if path.parent != scripts_dir]

    if missing:
        print("missing required iff scripts:", file=sys.stderr)
        for name in missing:
            print(f"- {scripts_dir / name}", file=sys.stderr)
    if outside:
        print("unexpected script path outside iff/scripts:", file=sys.stderr)
        for path in outside:
            print(f"- {path}", file=sys.stderr)
    if missing or outside:
        return 1

    print(f"ok {len(REQUIRED)} scripts in {scripts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
