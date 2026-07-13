from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_data_tests.py"


def write_fake_flutter(path: Path, test_name: str, result: str, exit_code: int) -> None:
    events = [
        {"type": "testStart", "test": {"id": 1, "name": test_name}},
        {
            "type": "testDone",
            "testID": 1,
            "result": result,
            "skipped": False,
        },
        {"type": "done", "success": exit_code == 0},
    ]
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o755)


class RunDataTestsTest(unittest.TestCase):
    def test_red_records_failure_for_each_bound_slot_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            bindings = root / "data_slot_bindings.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "loan_data_test.dart").write_text(
                "// DATA-SLOT:amount-node\n", encoding="utf-8"
            )
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "amount-node",
                                "binding": {"field": {"jsonPath": "$.amount"}},
                            },
                            {"node": "title-node", "staticReason": "fixed title"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            write_fake_flutter(flutter, "DATA-SLOT:amount-node changes visible text", "failure", 1)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--flutter",
                    str(flutter),
                    "--bindings",
                    str(bindings),
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
            self.assertEqual(
                "failure", red["cases"]["DATA-SLOT:amount-node"]["result"]
            )
            self.assertEqual(["DATA-SLOT:amount-node"], red["requiredCases"])

    def test_green_accepts_same_bound_slot_test_after_recorded_red(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            bindings = root / "data_slot_bindings.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "loan_data_test.dart").write_text(
                "// DATA-SLOT:amount-node\n", encoding="utf-8"
            )
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "amount-node",
                                "binding": {"field": {"jsonPath": "$.amount"}},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(SCRIPT),
                "--flutter",
                str(flutter),
                "--bindings",
                str(bindings),
                "--test-root",
                str(tests),
                "--evidence",
                str(evidence),
            ]
            write_fake_flutter(
                flutter, "DATA-SLOT:amount-node changes visible text", "failure", 1
            )
            red = subprocess.run(
                [*command, "--phase", "red"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, red.returncode, red.stdout + red.stderr)
            write_fake_flutter(
                flutter, "DATA-SLOT:amount-node changes visible text", "success", 0
            )

            green = subprocess.run(
                [*command, "--phase", "green"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, green.returncode, green.stdout + green.stderr)
            recorded = json.loads(evidence.read_text(encoding="utf-8"))["green"]
            self.assertEqual(
                "success", recorded["cases"]["DATA-SLOT:amount-node"]["result"]
            )

    def test_red_derives_repository_and_required_state_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "loan_data_test.dart").write_text(
                "// DATA-REPO:fetchLoan\n", encoding="utf-8"
            )
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "requiredStates": ["loading", "success", "error"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            write_fake_flutter(flutter, "DATA-REPO:fetchLoan calls public interface", "failure", 1)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--flutter",
                    str(flutter),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
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
            required = json.loads(evidence.read_text(encoding="utf-8"))["red"][
                "requiredCases"
            ]
            self.assertEqual(
                [
                    "DATA-REPO:fetchLoan",
                    "DATA-STATE:fetchLoan:loading",
                    "DATA-STATE:fetchLoan:success",
                    "DATA-STATE:fetchLoan:error",
                ],
                required,
            )

    def test_red_records_requested_browser_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            bindings = root / "data_slot_bindings.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "loan_data_test.dart").write_text(
                "// DATA-SLOT:amount-node\n", encoding="utf-8"
            )
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "amount-node",
                                "binding": {"field": {"jsonPath": "$.amount"}},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            write_fake_flutter(flutter, "DATA-SLOT:amount-node browser", "failure", 1)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--device",
                    "chrome",
                    "--flutter",
                    str(flutter),
                    "--bindings",
                    str(bindings),
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
            command = json.loads(evidence.read_text(encoding="utf-8"))["red"]["command"]
            self.assertIn("--device-id", command)
            self.assertIn("chrome", command)


if __name__ == "__main__":
    unittest.main()
