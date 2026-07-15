from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_interaction_wiring.py"


class CheckInteractionWiringTest(unittest.TestCase):
    def test_rules_with_no_project_unit_imported_by_tests_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            tests = root / "test"
            lib.mkdir()
            tests.mkdir()
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (tests / "feature_test.dart").write_text(
                "import 'package:flutter_test/flutter_test.dart';\n",
                encoding="utf-8",
            )
            (root / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            contract = root / "interaction_contract.json"
            contract.write_text(
                json.dumps({"rules": [{"id": "INT-ABC"}]}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--lib-root",
                    str(lib),
                    "--test-root",
                    str(tests),
                    "--entry",
                    str(lib / "main.dart"),
                    "--pubspec",
                    str(root / "pubspec.yaml"),
                    "--contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("no runtime feature unit", result.stdout)


if __name__ == "__main__":
    unittest.main()
