#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from make_repair_plan import (
    actionability_fingerprint,
    annotate_actionability,
    build_actionability_proof,
    select_top_action,
)


REGION18_NOTE = (
    "The component region differs by pixels, but runtime widget rects are missing; "
    "this is not proof of bbox offset."
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def region18_action() -> dict:
    return {
        "priority": "P0",
        "category": "layout_region",
        "node": "Region18",
        "actualTrace": None,
        "implementationHints": [],
        "diagnostic": {"confidence": "medium", "note": REGION18_NOTE},
    }


def asset_action(node: str = "97:194") -> dict:
    return {
        "priority": "P1",
        "category": "asset_region",
        "node": node,
        "actualTrace": {"rect": {"x": 700, "y": 40, "width": 48, "height": 48}},
        "implementationHints": [{"file": "lib/example.dart", "widgetKey": "asset-97-194"}],
        "diagnostic": {"confidence": "high", "note": "Runtime node and source asset are identified."},
    }


def test_region18_is_ineligible() -> None:
    marked = annotate_actionability([region18_action()])
    eligibility = marked[0]["repairEligibility"]
    assert eligibility["schemaVersion"] == 2, eligibility
    assert eligibility["eligible"] is False, eligibility
    assert "diagnostic_disclaims_bbox_offset" in eligibility["reasons"], eligibility
    assert select_top_action(marked) is None, marked


def test_actionable_asset_is_preferred() -> None:
    marked = annotate_actionability([region18_action(), asset_action()])
    top = select_top_action(marked)
    assert top is not None, marked
    assert top["node"] == "97:194", top
    assert top["repairEligibility"]["eligible"] is True, top


def scoped_fixture(root: Path) -> tuple[Path, Path, Path]:
    board = root / "approved"
    layout = board / "layout_contract.json"
    write_json(layout, {})
    diff = board / "diff_report.json"
    scope = {
        "board": "approved",
        "identityFields": ["board", "state", "component", "node", "bbox"],
        "scoped": True,
    }
    write_json(
        diff,
        {
            "assetIssueScope": scope,
            "assetIssues": [
                {"board": "approved", "state": "default", "component": "hero", "node": "97:194", "bbox": [50, 257, 650, 368], "pixelMismatch": 0.1234}
            ],
            "pass": False,
            "ssim": 0.9110,
            "thresholds": {"assetMismatch": 0.10},
        },
    )
    marked = annotate_actionability([asset_action()])
    top = select_top_action(marked)
    assert top is not None
    plan = board / "repair_plan.json"
    write_json(
        plan,
        {
            "repairPlanVersion": 2,
            "inputs": {"diff": str(diff), "layout": str(layout)},
            "provenance": {"board": "approved", "diffSha256": sha256(diff), "assetIssueScope": scope},
            "actionability": build_actionability_proof(marked, top),
            "topAction": top,
            "actions": marked,
        },
    )
    return diff, plan, layout


def replace_plan_action(plan: Path, action: dict) -> None:
    payload = json.loads(plan.read_text(encoding="utf-8"))
    marked = annotate_actionability([action])
    top = select_top_action(marked)
    assert top is not None, marked
    payload["actionability"] = build_actionability_proof(marked, top)
    payload["topAction"] = top
    payload["actions"] = marked
    write_json(plan, payload)


def refresh_post_diff(diff: Path, plan: Path, *, ssim: float) -> None:
    diff_payload = json.loads(diff.read_text(encoding="utf-8"))
    diff_payload["ssim"] = ssim
    write_json(diff, diff_payload)
    plan_payload = json.loads(plan.read_text(encoding="utf-8"))
    plan_payload["provenance"]["diffSha256"] = sha256(diff)
    write_json(plan, plan_payload)


def claim(
    script: Path,
    state: Path,
    diff: Path,
    plan: Path,
    prior: Path | None = None,
    fresh: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
            "python3",
            str(script),
            "claim",
            "--state",
            str(state),
            "--board",
            "approved",
            "--diff-report",
            str(diff),
            "--repair-plan",
            str(plan),
        ]
    if prior is not None:
        command.extend(["--prior-post-repair-diff", str(prior)])
    if fresh is not None:
        command.extend(["--fresh-post-diff", str(fresh)])
    return subprocess.run(command, text=True, capture_output=True)


def replan(script: Path, state: Path, diff: Path, plan: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(script),
            "replan",
            "--state",
            str(state),
            "--board",
            "approved",
            "--diff-report",
            str(diff),
            "--repair-plan",
            str(plan),
        ],
        text=True,
        capture_output=True,
    )


def test_one_time_v1_migration() -> None:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-actionability-v1-") as raw_tmp:
        root = Path(raw_tmp)
        diff, plan, _ = scoped_fixture(root)
        state = root / "budget.json"
        write_json(
            state,
            {
                "schemaVersion": 1,
                "legacyInvalidations": [],
                "validAttempt": {
                    "board": "approved",
                    "source": "scoped_claim",
                    "diffSha256": "legacy-v1",
                    "repairPlanSha256": "legacy-v1",
                },
            },
        )
        result = claim(script, state, diff, plan)
        assert result.returncode == 0, result.stderr
        evidence = json.loads(state.read_text(encoding="utf-8"))
        assert evidence["schemaVersion"] == 2, evidence
        assert len(evidence["legacyV1Invalidations"]) == 1, evidence
        assert evidence["validAttempt"]["actionabilityProof"]["schemaVersion"] == 2, evidence


def test_v2_distinct_retry_repetition_and_bounded_exhaustion() -> None:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-actionability-v2-") as raw_tmp:
        root = Path(raw_tmp)
        diff, plan, _ = scoped_fixture(root)
        state = root / "budget.json"
        first = claim(script, state, diff, plan)
        assert first.returncode == 0, first.stderr
        routed_child = asset_action("97:194:rendered-child")
        routed_child["sourceIssueNode"] = "97:194"
        routed_child["assetClassification"] = "overlap_routed_source_child"
        replace_plan_action(plan, routed_child)
        stale = claim(script, state, diff, plan, fresh=diff)
        assert stale.returncode != 0, stale.stdout
        assert "fresh post-diff must differ from the prior attempt diff" in stale.stderr, stale.stderr

        refresh_post_diff(diff, plan, ssim=0.9109)
        replace_plan_action(plan, asset_action())
        repeated = claim(script, state, diff, plan, fresh=diff)
        assert repeated.returncode == 0, repeated.stderr

        refresh_post_diff(diff, plan, ssim=0.9108)
        replace_plan_action(plan, routed_child)
        distinct = claim(script, state, diff, plan, fresh=diff)
        assert distinct.returncode == 0, distinct.stderr
        evidence = json.loads(state.read_text(encoding="utf-8"))
        assert evidence["validAttempt"]["attemptIndex"] == 3, evidence
        assert len(evidence["attemptHistory"]) == 2, evidence
        assert evidence["progressEvidence"][0]["reason"] == "prior_attempt_stalled_next_distinct", evidence

        for attempt_index in range(4, 6):
            refresh_post_diff(diff, plan, ssim=0.9109 - attempt_index * 0.0001)
            replace_plan_action(plan, routed_child)
            accepted = claim(script, state, diff, plan, fresh=diff)
            assert accepted.returncode == 0, accepted.stderr
        refresh_post_diff(diff, plan, ssim=0.9099)
        replace_plan_action(plan, routed_child)
        exhausted = claim(script, state, diff, plan, fresh=diff)
        assert exhausted.returncode != 0, exhausted.stdout
        assert "repair topAction fingerprint retry cap exhausted (3)" in exhausted.stderr, exhausted.stderr


def test_consumed_v2_without_source_proof_migrates_to_distinct_source_action() -> None:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-actionability-v2-migration-") as raw_tmp:
        root = Path(raw_tmp)
        diff, plan, _ = scoped_fixture(root)
        migrated_child = asset_action("97:194:rendered-child")
        migrated_child["sourceIssueNode"] = "97:194"
        migrated_child["assetClassification"] = "overlap_routed_source_child"
        replace_plan_action(plan, migrated_child)
        state = root / "budget.json"
        write_json(
            state,
            {
                "schemaVersion": 2,
                "legacyInvalidations": [],
                "legacyV1Invalidations": [],
                "attemptHistory": [],
                "validAttempt": {
                    "board": "approved",
                    "source": "scoped_claim",
                    "attemptIndex": 1,
                    "diffSha256": "consumed-node97-baseline-diff",
                    "baselineEvidence": {
                        "node": "97:194",
                        "pixelMismatch": 0.1234,
                        "ssim": 0.9136,
                        "thresholds": {"assetMismatch": 0.10},
                    },
                    "actionabilityProof": {
                        "schemaVersion": 2,
                        "eligible": True,
                        "topActionFingerprint": "legacy-node97-trace-only-fingerprint",
                        "topActionNode": "97:194",
                    },
                },
            },
        )
        migrated = claim(script, state, diff, plan, fresh=diff)
        assert migrated.returncode == 0, migrated.stderr
        evidence = json.loads(state.read_text(encoding="utf-8"))
        assert evidence["validAttempt"]["attemptIndex"] == 2, evidence
        assert evidence["progressEvidence"][0]["reason"] == "prior_v2_missing_source_binding_proof", evidence


def test_same_v1_prior_migration_and_partial_state_recovery() -> None:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-actionability-prior-v1-") as raw_tmp:
        root = Path(raw_tmp)
        diff, plan, _ = scoped_fixture(root)
        prior_hash = sha256(diff)
        states = [
            {
                "schemaVersion": 1,
                "legacyInvalidations": [],
                "validAttempt": {
                    "board": "approved",
                    "source": "scoped_claim",
                    "diffSha256": prior_hash,
                    "repairPlanSha256": "legacy-v1",
                },
            },
            {
                "schemaVersion": 2,
                "legacyInvalidations": [],
                "legacyV1Invalidations": [
                    {
                        "reason": "schema_v1_valid_attempt_lacks_actionability_proof",
                        "board": "approved",
                        "diffSha256": prior_hash,
                        "repairPlanSha256": "legacy-v1",
                    }
                ],
                "validAttempt": {
                    "board": "approved",
                    "source": "prior_scoped_post_repair_diff",
                    "diffSha256": prior_hash,
                    "repairPlanSha256": "legacy-v1",
                },
            },
        ]
        for index, initial_state in enumerate(states):
            state = root / f"budget-{index}.json"
            write_json(state, initial_state)
            result = claim(script, state, diff, plan, prior=diff)
            assert result.returncode == 0, result.stderr
            evidence = json.loads(state.read_text(encoding="utf-8"))
            assert len(evidence["legacyV1Invalidations"]) == 1, evidence
            assert evidence["validAttempt"]["source"] == "scoped_claim", evidence
            assert evidence["validAttempt"]["actionabilityProof"]["schemaVersion"] == 2, evidence


def test_legacy_v2_persistent_source_issue_proves_nonprogress_with_absolute_top_out() -> None:
    script = Path(__file__).resolve().parent / "visual_repair_budget.py"
    with tempfile.TemporaryDirectory(prefix="iff-actionability-top-out-") as raw_tmp:
        root = Path(raw_tmp)
        diff, plan, _layout = scoped_fixture(root)
        routed_child = asset_action("180:2779")
        routed_child["sourceIssueNode"] = "97:194"
        routed_child["assetClassification"] = "overlap_routed_source_child"
        replace_plan_action(plan, routed_child)
        fresh_diff = json.loads(diff.read_text(encoding="utf-8"))
        fresh_diff["ssim"] = 0.9110
        fresh_diff["thresholds"] = {"ssim": 0.99, "pixelMismatch": 0.01}
        source_issue = fresh_diff["assetIssues"][0]
        fresh_diff["assetIssues"] = [
            {**source_issue, "component": "Region3"},
            {**source_issue, "component": "RepeatedRegion11"},
            {**source_issue, "component": "Region18"},
        ]
        write_json(diff, fresh_diff)
        refreshed_plan = json.loads(plan.read_text(encoding="utf-8"))
        refreshed_plan["provenance"]["diffSha256"] = sha256(diff)
        write_json(plan, refreshed_plan)
        full_plan = json.loads(plan.read_text(encoding="utf-8"))
        top_out = root / "repair_plan_top_v3.json"
        write_json(
            top_out,
            {
                "actionability": full_plan["actionability"],
                "topAction": full_plan["topAction"],
                "topCategoryActions": [full_plan["topAction"]],
                "fullPlan": str(plan.resolve()),
            },
        )
        state = root / "budget.json"
        write_json(
            state,
            {
                "schemaVersion": 2,
                "legacyInvalidations": [],
                "legacyV1Invalidations": [],
                "attemptHistory": [],
                "validAttempt": {
                    "board": "approved",
                    "source": "scoped_claim",
                    "attemptIndex": 1,
                    "diffSha256": "5ff7adee0b6bf3881cb87773dfd380e137e03620179972bd0dfd276d8aa03f61",
                    "actionabilityProof": {
                        "schemaVersion": 2,
                        "eligible": True,
                        "topActionFingerprint": "aa7153827a5d82e5cd2d6dbd24809e66c9d30fd395c991fdd783d282bac59594",
                    },
                },
            },
        )

        migrated = claim(script, state, diff, top_out, fresh=diff)
        assert migrated.returncode == 0, migrated.stderr
        evidence = json.loads(state.read_text(encoding="utf-8"))
        attempt = evidence["validAttempt"]
        assert attempt["attemptIndex"] == 2, evidence
        assert attempt["repairPlan"] == str(plan.resolve()), evidence
        assert attempt["repairPlanTopOut"] == str(top_out.resolve()), evidence
        assert attempt["repairPlanTopOutSha256"] == sha256(top_out), evidence


def test_replan_replaces_newly_ineligible_claim_without_new_screenshot() -> None:
    script = Path(__file__).with_name("visual_repair_budget.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        diff, plan, _ = scoped_fixture(root)
        state = root / "budget.json"
        first = claim(script, state, diff, plan)
        assert first.returncode == 0, first.stderr

        current = json.loads(plan.read_text(encoding="utf-8"))
        prior = current["topAction"]
        prior_now = dict(prior)
        prior_now["diagnostic"] = {
            "confidence": "low",
            "note": "Pixel region severity is not proof of bbox offset.",
        }
        replacement = asset_action("180:2779")
        actions = annotate_actionability([prior_now, replacement])
        top = select_top_action(actions)
        assert top is not None and top["node"] == "180:2779", actions
        assert actionability_fingerprint(prior_now) == actionability_fingerprint(prior)
        current["actions"] = actions
        current["topAction"] = top
        current["actionability"] = build_actionability_proof(actions, top)
        write_json(plan, current)

        replaced = replan(script, state, diff, plan)
        assert replaced.returncode == 0, replaced.stderr
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["validAttempt"]["attemptIndex"] == 1, saved
        assert saved["validAttempt"]["actionabilityProof"]["topActionNode"] == "180:2779", saved
        assert len(saved["plannerInvalidations"]) == 1, saved


def main() -> int:
    test_region18_is_ineligible()
    test_actionable_asset_is_preferred()
    test_one_time_v1_migration()
    test_v2_distinct_retry_repetition_and_bounded_exhaustion()
    test_consumed_v2_without_source_proof_migrates_to_distinct_source_action()
    test_same_v1_prior_migration_and_partial_state_recovery()
    test_legacy_v2_persistent_source_issue_proves_nonprogress_with_absolute_top_out()
    test_replan_replaces_newly_ineligible_claim_without_new_screenshot()
    print(
        "OK: actionability migrates legacy evidence and caps each source-backed fingerprint at three claims"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
