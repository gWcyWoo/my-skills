#!/usr/bin/env python3
"""Validate that an iFF worker loaded the current skill rules."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from common import load_json


def digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    verify_script = skill_dir / "scripts" / "verify_pipeline_scripts.py"
    manifest = load_json(args.manifest)

    errors = []
    expected = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "verify_pipeline_scripts_sha256": digest(verify_script),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"{key} mismatch")
    loaded = set(manifest.get("loaded_files") or [])
    for path in (str(skill_md), str(test_rules)):
        if path not in loaded:
            errors.append(f"missing loaded file proof: {path}")
    if manifest.get("pipeline_scripts_ok") is not True:
        errors.append("pipeline_scripts_ok must be true")
    if manifest.get("worker_bootstrap_version") != "IFF_WORKER_BOOTSTRAP v1":
        errors.append("worker_bootstrap_version must be IFF_WORKER_BOOTSTRAP v1")
    if errors:
        raise SystemExit("ERROR: worker compliance failed:\n" + "\n".join(errors))
    print("ok worker compliance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
