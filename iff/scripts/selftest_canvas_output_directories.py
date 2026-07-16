#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    scripts = Path(__file__).resolve().parent
    fixture = scripts.parent / "evolution" / "regression" / "0002_backonly"

    with tempfile.TemporaryDirectory(prefix="iff-canvas-output-directories-") as raw_tmp:
        tmp = Path(raw_tmp)
        out = tmp / "project" / "lib" / "shared" / "widgets" / "shared_header.dart"
        colors_out = tmp / "project" / "lib" / "theme" / "generated" / "shared_header_colors.dart"
        assert not out.parent.exists()
        assert not colors_out.parent.exists()

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "generate_canvas.py"),
                "--render-plan",
                str(fixture / "render_plan.json"),
                "--classification",
                str(fixture / "classification.json"),
                "--out",
                str(out),
                "--colors-out",
                str(colors_out),
                "--colors-import",
                "shared_header_colors.dart",
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        outputs = [
            out,
            colors_out,
            Path(f"{out}.expected.json"),
            Path(f"{out}.slots.json"),
        ]
        assert all(path.is_file() for path in outputs), outputs

    print("PASS: generate_canvas public CLI creates every declared output parent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
