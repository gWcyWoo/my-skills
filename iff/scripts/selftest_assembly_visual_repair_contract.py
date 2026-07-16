#!/usr/bin/env python3
"""Regression checks for the assembly worker's bounded visual-repair handoff."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="iff-assembly-visual-repair-") as raw_tmp:
        root = Path(raw_tmp)
        spec = root / "feature" / "board"
        spec.mkdir(parents=True)
        project = root / "project"
        project.mkdir()
        row = root / "row.json"
        prompt_path = root / "worker_prompt.md"
        row.write_text(json.dumps({"title": "Visual repair contract"}), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts" / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "assembly",
                "--row-json",
                str(row),
                "--spec-dir",
                str(spec.parent),
                "--project-root",
                str(project),
                "--out",
                str(prompt_path),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        prompt = prompt_path.read_text(encoding="utf-8")

    trace_before_green = "Before GREEN, generate every child board's online-page trace test"
    repair_phase = "Assembly visual-repair phase"
    assert trace_before_green in prompt, prompt
    assert prompt.index(trace_before_green) < prompt.index(repair_phase), prompt
    assert "--require-actual-trace" in prompt, prompt
    assert "hasActualTrace=false" in prompt, prompt
    assert "reads ONLY" in prompt and "repair_plan_top.json" in prompt, prompt
    budget_claim = "visual_repair_budget.py"
    assert budget_claim in prompt and "--prior-post-repair-diff" in prompt, prompt
    assert prompt.index(budget_claim) < prompt.index("reads ONLY"), prompt
    assert "v2 eligibility is false" in prompt, prompt
    assert "STOP before claim/edit" in prompt, prompt
    assert "--fresh-post-diff" in prompt, prompt
    assert "source-backed fingerprint/topAction" in prompt, prompt
    assert "at most 32 claims and 3 per source-bound fingerprint" in prompt, prompt
    assert "--repair-budget-state" in prompt, prompt
    assert "A fourth claim" in prompt and "threshold change" in prompt, prompt
    assert "apply its source-backed action once" in prompt, prompt
    assert "Scripts measure/gate and never auto-edit UI" in prompt, prompt
    assert "claim 33 FAILS" in prompt, prompt
    assert "return to step 4" in prompt, prompt
    print("PASS: assembly visual repair requires trace and bounds total/per-fingerprint claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
