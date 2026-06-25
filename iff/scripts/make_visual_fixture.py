#!/usr/bin/env python3
"""Generate one visual fixture imported by tests, previews, and runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json


def dart_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classification", required=True)
    parser.add_argument("--api-contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    classification = load_json(args.classification)
    try:
        api_contract = load_json(args.api_contract)
    except FileNotFoundError:
        api_contract = {}
    states = classification.get("states") or ["default"]
    products = [
        {
            "id": f"visual_{i + 1}",
            "state": state,
            "title": state.replace("_", " ").title(),
            "amount": 1000 * (i + 1),
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
