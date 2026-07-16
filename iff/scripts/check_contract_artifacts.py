#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scope_api_contract import ApiScopeError, validate_feature_contract_files


REQUIRED_JSON_ARTIFACTS = (
    "interaction_contract.json",
    "interaction_completeness_report.json",
    "interaction_promotion_report.json",
    "state_machine.json",
    "interaction_anchors.json",
    "oas_missing_ref_paths.json",
    "row.json",
    "api_contract.json",
    "api_endpoint_selection.json",
    "feature_api_contract.json",
    "interaction_test_plan.json",
)


def interaction_plan_failures(contract: object, plan: object) -> list[str]:
    if not isinstance(contract, dict) or not isinstance(plan, dict):
        return ["interaction contract and test plan must be JSON objects"]
    rules = contract.get("rules") or []
    cases = plan.get("cases") or []
    if not isinstance(rules, list) or not isinstance(cases, list):
        return ["interaction rules and test cases must be arrays"]

    expected: dict[str, tuple[str, str]] = {}
    rule_ids: set[str] = set()
    failures: list[str] = []
    for rule in rules:
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        if not isinstance(rule_id, str) or not rule_id:
            failures.append("interaction rule id must be a non-empty string")
            continue
        if rule_id in rule_ids:
            failures.append(f"duplicate interaction rule id: {rule_id}")
            continue
        rule_ids.add(rule_id)
        required_ids = rule.get("testCaseIdsRequired") if isinstance(rule, dict) else None
        if not isinstance(required_ids, list) or not required_ids:
            required_ids = [f"{rule_id}-{variant}" for variant in ("HAPPY", "BOUNDARY", "FAILURE")]
        for case_id in required_ids:
            if not isinstance(case_id, str) or not case_id:
                failures.append(f"invalid required test case id for {rule_id}")
                continue
            expected[case_id] = (rule_id, case_id.rsplit("-", 1)[-1].casefold())

    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id") if isinstance(case, dict) else None
        interaction_id = case.get("interactionId") if isinstance(case, dict) else None
        variant = case.get("variant") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id:
            failures.append("interaction test case id must be a non-empty string")
            continue
        if case_id in seen:
            failures.append(f"duplicate interaction test case id: {case_id}")
            continue
        seen.add(case_id)
        expected_link = expected.get(case_id)
        if expected_link is None:
            failures.append(f"unexpected interaction test case: {case_id}")
        elif (interaction_id, variant) != expected_link:
            failures.append(f"interaction test case linkage mismatch: {case_id}")

    missing = sorted(set(expected) - seen)
    if missing:
        failures.append("missing interaction test cases: " + ", ".join(missing))
    declared_count = plan.get("caseCount")
    if declared_count is not None and declared_count != len(cases):
        failures.append(f"interaction test caseCount mismatch: declared={declared_count} actual={len(cases)}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--index", required=True, help="board_index.json")
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir).resolve()
    index = Path(args.index).resolve()
    failures: list[str] = []

    for name in REQUIRED_JSON_ARTIFACTS:
        path = spec_dir / name
        if not path.is_file():
            failures.append(f"missing {path}")
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"invalid JSON {path}: {exc}")

    contract_path = spec_dir / "interaction_contract.json"
    plan_path = spec_dir / "interaction_test_plan.json"
    if contract_path.is_file() and plan_path.is_file():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            failures.extend(interaction_plan_failures(contract, plan))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"invalid interaction contract/test plan: {exc}")

    api_paths = [
        spec_dir / "api_contract.json",
        spec_dir / "row.json",
        spec_dir / "interaction_contract.json",
        spec_dir / "api_endpoint_selection.json",
        spec_dir / "feature_api_contract.json",
    ]
    if all(path.is_file() for path in api_paths):
        try:
            validate_feature_contract_files(*api_paths)
        except (ApiScopeError, OSError) as exc:
            failures.append(f"invalid feature API contract: {exc}")

    if not index.is_file():
        failures.append(f"missing {index}")
    else:
        try:
            with index.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"invalid JSON {index}: {exc}")

    if failures:
        for failure in failures:
            print(f"FAIL contract artifacts: {failure}", file=sys.stderr)
        return 1

    anchor_check = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "resolve_interaction_anchors.py"),
            "--contract",
            str(spec_dir / "interaction_contract.json"),
            "--index",
            str(index),
            "--out",
            str(spec_dir / "interaction_anchors.json"),
            "--check",
        ],
        text=True,
        capture_output=True,
    )
    if anchor_check.returncode != 0:
        print(anchor_check.stdout, end="", file=sys.stderr)
        print(anchor_check.stderr, end="", file=sys.stderr)
        return anchor_check.returncode

    print(f"ok contract artifacts: {len(REQUIRED_JSON_ARTIFACTS)} files; anchors validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
