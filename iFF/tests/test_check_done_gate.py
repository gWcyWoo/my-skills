from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.test_check_interaction_feature import (
    add_valid_runtime_evidence,
    make_valid_core,
)
from iFF.tests.model_context_fixture import prepare_v3_context
from iFF.tests.png_fixture import write_png


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_done_gate.py"
SKILL_DIR = SCRIPT.parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def board_inputs_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for board in sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    ):
        digest.update(board.name.encode("utf-8"))
        for name in (
            "design_classification.json",
            "scene.json",
            "shared_components.local.json",
        ):
            path = board / name
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def make_valid_feature(root: Path, *, include_legacy_interaction: bool = True) -> None:
    for name in ("default", "approved"):
        board = root / name
        write_json(board / "artifact_digest.json", {})
        write_json(board / "shared_components.local.json", {"components": []})
        write_json(board / "layout_contract.json", {})
        write_json(board / "actual_layout_trace.json", {"nodes": {}})
        write_json(board / "merged_expected.json", {"nodes": {}})
        write_json(board / "tokens.json", {})
        write_json(
            board / "visual_manifest.json",
            {
                "actual_source": "simulator_screenshot",
                "device_id": "simulator-1",
                "capture_command": "simctl screenshot",
                "timestamp": "2026-01-01T00:00:00Z",
                "project_root": str(root.resolve()),
                "app_hashes": {},
                "runtime_input_hashes": {},
                "launch_command": ["flutter", "run", "-d", "simulator-1"],
                "viewport": {"width": 8, "height": 8, "density": 160},
            },
        )
        reference = board / "reference.png"
        actual = board / "actual.png"
        write_png(reference, 0, 0, 0, width=8, height=8)
        write_png(
            actual,
            0,
            0,
            0,
            width=8,
            height=8,
            metadata=b"fixture=actual",
        )
        diff = subprocess.run(
            [
                sys.executable,
                str(SKILL_DIR / "scripts/visual_diff.py"),
                "--reference",
                str(reference),
                "--actual",
                str(actual),
                "--layout",
                str(board / "layout_contract.json"),
                "--out",
                str(board / "diff_report.json"),
                "--heatmap",
                str(board / "diff_heatmap.png"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if diff.returncode != 0:
            raise AssertionError(diff.stdout + diff.stderr)
        fidelity = subprocess.run(
            [
                sys.executable,
                str(SKILL_DIR / "scripts/check_render_fidelity.py"),
                "--trace",
                str(board / "actual_layout_trace.json"),
                "--expected",
                str(board / "merged_expected.json"),
                "--tokens",
                str(board / "tokens.json"),
                "--diff-report",
                str(board / "diff_report.json"),
                "--out",
                str(board / "render_fidelity_report.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if fidelity.returncode != 0:
            raise AssertionError(fidelity.stdout + fidelity.stderr)
        write_json(
            board / "visual_gate_report.json",
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
            },
        )

    first = root / "default"
    write_json(first / "implementation_plan.json", {"prefilledBy": "test"})
    if include_legacy_interaction:
        write_json(
            first / "interaction_test_evidence.json",
            {"red": {"exitCode": 1}, "green": {"exitCode": 0}},
        )
        write_json(first / "wiring_report.json", {"ok": True, "unwired": []})
    write_json(first / "api_integration_report.json", {"missing": []})
    write_json(first / "worker_compliance.json", {})


def add_valid_model_context(root: Path, project: Path, manifest: Path) -> None:
    context_project = root.parent
    _, _, report, _ = prepare_v3_context(
        context_project,
        project=context_project,
        spec=root,
        manifest=manifest,
    )
    made = subprocess.run(
        [
            sys.executable,
            str(SCRIPT.parent / "check_model_context.py"),
            "--skill-dir",
            str(SKILL_DIR),
            "--spec-root",
            str(root),
            "--project-root",
            str(context_project),
            "--feature-manifest",
            str(manifest),
            "--out",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if made.returncode != 0:
        raise AssertionError(made.stdout + made.stderr)


class CheckDoneGateTest(unittest.TestCase):
    def test_done_requires_model_context_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("model_context_report.json missing", result.stdout)

    def test_done_recomputes_model_context_instead_of_trusting_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, project, manifest = make_valid_core(Path(tmp))
            make_valid_feature(root)
            add_valid_model_context(root, project, manifest)
            (root / ".iff/workers/board--default.prompt.md").write_text(
                "changed after context report\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("model context recompute failed", result.stdout)

    def test_hand_edited_data_gate_report_cannot_hide_missing_current_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        },
                        "approved": {
                            "board": "approved",
                            "canvasPath": "lib/approved_canvas.dart",
                            "generatedFiles": ["lib/approved_canvas.dart"],
                        },
                    },
                },
            )
            project = Path(tmp) / "project"
            project.mkdir()
            runtime = root / "default" / "data_runtime_manifest.json"
            write_json(runtime, {"operations": []})
            write_json(
                root / "default" / "data_gate_report.json",
                {
                    "version": 1,
                    "ok": True,
                    "specRoot": str(root.resolve()),
                    "projectRoot": str(project.resolve()),
                    "runtimeManifest": str(runtime.resolve()),
                    "inputs": {},
                    "failures": [],
                },
            )
            changed = Path(tmp) / "changed-files.txt"
            changed.write_text("lib/default_canvas.dart\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                    "--state-key",
                    "default",
                    "--changed-files",
                    str(changed),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("data gate recompute failed", result.stdout + result.stderr)

    def test_hand_edited_interaction_gate_report_cannot_hide_missing_current_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        },
                        "approved": {
                            "board": "approved",
                            "canvasPath": "lib/approved_canvas.dart",
                            "generatedFiles": ["lib/approved_canvas.dart"],
                        },
                    },
                },
            )
            changed = Path(tmp) / "changed-files.txt"
            changed.write_text("lib/approved_canvas.dart\n", encoding="utf-8")
            project = Path(tmp) / "project"
            project.mkdir()
            write_json(
                root / "default" / "interaction_gate_report.json",
                {
                    "version": 1,
                    "ok": True,
                    "specRoot": str(root),
                    "projectRoot": str(project),
                    "featureManifest": str(manifest),
                    "inputs": {},
                    "failures": [],
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                    "--state-key",
                    "approved",
                    "--changed-files",
                    str(changed),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("interaction gate recompute failed", result.stdout)

    def test_valid_feature_passes_with_atomic_state_changes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, project, manifest = make_valid_core(Path(tmp))
            make_valid_feature(root, include_legacy_interaction=False)
            write_json(
                manifest,
                {
                    "featureId": "feature",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        }
                    },
                },
            )
            state_machine = root / "state_machine.json"
            machine_doc = json.loads(state_machine.read_text(encoding="utf-8"))
            machine_doc["inputs"]["boards"] = board_inputs_hash(root)
            machine_doc["inputs"]["featureManifest"] = sha256(manifest)
            write_json(state_machine, machine_doc)
            add_valid_runtime_evidence(root, project)
            add_valid_model_context(root, project, manifest)
            wiring = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT.parent / "check_interaction_wiring.py"),
                    "--lib-root",
                    str(project / "lib"),
                    "--test-root",
                    str(project / "test"),
                    "--entry",
                    str(project / "lib" / "main.dart"),
                    "--pubspec",
                    str(project / "pubspec.yaml"),
                    "--contract",
                    str(root / "interaction_contract.json"),
                    "--out",
                    str(root / "default" / "wiring_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, wiring.returncode, wiring.stdout + wiring.stderr)
            interaction_gate = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT.parent / "check_interaction_feature.py"),
                    "--spec-root",
                    str(root),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(root / "default" / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                0,
                interaction_gate.returncode,
                interaction_gate.stdout + interaction_gate.stderr,
            )
            state_changes = Path(tmp) / "state_changes.json"
            write_json(
                state_changes,
                {
                    "version": 1,
                    "states": {"default": ["lib/default_canvas.dart"]},
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                    "--state-changes",
                    str(state_changes),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_done_requires_state_change_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        },
                        "approved": {
                            "board": "approved",
                            "canvasPath": "lib/approved_canvas.dart",
                            "generatedFiles": ["lib/approved_canvas.dart"],
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("state change evidence is required", result.stdout)

    def test_done_requires_a_feature_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("feature manifest is required", result.stdout)

    def test_feature_manifest_ownership_conflicts_block_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/shared_binding.dart"],
                        },
                        "approved": {
                            "board": "approved",
                            "canvasPath": "lib/approved_canvas.dart",
                            "generatedFiles": ["lib/shared_binding.dart"],
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("states share generated file", result.stdout)

    def test_state_change_scope_is_part_of_done_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        },
                        "approved": {
                            "board": "approved",
                            "canvasPath": "lib/approved_canvas.dart",
                            "generatedFiles": ["lib/approved_canvas.dart"],
                        },
                    },
                    "protectedFiles": ["lib/loan_home_page.dart"],
                },
            )
            changed = Path(tmp) / "changed-files.txt"
            changed.write_text("lib/loan_home_page.dart\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                    "--state-key",
                    "approved",
                    "--changed-files",
                    str(changed),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("out-of-scope change: lib/loan_home_page.dart", result.stdout)

    def test_each_board_requires_current_visual_gate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            for name in ("default", "approved"):
                (root / name / "visual_gate_report.json").unlink()

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("visual_gate_report.json", result.stdout)

    def test_every_board_requires_its_own_final_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            (root / "approved" / "diff_report.json").unlink()
            (root / "approved" / "visual_manifest.json").unlink()

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("approved", result.stdout)

    def test_visual_defects_in_later_board_block_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            write_json(
                root / "default" / "diff_report.json",
                {
                    "assetIssues": [
                        {"node": "approved-icon", "pixelMismatch": 0.42},
                    ],
                    "textIssues": [],
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("approved-icon", result.stdout)

    def test_unresolved_semantic_component_candidate_blocks_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            write_json(
                root / "approved" / "shared_components.local.json",
                {
                    "components": [
                        {
                            "signature": "struct:abc",
                            "status": "candidate",
                            "model_decision": {
                                "required": True,
                                "reason": "structural_match_only",
                            },
                        }
                    ]
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unresolved semantic component candidate", result.stdout)

    def test_feature_manifest_states_are_part_of_done_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loan_home"
            make_valid_feature(root)
            manifest = Path(tmp) / "loan_home.json"
            write_json(
                manifest,
                {
                    "featureId": "loan_home",
                    "states": {
                        "default": {"board": "default"},
                        "approved": {"board": "approved"},
                        "rejected": {"board": "rejected"},
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(root),
                    "--feature-manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("rejected: board directory missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
