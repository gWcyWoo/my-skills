#!/usr/bin/env python3
"""Run visible data cases once on an Android/iOS Flutter target."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

from check_interaction_device_evidence import (
    app_hashes,
    runtime_input_hashes,
    sha256,
    test_hashes,
)
from data_test_cases import required_data_cases
from run_interaction_tests import parse_machine_events


CAPTURE_MARKER = re.compile(
    r"IFF_DATA_CAPTURE\|([^|\r\n]+)\|([0-9]+)\|([A-Za-z0-9+/=]+)"
)


def png_dimensions(value: bytes) -> tuple[int, int]:
    if len(value) < 24 or value[:8] != b"\x89PNG\r\n\x1a\n" or value[12:16] != b"IHDR":
        raise SystemExit("ERROR: Flutter data capture is not a PNG")
    width, height = struct.unpack(">II", value[16:24])
    if width <= 0 or height <= 0:
        raise SystemExit("ERROR: Flutter data capture has invalid dimensions")
    return width, height


def persist_captures(stdout: str, case_ids: list[str], evidence_path: Path) -> list[dict]:
    capture_dir = evidence_path.parent / "data_device_captures"
    records = []
    seen: set[tuple[str, int]] = set()
    for match in CAPTURE_MARKER.finditer(stdout):
        case_id = match.group(1)
        index = int(match.group(2))
        if case_id not in case_ids:
            continue
        identity = (case_id, index)
        if identity in seen:
            raise SystemExit(f"ERROR: duplicate Flutter data capture: {case_id}:{index}")
        seen.add(identity)
        try:
            payload = base64.b64decode(match.group(3), validate=True)
        except ValueError as error:
            raise SystemExit(f"ERROR: invalid Flutter data capture: {case_id}:{index}") from error
        width, height = png_dimensions(payload)
        capture_dir.mkdir(parents=True, exist_ok=True)
        case_token = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:16]
        path = capture_dir / f"{case_token}-{index}.png"
        path.write_bytes(payload)
        records.append(
            {
                "caseId": case_id,
                "index": index,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": width,
                "height": height,
                "byteLength": len(payload),
            }
        )
    for case_id in case_ids:
        case_records = [record for record in records if record["caseId"] == case_id]
        expected_count = 2 if case_id.startswith("DATA-SLOT:") else 1
        if len(case_records) != expected_count:
            raise SystemExit(
                f"ERROR: {case_id} requires {expected_count} automated Flutter capture(s)"
            )
        if case_id.startswith("DATA-SLOT:") and len(
            {record["sha256"] for record in case_records}
        ) != 2:
            raise SystemExit(f"ERROR: {case_id} Flutter captures did not visibly change")
    return sorted(records, key=lambda record: (record["caseId"], record["index"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--platform", choices=("android", "ios"), required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    bindings_path = Path(args.bindings).resolve()
    runtime_path = Path(args.runtime_manifest).resolve()
    test_root = Path(args.test_root).resolve()
    project_root = Path(args.project_root).resolve()
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    case_ids = [
        case
        for case in required_data_cases(bindings, runtime)
        if case.startswith(("DATA-SLOT:", "DATA-STATE:"))
    ]

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
            "ERROR: target-client data tests failed: "
            f"exit={run.returncode} cases={failed}"
        )

    evidence_path = Path(args.evidence).resolve()
    captures = persist_captures(run.stdout, case_ids, evidence_path)
    evidence = {
        "version": 1,
        "generator": "run_data_device_tests.py",
        "command": command,
        "deviceId": args.device,
        "deviceTargetPlatform": device_platform,
        "platform": args.platform,
        "actualPlatforms": [args.platform],
        "exitCode": run.returncode,
        "bindingsHash": sha256(bindings_path),
        "runtimeManifestHash": sha256(runtime_path),
        "testHashes": test_hashes(test_root),
        "appHashes": app_hashes(project_root),
        "runtimeInputHashes": runtime_input_hashes(project_root),
        "stdoutHash": hashlib.sha256(run.stdout.encode("utf-8")).hexdigest(),
        "requiredCases": case_ids,
        "captures": captures,
        "cases": cases,
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ok target-client data tests cases={len(case_ids)} platform={args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
