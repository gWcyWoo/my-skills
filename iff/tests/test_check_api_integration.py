from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_api_integration.py"


class CheckApiIntegrationTest(unittest.TestCase):
    def test_commented_client_call_does_not_count_as_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            lib.mkdir()
            (lib / "loan_repository.dart").write_text(
                "// client.get('/loan');\nclass LoanRepository {}\n",
                encoding="utf-8",
            )
            contract = root / "api_contract.json"
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

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-contract",
                    str(contract),
                    "--lib-root",
                    str(lib),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("GET /loan", result.stdout + result.stderr)

    def test_path_parameter_matches_interpolated_real_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            lib.mkdir()
            (lib / "loan_repository.dart").write_text(
                "Future<void> fetch(String id) => client.get('/loans/$id');\n",
                encoding="utf-8",
            )
            contract = root / "api_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "endpoints": {
                            "/loans/{id}": {
                                "GET": {"responses": {"200": {"fields": {}}}}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-contract",
                    str(contract),
                    "--lib-root",
                    str(lib),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_call_in_unrelated_file_cannot_cover_declared_real_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            lib.mkdir()
            (lib / "real_loan_repository.dart").write_text(
                "class RealLoanRepository {}\n", encoding="utf-8"
            )
            (lib / "unused_client.dart").write_text(
                "Future<void> fetch() => client.get('/loan');\n", encoding="utf-8"
            )
            contract = root / "api_contract.json"
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
            runtime = root / "data_runtime_manifest.json"
            runtime.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "real": "lib/real_loan_repository.dart",
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
                    "--api-contract",
                    str(contract),
                    "--lib-root",
                    str(lib),
                    "--runtime-manifest",
                    str(runtime),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("GET /loan", result.stdout + result.stderr)

    def test_runtime_manifest_limits_check_to_feature_operation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            lib.mkdir()
            (lib / "real_loan_repository.dart").write_text(
                "Future<void> fetch() => client.get('/loan');\n", encoding="utf-8"
            )
            contract = root / "api_contract.json"
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
            runtime = root / "data_runtime_manifest.json"
            runtime.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "endpoint": "/loan",
                                "method": "GET",
                                "real": "lib/real_loan_repository.dart",
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
                    "--api-contract",
                    str(contract),
                    "--lib-root",
                    str(lib),
                    "--runtime-manifest",
                    str(runtime),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("all 1 operation(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
