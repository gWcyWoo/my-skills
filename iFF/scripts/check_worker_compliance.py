#!/usr/bin/env python3
"""Recompute one canonical iFF worker contract and completion receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from complete_worker import build_receipt, load_object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    receipt_path = Path(args.manifest).expanduser().resolve()
    try:
        stored = load_object(receipt_path)
        if stored.get("workerContractVersion") != "IFF_WORKER_CONTRACT v3":
            raise ValueError("legacy worker contract is not accepted")
        expected = build_receipt(
            Path(args.skill_dir).expanduser().resolve(),
            Path(args.feature_manifest).expanduser().resolve(),
            Path(str(stored.get("contractInputPath") or "")).expanduser().resolve(),
            Path(str(stored.get("resultPath") or "")).expanduser().resolve(),
            receipt_path,
        )
        if stored != expected:
            raise ValueError("worker receipt differs from current canonical receipt")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: worker compliance failed: {error}") from error
    print(f"ok worker compliance: {stored['worker']['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
