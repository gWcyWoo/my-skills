#!/usr/bin/env python3
"""Emit one bounded interaction judgment for the model; keep full artifacts script-side."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from check_interaction_contract import ALLOWED_SYSTEM_GESTURES, valid_observable_target
from model_context_contract import attach_write_contract, packet_source, write_model_packet


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def unresolved_fields(rule: dict) -> list[str]:
    missing = []
    for field in (
        "action",
        "observableOutcome",
        "boundaryOutcome",
        "failureOutcome",
    ):
        value = rule.get(field)
        if not isinstance(value, str) or not value.strip() or "__MODEL__" in value:
            missing.append(field)
    target = rule.get("actionTarget") or {}
    valid_target = False
    if target.get("kind") == "node":
        valid_target = (
            bool(str(target.get("feature") or "").strip())
            and bool(str(target.get("board") or "").strip())
            and str(target.get("key") or "").startswith("iff:")
        )
    elif target.get("kind") == "system":
        valid_target = target.get("gesture") in ALLOWED_SYSTEM_GESTURES
    if not valid_target:
        missing.append("actionTarget")
    observable_targets = rule.get("observableTargets") or {}
    for variant in ("happy", "boundary", "failure"):
        if not valid_observable_target(observable_targets.get(variant)):
            missing.append(f"observableTargets.{variant}")
    return missing


def placeholder_paths(value: object, prefix: str) -> list[str]:
    if isinstance(value, dict):
        return [
            path
            for key, child in value.items()
            for path in placeholder_paths(child, f"{prefix}.{key}")
        ]
    if isinstance(value, list):
        return [
            path
            for index, child in enumerate(value)
            for path in placeholder_paths(child, f"{prefix}.{index}")
        ]
    return [prefix] if "__MODEL__" in str(value or "") else []


def attach_interaction_write_contract(
    action: dict,
    contract: dict,
    state_machine: dict | None,
    anchors: dict | None,
) -> None:
    kind = str(action.get("kind") or "")
    paths_by_decision: dict[str, list[str]] | None = None
    if kind == "classify_compound_rule":
        target = "contract:compoundDecisions.-"
        paths_by_decision = {"single": [target], "split": [target]}
    elif kind == "classify_interaction_item":
        paths_by_decision = {
            "rule": ["contract:rules.-"],
            "non_rule_with_reason": ["contract:acknowledgedNonRules.-"],
        }
    elif kind in {"choose_action_target_board", "complete_rule_semantics"}:
        rule_index = next(
            (
                index
                for index, rule in enumerate(contract.get("rules") or [])
                if rule.get("id") == action.get("ruleId")
            ),
            None,
        )
        if rule_index is not None:
            fields = (
                ["actionTargetScope"]
                if kind == "choose_action_target_board"
                else list(action.get("missingFields") or [])
            )
            paths_by_decision = {
                "apply": [f"contract:rules.{rule_index}.{field}" for field in fields]
            }
    elif kind == "define_state_meaning" and state_machine is not None:
        node_index = next(
            (
                index
                for index, node in enumerate(state_machine.get("nodes") or [])
                if node.get("id") == action.get("stateId")
            ),
            None,
        )
        if node_index is not None:
            paths_by_decision = {"apply": [f"stateMachine:nodes.{node_index}.meaning"]}
    elif kind == "choose_initial_state":
        paths_by_decision = {"apply": ["stateMachine:initialState"]}
    elif kind == "define_transition" and action.get("edgeIndex") is not None:
        edge_index = int(action["edgeIndex"])
        paths_by_decision = {
            "apply": placeholder_paths(
                action.get("currentEdge") or {}, f"stateMachine:edges.{edge_index}"
            )
        }
    elif kind == "confirm_anchor" and anchors is not None:
        anchor_index = next(
            (
                index
                for index, anchor in enumerate(anchors.get("anchors") or [])
                if anchor.get("rule") == action.get("ruleId")
            ),
            None,
        )
        if anchor_index is not None:
            prefix = f"anchors:anchors.{anchor_index}"
            paths_by_decision = {
                "confirmed_candidate": [f"{prefix}.confirmed"],
                "pending_route_with_targetIntent": [
                    f"{prefix}.pending_route",
                    f"{prefix}.targetIntent",
                ],
            }
    if paths_by_decision:
        attach_write_contract(action, paths_by_decision)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    parser.add_argument("--ledger")
    args = parser.parse_args()

    spec_root = Path(args.spec_root).resolve()
    project_root = Path(args.project_root).resolve()
    contract_path = spec_root / "interaction_contract.json"
    index_path = project_root / ".iff" / "board_index.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))

    compound_decisions = {
        str(item.get("source") or "")
        for item in contract.get("compoundDecisions") or []
        if isinstance(item, dict) and item.get("confirmedByModel") is True
    }
    unresolved_compound = next(
        (
            item
            for item in contract.get("compoundCandidates") or []
            if str((item or {}).get("source") or "") not in compound_decisions
        ),
        None,
    )
    acknowledged_sources = {
        str(item.get("source") or "")
        for item in contract.get("acknowledgedNonRules") or []
        if isinstance(item, dict)
    }
    unresolved_item = next(
        (
            str(item)
            for item in contract.get("ignoredItems") or []
            if str(item) not in acknowledged_sources
        ),
        None,
    )

    selected = next(
        (rule for rule in contract.get("rules") or [] if unresolved_fields(rule)),
        None,
    )
    state_machine_path = spec_root / "state_machine.json"
    state_machine = (
        json.loads(state_machine_path.read_text(encoding="utf-8"))
        if state_machine_path.is_file()
        else None
    )
    anchors_path = spec_root / "interaction_anchors.json"
    anchors_doc = (
        json.loads(anchors_path.read_text(encoding="utf-8"))
        if anchors_path.is_file()
        else None
    )
    unresolved_anchor = None
    if anchors_doc is not None:
        unresolved_anchor = next(
            (
                anchor
                for anchor in anchors_doc.get("anchors") or []
                if (
                    anchor.get("resolution") == "ambiguous"
                    and not anchor.get("confirmed")
                )
                or (
                    anchor.get("resolution") == "unresolved"
                    and (
                        not anchor.get("pending_route")
                        or not anchor.get("targetIntent")
                    )
                )
            ),
            None,
        )
    plan_path = spec_root / "interaction_test_plan.json"
    plan = (
        json.loads(plan_path.read_text(encoding="utf-8"))
        if plan_path.is_file()
        else None
    )
    evidence_path = spec_root / "interaction_test_evidence.json"
    evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence_path.is_file()
        else {}
    )
    green_cases = (evidence.get("green") or {}).get("cases") or {}
    unproved_case = None
    if plan is not None:
        unproved_case = next(
            (
                case
                for case in plan.get("cases") or []
                if (green_cases.get(str(case.get("id"))) or {}).get("result")
                != "success"
            ),
            None,
        )
    if unresolved_compound:
        action = {
            "kind": "classify_compound_rule",
            "source": unresolved_compound.get("source"),
            "suggestedClauses": unresolved_compound.get("suggestedClauses") or [],
            "allowedDecisions": ["single", "split"],
        }
        state = "needs_model"
    elif unresolved_item:
        action = {
            "kind": "classify_interaction_item",
            "source": unresolved_item,
            "allowedDecisions": ["rule", "non_rule_with_reason"],
        }
        state = "needs_model"
    elif selected:
        action_text = norm(selected.get("action"))
        candidates = []
        for board in index.get("boards") or []:
            for node in board.get("nodes") or []:
                text = norm(node.get("text"))
                if text and text in action_text:
                    candidates.append(
                        {
                            "feature": board.get("feature"),
                            "board": board.get("board"),
                            "key": node.get("key"),
                            "text": node.get("text"),
                        }
                    )
        scope = selected.get("actionTargetScope") or {}
        if scope:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.get("feature") == scope.get("feature")
                and candidate.get("board") == scope.get("board")
            ]
        if len(candidates) > 5 and not scope:
            board_counts: dict[tuple[object, object], int] = {}
            for candidate in candidates:
                key = (candidate.get("feature"), candidate.get("board"))
                board_counts[key] = board_counts.get(key, 0) + 1
            action = {
                "kind": "choose_action_target_board",
                "ruleId": selected.get("id"),
                "source": str(selected.get("source") or ""),
                "candidateCount": len(candidates),
                "candidateBoards": [
                    {"feature": feature, "board": board, "nodeCount": count}
                    for (feature, board), count in sorted(board_counts.items())
                ],
                "writeField": "actionTargetScope",
            }
        else:
            action = {
                "kind": "complete_rule_semantics",
                "ruleId": selected.get("id"),
                "source": str(selected.get("source") or ""),
                "action": selected.get("action"),
                "observableOutcome": selected.get("observableOutcome"),
                "missingFields": unresolved_fields(selected),
                "actionTargetCandidates": candidates,
            }
        state = "needs_model"
    elif state_machine is not None and "__MODEL__" in json.dumps(state_machine):
        unresolved_node = next(
            (
                node
                for node in state_machine.get("nodes") or []
                if not str(node.get("meaning") or "").strip()
                or "__MODEL__" in str(node.get("meaning") or "")
            ),
            None,
        )
        if unresolved_node is not None:
            action = {
                "kind": "define_state_meaning",
                "stateId": unresolved_node.get("id"),
                "classificationType": unresolved_node.get("classificationType"),
                "sharedComponents": unresolved_node.get("sharedComponents") or [],
            }
        elif "__MODEL__" in str(state_machine.get("initialState") or ""):
            action = {
                "kind": "choose_initial_state",
                "candidateStateIds": [
                    node.get("id") for node in state_machine.get("nodes") or []
                ],
            }
        else:
            edge_index, edge = next(
                (
                    (index, edge)
                    for index, edge in enumerate(state_machine.get("edges") or [])
                    if "__MODEL__" in json.dumps(edge)
                ),
                (None, None),
            )
            action = {
                "kind": "define_transition",
                "edgeIndex": edge_index,
                "currentEdge": edge,
                "candidateStateIds": [
                    node.get("id") for node in state_machine.get("nodes") or []
                ],
                "ruleIds": [rule.get("id") for rule in contract.get("rules") or []],
            }
        state = "needs_model"
    elif unresolved_anchor is not None:
        action = {
            "kind": "confirm_anchor",
            "ruleId": unresolved_anchor.get("rule"),
            "query": unresolved_anchor.get("query"),
            "resolution": unresolved_anchor.get("resolution"),
            "candidates": unresolved_anchor.get("candidates") or [],
            "allowedDecisions": ["confirmed_candidate", "pending_route_with_targetIntent"],
        }
        state = "needs_model"
    elif unproved_case is not None:
        action = {
            "kind": "implement_interaction_case",
            "case": {
                key: unproved_case.get(key)
                for key in (
                    "id",
                    "precondition",
                    "action",
                    "actionTarget",
                    "expectedObservable",
                    "expectedObservableTarget",
                    "surface",
                )
            },
        }
        state = "needs_model"
    else:
        action = {"kind": "run_interaction_gate"}
        state = "deterministic_next"

    input_hashes = {
        "contract": sha256(contract_path),
        "boardIndex": sha256(index_path),
    }
    if state_machine_path.is_file():
        input_hashes["stateMachine"] = sha256(state_machine_path)
    if anchors_path.is_file():
        input_hashes["anchors"] = sha256(anchors_path)
    if plan_path.is_file():
        input_hashes["testPlan"] = sha256(plan_path)
    if evidence_path.is_file():
        input_hashes["testEvidence"] = sha256(evidence_path)
    source_paths = {
        "contract": contract_path,
        "boardIndex": index_path,
    }
    if state_machine_path.is_file():
        source_paths["stateMachine"] = state_machine_path
    if anchors_path.is_file():
        source_paths["anchors"] = anchors_path
    if plan_path.is_file():
        source_paths["testPlan"] = plan_path
    if evidence_path.is_file():
        source_paths["testEvidence"] = evidence_path
    if action.get("kind") != "none" and not action.get("allowedDecisions"):
        action["allowedDecisions"] = ["apply"]
    attach_interaction_write_contract(action, contract, state_machine, anchors_doc)
    packet = {
        "version": 2,
        "kind": "interaction",
        "scope": {"feature": spec_root.name},
        "sources": {
            name: packet_source(path) for name, path in source_paths.items()
        },
        "state": state,
        "facts": {"ruleCount": len(contract.get("rules") or [])},
        "inputs": input_hashes,
        "action": action,
    }
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
        raise SystemExit(f"ERROR: interaction {error}") from error
    print(f"ok interaction model packet: {size} bytes, action={action['kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
