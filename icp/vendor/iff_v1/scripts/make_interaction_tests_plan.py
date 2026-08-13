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
                    "trigger": rule.get("trigger"),
                    "expectation": rule.get("expectation"),
                    "purpose": purpose,
                    "testIdMustAppearInTestNameOrComment": case_id,
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
