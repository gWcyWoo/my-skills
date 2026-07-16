#!/usr/bin/env python3
"""Regression: assembly packaging must be post-RED and pre-GREEN."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    scripts = skill / "scripts"
    with tempfile.TemporaryDirectory(prefix="iff-assembly-packaging-order-") as raw_tmp:
        tmp = Path(raw_tmp)
        feature = tmp / "specs" / "home"
        (feature / "board-a").mkdir(parents=True)
        project = tmp / "project"
        project.mkdir()
        row = tmp / "row.json"
        prompt = tmp / "assembly_prompt.md"
        row.write_text(json.dumps({"title": "Home"}), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "assembly",
                "--row-json",
                str(row),
                "--spec-dir",
                str(feature),
                "--project-root",
                str(project),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        generated = prompt.read_text(encoding="utf-8")
        ordered_contract = [
            f"python3 {scripts / 'assembly_tdd_guard.py'} red",
            f"python3 {scripts / 'prepare_assembly_packaging.py'} prepare",
            "Reference that same fixture from a runtime/page path before GREEN.",
            f"python3 {scripts / 'assembly_tdd_guard.py'} green",
        ]
        positions = [generated.find(item) for item in ordered_contract]
        assert all(position >= 0 for position in positions), positions
        assert positions == sorted(positions), positions
        assert "assembly_packaging.json" in generated
        assert "must not run flutter test" in generated
        assert "Do not invoke `flutter test` directly" in generated
        assert "--failure-kind missing_feature_behavior\n```" in generated
        assert "--failure-kind missing_feature_behavior ." not in generated

    print("PASS: assembly prompt orders deterministic packaging after RED and before GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
