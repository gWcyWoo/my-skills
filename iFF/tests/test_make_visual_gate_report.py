from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.png_fixture import write_png


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_visual_gate_report.py"
LEGACY_MANIFEST = {
    "actual_source": "simulator_screenshot",
    "device_id": "simulator-1",
    "capture_command": "simctl screenshot",
    "timestamp": "2026-01-01T00:00:00Z",
}
VALID_MANIFEST = {
    **LEGACY_MANIFEST,
    "project_root": "/__iff_test_project__",
    "app_hashes": {},
    "runtime_input_hashes": {},
    "launch_command": ["flutter", "run", "-d", "simulator-1"],
    "viewport": {"width": 750, "height": 1334, "density": 160},
}


class MakeVisualGateReportTest(unittest.TestCase):
    def test_unexpected_region_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            write_png(board / "reference.png", 255, 255, 255)
            write_png(board / "actual.png", 0, 0, 0)
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "ssim": 1.0,
                        "shapeIssues": [],
                        "unexpectedIssues": [
                            {"issue": "outside expected widgets", "pixelCount": 100}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("unexpected_region", report["hardFailures"][0]["category"])

    def test_legacy_manifest_without_runtime_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(LEGACY_MANIFEST), encoding="utf-8"
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            reasons = " ".join(
                failure["reason"]
                for failure in json.loads(out.read_text(encoding="utf-8"))["hardFailures"]
            )
            self.assertIn("project_root", reasons)
            self.assertIn("app_hashes", reasons)
            self.assertIn("launch_command", reasons)
            self.assertIn("viewport", reasons)

    def test_changed_app_source_invalidates_screenshot_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            board = project / "spec"
            board.mkdir()
            app_file = project / "lib" / "feature" / "page.dart"
            app_file.parent.mkdir(parents=True)
            app_file.write_text("class PageV1 {}\n", encoding="utf-8")
            captured_hash = hashlib.sha256(app_file.read_bytes()).hexdigest()
            app_file.write_text("class PageV2 {}\n", encoding="utf-8")
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(
                    {
                        **VALID_MANIFEST,
                        "project_root": str(project),
                        "app_hashes": {"feature/page.dart": captured_hash},
                        "launch_command": ["flutter", "run", "-d", "simulator-1"],
                        "viewport": {"width": 750, "height": 1334, "density": 160},
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    failure["category"] == "evidence"
                    and "app source changed" in failure["reason"]
                    for failure in report["hardFailures"]
                ),
                report,
            )

    def test_changed_runtime_asset_configuration_invalidates_screenshot_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            board = project / "spec"
            board.mkdir()
            pubspec = project / "pubspec.yaml"
            pubspec.write_text("name: before\n", encoding="utf-8")
            captured_hash = hashlib.sha256(pubspec.read_bytes()).hexdigest()
            pubspec.write_text("name: after\n", encoding="utf-8")
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(
                    {
                        **VALID_MANIFEST,
                        "project_root": str(project),
                        "runtime_input_hashes": {"pubspec.yaml": captured_hash},
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(
                any("runtime inputs changed" in item["reason"] for item in report["hardFailures"]),
                report,
            )

    def test_launch_command_must_match_captured_device_and_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(
                    {
                        **VALID_MANIFEST,
                        "device_id": "simulator-1",
                        "route": "/approved",
                        "launch_command": [
                            "flutter",
                            "run",
                            "-d",
                            "simulator-2",
                            "--route=/default",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            reasons = " ".join(
                item["reason"]
                for item in json.loads(out.read_text(encoding="utf-8"))["hardFailures"]
            )
            self.assertIn("launch device does not match", reasons)
            self.assertIn("launch route does not match", reasons)

    def test_text_region_real_defect_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "ssim": 0.95,
                        "shapeIssues": [],
                        "textIssues": [
                            {"node": "term-label", "pixelMismatch": 0.51}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("text", report["hardFailures"][0]["category"])
            self.assertEqual("term-label", report["hardFailures"][0]["node"])

    def test_asset_region_real_defect_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "ssim": 0.95,
                        "shapeIssues": [],
                        "assetIssues": [
                            {"node": "back-icon", "pixelMismatch": 0.42}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("asset", report["hardFailures"][0]["category"])
            self.assertEqual("back-icon", report["hardFailures"][0]["node"])

    def test_actual_cannot_be_byte_identical_to_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"same-image")
            (board / "actual.png").write_bytes(b"same-image")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("byte-identical", report["hardFailures"][0]["reason"])

    def test_incomplete_screenshot_provenance_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps({"actual_source": "simulator_screenshot"}),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("evidence", report["hardFailures"][0]["category"])
            self.assertIn("device_id", report["hardFailures"][0]["reason"])

    def test_missing_asset_shape_channel_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": False}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("asset_shape", report["hardFailures"][0]["category"])

    def test_component_inputs_are_derived_from_registry_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            board = project / "spec"
            board.mkdir()
            write_png(board / "reference.png", 255, 255, 255)
            write_png(board / "actual.png", 0, 0, 0)
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(
                    {
                        **VALID_MANIFEST,
                        "shared_components": ["app_header"],
                        "viewport": {"width": 1, "height": 1, "density": 160},
                    }
                ),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeader {}\n", encoding="utf-8")
            contract = project / ".iff/contracts/app_header.json"
            contract.parent.mkdir(parents=True)
            contract.write_text('{"familyId":"app_header"}\n', encoding="utf-8")
            registry = project / ".iff/shared_components.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": hashlib.sha256(widget.read_bytes()).hexdigest(),
                                "contract_path": str(contract),
                                "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                    "--component-registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "widget": hashlib.sha256(widget.read_bytes()).hexdigest(),
                    "contract": hashlib.sha256(contract.read_bytes()).hexdigest(),
                },
                report["componentInputs"]["app_header"],
            )

    def test_shape_issue_becomes_a_hard_visual_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "ssim": 0.98,
                        "shapeIssues": [
                            {
                                "node": "card-background",
                                "diagnostic": "corner geometry differs",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(report["ok"])
            self.assertEqual("shape", report["hardFailures"][0]["category"])
            self.assertEqual("card-background", report["hardFailures"][0]["node"])

    def test_failed_runtime_trace_fidelity_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps(
                    {"ok": False, "assetShapeChecked": True, "byCategory": {"bbox": 1}}
                ),
                encoding="utf-8",
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("render_fidelity", report["hardFailures"][0]["category"])

    def test_non_simulator_actual_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps({**VALID_MANIFEST, "actual_source": "generated_preview"}),
                encoding="utf-8",
            )
            (board / "diff_report.json").write_text(
                json.dumps({"ssim": 1.0, "shapeIssues": []}), encoding="utf-8"
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("evidence", report["hardFailures"][0]["category"])

    def test_viewport_issue_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "reference.png").write_bytes(b"reference")
            (board / "actual.png").write_bytes(b"actual")
            (board / "render_fidelity_report.json").write_text(
                json.dumps({"ok": True, "assetShapeChecked": True}), encoding="utf-8"
            )
            (board / "visual_manifest.json").write_text(
                json.dumps(VALID_MANIFEST), encoding="utf-8"
            )
            (board / "diff_report.json").write_text(
                json.dumps(
                    {
                        "ssim": 1.0,
                        "shapeIssues": [],
                        "viewportIssues": [
                            {
                                "issue": "actual size differs from reference",
                                "reference": [390, 844],
                                "actual": [390, 812],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("viewport", report["hardFailures"][0]["category"])


if __name__ == "__main__":
    unittest.main()
