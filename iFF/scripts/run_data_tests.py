#!/usr/bin/env python3
"""Run Flutter data-driven UI tests and capture case-level TDD evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from data_test_cases import required_data_cases
from run_interaction_tests import parse_machine_events


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("red", "green"), required=True)
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--device")
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest")
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    bindings_path = Path(args.bindings).resolve()
    test_root = Path(args.test_root).resolve()
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    runtime_manifest_path = (
        Path(args.runtime_manifest).resolve() if args.runtime_manifest else None
    )
    runtime_manifest = {}
    if runtime_manifest_path:
        runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    case_ids = required_data_cases(bindings, runtime_manifest)
    command = [args.flutter, "test", "--machine"]
    if args.device:
        command.extend(["--device-id", args.device])
    command.append(str(test_root))
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    case_results = parse_machine_events(run.stdout, case_ids)
    test_hashes = {
        str(path.relative_to(test_root)): sha256(path)
        for path in sorted(test_root.rglob("*_test.dart"))
    }
    evidence_path = Path(args.evidence)
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        evidence = {}
    failed_cases = [
        case_id
        for case_id, result in case_results.items()
        if result.get("result") not in ("success", None) and not result.get("skipped")
    ]
    if args.phase == "red":
        if run.returncode == 0 or not failed_cases:
            print(f"FAIL data red evidence: no required case failed (exit_code={run.returncode})")
            return 1
    else:
        red = evidence.get("red") or {}
        green_failures = [
            case_id
            for case_id in case_ids
            if (case_results.get(case_id) or {}).get("result") != "success"
            or (case_results.get(case_id) or {}).get("skipped")
        ]
        if (
            run.returncode != 0
            or green_failures
            or red.get("bindingsHash") != sha256(bindings_path)
            or red.get("testHashes") != test_hashes
            or red.get("requiredCases") != case_ids
            or red.get("runtimeManifestHash")
            != (sha256(runtime_manifest_path) if runtime_manifest_path else None)
        ):
            print(
                "FAIL data green evidence: required cases did not all pass "
                "against the same red bindings/test fingerprints"
            )
            return 1

    evidence[args.phase] = {
            "command": command,
            "exitCode": run.returncode,
            "bindingsHash": sha256(bindings_path),
            "runtimeManifestHash": (
                sha256(runtime_manifest_path) if runtime_manifest_path else None
            ),
            "testHashes": test_hashes,
            "stdoutHash": hashlib.sha256(run.stdout.encode("utf-8")).hexdigest(),
            "requiredCases": case_ids,
            "cases": case_results,
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"ok data {args.phase} evidence: {len(case_results)} required case(s) observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
