from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from data_test_cases import required_data_cases  # noqa: E402


class DataTestCasesTest(unittest.TestCase):
    def test_feature_state_qualifies_repeated_slot_node(self) -> None:
        bindings = {
            "bindings": [
                {
                    "state": state,
                    "node": "amount-node",
                    "binding": {"field": {"jsonPath": "$.amount"}},
                }
                for state in ("approved", "default")
            ]
        }

        self.assertEqual(
            [
                "DATA-SLOT:approved:amount-node",
                "DATA-SLOT:default:amount-node",
            ],
            required_data_cases(bindings, {"operations": []}),
        )

    def test_single_board_slot_keeps_legacy_case_id(self) -> None:
        bindings = {
            "bindings": [
                {
                    "node": "amount-node",
                    "binding": {"field": {"jsonPath": "$.amount"}},
                }
            ]
        }

        self.assertEqual(
            ["DATA-SLOT:amount-node"],
            required_data_cases(bindings, {"operations": []}),
        )


if __name__ == "__main__":
    unittest.main()
