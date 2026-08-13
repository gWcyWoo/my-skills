from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iff.scripts.verify_pipeline_scripts import build_report as build_preflight_report
from iff.tests.model_context_fixture import prepare_v3_context, write_json


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts/make_worker_prompt.py"
CHECK_CONTEXT = SKILL_DIR / "scripts/check_model_context.py"


def prepare_inputs(
    root: Path, boards: tuple[str, ...] = ("default",)
) -> tuple[Path, Path, Path, Path, Path]:
    project = root / "project"
    spec = project / "spec/home"
    for board in boards:
        (spec / board).mkdir(parents=True, exist_ok=True)
    manifest = project / ".iff/features/home.json"
    write_json(
        manifest,
        {
            "featureId": "home",
            "states": {
                board: {
                    "board": board,
                    "canvasPath": f"lib/{board}_canvas.dart",
                    "generatedFiles": [f"lib/{board}_canvas.dart"],
                }
                for board in boards
            },
        },
    )
    row = spec / "row.json"
    write_json(row, {"title": "home", "design_url": "https://design/1"})
    preflight = project / ".iff/preflight_report.json"
    write_json(preflight, build_preflight_report(SKILL_DIR))
    return project, spec, manifest, row, preflight


def make_prompt(
    project: Path,
    spec: Path,
    manifest: Path,
    row: Path,
    preflight: Path,
    mode: str,
    *,
    board: str = "default",
    max_bytes: int = 8192,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    worker_id = "assembly" if mode == "assembly" else f"board--{board}"
    out = spec / ".iff/workers" / f"{worker_id}.prompt.md"
    role_spec = spec if mode == "assembly" else spec / board
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skill-dir",
            str(SKILL_DIR),
            "--row-json",
            str(row),
            "--spec-dir",
            str(role_spec),
            "--project-root",
            str(project),
            "--mode",
            mode,
            "--feature-manifest",
            str(manifest),
            "--preflight-report",
            str(preflight),
            "--max-bytes",
            str(max_bytes),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, out


class MakeWorkerPromptTest(unittest.TestCase):
    def test_fetch_role_is_replaced_by_the_deterministic_fetch_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, manifest, row, preflight = prepare_inputs(Path(tmp))
            result, _ = make_prompt(
                project, spec, manifest, row, preflight, "fetch"
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("invalid choice", result.stdout + result.stderr)

    def test_board_contract_is_bounded_current_and_reads_one_visual_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, manifest, row, preflight = prepare_inputs(Path(tmp))
            result, out = make_prompt(
                project, spec, manifest, row, preflight, "board"
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            prompt = out.read_text(encoding="utf-8")
            self.assertLessEqual(out.stat().st_size, 8192)
            self.assertIn("IFF_WORKER_CONTRACT v3", prompt)
            self.assertIn("make_visual_model_packet.py", prompt)
            self.assertIn("read ONLY visual_model_packet.json", prompt)
            self.assertIn("make_implementation_map.py", prompt)
            self.assertNotIn(f"Read {SKILL_DIR / 'SKILL.md'} completely", prompt)

    def test_assembly_contract_keeps_model_packets_bounded_and_defers_fan_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, manifest, row, preflight = prepare_inputs(Path(tmp))
            result, out = make_prompt(
                project, spec, manifest, row, preflight, "assembly"
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            prompt = out.read_text(encoding="utf-8")
            self.assertLessEqual(out.stat().st_size, 8192)
            self.assertIn("make_interaction_model_packet.py", prompt)
            self.assertIn("make_data_model_packet.py", prompt)
            self.assertIn("fan_in_request.json", prompt)
            self.assertIn("state_changes.json", prompt)
            self.assertIn("FORBIDDEN: pubspec", prompt)
            self.assertNotIn("run_data_device_tests.py", prompt)
            self.assertNotIn("check_done_gate.py", prompt)

    def test_large_row_and_shared_component_payloads_are_referenced_not_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, manifest, row, preflight = prepare_inputs(Path(tmp))
            sentinel = "UNBOUNDED_INPUT_" * 1000
            write_json(
                row,
                {
                    "title": "home",
                    "design_url": "https://design/1",
                    "ui_notes": sentinel,
                    "interaction": sentinel,
                    "api": sentinel,
                },
            )
            write_json(
                spec / "default/shared_components.local.json",
                {"components": [{"status": "reuse", "payload": sentinel}]},
            )

            board_result, board_out = make_prompt(
                project, spec, manifest, row, preflight, "board"
            )
            assembly_result, assembly_out = make_prompt(
                project, spec, manifest, row, preflight, "assembly"
            )

            self.assertEqual(
                0,
                board_result.returncode,
                board_result.stdout + board_result.stderr,
            )
            self.assertEqual(
                0,
                assembly_result.returncode,
                assembly_result.stdout + assembly_result.stderr,
            )
            self.assertNotIn(sentinel, board_out.read_text(encoding="utf-8"))
            self.assertNotIn(sentinel, assembly_out.read_text(encoding="utf-8"))
            self.assertIn(
                str((spec / "row_interaction.txt").resolve()),
                assembly_out.read_text(encoding="utf-8"),
            )

    def test_worker_prompt_fails_visibly_when_byte_budget_is_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, manifest, row, preflight = prepare_inputs(Path(tmp))
            result, out = make_prompt(
                project,
                spec,
                manifest,
                row,
                preflight,
                "board",
                max_bytes=100,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("worker prompt exceeds 100 bytes", result.stdout + result.stderr)
            self.assertFalse(out.exists())

    def test_five_board_context_counts_all_packets_and_reduces_controlled_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out, manifest = prepare_v3_context(
                Path(tmp), tuple(f"state-{index}" for index in range(5))
            )
            checked = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_CONTEXT),
                    "--skill-dir",
                    str(SKILL_DIR),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(14, len(report["modelFiles"]))
            self.assertEqual(
                8,
                sum(
                    item["kind"].endswith("_model_packet")
                    for item in report["modelFiles"]
                ),
            )
            prompt_bytes = sum(
                item["bytes"]
                for item in report["modelFiles"]
                if item["kind"] == "worker_prompt"
            )
            self.assertLessEqual(
                report["currentRetainedInputBytes"], prompt_bytes + 8 * 8192
            )
            self.assertGreaterEqual(report["controlledInputReductionPercent"], 90.0)


if __name__ == "__main__":
    unittest.main()
