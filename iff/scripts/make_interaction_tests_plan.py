#!/usr/bin/env python3
"""Generate required interaction test cases from interaction_contract.json."""

from __future__ import annotations

import argparse

from common import dump_json, load_json


VARIANTS = {
    "happy": "normal trigger reaches the expected visible result",
    "boundary": "repeat, disabled, empty, or edge-state trigger keeps a valid observable state",
    "failure": "mocked API failure or invalid state renders the specified error/blocked result",
}

OUTCOME_FIELDS = {
    "happy": "observableOutcome",
    "boundary": "boundaryOutcome",
    "failure": "failureOutcome",
}


def validate_plan(contract: dict, plan: dict) -> list[str]:
    expected = {
        f"{rule['id']}-{variant.upper()}"
        for rule in contract.get("rules") or []
        for variant in VARIANTS
    }
    actual = {
        str(case.get("id"))
        for case in plan.get("cases") or []
        if isinstance(case, dict) and case.get("id")
    }
    failures = [f"missing interaction case: {case_id}" for case_id in sorted(expected - actual)]
    failures.extend(f"unexpected interaction case: {case_id}" for case_id in sorted(actual - expected))
    rules = {str(rule.get("id")): rule for rule in contract.get("rules") or []}
    cases = {
        str(case.get("id")): case
        for case in plan.get("cases") or []
        if isinstance(case, dict) and case.get("id")
    }
    for case_id in sorted(expected & actual):
        interaction_id, variant_upper = case_id.rsplit("-", 1)
        variant = variant_upper.lower()
        rule = rules[interaction_id]
        case = cases[case_id]
        expected_fields = {
            "interactionId": interaction_id,
            "variant": variant,
            "precondition": rule.get("precondition"),
            "action": rule.get("action"),
            "actionTarget": rule.get("actionTarget"),
            "expectedObservable": rule.get(OUTCOME_FIELDS[variant]),
            "expectedObservableTarget": (rule.get("observableTargets") or {}).get(variant),
            "surface": "public_ui",
        }
        for field, value in expected_fields.items():
            if case.get(field) != value:
                failures.append(f"{case_id}: {field} mismatch")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--api-contract")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    contract = load_json(args.contract)
    api_contract = {}
    if args.api_contract:
        try:
            api_contract = load_json(args.api_contract)
        except FileNotFoundError:
            api_contract = {}
    cases = []
    for rule in contract.get("rules") or []:
        for variant, purpose in VARIANTS.items():
            case_id = f"{rule['id']}-{variant.upper()}"
            cases.append(
                {
                    "id": case_id,
                    "interactionId": rule["id"],
                    "variant": variant,
                    "precondition": rule.get("precondition"),
                    "action": rule.get("action"),
                    "actionTarget": rule.get("actionTarget"),
                    "expectedObservable": rule.get(OUTCOME_FIELDS[variant]),
                    "expectedObservableTarget": (rule.get("observableTargets") or {}).get(variant),
                    "surface": "public_ui",
                    "purpose": purpose,
                    "testIdMustAppearInTestWidgetsName": case_id,
                    "usesApiContract": bool(api_contract),
                }
            )
    dump_json(
        {
            "interactionContract": args.contract,
            "caseCount": len(cases),
            "cases": cases,
        },
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
