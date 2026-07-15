from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_interaction_device_tests.py"
CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_interaction_device_evidence.py"


class RunInteractionDeviceTestsTest(unittest.TestCase):
    def test_android_run_writes_current_case_level_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            lib = project / "lib"
            tests = project / "integration_test"
            lib.mkdir()
            tests.mkdir()
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY device', (tester) async {\n"
                "  app.main();\n"
                "  await tester.pumpAndSettle();\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:submit')));\n"
                "  expect(find.text('success'), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan = project / "interaction_test_plan.json"
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
            fake_flutter = project / "flutter"
            fake_flutter.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if len(sys.argv) > 1 and sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android','emulator':True}]))\n"
                "else:\n"
                "  print(json.dumps({'type':'testStart','test':{'id':1,'name':'INT-ABC-HAPPY device'}}))\n"
                "  print(json.dumps({'type':'testDone','testID':1,'result':'success','skipped':False}))\n",
                encoding="utf-8",
            )
            os.chmod(fake_flutter, 0o755)
            evidence = project / "interaction_device_evidence.json"

            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--flutter",
                    str(fake_flutter),
                    "--platform",
                    "android",
                    "--device",
                    "emulator-5554",
                    "--plan",
                    str(plan),
                    "--test-root",
                    str(tests),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            evidence_doc = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual("android", evidence_doc["deviceTargetPlatform"])
            checked = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--plan",
                    str(plan),
                    "--test-root",
                    str(tests),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
