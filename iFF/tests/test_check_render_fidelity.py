from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_render_fidelity.py"


class CheckRenderFidelityTest(unittest.TestCase):
    def test_missing_observed_style_values_fail_instead_of_skipping_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "expected.json"
            expected.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "title": {
                                "bbox": [0, 0, 100, 20],
                                "text": "Hello",
                                "fontSize": 20,
                                "colorHex": "#111111",
                                "radius": 8,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            trace = root / "trace.json"
            trace.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "title": {
                                "present": True,
                                "bbox": [0, 0, 100, 20],
                                "text": "Hello",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--trace",
                    str(trace),
                    "--expected",
                    str(expected),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            categories = {
                failure["category"]
                for failure in json.loads(report.read_text(encoding="utf-8"))["failures"]
            }
            self.assertEqual({"fontSize", "color", "radius"}, categories)

    def test_typography_mismatch_fails_structured_fidelity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "expected.json"
            expected.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "title": {
                                "bbox": [0, 0, 100, 20],
                                "text": "Hello",
                                "fontSize": 20,
                                "fontFamily": "Inter",
                                "fontStyle": "italic",
                                "weight": 600,
                                "letterSpacing": 0.5,
                                "lineHeight": 1.5,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            trace = root / "trace.json"
            trace.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "title": {
                                "present": True,
                                "bbox": [0, 0, 100, 20],
                                "text": "Hello",
                                "fontSize": 20,
                                "fontFamily": "Roboto",
                                "fontStyle": "normal",
                                "fontWeight": 400,
                                "letterSpacing": 0,
                                "lineHeight": 1.0,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--trace",
                    str(trace),
                    "--expected",
                    str(expected),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            categories = {
                failure["category"]
                for failure in json.loads(report.read_text(encoding="utf-8"))["failures"]
            }
            self.assertEqual(
                {"fontFamily", "fontStyle", "fontWeight", "letterSpacing", "lineHeight"},
                categories,
            )


if __name__ == "__main__":
    unittest.main()
