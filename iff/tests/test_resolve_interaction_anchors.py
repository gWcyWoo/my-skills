from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "resolve_interaction_anchors.py"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ResolveInteractionAnchorsTest(unittest.TestCase):
    def test_confirmed_ambiguous_anchor_must_be_one_of_its_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "interaction_contract.json"
            index = root / "board_index.json"
            anchors = root / "interaction_anchors.json"
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")
            index.write_text(json.dumps({"boards": []}), encoding="utf-8")
            anchors.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "contract": sha256(contract),
                            "index": sha256(index),
                        },
                        "anchors": [
                            {
                                "rule": "INT-1",
                                "query": "确认",
                                "resolution": "ambiguous",
                                "candidates": [
                                    {"feature": "loan", "board": "dialog"},
                                    {"feature": "loan", "board": "review"},
                                ],
                                "confirmed": "other/missing",
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
                    "--index",
                    str(index),
                    "--out",
                    str(anchors),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("confirmed target is not a candidate", result.stdout)

    def test_anchor_file_fails_after_contract_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "interaction_contract.json"
            index = root / "board_index.json"
            anchors = root / "interaction_anchors.json"
            contract.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-1",
                                "source": '点击"确认"',
                                "action": '点击"确认"',
                                "observableOutcome": "打开确认页",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            index.write_text(
                json.dumps(
                    {
                        "boards": [
                            {
                                "feature": "loan",
                                "board": "dialog",
                                "texts": ["确认"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            generated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--contract",
                    str(contract),
                    "--index",
                    str(index),
                    "--out",
                    str(anchors),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, generated.returncode, generated.stdout + generated.stderr)
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")

            checked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--contract",
                    str(contract),
                    "--index",
                    str(index),
                    "--out",
                    str(anchors),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, checked.returncode, checked.stdout)
            self.assertIn("stale contract hash", checked.stdout)

    def test_pending_route_requires_a_target_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "interaction_contract.json"
            index = root / "board_index.json"
            anchors = root / "interaction_anchors.json"
            contract.write_text(json.dumps({"rules": []}), encoding="utf-8")
            index.write_text(json.dumps({"boards": []}), encoding="utf-8")
            anchors.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "contract": sha256(contract),
                            "index": sha256(index),
                        },
                        "anchors": [
                            {
                                "rule": "INT-1",
                                "query": "还款详情",
                                "resolution": "unresolved",
                                "candidates": [],
                                "pending_route": True,
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
                    "--contract",
                    str(contract),
                    "--index",
                    str(index),
                    "--out",
                    str(anchors),
                    "--check",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("pending_route missing targetIntent", result.stdout)


if __name__ == "__main__":
    unittest.main()
