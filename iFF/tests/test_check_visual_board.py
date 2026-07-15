from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.png_fixture import write_png


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_visual_board.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def required_inputs(board: Path) -> dict[str, str]:
    defaults = {
        "render_fidelity_report.json": {"ok": True, "assetShapeChecked": True},
        "diff_report.json": {
            "shapeIssues": [],
            "assetIssues": [],
            "textIssues": [],
            "viewportIssues": [],
        },
        "visual_manifest.json": {
            "actual_source": "simulator_screenshot",
            "device_id": "simulator-1",
            "capture_command": "simctl screenshot",
            "timestamp": "2026-01-01T00:00:00Z",
            "project_root": "/__iff_test_project__",
            "app_hashes": {},
            "runtime_input_hashes": {},
            "launch_command": ["flutter", "run", "-d", "simulator-1"],
            "viewport": {"width": 1, "height": 1, "density": 160},
        },
    }
    for name, value in defaults.items():
        path = board / name
        if not path.is_file():
            path.write_text(json.dumps(value), encoding="utf-8")
    return {
        name: sha256(board / name)
        for name in (
            "reference.png",
            "actual.png",
            "render_fidelity_report.json",
            "diff_report.json",
            "visual_manifest.json",
        )
    }


class CheckVisualBoardTest(unittest.TestCase):
    def test_checker_recomputes_hard_failures_from_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "approved"
            board.mkdir()
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "shapeIssues": [],
                        "viewportIssues": [{"issue": "wrong crop"}],
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
                    }
                ),
                encoding="utf-8",
            )
            (board / "visual_gate_report.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "ok": True,
                        "inputs": required_inputs(board),
                        "hardFailures": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("current evidence has viewport hard failure", result.stdout)

    def test_all_visual_evidence_inputs_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "approved"
            board.mkdir()
            reference = board / "reference.png"
            actual = board / "actual.png"
            reference.write_bytes(b"reference")
            actual.write_bytes(b"actual")
            (board / "visual_gate_report.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "ok": True,
                        "inputs": {
                            "reference.png": sha256(reference),
                            "actual.png": sha256(actual),
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("input fingerprint missing: diff_report.json", result.stdout)

    def test_reference_change_invalidates_existing_visual_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "approved"
            board.mkdir()
            reference = board / "reference.png"
            actual = board / "actual.png"
            write_png(reference, 255, 255, 255)
            write_png(actual, 0, 0, 0)
            (board / "visual_gate_report.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "ok": True,
                        "inputs": required_inputs(board),
                    }
                ),
                encoding="utf-8",
            )

            initial = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initial.returncode, initial.stdout + initial.stderr)

            write_png(reference, 255, 0, 0)
            stale = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, stale.returncode, stale.stdout)
            self.assertIn("stale input reference.png", stale.stdout)

    def test_classified_reference_defect_blocks_even_when_report_says_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "approved"
            board.mkdir()
            reference = board / "reference.png"
            actual = board / "actual.png"
            reference.write_bytes(b"reference")
            actual.write_bytes(b"actual")
            (board / "visual_gate_report.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "ok": True,
                        "inputs": required_inputs(board),
                        "hardFailures": [
                            {
                                "category": "shape",
                                "node": "card-background",
                                "reason": "reference region differs",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("shape", result.stdout)
            self.assertIn("card-background", result.stdout)


if __name__ == "__main__":
    unittest.main()
