from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_interaction_device_evidence.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckInteractionDeviceEvidenceTest(unittest.TestCase):
    def test_host_platform_cannot_satisfy_client_interaction_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            test_root = project / "integration_test"
            lib = project / "lib"
            test_root.mkdir()
            lib.mkdir()
            plan = project / "interaction_test_plan.json"
            test_file = test_root / "feature_test.dart"
            main = lib / "main.dart"
            pubspec = project / "pubspec.yaml"
            plan.write_text(json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}), encoding="utf-8")
            test_file.write_text("// INT-ABC-HAPPY\n", encoding="utf-8")
            main.write_text("void main() {}\n", encoding="utf-8")
            pubspec.write_text("name: demo\n", encoding="utf-8")
            evidence = project / "interaction_device_evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "command": ["flutter", "test", "--machine", "-d", "macos", str(test_root)],
                        "deviceId": "macos",
                        "actualPlatforms": ["vm"],
                        "exitCode": 0,
                        "planHash": sha256(plan),
                        "testHashes": {"feature_test.dart": sha256(test_file)},
                        "appHashes": {"lib/main.dart": sha256(main)},
                        "runtimeInputHashes": {"pubspec.yaml": sha256(pubspec)},
                        "cases": {"INT-ABC-HAPPY": {"result": "success", "skipped": False}},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--plan",
                    str(plan),
                    "--test-root",
                    str(test_root),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("target client platform must be android or ios", result.stdout + result.stderr)

    def test_successful_device_case_without_public_action_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            test_root = project / "integration_test"
            lib = project / "lib"
            test_root.mkdir()
            lib.mkdir()
            plan = project / "interaction_test_plan.json"
            test_file = test_root / "feature_test.dart"
            main = lib / "main.dart"
            pubspec = project / "pubspec.yaml"
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-ABC-HAPPY",
                                "actionTarget": {"kind": "node", "key": "iff:submit"},
                                "expectedObservableTarget": {"kind": "text", "value": "success"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            test_file.write_text("// INT-ABC-HAPPY\n", encoding="utf-8")
            main.write_text("void main() {}\n", encoding="utf-8")
            pubspec.write_text("name: demo\n", encoding="utf-8")
            evidence = project / "interaction_device_evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "command": ["flutter", "test", "--machine", "-d", "emulator-5554", str(test_root)],
                        "deviceId": "emulator-5554",
                        "actualPlatforms": ["android"],
                        "exitCode": 0,
                        "planHash": sha256(plan),
                        "testHashes": {"feature_test.dart": sha256(test_file)},
                        "appHashes": {"lib/main.dart": sha256(main)},
                        "runtimeInputHashes": {"pubspec.yaml": sha256(pubspec)},
                        "cases": {"INT-ABC-HAPPY": {"result": "success", "skipped": False}},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--plan", str(plan), "--test-root", str(test_root), "--project-root", str(project), "--evidence", str(evidence)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("device case missing public action", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
