from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_shared_component_consumers.py"


class CheckSharedComponentConsumersTest(unittest.TestCase):
    def test_stale_consumer_board_evidence_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeader {}\n", encoding="utf-8")
            widget_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            board = project / "gates/home"
            board.mkdir(parents=True)
            for name, content in {
                "reference.png": b"reference-v1",
                "actual.png": b"actual",
                "render_fidelity_report.json": b"{}",
                "diff_report.json": b"{}",
                "visual_manifest.json": b"{}",
            }.items():
                (board / name).write_bytes(content)
            gate = board / "visual_gate_report.json"
            gate.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "inputs": {
                            name: hashlib.sha256((board / name).read_bytes()).hexdigest()
                            for name in (
                                "reference.png",
                                "actual.png",
                                "render_fidelity_report.json",
                                "diff_report.json",
                                "visual_manifest.json",
                            )
                        },
                        "componentInputs": {"app_header": widget_hash},
                    }
                ),
                encoding="utf-8",
            )
            (board / "reference.png").write_bytes(b"reference-v2")
            registry = project / ".iff/shared_components.json"
            registry.parent.mkdir()
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": widget_hash,
                                "consumers": [
                                    {
                                        "id": "home/default",
                                        "visual_gate": "gates/home/visual_gate_report.json",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("stale board evidence", result.stdout)

    def test_failed_consumer_visual_gate_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeader {}\n", encoding="utf-8")
            widget_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            gate = project / "gates/home.json"
            gate.parent.mkdir(parents=True)
            gate.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "componentInputs": {"app_header": widget_hash},
                    }
                ),
                encoding="utf-8",
            )
            registry = project / ".iff/shared_components.json"
            registry.parent.mkdir()
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": widget_hash,
                                "consumers": [
                                    {
                                        "id": "home/default",
                                        "visual_gate": "gates/home.json",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("consumer visual gate failed", result.stdout)

    def test_contract_change_invalidates_every_registered_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeader {}\n", encoding="utf-8")
            widget_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            contract = project / ".iff/contracts/app_header.json"
            contract.parent.mkdir(parents=True)
            contract.write_text('{"variants":["standard"]}\n', encoding="utf-8")
            old_contract_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
            home_gate = project / "gates/home.json"
            settings_gate = project / "gates/settings.json"
            home_gate.parent.mkdir(parents=True)
            for gate in (home_gate, settings_gate):
                gate.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "componentInputs": {"app_header": widget_hash},
                        }
                    ),
                    encoding="utf-8",
                )
            registry = project / ".iff/shared_components.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": widget_hash,
                                "contract_path": str(contract),
                                "contract_sha256": old_contract_hash,
                                "consumers": [
                                    {
                                        "id": "home/default",
                                        "visual_gate": "gates/home.json",
                                    },
                                    {
                                        "id": "settings/default",
                                        "visual_gate": "gates/settings.json",
                                    },
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            contract.write_text('{"variants":["standard","compact"]}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("home/default", result.stdout)
            self.assertIn("settings/default", result.stdout)

    def test_widget_change_invalidates_every_registered_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeaderV1 {}\n", encoding="utf-8")
            original_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            registry = project / ".iff/shared_components.json"
            registry.parent.mkdir()
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": original_hash,
                                "consumers": [
                                    {"id": "home/default"},
                                    {"id": "home/approved"},
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            widget.write_text("class AppHeaderV2 {}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("home/default", result.stdout)
            self.assertIn("home/approved", result.stdout)

    def test_consumer_gate_must_reference_current_component_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeaderV2 {}\n", encoding="utf-8")
            current_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            gate = project / "lanhu/specs/home/default/visual_gate_report.json"
            gate.parent.mkdir(parents=True)
            gate.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "componentInputs": {"app_header": "old-hash"},
                    }
                ),
                encoding="utf-8",
            )
            registry = project / ".iff/shared_components.json"
            registry.parent.mkdir()
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": current_hash,
                                "consumers": [
                                    {
                                        "id": "home/default",
                                        "visual_gate": "lanhu/specs/home/default/visual_gate_report.json",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("home/default", result.stdout)
            self.assertIn("consumer visual gate is stale", result.stdout)

    def test_consumer_gate_must_reference_current_contract_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text("class AppHeader {}\n", encoding="utf-8")
            widget_hash = hashlib.sha256(widget.read_bytes()).hexdigest()
            contract = project / ".iff/contracts/app_header.json"
            contract.parent.mkdir(parents=True)
            contract.write_text('{"variants":["standard"]}\n', encoding="utf-8")
            contract_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
            gate = project / "gates/home.json"
            gate.parent.mkdir(parents=True)
            gate.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "componentInputs": {"app_header": widget_hash},
                    }
                ),
                encoding="utf-8",
            )
            registry = project / ".iff/shared_components.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "widget_source_sha256": widget_hash,
                                "contract_path": str(contract),
                                "contract_sha256": contract_hash,
                                "consumers": [
                                    {
                                        "id": "home/default",
                                        "visual_gate": "gates/home.json",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("consumer visual gate is stale", result.stdout)


if __name__ == "__main__":
    unittest.main()
