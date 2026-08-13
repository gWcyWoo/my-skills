#!/usr/bin/env python3
"""Compile a feature's boards into a state-machine SKELETON.

A row's N state boards are N nodes of one page's state machine — treating them
only as visual variants throws the interaction semantics away. This script does
the deterministic part: nodes (one per board, with its classification/type and
which SHARED structure it carries) and empty edges with __MODEL__ placeholders.
The assembly worker's model fills each edge's trigger/condition (from 交互描述
+ board semantics + case memory), every filled edge then becomes an interaction
rule (INT-SM-xxx) appended to interaction_contract.json so it gets the standard
HAPPY/BOUNDARY/FAILURE case treatment.

--check fails while any __MODEL__ placeholder remains or an edge references an
unknown node.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import dump_json, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True, help="lanhu/specs/<feature>")
    parser.add_argument("--out", required=True, help="state_machine.json (feature-level)")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.spec_root).expanduser().resolve()

    if args.check:
        doc = load_json(args.out)
        raw = json.dumps(doc, ensure_ascii=False)
        problems = []
        if "__MODEL__" in raw:
            problems.append(f"{raw.count('__MODEL__')} unfilled __MODEL__ placeholder(s)")
        node_ids = {n["id"] for n in doc.get("nodes") or []}
        for e in doc.get("edges") or []:
            for end in ("from", "to"):
                if e.get(end) not in node_ids:
                    problems.append(f"edge {e.get('from')}->{e.get('to')}: unknown node {e.get(end)!r}")
        if not (doc.get("edges") or []) and len(node_ids) > 1:
            problems.append("multi-state feature has ZERO transitions — fill edges or record why in "
                            "'noTransitionReason'")
        if problems and not doc.get("noTransitionReason"):
            print("FAIL state machine:")
            for p in problems:
                print("  - " + p)
            return 1
        print(f"ok state machine: {len(node_ids)} states, {len(doc.get('edges') or [])} transitions")
        return 0

    nodes = []
    for board in sorted(d for d in root.iterdir() if d.is_dir()):
        try:
            classification = load_json(board / "design_classification.json")
        except FileNotFoundError:
            classification = {}
        shared = []
        try:
            shared = [{"name": c.get("name"), "kind": c.get("kind")}
                      for c in (load_json(board / "shared_components.local.json").get("components") or [])
                      if c.get("status") == "reuse"]
        except FileNotFoundError:
            pass
        nodes.append({
            "id": board.name,
            "spec_dir": str(board),
            "classificationType": classification.get("type"),
            "sharedComponents": shared,
            "meaning": "__MODEL__",  # one sentence: what business state this board represents
        })
    if not nodes:
        raise SystemExit(f"ERROR: no board dirs under {root}")

    skeleton = {
        "feature": root.name,
        "nodes": nodes,
        # The model REPLACES this template list with real transitions; each edge becomes
        # an INT-SM rule in interaction_contract.json.
        "edges": [
            {"from": "__MODEL__", "to": "__MODEL__",
             "trigger": "__MODEL__",   # user action or system event causing the transition
             "condition": "__MODEL__",  # guard (api result / validation / time), or null
             "ruleId": "__MODEL__"}     # INT-SM-001 style id appended to the contract
        ],
        "noTransitionReason": None,
        "modelFields": ["nodes[*].meaning", "edges (replace template with real transitions)"],
    }
    dump_json(skeleton, args.out)
    print(f"ok state-machine skeleton: {len(nodes)} states -> {args.out} "
          f"(model fills edges, then --check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
