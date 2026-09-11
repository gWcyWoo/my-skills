#!/usr/bin/env python3
import argparse
import json
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True)
    parser.add_argument("--status-column", required=True)
    parser.add_argument("--priority-column", required=True)
    parser.add_argument("--priority-order", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.load(sys.stdin)
    available_columns = {
        column for row in payload["rows"] for column in row["values"]
    }
    missing_columns = [
        column
        for column in (args.status_column, args.priority_column)
        if payload["rows"] and column not in available_columns
    ]
    if missing_columns:
        print(
            json.dumps(
                {"error": "missing_columns", "columns": missing_columns},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 4
    priority_rank = {
        value: index
        for index, value in enumerate(part.strip() for part in args.priority_order.split(","))
    }
    candidates = [
        row
        for row in payload["rows"]
        if row["values"].get(args.status_column) == args.status
    ]
    if not candidates:
        print(
            json.dumps({"error": "no_matching_task", "status": args.status}),
            file=sys.stderr,
        )
        return 3
    candidates.sort(
        key=lambda row: (
            priority_rank.get(row["values"].get(args.priority_column), len(priority_rank)),
            row["row_number"],
        )
    )
    print(json.dumps(candidates[0], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
