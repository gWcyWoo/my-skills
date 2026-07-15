from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_evidence.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckDataEvidenceTest(unittest.TestCase):
    def test_non_browser_green_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "loan_data_test.dart"
            test_file.write_text("// current test\n", encoding="utf-8")
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
            cases = [
                "DATA-SLOT:amount-node",
                "DATA-REPO:fetchLoan",
                "DATA-STATE:fetchLoan:loading",
                "DATA-STATE:fetchLoan:success",
                "DATA-STATE:fetchLoan:error",
            ]
            hashes = {"loan_data_test.dart": sha256(test_file)}
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            "bindingsHash": sha256(bindings),
                            "runtimeManifestHash": sha256(runtime),
                            "testHashes": hashes,
                            "requiredCases": cases,
                            "cases": {
                                case: {"result": "failure", "skipped": False}
                                for case in cases
                            },
                        },
                        "green": {
                            "command": ["flutter", "test", "--machine", str(tests)],
                            "bindingsHash": sha256(bindings),
                            "runtimeManifestHash": sha256(runtime),
                            "testHashes": hashes,
                            "requiredCases": cases,
                            "cases": {
                                case: {"result": "success", "skipped": False}
                                for case in cases
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
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("green evidence did not run on chrome", result.stdout + result.stderr)

    def test_chrome_argument_with_vm_machine_platform_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "data_test.dart"
            test_file.write_text("// current test\n", encoding="utf-8")
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            phase = {
                "command": ["flutter", "test", "--device-id", "chrome", str(tests)],
                "actualPlatforms": ["vm"],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"data_test.dart": sha256(test_file)},
                "requiredCases": [],
                "cases": {},
            }
            evidence.write_text(
                json.dumps({"red": phase, "green": phase}), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("actual platform was not chrome", result.stdout + result.stderr)

    def test_browser_evidence_is_rejected_for_iff_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            browser_evidence = root / "data_browser_evidence.json"
            tests = root / "test"
            app = root / "lib"
            tests.mkdir()
            app.mkdir()
            test_file = tests / "data_test.dart"
            app_file = app / "main.dart"
            test_file.write_text("// DATA-SLOT:amount-node\n", encoding="utf-8")
            app_file.write_text("// current app\n", encoding="utf-8")
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
            case = "DATA-SLOT:amount-node"
            common = {
                "command": ["flutter", "test", "--machine", str(tests)],
                "actualPlatforms": ["vm"],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"data_test.dart": sha256(test_file)},
                "requiredCases": [case],
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **common,
                            "cases": {case: {"result": "failure", "skipped": False}},
                        },
                        "green": {
                            **common,
                            "cases": {case: {"result": "success", "skipped": False}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            browser_evidence.write_text(
                json.dumps(
                    {
                        "browser": "in-app-browser",
                        "url": "http://127.0.0.1:8756/",
                        "bindingsHash": sha256(bindings),
                        "runtimeManifestHash": sha256(runtime),
                        "appHashes": {"main.dart": sha256(app_file)},
                        "requiredCases": [case],
                        "fields": {case: {"jsonPath": "$.amount"}},
                        "cases": {
                            case: {
                                "result": "success",
                                "skipped": False,
                                "action": "load page with amount 10, then 20",
                                "inputValues": [10, 20],
                                "observed": ["₦10", "₦20"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--app-root",
                    str(app),
                    "--browser-evidence",
                    str(browser_evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("unsupported for iFF client", result.stdout + result.stderr)
            return

            browser_payload = json.loads(browser_evidence.read_text(encoding="utf-8"))
            browser_payload["cases"][case]["observed"] = ["₦10", "₦10"]
            browser_evidence.write_text(json.dumps(browser_payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--app-root",
                    str(app),
                    "--browser-evidence",
                    str(browser_evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("two distinct visible values", result.stdout + result.stderr)

            browser_payload["cases"][case]["observed"] = ["₦10", "₦20"]
            browser_payload["cases"][case]["inputValues"] = [10, 10]
            browser_evidence.write_text(json.dumps(browser_payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--app-root",
                    str(app),
                    "--browser-evidence",
                    str(browser_evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("two distinct input values", result.stdout + result.stderr)

    def test_stale_bindings_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            (tests / "data_test.dart").write_text("// test\n", encoding="utf-8")
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            evidence.write_text(
                json.dumps(
                    {
                        phase: {
                            "command": [
                                "flutter",
                                "test",
                                "--device-id",
                                "chrome",
                                str(tests),
                            ],
                            "bindingsHash": "old",
                            "runtimeManifestHash": sha256(runtime),
                            "testHashes": {"data_test.dart": sha256(tests / "data_test.dart")},
                            "requiredCases": [],
                            "cases": {},
                        }
                        for phase in ("red", "green")
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("stale bindings evidence", result.stdout + result.stderr)

    def test_missing_repository_and_state_cases_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "data_test.dart"
            test_file.write_text("// DATA-SLOT:amount-node\n", encoding="utf-8")
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
            incomplete = ["DATA-SLOT:amount-node"]
            current_test_hashes = {"data_test.dart": sha256(test_file)}
            evidence.write_text(
                json.dumps(
                    {
                        phase: {
                            "command": [
                                "flutter",
                                "test",
                                "--device-id",
                                "chrome",
                                str(tests),
                            ],
                            "bindingsHash": sha256(bindings),
                            "runtimeManifestHash": sha256(runtime),
                            "testHashes": current_test_hashes,
                            "requiredCases": incomplete,
                            "cases": {
                                "DATA-SLOT:amount-node": {
                                    "result": "failure" if phase == "red" else "success",
                                    "skipped": False,
                                }
                            },
                        }
                        for phase in ("red", "green")
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("required data cases differ", result.stdout + result.stderr)

    def test_green_required_case_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "data_test.dart"
            test_file.write_text("// DATA-SLOT:amount-node\n", encoding="utf-8")
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
            case = "DATA-SLOT:amount-node"
            common = {
                "command": ["flutter", "test", "--device-id", "chrome", str(tests)],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"data_test.dart": sha256(test_file)},
                "requiredCases": [case],
            }
            evidence.write_text(
                json.dumps(
                    {
                        "red": {
                            **common,
                            "cases": {case: {"result": "failure", "skipped": False}},
                        },
                        "green": {
                            **common,
                            "cases": {case: {"result": "failure", "skipped": False}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("green case not successful: DATA-SLOT:amount-node", result.stdout + result.stderr)

    def test_red_without_a_required_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "data_test.dart"
            test_file.write_text("// DATA-SLOT:amount-node\n", encoding="utf-8")
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
            case = "DATA-SLOT:amount-node"
            phase = {
                "command": ["flutter", "test", "--device-id", "chrome", str(tests)],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"data_test.dart": sha256(test_file)},
                "requiredCases": [case],
                "cases": {case: {"result": "success", "skipped": False}},
            }
            evidence.write_text(
                json.dumps({"red": phase, "green": phase}), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("red evidence has no required failure", result.stdout + result.stderr)

    def test_changed_test_file_makes_evidence_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            evidence = root / "data_test_evidence.json"
            tests = root / "test"
            tests.mkdir()
            test_file = tests / "data_test.dart"
            test_file.write_text("// changed\n", encoding="utf-8")
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            phase = {
                "command": ["flutter", "test", "--device-id", "chrome", str(tests)],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"data_test.dart": "old"},
                "requiredCases": [],
                "cases": {},
            }
            evidence.write_text(
                json.dumps({"red": phase, "green": phase}), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--evidence",
                    str(evidence),
                    "--require-device",
                    "chrome",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("stale test evidence", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
