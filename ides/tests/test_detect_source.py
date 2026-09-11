import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "detect_source.py"


class DetectSourceCliTest(unittest.TestCase):
    def test_detects_google_sheets_url(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "https://docs.google.com/spreadsheets/d/sheet-123/edit#gid=42",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "provider": "google_sheets",
                "spreadsheet_id": "sheet-123",
                "gid": "42",
            },
        )

    def test_rejects_unsupported_url(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "https://alidocs.dingtalk.com/i/nodes/abc"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "error": "unsupported_source",
                "url": "https://alidocs.dingtalk.com/i/nodes/abc",
            },
        )


if __name__ == "__main__":
    unittest.main()
