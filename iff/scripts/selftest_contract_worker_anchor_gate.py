#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-contract-anchor-gate-") as raw_tmp:
        tmp = Path(raw_tmp)
        row = tmp / "row.json"
        spec = (tmp / "spec").resolve()
        project = (tmp / "project").resolve()
        prompt = tmp / "worker" / "prompt.md"
        row.write_text(
            json.dumps({"title": "Synthetic feature", "interaction": "tap to continue"}),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "contract",
                "--row-json",
                str(row),
                "--spec-dir",
                str(spec),
                "--project-root",
                str(project),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        generated = prompt.read_text(encoding="utf-8")
        anchor_command = (
            f"python3 {scripts / 'resolve_interaction_anchors.py'} "
            f"--contract {spec / 'interaction_contract.json'} "
            f"--index {project / '.iff' / 'board_index.json'} "
            f"--out {spec / 'interaction_anchors.json'}"
        )
        assert anchor_command in generated, {
            "missing": "anchor generation command",
            "expected": anchor_command,
        }
        assert f"{anchor_command} --check" in generated, {
            "missing": "anchor validation command",
            "expected": f"{anchor_command} --check",
        }
        artifact_gate = (
            f"python3 {scripts / 'check_contract_artifacts.py'} "
            f"--spec-dir {spec} --index {project / '.iff' / 'board_index.json'}"
        )
        assert artifact_gate in generated, {
            "missing": "nonzero contract artifact gate",
            "expected": artifact_gate,
        }

    print("PASS: contract-worker prompt generates and gates interaction anchors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
