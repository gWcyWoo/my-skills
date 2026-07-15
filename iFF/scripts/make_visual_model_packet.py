#!/usr/bin/env python3
"""Build one bounded, current-state packet for visual model judgment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from model_context_contract import packet_source, write_model_packet


def load_optional(path: Path) -> dict | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_at_path(document: object, path: str) -> object:
    current = document
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    parser.add_argument("--ledger")
    args = parser.parse_args()

    spec = Path(args.spec_dir).expanduser().resolve()
    digest_path = spec / "artifact_digest.json"
    if not digest_path.is_file():
        print(f"ERROR: artifact digest missing: {digest_path}")
        return 1
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    inputs = {"artifact_digest.json": sha256(digest_path)}

    facts = {
        key: digest.get(key)
        for key in ("classification", "scene", "renderPlan", "sharedComponents")
        if digest.get(key) is not None
    }
    action: dict = {"kind": "run_visual_verification"}

    shared_path = spec / "shared_components.local.json"
    shared = load_optional(shared_path)
    candidates = sorted([
        {
            key: component.get(key)
            for key in ("signature", "kind", "model_decision")
        }
        for component in (shared or {}).get("components") or []
        if component.get("status") == "candidate"
    ], key=lambda component: str(component.get("signature") or ""))
    if candidates:
        inputs[shared_path.name] = sha256(shared_path)
        action = {"kind": "resolve_component_semantics", "candidate": candidates[0]}
    else:
        plan_path = spec / "implementation_plan.json"
        plan = load_optional(plan_path)
        if plan and "__MODEL__" in plan_path.read_text(encoding="utf-8"):
            inputs[plan_path.name] = sha256(plan_path)
            model_fields = plan.get("modelFields") or []
            unresolved = [
                field
                for field in model_fields
                if isinstance(field, dict)
                and isinstance(field.get("path"), str)
                and value_at_path(plan, field["path"]) == "__MODEL__"
            ]
            if not unresolved:
                print(
                    "ERROR: __MODEL__ placeholder is not declared in modelFields",
                )
                return 1
            action = {
                "kind": "fill_plan_judgment",
                "modelField": unresolved[0],
            }
        else:
            gate_path = spec / "visual_gate_report.json"
            gate = load_optional(gate_path)
            if gate:
                inputs[gate_path.name] = sha256(gate_path)
                if gate.get("ok") is True:
                    action = {"kind": "none", "reason": "visual_gate_passed"}
                else:
                    hard_failures = gate.get("hardFailures") or []
                    action = {
                        "kind": "fix_hard_failure",
                        "hardFailure": hard_failures[0] if hard_failures else None,
                    }
            else:
                repair_path = spec / "repair_plan_top.json"
                repair = load_optional(repair_path)
                if repair and repair.get("topAction"):
                    inputs[repair_path.name] = sha256(repair_path)
                    action = {
                        "kind": "apply_one_repair",
                        "summary": repair.get("summary"),
                        "topAction": repair.get("topAction"),
                    }

    if action.get("kind") != "none" and not action.get("allowedDecisions"):
        action["allowedDecisions"] = {
            "resolve_component_semantics": ["reuse", "independent"],
            "fill_plan_judgment": ["set_value"],
            "run_visual_verification": ["execute"],
            "fix_hard_failure": ["repair"],
            "apply_one_repair": ["apply"],
        }.get(str(action.get("kind")), ["apply"])
    sources = {
        name: packet_source(spec / name)
        for name in inputs
    }
    packet = {
        "version": 2,
        "kind": "visual",
        "scope": {"feature": spec.parent.name, "board": spec.name},
        "sources": sources,
        "board": spec.name,
        "inputs": inputs,
        "facts": facts,
        "action": action,
    }
    out = Path(args.out)
    ledger = (
        Path(args.ledger).expanduser().resolve()
        if args.ledger
        else spec.parent / ".iff/model_context.jsonl"
    )
    try:
        size = write_model_packet(
            packet,
            out,
            max_bytes=args.max_bytes,
            ledger=ledger,
            owner=f"board--{spec.name}",
        )
    except ValueError as error:
        print(f"ERROR: visual {error}")
        return 1
    print(f"ok visual model packet: {size} bytes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
