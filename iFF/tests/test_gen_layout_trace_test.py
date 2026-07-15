from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_layout_trace_test.py"


class GenLayoutTraceTestTest(unittest.TestCase):
    def test_generated_trace_fails_on_unexpected_flutter_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "expected.json"
            expected.write_text(
                json.dumps(
                    {
                        "artboardWidth": 320,
                        "artboardHeight": 640,
                        "nodes": {"title": {"bbox": [0, 0, 100, 20]}},
                    }
                ),
                encoding="utf-8",
            )
            out = root / "trace_test.dart"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--expected",
                    str(expected),
                    "--page-import",
                    "package:app/page.dart",
                    "--page-type",
                    "Page",
                    "--trace-out",
                    str(root / "trace.json"),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            generated = out.read_text(encoding="utf-8")
            self.assertNotIn("while (tester.takeException() != null)", generated)
            self.assertIn("expect(tester.takeException(), isNull", generated)

    def test_generated_trace_records_structured_typography(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "expected.json"
            expected.write_text(
                json.dumps(
                    {
                        "artboardWidth": 320,
                        "artboardHeight": 640,
                        "nodes": {"title": {"bbox": [0, 0, 100, 20]}},
                    }
                ),
                encoding="utf-8",
            )
            out = root / "trace_test.dart"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--expected",
                    str(expected),
                    "--page-import",
                    "package:app/page.dart",
                    "--page-type",
                    "Page",
                    "--trace-out",
                    str(root / "trace.json"),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            generated = out.read_text(encoding="utf-8")
            for field in (
                "fontFamily",
                "fontStyle",
                "fontWeight",
                "letterSpacing",
                "lineHeight",
            ):
                self.assertIn(f"rec['{field}']", generated)


if __name__ == "__main__":
    unittest.main()
