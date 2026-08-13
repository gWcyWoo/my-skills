from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "parse_interactions.py"


def parse(text: str, out: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--interaction", text, "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(out.read_text(encoding="utf-8"))


class ParseInteractionsTest(unittest.TestCase):
    def test_rule_id_is_stable_when_an_unrelated_rule_is_inserted_before_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = parse('点击"确认"后显示成功页', root / "original.json")
            changed = parse(
                '点击"取消"后关闭弹窗；点击"确认"后显示成功页',
                root / "changed.json",
            )

            original_id = original["rules"][0]["id"]
            changed_id = next(
                rule["id"]
                for rule in changed["rules"]
                if rule["source"] == '点击"确认"后显示成功页'
            )

            self.assertEqual(original_id, changed_id)

    def test_deterministic_non_rule_is_acknowledged_with_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = parse(
                '# 交互说明\n点击"确认"后显示成功页',
                Path(tmp) / "contract.json",
            )

            self.assertEqual([], doc["ignoredItems"])
            self.assertEqual(
                [{"source": "# 交互说明", "reason": "structure_or_heading"}],
                doc["acknowledgedNonRules"],
            )

    def test_rule_separates_deterministic_action_from_model_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule = parse(
                '点击"确认"后显示成功页',
                Path(tmp) / "contract.json",
            )["rules"][0]

            self.assertEqual('点击"确认"', rule["action"])
            self.assertEqual("显示成功页", rule["observableOutcome"])
            self.assertEqual("__MODEL__", rule["boundaryOutcome"])
            self.assertEqual("__MODEL__", rule["failureOutcome"])
            self.assertEqual({"kind": "__MODEL__"}, rule["actionTarget"])

    def test_business_type_prefix_cannot_auto_acknowledge_a_real_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = parse(
                "LoanOffer：点击确认后显示成功页",
                Path(tmp) / "contract.json",
            )

            self.assertEqual([], doc["acknowledgedNonRules"])
            self.assertEqual(1, len(doc["rules"]))
            self.assertEqual("LoanOffer：点击确认后显示成功页", doc["rules"][0]["source"])
            self.assertEqual("点击确认", doc["rules"][0]["action"])
            self.assertEqual("显示成功页", doc["rules"][0]["observableOutcome"])

    def test_multiple_triggers_are_exposed_as_one_compound_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = "点击确认后显示成功页，点击取消后关闭弹窗"
            doc = parse(source, Path(tmp) / "contract.json")

            self.assertEqual([], doc["rules"])
            self.assertEqual(
                [
                    {
                        "source": source,
                        "suggestedClauses": [
                            "点击确认后显示成功页",
                            "点击取消后关闭弹窗",
                        ],
                    }
                ],
                doc["compoundCandidates"],
            )


if __name__ == "__main__":
    unittest.main()
