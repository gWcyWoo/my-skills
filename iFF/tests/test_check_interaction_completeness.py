from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "check_interaction_completeness.py"
)


class CheckInteractionCompletenessTest(unittest.TestCase):
    def test_source_item_missing_from_rules_and_non_rules_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "source": '点击"确认"后显示成功页；点击"取消"后关闭弹窗',
                        "rules": [
                            {
                                "id": "INT-CONFIRM",
                                "source": '点击"确认"后显示成功页',
                            }
                        ],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [],
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
            self.assertIn('点击"取消"后关闭弹窗', result.stdout)

    def test_acknowledged_non_rule_requires_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "source": "# 交互说明",
                        "rules": [],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [{"source": "# 交互说明"}],
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
            self.assertIn("missing reason", result.stdout)

    def test_compound_candidate_requires_an_explicit_model_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            source = "点击确认后显示成功页，点击取消后关闭弹窗"
            contract.write_text(
                json.dumps(
                    {
                        "source": source,
                        "rules": [],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [],
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

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unresolved compound candidate", result.stdout)

    def test_semantic_non_rule_requires_model_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "interaction_contract.json"
            contract.write_text(
                json.dumps(
                    {
                        "source": "默认状态展示申请入口",
                        "rules": [],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [
                            {
                                "source": "默认状态展示申请入口",
                                "reason": "只是页面说明",
                            }
                        ],
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
            self.assertIn("semantic non-rule not confirmed by model", result.stdout)


if __name__ == "__main__":
    unittest.main()
