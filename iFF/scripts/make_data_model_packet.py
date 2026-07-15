#!/usr/bin/env python3
"""Build one bounded data-semantics action for the model."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from model_context_contract import attach_write_contract, packet_source, write_model_packet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    parser.add_argument("--ledger")
    args = parser.parse_args()

    spec_root = Path(args.spec_root)
    bindings_path = spec_root / "data_slot_bindings.json"
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    unresolved = next(
        (
            entry
            for entry in bindings.get("bindings") or []
            if not (entry.get("binding") or {}).get("field")
            and not str(entry.get("staticReason") or "").strip()
        ),
        None,
    )
    unconfirmed = next(
        (
            entry
            for entry in bindings.get("bindings") or []
            if (entry.get("binding") or {}).get("field")
            and entry.get("confirmedByModel") is not True
        ),
        None,
    )
    gate_path = spec_root / "data_gate_report.json"
    gate_hash = None
    if unconfirmed is not None:
        binding = unconfirmed.get("binding") or {}
        action = {
            "kind": "confirm_field_binding",
            "state": unconfirmed.get("state"),
            "board": unconfirmed.get("board"),
            "node": unconfirmed.get("node"),
            "component": unconfirmed.get("component"),
            "designText": unconfirmed.get("designText"),
            "transform": binding.get("transform"),
            "field": binding.get("field"),
            "candidates": binding.get("compatibleCandidateFields")
            or binding.get("candidateFields")
            or [],
            "allowedDecisions": ["confirm_field", "change_field", "mark_static"],
            "writeBack": "confirmedByModel=true",
        }
    elif unresolved is None:
        failures = []
        if gate_path.is_file():
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            failures = gate.get("failures") or []
            gate_hash = hashlib.sha256(gate_path.read_bytes()).hexdigest()
        action = (
            {
                "kind": "run_deterministic_repair",
                "failure": failures[0],
                "requiresJudgment": False,
            }
            if failures
            else {"kind": "none", "reason": "data_gate_passed_or_not_run"}
        )
    else:
        binding = unresolved.get("binding") or {}
        candidates = binding.get("compatibleCandidateFields") or binding.get("candidateFields") or []
        selected_operation = binding.get("selectedOperation") or {}
        if selected_operation:
            candidates = [
                field
                for field in candidates
                if all(
                    field.get(key) == selected_operation.get(key)
                    for key in ("endpoint", "method", "status")
                )
            ]
        selected_group = binding.get("selectedFieldGroup")
        if selected_group is not None:
            if (
                isinstance(selected_group, bool)
                or not isinstance(selected_group, int)
                or selected_group < 0
                or selected_group * 10 >= len(candidates)
            ):
                raise SystemExit(
                    f"ERROR: invalid selectedFieldGroup for {unresolved.get('node')}: "
                    f"{selected_group!r}"
                )
            candidates = candidates[selected_group * 10 : (selected_group + 1) * 10]
        if len(candidates) > 20 and selected_operation:
            groups = [candidates[index : index + 10] for index in range(0, len(candidates), 10)]
            action = {
                "kind": "choose_field_group",
                "state": unresolved.get("state"),
                "board": unresolved.get("board"),
                "node": unresolved.get("node"),
                "component": unresolved.get("component"),
                "designText": unresolved.get("designText"),
                "transform": binding.get("transform"),
                "groups": [
                    {
                        "index": index,
                        "firstPath": group[0].get("jsonPath"),
                        "lastPath": group[-1].get("jsonPath"),
                        "candidateCount": len(group),
                    }
                    for index, group in enumerate(groups)
                ],
                "writeBack": "binding.selectedFieldGroup",
                "allowedDecisions": ["choose_field_group", "mark_static"],
                "staticWriteBack": "staticReason + confirmedByModel=true",
            }
        elif len(candidates) > 20:
            counts = Counter(
                (field.get("endpoint"), field.get("method"), field.get("status"))
                for field in candidates
            )
            operations = [
                {
                    "endpoint": endpoint,
                    "method": method,
                    "status": status,
                    "candidateCount": count,
                }
                for (endpoint, method, status), count in sorted(counts.items())
            ]
            action = {
                "kind": "choose_operation",
                "state": unresolved.get("state"),
                "board": unresolved.get("board"),
                "node": unresolved.get("node"),
                "component": unresolved.get("component"),
                "designText": unresolved.get("designText"),
                "transform": binding.get("transform"),
                "operations": operations,
                "writeBack": "binding.selectedOperation",
                "allowedDecisions": ["choose_operation", "mark_static"],
                "staticWriteBack": "staticReason + confirmedByModel=true",
            }
        else:
            action = {
                "kind": "choose_field",
                "state": unresolved.get("state"),
                "board": unresolved.get("board"),
                "node": unresolved.get("node"),
                "component": unresolved.get("component"),
                "designText": unresolved.get("designText"),
                "transform": binding.get("transform"),
                "candidates": candidates,
                "writeBack": "binding.field + confirmedByModel=true",
                "allowedDecisions": ["bind_field", "mark_static"],
                "staticWriteBack": "staticReason + confirmedByModel=true",
            }
    if action.get("kind") != "none" and not action.get("allowedDecisions"):
        action["allowedDecisions"] = ["execute"]
    target = unconfirmed if unconfirmed is not None else unresolved
    if target is not None:
        target_index = (bindings.get("bindings") or []).index(target)
        prefix = f"data_slot_bindings.json:bindings.{target_index}"
        static_paths = [
            f"{prefix}.staticReason",
            f"{prefix}.confirmedByModel",
        ]
        write_paths = {
            "confirm_field_binding": {
                "confirm_field": [f"{prefix}.confirmedByModel"],
                "change_field": [
                    f"{prefix}.binding.field",
                    f"{prefix}.confirmedByModel",
                ],
                "mark_static": static_paths,
            },
            "choose_field_group": {
                "choose_field_group": [f"{prefix}.binding.selectedFieldGroup"],
                "mark_static": static_paths,
            },
            "choose_operation": {
                "choose_operation": [f"{prefix}.binding.selectedOperation"],
                "mark_static": static_paths,
            },
            "choose_field": {
                "bind_field": [
                    f"{prefix}.binding.field",
                    f"{prefix}.confirmedByModel",
                ],
                "mark_static": static_paths,
            },
        }.get(str(action.get("kind")))
        if write_paths:
            attach_write_contract(action, write_paths)
    source_paths = {"data_slot_bindings.json": bindings_path}
    if gate_hash:
        source_paths["data_gate_report.json"] = gate_path
    packet = {
        "version": 2,
        "kind": "data",
        "scope": {"feature": spec_root.name},
        "sources": {
            name: packet_source(path) for name, path in source_paths.items()
        },
        "source": {
            "data_slot_bindings.json": hashlib.sha256(bindings_path.read_bytes()).hexdigest()
        },
        "action": action,
    }
    if gate_hash:
        packet["source"]["data_gate_report.json"] = gate_hash
    try:
        size = write_model_packet(
            packet,
            Path(args.out),
            max_bytes=args.max_bytes,
            ledger=(
                Path(args.ledger).expanduser().resolve()
                if args.ledger
                else spec_root / ".iff/model_context.jsonl"
            ),
            owner="assembly",
        )
    except ValueError as error:
        raise SystemExit(f"ERROR: data {error}") from error
    print(f"ok data model packet: action={action['kind']} bytes={size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
