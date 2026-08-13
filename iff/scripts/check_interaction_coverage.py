#!/usr/bin/env python3
"""Check interaction test mapping and red/green evidence before done."""

from __future__ import annotations

import argparse
import hashlib
import re
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PUBLIC_WIDGET_ACTION = re.compile(
    r"\btester\.(?:tap|enterText|drag|dragFrom|fling|flingFrom|longPress|pageBack)\s*\("
)


def observable_assertion_pattern(target: dict) -> re.Pattern[str] | None:
    kind = target.get("kind")
    matcher = "findsNothing" if kind in ("node_absent", "text_absent") else "findsOneWidget"
    if kind in ("text", "text_absent"):
        finder = (
            r"find\.text\s*\(\s*['\"]"
            + re.escape(str(target.get("value") or ""))
            + r"['\"]\s*\)"
        )
    elif kind in ("node", "node_absent"):
        finder = (
            r"find\.byKey\s*\(\s*(?:const\s+)?ValueKey(?:<[^>]+>)?\s*\(\s*['\"]"
            + re.escape(str(target.get("key") or ""))
            + r"['\"]\s*\)\s*\)"
        )
    else:
        return None
    return re.compile(
        r"\bexpect(?:Later)?\s*\(\s*" + finder + r"\s*,\s*" + matcher + r"\b"
    )


def evidence_ok(evidence: dict) -> list[str]:
    errors = []
    red = evidence.get("red") or {}
    green = evidence.get("green") or {}
    red_code = red.get("exitCode", red.get("exit_code"))
    green_code = green.get("exitCode", green.get("exit_code"))
    if red_code in (None, 0):
        errors.append("red evidence must exist and have non-zero exit_code")
    if green_code != 0:
        errors.append("green evidence must exist and have exit_code 0")
    if not red.get("command"):
        errors.append("red evidence missing command")
    if not green.get("command"):
        errors.append("green evidence missing command")
    for phase, phase_evidence in (("red", red), ("green", green)):
        command = phase_evidence.get("command")
        if command and not (
            isinstance(command, list)
            and len(command) >= 3
            and Path(str(command[0])).name == "flutter"
            and command[1] == "test"
            and "--machine" in command[2:]
        ):
            errors.append(f"{phase} evidence command must be flutter test --machine")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    plan = load_json(plan_path)
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
        declaration = re.compile(
            r"testWidgets\s*\(\s*['\"][^'\"]*" + re.escape(case_id)
        )
        declared_bodies = []
        for path in matches:
            text = haystack[path]
            match = declaration.search(text)
            if not match:
                continue
            next_test = re.search(r"\btestWidgets\s*\(", text[match.end():])
            end = match.end() + next_test.start() if next_test else len(text)
            declared_bodies.append((path, text[match.start():end]))
        if not declared_bodies:
            errors.append(f"{case_id}: not declared in testWidgets")
            continue
        if not any(
            re.search(r"\btester\.pumpWidget\s*\(", body)
            for _, body in declared_bodies
        ):
            errors.append(f"{case_id}: missing tester.pumpWidget runtime surface")
            continue
        if not any(PUBLIC_WIDGET_ACTION.search(body) for _, body in declared_bodies):
            errors.append(f"{case_id}: missing public WidgetTester action")
            continue
        if not any(re.search(r"\bexpect(?:Later)?\s*\(", body) for _, body in declared_bodies):
            errors.append(f"{case_id}: missing observable assertion")
            continue
        action_target = case.get("actionTarget") or {}
        if action_target.get("kind") == "node":
            key = str(action_target.get("key") or "")
            action_key_pattern = re.compile(
                r"\btester\.(?:tap|enterText|drag|dragFrom|fling|flingFrom|longPress)\s*\(\s*"
                r"find\.byKey\s*\(\s*(?:const\s+)?ValueKey(?:<[^>]+>)?\s*\(\s*['\"]"
                + re.escape(key)
                + r"['\"]"
            )
            if not any(action_key_pattern.search(body) for _, body in declared_bodies):
                errors.append(
                    f"{case_id}: missing planned actionTarget key {key}; "
                    f"action does not use planned target {key}"
                )
                continue
        elif action_target.get("kind") == "system":
            gesture = str(action_target.get("gesture") or "")
            gesture_patterns = {
                "back": re.compile(r"\btester\.pageBack\s*\("),
                "keyboard_done": re.compile(
                    r"\btester\.testTextInput\.receiveAction\s*\(\s*TextInputAction\.done"
                ),
                "pull_to_refresh": re.compile(r"\btester\.(?:drag|fling)\s*\("),
                "swipe_down": re.compile(r"\btester\.(?:drag|fling)\s*\("),
                "swipe_left": re.compile(r"\btester\.(?:drag|fling)\s*\("),
                "swipe_right": re.compile(r"\btester\.(?:drag|fling)\s*\("),
                "swipe_up": re.compile(r"\btester\.(?:drag|fling)\s*\("),
            }
            gesture_pattern = gesture_patterns.get(gesture)
            if gesture_pattern is None or not any(
                gesture_pattern.search(body) for _, body in declared_bodies
            ):
                errors.append(f"{case_id}: missing planned system gesture {gesture}")
                continue
        observable_target = case.get("expectedObservableTarget") or {}
        if observable_target:
            assertion_pattern = observable_assertion_pattern(observable_target)
            if assertion_pattern is None or not any(
                assertion_pattern.search(body) for _, body in declared_bodies
            ):
                errors.append(
                    f"{case_id}: assertion does not verify planned observable "
                    f"{observable_target}"
                )
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
        current_plan_hash = sha256(plan_path)
        current_test_hashes = {
            str(path.relative_to(test_root)): sha256(path)
            for path in sorted(files)
        }
        for phase in ("red", "green"):
            phase_evidence = evidence.get(phase) or {}
            if phase_evidence.get("planHash") != current_plan_hash:
                errors.append(f"{phase}: stale planHash")
            if phase_evidence.get("testHashes") != current_test_hashes:
                errors.append(f"{phase}: stale testHashes")
        red_cases = (evidence.get("red") or {}).get("cases") or {}
        green_cases = (evidence.get("green") or {}).get("cases") or {}
        for case in cases:
            case_id = case["id"]
            if case_id not in red_cases:
                errors.append(f"{case_id}: missing red case evidence mapping")
            green_case = green_cases.get(case_id)
            if not green_case:
                errors.append(f"{case_id}: missing green case evidence mapping")
            elif green_case.get("result") != "success" or green_case.get("skipped"):
                errors.append(f"{case_id}: green case did not execute successfully")

    if errors:
        raise SystemExit("ERROR: interaction coverage failed:\n" + "\n".join(errors))
    print(f"ok interaction coverage cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
