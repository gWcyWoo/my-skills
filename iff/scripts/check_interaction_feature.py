#!/usr/bin/env python3
"""Recompute the feature interaction gate from current artifacts and source."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from check_interaction_contract import validate_contract
from make_interaction_tests_plan import validate_plan


CORE_ARTIFACTS = (
    "interaction_contract.json",
    "state_machine.json",
    "interaction_anchors.json",
    "interaction_test_plan.json",
    "interaction_test_evidence.json",
    "interaction_device_evidence.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_one(root: Path, name: str) -> Path | None:
    matches = sorted(root.rglob(name))
    return matches[0] if len(matches) == 1 else None


def run_check(script: str, args: list[str]) -> str | None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(script)), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    return result.stdout.strip() or result.stderr.strip()


def validate_interaction_feature(
    spec_root: Path, project_root: Path, feature_manifest: Path
) -> tuple[list[str], dict[str, str]]:
    failures: list[str] = []
    inputs: dict[str, str] = {"feature_manifest": sha256(feature_manifest)}
    artifacts: dict[str, Path] = {}
    for name in CORE_ARTIFACTS:
        path = find_one(spec_root, name)
        if path is None:
            failures.append(f"{name} missing or not unique")
        else:
            artifacts[name] = path
            inputs[name] = sha256(path)
    contract_path = artifacts.get("interaction_contract.json")
    if contract_path:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        failures.extend(validate_contract(contract))
        completeness_failure = run_check(
            "check_interaction_completeness.py",
            ["--contract", str(contract_path)],
        )
        if completeness_failure:
            failures.append(completeness_failure)
    state_machine_path = artifacts.get("state_machine.json")
    if state_machine_path and contract_path:
        state_failure = run_check(
            "make_state_machine.py",
            [
                "--spec-root",
                str(spec_root),
                "--out",
                str(state_machine_path),
                "--contract",
                str(contract_path),
                "--feature-manifest",
                str(feature_manifest),
                "--check",
            ],
        )
        if state_failure:
            failures.append(state_failure)
    board_index = project_root / ".iff" / "board_index.json"
    if not board_index.is_file():
        failures.append(".iff/board_index.json missing")
    else:
        inputs["board_index.json"] = sha256(board_index)
        board_index_doc = json.loads(board_index.read_text(encoding="utf-8"))
        if contract_path:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            for rule in contract.get("rules") or []:
                target = rule.get("actionTarget") or {}
                if target.get("kind") != "node":
                    continue
                hits = [
                    board
                    for board in board_index_doc.get("boards") or []
                    if board.get("feature") == target.get("feature")
                    and board.get("board") == target.get("board")
                    and any(
                        node.get("key") == target.get("key")
                        for node in board.get("nodes") or []
                    )
                ]
                if len(hits) != 1:
                    failures.append(
                        f"{rule.get('id')}: actionTarget not found in board index "
                        f"or is ambiguous: {target.get('feature')}/"
                        f"{target.get('board')}/{target.get('key')}"
                    )
        anchors_path = artifacts.get("interaction_anchors.json")
        if anchors_path and contract_path:
            anchor_failure = run_check(
                "resolve_interaction_anchors.py",
                [
                    "--contract",
                    str(contract_path),
                    "--index",
                    str(board_index),
                    "--out",
                    str(anchors_path),
                    "--check",
                ],
            )
            if anchor_failure:
                failures.append(anchor_failure)
            anchors_doc = json.loads(anchors_path.read_text(encoding="utf-8"))
            pending_anchors = [
                anchor
                for anchor in anchors_doc.get("anchors") or []
                if anchor.get("pending_route")
            ]
            rules_by_id = {
                str(rule.get("id")): rule for rule in contract.get("rules") or []
            }
            cross_board_anchors = []
            for anchor in anchors_doc.get("anchors") or []:
                target = None
                if anchor.get("resolution") == "unique":
                    target = anchor.get("bound")
                elif anchor.get("resolution") == "ambiguous" and anchor.get("confirmed"):
                    feature, _, board = str(anchor.get("confirmed")).partition("/")
                    target = {"feature": feature, "board": board}
                rule = rules_by_id.get(str(anchor.get("rule"))) or {}
                source_target = rule.get("actionTarget") or {}
                source_board = source_target.get("board")
                source_feature = source_target.get("feature")
                if target and target.get("board") and (
                    target.get("board") != source_board
                    or target.get("feature") != source_feature
                ):
                    cross_board_anchors.append(
                        (anchor, source_feature, source_board, target)
                    )
            if pending_anchors or cross_board_anchors:
                flow_graph = project_root / ".iff" / "flow_graph.json"
                if not flow_graph.is_file():
                    for anchor in pending_anchors:
                        failures.append(
                            f"{anchor.get('rule')}: pending_route missing flow graph edge"
                        )
                    for anchor, _, _, _ in cross_board_anchors:
                        failures.append(
                            f"{anchor.get('rule')}: cross-board anchor missing flow graph edge"
                        )
                else:
                    inputs["flow_graph.json"] = sha256(flow_graph)
                    edges = list(
                        (json.loads(flow_graph.read_text(encoding="utf-8")).get("edges") or {}).values()
                    )
                    for anchor in pending_anchors:
                        intent = anchor.get("targetIntent")
                        matched = any(
                            edge.get("ruleId") == anchor.get("rule")
                            and (
                                edge.get("targetIntent") == intent
                                or edge.get("to_route") == intent
                                or edge.get("pending_route") == intent
                            )
                            for edge in edges
                        )
                        if not matched:
                            failures.append(
                                f"{anchor.get('rule')}: pending_route missing flow graph edge"
                            )
                    for anchor, source_feature, source_board, target in cross_board_anchors:
                        target_board = target.get("board")
                        target_full = f"{target.get('feature')}/{target_board}"
                        matched = any(
                            edge.get("ruleId") == anchor.get("rule")
                            and edge.get("from") in (
                                source_board,
                                f"{source_feature}/{source_board}",
                            )
                            and edge.get("to_board") in (target_board, target_full)
                            for edge in edges
                        )
                        if not matched:
                            failures.append(
                                f"{anchor.get('rule')}: cross-board anchor missing flow graph edge"
                            )
    plan_path = artifacts.get("interaction_test_plan.json")
    evidence_path = artifacts.get("interaction_test_evidence.json")
    test_root = project_root / "test"
    if plan_path and contract_path:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        failures.extend(validate_plan(contract, plan))
    if plan_path and evidence_path:
        coverage_failure = run_check(
            "check_interaction_coverage.py",
            [
                "--plan",
                str(plan_path),
                "--test-root",
                str(test_root),
                "--evidence",
                str(evidence_path),
            ],
        )
        if coverage_failure:
            failures.append(coverage_failure)
        for test_file in sorted(test_root.rglob("*_test.dart")):
            inputs[f"test:{test_file.relative_to(project_root)}"] = sha256(test_file)
    device_evidence_path = artifacts.get("interaction_device_evidence.json")
    device_test_root = project_root / "integration_test"
    if plan_path and device_evidence_path:
        device_failure = run_check(
            "check_interaction_device_evidence.py",
            [
                "--plan",
                str(plan_path),
                "--test-root",
                str(device_test_root),
                "--project-root",
                str(project_root),
                "--evidence",
                str(device_evidence_path),
            ],
        )
        if device_failure:
            failures.append(device_failure)
    if contract_path:
        wiring_failure = run_check(
            "check_interaction_wiring.py",
            [
                "--lib-root",
                str(project_root / "lib"),
                "--test-root",
                str(test_root),
                "--entry",
                str(project_root / "lib" / "main.dart"),
                "--pubspec",
                str(project_root / "pubspec.yaml"),
                "--contract",
                str(contract_path),
            ],
        )
        if wiring_failure:
            failures.append(wiring_failure)
        for source_file in sorted((project_root / "lib").rglob("*.dart")):
            inputs[f"lib:{source_file.relative_to(project_root)}"] = sha256(source_file)
    return failures, inputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    failures, inputs = validate_interaction_feature(
        Path(args.spec_root).resolve(),
        Path(args.project_root).resolve(),
        Path(args.feature_manifest).resolve(),
    )
    report = {
        "version": 1,
        "ok": not failures,
        "specRoot": str(Path(args.spec_root).resolve()),
        "projectRoot": str(Path(args.project_root).resolve()),
        "featureManifest": str(Path(args.feature_manifest).resolve()),
        "inputs": inputs,
        "failures": failures,
    }
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        print(f"FAIL interaction feature ({len(failures)}):")
        for failure in failures:
            print("  - " + failure)
        return 1
    print("ok interaction feature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
