from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.png_fixture import write_png


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_visual_feature.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_board(board: Path) -> None:
    board.mkdir(parents=True)
    reference = board / "reference.png"
    actual = board / "actual.png"
    write_png(reference, 255, 255, 255)
    write_png(actual, 0, 0, 0)
    (board / "render_fidelity_report.json").write_text(
        json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
    )
    (board / "diff_report.json").write_text(
        json.dumps(
            {
                "shapeIssues": [],
                "assetIssues": [],
                "textIssues": [],
                "viewportIssues": [],
            }
        ),
        encoding="utf-8",
    )
    (board / "visual_manifest.json").write_text(
        json.dumps(
            {
                "actual_source": "simulator_screenshot",
                "device_id": "simulator-1",
                "capture_command": "simctl screenshot",
                "timestamp": "2026-01-01T00:00:00Z",
                "project_root": "/__iff_test_project__",
                "app_hashes": {},
                "runtime_input_hashes": {},
                "launch_command": ["flutter", "run", "-d", "simulator-1"],
                "viewport": {"width": 1, "height": 1, "density": 160},
            }
        ),
        encoding="utf-8",
    )
    (board / "visual_gate_report.json").write_text(
        json.dumps(
            {
                "version": 1,
                "ok": True,
                "inputs": {
                    "reference.png": sha256(reference),
                    "actual.png": sha256(actual),
                    "render_fidelity_report.json": sha256(
                        board / "render_fidelity_report.json"
                    ),
                    "diff_report.json": sha256(board / "diff_report.json"),
                    "visual_manifest.json": sha256(board / "visual_manifest.json"),
                },
            }
        ),
        encoding="utf-8",
    )


class CheckVisualFeatureTest(unittest.TestCase):
    def test_every_manifest_state_requires_a_passing_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            make_board(root / "default")
            make_board(root / "approved")
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "states": {
                            "default": {"board": "default"},
                            "approved": {"board": "approved"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            passing = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, passing.returncode, passing.stdout + passing.stderr)

            for path in (root / "approved").iterdir():
                path.unlink()
            (root / "approved").rmdir()
            missing = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, missing.returncode, missing.stdout)
            self.assertIn("approved: board directory missing", missing.stdout)


if __name__ == "__main__":
    unittest.main()
