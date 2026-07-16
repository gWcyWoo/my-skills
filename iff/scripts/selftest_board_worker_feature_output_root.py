#!/usr/bin/env python3
"""Public-CLI regression for one feature's deterministic board output root."""

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
    board_names = ("首页-首贷", "首页-等待中", "首页-审核拒绝")

    with tempfile.TemporaryDirectory(prefix="iff-board-feature-root-") as tmp_raw:
        tmp = Path(tmp_raw)
        project = tmp / "project"
        feature_spec_root = project / "lanhu" / "specs" / "home"
        expected_contract = (
            "`FEATURE_KEY=home`",
            "`CANVAS_DIR=lib/home/presentation`",
            "`OUT=lib/home/presentation/<SOURCE_NAME>_canvas.dart`",
            "--out lib/home/presentation/<SOURCE_NAME>_canvas.dart "
            "--colors-out lib/home/presentation/<SOURCE_NAME>_canvas_colors.dart "
            "--colors-import <SOURCE_NAME>_canvas_colors.dart --class-name <CLASS_NAME>",
            "Do NOT replace `CANVAS_DIR` with `lib/src/features` or any other architecture directory",
        )

        for index, board_name in enumerate(board_names):
            spec = feature_spec_root / board_name
            spec.mkdir(parents=True)
            row = tmp / f"row-{index}.json"
            prompt = tmp / f"prompt-{index}.txt"
            row.write_text(json.dumps({"title": board_name}, ensure_ascii=False), encoding="utf-8")

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
                return fail(
                    f"{board_name}: make_worker_prompt exited {result.returncode}: "
                    f"{result.stderr.strip()}"
                )

            generated = prompt.read_text(encoding="utf-8")
            missing = [item for item in expected_contract if item not in generated]
            if missing:
                return fail(f"{board_name}: missing deterministic feature output contract: {missing}")
            if "lib/<feature>/presentation" in generated:
                return fail(f"{board_name}: unresolved feature output placeholder remains")

    print("PASS three Unicode boards share one deterministic feature output root")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
