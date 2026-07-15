#!/usr/bin/env python3
"""Fail when a registered shared component changed without consumer re-verification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from check_visual_board import validate_board


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    project_root = Path(args.project_root).expanduser().resolve()
    failures: list[str] = []

    for component in (registry.get("components") or {}).values():
        family = component.get("family_id") or component.get("name") or "unknown"
        consumers = [str(item.get("id")) for item in component.get("consumers") or []]
        contract_path = component.get("contract_path")
        expected_contract_hash = component.get("contract_sha256")
        if contract_path or expected_contract_hash:
            contract = Path(str(contract_path or ""))
            if not contract.is_absolute():
                contract = project_root / contract
            if (
                not contract_path
                or not contract.is_file()
                or not expected_contract_hash
                or sha256(contract) != expected_contract_hash
            ):
                failures.append(
                    f"{family} contract changed; reverify consumers: "
                    f"{', '.join(consumers) or '(none registered)'}"
                )
                continue
        widget_path = component.get("widget_path")
        expected_hash = component.get("widget_source_sha256")
        widget = project_root / str(widget_path or "")
        if not widget_path or not widget.is_file() or not expected_hash or sha256(widget) != expected_hash:
            failures.append(f"{family} changed; reverify consumers: {', '.join(consumers) or '(none registered)'}")
            continue

        for consumer in component.get("consumers") or []:
            gate_path = consumer.get("visual_gate")
            gate = project_root / str(gate_path or "")
            gate_doc = json.loads(gate.read_text(encoding="utf-8")) if gate_path and gate.is_file() else {}
            if gate_doc.get("ok") is not True:
                failures.append(
                    f"{family} consumer visual gate failed: {consumer.get('id') or '(unknown)'}"
                )
                continue
            component_inputs = gate_doc.get("componentInputs") or {}
            expected_input: object = expected_hash
            if expected_contract_hash:
                expected_input = {
                    "widget": expected_hash,
                    "contract": expected_contract_hash,
                }
            if component_inputs.get(family) != expected_input:
                failures.append(
                    f"{family} consumer visual gate is stale: {consumer.get('id') or '(unknown)'}"
                )
                continue
            board_failures = validate_board(gate.parent, gate.name)
            if board_failures:
                failures.append(
                    f"{family} consumer has stale board evidence: "
                    f"{consumer.get('id') or '(unknown)'} ({board_failures[0]})"
                )

    if failures:
        print(f"FAIL shared component consumers ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("ok shared component consumers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
