#!/usr/bin/env python3
"""Check interaction test mapping and red/green evidence before done."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json


def dart_test_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*.dart")
        if ".dart_tool" not in path.parts and "build" not in path.parts
    ]


def evidence_ok(evidence: dict) -> list[str]:
    errors = []
    red = evidence.get("red") or {}
    green = evidence.get("green") or {}
    if red.get("exit_code") in (None, 0):
        errors.append("red evidence must exist and have non-zero exit_code")
    if green.get("exit_code") != 0:
        errors.append("green evidence must exist and have exit_code 0")
    if not red.get("command"):
        errors.append("red evidence missing command")
    if not green.get("command"):
        errors.append("green evidence missing command")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan = load_json(args.plan)
    cases = plan.get("cases") or []
    if not cases:
        print("ok interaction coverage: no interaction cases")
        return 0

    test_root = Path(args.test_root)
    files = dart_test_files(test_root)
    if not files:
        raise SystemExit(f"ERROR: no Dart test files found under {test_root}")
    haystack = {}
    for path in files:
        try:
            haystack[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

    errors = []
    for case in cases:
        case_id = case["id"]
        matches = [path for path, text in haystack.items() if case_id in text]
        if not matches:
            errors.append(f"{case_id}: missing literal case id in test name or comment")
            continue
        for path in matches:
            text = haystack[path]
            for line in text.splitlines():
                if case_id in line and ("skip:" in line or ".skip" in line):
                    errors.append(f"{case_id}: mapped test appears skipped in {path}")

    evidence_path = Path(args.evidence)
    if not evidence_path.is_file():
        errors.append(f"missing red/green evidence file: {evidence_path}")
    else:
        evidence = load_json(evidence_path)
        errors.extend(evidence_ok(evidence))
        case_evidence = evidence.get("cases") or {}
        for case in cases:
            if case["id"] not in case_evidence:
                errors.append(f"{case['id']}: missing case evidence mapping")

    if errors:
        raise SystemExit("ERROR: interaction coverage failed:\n" + "\n".join(errors))
    print(f"ok interaction coverage cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
