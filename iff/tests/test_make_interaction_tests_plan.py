from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "make_interaction_tests_plan.py"
)


class MakeInteractionTestsPlanTest(unittest.TestCase):
    def test_each_variant_uses_its_rule_specific_observable_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "interaction_contract.json"
            plan = root / "interaction_test_plan.json"
            contract.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": '点击"提交"后显示成功页',
                                "precondition": "表单有效",
                                "action": '点击"提交"',
                                "actionTarget": {
                                    "kind": "node",
                                    "feature": "loan",
                                    "board": "form",
                                    "key": "iff:submit",
                                },
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击只提交一次",
                                "failureOutcome": "显示提交失败提示",
                                "observableTargets": {
                                    "happy": {
                                        "kind": "node",
                                        "feature": "loan",
                                        "board": "success",
                                        "key": "iff:success",
                                    },
                                    "boundary": {
                                        "kind": "text",
                                        "feature": "loan",
                                        "board": "form",
                                        "value": "处理中",
                                    },
                                    "failure": {
                                        "kind": "text",
                                        "feature": "loan",
                                        "board": "form",
                                        "value": "提交失败",
                                    },
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--contract",
                    str(contract),
                    "--out",
                    str(plan),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            cases = {
                case["variant"]: case
                for case in json.loads(plan.read_text(encoding="utf-8"))["cases"]
            }

            self.assertEqual("显示成功页", cases["happy"]["expectedObservable"])
            self.assertEqual(
                "重复点击只提交一次",
                cases["boundary"]["expectedObservable"],
            )
            self.assertEqual(
                "显示提交失败提示",
                cases["failure"]["expectedObservable"],
            )
            self.assertTrue(all(case["surface"] == "public_ui" for case in cases.values()))
            self.assertEqual(
                "iff:success", cases["happy"]["expectedObservableTarget"]["key"]
            )
            self.assertEqual(
                "处理中", cases["boundary"]["expectedObservableTarget"]["value"]
            )
            self.assertEqual(
                "提交失败", cases["failure"]["expectedObservableTarget"]["value"]
            )
            self.assertTrue(
                all(
                    case["actionTarget"]
                    == {
                        "kind": "node",
                        "feature": "loan",
                        "board": "form",
                        "key": "iff:submit",
                    }
                    for case in cases.values()
                )
            )


if __name__ == "__main__":
    unittest.main()
