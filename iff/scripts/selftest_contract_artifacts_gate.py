#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_JSON_ARTIFACTS = (
    "interaction_contract.json",
    "interaction_completeness_report.json",
    "interaction_promotion_report.json",
    "state_machine.json",
    "interaction_anchors.json",
    "oas_missing_ref_paths.json",
    "row.json",
    "api_contract.json",
    "api_endpoint_selection.json",
    "feature_api_contract.json",
    "interaction_test_plan.json",
)


def write_fixture(
    spec: Path,
    index: Path,
    *,
    anchors: list[dict[str, object]] | None,
    interaction_rules: list[dict[str, object]] | None = None,
) -> None:
    spec.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    index.write_text("{}\n", encoding="utf-8")
    for name in REQUIRED_JSON_ARTIFACTS:
        if name == "interaction_anchors.json" and anchors is None:
            continue
        value: object = {"anchors": anchors} if name == "interaction_anchors.json" else {}
        (spec / name).write_text(json.dumps(value) + "\n", encoding="utf-8")
    (spec / "interaction_contract.json").write_text(
        json.dumps({"rules": interaction_rules or []}) + "\n", encoding="utf-8"
    )
    project_contract = {
        "contractScope": "project",
        "endpointCount": 0,
        "operationCount": 0,
        "endpoints": {},
        "source": {},
    }
    row = {"title": "fixture", "api": ""}
    selection = {
        "contractScope": "feature-selection",
        "apiRequired": False,
        "basis": {"rowApi": "", "interactionRuleIds": []},
        "selectedEndpoints": [],
    }
    (spec / "api_contract.json").write_text(json.dumps(project_contract) + "\n", encoding="utf-8")
    (spec / "row.json").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (spec / "api_endpoint_selection.json").write_text(json.dumps(selection) + "\n", encoding="utf-8")
    scoped = subprocess.run(
        [
            "python3",
            str(Path(__file__).resolve().parent / "scope_api_contract.py"),
            "--project-contract",
            str(spec / "api_contract.json"),
            "--row-json",
            str(spec / "row.json"),
            "--interaction-contract",
            str(spec / "interaction_contract.json"),
            "--selection",
            str(spec / "api_endpoint_selection.json"),
            "--out",
            str(spec / "feature_api_contract.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert scoped.returncode == 0, scoped.stdout + scoped.stderr


def run_gate(scripts: Path, spec: Path, index: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(scripts / "check_contract_artifacts.py"),
            "--spec-dir",
            str(spec),
            "--index",
            str(index),
        ],
        text=True,
        capture_output=True,
    )


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-contract-artifacts-gate-") as raw_tmp:
        tmp = Path(raw_tmp)

        missing_spec = tmp / "missing" / "spec"
        missing_index = tmp / "missing" / "project" / ".iff" / "board_index.json"
        write_fixture(missing_spec, missing_index, anchors=None)
        missing_result = run_gate(scripts, missing_spec, missing_index)
        assert missing_result.returncode != 0, missing_result.stdout
        assert "interaction_anchors.json" in missing_result.stderr, missing_result.stderr

        no_refs_spec = tmp / "valid-no-refs" / "spec"
        no_refs_index = tmp / "valid-no-refs" / "project" / ".iff" / "board_index.json"
        write_fixture(no_refs_spec, no_refs_index, anchors=[])
        no_refs_result = run_gate(scripts, no_refs_spec, no_refs_index)
        assert no_refs_result.returncode == 0, no_refs_result.stderr or no_refs_result.stdout
        assert "anchors validated" in no_refs_result.stdout, no_refs_result.stdout

        empty_plan_spec = tmp / "invalid-empty-plan" / "spec"
        empty_plan_index = tmp / "invalid-empty-plan" / "project" / ".iff" / "board_index.json"
        write_fixture(
            empty_plan_spec,
            empty_plan_index,
            anchors=[],
            interaction_rules=[{"id": "INT-001"}],
        )
        (empty_plan_spec / "interaction_test_plan.json").write_text(
            json.dumps({"caseCount": 0, "cases": []}) + "\n", encoding="utf-8"
        )
        empty_plan_result = run_gate(scripts, empty_plan_spec, empty_plan_index)
        assert empty_plan_result.returncode != 0, empty_plan_result.stdout
        assert "missing interaction test cases" in empty_plan_result.stderr, empty_plan_result.stderr

        complete_plan_spec = tmp / "valid-complete-plan" / "spec"
        complete_plan_index = tmp / "valid-complete-plan" / "project" / ".iff" / "board_index.json"
        write_fixture(
            complete_plan_spec,
            complete_plan_index,
            anchors=[],
            interaction_rules=[{"id": "INT-001"}],
        )
        complete_cases = [
            {"id": f"INT-001-{variant.upper()}", "interactionId": "INT-001", "variant": variant}
            for variant in ("happy", "boundary", "failure")
        ]
        (complete_plan_spec / "interaction_test_plan.json").write_text(
            json.dumps({"caseCount": 3, "cases": complete_cases}) + "\n", encoding="utf-8"
        )
        complete_plan_result = run_gate(scripts, complete_plan_spec, complete_plan_index)
        assert complete_plan_result.returncode == 0, complete_plan_result.stderr or complete_plan_result.stdout

        pending_spec = tmp / "valid-pending-route" / "spec"
        pending_index = tmp / "valid-pending-route" / "project" / ".iff" / "board_index.json"
        write_fixture(
            pending_spec,
            pending_index,
            anchors=[
                {
                    "rule": "INT-001",
                    "query": "next page",
                    "resolution": "unresolved",
                    "pending_route": "/next",
                }
            ],
        )
        pending_result = run_gate(scripts, pending_spec, pending_index)
        assert pending_result.returncode == 0, pending_result.stderr or pending_result.stdout
        assert "anchors validated" in pending_result.stdout, pending_result.stdout

    print("PASS: contract artifact gate fails closed; two isolated complete specs pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
