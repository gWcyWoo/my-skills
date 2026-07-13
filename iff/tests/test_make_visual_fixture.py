from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_visual_fixture.py"


class MakeVisualFixtureTest(unittest.TestCase):
    def test_duplicate_state_name_fails_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.slots.json"
            second = root / "second.slots.json"
            out = root / "loan_visual_fixture.dart"
            first.write_text(json.dumps({"amount": "₦10"}), encoding="utf-8")
            second.write_text(json.dumps({"amount": "₦20"}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--feature",
                    "loan",
                    "--slots",
                    f"success={first}",
                    "--slots",
                    f"success={second}",
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("duplicate state: success", result.stdout + result.stderr)
            self.assertFalse(out.exists())

    def test_generated_fixture_records_current_slot_seed_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slots = root / "success.slots.json"
            out = root / "loan_visual_fixture.dart"
            slots.write_text(json.dumps({"amount": "₦10"}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--feature",
                    "loan",
                    "--slots",
                    f"success={slots}",
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            source = Path(str(out) + ".source.json")
            self.assertTrue(source.is_file())
            payload = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(
                hashlib.sha256(slots.read_bytes()).hexdigest(),
                payload["states"]["success"]["sha256"],
            )
            self.assertEqual(1, payload["states"]["success"]["slotCount"])


if __name__ == "__main__":
    unittest.main()
