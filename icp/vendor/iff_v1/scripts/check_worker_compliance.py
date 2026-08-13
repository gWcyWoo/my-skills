#!/usr/bin/env python3
"""Validate that an iFF worker loaded the current skill rules."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expected-skill-md-sha256")
    parser.add_argument("--expected-test-rules-sha256")
    parser.add_argument("--expected-verify-pipeline-scripts-sha256")
    parser.add_argument(
        "--expected-loaded-file-sha256",
        action="append",
        default=[],
        nargs=2,
        metavar=("PATH", "SHA256"),
    )
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    verify_script = skill_dir / "scripts" / "verify_pipeline_scripts.py"
    expected = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "verify_pipeline_scripts_sha256": digest(verify_script),
    }
    expected_loaded_files = {
        str(Path(path).expanduser().resolve()): expected_hash
        for path, expected_hash in args.expected_loaded_file_sha256
    }
    if args.write:
        prompt_expected = {
            "skill_md_sha256": args.expected_skill_md_sha256,
            "test_rules_sha256": args.expected_test_rules_sha256,
            "verify_pipeline_scripts_sha256": args.expected_verify_pipeline_scripts_sha256,
        }
        missing = [key for key, value in prompt_expected.items() if not value]
        if missing:
            raise SystemExit(
                "ERROR: compliance writer missing generation-time hashes: " + ", ".join(missing)
            )
        drifted = [key for key, value in expected.items() if prompt_expected[key] != value]
        drifted.extend(
            f"loaded_file_sha256:{path}"
            for path, expected_hash in expected_loaded_files.items()
            if not Path(path).is_file() or digest(Path(path)) != expected_hash
        )
        if drifted:
            raise SystemExit(
                "ERROR: compliance sources changed after prompt generation:\n" + "\n".join(drifted)
            )
        manifest_path = Path(args.manifest).expanduser().resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "loaded_files": [str(skill_md), str(test_rules), *sorted(expected_loaded_files)],
                    "loaded_file_sha256": expected_loaded_files,
                    **expected,
                    "pipeline_scripts_ok": True,
                    "worker_bootstrap_version": "IFF_WORKER_BOOTSTRAP v1",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"ok wrote worker compliance {manifest_path}")
        return 0

    manifest = load_json(args.manifest)
    errors = []
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"{key} mismatch")
    loaded = set(manifest.get("loaded_files") or [])
    for path in (str(skill_md), str(test_rules)):
        if path not in loaded:
            errors.append(f"missing loaded file proof: {path}")
    loaded_file_hashes = manifest.get("loaded_file_sha256") or {}
    if not isinstance(loaded_file_hashes, dict):
        errors.append("loaded_file_sha256 must be an object")
    else:
        for path, expected_hash in loaded_file_hashes.items():
            source = Path(path)
            if path not in loaded:
                errors.append(f"missing loaded file proof: {path}")
            if not source.is_file() or digest(source) != expected_hash:
                errors.append(f"loaded file hash mismatch: {path}")
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
