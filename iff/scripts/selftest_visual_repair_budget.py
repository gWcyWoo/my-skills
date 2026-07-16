#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from make_repair_plan import annotate_actionability, build_actionability_proof, select_top_action


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def claim(
    script: Path,
    state: Path,
    board: str,
    diff: Path,
    plan: Path,
    prior: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "python3",
        str(script),
        "claim",
        "--state",
        str(state),
        "--board",
        board,
        "--diff-report",
        str(diff),
        "--repair-plan",
        str(plan),
    ]
    if prior is not None:
        command.extend(["--prior-post-repair-diff", str(prior)])
    return subprocess.run(command, text=True, capture_output=True)


def main() -> int:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-visual-repair-budget-") as raw_tmp:
        root = Path(raw_tmp)
        board = root / "approved"
        layout = board / "layout_contract.json"
        write_json(layout, {})
        scoped_diff = board / "diff_report.json"
        write_json(
            scoped_diff,
            {
                "assetIssueScope": {
                    "board": "approved",
                    "identityFields": ["board", "state", "component", "node", "bbox"],
                },
                "assetIssues": [
                    {"node": "17:158", "board": "approved", "state": "approved", "component": "icon-a", "bbox": [0, 0, 10, 10], "pixelMismatch": 1.0},
                    {"node": "97:194", "board": "approved", "state": "approved", "component": "icon-b", "bbox": [20, 0, 10, 10], "pixelMismatch": 0.123},
                ],
                "thresholds": {"assetMismatch": 0.10},
            },
        )
        plan = board / "repair_plan.json"
        actions = annotate_actionability(
            [
                {
                    "priority": "P0",
                    "category": "asset_region",
                    "node": "17:158",
                    "actualTrace": {"rect": {"x": 700, "y": 40, "width": 48, "height": 48}},
                    "implementationHints": [
                        {"file": "lib/generated/example.dart", "valueKey": "design-node-17-158"}
                    ],
                    "diagnostic": {"confidence": "high", "note": "Runtime node is identified."},
                }
            ]
        )
        top_action = select_top_action(actions)
        assert top_action is not None
        write_json(
            plan,
            {
                "repairPlanVersion": 2,
                "inputs": {"diff": str(scoped_diff), "layout": str(layout)},
                "provenance": {
                    "board": "approved",
                    "diffSha256": sha256(scoped_diff),
                    "assetIssueScope": json.loads(scoped_diff.read_text())["assetIssueScope"],
                },
                "actionability": build_actionability_proof(actions, top_action),
                "topAction": top_action,
                "actions": actions,
            },
        )
        legacy_diff = root / "post_repair_diff_report.json"
        write_json(
            legacy_diff,
            {
                "assetIssues": [
                    {"node": "17:158", "pixelMismatch": 1.0},
                    {"node": "97:194", "pixelMismatch": 0.123},
                ]
            },
        )

        rejected_state = root / "unscoped_budget.json"
        rejected = claim(script, rejected_state, "approved", legacy_diff, plan)
        assert rejected.returncode != 0, rejected.stdout
        assert "deterministic assetIssueScope" in rejected.stderr, rejected.stderr
        assert not rejected_state.exists(), rejected_state

        state = root / "visual_repair_budget.json"
        migrated = claim(script, state, "approved", scoped_diff, plan, legacy_diff)
        assert migrated.returncode == 0, migrated.stdout + migrated.stderr
        evidence = json.loads(state.read_text(encoding="utf-8"))
        assert len(evidence["legacyInvalidations"]) == 1, evidence
        assert evidence["legacyInvalidations"][0]["diffSha256"] == sha256(legacy_diff), evidence
        assert evidence["validAttempt"]["board"] == "approved", evidence
        assert evidence["validAttempt"]["diffSha256"] == sha256(scoped_diff), evidence
        assert evidence["validAttempt"]["repairPlanSha256"] == sha256(plan), evidence

        retry = claim(script, state, "approved", scoped_diff, plan, legacy_diff)
        assert retry.returncode != 0, retry.stdout
        assert "another repair requires --fresh-post-diff evidence" in retry.stderr, retry.stderr
        unchanged = json.loads(state.read_text(encoding="utf-8"))
        assert unchanged == evidence, (unchanged, evidence)

    print("PASS: one legacy unscoped consumption migrates to exactly one valid scoped repair attempt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
