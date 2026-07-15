from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_feature_tests.py"


def write_fake_flutter(path: Path, counter: Path, cases: list[str], result: str, exit_code: int) -> None:
    events = [[], {"type": "suite", "suite": {"id": 0, "platform": "chrome"}}]
    for index, case in enumerate(cases, start=1):
        events.append({"type": "testStart", "test": {"id": index, "name": case}})
        events.append(
            {
                "type": "testDone",
                "testID": index,
                "result": result,
                "skipped": False,
            }
        )
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "from pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "counter.write_text(str(int(counter.read_text() or '0') + 1))\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o755)


class RunFeatureTestsTest(unittest.TestCase):
    def test_one_red_flutter_run_records_interaction_and_data_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            counter = root / "counter"
            counter.write_text("0", encoding="utf-8")
            interaction_plan = root / "interaction_test_plan.json"
            interaction_evidence = root / "interaction_test_evidence.json"
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            data_evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "feature_test.dart").write_text("// cases\n", encoding="utf-8")
            interaction_plan.write_text(
                json.dumps({"cases": [{"id": "INT-1-HAPPY"}]}), encoding="utf-8"
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
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            write_fake_flutter(
                flutter,
                counter,
                ["INT-1-HAPPY user flow", "DATA-SLOT:amount-node changes text"],
                "failure",
                1,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--phase",
                    "red",
                    "--flutter",
                    str(flutter),
                    "--device",
                    "chrome",
                    "--interaction-plan",
                    str(interaction_plan),
                    "--interaction-evidence",
                    str(interaction_evidence),
                    "--data-bindings",
                    str(bindings),
                    "--data-runtime-manifest",
                    str(runtime),
                    "--data-evidence",
                    str(data_evidence),
                    "--test-root",
                    str(tests),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("1", counter.read_text(encoding="utf-8"))
            interaction_red = json.loads(interaction_evidence.read_text(encoding="utf-8"))["red"]
            data_red = json.loads(data_evidence.read_text(encoding="utf-8"))["red"]
            self.assertEqual("failure", interaction_red["cases"]["INT-1-HAPPY"]["result"])
            self.assertEqual(
                "failure", data_red["cases"]["DATA-SLOT:amount-node"]["result"]
            )
            self.assertEqual(["chrome"], data_red["actualPlatforms"])

    def test_one_green_flutter_run_completes_both_current_red_evidences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flutter = root / "flutter"
            counter = root / "counter"
            counter.write_text("0", encoding="utf-8")
            plan = root / "interaction_test_plan.json"
            interaction_evidence = root / "interaction_test_evidence.json"
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            data_evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "feature_test.dart").write_text("// cases\n", encoding="utf-8")
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-1-HAPPY"}]}), encoding="utf-8"
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
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPT),
                "--flutter",
                str(flutter),
                "--device",
                "chrome",
                "--interaction-plan",
                str(plan),
                "--interaction-evidence",
                str(interaction_evidence),
                "--data-bindings",
                str(bindings),
                "--data-runtime-manifest",
                str(runtime),
                "--data-evidence",
                str(data_evidence),
                "--test-root",
                str(tests),
            ]
            case_names = ["INT-1-HAPPY flow", "DATA-SLOT:amount-node changes text"]
            write_fake_flutter(flutter, counter, case_names, "failure", 1)
            red = subprocess.run(
                [*command, "--phase", "red"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, red.returncode, red.stdout + red.stderr)
            write_fake_flutter(flutter, counter, case_names, "success", 0)

            green = subprocess.run(
                [*command, "--phase", "green"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, green.returncode, green.stdout + green.stderr)
            self.assertEqual("2", counter.read_text(encoding="utf-8"))
            interaction_green = json.loads(
                interaction_evidence.read_text(encoding="utf-8")
            )["green"]
            data_green = json.loads(data_evidence.read_text(encoding="utf-8"))["green"]
            self.assertEqual("success", interaction_green["cases"]["INT-1-HAPPY"]["result"])
            self.assertEqual(
                "success", data_green["cases"]["DATA-SLOT:amount-node"]["result"]
            )
            self.assertEqual(["chrome"], data_green["actualPlatforms"])


if __name__ == "__main__":
    unittest.main()
