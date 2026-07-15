#!/usr/bin/env python3
"""Bind required data case IDs to executable public-behavior test declarations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from data_test_cases import required_data_cases


def declared_blocks(test_root: Path, case_id: str, declaration: str) -> list[str]:
    pattern = re.compile(
        rf"\b{declaration}\s*\(\s*['\"][^'\"]*{re.escape(case_id)}"
    )
    blocks = []
    for path in sorted(test_root.rglob("*_test.dart")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            next_test = re.search(r"\b(?:testWidgets|test)\s*\(", text[match.end() :])
            end = match.end() + next_test.start() if next_test else len(text)
            blocks.append(text[match.start() : end])
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--test-root", required=True)
    args = parser.parse_args()

    bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8"))
    runtime = json.loads(Path(args.runtime_manifest).read_text(encoding="utf-8"))
    test_root = Path(args.test_root)
    slot_targets = {}
    slot_fields = {}
    for entry in bindings.get("bindings") or []:
        field = (entry.get("binding") or {}).get("field")
        if not field:
            continue
        state = entry.get("state")
        qualifier = f"{state}:" if state is not None else ""
        case_id = f"DATA-SLOT:{qualifier}{entry.get('node')}"
        slot_targets[case_id] = f"iff:{entry.get('node')}"
        slot_fields[case_id] = str(field.get("jsonPath") or "")
    operations = {
        f"DATA-REPO:{operation.get('id')}": operation
        for operation in runtime.get("operations") or []
    }
    state_targets = {
        f"DATA-STATE:{operation.get('id')}:{state}": (
            operation.get("stateTargets") or {}
        ).get(state)
        for operation in runtime.get("operations") or []
        for state in operation.get("requiredStates") or []
    }
    errors = []
    for case_id in required_data_cases(bindings, runtime):
        declaration = (
            "testWidgets"
            if case_id.startswith(("DATA-SLOT:", "DATA-STATE:"))
            else "test"
        )
        blocks = declared_blocks(test_root, case_id, declaration)
        if not blocks:
            errors.append(f"{case_id}: not declared in {declaration}")
            continue
        if case_id.startswith("DATA-REPO:"):
            if not any(re.search(r"\bHttpServer\.bind\s*\(", block) for block in blocks):
                errors.append(f"{case_id}: missing local HTTP boundary")
                continue
            operation = operations[case_id]
            public_method = str(operation.get("publicMethod") or operation.get("id") or "")
            public_call = re.compile(r"\." + re.escape(public_method) + r"\s*\(")
            if not any(public_call.search(block) for block in blocks):
                errors.append(
                    f"{case_id}: missing public repository call {public_method}"
                )
                continue
            method = str(operation.get("method") or "").upper()
            endpoint = str(operation.get("endpoint") or "")
            method_assertion = re.compile(
                r"\bexpect(?:Later)?\s*\(\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\.method"
                r"\s*,\s*['\"]"
                + re.escape(method)
                + r"['\"]"
            )
            endpoint_pattern = re.escape(endpoint)
            endpoint_pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/'\"]+", endpoint_pattern)
            path_assertion = re.compile(
                r"\bexpect(?:Later)?\s*\(\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\.uri\.path"
                r"\s*,\s*['\"]"
                + endpoint_pattern
                + r"['\"]"
            )
            if not any(
                method_assertion.search(block) and path_assertion.search(block)
                for block in blocks
            ):
                errors.append(
                    f"{case_id}: missing HTTP request assertion {method} {endpoint}"
                )
                continue
            status_assertion = re.compile(
                r"\bexpect(?:Later)?\s*\(\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\.statusCode"
                r"\s*,\s*200\b"
            )
            if not any(status_assertion.search(block) for block in blocks):
                errors.append(f"{case_id}: missing HTTP status assertion 200")
                continue
            has_mapped_result = False
            for block in blocks:
                assignments = re.findall(
                    r"\b([A-Za-z_]\w*)\s*=\s*await\s+"
                    r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\."
                    + re.escape(public_method)
                    + r"\s*\(",
                    block,
                )
                for variable in assignments:
                    result_assertion = re.compile(
                        r"\bexpect(?:Later)?\s*\(\s*"
                        + re.escape(variable)
                        + r"\.[A-Za-z_]\w*\s*,\s*(?!true\b|false\b)[^,)]+"
                    )
                    if result_assertion.search(block):
                        has_mapped_result = True
                        break
                if has_mapped_result:
                    break
            if not has_mapped_result:
                errors.append(f"{case_id}: missing mapped result assertion")
            continue
        if case_id.startswith("DATA-STATE:"):
            target = state_targets.get(case_id)
            if not (
                isinstance(target, dict)
                and isinstance(target.get("key"), str)
                and target.get("key")
                and isinstance(target.get("text"), str)
                and target.get("text")
            ):
                errors.append(f"{case_id}: missing structured state target key/text")
                continue
            if not any(
                re.search(r"\b(?:tester\.pumpWidget|app\.main)\s*\(", block)
                for block in blocks
            ):
                errors.append(f"{case_id}: missing public runtime surface")
                continue
            key = target["key"]
            key_assertion = re.compile(
                r"find\.byKey\s*\(\s*(?:const\s+)?ValueKey(?:<[^>]+>)?\s*\(\s*['\"]"
                + re.escape(key)
                + r"['\"]"
            )
            if not any(key_assertion.search(block) for block in blocks):
                errors.append(f"{case_id}: missing exact state target {key}")
                continue
            text = target["text"]
            text_assertion = re.compile(
                r"\bexpect(?:Later)?\s*\(\s*find\.text\s*\(\s*['\"]"
                + re.escape(text)
                + r"['\"]"
            )
            if not any(text_assertion.search(block) for block in blocks):
                errors.append(f"{case_id}: missing visible state text {text}")
            continue
        if case_id.startswith("DATA-SLOT:") and not any(
            re.search(r"\b(?:tester\.pumpWidget|app\.main)\s*\(", block)
            for block in blocks
        ):
            errors.append(f"{case_id}: missing public runtime surface")
            continue
        if case_id.startswith("DATA-SLOT:"):
            key = slot_targets[case_id]
            target = re.compile(
                r"find\.byKey\s*\(\s*(?:const\s+)?ValueKey(?:<[^>]+>)?\s*\(\s*['\"]"
                + re.escape(key)
                + r"['\"]"
            )
            if not any(target.search(block) for block in blocks):
                errors.append(f"{case_id}: missing exact slot target {key}")
                continue
            field_path = slot_fields[case_id]
            field_literal = re.compile(r"['\"]" + re.escape(field_path) + r"['\"]")
            if not any(field_literal.search(block) for block in blocks):
                errors.append(f"{case_id}: missing bound field {field_path}")
                continue
            visible_values = {
                value
                for block in blocks
                for value in re.findall(
                    r"\bexpect(?:Later)?\s*\(\s*find\.text\s*\(\s*['\"]([^'\"]+)['\"]",
                    block,
                )
            }
            if len(visible_values) < 2:
                errors.append(f"{case_id}: needs two distinct visible assertions")
                continue
            field_parts = [part for part in re.split(r"[.\[\]]+", field_path) if part and part != "$"]
            field_name = field_parts[-1] if field_parts else ""
            input_values = {
                value.strip()
                for block in blocks
                for value in re.findall(
                    r"['\"]"
                    + re.escape(field_name)
                    + r"['\"]\s*:\s*([^,}\n]+)",
                    block,
                )
            }
            if len(input_values) < 2:
                errors.append(f"{case_id}: needs two distinct bound field inputs")

    if errors:
        raise SystemExit(
            "ERROR: invalid data coverage:\n" + "\n".join(f"- {error}" for error in errors)
        )
    print("ok data coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
