from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_state_machine.py"


class MakeStateMachineTest(unittest.TestCase):
    def test_skeleton_exposes_initial_state_as_a_model_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("idle", "done"):
                board = root / name
                board.mkdir()
                (board / "design_classification.json").write_text(
                    json.dumps({"type": "variant_board"}), encoding="utf-8"
                )
            out = root / "state_machine.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("__MODEL__", doc["initialState"])
            self.assertIn("initialState", doc["modelFields"])

    def test_no_transition_reason_cannot_hide_invalid_edges_or_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "idle", "meaning": "初始状态"},
                            {"id": "done", "meaning": "完成状态"},
                        ],
                        "edges": [
                            {
                                "from": "missing",
                                "to": "done",
                                "trigger": "__MODEL__",
                                "condition": None,
                                "ruleId": "INT-SM-001",
                            }
                        ],
                        "noTransitionReason": "设计稿没有迁移",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unfilled __MODEL__", result.stdout)
            self.assertIn("unknown node", result.stdout)

    def test_transition_rule_must_exist_in_interaction_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            contract = root / "interaction_contract.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "idle", "meaning": "初始状态"},
                            {"id": "done", "meaning": "完成状态"},
                        ],
                        "edges": [
                            {
                                "from": "idle",
                                "to": "done",
                                "trigger": "点击确认",
                                "condition": None,
                                "ruleId": "INT-SM-MISSING",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--contract",
                    str(contract),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("ruleId not found in contract", result.stdout)

    def test_nodes_must_match_current_feature_manifest_boards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            manifest = root / "feature.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "invented", "meaning": "不存在的状态"}],
                        "edges": [],
                        "noTransitionReason": "单状态",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "states": {
                            "default": {"board": "default"},
                            "approved": {"board": "approved"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--feature-manifest",
                    str(manifest),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("nodes do not match feature manifest boards", result.stdout)

    def test_same_trigger_and_condition_cannot_target_two_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "idle", "meaning": "初始"},
                            {"id": "approved", "meaning": "通过"},
                            {"id": "rejected", "meaning": "拒绝"},
                        ],
                        "edges": [
                            {
                                "from": "idle",
                                "to": "approved",
                                "trigger": "点击提交",
                                "condition": "status=ok",
                                "ruleId": "INT-1",
                            },
                            {
                                "from": "idle",
                                "to": "rejected",
                                "trigger": "点击提交",
                                "condition": "status=ok",
                                "ruleId": "INT-2",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("conflicting transition", result.stdout)

    def test_every_state_must_be_reachable_from_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [
                            {"id": "idle", "meaning": "初始"},
                            {"id": "approved", "meaning": "通过"},
                            {"id": "abandoned", "meaning": "放弃"},
                        ],
                        "edges": [
                            {
                                "from": "idle",
                                "to": "approved",
                                "trigger": "点击提交",
                                "condition": None,
                                "ruleId": "INT-1",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unreachable states", result.stdout)
            self.assertIn("abandoned", result.stdout)

    def test_blank_state_meaning_and_transition_trigger_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            state_machine.write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [
                            {"id": "idle", "meaning": ""},
                            {"id": "done", "meaning": "完成"},
                        ],
                        "edges": [
                            {
                                "from": "idle",
                                "to": "done",
                                "trigger": "",
                                "condition": None,
                                "ruleId": "INT-1",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(state_machine),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("state idle: missing meaning", result.stdout)
            self.assertIn("edge idle->done: missing trigger", result.stdout)

    def test_duplicate_transition_edge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_machine = root / "state_machine.json"
            edge = {
                "from": "idle",
                "to": "done",
                "trigger": "点击确认",
                "condition": None,
                "ruleId": "INT-1",
            }
            state_machine.write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [
                            {"id": "idle", "meaning": "初始"},
                            {"id": "done", "meaning": "完成"},
                        ],
                        "edges": [edge, edge],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root), "--out", str(state_machine), "--check"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("duplicate edge", result.stdout)

    def test_generated_machine_fails_after_board_inputs_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = root / "idle"
            board.mkdir()
            classification = board / "design_classification.json"
            classification.write_text(json.dumps({"type": "state"}), encoding="utf-8")
            contract = root / "interaction_contract.json"
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")
            manifest = root / "feature.json"
            manifest.write_text(
                json.dumps({"states": {"idle": {"board": "idle"}}}), encoding="utf-8"
            )
            out = root / "state_machine.json"
            generated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(out),
                    "--contract",
                    str(contract),
                    "--feature-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, generated.returncode, generated.stdout + generated.stderr)
            classification.write_text(json.dumps({"type": "changed"}), encoding="utf-8")

            checked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(out),
                    "--contract",
                    str(contract),
                    "--feature-manifest",
                    str(manifest),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, checked.returncode, checked.stdout)
            self.assertIn("stale board inputs", checked.stdout)

    def test_feature_check_requires_current_input_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "state_machine.json"
            contract = root / "interaction_contract.json"
            manifest = root / "feature.json"
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")
            manifest.write_text(
                json.dumps({"states": {"idle": {"board": "idle"}}}), encoding="utf-8"
            )
            out.write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [{"id": "idle", "meaning": "初始"}],
                        "edges": [],
                        "noTransitionReason": "单状态",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--out",
                    str(out),
                    "--contract",
                    str(contract),
                    "--feature-manifest",
                    str(manifest),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("missing current input fingerprints", result.stdout)


if __name__ == "__main__":
    unittest.main()
