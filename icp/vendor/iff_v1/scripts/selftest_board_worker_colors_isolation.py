#!/usr/bin/env python3
"""Public-CLI regression for board-owned canvas color outputs."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-board-colors-") as raw_tmp:
        tmp = Path(raw_tmp)
        row = tmp / "row.json"
        spec = (tmp / "spec" / "synthetic-board").resolve()
        prompt = tmp / "worker" / "board_prompt.md"
        row.write_text(json.dumps({"title": "Synthetic board"}), encoding="utf-8")

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
                str(tmp / "project"),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        generated = prompt.read_text(encoding="utf-8")
        feature_key = spec.parent.name
        canvas = f"lib/{feature_key}/presentation/<SOURCE_NAME>_canvas.dart"
        colors = f"lib/{feature_key}/presentation/<SOURCE_NAME>_canvas_colors.dart"
        command_contract = (
            f"--out {canvas} --colors-out {colors} "
            "--colors-import <SOURCE_NAME>_canvas_colors.dart --class-name <CLASS_NAME>"
        )
        assert command_contract in generated, generated
        allowed_contract = (
            f"Allowed writes: {canvas}{{,.expected.json,.slots.json}}, {colors}"
        )
        assert allowed_contract in generated, generated
        assert "FORBIDDEN: page/selector/colors/fixture" not in generated, generated
        assert "app_colors.dart" not in generated, generated

    print("PASS: board-worker prompt owns an explicit per-canvas colors output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
