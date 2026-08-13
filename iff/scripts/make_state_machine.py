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
import hashlib
import json
from pathlib import Path

from common import dump_json, load_json


STATE_INPUT_FILES = (
    "design_classification.json",
    "scene.json",
    "shared_components.local.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def board_inputs_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for board in sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    ):
        digest.update(board.name.encode("utf-8"))
        for name in STATE_INPUT_FILES:
            path = board / name
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True, help="lanhu/specs/<feature>")
    parser.add_argument("--out", required=True, help="state_machine.json (feature-level)")
    parser.add_argument("--contract", help="interaction_contract.json used to validate edge ruleId")
    parser.add_argument("--feature-manifest", help="feature manifest used to validate state boards")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.spec_root).expanduser().resolve()

    if args.check:
        doc = load_json(args.out)
        raw = json.dumps(doc, ensure_ascii=False)
        problems = []
        inputs = doc.get("inputs") or {}
        if (args.contract or args.feature_manifest) and (
            doc.get("version") != 2 or not inputs
        ):
            problems.append("missing current input fingerprints")
        if inputs:
            if inputs.get("boards") != board_inputs_hash(root):
                problems.append("stale board inputs")
            if args.contract and inputs.get("contract") != sha256(Path(args.contract)):
                problems.append("stale contract input")
            if (
                args.feature_manifest
                and inputs.get("featureManifest") != sha256(Path(args.feature_manifest))
            ):
                problems.append("stale feature manifest input")
        if "__MODEL__" in raw:
            problems.append(f"{raw.count('__MODEL__')} unfilled __MODEL__ placeholder(s)")
        node_ids = {n["id"] for n in doc.get("nodes") or []}
        for node in doc.get("nodes") or []:
            if not str(node.get("meaning") or "").strip():
                problems.append(f"state {node.get('id')}: missing meaning")
        if args.feature_manifest:
            manifest = load_json(args.feature_manifest)
            manifest_boards = {
                str(value.get("board") or state)
                for state, value in (manifest.get("states") or {}).items()
                if isinstance(value, dict)
            }
            if node_ids != manifest_boards:
                problems.append(
                    "nodes do not match feature manifest boards: "
                    f"machine={sorted(node_ids)} manifest={sorted(manifest_boards)}"
                )
        contract_rule_ids = None
        if args.contract:
            contract_rule_ids = {
                rule.get("id")
                for rule in (load_json(args.contract).get("rules") or [])
            }
        transitions: dict[tuple[object, object, object], object] = {}
        seen_edges: set[tuple[object, object, object, object, object]] = set()
        adjacency: dict[object, set] = {}
        for e in doc.get("edges") or []:
            if not str(e.get("trigger") or "").strip():
                problems.append(
                    f"edge {e.get('from')}->{e.get('to')}: missing trigger"
                )
            edge_key = (
                e.get("from"),
                e.get("to"),
                e.get("trigger"),
                e.get("condition"),
                e.get("ruleId"),
            )
            if edge_key in seen_edges:
                problems.append(
                    f"duplicate edge {e.get('from')}->{e.get('to')} "
                    f"trigger={e.get('trigger')!r}"
                )
            seen_edges.add(edge_key)
            for end in ("from", "to"):
                if e.get(end) not in node_ids:
                    problems.append(f"edge {e.get('from')}->{e.get('to')}: unknown node {e.get(end)!r}")
            if contract_rule_ids is not None and e.get("ruleId") not in contract_rule_ids:
                problems.append(
                    f"edge {e.get('from')}->{e.get('to')}: ruleId not found in contract: "
                    f"{e.get('ruleId')!r}"
                )
            transition_key = (e.get("from"), e.get("trigger"), e.get("condition"))
            previous_target = transitions.get(transition_key)
            if previous_target is not None and previous_target != e.get("to"):
                problems.append(
                    "conflicting transition for "
                    f"from={e.get('from')!r} trigger={e.get('trigger')!r} "
                    f"condition={e.get('condition')!r}: "
                    f"{previous_target!r} vs {e.get('to')!r}"
                )
            transitions[transition_key] = e.get("to")
            adjacency.setdefault(e.get("from"), set()).add(e.get("to"))
        initial_state = doc.get("initialState")
        if len(node_ids) > 1 and initial_state not in node_ids:
            problems.append(f"invalid or missing initialState: {initial_state!r}")
        elif initial_state in node_ids:
            reachable = set()
            pending = [initial_state]
            while pending:
                state = pending.pop()
                if state in reachable:
                    continue
                reachable.add(state)
                pending.extend(adjacency.get(state, set()) - reachable)
            unreachable = sorted(node_ids - reachable)
            if unreachable:
                problems.append(f"unreachable states from {initial_state!r}: {unreachable}")
        if (
            not (doc.get("edges") or [])
            and len(node_ids) > 1
            and not str(doc.get("noTransitionReason") or "").strip()
        ):
            problems.append("multi-state feature has ZERO transitions — fill edges or record why in "
                            "'noTransitionReason'")
        if problems:
            print("FAIL state machine:")
            for p in problems:
                print("  - " + p)
            return 1
        print(f"ok state machine: {len(node_ids)} states, {len(doc.get('edges') or [])} transitions")
        return 0

    nodes = []
    for board in sorted(
        d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
    ):
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
        "version": 2,
        "feature": root.name,
        "inputs": {
            "boards": board_inputs_hash(root),
            **({"contract": sha256(Path(args.contract))} if args.contract else {}),
            **(
                {"featureManifest": sha256(Path(args.feature_manifest))}
                if args.feature_manifest
                else {}
            ),
        },
        "initialState": "__MODEL__",
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
        "modelFields": [
            "initialState",
            "nodes[*].meaning",
            "edges (replace template with real transitions)",
        ],
    }
    dump_json(skeleton, args.out)
    print(f"ok state-machine skeleton: {len(nodes)} states -> {args.out} "
          f"(model fills edges, then --check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
