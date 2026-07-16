#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from make_repair_plan import (
    actionability_fingerprint,
    deterministic_source_binding,
    repair_eligibility,
    source_binding_fingerprint,
)


REQUIRED_IDENTITY_FIELDS = {"board", "state", "component", "node", "bbox"}
MAX_ELIGIBLE_ATTEMPTS = 32
MAX_ATTEMPTS_PER_FINGERPRINT = 3


class BudgetError(ValueError):
    pass


def load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BudgetError(f"{label} unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise BudgetError(f"{label} must be a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_scoped_diff(report: dict, board: str, label: str) -> dict:
    scope = report.get("assetIssueScope")
    if not isinstance(scope, dict):
        raise BudgetError(f"{label} lacks deterministic assetIssueScope")
    if scope.get("board") != board:
        raise BudgetError(f"{label} assetIssueScope board does not match selected board {board!r}")
    identity_fields = scope.get("identityFields")
    if not isinstance(identity_fields, list) or not REQUIRED_IDENTITY_FIELDS.issubset(identity_fields):
        raise BudgetError(f"{label} assetIssueScope lacks board/state/component/node/bbox identity")
    issues = report.get("assetIssues") or []
    if not isinstance(issues, list):
        raise BudgetError(f"{label} assetIssues must be an array")
    for issue in issues:
        if not isinstance(issue, dict):
            raise BudgetError(f"{label} contains a non-object asset issue")
        bbox = issue.get("bbox")
        if (
            issue.get("board") != board
            or not isinstance(issue.get("node"), str)
            or not issue.get("node")
            or not isinstance(bbox, list)
            or len(bbox) != 4
        ):
            raise BudgetError(f"{label} contains an ambiguous or cross-board asset issue")
    return scope


def validate_plan(plan: dict, plan_path: Path, diff_path: Path, diff: dict, board: str) -> dict:
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise BudgetError("repair plan has no actionable repair and cannot consume budget")
    if plan.get("repairPlanVersion") != 2:
        raise BudgetError("repair plan must use repairPlanVersion=2 actionability proof")
    actionability = plan.get("actionability")
    top_action = plan.get("topAction")
    if not isinstance(actionability, dict) or actionability.get("schemaVersion") != 2:
        raise BudgetError("repair plan lacks v2 actionability proof")
    if actionability.get("eligible") is not True or not isinstance(top_action, dict):
        raise BudgetError("repair plan has no eligible topAction and cannot consume budget")
    recomputed = repair_eligibility(top_action)
    if recomputed.get("eligible") is not True or top_action.get("repairEligibility") != recomputed:
        raise BudgetError("repair plan topAction eligibility proof is invalid or stale")
    source_backed = deterministic_source_binding(top_action)
    if top_action.get("category") == "asset_region" and not source_backed:
        raise BudgetError("asset repair topAction lacks deterministic implementation_map/ValueKey source binding")
    binding_fingerprint = source_binding_fingerprint(top_action)
    if actionability.get("sourceBacked") is not source_backed:
        raise BudgetError("repair plan source-binding eligibility proof is invalid or stale")
    if actionability.get("sourceBindingFingerprint") != binding_fingerprint:
        raise BudgetError("repair plan source-binding fingerprint is invalid or stale")
    fingerprint = actionability_fingerprint(top_action)
    if actionability.get("topActionFingerprint") != fingerprint:
        raise BudgetError("repair plan topAction actionability fingerprint is invalid or stale")
    if not any(actionability_fingerprint(action) == fingerprint for action in actions if isinstance(action, dict)):
        raise BudgetError("repair plan topAction is not present in the scoped action list")
    inputs = plan.get("inputs")
    provenance = plan.get("provenance")
    if not isinstance(inputs, dict) or not isinstance(provenance, dict):
        raise BudgetError("repair plan lacks scoped provenance")
    input_diff = Path(str(inputs.get("diff") or ""))
    if not input_diff.is_absolute():
        input_diff = Path.cwd() / input_diff
    input_diff = input_diff.resolve()
    if input_diff != diff_path.resolve():
        raise BudgetError("repair plan input diff does not match the claimed diff report")
    layout = Path(str(inputs.get("layout") or ""))
    if not layout.is_absolute():
        layout = Path.cwd() / layout
    layout = layout.resolve()
    if layout.parent.name != board:
        raise BudgetError("repair plan layout does not match the selected board")
    if provenance.get("board") != board:
        raise BudgetError("repair plan provenance board does not match the selected board")
    if provenance.get("diffSha256") != file_sha256(diff_path):
        raise BudgetError("repair plan provenance diff hash is stale or mismatched")
    if provenance.get("assetIssueScope") != diff.get("assetIssueScope"):
        raise BudgetError("repair plan assetIssueScope does not match the claimed diff report")
    if plan_path.resolve() == diff_path.resolve():
        raise BudgetError("repair plan and diff report must be separate artifacts")
    return {
        "schemaVersion": 2,
        "eligible": True,
        "topActionFingerprint": fingerprint,
        "sourceBacked": source_backed,
        "sourceBindingFingerprint": binding_fingerprint,
        "topActionNode": top_action.get("node"),
        "sourceIssueNode": top_action.get("sourceIssueNode"),
        "category": top_action.get("category"),
    }


def empty_state() -> dict:
    return {
        "schemaVersion": 2,
        "legacyInvalidations": [],
        "legacyV1Invalidations": [],
        "plannerInvalidations": [],
        "attemptHistory": [],
        "validAttempt": None,
    }


def migrate_v1_state(state: dict) -> dict:
    invalidations = state.get("legacyInvalidations")
    if not isinstance(invalidations, list):
        raise BudgetError("visual repair budget legacyInvalidations must be an array")
    migrated = empty_state()
    migrated["legacyInvalidations"] = invalidations
    attempt = state.get("validAttempt")
    if attempt is None:
        return migrated
    if not isinstance(attempt, dict):
        raise BudgetError("schema-v1 visual repair validAttempt must be an object")
    proof = attempt.get("actionabilityProof")
    if isinstance(proof, dict) and proof.get("schemaVersion") == 2 and proof.get("eligible") is True:
        migrated["validAttempt"] = attempt
        return migrated
    migrated["legacyV1Invalidations"].append(
        {
            "reason": "schema_v1_valid_attempt_lacks_actionability_proof",
            "board": attempt.get("board"),
            "diffSha256": attempt.get("diffSha256"),
            "repairPlanSha256": attempt.get("repairPlanSha256"),
        }
    )
    return migrated


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    state = load_object(path, "visual repair budget state")
    if state.get("schemaVersion") == 1:
        return migrate_v1_state(state)
    if state.get("schemaVersion") != 2:
        raise BudgetError("unsupported visual repair budget state schema")
    if not isinstance(state.get("legacyInvalidations"), list):
        raise BudgetError("visual repair budget legacyInvalidations must be an array")
    if not isinstance(state.get("legacyV1Invalidations"), list):
        raise BudgetError("visual repair budget legacyV1Invalidations must be an array")
    if "attemptHistory" not in state:
        state["attemptHistory"] = []
    if not isinstance(state.get("attemptHistory"), list):
        raise BudgetError("visual repair budget attemptHistory must be an array")
    if "plannerInvalidations" not in state:
        state["plannerInvalidations"] = []
    if not isinstance(state.get("plannerInvalidations"), list):
        raise BudgetError("visual repair budget plannerInvalidations must be an array")
    return state


def matching_v1_invalidation_count(state: dict, diff_sha256: str) -> int:
    return sum(
        1
        for item in state.get("legacyV1Invalidations", [])
        if isinstance(item, dict) and item.get("diffSha256") == diff_sha256
    )


def recover_partial_v1_prior_duplicate(state: dict) -> None:
    attempt = state.get("validAttempt")
    if not isinstance(attempt, dict) or attempt.get("source") != "prior_scoped_post_repair_diff":
        return
    proof = attempt.get("actionabilityProof")
    if isinstance(proof, dict) and proof.get("schemaVersion") == 2 and proof.get("eligible") is True:
        return
    diff_sha256 = str(attempt.get("diffSha256") or "")
    match_count = matching_v1_invalidation_count(state, diff_sha256)
    if match_count > 1:
        raise BudgetError("ambiguous duplicate schema-v1 invalidation provenance")
    if match_count == 1:
        state["validAttempt"] = None


def prior_matches_invalidated_v1(state: dict, prior_path: Path) -> bool:
    match_count = matching_v1_invalidation_count(state, file_sha256(prior_path))
    if match_count > 1:
        raise BudgetError("ambiguous duplicate schema-v1 invalidation provenance")
    return match_count == 1


def record_prior_consumption(state: dict, prior_path: Path, board: str, state_path: Path) -> None:
    prior = load_object(prior_path, "prior post-repair diff")
    prior_hash = file_sha256(prior_path)
    if not isinstance(prior.get("assetIssueScope"), dict):
        invalidations = state["legacyInvalidations"]
        if invalidations and invalidations[0].get("diffSha256") != prior_hash:
            raise BudgetError("legacy unscoped consumption migration was already used")
        if not invalidations:
            invalidations.append(
                {
                    "reason": "legacy_unscoped_consumption",
                    "diff": str(prior_path.resolve()),
                    "diffSha256": prior_hash,
                }
            )
        return
    validate_scoped_diff(prior, board, "prior post-repair diff")
    state["validAttempt"] = {
        "board": board,
        "source": "prior_scoped_post_repair_diff",
        "diff": str(prior_path.resolve()),
        "diffSha256": prior_hash,
    }
    atomic_write(state_path, state)
    raise BudgetError("valid scoped visual repair attempt already consumed")


def mismatch_for_node(diff: dict, node: str | None) -> float | None:
    if not node:
        return None
    for issue in diff.get("assetIssues") or []:
        if not isinstance(issue, dict) or str(issue.get("node") or "") != str(node):
            continue
        value = issue.get("pixelMismatch", issue.get("mismatch"))
        if isinstance(value, (int, float)):
            return float(value)
    return None


def attempt_evidence(diff: dict, proof: dict) -> dict:
    node = proof.get("sourceIssueNode") or proof.get("topActionNode")
    return {
        "node": node,
        "pixelMismatch": mismatch_for_node(diff, str(node) if node else None),
        "ssim": diff.get("ssim"),
        "pass": diff.get("pass"),
        "thresholds": diff.get("thresholds"),
    }


def validate_distinct_retry(
    state: dict,
    prior_attempt: dict,
    next_proof: dict,
    fresh_diff: dict,
    fresh_path: Path,
) -> dict:
    prior_proof = prior_attempt.get("actionabilityProof")
    if not isinstance(prior_proof, dict) or prior_proof.get("schemaVersion") != 2:
        raise BudgetError("prior attempt lacks v2 actionability provenance")
    prior_fingerprint = prior_proof.get("topActionFingerprint")
    next_fingerprint = next_proof.get("topActionFingerprint")
    fingerprint_attempts = sum(
        1
        for attempt in [*(state.get("attemptHistory") or []), prior_attempt]
        if isinstance(attempt, dict)
        and isinstance(attempt.get("actionabilityProof"), dict)
        and attempt["actionabilityProof"].get("topActionFingerprint") == next_fingerprint
    )
    if fingerprint_attempts >= MAX_ATTEMPTS_PER_FINGERPRINT:
        raise BudgetError(
            "repair topAction fingerprint retry cap exhausted "
            f"({MAX_ATTEMPTS_PER_FINGERPRINT})"
        )
    if next_proof.get("sourceBacked") is not True or not next_proof.get("sourceBindingFingerprint"):
        raise BudgetError("bounded retry requires a deterministic source-backed topAction")
    attempt_count = len(state.get("attemptHistory") or []) + 1
    if attempt_count >= MAX_ELIGIBLE_ATTEMPTS:
        raise BudgetError(f"bounded distinct-fingerprint repair cap exhausted ({MAX_ELIGIBLE_ATTEMPTS})")
    prior_diff_sha256 = prior_attempt.get("diffSha256")
    fresh_diff_sha256 = file_sha256(fresh_path)
    if not prior_diff_sha256:
        raise BudgetError("prior attempt lacks diff hash provenance for a fresh retry")
    if prior_diff_sha256 == fresh_diff_sha256:
        raise BudgetError("fresh post-diff must differ from the prior attempt diff")
    thresholds = fresh_diff.get("thresholds") if isinstance(fresh_diff.get("thresholds"), dict) else {}
    reported_asset_threshold = thresholds.get("assetMismatch")
    if reported_asset_threshold is None:
        asset_threshold = 0.10
    elif isinstance(reported_asset_threshold, (int, float)):
        asset_threshold = float(reported_asset_threshold)
    else:
        raise BudgetError("asset mismatch threshold must be numeric when present")
    if asset_threshold > 0.10:
        raise BudgetError("asset mismatch threshold relaxation is forbidden")
    baseline = prior_attempt.get("baselineEvidence")
    evidence_proof = prior_proof if prior_proof.get("topActionNode") else next_proof
    current = attempt_evidence(fresh_diff, evidence_proof)
    reason = None
    if not prior_proof.get("sourceBindingFingerprint"):
        source_issue_node = next_proof.get("sourceIssueNode")
        prior_node = prior_proof.get("topActionNode")
        current_mismatch = mismatch_for_node(fresh_diff, str(source_issue_node or ""))
        if not source_issue_node or (prior_node and prior_node != source_issue_node):
            raise BudgetError("fresh plan does not route the misclassified prior asset node to a source-backed child")
        if (
            not isinstance(current_mismatch, (int, float))
            or not isinstance(asset_threshold, (int, float))
            or float(current_mismatch) <= float(asset_threshold)
        ):
            raise BudgetError("fresh scoped source issue does not prove the legacy v2 action remained ineffective")
        reason = "prior_v2_missing_source_binding_proof"
    elif isinstance(baseline, dict):
        baseline_thresholds = baseline.get("thresholds")
        if isinstance(baseline_thresholds, dict) and thresholds != baseline_thresholds:
            raise BudgetError("visual threshold changes between repair attempts are forbidden")
        baseline_mismatch = baseline.get("pixelMismatch")
        current_mismatch = current.get("pixelMismatch")
        baseline_ssim = baseline.get("ssim")
        current_ssim = current.get("ssim")
        mismatch_nonprogress = (
            isinstance(baseline_mismatch, (int, float))
            and isinstance(current_mismatch, (int, float))
            and float(current_mismatch) >= float(baseline_mismatch)
        )
        ssim_nonprogress = (
            isinstance(baseline_ssim, (int, float))
            and isinstance(current_ssim, (int, float))
            and float(current_ssim) <= float(baseline_ssim)
        )
        reason = (
            "prior_attempt_progressed_but_thresholds_unmet"
            if not mismatch_nonprogress and not ssim_nonprogress
            else "prior_attempt_stalled_next_distinct"
        )
    else:
        raise BudgetError("prior source-backed attempt lacks baseline evidence for retry")
    return {
        "reason": reason,
        "priorFingerprint": prior_fingerprint,
        "nextFingerprint": next_fingerprint,
        "freshPostDiff": str(fresh_path.resolve()),
        "freshPostDiffSha256": fresh_diff_sha256,
        "freshEvidence": current,
    }


def resolve_repair_plan_input(path: Path) -> tuple[dict, Path, Path | None]:
    supplied = load_object(path, "repair plan")
    if isinstance(supplied.get("actions"), list):
        return supplied, path, None
    top_actions = supplied.get("topCategoryActions")
    full_ref = supplied.get("fullPlan")
    if not isinstance(top_actions, list) or not top_actions or not isinstance(full_ref, str) or not full_ref:
        return supplied, path, None
    raw_full = Path(full_ref)
    candidates = [raw_full.resolve()] if raw_full.is_absolute() else [
        (Path.cwd() / raw_full).resolve(),
        (path.resolve().parent / raw_full).resolve(),
    ]
    existing = []
    for candidate in candidates:
        if candidate.exists() and candidate not in existing:
            existing.append(candidate)
    if len(existing) != 1:
        raise BudgetError("repair plan top-out fullPlan reference is missing or ambiguous")
    full_path = existing[0]
    full_plan = load_object(full_path, "repair plan top-out fullPlan")
    if supplied.get("topAction") != full_plan.get("topAction"):
        raise BudgetError("repair plan top-out topAction does not match fullPlan")
    if supplied.get("actionability") != full_plan.get("actionability"):
        raise BudgetError("repair plan top-out actionability does not match fullPlan")
    if supplied.get("topAction") not in top_actions:
        raise BudgetError("repair plan top-out topAction is absent from topCategoryActions")
    return full_plan, full_path, path


def claim(args: argparse.Namespace) -> dict:
    state_path = Path(args.state)
    diff_path = Path(args.diff_report)
    supplied_plan_path = Path(args.repair_plan)
    diff = load_object(diff_path, "diff report")
    scope = validate_scoped_diff(diff, args.board, "diff report")
    plan, plan_path, top_out_path = resolve_repair_plan_input(supplied_plan_path)
    actionability_proof = validate_plan(plan, plan_path, diff_path, diff, args.board)
    state = load_state(state_path)
    recover_partial_v1_prior_duplicate(state)
    prior_attempt = state.get("validAttempt")
    retry_evidence = None
    if isinstance(prior_attempt, dict):
        if not args.fresh_post_diff:
            raise BudgetError("another repair requires --fresh-post-diff evidence")
        fresh_path = Path(args.fresh_post_diff)
        fresh_diff = load_object(fresh_path, "fresh post-repair diff report")
        validate_scoped_diff(fresh_diff, args.board, "fresh post-repair diff report")
        if file_sha256(fresh_path) != file_sha256(diff_path):
            raise BudgetError("fresh post-diff must be the scoped diff used by the next repair plan")
        retry_evidence = validate_distinct_retry(
            state,
            prior_attempt,
            actionability_proof,
            fresh_diff,
            fresh_path,
        )
    elif args.fresh_post_diff:
        raise BudgetError("--fresh-post-diff is only valid for a bounded distinct retry")
    if prior_attempt is None and args.prior_post_repair_diff:
        prior_path = Path(args.prior_post_repair_diff)
        if prior_path.exists():
            if not prior_matches_invalidated_v1(state, prior_path):
                record_prior_consumption(state, prior_path, args.board, state_path)
    if isinstance(prior_attempt, dict):
        state.setdefault("attemptHistory", []).append(prior_attempt)
        state.setdefault("progressEvidence", []).append(retry_evidence)
    state["validAttempt"] = {
        "board": args.board,
        "source": "scoped_claim",
        "attemptIndex": len(state.get("attemptHistory") or []) + 1,
        "diff": str(diff_path.resolve()),
        "diffSha256": file_sha256(diff_path),
        "repairPlan": str(plan_path.resolve()),
        "repairPlanSha256": file_sha256(plan_path),
        "repairPlanTopOut": str(top_out_path.resolve()) if top_out_path else None,
        "repairPlanTopOutSha256": file_sha256(top_out_path) if top_out_path else None,
        "assetIssueScope": scope,
        "actionabilityProof": actionability_proof,
        "baselineEvidence": attempt_evidence(diff, actionability_proof),
        "retryEvidence": retry_evidence,
        "claimedAtNs": time.time_ns(),
    }
    atomic_write(state_path, state)
    return state


def replan(args: argparse.Namespace) -> dict:
    state_path = Path(args.state)
    diff_path = Path(args.diff_report)
    supplied_plan_path = Path(args.repair_plan)
    diff = load_object(diff_path, "diff report")
    scope = validate_scoped_diff(diff, args.board, "diff report")
    plan, plan_path, top_out_path = resolve_repair_plan_input(supplied_plan_path)
    actionability_proof = validate_plan(plan, plan_path, diff_path, diff, args.board)
    state = load_state(state_path)
    prior_attempt = state.get("validAttempt")
    if not isinstance(prior_attempt, dict):
        raise BudgetError("replan requires an existing valid repair claim")
    if prior_attempt.get("board") != args.board:
        raise BudgetError("replan board does not match the existing repair claim")
    if prior_attempt.get("diffSha256") != file_sha256(diff_path):
        raise BudgetError("replan requires the unchanged scoped diff from the existing repair claim")
    prior_proof = prior_attempt.get("actionabilityProof")
    prior_fingerprint = prior_proof.get("topActionFingerprint") if isinstance(prior_proof, dict) else None
    if not prior_fingerprint:
        raise BudgetError("existing repair claim lacks an actionability fingerprint")
    matching = [
        action
        for action in plan.get("actions") or []
        if actionability_fingerprint(action) == prior_fingerprint
    ]
    if len(matching) != 1:
        raise BudgetError("replan must retain exactly one current action for the claimed fingerprint")
    current_prior = matching[0]
    current_eligibility = repair_eligibility(current_prior)
    if current_prior.get("repairEligibility") != current_eligibility:
        raise BudgetError("replan prior-action eligibility proof is invalid or stale")
    if current_eligibility.get("eligible") is True:
        raise BudgetError("replan cannot replace a claim that remains repair-eligible")
    next_fingerprint = actionability_proof.get("topActionFingerprint")
    if next_fingerprint == prior_fingerprint:
        raise BudgetError("replan replacement must use a distinct eligible fingerprint")
    invalidation = {
        "board": args.board,
        "attemptIndex": prior_attempt.get("attemptIndex"),
        "priorFingerprint": prior_fingerprint,
        "replacementFingerprint": next_fingerprint,
        "reasons": current_eligibility.get("reasons") or [],
        "priorRepairPlanSha256": prior_attempt.get("repairPlanSha256"),
        "replacementRepairPlanSha256": file_sha256(plan_path),
        "diffSha256": file_sha256(diff_path),
        "invalidatedAtNs": time.time_ns(),
    }
    state.setdefault("plannerInvalidations", []).append(invalidation)
    state["validAttempt"] = {
        "board": args.board,
        "source": "scoped_replan",
        "attemptIndex": prior_attempt.get("attemptIndex"),
        "diff": str(diff_path.resolve()),
        "diffSha256": file_sha256(diff_path),
        "repairPlan": str(plan_path.resolve()),
        "repairPlanSha256": file_sha256(plan_path),
        "repairPlanTopOut": str(top_out_path.resolve()) if top_out_path else None,
        "repairPlanTopOutSha256": file_sha256(top_out_path) if top_out_path else None,
        "assetIssueScope": scope,
        "actionabilityProof": actionability_proof,
        "baselineEvidence": attempt_evidence(diff, actionability_proof),
        "retryEvidence": {
            "reason": "planner_invalidated_prior_claim",
            "priorFingerprint": prior_fingerprint,
            "nextFingerprint": next_fingerprint,
            "plannerInvalidationIndex": len(state["plannerInvalidations"]),
        },
        "claimedAtNs": time.time_ns(),
    }
    atomic_write(state_path, state)
    return state


def verify(args: argparse.Namespace) -> dict:
    state = load_state(Path(args.state))
    attempt = state.get("validAttempt")
    if not isinstance(attempt, dict):
        raise BudgetError("no valid scoped visual repair attempt has been consumed")
    if attempt.get("board") != args.board:
        raise BudgetError("valid repair attempt belongs to a different board")
    if attempt.get("diffSha256") != file_sha256(Path(args.diff_report)):
        raise BudgetError("claimed diff report changed after budget consumption")
    if attempt.get("repairPlanSha256") != file_sha256(Path(args.repair_plan)):
        raise BudgetError("claimed repair plan changed after budget consumption")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim, replan, or verify a scoped iFF visual repair attempt")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("claim", "replan", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--state", required=True)
        subparser.add_argument("--board", required=True)
        subparser.add_argument("--diff-report", required=True)
        subparser.add_argument("--repair-plan", required=True)
        if command == "claim":
            subparser.add_argument("--prior-post-repair-diff")
            subparser.add_argument("--fresh-post-diff")
    args = parser.parse_args()
    try:
        if args.command == "claim":
            state = claim(args)
        elif args.command == "replan":
            state = replan(args)
        else:
            state = verify(args)
    except (BudgetError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "state": str(Path(args.state).resolve()), "validAttempt": state["validAttempt"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
