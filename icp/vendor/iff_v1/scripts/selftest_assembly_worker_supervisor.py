#!/usr/bin/env python3
"""Regression for the fail-closed assembly process/agent handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from selftest_assembly_completion_evidence import make_complete_spec
from scope_api_contract import build_from_files


def execute(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True)


def main() -> int:
    scripts = Path(__file__).resolve().parent
    supervisor = scripts / "assembly_worker_supervisor.py"
    completion = scripts / "assembly_completion.py"

    with tempfile.TemporaryDirectory(prefix="iff-assembly-supervisor-") as raw_tmp:
        root = Path(raw_tmp)
        feature = make_complete_spec(root, scripts)
        project = feature.parents[2]
        registry = project / ".iff" / "shared_components.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(
            json.dumps({"version": 1, "components": {}}),
            encoding="utf-8",
        )
        for shared_contract in feature.glob("*/shared_components.local.json"):
            shared_contract.write_text(
                json.dumps({"registry": str(registry), "components": []}),
                encoding="utf-8",
            )
        api_inputs = {
            "api_contract.json": {"contractScope": "project", "endpoints": {}},
            "row.json": {"title": "assembly-supervisor-selftest", "api": ""},
            "interaction_contract.json": {"rules": []},
            "api_endpoint_selection.json": {
                "contractScope": "feature-selection",
                "apiRequired": False,
                "basis": {"rowApi": "", "interactionRuleIds": []},
                "selectedEndpoints": [],
            },
        }
        for name, value in api_inputs.items():
            (feature / name).write_text(json.dumps(value), encoding="utf-8")
        feature_contract = feature / "feature_api_contract.json"
        feature_contract.write_text(
            json.dumps(
                build_from_files(
                    feature / "api_contract.json",
                    feature / "row.json",
                    feature / "interaction_contract.json",
                    feature / "api_endpoint_selection.json",
                )
            ),
            encoding="utf-8",
        )
        (feature / "api_integration_report.json").write_text(
            json.dumps(
                {
                    "contractScope": "feature",
                    "contractSha256": hashlib.sha256(feature_contract.read_bytes()).hexdigest(),
                    "apiRequired": False,
                    "operationCount": 0,
                    "selected": [],
                    "integrated": [],
                    "missing": [],
                    "ok": True,
                }
            ),
            encoding="utf-8",
        )
        prompt = feature / "worker_prompt.md"
        prompt.write_text("bounded supervisor selftest prompt\n", encoding="utf-8")
        contract_path = feature / "worker_prompt.md.assembly_invocation.json"
        contract = {
            "schemaVersion": 2,
            "kind": "iff_assembly_invocation",
            "sessionMode": "fresh_only",
            "resumeAllowed": False,
            "recoveryMode": "strict-tdd",
            "prompt": str(prompt),
            "promptSha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "specRoot": str(feature),
            "projectRoot": str(project),
            "evidence": str(feature / "assembly_completion.json"),
            "state": str(feature / "assembly_supervisor_state.json"),
            "completionVerifier": str(completion),
            "supervisor": str(supervisor),
            "workerExitIsSuccess": False,
            "successCriterion": "assembly_worker_supervisor.py verify must accept fresh evidence",
        }
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        assert contract["workerExitIsSuccess"] is False
        assert contract["successCriterion"].startswith("assembly_worker_supervisor.py verify")

        evidence = feature / "assembly_completion.json"
        resumed_marker = root / "resumed-worker-ran"
        resumed = execute(
            sys.executable,
            str(supervisor),
            "run",
            "--contract",
            str(contract_path),
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(resumed_marker)!r}).write_text('ran')",
            "resume",
        )
        assert resumed.returncode != 0, resumed.stdout + resumed.stderr
        assert "fresh session; resume is forbidden" in resumed.stderr
        assert not resumed_marker.exists(), "resumed worker command must not launch"
        stale = execute(
            sys.executable,
            str(completion),
            "issue",
            "--spec-root",
            str(feature),
            "--evidence",
            str(evidence),
        )
        assert stale.returncode == 0, stale.stdout + stale.stderr
        assert evidence.is_file()

        empty_exit_zero = execute(
            sys.executable,
            str(supervisor),
            "run",
            "--contract",
            str(contract_path),
            "--",
            sys.executable,
            "-c",
            "pass",
        )
        assert empty_exit_zero.returncode != 0, empty_exit_zero.stdout + empty_exit_zero.stderr
        assert "without fresh completion evidence" in (
            empty_exit_zero.stdout + empty_exit_zero.stderr
        )
        assert not evidence.exists(), "stale completion evidence must be removed before launch"

        startup_error = (
            "import sys; "
            "sys.stderr.write('WARNING could not create PATH aliases: Operation not permitted\\n'"
            "+ 'Error failed to initialize in-process app-server client: Operation not permitted\\n'); "
            "raise SystemExit(1)"
        )
        external_blocker = execute(
            sys.executable,
            str(supervisor),
            "run",
            "--contract",
            str(contract_path),
            "--",
            sys.executable,
            "-c",
            startup_error,
        )
        assert external_blocker.returncode != 0
        failure_path = Path(contract["state"]).with_suffix(".failure.json")
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        state = json.loads(Path(contract["state"]).read_text(encoding="utf-8"))
        assert state["status"] == "external_blocker"
        assert failure["classification"] == "external_sandbox_permission_startup"
        assert failure["owner"] == "main_session"
        assert failure["requiresEscalation"] is True
        assert len(failure["matchedDiagnostics"]) == 2
        retry = failure["retryContract"]
        assert retry["requiresEscalation"] is True
        assert retry["autoEscalationAllowed"] is False
        assert retry["supervisorBypassAllowed"] is False
        assert retry["argv"][1] == str(supervisor)
        assert retry["argv"][-3:] == [sys.executable, "-c", startup_error]
        assert not evidence.exists()

        worker_failure = execute(
            sys.executable,
            str(supervisor),
            "run",
            "--contract",
            str(contract_path),
            "--",
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('worker failed\\n'); raise SystemExit(7)",
        )
        assert worker_failure.returncode == 7
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        state = json.loads(Path(contract["state"]).read_text(encoding="utf-8"))
        assert state["status"] == "worker_failed"
        assert failure["classification"] == "worker_failure"
        assert failure["requiresEscalation"] is False
        assert failure["retryContract"]["requiresEscalation"] is False
        assert not evidence.exists()

        fresh_success = execute(
            sys.executable,
            str(supervisor),
            "run",
            "--contract",
            str(contract_path),
            "--",
            sys.executable,
            str(completion),
            "issue",
            "--spec-root",
            str(feature),
            "--evidence",
            str(evidence),
        )
        assert fresh_success.returncode == 0, fresh_success.stdout + fresh_success.stderr
        state = json.loads(Path(contract["state"]).read_text(encoding="utf-8"))
        assert state["status"] == "accepted"
        assert state["evidenceSha256"]
        assert evidence.stat().st_mtime_ns >= state["startedAtNs"]
        assert not failure_path.exists()

    print(
        "PASS: external startup blockers and worker failures are distinct; "
        "fresh verified evidence is still required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
