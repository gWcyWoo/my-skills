#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path
from unittest import mock

import icp_begin_requirement_v1 as begin_module
import csv_task_source
import selftest_p1b as p1b_fixtures


DIGEST = "a" * 64


def _entry(status: str, unattended_ready: bool) -> dict:
    return {
        "status": status,
        "unattended_ready": unattended_ready,
        "resolved_config": {"platform": "nextjs"},
        "readiness_report": {"kind": "icp.entry-readiness-report.v1"},
        "entry_gate_decision": {"decision": "select-new"},
        "package_resolution": {"platform_id": "nextjs"},
        "package_verification_digest": DIGEST,
    }


def test_begin_rechecks_ready_entry_and_calls_only_gated_prepare() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-begin-ready-") as directory:
        root = Path(directory)
        features = root / "features.json"
        features.write_text(json.dumps([{"feature_id": "home", "state": "pending"}]))
        prepared = {"requirement_id": "b" * 64}
        with mock.patch.object(begin_module.icp_entry_v1, "preflight", return_value=_entry("ready", True)), mock.patch.object(
            begin_module.icp_common, "load_registries", return_value={"platforms": {}}
        ), mock.patch.object(
            begin_module.orchestrator,
            "prepare_single_requirement_with_entry_gate",
            return_value=prepared,
        ) as prepare:
            result = begin_module.begin(
                config_path=root / "config.json",
                feature_positions_path=features,
                verified_operation_plan_digest=DIGEST,
            )
        assert result["status"] == "prepared"
        assert result["prepared"] == prepared
        kwargs = prepare.call_args.kwargs
        assert kwargs["readiness_report"] is result["entry"]["readiness_report"]
        assert kwargs["entry_gate_decision"] is result["entry"]["entry_gate_decision"]
        assert kwargs["package_verification_digest"] == DIGEST


def test_begin_does_not_claim_when_recheck_is_not_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-begin-missing-") as directory:
        root = Path(directory)
        features = root / "features.json"
        features.write_text(json.dumps([{"feature_id": "home", "state": "pending"}]))
        with mock.patch.object(
            begin_module.icp_entry_v1,
            "preflight",
            return_value=_entry("needs-user-input", False),
        ), mock.patch.object(
            begin_module.orchestrator, "prepare_single_requirement_with_entry_gate"
        ) as prepare:
            result = begin_module.begin(
                config_path=root / "config.json",
                feature_positions_path=features,
                verified_operation_plan_digest=DIGEST,
            )
        assert result["status"] == "needs-user-input"
        assert result["prepared"] is None
        prepare.assert_not_called()


def test_begin_real_entry_to_single_claim_bridge() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-begin-integration-") as directory:
        root = Path(directory).resolve()
        project = root / "project"
        project.mkdir()
        (project / ".icp").mkdir()
        platform_config = {"route": "/", "viewport_width": 390, "viewport_height": 844}
        (project / ".icp" / "platform-config.json").write_text(json.dumps(platform_config))
        task = root / "tasks.csv"
        task.write_bytes(
            p1b_fixtures._good_csv_multi().replace(b",doing\n", b",done\n")
        )
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "task_source": "csv",
                    "task_ref": str(task),
                    "design_source": "lanhu-figma",
                    "platform": "nextjs",
                    "profile": "nextjs-standard",
                    "project_root": str(project),
                }
            )
        )
        features = root / "features.json"
        features.write_text(
            json.dumps(
                [
                    {
                        "feature_id": "feature.login",
                        "state": "pending",
                        "inflight_step_id": None,
                        "next_step_id": "visible_implementation",
                        "replay_policy": "none",
                        "recovery_verifier_digest": None,
                        "last_checkpoint_receipt_digest": None,
                    }
                ]
            )
        )
        config_digest = hashlib.sha256(
            json.dumps(
                platform_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        platform_report = {
            "kind": "icp.nextjs-project-preflight.v1",
            "platform_config_digest": config_digest,
            "status": "pass",
        }
        inspection = {
            "kind": "icp.nextjs-entry-requirements-inspection.v1",
            "platform_id": "nextjs",
            "platform_report": platform_report,
            "missing_inputs": [],
        }
        with mock.patch.object(
            begin_module.icp_entry_v1,
            "_platform_preflight",
            return_value=(platform_report, [], inspection),
        ), mock.patch(
            "design_sources.lanhu_figma_v1.probe",
            return_value={"kind": "icp.design-source-probe.v1", "ok": True},
        ):
            result = begin_module.begin(
                config_path=config,
                feature_positions_path=features,
                verified_operation_plan_digest=DIGEST,
                batch_id="entry-bridge",
            )
        assert result["status"] == "prepared", result
        assert result["prepared"]["decision"] == "requirement-activated", result["prepared"]
        assert len(result["prepared"]["requirement_id"]) == 64, result["prepared"]
        statuses = csv_task_source.probe(task)["statuses"]
        assert statuses["doing"] == 1, statuses
        with mock.patch.object(
            begin_module.icp_entry_v1,
            "_platform_preflight",
            return_value=(platform_report, [], inspection),
        ):
            resumed = begin_module.icp_entry_v1.preflight(config)
        assert resumed["status"] == "resume-required", resumed
        assert resumed["unattended_ready"] is True
        assert resumed["candidate_count"] == 0
        assert resumed["entry_gate_decision"]["decision"] not in {"select-new", "no-work"}


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
            print(f"ok {name}")
        except Exception as exc:
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
