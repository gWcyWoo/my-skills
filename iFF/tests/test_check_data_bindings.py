from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_bindings.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckDataBindingsTest(unittest.TestCase):
    def test_high_confidence_binding_requires_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                "type": "number",
                "format": None,
                "required": True,
                "nullable": False,
                "enum": None,
            }
            write_json(
                manifest,
                {
                    "components": [
                        {"dynamicSlots": [{"node": "amount-node", "text": "₦10"}]}
                    ]
                },
            )
            write_json(
                contract,
                {
                    "endpoints": {
                        "/loan": {
                            "GET": {
                                "responses": {"200": {"fields": {"$.amount": field}}}
                            }
                        }
                    }
                },
            )
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
                            "confirmedByModel": False,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("model confirmation required: amount-node", result.stdout + result.stderr)

    def test_same_node_in_two_feature_states_is_qualified_by_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                "type": "number",
                "format": None,
                "required": True,
                "nullable": False,
                "enum": None,
            }
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "state": state,
                            "dynamicSlots": [{"node": "amount-node", "text": text}],
                        }
                        for state, text in (("default", "₦10"), ("approved", "₦20"))
                    ]
                },
            )
            write_json(
                contract,
                {
                    "endpoints": {
                        "/loan": {
                            "GET": {
                                "responses": {"200": {"fields": {"$.amount": field}}}
                            }
                        }
                    }
                },
            )
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [
                        {
                            "state": state,
                            "node": "amount-node",
                            "binding": {
                                "field": field,
                                "transform": "formatNaira",
                                "confidence": "high",
                            },
                            "confirmedByModel": True,
                        }
                        for state in ("default", "approved")
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_stale_manifest_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(manifest, {"components": []})
            write_json(contract, {"endpoints": {}})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": "old",
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("stale component_manifest.json", result.stdout + result.stderr)

    def test_missing_dynamic_slot_binding_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "name": "LoanCard",
                            "dynamicSlots": [{"node": "amount-node", "text": "₦10"}],
                        }
                    ]
                },
            )
            write_json(contract, {"endpoints": {}})
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

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
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

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("missing binding: amount-node", result.stdout + result.stderr)

    def test_duplicate_binding_for_one_node_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {
                    "components": [
                        {
                            "dynamicSlots": [{"node": "amount-node", "text": "₦10"}]
                        }
                    ]
                },
            )
            write_json(contract, {"endpoints": {}})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [
                        {"node": "amount-node", "staticReason": "first"},
                        {"node": "amount-node", "staticReason": "second"},
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("duplicate binding: amount-node", result.stdout + result.stderr)

    def test_unresolved_slot_without_static_reason_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
            )
            write_json(contract, {"endpoints": {}})
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
                                "field": None,
                                "transform": "formatNaira",
                                "confidence": "low",
                            },
                            "confirmedByModel": False,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("unresolved binding: amount-node", result.stdout + result.stderr)

    def test_field_not_present_in_current_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
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
                                                "type": "number",
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
            invented = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.availableAmount",
                "type": "number",
                "format": None,
                "required": True,
                "nullable": False,
                "enum": None,
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
                            "binding": {"field": invented, "transform": "formatNaira"},
                            "confirmedByModel": True,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("field absent from current contract: amount-node", result.stdout + result.stderr)

    def test_ambiguous_selected_field_requires_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
            )
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
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
                                        "fields": {
                                            "$.amount": {
                                                key: value
                                                for key, value in field.items()
                                                if key
                                                not in {"endpoint", "method", "status", "jsonPath"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
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
                                "confidence": "medium",
                            },
                            "confirmedByModel": False,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("model confirmation required: amount-node", result.stdout + result.stderr)

    def test_confirmed_binding_still_requires_transform_type_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
            )
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                "type": "string",
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
                                        "fields": {
                                            "$.amount": {
                                                key: value
                                                for key, value in field.items()
                                                if key
                                                not in {"endpoint", "method", "status", "jsonPath"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
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
                                "confidence": "medium",
                            },
                            "confirmedByModel": True,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("transform/type mismatch: amount-node", result.stdout + result.stderr)

    def test_unknown_transform_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "amount-node"}]}]},
            )
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
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
                                        "fields": {
                                            "$.amount": {
                                                key: value
                                                for key, value in field.items()
                                                if key
                                                not in {"endpoint", "method", "status", "jsonPath"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
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
                                "transform": "inventedTransform",
                                "confidence": "medium",
                            },
                            "confirmedByModel": True,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("unknown transform: amount-node", result.stdout + result.stderr)

    def test_static_reason_requires_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(
                manifest,
                {"components": [{"dynamicSlots": [{"node": "title-node"}]}]},
            )
            write_json(contract, {"endpoints": {}})
            write_json(
                bindings,
                {
                    "inputs": {
                        "component_manifest.json": sha256(manifest),
                        "api_contract.json": sha256(contract),
                    },
                    "bindings": [
                        {
                            "node": "title-node",
                            "binding": None,
                            "staticReason": "fixed legal heading",
                            "confirmedByModel": False,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("static reason requires model confirmation: title-node", result.stdout + result.stderr)

    def test_slot_cannot_be_both_dynamic_and_static(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "component_manifest.json"
            contract = root / "api_contract.json"
            bindings = root / "data_slot_bindings.json"
            write_json(manifest, {"components": [{"dynamicSlots": [{"node": "node"}]}]})
            field_spec = {
                "type": "string",
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
                                "responses": {"200": {"fields": {"$.title": field_spec}}}
                            }
                        }
                    }
                },
            )
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.title",
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
                            "node": "node",
                            "binding": {
                                "field": field,
                                "transform": "asText",
                                "confidence": "high",
                            },
                            "staticReason": "also static",
                            "confirmedByModel": True,
                        }
                    ],
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
                    "--bindings",
                    str(bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("conflicting dynamic/static resolution: node", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
