#!/usr/bin/env python3
"""Generate one visual fixture imported by tests, previews, and runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json


def dart_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def states_from_groups(classification_path: Path) -> list[str]:
    groups_path = classification_path.with_name("groups.json")
    try:
        groups = load_json(groups_path).get("groups") or []
    except FileNotFoundError:
        return []
    states = []
    for group in groups:
        if group.get("kind") != "loan_card":
            continue
        state = group.get("state")
        if state and state not in states:
            states.append(str(state))
    return states


def status_from_state(state: str) -> str:
    if state == "apply_0_1_2_10":
        return "0"
    for code in ("11", "10", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
        if f"_{code}" in state or state.endswith(code):
            return code
    return "0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classification", required=True)
    parser.add_argument("--api-contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    classification_path = Path(args.classification)
    classification = load_json(classification_path)
    try:
        api_contract = load_json(args.api_contract)
    except FileNotFoundError:
        api_contract = {}
    states = states_from_groups(classification_path) or classification.get("states") or ["default"]
    products = [
        {
            "id": f"visual_{i + 1}",
            "state": state,
            "applyStatus": status_from_state(str(state)),
            "title": state.replace("_", " ").title(),
            "amount": 50000,
        }
        for i, state in enumerate(states)
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".json":
        out.write_text(json.dumps({"products": products, "apiContract": api_contract}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        rows = []
        for product in products:
            rows.append(
                "  {"
                f"'id': {dart_string(product['id'])}, "
                f"'state': {dart_string(product['state'])}, "
                f"'applyStatus': {dart_string(product['applyStatus'])}, "
                f"'title': {dart_string(product['title'])}, "
                f"'amount': {product['amount']}"
                "},"
            )
        out.write_text(
            "const homeVisualProducts = <Map<String, Object>>[\n"
            + "\n".join(rows)
            + "\n];\n",
            encoding="utf-8",
        )
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
