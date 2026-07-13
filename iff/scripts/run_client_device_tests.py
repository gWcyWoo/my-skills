#!/usr/bin/env python3
"""Run interaction and data target-client cases in one Flutter invocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from check_interaction_device_evidence import (
    app_hashes,
    runtime_input_hashes,
    sha256,
    test_hashes,
)
from data_test_cases import required_data_cases
from run_data_device_tests import persist_captures
from run_interaction_tests import parse_machine_events


def write_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--platform", choices=("android", "ios"), required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--interaction-plan", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--interaction-evidence", required=True)
    parser.add_argument("--data-evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.interaction_plan).resolve()
    bindings_path = Path(args.bindings).resolve()
    runtime_path = Path(args.runtime_manifest).resolve()
    test_root = Path(args.test_root).resolve()
    project_root = Path(args.project_root).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    interaction_ids = [str(case.get("id") or "") for case in plan.get("cases") or []]
    data_ids = [
        case
        for case in required_data_cases(bindings, runtime)
        if case.startswith(("DATA-SLOT:", "DATA-STATE:"))
    ]
    case_ids = [*interaction_ids, *data_ids]

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
        (item for item in devices if str(item.get("id") or "") == args.device), None
    )
    if descriptor is None:
        raise SystemExit(f"ERROR: Flutter device not found: {args.device}")
    raw_platform = str(descriptor.get("targetPlatform") or "").lower()
    device_platform = (
        "android"
        if raw_platform.startswith("android")
        else "ios"
        if raw_platform.startswith("ios")
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
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    cases = parse_machine_events(completed.stdout, case_ids)
    failed = [
        case_id
        for case_id in case_ids
        if (cases.get(case_id) or {}).get("result") != "success"
        or (cases.get(case_id) or {}).get("skipped")
    ]
    if completed.returncode != 0 or failed:
        raise SystemExit(
            f"ERROR: combined target-client tests failed: exit={completed.returncode} cases={failed}"
        )
    interaction_path = Path(args.interaction_evidence).resolve()
    data_path = Path(args.data_evidence).resolve()
    interaction_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    captures = persist_captures(completed.stdout, data_ids, data_path)
    common = {
        "version": 1,
        "generator": "run_client_device_tests.py",
        "command": command,
        "deviceId": args.device,
        "deviceTargetPlatform": device_platform,
        "actualPlatforms": [args.platform],
        "exitCode": completed.returncode,
        "testHashes": test_hashes(test_root),
        "appHashes": app_hashes(project_root),
        "runtimeInputHashes": runtime_input_hashes(project_root),
        "stdoutHash": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
    }
    interaction = {
        **common,
        "planHash": sha256(plan_path),
        "cases": {case_id: cases[case_id] for case_id in interaction_ids},
    }
    data = {
        **common,
        "platform": args.platform,
        "bindingsHash": sha256(bindings_path),
        "runtimeManifestHash": sha256(runtime_path),
        "requiredCases": data_ids,
        "captures": captures,
        "cases": {case_id: cases[case_id] for case_id in data_ids},
    }
    write_atomic(interaction_path, interaction)
    write_atomic(data_path, data)
    print(
        f"ok combined target-client tests: interaction={len(interaction_ids)} "
        f"data={len(data_ids)} platform={args.platform}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
