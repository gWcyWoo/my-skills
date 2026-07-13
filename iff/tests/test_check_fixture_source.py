from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_fixture_source.py"


class CheckFixtureSourceTest(unittest.TestCase):
    def test_runtime_comment_cannot_count_as_fixture_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "lib" / "loan_visual_fixture.dart"
            runtime = root / "lib" / "loan_page.dart"
            test = root / "test" / "loan_page_test.dart"
            fixture.parent.mkdir(parents=True)
            runtime.parent.mkdir(parents=True, exist_ok=True)
            test.parent.mkdir(parents=True)
            fixture.write_text(
                "abstract final class LoanVisualFixture { static const states = {}; }\n",
                encoding="utf-8",
            )
            runtime.write_text(
                "// LoanVisualFixture used by the page\nclass LoanPage {}\n",
                encoding="utf-8",
            )
            test.write_text(
                "import '../lib/loan_visual_fixture.dart';\n"
                "void main() { print(LoanVisualFixture.states); }\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("NOT same-source", result.stdout + result.stderr)

    def test_changed_design_slot_seed_makes_fixture_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "lib" / "loan_visual_fixture.dart"
            runtime = root / "lib" / "loan_page.dart"
            test = root / "test" / "loan_page_test.dart"
            slots = root / "success.slots.json"
            fixture.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            fixture.write_text(
                "abstract final class LoanVisualFixture { static const states = {}; }\n",
                encoding="utf-8",
            )
            runtime.write_text(
                "import 'loan_visual_fixture.dart';\n"
                "final states = LoanVisualFixture.states;\n",
                encoding="utf-8",
            )
            test.write_text(
                "import '../lib/loan_visual_fixture.dart';\n"
                "void main() { print(LoanVisualFixture.states); }\n",
                encoding="utf-8",
            )
            slots.write_text(json.dumps({"amount": "₦10"}), encoding="utf-8")
            Path(str(fixture) + ".source.json").write_text(
                json.dumps(
                    {
                        "states": {
                            "success": {
                                "path": str(slots),
                                "sha256": hashlib.sha256(slots.read_bytes()).hexdigest(),
                                "slotCount": 1,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            slots.write_text(json.dumps({"amount": "₦20"}), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("stale design slot seed: success", result.stdout + result.stderr)

    def test_fixture_without_source_provenance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "lib/loan_visual_fixture.dart"
            runtime = root / "lib/loan_page.dart"
            test = root / "test/loan_page_test.dart"
            fixture.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            fixture.write_text(
                "abstract final class LoanVisualFixture { static const states = {}; }\n",
                encoding="utf-8",
            )
            runtime.write_text(
                "import 'loan_visual_fixture.dart';\n"
                "final states = LoanVisualFixture.states;\n",
                encoding="utf-8",
            )
            test.write_text(
                "import '../lib/loan_visual_fixture.dart';\n"
                "void main() { print(LoanVisualFixture.states); }\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("fixture source provenance missing", result.stdout + result.stderr)

    def test_generated_fixture_modified_after_generation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "lib/loan_visual_fixture.dart"
            runtime = root / "lib/loan_page.dart"
            test = root / "test/loan_page_test.dart"
            slots = root / "success.slots.json"
            fixture.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            fixture.write_text(
                "abstract final class LoanVisualFixture { static const states = {}; }\n",
                encoding="utf-8",
            )
            slots.write_text(json.dumps({"amount": "₦10"}), encoding="utf-8")
            Path(str(fixture) + ".source.json").write_text(
                json.dumps(
                    {
                        "fixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                        "states": {
                            "success": {
                                "path": str(slots),
                                "sha256": hashlib.sha256(slots.read_bytes()).hexdigest(),
                                "slotCount": 1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            runtime.write_text(
                "import 'loan_visual_fixture.dart';\n"
                "final states = LoanVisualFixture.states;\n",
                encoding="utf-8",
            )
            test.write_text(
                "import '../lib/loan_visual_fixture.dart';\n"
                "void main() { print(LoanVisualFixture.states); }\n",
                encoding="utf-8",
            )
            fixture.write_text(fixture.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("fixture differs from generated source", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
