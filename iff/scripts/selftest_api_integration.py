#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_done_gate import api_gate_failures


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-api-integration-") as raw_tmp:
        root = Path(raw_tmp)
        spec = root / "spec"
        lib = root / "lib"
        spec.mkdir()
        lib.mkdir()
        project = {
            "source": "focused selftest",
            "contractScope": "project",
            "endpointCount": 46,
            "operationCount": 46,
            "endpoints": {
                f"/project/endpoint/{index}": {
                    "GET": {"summary": f"endpoint {index}", "responseFields": {}}
                }
                for index in range(46)
            },
        }
        row_api = "Load home summary and refresh offers"
        row = {"title": "home", "api": row_api}
        interaction = {"rules": [{"id": "INT-001"}]}
        selection = {
            "contractScope": "feature-selection",
            "apiRequired": True,
            "basis": {"rowApi": row_api, "interactionRuleIds": ["INT-001"]},
            "selectedEndpoints": [
                {"path": "/project/endpoint/7", "method": "GET"},
                {"path": "/project/endpoint/31", "method": "GET"},
            ],
        }
        project_path = spec / "api_contract.json"
        row_path = spec / "row.json"
        interaction_path = spec / "interaction_contract.json"
        selection_path = spec / "api_endpoint_selection.json"
        feature_path = spec / "feature_api_contract.json"
        report_path = spec / "api_integration_report.json"
        write_json(project_path, project)
        write_json(row_path, row)
        write_json(interaction_path, interaction)
        write_json(selection_path, selection)
        scoped = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_path),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(selection_path),
                "--out",
                str(feature_path),
            ],
            text=True,
            capture_output=True,
        )
        assert scoped.returncode == 0, scoped.stdout + scoped.stderr

        source = lib / "home_repository.dart"
        source.write_text(
            "const home = '/project/endpoint/7';\nconst offers = '/project/endpoint/31';\n",
            encoding="utf-8",
        )
        integrated = subprocess.run(
            [
                sys.executable,
                str(scripts / "check_api_integration.py"),
                "--api-contract",
                str(feature_path),
                "--lib-root",
                str(lib),
                "--out",
                str(report_path),
            ],
            text=True,
            capture_output=True,
        )
        assert integrated.returncode == 0, integrated.stdout + integrated.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["endpointCount"] == 2, report
        assert report["operationCount"] == 2, report
        assert report["selected"] == [
            "GET /project/endpoint/31",
            "GET /project/endpoint/7",
        ], report
        assert report["integrated"] == report["selected"], report
        assert report["missing"] == [], report
        assert api_gate_failures(spec) == [], api_gate_failures(spec)

        unscoped = subprocess.run(
            [
                sys.executable,
                str(scripts / "check_api_integration.py"),
                "--api-contract",
                str(project_path),
                "--lib-root",
                str(lib),
                "--out",
                str(spec / "unscoped_report.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert unscoped.returncode != 0, unscoped.stdout
        assert "contractScope=feature" in unscoped.stdout, unscoped.stdout

        source.write_text("const home = '/project/endpoint/7';\n", encoding="utf-8")
        missing = subprocess.run(
            [
                sys.executable,
                str(scripts / "check_api_integration.py"),
                "--api-contract",
                str(feature_path),
                "--lib-root",
                str(lib),
                "--out",
                str(spec / "missing_report.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert missing.returncode != 0, missing.stdout
        missing_report = json.loads((spec / "missing_report.json").read_text(encoding="utf-8"))
        assert missing_report["missing"] == ["GET /project/endpoint/31"], missing_report

        stale_report = dict(report)
        stale_report["integrated"] = ["GET /project/endpoint/7"]
        write_json(report_path, stale_report)
        gate_failures = api_gate_failures(spec)
        assert any("does not prove every selected endpoint" in item for item in gate_failures), gate_failures

        unscoped_feature = dict(project)
        write_json(feature_path, unscoped_feature)
        unscoped_gate = api_gate_failures(spec)
        assert any("feature API contract invalid" in item for item in unscoped_gate), unscoped_gate

        write_json(row_path, {"title": "static-home", "api": ""})
        write_json(interaction_path, {"rules": []})
        write_json(
            selection_path,
            {
                "contractScope": "feature-selection",
                "apiRequired": False,
                "basis": {"rowApi": "", "interactionRuleIds": []},
                "selectedEndpoints": [],
            },
        )
        no_api_scope = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_path),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(selection_path),
                "--out",
                str(feature_path),
            ],
            text=True,
            capture_output=True,
        )
        assert no_api_scope.returncode == 0, no_api_scope.stdout + no_api_scope.stderr
        no_api_check = subprocess.run(
            [
                sys.executable,
                str(scripts / "check_api_integration.py"),
                "--api-contract",
                str(feature_path),
                "--lib-root",
                str(lib),
                "--out",
                str(report_path),
            ],
            text=True,
            capture_output=True,
        )
        assert no_api_check.returncode == 0, no_api_check.stdout + no_api_check.stderr
        no_api_report = json.loads(report_path.read_text(encoding="utf-8"))
        assert no_api_report["apiRequired"] is False, no_api_report
        assert no_api_report["operationCount"] == 0, no_api_report
        assert no_api_report["selected"] == [], no_api_report
        assert no_api_report["integrated"] == [], no_api_report
        assert no_api_report["missing"] == [], no_api_report
        assert no_api_report["ok"] is True, no_api_report
        assert api_gate_failures(spec) == [], api_gate_failures(spec)

    print("ok feature-scoped API integration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
