from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.png_fixture import write_png


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "check_visual_provenance.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run(name: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


def prepare_board(board: Path) -> None:
    board.mkdir(parents=True)
    write_png(board / "reference.png", 0, 0, 0, width=8, height=8)
    write_png(
        board / "actual.png",
        0,
        0,
        0,
        width=8,
        height=8,
        metadata=b"fixture=actual",
    )
    write_json(board / "layout_contract.json", {})
    write_json(board / "actual_layout_trace.json", {"nodes": {}})
    write_json(board / "merged_expected.json", {"nodes": {}})
    write_json(board / "tokens.json", {})
    diff = run(
        "visual_diff.py",
        "--reference",
        board / "reference.png",
        "--actual",
        board / "actual.png",
        "--layout",
        board / "layout_contract.json",
        "--out",
        board / "diff_report.json",
        "--heatmap",
        board / "diff_heatmap.png",
    )
    if diff.returncode != 0:
        raise AssertionError(diff.stdout + diff.stderr)
    fidelity = run(
        "check_render_fidelity.py",
        "--trace",
        board / "actual_layout_trace.json",
        "--expected",
        board / "merged_expected.json",
        "--tokens",
        board / "tokens.json",
        "--diff-report",
        board / "diff_report.json",
        "--out",
        board / "render_fidelity_report.json",
    )
    if fidelity.returncode != 0:
        raise AssertionError(fidelity.stdout + fidelity.stderr)


class CheckVisualProvenanceTest(unittest.TestCase):
    def test_current_reports_pass_and_hand_edited_result_fails_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "default"
            prepare_board(board)

            current = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, current.returncode, current.stdout + current.stderr)

            report = json.loads(
                (board / "diff_report.json").read_text(encoding="utf-8")
            )
            report["pixelMismatch"] = 0.5
            write_json(board / "diff_report.json", report)

            tampered = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, tampered.returncode)
            self.assertIn(
                "diff_report.json differs from deterministic recomputation",
                tampered.stdout + tampered.stderr,
            )


if __name__ == "__main__":
    unittest.main()
