#!/usr/bin/env python3
"""Compile Android/iOS runtime observations into fingerprinted data evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from data_test_cases import required_data_cases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def app_hashes(app_root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(app_root)): sha256(path)
        for path in sorted(app_root.rglob("*.dart"))
    }


def capture_record(
    manifest_path: Path, platform: str, device_id: str, app_root: Path
) -> dict:
    if not manifest_path.is_file():
        raise SystemExit(f"ERROR: capture manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("actual_source") != "simulator_screenshot":
        raise SystemExit(
            f"ERROR: capture must use actual_source=simulator_screenshot: {manifest_path}"
        )
    if str(manifest.get("device_id") or "") != device_id:
        raise SystemExit(f"ERROR: capture device differs: {manifest_path}")
    if (
        manifest.get("project_root") != str(app_root.parent.resolve())
        or manifest.get("app_hashes") != app_hashes(app_root)
    ):
        raise SystemExit(f"ERROR: capture app differs: {manifest_path}")
    launch_command = manifest.get("launch_command") or []
    expected_launch = ["flutter", "run", "-d", device_id, "--debug", "--no-resident"]
    if launch_command[: len(expected_launch)] != expected_launch:
        raise SystemExit(f"ERROR: invalid client launch command: {manifest_path}")
    command = str(manifest.get("capture_command") or "")
    expected = (
        f"adb -s {device_id} shell screencap"
        if platform == "android"
        else f"xcrun simctl io {device_id} screenshot"
    )
    if not command.startswith(expected):
        raise SystemExit(f"ERROR: invalid {platform} capture command: {manifest_path}")
    screenshot = Path(str(manifest.get("actual_path") or ""))
    if not screenshot.is_file() or screenshot.stat().st_size == 0:
        raise SystemExit(f"ERROR: captured screenshot missing: {screenshot}")
    return {
        "manifestPath": str(manifest_path.resolve()),
        "manifestHash": sha256(manifest_path),
        "screenshotPath": str(screenshot.resolve()),
        "screenshotHash": sha256(screenshot),
        "actualSource": manifest["actual_source"],
        "deviceId": device_id,
        "captureCommand": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    bindings_path = Path(args.bindings).resolve()
    runtime_path = Path(args.runtime_manifest).resolve()
    app_root = Path(args.app_root).resolve()
    observations = json.loads(Path(args.observations).read_text(encoding="utf-8"))
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    platform = str(observations.get("platform") or "")
    device_id = str(observations.get("deviceId") or "")
    if platform not in {"android", "ios"}:
        raise SystemExit("ERROR: data evidence platform must be android or ios")
    if not device_id:
        raise SystemExit("ERROR: client deviceId is required")

    required = [
        case
        for case in required_data_cases(bindings, runtime)
        if case.startswith("DATA-SLOT:") or case.startswith("DATA-STATE:")
    ]
    fields = {}
    for entry in bindings.get("bindings") or []:
        field = (entry.get("binding") or {}).get("field")
        if not field:
            continue
        state = entry.get("state")
        qualifier = f"{state}:" if state is not None else ""
        fields[f"DATA-SLOT:{qualifier}{entry.get('node')}"] = field
    cases = observations.get("cases") or {}
    if set(cases) != set(required) or len(cases) != len(required):
        raise SystemExit(
            f"ERROR: observation cases differ: expected {required}, got {sorted(cases)}"
        )

    captures = {}
    for case_id in required:
        result = cases[case_id]
        observed = [
            value.strip()
            for value in result.get("observed") or []
            if isinstance(value, str) and value.strip()
        ]
        if (
            result.get("result") != "success"
            or result.get("skipped")
            or not observed
            or not str(result.get("action") or "").strip()
        ):
            raise SystemExit(f"ERROR: incomplete client observation: {case_id}")
        manifest_paths = [
            Path(str(value)).resolve() for value in result.get("captureManifests") or []
        ]
        if not manifest_paths:
            raise SystemExit(f"ERROR: client capture missing: {case_id}")
        case_records = []
        for manifest_path in manifest_paths:
            record = capture_record(manifest_path, platform, device_id, app_root)
            captures[record["manifestPath"]] = record
            case_records.append(record)
        if case_id.startswith("DATA-SLOT:"):
            input_values = result.get("inputValues") or []
            distinct_inputs = {
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                for value in input_values
            }
            if len(distinct_inputs) < 2 or len(set(observed)) < 2:
                raise SystemExit(
                    f"ERROR: slot needs two distinct input and visible values: {case_id}"
                )
            if len({record["manifestPath"] for record in case_records}) < 2:
                raise SystemExit(f"ERROR: slot needs two distinct client captures: {case_id}")
            if len({record["screenshotHash"] for record in case_records}) < 2:
                raise SystemExit(f"ERROR: slot client captures did not visibly change: {case_id}")

    payload = {
        "platform": platform,
        "deviceId": device_id,
        "bindingsHash": sha256(bindings_path),
        "runtimeManifestHash": sha256(runtime_path),
        "appHashes": app_hashes(app_root),
        "requiredCases": required,
        "fields": fields,
        "captures": [captures[key] for key in sorted(captures)],
        "cases": {case_id: cases[case_id] for case_id in required},
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"ok data device evidence: platform={platform} cases={len(required)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
