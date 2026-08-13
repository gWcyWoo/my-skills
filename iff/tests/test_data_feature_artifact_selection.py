from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_data_feature import find_one  # noqa: E402


class DataFeatureArtifactSelectionTest(unittest.TestCase):
    def test_feature_root_artifact_wins_over_per_board_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature = root / "component_manifest.json"
            board_a = root / "a/component_manifest.json"
            board_b = root / "b/component_manifest.json"
            board_a.parent.mkdir()
            board_b.parent.mkdir()
            for path in (feature, board_a, board_b):
                path.write_text("{}\n", encoding="utf-8")

            self.assertEqual(feature, find_one(root, "component_manifest.json"))

    def test_multiple_board_artifacts_without_feature_merge_remain_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for board in ("a", "b"):
                path = root / board / "component_manifest.json"
                path.parent.mkdir()
                path.write_text("{}\n", encoding="utf-8")

            self.assertIsNone(find_one(root, "component_manifest.json"))


if __name__ == "__main__":
    unittest.main()
