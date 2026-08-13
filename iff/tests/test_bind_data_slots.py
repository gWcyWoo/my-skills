from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bind_data_slots.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class BindDataSlotsTest(unittest.TestCase):
    def test_same_named_fields_from_two_operations_remain_distinct_and_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "name": "LoanCard",
                            "variantIndex": 0,
                            "dynamicSlots": [{"node": "amount-node", "text": "₦10,000"}],
                        }
                    ]
                },
            )
            write_json(
                contract,
                {
                    "sourceFingerprint": {"sha256": "oas-current"},
                    "endpoints": {
                        "/loans/current": {
                            "GET": {
                                "responses": {
                                    "200": {
                                        "fields": {
                                            "$.data.amount": {
                                                "type": "number",
                                                "format": "double",
                                                "required": True,
                                                "nullable": False,
                                                "enum": None,
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "/loans/history": {
                            "GET": {
                                "responses": {
                                    "200": {
                                        "fields": {
                                            "$.items[].amount": {
                                                "type": "number",
                                                "format": "double",
                                                "required": True,
                                                "nullable": False,
                                                "enum": None,
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            binding = payload["bindings"][0]["binding"]
            self.assertIsNone(binding["field"])
            self.assertEqual("medium", binding["confidence"])
            self.assertEqual(
                [
                    {
                        "endpoint": "/loans/current",
                        "method": "GET",
                        "status": "200",
                        "jsonPath": "$.data.amount",
                        "type": "number",
                        "format": "double",
                        "required": True,
                        "nullable": False,
                        "enum": None,
                    },
                    {
                        "endpoint": "/loans/history",
                        "method": "GET",
                        "status": "200",
                        "jsonPath": "$.items[].amount",
                        "type": "number",
                        "format": "double",
                        "required": True,
                        "nullable": False,
                        "enum": None,
                    },
                ],
                binding["candidateFields"],
            )
            self.assertEqual("amount-node", payload["needsModelBinding"][0]["node"])

    def test_missing_api_contract_fails_without_writing_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            out = root / "data_slot_bindings.json"
            write_json(manifest, {"components": []})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(root / "missing.json"),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("api contract", (result.stdout + result.stderr).lower())
            self.assertFalse(out.exists())

    def test_incompatible_field_type_is_never_auto_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "name": "LoanCard",
                            "dynamicSlots": [{"node": "amount-node", "text": "₦10,000"}],
                        }
                    ]
                },
            )
            write_json(
                contract,
                {
                    "endpoints": {
                        "/loan": {
                            "GET": {
                                "responses": {
                                    "200": {
                                        "fields": {
                                            "$.amount": {
                                                "type": "string",
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
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            binding = json.loads(out.read_text(encoding="utf-8"))["bindings"][0]["binding"]
            self.assertIsNone(binding["field"])
            self.assertEqual("low", binding["confidence"])
            self.assertEqual([], binding["compatibleCandidateFields"])

    def test_bindings_record_manifest_and_contract_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(manifest, {"components": []})
            write_json(
                contract,
                {
                    "endpoints": {
                        "/health": {
                            "GET": {"responses": {"204": {"fields": {}}}}
                        }
                    }
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
                payload["inputs"]["component_manifest.json"],
            )
            self.assertEqual(
                hashlib.sha256(contract.read_bytes()).hexdigest(),
                payload["inputs"]["api_contract.json"],
            )

    def test_unmatched_dynamic_text_exposes_real_fields_without_auto_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "name": "LoanCard",
                            "dynamicSlots": [
                                {"node": "product-node", "text": "Salary Loan"}
                            ],
                        }
                    ]
                },
            )
            write_json(
                contract,
                {
                    "endpoints": {
                        "/loan": {
                            "GET": {
                                "responses": {
                                    "200": {
                                        "fields": {
                                            "$.productName": {
                                                "type": "string",
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
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            binding = payload["bindings"][0]["binding"]
            self.assertEqual("asText", binding["transform"])
            self.assertEqual("low", binding["confidence"])
            self.assertIsNone(binding["field"])
            self.assertEqual("$.productName", binding["candidateFields"][0]["jsonPath"])
            self.assertEqual("product-node", payload["needsModelBinding"][0]["node"])

    def test_provided_interaction_contract_is_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            interactions = root / "interaction_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(manifest, {"components": []})
            write_json(
                contract,
                {
                    "endpoints": {
                        "/health": {
                            "GET": {"responses": {"204": {"fields": {}}}}
                        }
                    }
                },
            )
            write_json(interactions, {"rules": [{"id": "INT-1"}]})

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--interaction-contract",
                    str(interactions),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                hashlib.sha256(interactions.read_bytes()).hexdigest(),
                payload["inputs"]["interaction_contract.json"],
            )

    def test_schema_variant_is_part_of_candidate_field_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            out = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {"dynamicSlots": [{"node": "amount-node", "text": "₦10"}]}
                    ]
                },
            )
            field_spec = {
                "type": "number",
                "format": None,
                "required": True,
                "nullable": False,
                "enum": None,
            }
            write_json(
                contract,
                {
                    "endpoints": {
                        "/loan": {
                            "GET": {
                                "responses": {
                                    "200": {
                                        "schemaKind": "oneOf",
                                        "fields": {},
                                        "variants": [
                                            {"index": 0, "fields": {"$.amount": field_spec}},
                                            {
                                                "index": 1,
                                                "fields": {"$.reason": {**field_spec, "type": "string"}},
                                            },
                                        ],
                                    }
                                }
                            }
                        }
                    }
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--api-contract",
                    str(contract),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            field = json.loads(out.read_text(encoding="utf-8"))["bindings"][0][
                "binding"
            ]["field"]
            self.assertEqual("oneOf", field["variantKind"])
            self.assertEqual(0, field["variantIndex"])


if __name__ == "__main__":
    unittest.main()
