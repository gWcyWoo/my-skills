from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_render_plan.py"


class MakeRenderPlanTest(unittest.TestCase):
    def test_typography_survives_scene_to_render_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scene = root / "scene.json"
            scene.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "root",
                                "type": "FRAME",
                                "bbox": [0, 0, 320, 640],
                                "parent": None,
                                "children": ["title"],
                            },
                            {
                                "id": "title",
                                "type": "TEXT",
                                "bbox": [20, 20, 200, 30],
                                "parent": "root",
                                "children": [],
                                "text": "Hello",
                                "fontFamily": "Inter",
                                "fontStyle": "italic",
                                "fontSize": 20,
                                "weight": 600,
                                "letterSpacing": {"value": 0.5},
                                "lineHeight": {"value": 30},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            assets = root / "assets.json"
            assets.write_text("{}", encoding="utf-8")
            layout = root / "layout.json"
            layout.write_text(
                json.dumps(
                    {"content": {"widgets": {"title": {"node": "title", "bbox": [20, 20, 200, 30]}}}}
                ),
                encoding="utf-8",
            )
            out = root / "render_plan.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--scene",
                    str(scene),
                    "--assets",
                    str(assets),
                    "--layout",
                    str(layout),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            title = json.loads(out.read_text(encoding="utf-8"))["nodes"]["title"]
            self.assertEqual("Inter", title["fontFamily"])
            self.assertEqual("italic", title["fontStyle"])


if __name__ == "__main__":
    unittest.main()
