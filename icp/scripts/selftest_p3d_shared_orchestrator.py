#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import orchestrate_client_project_v1 as orchestrator
import requirement_claim_intent_v1 as claim_contract
import requirement_progress_v1 as progress_contract


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _documents() -> tuple[dict, dict, dict]:
    selection_digest = _digest("selection")
    row_digest = _digest("row")
    claim_ack_digest = _digest("claim-ack")
    requirement_id = progress_contract.derive_requirement_id(selection_digest, row_digest)
    progress_id = progress_contract.derive_progress_id(requirement_id, claim_ack_digest)
    intent = {
        "kind": "icp.requirement-claim-intent.v1",
        "schema_version": 1,
        "requirement_id": requirement_id,
        "selection_manifest_digest": selection_digest,
        "row_identity_digest": row_digest,
        "task_source_snapshot_digest": _digest("task-source-snapshot"),
        "candidate_identity_digest": _digest("candidate"),
        "expected_status_before": "empty",
        "source_sha256_before": _digest("source-before"),
        "expected_source_sha256_after": _digest("source-after"),
    }
    claim_contract.verify_claim_intent(intent)
    active = {
        "kind": "icp.active-requirement.v1",
        "schema_version": 1,
        "requirement_id": requirement_id,
        "selection_manifest_digest": selection_digest,
        "row_identity_digest": row_digest,
        "claim_intent_digest": claim_contract.document_digest(intent),
        "claim_ack_digest": claim_ack_digest,
        "progress_id": progress_id,
    }
    progress = {
        "kind": "icp.requirement-progress.v1",
        "schema_version": 1,
        "requirement_id": requirement_id,
        "progress_id": progress_id,
        "claim_ack_digest": claim_ack_digest,
        "verified_operation_plan_digest": _digest("plan"),
        "revision": 0,
        "phase": "claimed",
        "latest_checkpoint_receipt_digest": None,
        "checkpoint_count": 0,
        "feature_positions": [
            {
                "feature_id": "feature.login",
                "state": "pending",
                "inflight_step_id": None,
                "next_step_id": "visible_implementation",
                "replay_policy": "none",
                "recovery_verifier_digest": None,
                "last_checkpoint_receipt_digest": None,
            }
        ],
    }
    progress_contract.verify_active_requirement(active)
    progress_contract.verify_progress(progress)
    return intent, active, progress


def _receipt(active: dict) -> dict:
    receipt = {
        "kind": "icp.checkpoint-receipt.v1",
        "schema_version": 1,
        "receipt_id": _digest("receipt-0"),
        "requirement_id": active["requirement_id"],
        "progress_id": active["progress_id"],
        "claim_ack_digest": active["claim_ack_digest"],
        "sequence": 0,
        "previous_receipt_digest": progress_contract.GENESIS_RECEIPT_DIGEST,
        "feature_id": "feature.login",
        "step_id": "visible_implementation",
        "execution_mode": "first-run",
        "input_artifact_digests": [{"id": "request", "digest": _digest("request")}],
        "output_artifact_digests": [{"id": "source", "digest": _digest("source")}],
        "producer_digest": _digest("producer"),
        "verifier_digest": _digest("verifier"),
    }
    progress_contract.verify_checkpoint_receipt(receipt)
    return receipt


def test_store_persists_and_resumes_one_requirement() -> None:
    intent, active, progress = _documents()
    with tempfile.TemporaryDirectory(prefix="icp-p3d-store-") as directory:
        store = orchestrator.RequirementStateStore(Path(directory))
        with store.exclusive_lock():
            store.publish_claim_intent(intent)
            store.activate(active, progress)
            snapshot = store.load_snapshot()
            assert snapshot["active"] == active
            assert snapshot["progress"] == progress
            assert snapshot["receipts"] == []
            try:
                store.activate(active, progress)
            except orchestrator.OrchestratorError as exc:
                assert exc.code == "active_requirement_exists"
            else:
                raise AssertionError("a second active requirement must fail closed")

        reopened = orchestrator.RequirementStateStore(Path(directory))
        with reopened.exclusive_lock():
            assert reopened.load_snapshot()["active"] == active


def test_prepare_rejects_non_hex_operation_plan_digest_before_effects() -> None:
    try:
        orchestrator.prepare_single_requirement_with_entry_gate(
            resolved_config={},
            registries={},
            readiness_report={},
            entry_gate_decision={},
            package_resolution={},
            package_verification_digest="0" * 64,
            verified_operation_plan_digest="g" * 64,
            feature_positions=[{}],
        )
    except orchestrator.OrchestratorError as exc:
        assert exc.code == "invalid_operation_plan_digest"
    else:
        raise AssertionError("non-hex operation plan digest must be rejected")


def test_common_checkpoint_builder_is_platform_neutral() -> None:
    _, _, progress = _documents()
    receipt = orchestrator.build_execution_checkpoint_receipt(
        progress=progress,
        platform_id="vue",
        feature_id="feature.login",
        step_id="visible_implementation",
        execution_mode="first-run",
        input_artifact_digests={"authorization": _digest("authorization")},
        output_artifact_digests={"source": _digest("source")},
        producer_digest=_digest("vue-executor"),
        verifier_digest=_digest("vue-verifier"),
    )
    progress_contract.verify_checkpoint_receipt(receipt)
    assert receipt["sequence"] == 0


def test_checkpoint_is_immutable_and_progress_uses_revision_cas() -> None:
    intent, active, progress = _documents()
    receipt = _receipt(active)
    next_progress = dict(progress)
    next_progress["revision"] = 1
    next_progress["phase"] = "running"
    next_progress["latest_checkpoint_receipt_digest"] = progress_contract.document_digest(receipt)
    next_progress["checkpoint_count"] = 1
    next_progress["feature_positions"] = [
        {
            "feature_id": "feature.login",
            "state": "checkpointed",
            "inflight_step_id": None,
            "next_step_id": "fixture",
            "replay_policy": "none",
            "recovery_verifier_digest": None,
            "last_checkpoint_receipt_digest": progress_contract.document_digest(receipt),
        }
    ]
    progress_contract.verify_progress(next_progress)

    with tempfile.TemporaryDirectory(prefix="icp-p3d-checkpoint-") as directory:
        store = orchestrator.RequirementStateStore(Path(directory))
        with store.exclusive_lock():
            store.publish_claim_intent(intent)
            store.activate(active, progress)
            store.commit_checkpoint(receipt, next_progress, expected_revision=0)
            progress_contract.verify_checkpoint_chain(
                store.load_snapshot()["receipts"], active=active, progress=next_progress
            )
            try:
                store.commit_checkpoint(receipt, next_progress, expected_revision=0)
            except orchestrator.OrchestratorError as exc:
                assert exc.code in {"stale_progress_revision", "checkpoint_exists"}
            else:
                raise AssertionError("checkpoint replay must fail before mutation")


def test_terminal_cleanup_removes_only_mutable_state_and_keeps_audit_evidence() -> None:
    intent, active, progress = _documents()
    terminal_progress = dict(progress)
    terminal_progress["revision"] = 1
    terminal_progress["phase"] = "terminal-pending"
    progress_contract.verify_progress(terminal_progress)
    writeback_digest = _digest("writeback-ack")

    with tempfile.TemporaryDirectory(prefix="icp-p3d-cleanup-") as directory:
        root = Path(directory)
        store = orchestrator.RequirementStateStore(root)
        with store.exclusive_lock():
            store.publish_claim_intent(intent)
            store.activate(active, progress)
            store.replace_progress(terminal_progress, expected_revision=0)
            scratch = store.scratch_directory(active["requirement_id"])
            (scratch / "partial.txt").write_text("partial", encoding="utf-8")
            sealed_digest = store.seal_evidence(
                active["requirement_id"],
                {"kind": "icp.sealed-requirement-evidence.v1", "status": "done"},
            )
            plan = progress_contract.plan_terminal_cleanup(
                active,
                terminal_progress,
                terminal_status="done",
                writeback_ack_digest=writeback_digest,
                expected_writeback_ack_digest=writeback_digest,
                sealed_evidence_digest=sealed_digest,
            )
            store.stage_terminal_cleanup(plan)

        recovered_store = orchestrator.RequirementStateStore(root)
        with recovered_store.exclusive_lock():
            report = recovered_store.recover_terminal_cleanup()
            assert report is not None
            assert report["next_requirement_allowed"] is True
            assert recovered_store.load_snapshot() == {"active": None, "progress": None, "receipts": []}

        assert list((root / "claim-intents").glob("*.json"))
        assert list((root / "sealed-evidence").glob("*.json"))
        assert not (root / "scratch" / active["requirement_id"]).exists()


def main() -> int:
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    failures = 0
    for name, test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover - selftest diagnostics
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok {name}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
