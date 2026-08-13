#!/usr/bin/env python3
"""Build one bounded current-fact packet for one shared-component semantic decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from model_context_contract import packet_source, write_model_packet


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: expected JSON object: {path}")
    return value


def candidate_projection(component: dict, by_signature: dict[str, dict]) -> dict:
    return {
        "signature": component.get("signature"),
        "kind": component.get("kind"),
        "variations": component.get("variations") or [],
        "rows": [
            {
                key: row.get(key)
                for key in ("spec_dir", "group_name", "kind", "bbox")
                if row.get(key) is not None
            }
            for row in component.get("rows") or []
        ],
        "modelDecision": component.get("model_decision"),
        "relatedCandidates": [
            {
                "signature": signature,
                "kind": related.get("kind"),
                "groupNames": sorted(
                    {
                        str(row.get("group_name"))
                        for row in related.get("rows") or []
                        if row.get("group_name")
                    }
                ),
            }
            for signature in component.get("related_signatures") or []
            if (related := by_signature.get(str(signature))) is not None
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--business-facts")
    parser.add_argument("--feature", default="shared")
    parser.add_argument("--ledger")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    args = parser.parse_args()

    batch_path = Path(args.batch).expanduser().resolve()
    batch = load_object(batch_path)
    candidates = sorted(
        (
            component
            for component in batch.get("components") or []
            if component.get("status") == "candidate"
        ),
        key=lambda component: str(component.get("signature") or ""),
    )
    by_signature = {
        str(component.get("signature")): component
        for component in batch.get("components") or []
        if component.get("signature")
    }
    inputs = {batch_path.name: sha256(batch_path)}
    source_paths = {batch_path.name: batch_path}
    business_facts: dict = {}
    if args.business_facts:
        facts_path = Path(args.business_facts).expanduser().resolve()
        business_facts = load_object(facts_path)
        inputs[facts_path.name] = sha256(facts_path)
        source_paths[facts_path.name] = facts_path

    action = (
        {
            "kind": "resolve_component_semantics",
            "candidate": candidate_projection(candidates[0], by_signature),
        }
        if candidates
        else {"kind": "none", "reason": "no_unresolved_component_candidate"}
    )
    if action.get("kind") != "none":
        action["allowedDecisions"] = ["reuse", "independent"]
    packet = {
        "version": 2,
        "kind": "component",
        "scope": {"feature": args.feature},
        "sources": {
            name: packet_source(path) for name, path in source_paths.items()
        },
        "inputs": inputs,
        "businessFacts": business_facts,
        "action": action,
    }
    out = Path(args.out)
    try:
        size = write_model_packet(
            packet,
            out,
            max_bytes=args.max_bytes,
            ledger=Path(args.ledger).expanduser().resolve() if args.ledger else None,
            owner=f"feature--{args.feature}",
        )
    except ValueError as error:
        print(f"ERROR: component {error}")
        return 1
    print(f"ok component model packet: {size} bytes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
