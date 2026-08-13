from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_component_contract.py"


class CheckComponentContractTest(unittest.TestCase):
    def test_public_source_cannot_expose_raw_visual_override_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "app_button.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_button",
                        "invariants": {"layout": "button"},
                        "variants": ["primary"],
                        "businessInputs": ["label"],
                        "uiStateInputs": ["loading"],
                        "events": ["onPressed"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )
            source = root / "app_button.dart"
            source.write_text(
                "class AppButton {\n"
                "  const AppButton({required this.label, this.loading = false, this.onPressed, this.backgroundColor});\n"
                "  final String label;\n"
                "  final bool loading;\n"
                "  final VoidCallback? onPressed;\n"
                "  final Color? backgroundColor;\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract), "--source", str(source)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("raw visual override type is forbidden: Color backgroundColor", result.stdout)

    def test_declared_component_inputs_must_exist_in_public_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = root / "app_header.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_header",
                        "invariants": {"layout": "header"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": ["loading"],
                        "events": ["onBack"],
                        "controlledSlots": [{"name": "trailing", "allowedRoles": ["action"]}],
                    }
                ),
                encoding="utf-8",
            )
            source = root / "app_header.dart"
            source.write_text(
                "class AppHeader {\n"
                "  const AppHeader({required this.title});\n"
                "  final String title;\n"
                "}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract), "--source", str(source)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("declared uiStateInputs missing from source: loading", result.stdout)
            self.assertIn("declared events missing from source: onBack", result.stdout)
            self.assertIn("declared controlledSlots missing from source: trailing", result.stdout)

    def test_contract_requires_invariants_and_all_variable_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "empty.json"
            contract.write_text(json.dumps({}), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("familyId must be a non-empty string", result.stdout)
            self.assertIn("invariants must be a non-empty object", result.stdout)
            self.assertIn("variants must be a non-empty list", result.stdout)
            self.assertIn("businessInputs must be a list", result.stdout)
            self.assertIn("uiStateInputs must be a list", result.stdout)
            self.assertIn("events must be a list", result.stdout)
            self.assertIn("controlledSlots must be a list", result.stdout)

    def test_raw_visual_style_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "app_button.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_button",
                        "invariants": {"shape": "button"},
                        "variants": ["primary", "danger"],
                        "businessInputs": ["label", "backgroundColor"],
                        "uiStateInputs": ["enabled", "loading"],
                        "events": ["onPressed"],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("raw visual override is forbidden: backgroundColor", result.stdout)

    def test_layout_and_typography_values_cannot_be_business_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "status_panel.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "status_panel",
                        "invariants": {"layout": "status-panel"},
                        "variants": ["empty", "error"],
                        "businessInputs": ["title", "padding", "borderRadius", "fontSize"],
                        "uiStateInputs": [],
                        "events": [],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("raw visual override is forbidden: padding", result.stdout)
            self.assertIn("raw visual override is forbidden: borderRadius", result.stdout)
            self.assertIn("raw visual override is forbidden: fontSize", result.stdout)

    def test_visual_override_aliases_cannot_bypass_the_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "card.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_card",
                        "invariants": {"layout": "card"},
                        "variants": ["standard", "emphasis"],
                        "businessInputs": [
                            "title",
                            "margin",
                            "textStyle",
                            "decoration",
                            "iconColor",
                        ],
                        "uiStateInputs": [],
                        "events": [],
                        "controlledSlots": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("raw visual override is forbidden: margin", result.stdout)
            self.assertIn("raw visual override is forbidden: textStyle", result.stdout)
            self.assertIn("raw visual override is forbidden: decoration", result.stdout)
            self.assertIn("raw visual override is forbidden: iconColor", result.stdout)

    def test_slots_must_be_structurally_constrained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "modal.json"
            contract.write_text(
                json.dumps(
                    {
                        "familyId": "app_modal",
                        "invariants": {"layout": "modal"},
                        "variants": ["standard"],
                        "businessInputs": ["title"],
                        "uiStateInputs": [],
                        "events": ["onClose"],
                        "controlledSlots": ["content", {"name": "footer"}],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("controlled slot must be an object: content", result.stdout)
            self.assertIn("controlled slot footer must declare allowedRoles", result.stdout)

    def test_shared_component_cannot_depend_on_feature_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                        "forbiddenDependencies": ["repository", "router", "apiDto"],
                    }
                ),
                encoding="utf-8",
            )
            source = root / "app_header.dart"
            source.write_text(
                "import 'package:app/features/home/data/home_repository.dart';\n"
                "class AppHeader {}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--contract",
                    str(contract),
                    "--source",
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("forbidden dependency in source: repository", result.stdout)


if __name__ == "__main__":
    unittest.main()
