from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from check_interaction_coverage import evidence_ok


SCRIPT = SCRIPTS_DIR / "check_interaction_coverage.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckInteractionCoverageTest(unittest.TestCase):
    def test_evidence_command_must_be_flutter_test_machine(self) -> None:
        errors = evidence_ok(
            {
                "red": {"exitCode": 1, "command": ["python", "fake.py"]},
                "green": {"exitCode": 0, "command": ["python", "fake.py"]},
            }
        )

        self.assertIn("red evidence command must be flutter test --machine", errors)
        self.assertIn("green evidence command must be flutter test --machine", errors)

    def test_evidence_fails_after_test_plan_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {
                                "INT-ABC-HAPPY": {
                                    "result": "failure",
                                    "skipped": False,
                                }
                            },
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {
                                "INT-ABC-HAPPY": {
                                    "result": "success",
                                    "skipped": False,
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {"id": "INT-ABC-HAPPY"},
                            {"id": "INT-ABC-BOUNDARY"},
                        ]
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("stale planHash", result.stderr + result.stdout)

    def test_case_id_in_comment_or_unit_test_does_not_count_as_widget_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "// INT-ABC-HAPPY\ntest('domain logic only', () {});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {
                                "INT-ABC-HAPPY": {
                                    "result": "failure",
                                    "skipped": False,
                                }
                            },
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {
                                "INT-ABC-HAPPY": {
                                    "result": "success",
                                    "skipped": False,
                                }
                            },
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("not declared in testWidgets", result.stderr + result.stdout)

    def test_widget_test_without_public_ui_action_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY renders', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  expect(find.byType(Placeholder), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing public WidgetTester action", result.stderr + result.stdout)

    def test_widget_test_must_mount_a_runtime_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:submit')));\n"
                "  expect(1, 1);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing tester.pumpWidget runtime surface", result.stderr + result.stdout)

    def test_widget_action_without_observable_assertion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byType(Placeholder));\n"
                "  await tester.pump();\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing observable assertion", result.stderr + result.stdout)

    def test_widget_action_must_use_the_planned_node_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:other')));\n"
                "  expect(find.text('success'), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-ABC-HAPPY",
                                "actionTarget": {
                                    "kind": "node",
                                    "board": "form",
                                    "key": "iff:submit",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing planned actionTarget key iff:submit", result.stderr + result.stdout)

    def test_planned_key_in_assertion_cannot_cover_an_action_on_another_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:other')));\n"
                "  expect(find.byKey(const ValueKey('iff:submit')), findsOneWidget);\n"
                "  expect(find.text('success'), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-ABC-HAPPY",
                                "actionTarget": {
                                    "kind": "node",
                                    "feature": "loan",
                                    "board": "form",
                                    "key": "iff:submit",
                                },
                                "expectedObservableTarget": {
                                    "kind": "text",
                                    "feature": "loan",
                                    "board": "success",
                                    "value": "success",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("action does not use planned target iff:submit", result.stderr + result.stdout)

    def test_unrelated_assertion_cannot_cover_the_planned_observable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:submit')));\n"
                "  expect(find.text('unrelated'), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-ABC-HAPPY",
                                "actionTarget": {"kind": "node", "key": "iff:submit"},
                                "expectedObservableTarget": {
                                    "kind": "text",
                                    "feature": "loan",
                                    "board": "success",
                                    "value": "success",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("assertion does not verify planned observable", result.stderr + result.stdout)

    def test_system_back_case_requires_page_back_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "interaction_test_plan.json"
            evidence = root / "interaction_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-BACK-HAPPY back', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byType(Placeholder));\n"
                "  expect(find.text('closed'), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-BACK-HAPPY",
                                "actionTarget": {"kind": "system", "gesture": "back"},
                                "expectedObservableTarget": {
                                    "kind": "text",
                                    "value": "closed",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-BACK-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-BACK-HAPPY": {"result": "success"}},
                        },
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
                    str(tests),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing planned system gesture back", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
