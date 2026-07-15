#!/usr/bin/env python3
"""Validate visual screenshot provenance."""

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
    parser.add_argument("manifest")
    parser.add_argument("--reference")
    parser.add_argument("--actual")
    args = parser.parse_args()

    data = load_json(args.manifest)
    required = [
        "actual_source",
        "device_id",
        "capture_command",
        "timestamp",
        "project_root",
    ]
    missing = [key for key in required if not data.get(key)]
    if not isinstance(data.get("app_hashes"), dict):
        missing.append("app_hashes")
    if not isinstance(data.get("runtime_input_hashes"), dict):
        missing.append("runtime_input_hashes")
    if not isinstance(data.get("launch_command"), list) or not data.get("launch_command"):
        missing.append("launch_command")
    if not isinstance(data.get("viewport"), dict) or not data.get("viewport"):
        missing.append("viewport")
    if missing:
        raise SystemExit("ERROR: visual manifest missing fields: " + ", ".join(missing))
    if data.get("actual_source") != "simulator_screenshot":
        raise SystemExit("ERROR: actual_source must be simulator_screenshot")
    actual = Path(args.actual or data.get("actual_path", ""))
    if not actual.is_file():
        raise SystemExit(f"ERROR: actual screenshot missing: {actual}")
    reference_value = args.reference or data.get("reference_path")
    if reference_value:
        reference = Path(reference_value)
        if reference.is_file() and digest(reference) == digest(actual):
            raise SystemExit("ERROR: actual screenshot is byte-identical to reference")
    print("ok visual manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
