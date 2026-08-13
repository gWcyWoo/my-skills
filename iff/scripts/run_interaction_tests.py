#!/usr/bin/env python3
"""Run Flutter interaction tests and capture case-level machine evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_machine_events(stdout: str, case_ids: list[str]) -> dict[str, dict]:
    starts: dict[object, str] = {}
    results: dict[str, dict] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "testStart":
            test = event.get("test") or {}
            starts[test.get("id")] = str(test.get("name") or "")
        elif event.get("type") == "testDone":
            name = starts.get(event.get("testID"), "")
            for case_id in case_ids:
                if case_id in name:
                    results[case_id] = {
                        "testName": name,
                        "result": event.get("result"),
                        "skipped": bool(event.get("skipped")),
                    }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("red", "green"), required=True)
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    test_root = Path(args.test_root).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    case_ids = [str(case["id"]) for case in plan.get("cases") or []]
    command = [args.flutter, "test", "--machine", str(test_root)]
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
    plan_hash = sha256(plan_path)

    if args.phase == "red":
        planned_failures = [
            case_id
            for case_id, result in case_results.items()
            if result.get("result") not in ("success", None) and not result.get("skipped")
        ]
        if run.returncode == 0 or not planned_failures:
            print(
                "FAIL interaction red evidence: no planned case failed "
                f"(exit_code={run.returncode})"
            )
            return 1
    else:
        red = evidence.get("red") or {}
        failed_cases = [
            case_id
            for case_id in case_ids
            if (case_results.get(case_id) or {}).get("result") != "success"
            or (case_results.get(case_id) or {}).get("skipped")
        ]
        if (
            run.returncode != 0
            or failed_cases
            or red.get("planHash") != plan_hash
            or red.get("testHashes") != test_hashes
        ):
            print(
                "FAIL interaction green evidence: planned cases did not all pass "
                "against the same red plan/test fingerprints"
            )
            return 1
    evidence[args.phase] = {
        "command": command,
        "exitCode": run.returncode,
        "planHash": plan_hash,
        "testHashes": test_hashes,
        "stdoutHash": hashlib.sha256(run.stdout.encode("utf-8")).hexdigest(),
        "cases": case_results,
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ok interaction {args.phase} evidence: {len(case_results)} planned case(s) observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
