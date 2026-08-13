#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    scripts = skill / "scripts"
    with tempfile.TemporaryDirectory(prefix="iff-feature-api-contract-") as raw_tmp:
        root = Path(raw_tmp)
        spec = root / "spec"
        spec.mkdir()
        oas = {
            "openapi": "3.0.0",
            "paths": {
                f"/project/endpoint/{index}": {
                    "get": {
                        "operationId": f"endpoint{index}",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object"}}
                                }
                            }
                        },
                    }
                }
                for index in range(46)
            },
        }
        row_api = "Load home summary and refresh offers"
        row = {"title": "home", "api": row_api}
        interaction = {"rules": [{"id": "INT-001"}, {"id": "INT-002"}]}
        selection = {
            "contractScope": "feature-selection",
            "apiRequired": True,
            "basis": {"rowApi": row_api, "interactionRuleIds": ["INT-001"]},
            "selectedEndpoints": [
                {"path": "/project/endpoint/7", "method": "GET"},
                {"path": "/project/endpoint/31", "method": "GET"},
            ],
        }
        oas_path = spec / "oas.json"
        row_path = spec / "row.json"
        interaction_path = spec / "interaction_contract.json"
        selection_path = spec / "api_endpoint_selection.json"
        project_contract = spec / "api_contract.json"
        feature_contract = spec / "feature_api_contract.json"
        write_json(oas_path, oas)
        write_json(row_path, row)
        write_json(interaction_path, interaction)
        write_json(selection_path, selection)

        normalized = subprocess.run(
            [
                sys.executable,
                str(scripts / "normalize_api_contract.py"),
                "--oas",
                str(oas_path),
                "--out",
                str(project_contract),
            ],
            text=True,
            capture_output=True,
        )
        assert normalized.returncode == 0, normalized.stdout + normalized.stderr
        full = json.loads(project_contract.read_text(encoding="utf-8"))
        assert full["contractScope"] == "project", full
        assert full["endpointCount"] == 46, full
        assert full["operationCount"] == 46, full

        scoped = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(selection_path),
                "--out",
                str(feature_contract),
            ],
            text=True,
            capture_output=True,
        )
        assert scoped.returncode == 0, scoped.stdout + scoped.stderr
        feature = json.loads(feature_contract.read_text(encoding="utf-8"))
        assert feature["contractScope"] == "feature", feature
        assert feature["projectEndpointCount"] == 46, feature
        assert feature["endpointCount"] == 2, feature
        assert feature["operationCount"] == 2, feature
        assert feature["selectedEndpoints"] == [
            {"path": "/project/endpoint/31", "method": "GET"},
            {"path": "/project/endpoint/7", "method": "GET"},
        ], feature

        no_api_row = spec / "no_api_row.json"
        no_api_interaction = spec / "no_api_interaction_contract.json"
        no_api_selection = spec / "no_api_selection.json"
        no_api_contract = spec / "no_api_feature_contract.json"
        write_json(no_api_row, {"title": "static-home", "api": ""})
        write_json(no_api_interaction, {"rules": []})
        write_json(
            no_api_selection,
            {
                "contractScope": "feature-selection",
                "apiRequired": False,
                "basis": {"rowApi": "", "interactionRuleIds": []},
                "selectedEndpoints": [],
            },
        )
        no_api_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(no_api_row),
                "--interaction-contract",
                str(no_api_interaction),
                "--selection",
                str(no_api_selection),
                "--out",
                str(no_api_contract),
            ],
            text=True,
            capture_output=True,
        )
        assert no_api_result.returncode == 0, no_api_result.stdout + no_api_result.stderr
        no_api_feature = json.loads(no_api_contract.read_text(encoding="utf-8"))
        assert no_api_feature["contractScope"] == "feature", no_api_feature
        assert no_api_feature["apiRequired"] is False, no_api_feature
        assert no_api_feature["endpointCount"] == 0, no_api_feature
        assert no_api_feature["operationCount"] == 0, no_api_feature
        assert no_api_feature["selectedEndpoints"] == [], no_api_feature

        inferred_selection = spec / "inferred_selection.json"
        write_json(
            inferred_selection,
            {
                "contractScope": "feature-selection",
                "apiRequired": True,
                "basis": {"rowApi": "", "interactionRuleIds": []},
                "selectedEndpoints": [{"path": "/project/endpoint/7", "method": "GET"}],
            },
        )
        inferred_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(no_api_row),
                "--interaction-contract",
                str(no_api_interaction),
                "--selection",
                str(inferred_selection),
                "--out",
                str(spec / "inferred_feature_contract.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert inferred_result.returncode != 0, inferred_result.stdout
        assert "API selection lacks a row api or interaction-rule basis" in inferred_result.stderr

        unknown = dict(selection)
        unknown["selectedEndpoints"] = [{"path": "/project/unknown", "method": "GET"}]
        unknown_path = spec / "unknown_selection.json"
        write_json(unknown_path, unknown)
        unknown_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(unknown_path),
                "--out",
                str(spec / "unknown_feature_contract.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert unknown_result.returncode != 0, unknown_result.stdout
        assert "unknown OAS operations" in unknown_result.stderr, unknown_result.stderr

        empty = dict(selection)
        empty["selectedEndpoints"] = []
        empty_path = spec / "empty_selection.json"
        write_json(empty_path, empty)
        empty_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(empty_path),
                "--out",
                str(spec / "empty_feature_contract.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert empty_result.returncode != 0, empty_result.stdout
        assert "API is required but selectedEndpoints is empty" in empty_result.stderr

        missing_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "scope_api_contract.py"),
                "--project-contract",
                str(project_contract),
                "--row-json",
                str(row_path),
                "--interaction-contract",
                str(interaction_path),
                "--selection",
                str(spec / "missing_selection.json"),
                "--out",
                str(spec / "missing_feature_contract.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert missing_result.returncode != 0, missing_result.stdout
        assert "endpoint selection missing" in missing_result.stderr

        prompt_path = spec / "contract_worker_prompt.md"
        prompt_result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--mode",
                "contract",
                "--row-json",
                str(row_path),
                "--spec-dir",
                str(spec),
                "--project-root",
                str(root),
                "--out",
                str(prompt_path),
            ],
            text=True,
            capture_output=True,
        )
        assert prompt_result.returncode == 0, prompt_result.stdout + prompt_result.stderr
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "scope_api_contract.py" in prompt, prompt
        assert "api_endpoint_selection.json" in prompt, prompt
        assert "--api-contract " in prompt and "feature_api_contract.json" in prompt, prompt
        assert "The project OAS summary is never feature endpoint evidence" in prompt, prompt
        assert "both evidence sources are empty" in prompt, prompt
        assert '"apiRequired":false' in prompt, prompt
        assert '"selectedEndpoints":[]' in prompt, prompt

    print("ok feature API contract scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
