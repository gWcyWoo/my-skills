"""Run the bounded interaction-completeness promotion pass.

The initial completeness failure is expected input, not a worker stop condition. Every
reported occurrence is removed from ``ignoredItems`` in report order. Exact duplicates
of existing rules and overlapping/duplicate reported occurrences are recorded as
deduplicated actions; one longest canonical occurrence per overlap group is promoted.
The caller owns test-plan regeneration and the single final completeness rerun.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

from check_interaction_completeness import EFFECT, TRIGGER, looks_like_rule
from parse_interactions import split_trigger_expectation


CHECK = Path(__file__).with_name("check_interaction_completeness.py")
RULE_ID = re.compile(r"^INT-(\d+)$")


def normalize(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def item_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def overlaps(left: str, right: str) -> bool:
    return bool(left and right and (left in right or right in left))


def derive_semantics(source: str) -> tuple[str, str]:
    trigger, expectation = split_trigger_expectation(source)
    if trigger and expectation:
        return trigger.strip(), expectation.strip()

    trigger_match = TRIGGER.search(source)
    effect_match = EFFECT.search(source)
    if not trigger_match or not effect_match:
        raise ValueError(f"reported occurrence has no deterministic trigger/effect split: {source}")

    if trigger_match.start() <= effect_match.start():
        trigger = source[: effect_match.start()].strip(" \t\r\n，,；;。:")
        expectation = source[effect_match.start() :].strip()
    else:
        trigger = source[trigger_match.start() :].strip()
        expectation = source.strip()
    if not trigger or not expectation:
        raise ValueError(f"reported occurrence produced an empty trigger/expectation: {source}")
    return trigger, expectation


def next_rule_number(rules: list[object]) -> int:
    numbers: list[int] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        match = RULE_ID.fullmatch(str(rule.get("id") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def run_initial_completeness(contract: Path, report: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(CHECK), "--contract", str(contract), "--out", str(report)],
        text=True,
        capture_output=True,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stdout + completed.stderr)
    return json.loads(report.read_text(encoding="utf-8"))


def reported_occurrences(
    contract: dict[str, object], report: dict[str, object]
) -> list[dict[str, object]]:
    ignored = contract.get("ignoredItems") or []
    acknowledgements = contract.get("acknowledgedNonRules") or []
    if not isinstance(ignored, list) or not isinstance(acknowledgements, list):
        raise ValueError("ignoredItems and acknowledgedNonRules must be arrays")

    acknowledgement_counts = Counter(normalize(value) for value in acknowledgements)
    occurrences: list[dict[str, object]] = []
    for ignored_index, value in enumerate(ignored):
        source = item_text(value)
        if not looks_like_rule(source):
            continue
        normalized = normalize(source)
        if acknowledgement_counts[normalized] > 0:
            acknowledgement_counts[normalized] -= 1
            continue
        occurrences.append(
            {
                "reportIndex": len(occurrences),
                "ignoredIndex": ignored_index,
                "source": source.strip(),
                "normalized": normalized,
            }
        )

    unmatched_acknowledgements = [
        value for value, count in acknowledgement_counts.items() if count > 0
    ]
    if unmatched_acknowledgements:
        raise ValueError(
            "acknowledgedNonRules must match exact normalized reported occurrences: "
            + json.dumps(unmatched_acknowledgements, ensure_ascii=False)
        )

    reported = report.get("suspectedMissedRules") or []
    if not isinstance(reported, list):
        raise ValueError("suspectedMissedRules must be an array")
    actual_sources = [entry["source"] for entry in occurrences]
    if actual_sources != reported:
        raise ValueError("completeness report does not identify exact ignored occurrences")
    return occurrences


def overlap_groups(entries: list[dict[str, object]]) -> list[list[int]]:
    parent = list(range(len(entries)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(entries)):
        for right in range(left + 1, len(entries)):
            if overlaps(str(entries[left]["normalized"]), str(entries[right]["normalized"])):
                union(left, right)

    grouped: dict[int, list[int]] = {}
    for index in range(len(entries)):
        grouped.setdefault(find(index), []).append(index)
    return sorted(grouped.values(), key=min)


def promote(contract_path: Path, report_path: Path, out_path: Path) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("interaction contract must be an object")
    report = run_initial_completeness(contract_path, report_path)
    occurrences = reported_occurrences(contract, report)
    rules = contract.get("rules") or []
    ignored = contract.get("ignoredItems") or []
    if not isinstance(rules, list) or not isinstance(ignored, list):
        raise ValueError("rules and ignoredItems must be arrays")

    existing_sources = {
        normalize(rule.get("source"))
        for rule in rules
        if isinstance(rule, dict) and rule.get("source")
    }
    actions: list[dict[str, object] | None] = [None] * len(occurrences)
    candidates: list[dict[str, object]] = []
    for entry in occurrences:
        if entry["normalized"] in existing_sources:
            actions[int(entry["reportIndex"])] = {
                **entry,
                "action": "deduplicated_existing_rule",
            }
        else:
            candidates.append(entry)

    promoted_rule_ids: list[str] = []
    next_number = next_rule_number(rules)
    for group in overlap_groups(candidates):
        members = [candidates[index] for index in group]
        canonical = max(
            members,
            key=lambda entry: (len(str(entry["normalized"])), -int(entry["reportIndex"])),
        )
        rule_id = f"INT-{next_number:03d}"
        next_number += 1
        trigger, expectation = derive_semantics(str(canonical["source"]))
        rules.append(
            {
                "id": rule_id,
                "source": canonical["source"],
                "trigger": trigger,
                "expectation": expectation,
                "coverageRequired": ["happy", "boundary", "failure"],
                "testCaseIdsRequired": [
                    f"{rule_id}-HAPPY",
                    f"{rule_id}-BOUNDARY",
                    f"{rule_id}-FAILURE",
                ],
            }
        )
        promoted_rule_ids.append(rule_id)
        for entry in members:
            report_index = int(entry["reportIndex"])
            actions[report_index] = {
                **entry,
                "action": "promoted" if entry is canonical else "deduplicated_overlap",
                "ruleId": rule_id,
                "canonicalReportIndex": canonical["reportIndex"],
            }

    remove_indices = {int(entry["ignoredIndex"]) for entry in occurrences}
    contract["rules"] = rules
    contract["ignoredItems"] = [
        value for index, value in enumerate(ignored) if index not in remove_indices
    ]
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    resolved_actions = [action for action in actions if action is not None]
    promotion_report = {
        "initialCompletenessRuns": 1,
        "finalCompletenessPending": True,
        "initialRuleCount": report.get("ruleCount", len(rules) - len(promoted_rule_ids)),
        "reportedOccurrenceCount": len(occurrences),
        "promotedRuleIds": promoted_rule_ids,
        "deduplicatedOccurrenceCount": sum(
            str(action["action"]).startswith("deduplicated")
            for action in resolved_actions
        ),
        "acknowledgedNonRuleCount": report.get("acknowledgedNonRules", 0),
        "finalRuleCount": len(rules),
        "actions": resolved_actions,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(promotion_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--completeness-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        promote(Path(args.contract), Path(args.completeness_report), Path(args.out))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"interaction promotion failed: {error}")
        return 1
    print(f"interaction promotion ok: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
