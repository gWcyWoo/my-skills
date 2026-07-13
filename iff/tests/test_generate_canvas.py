from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_canvas.py"


class GenerateCanvasTest(unittest.TestCase):
    def test_text_uses_design_typography_and_records_expected_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "render_plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "root": {
                                "name": "Artboard",
                                "bbox": [0, 0, 320, 640],
                                "implementation": "shape_container",
                                "fills": ["#FFFFFF"],
                                "parent": None,
                            },
                            "title": {
                                "name": "Title",
                                "bbox": [20, 20, 200, 36],
                                "implementation": "text",
                                "fills": ["#111111"],
                                "parent": "root",
                                "text": "Hello",
                                "fontFamily": "Inter",
                                "fontStyle": "italic",
                                "fontSize": 20,
                                "weight": 600,
                                "letterSpacing": {"value": 0.5},
                                "lineHeight": {"value": 30},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            out = root / "canvas.dart"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--render-plan", str(plan), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            source = out.read_text(encoding="utf-8")
            self.assertIn("fontFamily: 'Inter'", source)
            self.assertIn("fontStyle: FontStyle.italic", source)
            self.assertIn("fontWeight: FontWeight.w600", source)
            self.assertIn("letterSpacing: 0.50 * u", source)
            self.assertIn("height: 1.5", source)
            expected = json.loads(
                Path(str(out) + ".expected.json").read_text(encoding="utf-8")
            )["nodes"]["title"]
            self.assertEqual("Inter", expected["fontFamily"])
            self.assertEqual("italic", expected["fontStyle"])
            self.assertEqual(600, expected["weight"])
            self.assertEqual(0.5, expected["letterSpacing"])
            self.assertEqual(1.5, expected["lineHeight"])

    def test_unknown_vector_fails_instead_of_emitting_transparent_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "render_plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "root": {
                                "name": "Artboard",
                                "bbox": [0, 0, 320, 640],
                                "implementation": "shape_container",
                                "fills": ["#FFFFFF"],
                                "parent": None,
                            },
                            "icon": {
                                "name": "Vector",
                                "bbox": [20, 20, 24, 24],
                                "implementation": "shape",
                                "fills": ["#000000"],
                                "parent": "root",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--render-plan",
                    str(plan),
                    "--out",
                    str(root / "canvas.dart"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unrenderable vector", result.stdout + result.stderr)
            self.assertFalse((root / "canvas.dart").exists())


if __name__ == "__main__":
    unittest.main()
