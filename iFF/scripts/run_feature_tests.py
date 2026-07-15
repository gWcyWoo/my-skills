#!/usr/bin/env python3
"""Run one Flutter machine test process and emit both interaction and data TDD evidence."""
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


def has_failure(results: dict[str, dict]) -> bool:
    return any(
        result.get("result") != "success" and not result.get("skipped")
        for result in results.values()
    )


def all_success(case_ids: list[str], results: dict[str, dict]) -> bool:
    return all(
        (results.get(case_id) or {}).get("result") == "success"
        and not (results.get(case_id) or {}).get("skipped")
        for case_id in case_ids
    )


def actual_platforms(machine_output: str) -> list[str]:
    platforms = set()
    for line in machine_output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "suite" and (event.get("suite") or {}).get("platform"):
            platforms.add(str(event["suite"]["platform"]))
    return sorted(platforms)


def write_phase(path: Path, phase: str, payload: dict) -> None:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        evidence = {}
    evidence[phase] = payload
    path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("red", "green"), required=True)
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--device")
    parser.add_argument("--interaction-plan", required=True)
    parser.add_argument("--interaction-evidence", required=True)
    parser.add_argument("--data-bindings", required=True)
    parser.add_argument("--data-runtime-manifest", required=True)
    parser.add_argument("--data-evidence", required=True)
    parser.add_argument("--test-root", required=True)
    args = parser.parse_args()

    plan_path = Path(args.interaction_plan).resolve()
    bindings_path = Path(args.data_bindings).resolve()
    runtime_path = Path(args.data_runtime_manifest).resolve()
    test_root = Path(args.test_root).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    interaction_ids = [str(case.get("id")) for case in plan.get("cases") or []]
    data_ids = required_data_cases(bindings, runtime)
    command = [args.flutter, "test", "--machine"]
    if args.device:
        command.extend(["--device-id", args.device])
    command.append(str(test_root))
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    interaction_results = parse_machine_events(run.stdout, interaction_ids)
    data_results = parse_machine_events(run.stdout, data_ids)

    test_hashes = {
        str(path.relative_to(test_root)): sha256(path)
        for path in sorted(test_root.rglob("*_test.dart"))
    }
    if args.phase == "red":
        if run.returncode == 0:
            print("FAIL feature red evidence: Flutter run succeeded")
            return 1
        if interaction_ids and not has_failure(interaction_results):
            print("FAIL feature red evidence: no planned interaction case failed")
            return 1
        if data_ids and not has_failure(data_results):
            print("FAIL feature red evidence: no required data case failed")
            return 1
    else:
        try:
            interaction_red = json.loads(
                Path(args.interaction_evidence).read_text(encoding="utf-8")
            ).get("red") or {}
            data_red = json.loads(
                Path(args.data_evidence).read_text(encoding="utf-8")
            ).get("red") or {}
        except FileNotFoundError:
            print("FAIL feature green evidence: matching red evidence missing")
            return 1
        if (
            run.returncode != 0
            or not all_success(interaction_ids, interaction_results)
            or not all_success(data_ids, data_results)
            or interaction_red.get("planHash") != sha256(plan_path)
            or interaction_red.get("testHashes") != test_hashes
            or data_red.get("bindingsHash") != sha256(bindings_path)
            or data_red.get("runtimeManifestHash") != sha256(runtime_path)
            or data_red.get("testHashes") != test_hashes
            or data_red.get("requiredCases") != data_ids
        ):
            print(
                "FAIL feature green evidence: cases or red fingerprints differ "
                "for interaction/data"
            )
            return 1
    shared = {
        "command": command,
        "actualPlatforms": actual_platforms(run.stdout),
        "exitCode": run.returncode,
        "testHashes": test_hashes,
        "stdoutHash": hashlib.sha256(run.stdout.encode("utf-8")).hexdigest(),
    }
    write_phase(
        Path(args.interaction_evidence),
        args.phase,
        {**shared, "planHash": sha256(plan_path), "cases": interaction_results},
    )
    write_phase(
        Path(args.data_evidence),
        args.phase,
        {
            **shared,
            "bindingsHash": sha256(bindings_path),
            "runtimeManifestHash": sha256(runtime_path),
            "requiredCases": data_ids,
            "cases": data_results,
        },
    )
    print(
        f"ok feature {args.phase} evidence: interaction={len(interaction_results)} "
        f"data={len(data_results)} one_flutter_run=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
