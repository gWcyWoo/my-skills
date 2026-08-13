#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import requirement_progress_v1 as progress_contract
import selftest_p2e2b_flutter_executor as flutter_fixtures
from platforms import flutter_operations_v1 as operations_v1
from platforms import flutter_requirement_execution_v1 as requirement_v1


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_existing_flutter_binding_authorization_gain_requirement_receipt_without_semantic_drift() -> None:
    executor_module = flutter_fixtures._load("p3d_flutter_executor_fixture")
    context = flutter_fixtures._build_verified_binding(
        executor_module,
        "flutter.fan_in.v1",
        flutter_fixtures._fan_in_done_gate_request,
    )
    values = context.__enter__()
    try:
        _, _, fixture_authorization, manifest_path, _, run_root, _, execution_nonce = values
        fixture_binding = fixture_authorization["verified_binding"]
        fake_preflight = flutter_fixtures._with_fake_preflight(requirement_v1.binding_v1)
        fake_preflight.__enter__()
        original_binding_loader = requirement_v1.authorization_v1._load_binding_module
        requirement_v1.authorization_v1._load_binding_module = lambda: requirement_v1.binding_v1
        base_binding = requirement_v1.binding_v1.prepare_binding(
            manifest_path,
            fixture_binding["operation_id"],
            fixture_binding["request"],
        )
        readiness_path = run_root / "entry-readiness.json"
        package_path = run_root / "platform-package-selection.json"
        readiness_path.write_bytes(b'{"kind":"readiness"}\n')
        package_path.write_bytes(b'{"kind":"package"}\n')
        selection_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        row_digest = _digest("row")
        requirement_id = progress_contract.derive_requirement_id(selection_digest, row_digest)
        claim_ack_digest = _digest("flutter-claim-ack")
        progress_id = progress_contract.derive_progress_id(requirement_id, claim_ack_digest)
        scope = {
            "kind": "icp.platform-requirement-scope.v1",
            "schema_version": 1,
            "requirement_id": requirement_id,
            "claim_intent_digest": _digest("flutter-claim-intent"),
            "progress_id": progress_id,
            "selection_manifest_path": str(manifest_path),
            "selection_manifest_digest": selection_digest,
            "entry_readiness_path": str(readiness_path),
            "entry_readiness_digest": hashlib.sha256(readiness_path.read_bytes()).hexdigest(),
            "platform_package_selection_path": str(package_path),
            "platform_package_selection_digest": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        }
        operation_plan = base_binding["plan"]
        requirement_plan = {
            "kind": "icp.flutter-requirement-operation-plan.v1",
            "schema_version": 1,
            "operation_id": base_binding["operation_id"],
            "requirement_scope": scope,
            "operation_plan": operation_plan,
            "operation_plan_digest": operations_v1._sha256_bytes(
                operations_v1._canonical_json_bytes(operation_plan)
            ),
        }
        requirement_v1.verify_plan(requirement_plan)
        wrapped_binding = {
            "kind": "icp.flutter-requirement-execution-binding.v1",
            "schema_version": 1,
            "requirement_plan": requirement_plan,
            "binding": base_binding,
            "binding_digest": requirement_v1.binding_v1.verify_binding(base_binding)["binding_digest"],
        }
        requirement_v1.verify_binding(wrapped_binding)
        authorization = requirement_v1.prepare_authorization(
            wrapped_binding, execution_nonce=execution_nonce
        )
        requirement_v1.verify_authorization(authorization)
        progress = {
            "kind": progress_contract.KIND_PROGRESS,
            "schema_version": 1,
            "requirement_id": requirement_id,
            "progress_id": progress_id,
            "claim_ack_digest": claim_ack_digest,
            "verified_operation_plan_digest": requirement_plan["operation_plan_digest"],
            "revision": 0,
            "phase": "running",
            "latest_checkpoint_receipt_digest": None,
            "checkpoint_count": 0,
            "feature_positions": [
                {
                    "feature_id": "feature.login",
                    "state": "started",
                    "inflight_step_id": "fan_in",
                    "next_step_id": "fan_in",
                    "replay_policy": "idempotent",
                    "recovery_verifier_digest": None,
                    "last_checkpoint_receipt_digest": None,
                }
            ],
        }
        progress_contract.verify_progress(progress)
        receipt = requirement_v1.build_checkpoint_receipt(
            authorization,
            {"kind": "icp.test-execution-report.v1", "status": "success"},
            progress=progress,
            feature_id="feature.login",
            step_id="fan_in",
            execution_mode="first-run",
        )
        progress_contract.verify_checkpoint_receipt(receipt)
        next_progress = dict(progress)
        next_progress["revision"] = 1
        next_progress["latest_checkpoint_receipt_digest"] = progress_contract.document_digest(receipt)
        next_progress["checkpoint_count"] = 1
        next_progress["feature_positions"] = [
            {
                "feature_id": "feature.login",
                "state": "done",
                "inflight_step_id": None,
                "next_step_id": None,
                "replay_policy": "none",
                "recovery_verifier_digest": None,
                "last_checkpoint_receipt_digest": progress_contract.document_digest(receipt),
            }
        ]
        active = {
            "kind": progress_contract.KIND_ACTIVE_REQUIREMENT,
            "schema_version": 1,
            "requirement_id": requirement_id,
            "selection_manifest_digest": selection_digest,
            "row_identity_digest": row_digest,
            "claim_intent_digest": scope["claim_intent_digest"],
            "claim_ack_digest": claim_ack_digest,
            "progress_id": progress_id,
        }
        progress_contract.verify_active_requirement(active)
        progress_contract.verify_checkpoint_chain([receipt], active=active, progress=next_progress)
    finally:
        if "original_binding_loader" in locals():
            requirement_v1.authorization_v1._load_binding_module = original_binding_loader
        if "fake_preflight" in locals():
            fake_preflight.__exit__(None, None, None)
        context.__exit__(None, None, None)


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
        except Exception as exc:  # pragma: no cover
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
