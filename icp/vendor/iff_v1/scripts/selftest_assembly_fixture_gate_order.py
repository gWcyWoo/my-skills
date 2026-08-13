#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    scripts = skill / "scripts"

    with tempfile.TemporaryDirectory(prefix="iff-assembly-fixture-order-") as raw_tmp:
        tmp = Path(raw_tmp)
        feature = (tmp / "specs" / "synthetic-feature").resolve()
        (feature / "board-a").mkdir(parents=True)
        project = (tmp / "project").resolve()
        project.mkdir()
        row = tmp / "row.json"
        prompt = tmp / "assembly_prompt.md"
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
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode

        generated = prompt.read_text(encoding="utf-8")
        ordered_contract = [
            "Create the one shared visual fixture from all generated board slot files.",
            "Reference that fixture from the feature tests",
            "Reference that same fixture from a runtime/page path",
            f"python3 {scripts / 'check_fixture_source.py'} --root {project}",
        ]
        positions = [generated.find(item) for item in ordered_contract]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            print("ERROR: assembly prompt does not defer the same-source gate until runtime wiring")
            for item, position in zip(ordered_contract, positions):
                print(f"{position}: {item}")
            return 1

    print("PASS: assembly prompt wires test and runtime fixture sources before the strict gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
