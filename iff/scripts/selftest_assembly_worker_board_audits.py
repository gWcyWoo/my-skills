#!/usr/bin/env python3
"""Public-CLI regression for assembly ownership of child-board audits."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-assembly-board-audits-") as raw_tmp:
        tmp = Path(raw_tmp)
        feature = (tmp / "specs" / "synthetic-feature").resolve()
        board_b = feature / "board-b"
        board_a = feature / "board-a"
        board_b.mkdir(parents=True)
        board_a.mkdir()
        project = (tmp / "project").resolve()
        row = tmp / "row.json"
        prompt = tmp / "worker" / "assembly_prompt.md"
        row.write_text(json.dumps({"title": "Synthetic feature"}), encoding="utf-8")

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
        assert result.returncode == 0, result.stderr or result.stdout
        generated = prompt.read_text(encoding="utf-8")

        prepare = (
            f"python3 {scripts / 'assembly_plan_batch.py'} prepare "
            f"--spec-root {feature} --project-root {project} "
            f"--context {feature / 'assembly_context.json'} "
            f"--decisions {feature / 'assembly_decisions.json'}"
        )
        assert generated.count(prepare) == 1, generated
        for board in (board_a, board_b):
            assert str(board / "implementation_plan.json") not in generated, generated
            assert f"--spec-dir {board}" not in generated, generated
        root_audit = (
            f"python3 {scripts / 'check_design_artifacts.py'} --spec-dir {feature}"
        )
        assert root_audit not in generated.splitlines(), generated
        assert f"--render-plan {feature / 'render_plan.json'}" not in generated, generated

    print("PASS: assembly prompt delegates stable child-board audits to one batch command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
