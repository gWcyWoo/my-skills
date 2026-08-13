#!/usr/bin/env python3
"""Validate that interaction rules are concrete enough to test through the UI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_RULE_FIELDS = (
    "id",
    "source",
    "action",
    "observableOutcome",
    "boundaryOutcome",
    "failureOutcome",
)

ALLOWED_SYSTEM_GESTURES = {
    "back",
    "keyboard_done",
    "pull_to_refresh",
    "swipe_down",
    "swipe_left",
    "swipe_right",
    "swipe_up",
}


def valid_observable_target(target: object) -> bool:
    if not isinstance(target, dict):
        return False
    kind = target.get("kind")
    if kind in ("node", "node_absent"):
        return (
            bool(str(target.get("feature") or "").strip())
            and bool(str(target.get("board") or "").strip())
            and str(target.get("key") or "").startswith("iff:")
        )
    if kind in ("text", "text_absent"):
        return (
            bool(str(target.get("feature") or "").strip())
            and bool(str(target.get("board") or "").strip())
            and bool(str(target.get("value") or "").strip())
        )
    return False


def validate_contract(contract: dict) -> list[str]:
    failures: list[str] = []
    seen_ids: set[str] = set()
    for index, rule in enumerate(contract.get("rules") or []):
        label = rule.get("id") or f"rule[{index}]"
        if str(label) in seen_ids:
            failures.append(f"duplicate rule id: {label}")
        seen_ids.add(str(label))
        for field in REQUIRED_RULE_FIELDS:
            value = rule.get(field)
            if not isinstance(value, str) or not value.strip() or "__MODEL__" in value:
                failures.append(f"{label}: missing or unresolved {field}")
        target = rule.get("actionTarget")
        valid_target = False
        if isinstance(target, dict) and target.get("kind") == "node":
            valid_target = (
                bool(str(target.get("feature") or "").strip())
                and
                str(target.get("key") or "").startswith("iff:")
                and bool(str(target.get("board") or "").strip())
            )
            if not valid_target:
                failures.append(
                    f"{label}: node actionTarget requires feature, board and iff: key"
                )
        elif isinstance(target, dict) and target.get("kind") == "system":
            gesture = str(target.get("gesture") or "").strip()
            valid_target = gesture in ALLOWED_SYSTEM_GESTURES
            if gesture and not valid_target:
                failures.append(f"{label}: unsupported system gesture: {gesture}")
        if not valid_target and not (
            isinstance(target, dict) and target.get("kind") == "node"
        ):
            failures.append(f"{label}: missing or invalid actionTarget")
        observable_targets = rule.get("observableTargets") or {}
        for variant in ("happy", "boundary", "failure"):
            if not valid_observable_target(observable_targets.get(variant)):
                failures.append(
                    f"{label}: missing or invalid observableTargets.{variant}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    failures = validate_contract(contract)
    report = {"ok": not failures, "failures": failures}
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if failures:
        print(f"FAIL interaction contract ({len(failures)}):")
        for failure in failures:
            print("  - " + failure)
        return 1
    print(f"ok interaction contract: {len(contract.get('rules') or [])} rule(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
