from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def run(name: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


class ApplyModelDecisionTest(unittest.TestCase):
    def test_data_packet_applies_only_the_decisions_exact_declared_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp)
            bindings = spec / "data_slot_bindings.json"
            field = {
                "endpoint": "/loan",
                "method": "GET",
                "status": "200",
                "jsonPath": "$.amount",
                "type": "number",
            }
            write_json(
                bindings,
                {
                    "bindings": [
                        {
                            "node": "amount",
                            "binding": {
                                "field": field,
                                "compatibleCandidateFields": [field],
                            },
                            "confirmedByModel": False,
                        }
                    ]
                },
            )
            packet = spec / "data_model_packet.json"
            made = run(
                "make_data_model_packet.py",
                "--spec-root",
                spec,
                "--out",
                packet,
            )
            self.assertEqual(0, made.returncode, made.stdout + made.stderr)
            action = json.loads(packet.read_text(encoding="utf-8"))["action"]
            self.assertEqual(
                ["data_slot_bindings.json:bindings.0.confirmedByModel"],
                action["requiredWritePathsByDecision"]["confirm_field"],
            )

            before = bindings.read_bytes()
            forbidden = spec / "forbidden.json"
            write_json(
                forbidden,
                {
                    "kind": "confirm_field",
                    "updates": [
                        {
                            "source": "data_slot_bindings.json",
                            "path": "bindings.0.confirmedByModel",
                            "value": True,
                        },
                        {
                            "source": "data_slot_bindings.json",
                            "path": "bindings.0.staticReason",
                            "value": "invented",
                        },
                    ],
                },
            )
            rejected = run(
                "apply_model_decision.py",
                "--packet",
                packet,
                "--decision",
                forbidden,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual(before, bindings.read_bytes())

            decision = spec / "decision.json"
            write_json(
                decision,
                {
                    "kind": "confirm_field",
                    "updates": [
                        {
                            "source": "data_slot_bindings.json",
                            "path": "bindings.0.confirmedByModel",
                            "value": True,
                        }
                    ],
                },
            )
            applied = run(
                "apply_model_decision.py",
                "--packet",
                packet,
                "--decision",
                decision,
            )
            self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
            self.assertIs(
                True,
                json.loads(bindings.read_text(encoding="utf-8"))["bindings"][0][
                    "confirmedByModel"
                ],
            )

    def test_interaction_packet_applies_one_state_meaning_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            write_json(
                spec / "interaction_contract.json",
                {"rules": []},
            )
            state_machine = spec / "state_machine.json"
            write_json(
                state_machine,
                {
                    "initialState": "idle",
                    "nodes": [{"id": "idle", "meaning": "__MODEL__"}],
                    "edges": [],
                },
            )
            write_json(project / ".iff/board_index.json", {"boards": []})
            packet = spec / "interaction_model_packet.json"
            made = run(
                "make_interaction_model_packet.py",
                "--spec-root",
                spec,
                "--project-root",
                project,
                "--out",
                packet,
            )
            self.assertEqual(0, made.returncode, made.stdout + made.stderr)
            action = json.loads(packet.read_text(encoding="utf-8"))["action"]
            self.assertEqual("define_state_meaning", action["kind"])
            self.assertEqual(
                ["stateMachine:nodes.0.meaning"],
                action["requiredWritePathsByDecision"]["apply"],
            )

            decision = spec / "decision.json"
            write_json(
                decision,
                {
                    "kind": "apply",
                    "updates": [
                        {
                            "source": "stateMachine",
                            "path": "nodes.0.meaning",
                            "value": "等待用户操作",
                        }
                    ],
                },
            )
            applied = run(
                "apply_model_decision.py",
                "--packet",
                packet,
                "--decision",
                decision,
            )
            self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
            self.assertEqual(
                "等待用户操作",
                json.loads(state_machine.read_text(encoding="utf-8"))["nodes"][0][
                    "meaning"
                ],
            )


if __name__ == "__main__":
    unittest.main()
