#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import icp_entry_v1
import selftest_p1b as p1b_fixtures
from platforms import flutter_project_preflight_v1
from platforms import nextjs_package_v1


def _config(path: Path, task: Path, project: Path, platform: str, profile: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "task_source": "csv",
                "task_ref": str(task),
                "design_source": "lanhu-figma",
                "platform": platform,
                "project_root": str(project),
                "profile": profile,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _no_doing_csv() -> bytes:
    return p1b_fixtures._good_csv_multi().replace(b",doing\n", b",done\n")


def test_nextjs_missing_runtime_config_is_reported_before_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-next-") as directory:
        root = Path(directory).resolve()
        task = root / "tasks.csv"
        task.write_bytes(
            _no_doing_csv().replace(
                b"https://figma.com/file/a", b"https://lanhuapp.com/path?image_id=abc"
            )
        )
        project = root / "project"
        project.mkdir()
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "next-fixture",
                    "scripts": {"build": "next build", "test": "node --test"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (project / "next.config.js").write_text("export default {};\n", encoding="utf-8")
        before = task.read_bytes()
        with mock.patch(
            "design_sources.lanhu_figma_v1.probe",
            return_value={"kind": "icp.design-source-probe.v1", "ok": True},
        ):
            result = icp_entry_v1.preflight(
                _config(root / "config.json", task, project, "nextjs", "nextjs-standard")
            )
        assert result["status"] == "needs-user-input", result
        assert "runtime_config" in {item["id"] for item in result["missing_inputs"]}
        assert any(
            ".icp/platform-config.json" in item["detail"]
            for item in result["missing_inputs"]
            if item["id"] == "runtime_config"
        )
        assert task.read_bytes() == before


def test_nextjs_complete_entry_materials_return_ready_without_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-next-ready-") as directory:
        root = Path(directory).resolve()
        task = root / "tasks.csv"
        task.write_bytes(
            _no_doing_csv().replace(
                b"https://figma.com/file/a", b"https://lanhuapp.com/path?image_id=abc"
            )
        )
        project = root / "project"
        project.mkdir()
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "next-fixture",
                    "scripts": {"dev": "next dev", "build": "next build", "test": "node --test"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (project / "next.config.js").write_text("export default {};\n", encoding="utf-8")
        (project / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (project / "node_modules" / "next").mkdir(parents=True)
        (project / "node_modules" / "react").mkdir(parents=True)
        (project / "node_modules" / "next" / "package.json").write_text("{}\n", encoding="utf-8")
        (project / "node_modules" / "react" / "package.json").write_text("{}\n", encoding="utf-8")
        (project / ".icp").mkdir()
        (project / ".icp" / "platform-config.json").write_text(
            json.dumps({"route": "/", "viewport_width": 390, "viewport_height": 844}),
            encoding="utf-8",
        )
        bin_dir = root / "bin"
        bin_dir.mkdir()
        tools = {}
        for name in ("node", "npm"):
            executable = bin_dir / name
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            tools[name] = str(executable)
        before = task.read_bytes()
        with (
            mock.patch(
                "design_sources.lanhu_figma_v1.probe",
                return_value={"kind": "icp.design-source-probe.v1", "ok": True},
            ),
            mock.patch(
                "platforms.inactive_platform_core_v1.shutil.which",
                side_effect=lambda name: tools.get(name),
            ),
            mock.patch.object(
                icp_entry_v1.csv_task_source,
                "probe_write_readiness",
                wraps=icp_entry_v1.csv_task_source.probe_write_readiness,
            ) as write_probe,
        ):
            result = icp_entry_v1.preflight(
                _config(root / "config.json", task, project, "nextjs", "nextjs-standard")
            )
        assert result["status"] == "ready", result
        assert result["unattended_ready"] is True
        assert result["readiness_report"]["kind"] == "icp.entry-readiness-report.v1"
        assert result["entry_gate_decision"]["decision"] == "select-new"
        assert result["package_resolution"]["activation_state"] == "active"
        assert result["package_resolution"]["executable"] is True
        assert result["task_write_probe"]["ok"] is True
        write_probe.assert_called_once_with(task)
        assert task.read_bytes() == before


def test_flutter_entry_requires_and_probes_selected_device() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-flutter-runtime-") as directory:
        project = Path(directory).resolve()
        inspection = flutter_project_preflight_v1.inspect_entry_requirements(project)
        assert "runtime_config" in {item["id"] for item in inspection["missing_inputs"]}

        (project / ".icp").mkdir()
        (project / "lib").mkdir()
        (project / ".dart_tool").mkdir()
        (project / "pubspec.yaml").write_text("name: fixture\n", encoding="utf-8")
        (project / "pubspec.lock").write_text("packages: {}\n", encoding="utf-8")
        (project / ".dart_tool" / "package_config.json").write_text("{}", encoding="utf-8")
        (project / ".icp" / "platform-config.json").write_text(
            json.dumps({"device_id": "SIM-1"}), encoding="utf-8"
        )
        completed = mock.Mock(returncode=0, stdout=b'[{"id":"SIM-1"}]', stderr=b"")
        platform_report = {"toolchain": {"flutter_executable": "/fixed/flutter"}}
        with mock.patch.object(flutter_project_preflight_v1.shutil, "which", return_value="/fixed/flutter"), mock.patch.object(
            flutter_project_preflight_v1, "preflight", return_value=platform_report
        ), mock.patch.object(flutter_project_preflight_v1.subprocess, "run", return_value=completed) as run:
            inspection = flutter_project_preflight_v1.inspect_entry_requirements(project)
        assert inspection["missing_inputs"] == []
        runtime = inspection["platform_report"]["runtime_target"]
        assert runtime["status"] == "pass"
        assert runtime["device_id"] == "SIM-1"
        assert len(runtime["platform_config_digest"]) == 64
        assert run.call_args.args[0] == ["/fixed/flutter", "devices", "--machine"]


def test_active_requirement_wins_when_no_pending_claim_exists() -> None:
    store = mock.Mock()
    store.state_root = Path("/controlled-state")
    store.load_snapshot.return_value = {
        "active": {
            "requirement_id": "a" * 64,
            "claim_ack_digest": "c" * 64,
            "progress_id": "b" * 64,
        },
        "progress": {"progress_id": "b" * 64},
        "receipts": [],
    }
    store.load_execution_scope.return_value = {
        "requirement_id": "a" * 64,
        "selection_manifest_digest": "d" * 64,
        "verified_operation_plan_digest": "e" * 64,
        "task_ref": "/controlled/tasks.csv",
        "row_identity": {"row_index": 1},
    }
    store._read_json.return_value = {
        "kind": "icp.requirement-claim-intent.v1",
        "row_identity_digest": "f" * 64,
    }
    with mock.patch.object(
        icp_entry_v1.orchestrator,
        "recover_pending_csv_claim",
        return_value={"decision": "no-pending-claim"},
    ), mock.patch.object(
        icp_entry_v1.csv_task_source,
        "recover_claim_with_intent",
        return_value={"recovery_report": {"observed_status": "doing"}},
    ), mock.patch.object(
        icp_entry_v1.orchestrator,
        "decide_stored_resume",
        return_value={"decision": "resume-step", "step_id": "feature.build"},
    ):
        decision = icp_entry_v1._active_status(store, "met")
    assert decision["decision"] == "resume-required"
    assert decision["resume_decision"] == {
        "decision": "resume-step",
        "step_id": "feature.build",
    }


def test_active_requirement_with_missing_prerequisite_is_not_unattended_ready() -> None:
    store = mock.Mock()
    store.state_root = Path("/controlled-state")
    store.load_snapshot.return_value = {
        "active": {
            "requirement_id": "a" * 64,
            "claim_ack_digest": "c" * 64,
            "progress_id": "b" * 64,
        },
        "progress": {"progress_id": "b" * 64},
        "receipts": [],
    }
    store.load_execution_scope.return_value = {
        "requirement_id": "a" * 64,
        "selection_manifest_digest": "d" * 64,
        "verified_operation_plan_digest": "e" * 64,
        "task_ref": "/controlled/tasks.csv",
        "row_identity": {"row_index": 1},
    }
    store._read_json.return_value = {
        "kind": "icp.requirement-claim-intent.v1",
        "row_identity_digest": "f" * 64,
    }
    with mock.patch.object(
        icp_entry_v1.orchestrator,
        "recover_pending_csv_claim",
        return_value={"decision": "no-pending-claim"},
    ), mock.patch.object(
        icp_entry_v1.csv_task_source,
        "recover_claim_with_intent",
        return_value={"recovery_report": {"observed_status": "doing"}},
    ), mock.patch.object(
        icp_entry_v1.orchestrator,
        "decide_stored_resume",
        return_value={"decision": "needs-user-input", "reason_code": "prerequisite-missing"},
    ):
        decision = icp_entry_v1._active_status(store, "missing")
    assert decision["decision"] == "needs-user-input"


def test_platform_inspection_failure_cannot_produce_ready_canonical_gate() -> None:
    report, decision = icp_entry_v1._readiness_documents(
        resolved={"task_source": "csv", "design_source": "lanhu-figma"},
        descriptor=nextjs_package_v1.describe_package(),
        probe={"sha256": "1" * 64},
        task_write_probe={"evidence_digest": "2" * 64},
        candidates=[{"row_index": 1}],
        design_probe={"ok": True},
        platform_report=None,
        platform_missing=[
            {
                "id": "platform_project_preflight",
                "owner": "environment",
                "remediation": "repair selected package",
                "detail": "inspection failed",
            }
        ],
    )
    assert report["status"] != "ready"
    assert decision["decision"] != "select-new"


def test_nextjs_no_candidate_returns_no_work_without_state_or_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-next-no-work-") as directory:
        root = Path(directory).resolve()
        task = root / "tasks.csv"
        task.write_bytes(
            p1b_fixtures._good_csv_multi()
            .replace(b"ap-A,\n", b"ap-A,done\n")
            .replace(b"ap-B,\n", b"ap-B,done\n")
            .replace(b"ap-D,doing\n", b"ap-D,done\n")
        )
        project = root / "project"
        project.mkdir()
        (project / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"dev": "next dev", "build": "next build", "test": "node --test"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (project / "next.config.js").write_text("export default {};\n", encoding="utf-8")
        (project / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (project / "node_modules" / "next").mkdir(parents=True)
        (project / "node_modules" / "react").mkdir(parents=True)
        (project / ".icp").mkdir()
        (project / ".icp" / "platform-config.json").write_text(
            json.dumps({"route": "/", "viewport_width": 390, "viewport_height": 844}),
            encoding="utf-8",
        )
        bin_dir = root / "bin"
        bin_dir.mkdir()
        tools = {}
        for name in ("node", "npm"):
            executable = bin_dir / name
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            tools[name] = str(executable)
        before = task.read_bytes()
        with mock.patch(
            "platforms.inactive_platform_core_v1.shutil.which",
            side_effect=lambda name: tools.get(name),
        ):
            result = icp_entry_v1.preflight(
                _config(root / "config.json", task, project, "nextjs", "nextjs-standard")
            )
        assert result["status"] == "no-work", result
        assert result["candidate_count"] == 0
        assert task.read_bytes() == before
        assert not (project / ".icp" / "icp-requirements-v1").exists()


def test_orphan_doing_row_blocks_before_new_candidate_or_design_probe() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-orphan-doing-") as directory:
        root = Path(directory).resolve()
        task = root / "tasks.csv"
        task.write_bytes(p1b_fixtures._good_csv_multi())
        before = task.read_bytes()
        project = root / "project"
        (project / ".icp").mkdir(parents=True)
        config_document = {"route": "/", "viewport_width": 390, "viewport_height": 844}
        (project / ".icp" / "platform-config.json").write_text(json.dumps(config_document))
        platform_report = {
            "kind": "icp.nextjs-project-preflight.v1",
            "platform_config_digest": icp_entry_v1.hashlib.sha256(
                icp_entry_v1._canonical(config_document)
            ).hexdigest(),
            "status": "pass",
        }
        inspection = {
            "kind": "icp.nextjs-entry-requirements-inspection.v1",
            "platform_id": "nextjs",
            "platform_report": platform_report,
            "missing_inputs": [],
        }
        with mock.patch.object(
            icp_entry_v1,
            "_platform_preflight",
            return_value=(platform_report, [], inspection),
        ), mock.patch.object(
            icp_entry_v1.csv_task_source, "select_candidates"
        ) as select_candidates, mock.patch(
            "design_sources.lanhu_figma_v1.probe"
        ) as design_probe:
            result = icp_entry_v1.preflight(
                _config(root / "config.json", task, project, "nextjs", "nextjs-standard")
            )
        assert result["status"] == "blocked", result
        assert result["blockers"][0]["id"] == "orphan_doing_without_state"
        assert result["candidate_count"] == 0
        select_candidates.assert_not_called()
        design_probe.assert_not_called()
        assert task.read_bytes() == before


def test_vue_missing_installation_is_reported_before_activation_or_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-entry-vue-") as directory:
        root = Path(directory).resolve()
        task = root / "tasks.csv"
        task.write_bytes(_no_doing_csv())
        project = root / "project"
        project.mkdir()
        package = {
            "name": "vue-fixture",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "test:unit": "vitest run tests/unit",
                "test:e2e": "playwright test",
            },
            "dependencies": {"vue": "3.5.0"},
            "devDependencies": {"vite": "7.0.0", "vitest": "3.0.0", "@playwright/test": "1.50.0"},
        }
        (project / "package.json").write_text(json.dumps(package), encoding="utf-8")
        (project / "index.html").write_text("<div id='app'></div>\n", encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "main.js").write_text("// main\n", encoding="utf-8")
        (project / "src" / "App.vue").write_text("<template/>\n", encoding="utf-8")
        (project / "tests" / "unit").mkdir(parents=True)
        (project / "tests" / "e2e").mkdir(parents=True)
        before = task.read_bytes()
        result = icp_entry_v1.preflight(
            _config(root / "config.json", task, project, "vue", "vue-vite")
        )
        assert result["status"] == "needs-user-input"
        assert "dependencies" in {item["id"] for item in result["missing_inputs"]}
        assert task.read_bytes() == before


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
