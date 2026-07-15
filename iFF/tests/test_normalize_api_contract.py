from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "normalize_api_contract.py"


class NormalizeApiContractTest(unittest.TestCase):
    def test_created_array_response_exposes_traceable_nested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/loans": {
                                "post": {
                                    "operationId": "createLoan",
                                    "responses": {
                                        "201": {
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "object",
                                                        "required": ["data"],
                                                        "properties": {
                                                            "data": {
                                                                "type": "array",
                                                                "items": {
                                                                    "$ref": "#/components/schemas/Loan"
                                                                },
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    },
                                }
                            }
                        },
                        "components": {
                            "schemas": {
                                "Loan": {
                                    "type": "object",
                                    "required": ["amount"],
                                    "properties": {
                                        "amount": {"type": "number", "format": "double"}
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            contract = json.loads(out.read_text(encoding="utf-8"))
            operation = contract["endpoints"]["/loans"]["POST"]
            fields = operation["responses"]["201"]["fields"]
            self.assertEqual(
                {
                    "type": "number",
                    "format": "double",
                    "required": True,
                    "nullable": False,
                    "enum": None,
                },
                fields["$.data[].amount"],
            )

    def test_unresolved_response_reference_fails_visibly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/loans": {
                                "get": {
                                    "responses": {
                                        "200": {
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "$ref": "#/components/schemas/MissingLoan"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "components": {"schemas": {}},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("unresolved $ref", result.stdout + result.stderr)
            self.assertFalse(out.exists())

    def test_operation_preserves_path_parameter_and_json_request_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/loans/{id}": {
                                "post": {
                                    "parameters": [
                                        {
                                            "name": "id",
                                            "in": "path",
                                            "required": True,
                                            "schema": {"type": "string", "format": "uuid"},
                                        }
                                    ],
                                    "requestBody": {
                                        "required": True,
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "object",
                                                    "required": ["amount"],
                                                    "properties": {
                                                        "amount": {"type": "integer"}
                                                    },
                                                }
                                            }
                                        },
                                    },
                                    "responses": {"204": {"description": "created"}},
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            operation = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loans/{id}"
            ]["POST"]
            self.assertEqual(
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "type": "string",
                    "format": "uuid",
                },
                operation["parameters"][0],
            )
            self.assertEqual(True, operation["requestBody"]["required"])
            self.assertEqual("application/json", operation["requestBody"]["mediaType"])
            self.assertEqual(
                "integer", operation["requestBody"]["fields"]["$.amount"]["type"]
            )

    def test_all_of_response_exposes_fields_from_every_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
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
                                                        "allOf": [
                                                            {
                                                                "$ref": "#/components/schemas/BaseLoan"
                                                            },
                                                            {
                                                                "type": "object",
                                                                "properties": {
                                                                    "status": {
                                                                        "type": "string"
                                                                    }
                                                                },
                                                            },
                                                        ]
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "components": {
                            "schemas": {
                                "BaseLoan": {
                                    "type": "object",
                                    "properties": {"id": {"type": "integer"}},
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            fields = json.loads(out.read_text(encoding="utf-8"))["endpoints"]["/loan"][
                "GET"
            ]["responses"]["200"]["fields"]
            self.assertEqual({"$.id", "$.status"}, set(fields))

    def test_contract_records_the_exact_oas_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/health": {
                                "get": {"responses": {"204": {"description": "ok"}}}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            contract = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                hashlib.sha256(oas.read_bytes()).hexdigest(),
                contract["sourceFingerprint"]["sha256"],
            )
            self.assertEqual("3.0.3", contract["sourceFingerprint"]["openapi"])

    def test_one_of_response_preserves_each_schema_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
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
                                                        "oneOf": [
                                                            {
                                                                "type": "object",
                                                                "properties": {
                                                                    "amount": {"type": "number"}
                                                                },
                                                            },
                                                            {
                                                                "type": "object",
                                                                "properties": {
                                                                    "reason": {"type": "string"}
                                                                },
                                                            },
                                                        ]
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            response = json.loads(out.read_text(encoding="utf-8"))["endpoints"]["/loan"][
                "GET"
            ]["responses"]["200"]
            self.assertEqual("oneOf", response["schemaKind"])
            self.assertEqual(2, len(response["variants"]))
            self.assertIn("$.amount", response["variants"][0]["fields"])
            self.assertIn("$.reason", response["variants"][1]["fields"])

    def test_operation_inherits_path_level_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/loans/{id}": {
                                "parameters": [
                                    {
                                        "name": "id",
                                        "in": "path",
                                        "required": True,
                                        "schema": {"type": "string"},
                                    }
                                ],
                                "get": {"responses": {"204": {"description": "ok"}}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            parameters = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loans/{id}"
            ]["GET"]["parameters"]
            self.assertEqual("id", parameters[0]["name"])
            self.assertTrue(parameters[0]["required"])

    def test_vendor_json_response_media_type_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/loan": {
                                "get": {
                                    "responses": {
                                        "200": {
                                            "content": {
                                                "application/vnd.loan+json": {
                                                    "schema": {
                                                        "type": "object",
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
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            response = json.loads(out.read_text(encoding="utf-8"))["endpoints"]["/loan"][
                "GET"
            ]["responses"]["200"]
            self.assertEqual("application/vnd.loan+json", response["mediaType"])
            self.assertIn("$.amount", response["fields"])

    def test_openapi_31_null_union_is_normalized_to_nullable_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "get": {
                                    "responses": {
                                        "200": {
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "object",
                                                        "properties": {
                                                            "reason": {
                                                                "type": ["string", "null"]
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            field = json.loads(out.read_text(encoding="utf-8"))["endpoints"]["/loan"][
                "GET"
            ]["responses"]["200"]["fields"]["$.reason"]
            self.assertEqual("string", field["type"])
            self.assertTrue(field["nullable"])

    def test_required_leaf_under_optional_parent_is_not_path_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
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
                                                        "properties": {
                                                            "data": {
                                                                "type": "object",
                                                                "required": ["amount"],
                                                                "properties": {
                                                                    "amount": {"type": "number"}
                                                                },
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            field = json.loads(out.read_text(encoding="utf-8"))["endpoints"]["/loan"][
                "GET"
            ]["responses"]["200"]["fields"]["$.data.amount"]
            self.assertFalse(field["required"])

    def test_local_response_reference_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "get": {
                                    "responses": {
                                        "200": {
                                            "$ref": "#/components/responses/LoanResponse"
                                        }
                                    }
                                }
                            }
                        },
                        "components": {
                            "responses": {
                                "LoanResponse": {
                                    "description": "ok",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "amount": {"type": "number"}
                                                },
                                            }
                                        }
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            response = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loan"
            ]["GET"]["responses"]["200"]
            self.assertEqual("number", response["fields"]["$.amount"]["type"])

    def test_local_request_body_reference_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "post": {
                                    "requestBody": {
                                        "$ref": "#/components/requestBodies/CreateLoan"
                                    },
                                    "responses": {"204": {"description": "created"}},
                                }
                            }
                        },
                        "components": {
                            "requestBodies": {
                                "CreateLoan": {
                                    "required": True,
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "amount": {"type": "number"}
                                                },
                                            }
                                        }
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            request = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loan"
            ]["POST"]["requestBody"]
            self.assertTrue(request["required"])
            self.assertEqual("number", request["fields"]["$.amount"]["type"])

    def test_local_parameter_reference_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan/{id}": {
                                "get": {
                                    "parameters": [
                                        {"$ref": "#/components/parameters/LoanId"}
                                    ],
                                    "responses": {"204": {"description": "ok"}},
                                }
                            }
                        },
                        "components": {
                            "parameters": {
                                "LoanId": {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string", "format": "uuid"},
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            parameter = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loan/{id}"
            ]["GET"]["parameters"][0]
            self.assertEqual("id", parameter["name"])
            self.assertEqual("uuid", parameter["format"])

    def test_local_path_item_reference_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "$ref": "#/components/pathItems/LoanOperations"
                            }
                        },
                        "components": {
                            "pathItems": {
                                "LoanOperations": {
                                    "get": {
                                        "responses": {"204": {"description": "ok"}}
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            operations = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loan"
            ]
            self.assertEqual({"GET"}, set(operations))

    def test_path_item_extensions_are_not_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "get": {
                                    "responses": {"204": {"description": "ok"}}
                                },
                                "x-client-metadata": {"cache": True},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            operations = json.loads(out.read_text(encoding="utf-8"))["endpoints"][
                "/loan"
            ]
            self.assertEqual({"GET"}, set(operations))

    def test_check_rejects_contract_content_changed_after_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oas = root / "oas.json"
            out = root / "api_contract.json"
            oas.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {
                            "/loan": {
                                "get": {
                                    "responses": {
                                        "200": {
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "object",
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
                    }
                ),
                encoding="utf-8",
            )
            created = subprocess.run(
                [sys.executable, str(SCRIPT), "--oas", str(oas), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, created.returncode, created.stdout + created.stderr)
            contract = json.loads(out.read_text(encoding="utf-8"))
            contract["endpoints"]["/loan"]["GET"]["responses"]["200"]["fields"][
                "$.amount"
            ]["type"] = "string"
            out.write_text(json.dumps(contract), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--oas",
                    str(oas),
                    "--out",
                    str(out),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not canonical", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
