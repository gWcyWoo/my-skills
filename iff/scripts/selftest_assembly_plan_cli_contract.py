#!/usr/bin/env python3
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    scripts = skill / "scripts"
    batch = (scripts / "assembly_plan_batch.py").resolve()

    with tempfile.TemporaryDirectory(prefix="iff-assembly-plan-cli-") as raw_tmp:
        tmp = Path(raw_tmp)
        feature = (tmp / "specs" / "home").resolve()
        board = feature / "首页-审核拒绝 状态"
        board.mkdir(parents=True)
        row = tmp / "row.json"
        prompt = tmp / "assembly_prompt.md"
        row.write_text(json.dumps({"title": "Home"}), encoding="utf-8")

        generated_result = subprocess.run(
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
                str(tmp / "project"),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        if generated_result.returncode != 0:
            print(generated_result.stdout, end="")
            print(generated_result.stderr, end="", file=sys.stderr)
            return generated_result.returncode

        generated = prompt.read_text(encoding="utf-8")
        command_lines = [line for line in generated.splitlines() if str(batch) in line]
        failures = []
        if len(command_lines) != 2 or any("Run: " not in line for line in command_lines):
            failures.append(f"expected prepare/apply batch commands, got: {command_lines}")
        else:
            actual = [shlex.split(line.split("Run: ", 1)[1]) for line in command_lines]
            context = feature / "assembly_context.json"
            decisions = feature / "assembly_decisions.json"
            expected = [
                [
                    "python3",
                    str(batch),
                    "prepare",
                    "--spec-root",
                    str(feature),
                    "--project-root",
                    str((tmp / "project").resolve()),
                    "--context",
                    str(context),
                    "--decisions",
                    str(decisions),
                ],
                [
                    "python3",
                    str(batch),
                    "apply",
                    "--context",
                    str(context),
                    "--decisions",
                    str(decisions),
                ],
            ]
            if actual != expected:
                failures.append(f"ambiguous batch plan argv: expected={expected}, actual={actual}")

        if str(board / "implementation_plan.json") in generated:
            failures.append("prompt still exposes a child implementation_plan.json for manual patching")

        invalid = subprocess.run(
            [
                sys.executable,
                str(batch),
                "apply",
                "--context",
                str(feature / "missing-context.json"),
                "--decisions",
                str(feature / "missing-decisions.json"),
            ],
            text=True,
            capture_output=True,
        )
        invalid_output = invalid.stdout + invalid.stderr
        if invalid.returncode == 0:
            failures.append("batch apply accepted missing context/decisions")
        if "ERROR:" not in invalid_output:
            failures.append(f"batch apply did not fail visibly: {invalid_output!r}")
        if "Traceback" in invalid_output:
            failures.append(f"batch apply leaked a traceback: {invalid_output!r}")

        if failures:
            for failure in failures:
                print(f"ERROR: {failure}")
            return 1

    print("PASS: assembly uses exact batch plan commands and rejects invalid inputs visibly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
