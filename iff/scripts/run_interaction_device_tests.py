#!/usr/bin/env python3
"""Run all planned interaction cases once on an Android/iOS Flutter target."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from check_interaction_device_evidence import app_hashes, runtime_input_hashes, sha256, test_hashes
from run_interaction_tests import parse_machine_events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--platform", choices=("android", "ios"), required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    test_root = Path(args.test_root).resolve()
    project_root = Path(args.project_root).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    case_ids = [str(case.get("id") or "") for case in plan.get("cases") or []]
    devices_run = subprocess.run(
        [args.flutter, "devices", "--machine"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        devices = json.loads(devices_run.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"ERROR: cannot read Flutter devices: {error}") from error
    descriptor = next(
        (item for item in devices if str(item.get("id") or "") == args.device),
        None,
    )
    if descriptor is None:
        raise SystemExit(f"ERROR: Flutter device not found: {args.device}")
    raw_platform = str(descriptor.get("targetPlatform") or "").lower()
    device_platform = (
        "android" if raw_platform.startswith("android")
        else "ios" if raw_platform.startswith("ios")
        else raw_platform
    )
    if device_platform != args.platform:
        raise SystemExit(
            f"ERROR: device platform mismatch: expected={args.platform} actual={device_platform}"
        )
    command = [
        args.flutter,
        "test",
        "--machine",
        "-d",
        args.device,
        str(test_root),
    ]
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    cases = parse_machine_events(run.stdout, case_ids)
    failed = [
        case_id
        for case_id in case_ids
        if (cases.get(case_id) or {}).get("result") != "success"
        or (cases.get(case_id) or {}).get("skipped")
    ]
    if run.returncode != 0 or failed:
        raise SystemExit(
            "ERROR: target-client interaction tests failed: "
            f"exit={run.returncode} cases={failed}"
        )
    evidence = {
        "version": 1,
        "command": command,
        "deviceId": args.device,
        "deviceTargetPlatform": device_platform,
        "actualPlatforms": [args.platform],
        "exitCode": run.returncode,
        "planHash": sha256(plan_path),
        "testHashes": test_hashes(test_root),
        "appHashes": app_hashes(project_root),
        "runtimeInputHashes": runtime_input_hashes(project_root),
        "stdoutHash": hashlib.sha256(run.stdout.encode("utf-8")).hexdigest(),
        "cases": cases,
    }
    Path(args.evidence).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ok target-client interaction tests cases={len(case_ids)} platform={args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
