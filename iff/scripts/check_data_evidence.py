#!/usr/bin/env python3
"""Validate current RED/GREEN tests and target-client runtime observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from data_test_cases import required_data_cases
from make_data_device_evidence import capture_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--require-device")
    parser.add_argument("--app-root")
    parser.add_argument("--browser-evidence")
    parser.add_argument("--device-evidence")
    args = parser.parse_args()

    bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8"))
    runtime_manifest = json.loads(Path(args.runtime_manifest).read_text(encoding="utf-8"))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    errors = []
    required_cases = required_data_cases(bindings, runtime_manifest)
    runtime_hash = hashlib.sha256(Path(args.runtime_manifest).read_bytes()).hexdigest()
    test_root = Path(args.test_root)
    test_hashes = {
        str(path.relative_to(test_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(test_root.rglob("*_test.dart"))
    }
    for phase in ("red", "green"):
        phase_evidence = evidence.get(phase) or {}
        if phase_evidence.get("requiredCases") != required_cases:
            errors.append(f"required data cases differ: {phase}")
        if phase_evidence.get("runtimeManifestHash") != runtime_hash:
            errors.append(f"stale runtime manifest evidence: {phase}")
        if phase_evidence.get("testHashes") != test_hashes:
            errors.append(f"stale test evidence: {phase}")
    green_cases = (evidence.get("green") or {}).get("cases") or {}
    for case_id in required_cases:
        result = green_cases.get(case_id) or {}
        if result.get("result") != "success" or result.get("skipped"):
            errors.append(f"green case not successful: {case_id}")
    red_cases = (evidence.get("red") or {}).get("cases") or {}
    missing_red = [case_id for case_id in required_cases if case_id not in red_cases]
    for case_id in missing_red:
        errors.append(f"red case not observed: {case_id}")
    red_failures = [
        case_id
        for case_id in required_cases
        if (red_cases.get(case_id) or {}).get("result") != "success"
        and not (red_cases.get(case_id) or {}).get("skipped")
    ]
    if required_cases and not red_failures:
        errors.append("red evidence has no required failure")
    bindings_hash = hashlib.sha256(Path(args.bindings).read_bytes()).hexdigest()
    for phase in ("red", "green"):
        if (evidence.get(phase) or {}).get("bindingsHash") != bindings_hash:
            errors.append(f"stale bindings evidence: {phase}")
    if args.require_device:
        command = (evidence.get("green") or {}).get("command") or []
        device_pair = ["--device-id", args.require_device]
        if not any(
            command[index : index + 2] == device_pair
            for index in range(max(0, len(command) - 1))
        ):
            errors.append(f"green evidence did not run on {args.require_device}")
        actual = (evidence.get("green") or {}).get("actualPlatforms") or []
        if args.require_device not in actual:
            errors.append(
                f"green evidence actual platform was not {args.require_device}: {actual}"
            )
    if not args.app_root or not args.device_evidence:
        errors.append("app root and Android/iOS device evidence are required")
    if args.browser_evidence:
        errors.append(
            "browser evidence is unsupported for iFF client; use Android/iOS device evidence"
        )
    if args.device_evidence:
        if not args.app_root:
            errors.append("app root and device evidence must be provided together")
        device_path = Path(args.device_evidence)
        if not device_path.is_file():
            errors.append("device evidence is missing")
        else:
            device = json.loads(device_path.read_text(encoding="utf-8"))
            if device.get("generator") in {
                "run_data_device_tests.py",
                "run_client_device_tests.py",
            }:
                project_root = Path(args.app_root).resolve().parent
                checked = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("check_data_device_evidence.py")),
                        "--bindings",
                        str(Path(args.bindings).resolve()),
                        "--runtime-manifest",
                        str(Path(args.runtime_manifest).resolve()),
                        "--test-root",
                        str(project_root / "integration_test"),
                        "--project-root",
                        str(project_root),
                        "--evidence",
                        str(device_path.resolve()),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if checked.returncode != 0:
                    errors.append(checked.stdout.strip() or checked.stderr.strip())
                if errors:
                    raise SystemExit(
                        "ERROR: invalid data evidence:\n"
                        + "\n".join(f"- {error}" for error in errors)
                    )
                print("ok data evidence")
                return 0
            device_cases = [
                case
                for case in required_cases
                if case.startswith("DATA-SLOT:") or case.startswith("DATA-STATE:")
            ]
            device_fields = {}
            for entry in bindings.get("bindings") or []:
                field = (entry.get("binding") or {}).get("field")
                if not field:
                    continue
                state = entry.get("state")
                qualifier = f"{state}:" if state is not None else ""
                device_fields[f"DATA-SLOT:{qualifier}{entry.get('node')}"] = field
            app_root = Path(args.app_root)
            app_hashes = {
                str(path.relative_to(app_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(app_root.rglob("*.dart"))
            }
            platform = str(device.get("platform") or "")
            device_id = str(device.get("deviceId") or "")
            if platform not in {"android", "ios"} or not device_id:
                errors.append("device evidence has no Android/iOS client target")
            if device.get("bindingsHash") != bindings_hash:
                errors.append("stale device bindings evidence")
            if device.get("runtimeManifestHash") != runtime_hash:
                errors.append("stale device runtime evidence")
            if device.get("appHashes") != app_hashes:
                errors.append("stale device app evidence")
            if device.get("requiredCases") != device_cases:
                errors.append("device required data cases differ")
            if device.get("fields") != device_fields:
                errors.append("device bound fields differ")
            current_captures = {}
            observed_cases = device.get("cases") or {}
            for case_id in device_cases:
                result = observed_cases.get(case_id) or {}
                observed = [
                    value.strip()
                    for value in result.get("observed") or []
                    if isinstance(value, str) and value.strip()
                ]
                if result.get("result") != "success" or result.get("skipped"):
                    errors.append(f"device case not successful: {case_id}")
                if not observed or not str(result.get("action") or "").strip():
                    errors.append(f"device case observation incomplete: {case_id}")
                records = []
                for manifest_value in result.get("captureManifests") or []:
                    try:
                        record = capture_record(
                            Path(str(manifest_value)).resolve(),
                            platform,
                            device_id,
                            app_root,
                        )
                    except SystemExit as exc:
                        errors.append(f"stale device capture: {case_id}: {exc}")
                        continue
                    current_captures[record["manifestPath"]] = record
                    records.append(record)
                if not records:
                    errors.append(f"device capture missing: {case_id}")
                if case_id.startswith("DATA-SLOT:"):
                    distinct_inputs = {
                        json.dumps(value, ensure_ascii=False, sort_keys=True)
                        for value in result.get("inputValues") or []
                    }
                    if len(distinct_inputs) < 2 or len(set(observed)) < 2:
                        errors.append(
                            f"device slot needs two distinct input/visible values: {case_id}"
                        )
                    if len({record["manifestPath"] for record in records}) < 2:
                        errors.append(f"device slot needs two captures: {case_id}")
                    if len({record["screenshotHash"] for record in records}) < 2:
                        errors.append(f"device slot pixels did not change: {case_id}")
            expected_captures = [
                current_captures[key] for key in sorted(current_captures)
            ]
            if device.get("captures") != expected_captures:
                errors.append("stale device capture fingerprints")

    if errors:
        raise SystemExit("ERROR: invalid data evidence:\n" + "\n".join(f"- {e}" for e in errors))
    print("ok data evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
