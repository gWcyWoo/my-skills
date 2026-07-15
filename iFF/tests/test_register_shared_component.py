from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "register_shared_component.py"


class RegisterSharedComponentTest(unittest.TestCase):
    def test_registration_validates_forbidden_dependencies_in_widget_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source_spec = project / "spec"
            source_spec.mkdir()
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text(
                "import 'package:app/features/home/data/home_repository.dart';\n"
                "class AppHeader {}\n",
                encoding="utf-8",
            )
            contract = project / "app_header.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_header",
                        "invariants": {"layout": "header"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": [],
                        "events": ["onBack"],
                        "controlledSlots": [],
                        "forbiddenDependencies": ["repository", "router", "apiDto"],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(project / ".iff/shared_components.json"),
                    "--signature",
                    "componentId:header",
                    "--name",
                    "AppHeader",
                    "--widget-path",
                    "lib/shared/components/app_header.dart",
                    "--project-root",
                    str(project),
                    "--source-spec-dir",
                    str(source_spec),
                    "--component-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("forbidden dependency in source: repository", result.stdout)

    def test_registration_requires_a_component_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_spec = root / "spec"
            source_spec.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(root / "registry.json"),
                    "--signature",
                    "componentId:header",
                    "--name",
                    "AppHeader",
                    "--widget-path",
                    "lib/shared/components/app_header.dart",
                    "--source-spec-dir",
                    str(source_spec),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("--component-contract is required", result.stdout)

    def test_registration_persists_contract_identity_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_spec = root / "spec"
            source_spec.mkdir()
            contract = root / "app_header.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_header",
                        "invariants": {"layout": "header"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": [],
                        "events": ["onBack"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--signature",
                    "componentId:header",
                    "--name",
                    "AppHeader",
                    "--widget-path",
                    "lib/shared/components/app_header.dart",
                    "--source-spec-dir",
                    str(source_spec),
                    "--component-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            doc = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(2, doc["version"])
            entry = doc["components"]["componentId:header"]
            self.assertEqual("app_header", entry["family_id"])
            self.assertEqual(str(contract.resolve()), entry["contract_path"])
            self.assertEqual(
                hashlib.sha256(contract.read_bytes()).hexdigest(),
                entry["contract_sha256"],
            )

    def test_invalid_component_contract_cannot_be_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_spec = root / "spec"
            source_spec.mkdir()
            contract = root / "bad.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "bad_button",
                        "invariants": {"layout": "button"},
                        "variants": ["primary"],
                        "businessInputs": ["label", "backgroundColor"],
                        "uiStateInputs": [],
                        "events": ["onPressed"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(root / "registry.json"),
                    "--signature",
                    "componentId:bad",
                    "--name",
                    "BadButton",
                    "--widget-path",
                    "lib/shared/components/bad_button.dart",
                    "--source-spec-dir",
                    str(source_spec),
                    "--component-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("raw visual override is forbidden: backgroundColor", result.stdout)

    def test_registration_persists_confirmed_cross_file_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_spec = root / "spec"
            source_spec.mkdir()
            contract = root / "app_header.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_header",
                        "invariants": {"layout": "header"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": [],
                        "events": ["onBack"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            role_map = root / "role-map.json"
            role_map.write_text(
                json.dumps(
                    {
                        "nodeRoleNodes": {
                            "container": "canonical-root",
                            "title": "canonical-title",
                        },
                        "aliasRoleIndices": {
                            "struct:copy-a": {"container": 0, "title": 1},
                            "struct:copy-b": {"container": 0, "title": 2},
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
                    "--signature",
                    "componentId:header",
                    "--source-alias",
                    "struct:copy-a",
                    "--source-alias",
                    "struct:copy-b",
                    "--role-map",
                    str(role_map),
                    "--name",
                    "AppHeader",
                    "--widget-path",
                    "lib/shared/components/app_header.dart",
                    "--source-spec-dir",
                    str(source_spec),
                    "--component-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            entry = json.loads(registry.read_text(encoding="utf-8"))["components"]["componentId:header"]
            self.assertEqual(["struct:copy-a", "struct:copy-b"], entry["source_aliases"])
            self.assertEqual(
                {"container": "canonical-root", "title": "canonical-title"},
                entry["node_role_nodes"],
            )
            self.assertEqual(
                {
                    "struct:copy-a": {"container": 0, "title": 1},
                    "struct:copy-b": {"container": 0, "title": 2},
                },
                entry["alias_role_indices"],
            )

    def test_registration_tracks_widget_hash_and_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source_spec = project / "spec"
            source_spec.mkdir()
            widget = project / "lib/shared/components/app_header.dart"
            widget.parent.mkdir(parents=True)
            widget.write_text(
                "class AppHeader {\n"
                "  const AppHeader({required this.title, this.onBack});\n"
                "  final String title;\n"
                "  final void Function()? onBack;\n"
                "}\n",
                encoding="utf-8",
            )
            contract = project / "app_header.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_header",
                        "invariants": {"layout": "header"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": [],
                        "events": ["onBack"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )
            registry = project / ".iff/shared_components.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(registry),
                    "--signature",
                    "componentId:header",
                    "--name",
                    "AppHeader",
                    "--widget-path",
                    "lib/shared/components/app_header.dart",
                    "--project-root",
                    str(project),
                    "--consumer-id",
                    "home/default",
                    "--consumer-visual-gate",
                    "lanhu/specs/home/default/visual_gate_report.json",
                    "--source-spec-dir",
                    str(source_spec),
                    "--component-contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            entry = json.loads(registry.read_text(encoding="utf-8"))["components"]["componentId:header"]
            self.assertEqual(hashlib.sha256(widget.read_bytes()).hexdigest(), entry["widget_source_sha256"])
            self.assertEqual(
                [
                    {
                        "id": "home/default",
                        "visual_gate": "lanhu/specs/home/default/visual_gate_report.json",
                    }
                ],
                entry["consumers"],
            )


if __name__ == "__main__":
    unittest.main()
