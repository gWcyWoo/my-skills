from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_state_change_scope.py"


class CheckStateChangeScopeTest(unittest.TestCase):
    def test_state_changes_manifest_validates_every_declared_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "states": {
                            "default": {
                                "canvasPath": "lib/default.dart",
                                "generatedFiles": ["lib/default.dart"],
                            },
                            "approved": {
                                "canvasPath": "lib/approved.dart",
                                "generatedFiles": ["lib/approved.dart"],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            changes = root / "state_changes.json"
            changes.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "states": {
                            "default": ["lib/default.dart"],
                            "approved": ["lib/approved.dart"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--state-changes",
                    str(changes),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_state_changes_manifest_rejects_duplicate_file_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "states": {
                            "default": {
                                "canvasPath": "lib/shared.dart",
                                "generatedFiles": ["lib/shared.dart"],
                            },
                            "approved": {
                                "canvasPath": "lib/shared.dart",
                                "generatedFiles": ["lib/shared.dart"],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            changes = root / "state_changes.json"
            changes.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "states": {
                            "default": ["lib/shared.dart"],
                            "approved": ["lib/shared.dart"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--state-changes",
                    str(changes),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("listed for multiple states", result.stdout + result.stderr)

    def test_state_worker_cannot_change_existing_shared_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "protectedFiles": ["lib/features/home/home_page.dart"],
                        "states": {
                            "default": {
                                "canvasPath": "lib/features/home/default_canvas.dart",
                                "generatedFiles": [
                                    "lib/features/home/default_canvas.dart"
                                ],
                            },
                            "approved": {
                                "canvasPath": "lib/features/home/approved_canvas.dart",
                                "generatedFiles": [
                                    "lib/features/home/approved_canvas.dart",
                                    "test/features/home/approved_canvas_test.dart",
                                ],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            changed = root / "changed-files.txt"
            changed.write_text(
                "lib/features/home/approved_canvas.dart\n"
                "lib/features/home/home_page.dart\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--state",
                    "approved",
                    "--changed-files",
                    str(changed),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("out-of-scope change", result.stdout)
            self.assertIn("lib/features/home/home_page.dart", result.stdout)
            self.assertNotIn("approved_canvas.dart\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
