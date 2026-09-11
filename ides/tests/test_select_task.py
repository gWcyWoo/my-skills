import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "select_task.py"


class SelectTaskCliTest(unittest.TestCase):
    def test_selects_highest_priority_matching_status_and_returns_full_row(self) -> None:
        payload = {
            "rows": [
                {"row_number": 2, "values": {"状态": "ready", "优先级": "P2", "设计": "B"}},
                {"row_number": 3, "values": {"状态": "doing", "优先级": "P0", "设计": "C"}},
                {"row_number": 4, "values": {"状态": "ready", "优先级": "P0", "设计": "A"}},
            ]
        }
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--status",
                "ready",
                "--status-column",
                "状态",
                "--priority-column",
                "优先级",
                "--priority-order",
                "P0,P1,P2,P3",
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"row_number": 4, "values": {"状态": "ready", "优先级": "P0", "设计": "A"}},
        )

    def test_reports_when_no_row_matches_status(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--status",
                "ready",
                "--status-column",
                "状态",
                "--priority-column",
                "优先级",
                "--priority-order",
                "P0,P1",
            ],
            input=json.dumps({"rows": []}),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 3)
        self.assertEqual(
            json.loads(result.stderr),
            {"error": "no_matching_task", "status": "ready"},
        )

    def test_rejects_a_missing_mapped_column(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--status",
                "ready",
                "--status-column",
                "状态",
                "--priority-column",
                "优先级",
                "--priority-order",
                "P0,P1",
            ],
            input=json.dumps(
                {"rows": [{"row_number": 2, "values": {"状态": "ready"}}]}
            ),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 4)
        self.assertEqual(
            json.loads(result.stderr),
            {"error": "missing_columns", "columns": ["优先级"]},
        )


if __name__ == "__main__":
    unittest.main()
