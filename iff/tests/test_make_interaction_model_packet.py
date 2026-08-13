from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "make_interaction_model_packet.py"
)


class MakeInteractionModelPacketTest(unittest.TestCase):
    def test_unresolved_compound_candidate_is_one_model_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            source = "点击确认后显示成功页，点击取消后关闭弹窗"
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [],
                        "compoundCandidates": [
                            {
                                "source": source,
                                "suggestedClauses": [
                                    "点击确认后显示成功页",
                                    "点击取消后关闭弹窗",
                                ],
                            }
                        ],
                        "compoundDecisions": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("classify_compound_rule", packet["action"]["kind"])
            self.assertEqual(source, packet["action"]["source"])
            self.assertEqual(2, len(packet["action"]["suggestedClauses"]))

    def test_ignored_semantic_item_is_one_classification_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            source = "默认状态展示申请入口"
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [],
                        "ignoredItems": [source],
                        "acknowledgedNonRules": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(spec), "--project-root", str(project), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("classify_interaction_item", packet["action"]["kind"])
            self.assertEqual(source, packet["action"]["source"])

    def test_packet_is_bounded_and_contains_exactly_one_unresolved_rule_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-FIRST",
                                "source": "点击确认后显示成功页",
                                "action": "__MODEL__",
                                "actionTarget": {"kind": "__MODEL__"},
                                "observableOutcome": "__MODEL__",
                                "boundaryOutcome": "__MODEL__",
                                "failureOutcome": "__MODEL__",
                            },
                            {
                                "id": "INT-SECOND",
                                "source": "点击取消后关闭弹窗" + "x" * 20000,
                                "action": "点击取消",
                                "actionTarget": {"kind": "__MODEL__"},
                                "observableOutcome": "关闭弹窗",
                                "boundaryOutcome": "__MODEL__",
                                "failureOutcome": "__MODEL__",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps(
                    {
                        "boards": [
                            {
                                "feature": "feature",
                                "board": "default",
                                "texts": ["确认"],
                                "nodes": [
                                    {
                                        "id": "confirm",
                                        "key": "iff:confirm",
                                        "text": "确认",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertLessEqual(len(out.read_bytes()), 8192)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("INT-FIRST", packet["action"]["ruleId"])
            self.assertNotIn("INT-SECOND", out.read_text(encoding="utf-8"))
            self.assertIsInstance(packet["action"], dict)
            self.assertIn("action", packet["action"]["missingFields"])
            self.assertIn("observableOutcome", packet["action"]["missingFields"])
            self.assertIn("observableTargets.happy", packet["action"]["missingFields"])

    def test_selected_rule_source_is_never_silently_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            source = "点击确认后" + "显示完整业务说明" * 80
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-LONG",
                                "source": source,
                                "action": "点击确认",
                                "actionTarget": {"kind": "__MODEL__"},
                                "observableOutcome": "显示结果",
                                "boundaryOutcome": "__MODEL__",
                                "failureOutcome": "__MODEL__",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(spec), "--project-root", str(project), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(source, packet["action"]["source"])

    def test_many_action_targets_use_a_lossless_board_selection_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-MANY",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "actionTarget": {"kind": "__MODEL__"},
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "__MODEL__",
                                "failureOutcome": "__MODEL__",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            boards = []
            for feature, board in (("loan", "form"), ("account", "form")):
                boards.append(
                    {
                        "feature": feature,
                        "board": board,
                        "nodes": [
                            {"key": f"iff:{feature}-{index}", "text": "确认"}
                            for index in range(3)
                        ],
                    }
                )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": boards}, ensure_ascii=False), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(spec), "--project-root", str(project), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("choose_action_target_board", action["kind"])
            self.assertEqual(6, action["candidateCount"])
            self.assertEqual(2, len(action["candidateBoards"]))

    def test_resolved_contract_advances_to_one_state_machine_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "actionTarget": {
                                    "kind": "node",
                                    "feature": "loan",
                                    "board": "idle",
                                    "key": "iff:confirm",
                                },
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                                "observableTargets": {
                                    variant: {"kind": "text", "feature": "loan", "board": "idle", "value": "result"}
                                    for variant in ("happy", "boundary", "failure")
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (spec / "state_machine.json").write_text(
                json.dumps(
                    {
                        "initialState": "__MODEL__",
                        "nodes": [
                            {"id": "idle", "meaning": "__MODEL__"},
                            {"id": "done", "meaning": "__MODEL__"},
                        ],
                        "edges": [{"from": "__MODEL__", "to": "__MODEL__"}],
                    }
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("define_state_meaning", packet["action"]["kind"])
            self.assertEqual("idle", packet["action"]["stateId"])
            self.assertNotIn("nodes", packet["action"])
            self.assertLessEqual(len(out.read_bytes()), 8192)

    def test_resolved_state_advances_to_one_ambiguous_anchor_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            contract = {
                "rules": [
                    {
                        "id": "INT-ABC",
                        "source": "点击确认后显示成功页",
                        "action": "点击确认",
                        "actionTarget": {
                            "kind": "node",
                            "feature": "loan",
                            "board": "idle",
                            "key": "iff:confirm",
                        },
                        "observableOutcome": "显示成功页",
                        "boundaryOutcome": "重复点击保持成功页",
                        "failureOutcome": "显示失败提示",
                        "observableTargets": {
                            variant: {"kind": "text", "feature": "loan", "board": "idle", "value": "result"}
                            for variant in ("happy", "boundary", "failure")
                        },
                    }
                ]
            }
            (spec / "interaction_contract.json").write_text(
                json.dumps(contract, ensure_ascii=False), encoding="utf-8"
            )
            (spec / "state_machine.json").write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [{"id": "idle", "meaning": "初始"}],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            (spec / "interaction_anchors.json").write_text(
                json.dumps(
                    {
                        "anchors": [
                            {
                                "rule": "INT-ABC",
                                "query": "成功页",
                                "resolution": "ambiguous",
                                "candidates": [
                                    {"feature": "loan", "board": f"state-{index}"}
                                    for index in range(9)
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("confirm_anchor", action["kind"])
            self.assertEqual("INT-ABC", action["ruleId"])
            self.assertEqual(9, len(action["candidates"]))

    def test_ready_plan_exposes_only_first_unproved_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            (project / ".iff").mkdir(parents=True)
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "actionTarget": {
                                    "kind": "node",
                                    "feature": "loan",
                                    "board": "default",
                                    "key": "iff:confirm",
                                },
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                                "observableTargets": {
                                    variant: {"kind": "text", "feature": "loan", "board": "default", "value": "result"}
                                    for variant in ("happy", "boundary", "failure")
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (spec / "state_machine.json").write_text(
                json.dumps(
                    {
                        "initialState": "default",
                        "nodes": [{"id": "default", "meaning": "默认"}],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            (spec / "interaction_anchors.json").write_text(
                json.dumps({"anchors": []}), encoding="utf-8"
            )
            (spec / "interaction_test_plan.json").write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "INT-ABC-HAPPY",
                                "action": "点击确认",
                                "actionTarget": {
                                    "kind": "node",
                                    "board": "default",
                                    "key": "iff:confirm",
                                },
                                "expectedObservable": "显示成功页",
                                "expectedObservableTarget": {
                                    "kind": "text",
                                    "feature": "loan",
                                    "board": "default",
                                    "value": "success",
                                },
                                "surface": "public_ui",
                            },
                            {
                                "id": "INT-ABC-BOUNDARY",
                                "action": "重复点击确认",
                                "expectedObservable": "只提交一次",
                                "surface": "public_ui",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project / ".iff" / "board_index.json").write_text(
                json.dumps({"boards": []}), encoding="utf-8"
            )
            out = spec / "interaction_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet_text = out.read_text(encoding="utf-8")
            action = json.loads(packet_text)["action"]
            self.assertEqual("implement_interaction_case", action["kind"])
            self.assertEqual("INT-ABC-HAPPY", action["case"]["id"])
            self.assertEqual("iff:confirm", action["case"]["actionTarget"]["key"])
            self.assertEqual(
                "success", action["case"]["expectedObservableTarget"]["value"]
            )
            self.assertNotIn("INT-ABC-BOUNDARY", packet_text)


if __name__ == "__main__":
    unittest.main()
