from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_interaction_contract.py"


class CheckInteractionContractTest(unittest.TestCase):
    def test_rule_missing_observable_variant_outcomes_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": '点击"确认"后显示成功页',
                                "action": '点击"确认"',
                                "observableOutcome": "显示成功页",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("boundaryOutcome", result.stdout)
            self.assertIn("failureOutcome", result.stdout)

    def test_rule_requires_a_concrete_public_action_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("missing or invalid actionTarget", result.stdout)

    def test_duplicate_rule_ids_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            rule = {
                "id": "INT-DUP",
                "source": "点击确认后显示成功页",
                "action": "点击确认",
                "actionTarget": {
                    "kind": "node",
                    "board": "default",
                    "key": "iff:confirm",
                },
                "observableOutcome": "显示成功页",
                "boundaryOutcome": "重复点击保持成功页",
                "failureOutcome": "显示失败提示",
            }
            contract.write_text(
                json.dumps({"rules": [rule, rule]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("duplicate rule id: INT-DUP", result.stdout)

    def test_node_target_requires_feature_board_and_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "actionTarget": {
                                    "kind": "node",
                                    "board": "default",
                                    "key": "iff:confirm",
                                },
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("node actionTarget requires feature, board and iff: key", result.stdout)

    def test_system_target_rejects_unknown_gesture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            rule = {
                "id": "INT-BACK",
                "source": "返回后关闭弹窗",
                "action": "返回",
                "actionTarget": {"kind": "system", "gesture": "magic"},
                "observableOutcome": "关闭弹窗",
                "boundaryOutcome": "已关闭时保持页面",
                "failureOutcome": "无法关闭时保留弹窗",
            }
            contract.write_text(json.dumps({"rules": [rule]}), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unsupported system gesture: magic", result.stdout)

    def test_each_outcome_requires_a_structured_public_ui_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            rule = {
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
            }
            contract.write_text(json.dumps({"rules": [rule]}), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("missing or invalid observableTargets.happy", result.stdout)
            self.assertIn("missing or invalid observableTargets.boundary", result.stdout)
            self.assertIn("missing or invalid observableTargets.failure", result.stdout)


if __name__ == "__main__":
    unittest.main()
