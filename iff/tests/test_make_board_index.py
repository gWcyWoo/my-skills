from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_board_index.py"


class MakeBoardIndexTest(unittest.TestCase):
    def test_index_exposes_visible_node_ids_as_runtime_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board = root / "specs" / "loan" / "default"
            board.mkdir(parents=True)
            (board / "scene.json").write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "confirm-button", "text": "确认"},
                            {"id": "shape-only"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = root / "board_index.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--specs-dir",
                    str(root / "specs"),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            nodes = json.loads(out.read_text(encoding="utf-8"))["boards"][0]["nodes"]
            self.assertEqual(
                {"id": "confirm-button", "key": "iff:confirm-button", "text": "确认"},
                nodes[0],
            )


if __name__ == "__main__":
    unittest.main()
