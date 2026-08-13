#!/usr/bin/env python3
"""Public-CLI regression: colorless canvases emit no unused color artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff_canvas_empty_colors_") as td:
        root = Path(td)
        render_plan = root / "render_plan.json"
        out = root / "nested" / "widget.dart"
        colors_out = root / "nested" / "empty_colors.dart"
        render_plan.write_text(
            json.dumps(
                {
                    "nodes": {
                        "asset": {
                            "name": "Asset only",
                            "parent": None,
                            "bbox": [0, 0, 72, 72],
                            "visible": True,
                            "required": True,
                            "implementation": "image_png",
                            "asset": "asset_only.png",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "generate_canvas.py"),
                "--render-plan",
                str(render_plan),
                "--artboard-width",
                "72",
                "--artboard-height",
                "72",
                "--out",
                str(out),
                "--colors-out",
                str(colors_out),
                "--colors-import",
                colors_out.name,
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        widget = out.read_text(encoding="utf-8")
        assert f"import '{colors_out.name}';" not in widget, widget
        assert not colors_out.exists(), colors_out.read_text(encoding="utf-8")

    print("PASS: colorless canvas omits the colors import and colors file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
