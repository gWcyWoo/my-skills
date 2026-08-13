from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_feature.py"
MAKE_DEVICE = Path(__file__).resolve().parents[1] / "scripts" / "make_data_device_evidence.py"
NORMALIZE_API = Path(__file__).resolve().parents[1] / "scripts" / "normalize_api_contract.py"
RUN_DEVICE = Path(__file__).resolve().parents[1] / "scripts" / "run_data_device_tests.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class CheckDataFeatureTest(unittest.TestCase):
    def test_stale_oas_contract_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            evidence = spec / "data_test_evidence.json"
            write_json(oas, {"openapi": "3.0.3", "paths": {}})
            write_json(
                contract,
                {
                    "sourceFingerprint": {"sha256": "old"},
                    "endpoints": {},
                },
            )
            write_json(manifest, {"components": []})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [],
                },
            )
            write_json(runtime, {"operations": []})
            write_json(
                evidence,
                {
                    phase: {
                        "command": ["flutter", "test", "--device-id", "chrome"],
                        "bindingsHash": sha256(bindings),
                        "runtimeManifestHash": sha256(runtime),
                        "testHashes": {},
                        "requiredCases": [],
                        "cases": {},
                    }
                    for phase in ("red", "green")
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("api_contract.json stale against oas.json", result.stdout + result.stderr)

    def test_noncanonical_contract_with_current_oas_hash_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            runtime = spec / "data_runtime_manifest.json"
            write_json(oas, {"openapi": "3.0.3", "paths": {}})
            write_json(
                contract,
                {
                    "sourceFingerprint": {"sha256": sha256(oas)},
                    "endpoints": {"/invented": {"GET": {"responses": {}}}},
                },
            )
            write_json(runtime, {"operations": []})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not canonical", result.stdout + result.stderr)

    def test_missing_dynamic_binding_is_recomputed_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            evidence = spec / "data_test_evidence.json"
            write_json(oas, {"openapi": "3.0.3", "paths": {}})
            write_json(
                contract,
                {
                    "sourceFingerprint": {"sha256": sha256(oas)},
                    "endpoints": {},
                },
            )
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
            )
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [],
                },
            )
            write_json(runtime, {"operations": []})
            write_json(evidence, {})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing binding: amount-node", result.stdout + result.stderr)

    def test_empty_data_test_evidence_is_rejected_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / "test").mkdir(parents=True)
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            evidence = spec / "data_test_evidence.json"
            write_json(oas, {"openapi": "3.0.3", "paths": {}})
            write_json(
                contract,
                {
                    "sourceFingerprint": {"sha256": sha256(oas)},
                    "endpoints": {},
                },
            )
            write_json(manifest, {"components": []})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [],
                },
            )
            write_json(runtime, {"operations": []})
            write_json(evidence, {})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("required data cases differ: green", result.stdout + result.stderr)

    def test_required_live_api_verification_cannot_be_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            runtime = spec / "data_runtime_manifest.json"
            write_json(runtime, {"operations": []})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--require-live-api",
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("live API verification required but missing", result.stdout + result.stderr)

    def test_hand_written_live_report_cannot_set_live_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            runtime = spec / "data_runtime_manifest.json"
            live = spec / "live_api_report.json"
            write_json(oas, {"openapi": "3.0.3", "paths": {}})
            normalized = subprocess.run(
                [sys.executable, str(NORMALIZE_API), "--oas", str(oas), "--out", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, normalized.returncode, normalized.stdout + normalized.stderr)
            write_json(runtime, {"operations": []})
            write_json(
                live,
                {
                    "ok": True,
                    "apiContractHash": sha256(contract),
                    "runtimeManifestHash": sha256(runtime),
                    "checkedOperations": [],
                },
            )
            report = spec / "data_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--live-api-report",
                    str(live),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("must be generated by run_live_api_tests.py", result.stdout + result.stderr)
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["liveApiVerified"])

    def test_feature_gate_recomputes_public_data_behavior_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / "test").mkdir(parents=True)
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            write_json(
                oas,
                {
                    "openapi": "3.0.3",
                    "paths": {
                        "/loan": {
                            "get": {
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "object",
                                                    "required": ["amount"],
                                                    "properties": {"amount": {"type": "number"}},
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                },
            )
            normalized = subprocess.run(
                [sys.executable, str(NORMALIZE_API), "--oas", str(oas), "--out", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, normalized.returncode, normalized.stdout + normalized.stderr)
            write_json(manifest, {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [
                        {
                            "node": "amount-node",
                            "binding": {
                                "field": {
                                    "endpoint": "/loan",
                                    "method": "GET",
                                    "status": "200",
                                    "jsonPath": "$.amount",
                                    "type": "number",
                                    "format": None,
                                    "required": True,
                                    "nullable": False,
                                    "enum": None,
                                },
                                "transform": "formatNaira",
                            },
                            "confirmedByModel": True,
                        }
                    ],
                },
            )
            write_json(runtime, {"operations": []})
            write_json(spec / "data_test_evidence.json", {})
            write_text(
                project / "test/loan_data_test.dart",
                "testWidgets('DATA-SLOT:amount-node', (tester) async { expect(true, true); });",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("DATA-SLOT:amount-node: missing public runtime surface", result.stdout + result.stderr)

    def test_feature_gate_does_not_require_unbound_project_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / "test").mkdir(parents=True)
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            write_json(
                oas,
                {
                    "openapi": "3.0.3",
                    "paths": {
                        "/profile": {
                            "get": {"responses": {"200": {"description": "ok"}}}
                        }
                    },
                },
            )
            normalized = subprocess.run(
                [sys.executable, str(NORMALIZE_API), "--oas", str(oas), "--out", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, normalized.returncode, normalized.stdout + normalized.stderr)
            write_json(manifest, {"components": []})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [],
                },
            )
            write_json(runtime, {"operations": []})
            write_json(spec / "data_test_evidence.json", {})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(spec / "data_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("missing runtime operation: GET /profile", result.stdout + result.stderr)

    def test_current_data_chain_rejects_hand_written_client_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            oas = spec / "oas.json"
            contract = spec / "api_contract.json"
            manifest = spec / "component_manifest.json"
            bindings = spec / "data_slot_bindings.json"
            runtime = spec / "data_runtime_manifest.json"
            evidence = spec / "data_test_evidence.json"
            report = spec / "data_gate_report.json"
            slots = spec / "success.slots.json"
            write_json(
                oas,
                {
                    "openapi": "3.0.3",
                    "paths": {
                        "/loan": {
                            "get": {
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "object",
                                                    "required": ["amount"],
                                                    "properties": {
                                                        "amount": {"type": "number"}
                                                    },
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                },
            )
            field_spec = {
                "type": "number",
                "format": None,
                "required": True,
                "nullable": False,
                "enum": None,
            }
            normalized = subprocess.run(
                [
                    sys.executable,
                    str(NORMALIZE_API),
                    "--oas",
                    str(oas),
                    "--out",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, normalized.returncode, normalized.stdout + normalized.stderr)
            write_json(
                manifest,
                {
                    "components": [
                        {"dynamicSlots": [{"node": "amount-node", "text": "₦10"}]}
                    ]
                },
            )
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                **field_spec,
            }
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [
                        {
                            "node": "amount-node",
                            "binding": {
                                "field": field,
                                "transform": "formatNaira",
                                "confidence": "high",
                            },
                            "confirmedByModel": True,
                        }
                    ],
                },
            )
            write_json(
                runtime,
                {
                    "entry": "lib/main.dart",
                    "operations": [
                        {
                            "id": "fetchLoan",
                            "endpoint": "/loan",
                            "method": "GET",
                            "publicMethod": "fetchLoan",
                            "interface": "lib/loan_repository.dart",
                            "real": "lib/real_loan_repository.dart",
                            "mock": "lib/mock_loan_repository.dart",
                            "dto": "lib/loan_dto.dart",
                            "mapper": "lib/loan_mapper.dart",
                            "consumer": "lib/loan_page.dart",
                            "requiredStates": ["loading", "success", "error"],
                            "stateTargets": {
                                state: {
                                    "key": f"iff:loan-{state}",
                                    "text": f"Loan {state}",
                                }
                                for state in ("loading", "success", "error")
                            },
                        }
                    ],
                },
            )
            write_text(project / "pubspec.yaml", "name: sample_app\n")
            write_text(project / "lib/main.dart", "import 'loan_page.dart';\n")
            write_text(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write_text(
                project / "lib/loan_mapper.dart",
                "import 'loan_dto.dart';\nclass LoanMapper {}\n",
            )
            write_text(
                project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n"
            )
            shared = (
                "import 'loan_repository.dart';\n"
                "import 'loan_mapper.dart';\n"
                "import 'loan_dto.dart';\n"
            )
            write_text(
                project / "lib/real_loan_repository.dart",
                shared + "Future<void> fetch() => client.get('/loan');\n",
            )
            write_text(project / "lib/mock_loan_repository.dart", shared)
            fixture = project / "lib/loan_visual_fixture.dart"
            write_text(
                fixture,
                "abstract final class LoanVisualFixture { static const states = {}; }\n",
            )
            write_text(
                project / "lib/loan_page.dart",
                "import 'real_loan_repository.dart';\n"
                "import 'loan_visual_fixture.dart';\n"
                "final states = LoanVisualFixture.states;\n",
            )
            write_json(slots, {"amount-node": "₦10"})
            write_json(
                Path(str(fixture) + ".source.json"),
                {
                    "fixtureSha256": sha256(fixture),
                    "states": {
                        "success": {
                            "path": str(slots),
                            "sha256": sha256(slots),
                            "slotCount": 1,
                        }
                    }
                },
            )
            test_file = project / "test/loan_data_test.dart"
            write_text(
                test_file,
                "import '../lib/loan_visual_fixture.dart';\n"
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " final fixtureStates = LoanVisualFixture.states;"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 20}));"
                " expect(find.text('₦20'), findsOneWidget);"
                "});\n"
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " server.listen((request) {"
                "  expect(request.method, 'GET');"
                "  expect(request.uri.path, '/loan');"
                "  request.response.statusCode = 200;"
                "  expect(request.response.statusCode, 200);"
                "  request.response.write('{\"amount\":10}');"
                "  request.response.close();"
                " });"
                " final result = await repository.fetchLoan();"
                " expect(result.amount, 10);"
                " await server.close();"
                "});\n"
                + "\n".join(
                    "testWidgets('DATA-STATE:fetchLoan:{state}', (tester) async {{"
                    " await tester.pumpWidget(const LoanApp());"
                    " expect(find.byKey(const ValueKey('iff:loan-{state}')), findsOneWidget);"
                    " expect(find.text('Loan {state}'), findsOneWidget);"
                    "}});".format(state=state)
                    for state in ("loading", "success", "error")
                )
                + "\n",
            )
            cases = [
                "DATA-SLOT:amount-node",
                "DATA-REPO:fetchLoan",
                "DATA-STATE:fetchLoan:loading",
                "DATA-STATE:fetchLoan:success",
                "DATA-STATE:fetchLoan:error",
            ]
            common = {
                "command": ["flutter", "test", "--device-id", "chrome", "test"],
                "bindingsHash": sha256(bindings),
                "runtimeManifestHash": sha256(runtime),
                "testHashes": {"loan_data_test.dart": sha256(test_file)},
                "requiredCases": cases,
            }
            write_json(
                evidence,
                {
                    "red": {
                        **common,
                        "cases": {
                            case: {
                                "result": "failure" if index == 0 else "success",
                                "skipped": False,
                            }
                            for index, case in enumerate(cases)
                        },
                    },
                    "green": {
                        **common,
                        "cases": {
                            case: {"result": "success", "skipped": False}
                            for case in cases
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("data_device_evidence.json", result.stdout + result.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["liveApiVerified"])

            integration = project / "integration_test/data_test.dart"
            device_source = (
                "testWidgets('DATA-SLOT:amount-node device', (tester) async {"
                " final binding = IntegrationTestWidgetsFlutterBinding.instance;"
                " app.main();"
                " await binding.convertFlutterSurfaceToImage();"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                " final firstPng = await binding.takeScreenshot('DATA-SLOT:amount-node:1');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|1|${base64Encode(firstPng)}');"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 20}));"
                " expect(find.text('₦20'), findsOneWidget);"
                " final secondPng = await binding.takeScreenshot('DATA-SLOT:amount-node:2');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|2|${base64Encode(secondPng)}');"
                "});\n"
                + "\n".join(
                    "testWidgets('DATA-STATE:fetchLoan:{state} device', (tester) async {{"
                    " final binding = IntegrationTestWidgetsFlutterBinding.instance;"
                    " app.main();"
                    " await binding.convertFlutterSurfaceToImage();"
                    " expect(find.byKey(const ValueKey('iff:loan-{state}')), findsOneWidget);"
                    " expect(find.text('Loan {state}'), findsOneWidget);"
                    " final png = await binding.takeScreenshot('DATA-STATE:fetchLoan:{state}:1');"
                    " print('IFF_DATA_CAPTURE|DATA-STATE:fetchLoan:{state}|1|${{base64Encode(png)}}');"
                    "}});".format(state=state)
                    for state in ("loading", "success", "error")
                )
                + "\n"
            )
            write_text(integration, device_source)
            device_cases = [
                "DATA-SLOT:amount-node",
                "DATA-STATE:fetchLoan:loading",
                "DATA-STATE:fetchLoan:success",
                "DATA-STATE:fetchLoan:error",
            ]
            pngs = [
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC",
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC",
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4/58BAAT/Af9dfQKHAAAAAElFTkSuQmCC",
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+P8fAAMBAf+2EqLVAAAAAElFTkSuQmCC",
            ]
            markers = {
                device_cases[0]: [
                    f"IFF_DATA_CAPTURE|{device_cases[0]}|1|{pngs[0]}",
                    f"IFF_DATA_CAPTURE|{device_cases[0]}|2|{pngs[1]}",
                ],
                **{
                    case: [f"IFF_DATA_CAPTURE|{case}|1|{pngs[index + 2]}"]
                    for index, case in enumerate(device_cases[1:])
                },
            }
            fake_flutter = project / "flutter"
            write_text(
                fake_flutter,
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"cases = {device_cases!r}\n"
                f"markers = {markers!r}\n"
                "if len(sys.argv) > 1 and sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android'}]))\n"
                "else:\n"
                "  for index, case in enumerate(cases, 1):\n"
                "    print(json.dumps({'type':'testStart','test':{'id':index,'name':case + ' device'}}))\n"
                "    for marker in markers[case]: print(marker)\n"
                "    print(json.dumps({'type':'testDone','testID':index,'result':'success','skipped':False}))\n",
            )
            os.chmod(fake_flutter, 0o755)
            automated = subprocess.run(
                [
                    sys.executable,
                    str(RUN_DEVICE),
                    "--flutter",
                    str(fake_flutter),
                    "--platform",
                    "android",
                    "--device",
                    "emulator-5554",
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(integration.parent),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(spec / "data_device_evidence.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, automated.returncode, automated.stdout + automated.stderr)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            device_cases = [case for case in cases if not case.startswith("DATA-REPO:")]
            first_image = spec / "amount-10.png"
            second_image = spec / "amount-20.png"
            first_capture = spec / "amount-10.manifest.json"
            second_capture = spec / "amount-20.manifest.json"
            write_text(first_image, "client pixels 10")
            write_text(second_image, "client pixels 20")
            for capture_path, image_path in (
                (first_capture, first_image),
                (second_capture, second_image),
            ):
                write_json(
                    capture_path,
                    {
                        "actual_source": "simulator_screenshot",
                        "device_id": "emulator-5554",
                        "project_root": str(project.resolve()),
                        "app_hashes": {
                            str(path.relative_to(project / "lib")): sha256(path)
                            for path in sorted((project / "lib").rglob("*.dart"))
                        },
                        "launch_command": [
                            "flutter",
                            "run",
                            "-d",
                            "emulator-5554",
                            "--debug",
                            "--no-resident",
                        ],
                        "capture_command": (
                            "adb -s emulator-5554 shell screencap -p "
                            "/sdcard/iff_actual.png"
                        ),
                        "actual_path": str(image_path),
                    },
                )
            observations = spec / "data_device_observations.json"
            write_json(
                observations,
                {
                    "platform": "android",
                    "deviceId": "emulator-5554",
                    "cases": {
                        case: {
                            "result": "success",
                            "skipped": False,
                            "action": "exercise public page data surface",
                            **(
                                {"inputValues": [10, 20]}
                                if case.startswith("DATA-SLOT:")
                                else {}
                            ),
                            "observed": (
                                ["₦10", "₦20"]
                                if case.startswith("DATA-SLOT:")
                                else ["visible state"]
                            ),
                            "captureManifests": (
                                [str(first_capture), str(second_capture)]
                                if case.startswith("DATA-SLOT:")
                                else [str(second_capture)]
                            ),
                        }
                        for case in device_cases
                    },
                },
            )
            made = subprocess.run(
                [
                    sys.executable,
                    str(MAKE_DEVICE),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--app-root",
                    str(project / "lib"),
                    "--observations",
                    str(observations),
                    "--out",
                    str(spec / "data_device_evidence.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, made.returncode, made.stdout + made.stderr)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(runtime),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "must be generated by run_data_device_tests.py",
                result.stdout + result.stderr,
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["liveApiVerified"])


if __name__ == "__main__":
    unittest.main()
