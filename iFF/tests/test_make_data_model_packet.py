from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_data_model_packet.py"


class MakeDataModelPacketTest(unittest.TestCase):
    def test_selected_field_still_requires_one_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                "type": "number",
            }
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "state": "approved",
                                "node": "amount-node",
                                "designText": "₦10",
                                "binding": {
                                    "field": field,
                                    "transform": "formatNaira",
                                    "confidence": "high",
                                    "compatibleCandidateFields": [field],
                                },
                                "confirmedByModel": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("confirm_field_binding", action["kind"])
            self.assertEqual(field, action["field"])
            self.assertEqual("confirmedByModel=true", action["writeBack"])

    def test_large_candidate_set_becomes_one_bounded_operation_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            candidates = [
                {
                    "endpoint": f"/loans/{index % 3}",
                    "method": "GET",
                    "status": "200",
                    "jsonPath": f"$.data.field{index}",
                    "type": "string",
                    "format": None,
                    "required": False,
                    "nullable": True,
                    "enum": None,
                }
                for index in range(300)
            ]
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "component": "LoanCard",
                                "state": "approved",
                                "board": "approved-board",
                                "node": "product-node",
                                "designText": "Salary Loan",
                                "binding": {
                                    "transform": "asText",
                                    "field": None,
                                    "confidence": "low",
                                    "candidateFields": candidates,
                                    "compatibleCandidateFields": candidates,
                                },
                                "confirmedByModel": False,
                            }
                        ],
                        "needsModelBinding": [{"node": "product-node"}],
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                    "--max-bytes",
                    "4000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("choose_operation", packet["action"]["kind"])
            self.assertEqual("product-node", packet["action"]["node"])
            self.assertEqual("approved", packet["action"]["state"])
            self.assertEqual("approved-board", packet["action"]["board"])
            self.assertEqual(3, len(packet["action"]["operations"]))
            self.assertNotIn("candidateFields", json.dumps(packet))
            self.assertLess(out.stat().st_size, 4000)

    def test_large_selected_operation_advances_to_field_group_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            candidates = [
                {
                    "endpoint": "/loan",
                    "method": "GET",
                    "status": "200",
                    "jsonPath": f"$.data.field{index:02d}",
                    "type": "string",
                }
                for index in range(21)
            ]
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "product-node",
                                "designText": "Salary Loan",
                                "binding": {
                                    "field": None,
                                    "transform": "asText",
                                    "selectedOperation": {
                                        "endpoint": "/loan",
                                        "method": "GET",
                                        "status": "200",
                                    },
                                    "compatibleCandidateFields": candidates,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("choose_field_group", action["kind"])
            self.assertGreater(len(action["groups"]), 1)
            self.assertTrue(all(group["candidateCount"] <= 10 for group in action["groups"]))
            self.assertEqual("binding.selectedFieldGroup", action["writeBack"])

    def test_selected_field_group_exposes_only_that_bounded_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            candidates = [
                {
                    "endpoint": "/loan",
                    "method": "GET",
                    "status": "200",
                    "jsonPath": f"$.data.field{index:02d}",
                    "type": "string",
                }
                for index in range(21)
            ]
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "product-node",
                                "designText": "Salary Loan",
                                "binding": {
                                    "field": None,
                                    "transform": "asText",
                                    "selectedOperation": {
                                        "endpoint": "/loan",
                                        "method": "GET",
                                        "status": "200",
                                    },
                                    "selectedFieldGroup": 1,
                                    "compatibleCandidateFields": candidates,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("choose_field", action["kind"])
            self.assertEqual(10, len(action["candidates"]))
            self.assertEqual("$.data.field10", action["candidates"][0]["jsonPath"])
            self.assertEqual("$.data.field19", action["candidates"][-1]["jsonPath"])

    def test_selected_operation_yields_only_its_field_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            candidates = [
                {
                    "endpoint": endpoint,
                    "method": "GET",
                    "status": "200",
                    "jsonPath": f"$.field{index}",
                    "type": "string",
                    "format": None,
                    "required": False,
                    "nullable": True,
                    "enum": None,
                }
                for endpoint in ("/current", "/history")
                for index in range(15)
            ]
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "product-node",
                                "designText": "Salary Loan",
                                "binding": {
                                    "transform": "asText",
                                    "field": None,
                                    "selectedOperation": {
                                        "endpoint": "/current",
                                        "method": "GET",
                                        "status": "200",
                                    },
                                    "compatibleCandidateFields": candidates,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                    "--max-bytes",
                    "8192",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("choose_field", action["kind"])
            self.assertEqual(15, len(action["candidates"]))
            self.assertEqual({"/current"}, {field["endpoint"] for field in action["candidates"]})

    def test_resolved_bindings_route_first_gate_failure_as_deterministic_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            (spec / "data_slot_bindings.json").write_text(
                json.dumps({"bindings": []}), encoding="utf-8"
            )
            (spec / "data_gate_report.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "failures": [
                            "fetchLoan: missing required states: error",
                            "second failure should wait",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("run_deterministic_repair", action["kind"])
            self.assertFalse(action["requiresJudgment"])
            self.assertEqual(
                "fetchLoan: missing required states: error", action["failure"]
            )
            self.assertNotIn("second failure should wait", json.dumps(action))

    def test_field_choice_packet_exposes_confirmed_static_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            (spec / "data_slot_bindings.json").write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "title-node",
                                "designText": "Terms",
                                "binding": {
                                    "transform": "asText",
                                    "field": None,
                                    "compatibleCandidateFields": [],
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = spec / "data_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual(["bind_field", "mark_static"], action["allowedDecisions"])
            self.assertEqual(
                "staticReason + confirmedByModel=true", action["staticWriteBack"]
            )


if __name__ == "__main__":
    unittest.main()
