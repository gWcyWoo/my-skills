#!/usr/bin/env python3
"""Public-CLI regression for board canvas generation ordering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> int:
    print(f"FAIL {message}", file=sys.stderr)
    return 1


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-board-canvas-order-") as tmp_raw:
        tmp = Path(tmp_raw)
        project = tmp / "project"
        spec = project / "lanhu" / "specs" / "home" / "首页-首贷"
        spec.mkdir(parents=True)
        future_canvas = project / "lib" / "home" / "presentation" / "first_loan_canvas.dart"
        if future_canvas.exists():
            return fail("fixture canvas must not exist before prompt generation")

        row = tmp / "row.json"
        prompt = tmp / "board_prompt.txt"
        row.write_text(json.dumps({"title": "首页-首贷"}, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "board",
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
        if result.returncode != 0:
            return fail(f"make_worker_prompt exited {result.returncode}: {result.stderr.strip()}")

        generated = prompt.read_text(encoding="utf-8")
        required = (
            "Freeze `SOURCE_NAME` before any canvas output path is accessed",
            "`CLASS_NAME` = PascalCase(`SOURCE_NAME`) + `Canvas`",
            "--class-name <CLASS_NAME>",
            "Do NOT read, grep, rg, cat, stat, or test existence of `OUT` before generate_canvas.py",
            "Only after generate_canvas.py exits 0 may you read or grep `OUT`",
        )
        missing = [item for item in required if item not in generated]
        if missing:
            return fail(f"board prompt lacks future-output contract: {missing}")

    print("PASS board worker freezes canvas identity before touching future output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
