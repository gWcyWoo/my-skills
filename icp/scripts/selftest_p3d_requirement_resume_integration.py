#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import copy
import json
import tempfile
from pathlib import Path

import csv_task_source
import orchestrate_client_project_v1 as orchestrator
import requirement_claim_intent_v1 as claim_contract
import requirement_progress_v1 as progress_contract
import selftest_p3b1_entry_seam as entry_fixtures


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _task(path: Path) -> None:
    path.write_text(
        "id,title,design_url,ui_notes,interaction,api,status,error,spec_dir\n"
        "1,Login,https://example.invalid/design,Use brand colors,Tap submit,/login,,,\n",
        encoding="utf-8",
    )


def _intent(path: Path, *, selection_digest: str | None = None) -> dict:
    selection_digest = selection_digest or _digest("selection")
    row_digest = _digest("row:Login")
    requirement_id = progress_contract.derive_requirement_id(selection_digest, row_digest)
    return csv_task_source.prepare_claim_intent(
        path,
        "Login",
        requirement_id=requirement_id,
        selection_manifest_digest=selection_digest,
        row_identity_digest=row_digest,
        task_source_snapshot_digest=_digest("snapshot"),
        candidate_identity_digest=_digest("candidate:Login"),
    )


def test_empty_row_recovery_performs_one_legacy_cas_then_reconstructs_ack() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-csv-") as directory:
        task = Path(directory) / "tasks.csv"
        _task(task)
        intent = _intent(task)
        claim_contract.verify_claim_intent(intent)

        first = csv_task_source.recover_claim_with_intent(task, "Login", intent)
        assert first["recovery_report"]["decision"] == "retry-cas"
        ack = first["claim_ack"]
        assert ack["status"] == "doing"
        assert ack["sha256_before"] == intent["source_sha256_before"]
        assert ack["sha256_after"] == intent["expected_source_sha256_after"]

        second = csv_task_source.recover_claim_with_intent(task, "Login", intent)
        assert second["recovery_report"]["decision"] == "reconstruct-claim-ack"
        assert second["claim_ack"] == ack


def test_claim_with_intent_keeps_legacy_ack_shape() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-csv-shape-") as directory:
        task = Path(directory) / "tasks.csv"
        _task(task)
        intent = _intent(task)
        ack = csv_task_source.claim_with_intent(task, "Login", intent)
        assert list(ack) == [
            "kind",
            "schema_version",
            "ok",
            "task_ref",
            "row_identity",
            "row_index",
            "previous_status",
            "status",
            "sha256_before",
            "sha256_after",
        ]
        assert csv_task_source.ack_to_json_bytes(ack).endswith(b"\n")


def test_source_drift_blocks_without_mutation() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-csv-drift-") as directory:
        task = Path(directory) / "tasks.csv"
        _task(task)
        intent = _intent(task)
        before = task.read_bytes()
        task.write_bytes(before.replace(b"Use brand colors", b"Use safe colors"))
        drifted = task.read_bytes()
        result = csv_task_source.recover_claim_with_intent(task, "Login", intent)
        assert result["recovery_report"]["decision"] == "blocked"
        assert result["claim_ack"] is None
        assert task.read_bytes() == drifted


def test_persisted_scope_recovers_claim_and_activates_after_restart() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-pending-") as directory:
        root = Path(directory)
        task = root / "tasks.csv"
        _task(task)
        selection = root / "selection-manifest.json"
        readiness = root / "entry-readiness.json"
        package = root / "platform-package-selection.json"
        selection.write_bytes(b'{"kind":"selection"}\n')
        readiness.write_bytes(b'{"kind":"readiness"}\n')
        package.write_bytes(b'{"kind":"package"}\n')
        selection_digest = hashlib.sha256(selection.read_bytes()).hexdigest()
        intent = _intent(task, selection_digest=selection_digest)
        scope = {
            "kind": "icp.requirement-execution-scope.v1",
            "schema_version": 1,
            "requirement_id": intent["requirement_id"],
            "task_ref": str(task.resolve()),
            "row_identity": "Login",
            "selection_manifest_path": str(selection.resolve()),
            "selection_manifest_digest": selection_digest,
            "entry_readiness_path": str(readiness.resolve()),
            "entry_readiness_digest": hashlib.sha256(readiness.read_bytes()).hexdigest(),
            "platform_package_selection_path": str(package.resolve()),
            "platform_package_selection_digest": hashlib.sha256(package.read_bytes()).hexdigest(),
            "verified_operation_plan_digest": _digest("operation-plan"),
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
        store = orchestrator.RequirementStateStore(root / "state")
        with store.exclusive_lock():
            store.publish_claim_intent(intent)
            store.publish_execution_scope(scope)

        reopened = orchestrator.RequirementStateStore(root / "state")
        with reopened.exclusive_lock():
            recovered = orchestrator.recover_pending_csv_claim(reopened)
            assert recovered["decision"] == "claim-activated"
            assert recovered["recovery_report"]["decision"] == "retry-cas"
            assert reopened.load_snapshot()["active"] == recovered["active"]
            decision = orchestrator.decide_stored_resume(
                reopened, prerequisites_status="met", observed_row_status="doing"
            )
            assert decision["decision"] == "resume-step"
            assert decision["step_id"] == "visible_implementation"

        restarted = orchestrator.RequirementStateStore(root / "state")
        with restarted.exclusive_lock():
            assert orchestrator.recover_pending_csv_claim(restarted)["decision"] == "active-present"


def test_writeback_intent_reconstructs_ack_after_terminal_cas_crash() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-writeback-") as directory:
        task = Path(directory) / "tasks.csv"
        _task(task)
        claim_intent = _intent(task)
        claim_ack = csv_task_source.claim_with_intent(task, "Login", claim_intent)
        writeback_intent = csv_task_source.prepare_writeback_intent(task, claim_ack, outcome="done")
        original_ack = csv_task_source.writeback(task, claim_ack, outcome="done")
        recovered = csv_task_source.recover_writeback_with_intent(task, claim_ack, writeback_intent)
        assert recovered["decision"] == "reconstruct-writeback-ack"
        assert recovered["writeback_ack"] == original_ack


def test_terminal_finalize_writes_done_clears_mutable_state_and_allows_next_scope() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-finalize-") as directory:
        root = Path(directory)
        task = root / "tasks.csv"
        _task(task)
        artifacts = []
        for name in ("selection-manifest.json", "entry-readiness.json", "platform-package-selection.json"):
            path = root / name
            path.write_text(f'{{"kind":"{name}"}}\n', encoding="utf-8")
            artifacts.append(path)
        intent = _intent(task, selection_digest=hashlib.sha256(artifacts[0].read_bytes()).hexdigest())
        scope = {
            "kind": "icp.requirement-execution-scope.v1",
            "schema_version": 1,
            "requirement_id": intent["requirement_id"],
            "task_ref": str(task.resolve()),
            "row_identity": "Login",
            "selection_manifest_path": str(artifacts[0].resolve()),
            "selection_manifest_digest": hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
            "entry_readiness_path": str(artifacts[1].resolve()),
            "entry_readiness_digest": hashlib.sha256(artifacts[1].read_bytes()).hexdigest(),
            "platform_package_selection_path": str(artifacts[2].resolve()),
            "platform_package_selection_digest": hashlib.sha256(artifacts[2].read_bytes()).hexdigest(),
            "verified_operation_plan_digest": _digest("operation-plan"),
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
        store = orchestrator.RequirementStateStore(root / "state")
        with store.exclusive_lock():
            store.publish_claim_intent(intent)
            store.publish_execution_scope(scope)
            orchestrator.recover_pending_csv_claim(store)
            snapshot = store.load_snapshot()
            done_progress = copy.deepcopy(snapshot["progress"])
            done_progress["revision"] = 1
            done_progress["phase"] = "running"
            done_progress["feature_positions"][0] = {
                "feature_id": "feature.login",
                "state": "done",
                "inflight_step_id": None,
                "next_step_id": None,
                "replay_policy": "none",
                "recovery_verifier_digest": None,
                "last_checkpoint_receipt_digest": None,
            }
            store.replace_progress(done_progress, expected_revision=0)
            result = orchestrator.finalize_active_csv_requirement(
                store,
                outcome="done",
                evidence={"actual_source": "browser_screenshot", "visual_diff": _digest("diff")},
            )
            assert result["cleanup_report"]["next_requirement_allowed"] is True
            assert store.load_snapshot()["active"] is None
            assert store.unactivated_execution_scopes() == []
        assert ",done," in task.read_text(encoding="utf-8")


def test_entry_gate_refuses_inactive_package_before_claim_or_publication() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-p3d-entry-") as directory:
        root = Path(directory)
        task = root / "tasks.csv"
        _task(task)
        project = root / "project"
        project.mkdir()
        registry = entry_fixtures._synthetic_activated_registry(
            platform_id="flutter", profile_id="flutter-standard"
        )
        config = entry_fixtures._synthetic_resolved_config(
            platform_id="flutter",
            profile_id="flutter-standard",
            task_ref=str(task.resolve()),
            project_root=str(project.resolve()),
        )
        resolution = entry_fixtures._resolve_synthetic_package(
            platform_id="flutter",
            profile_id="flutter-standard",
            registry=registry,
        )
        descriptor = entry_fixtures._synthetic_descriptor(
            platform_id="flutter",
            profile_id="flutter-standard",
            registry_digest=resolution["registry_digest"],
            selected_profile_digest=resolution["selected_profile_digest"],
            activation_state="inactive",
            executable=False,
        )
        config_digest = hashlib.sha256(
            (json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        ).hexdigest()
        report = entry_fixtures._ready_readiness_report(
            resolved_config_digest=config_digest,
            package_descriptor_digest=resolution["package_descriptor_digest"],
            task_source_snapshot_digest=_digest("task-snapshot"),
            candidate_identity_digest=_digest("candidate:Login"),
            candidate_count=1,
            package_descriptor=descriptor,
        )
        decision = entry_fixtures._select_new_decision(readiness_report=report)
        result = orchestrator.prepare_single_requirement_with_entry_gate(
            resolved_config=config,
            registries=registry,
            readiness_report=report,
            entry_gate_decision=decision,
            package_resolution=resolution,
            package_verification_digest=_digest("package-verification"),
            verified_operation_plan_digest=_digest("operation-plan"),
            feature_positions=[
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
            batch_id="entry-batch",
        )
        assert result["decision"] == "claim-failed"
        assert result["preparation"]["gate_code"] == "platform_package_inactive"
        assert result["published"] == {}
        assert task.read_text(encoding="utf-8").count(",doing,") == 0


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
