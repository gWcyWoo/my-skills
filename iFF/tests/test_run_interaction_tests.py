from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.scripts.run_interaction_tests import parse_machine_events


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_interaction_tests.py"


def write_fake_flutter(path: Path, test_name: str, result: str, exit_code: int) -> None:
    events = [
        {
            "type": "testStart",
            "test": {"id": 1, "name": test_name, "url": "test/feature_test.dart"},
        },
        {
            "type": "testDone",
            "testID": 1,
            "result": result,
            "skipped": False,
            "hidden": False,
        },
        {"type": "done", "success": exit_code == 0},
    ]
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o755)


class RunInteractionTestsTest(unittest.TestCase):
    def test_machine_parser_ignores_non_object_json_lines(self) -> None:
        stdout = "[]\n" + json.dumps(
            {
                "type": "testStart",
                "test": {"id": 1, "name": "INT-ABC-HAPPY", "url": "test.dart"},
            }
        )

        self.assertEqual({}, parse_machine_events(stdout, ["INT-ABC-HAPPY"]))

    def test_red_rejects_nonzero_exit_when_no_planned_case_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "feature_test.dart").write_text("// INT-ABC-HAPPY\n", encoding="utf-8")
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            write_fake_flutter(flutter, "unrelated test", "failure", 1)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--flutter",
                    str(flutter),
                    "--plan",
                    str(plan),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("no planned case failed", result.stdout)

    def test_valid_red_records_planned_failure_and_current_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text("// INT-ABC-HAPPY\n", encoding="utf-8")
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            write_fake_flutter(flutter, "INT-ABC-HAPPY submits", "failure", 1)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--flutter",
                    str(flutter),
                    "--plan",
                    str(plan),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            red = json.loads(evidence.read_text(encoding="utf-8"))["red"]
            self.assertEqual("failure", red["cases"]["INT-ABC-HAPPY"]["result"])
            self.assertIn("planHash", red)
            self.assertIn("feature_test.dart", red["testHashes"])

    def test_green_accepts_same_planned_case_passing_after_valid_red(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "feature_test.dart").write_text(
                "// INT-ABC-HAPPY\n", encoding="utf-8"
            )
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            base_command = [
                sys.executable,
                str(SCRIPT),
                "--flutter",
                str(flutter),
                "--plan",
                str(plan),
                "--test-root",
                str(tests),
                "--evidence",
                str(evidence),
            ]
            write_fake_flutter(flutter, "INT-ABC-HAPPY submits", "failure", 1)
            red = subprocess.run(
                [*base_command, "--phase", "red"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, red.returncode, red.stdout + red.stderr)
            write_fake_flutter(flutter, "INT-ABC-HAPPY submits", "success", 0)

            green = subprocess.run(
                [*base_command, "--phase", "green"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, green.returncode, green.stdout + green.stderr)
            evidence_doc = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(
                "success",
                evidence_doc["green"]["cases"]["INT-ABC-HAPPY"]["result"],
            )


if __name__ == "__main__":
    unittest.main()
