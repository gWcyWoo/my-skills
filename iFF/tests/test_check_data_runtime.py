from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_runtime.py"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CheckDataRuntimeTest(unittest.TestCase):
    def test_mock_using_a_different_mapper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(project / "lib/loan_mapper.dart", "class LoanMapper {}\n")
            write(project / "lib/mock_loan_mapper.dart", "class MockLoanMapper {}\n")
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            write(
                project / "lib/real_loan_repository.dart",
                "import 'loan_repository.dart';\n"
                "import 'loan_dto.dart';\n"
                "import 'loan_mapper.dart';\n",
            )
            write(
                project / "lib/mock_loan_repository.dart",
                "import 'loan_repository.dart';\n"
                "import 'loan_dto.dart';\n"
                "import 'mock_loan_mapper.dart';\n",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "fetchLoan: mock does not use shared mapper",
                result.stdout + result.stderr,
            )

    def test_consumer_and_real_repository_must_be_reachable_from_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/main.dart", "void main() {}\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(
                project / "lib/loan_mapper.dart",
                "import 'loan_dto.dart';\nclass LoanMapper {}\n",
            )
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            shared_imports = (
                "import 'loan_repository.dart';\n"
                "import 'loan_dto.dart';\n"
                "import 'loan_mapper.dart';\n"
            )
            write(project / "lib/real_loan_repository.dart", shared_imports)
            write(project / "lib/mock_loan_repository.dart", shared_imports)
            write(
                project / "lib/loan_page.dart",
                "import 'real_loan_repository.dart';\nclass LoanPage {}\n",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "entry": "lib/main.dart",
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("fetchLoan: consumer unreachable from entry", result.stdout + result.stderr)
            self.assertIn(
                "fetchLoan: real repository unreachable from entry",
                result.stdout + result.stderr,
            )

    def test_mock_must_use_shared_repository_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(
                project / "lib/main.dart",
                "import 'loan_page.dart';\nvoid main() {}\n",
            )
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(
                project / "lib/loan_mapper.dart",
                "import 'loan_dto.dart';\nclass LoanMapper {}\n",
            )
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            write(
                project / "lib/real_loan_repository.dart",
                "import 'loan_repository.dart';\nimport 'loan_mapper.dart';\n",
            )
            write(
                project / "lib/mock_loan_repository.dart",
                "import 'loan_mapper.dart';\nclass UnrelatedMock {}\n",
            )
            write(
                project / "lib/loan_page.dart",
                "import 'real_loan_repository.dart';\nclass LoanPage {}\n",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "entry": "lib/main.dart",
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "fetchLoan: mock does not use shared repository interface",
                result.stdout + result.stderr,
            )

    def test_mock_must_use_shared_dto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/main.dart", "import 'loan_page.dart';\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(project / "lib/loan_mapper.dart", "class LoanMapper {}\n")
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            write(
                project / "lib/real_loan_repository.dart",
                "import 'loan_repository.dart';\n"
                "import 'loan_mapper.dart';\n"
                "import 'loan_dto.dart';\n",
            )
            write(
                project / "lib/mock_loan_repository.dart",
                "import 'loan_repository.dart';\nimport 'loan_mapper.dart';\n",
            )
            write(project / "lib/loan_page.dart", "import 'real_loan_repository.dart';\n")
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("fetchLoan: mock does not use shared DTO", result.stdout + result.stderr)

    def test_operation_method_must_exist_in_current_api_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/main.dart", "import 'loan_page.dart';\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(project / "lib/loan_mapper.dart", "import 'loan_dto.dart';\n")
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            shared = (
                "import 'loan_repository.dart';\n"
                "import 'loan_mapper.dart';\n"
                "import 'loan_dto.dart';\n"
            )
            write(project / "lib/real_loan_repository.dart", shared)
            write(project / "lib/mock_loan_repository.dart", shared)
            write(project / "lib/loan_page.dart", "import 'real_loan_repository.dart';\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loan": {"POST": {"responses": {"200": {"fields": {}}}}}
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "fetchLoan: GET /loan absent from current API contract",
                result.stdout + result.stderr,
            )

    def test_network_operation_requires_loading_success_and_error_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/main.dart", "import 'loan_page.dart';\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(project / "lib/loan_mapper.dart", "import 'loan_dto.dart';\n")
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            shared = (
                "import 'loan_repository.dart';\n"
                "import 'loan_mapper.dart';\n"
                "import 'loan_dto.dart';\n"
            )
            write(project / "lib/real_loan_repository.dart", shared)
            write(project / "lib/mock_loan_repository.dart", shared)
            write(project / "lib/loan_page.dart", "import 'real_loan_repository.dart';\n")
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                                "requiredStates": ["success"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "fetchLoan: missing required states: error, loading",
                result.stdout + result.stderr,
            )

    def test_array_response_requires_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            write(project / "lib/main.dart", "import 'loan_page.dart';\n")
            write(project / "lib/loan_dto.dart", "class LoanDto {}\n")
            write(project / "lib/loan_mapper.dart", "import 'loan_dto.dart';\n")
            write(project / "lib/loan_repository.dart", "abstract class LoanRepository {}\n")
            shared = (
                "import 'loan_repository.dart';\n"
                "import 'loan_mapper.dart';\n"
                "import 'loan_dto.dart';\n"
            )
            write(project / "lib/real_loan_repository.dart", shared)
            write(project / "lib/mock_loan_repository.dart", shared)
            write(project / "lib/loan_page.dart", "import 'real_loan_repository.dart';\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loans": {
                                "GET": {
                                    "responses": {
                                        "200": {
                                            "fields": {
                                                "$.items[].id": {
                                                    "type": "integer",
                                                    "format": None,
                                                    "required": True,
                                                    "nullable": False,
                                                    "enum": None,
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoans",
                                "endpoint": "/loans",
                                "method": "GET",
                                "interface": "lib/loan_repository.dart",
                                "real": "lib/real_loan_repository.dart",
                                "mock": "lib/mock_loan_repository.dart",
                                "dto": "lib/loan_dto.dart",
                                "mapper": "lib/loan_mapper.dart",
                                "consumer": "lib/loan_page.dart",
                                "requiredStates": ["loading", "success", "error"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("fetchLoans: array response requires empty state", result.stdout + result.stderr)

    def test_every_contract_operation_requires_one_runtime_manifest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loan": {
                                "GET": {"responses": {"200": {"fields": {}}}}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(json.dumps({"operations": []}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing runtime operation: GET /loan", result.stdout + result.stderr)

    def test_unbound_contract_operations_are_outside_feature_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loan": {"GET": {"responses": {"200": {"fields": {}}}}},
                            "/profile": {"GET": {"responses": {"200": {"fields": {}}}}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            bindings = project / "data_slot_bindings.json"
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(json.dumps({"operations": []}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_non_slot_runtime_operation_requires_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loan": {"GET": {"responses": {"200": {"fields": {}}}}}
                        }
                    }
                ),
                encoding="utf-8",
            )
            bindings = project / "data_slot_bindings.json"
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "requiredStates": ["loading", "success", "error"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "fetchLoan: non-slot operation requires model confirmation",
                result.stdout + result.stderr,
            )

    def test_feature_runtime_operation_requires_public_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            contract = project / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loan": {"GET": {"responses": {"200": {"fields": {}}}}}
                        }
                    }
                ),
                encoding="utf-8",
            )
            bindings = project / "data_slot_bindings.json"
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "binding": {
                                    "field": {"endpoint": "/loan", "method": "GET"}
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manifest = project / "data_runtime_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "",
                                "publicMethod": "",
                                "endpoint": "/loan",
                                "method": "GET",
                                "requiredStates": ["loading", "success", "error"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing runtime operation id", output)
            self.assertIn("missing runtime publicMethod", output)

    def test_runtime_operation_ids_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write(project / "pubspec.yaml", "name: sample_app\n")
            manifest = project / "data_runtime_manifest.json"
            operation = {
                "id": "fetch",
                "interface": "lib/repository.dart",
                "real": "lib/real.dart",
                "mock": "lib/mock.dart",
                "dto": "lib/dto.dart",
                "mapper": "lib/mapper.dart",
                "consumer": "lib/page.dart",
                "requiredStates": ["loading", "success", "error"],
            }
            manifest.write_text(
                json.dumps(
                    {
                        "operations": [
                            {**operation, "endpoint": "/a", "method": "GET"},
                            {**operation, "endpoint": "/b", "method": "GET"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--project-root",
                    str(project),
                    "--runtime-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("duplicate runtime operation id: fetch", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
