#!/usr/bin/env python3
"""Verify compact assembly judgments are applied to every large board plan."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-assembly-plan-batch-") as raw_tmp:
        root = Path(raw_tmp)
        feature = (root / "specs" / "feature").resolve()
        project = (root / "project").resolve()
        project.mkdir(parents=True)
        boards = []
        for name in ("board-a", "board-b"):
            board = feature / name
            board.mkdir(parents=True)
            write_json(board / "design_classification.json", {"states": []})
            write_json(board / "render_plan.json", {"nodes": {}})
            write_json(board / "layout_contract.json", {})
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "prefill_implementation_plan.py"),
                    "--spec-dir",
                    str(board),
                    "--project-root",
                    str(project),
                ],
                text=True,
                capture_output=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            boards.append({
                "board": name,
                "specDir": str(board),
                "artifactDigest": str(board / "artifact_digest.json"),
                "implementationPlan": str(board / "implementation_plan.json"),
                "states": [],
                "regions": [],
            })

        context = feature / "assembly_context.json"
        decisions = feature / "assembly_decisions.json"
        write_json(context, {
            "schemaVersion": 1,
            "preparedBy": "assembly_plan_batch.py",
            "specRoot": str(feature),
            "projectRoot": str(project),
            "boards": boards,
            "deterministicRegionRationale": (
                "Use the board-generated absolute canvas; merge or skip no required visible node."
            ),
        })
        write_json(decisions, {
            "schemaVersion": 1,
            "specRoot": str(feature),
            "projectAlignment": {
                "entrypoint": "lib/main.dart",
                "appShell": "App",
                "existingFeatureDirs": [],
                "missingFeatureDirs": ["lib/feature"],
                "fanoutOwnedFiles": ["lib/feature/**"],
                "faninRequests": [],
            },
            "fixtureSource": "lib/feature/data/feature_visual_fixture.dart",
            "stateDataByBoard": {"board-a": [], "board-b": []},
        })
        applied = subprocess.run(
            [
                sys.executable,
                str(scripts / "assembly_plan_batch.py"),
                "apply",
                "--context",
                str(context),
                "--decisions",
                str(decisions),
            ],
            text=True,
            capture_output=True,
        )
        assert applied.returncode == 0, applied.stdout + applied.stderr
        for board in boards:
            text = Path(board["implementationPlan"]).read_text(encoding="utf-8")
            assert "__MODEL__" not in text, text
            assert "lib/feature/data/feature_visual_fixture.dart" in text, text

    print("PASS: one compact decision file fills and validates every board plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
