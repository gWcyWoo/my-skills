from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_visual_manifest.py"


class CheckVisualManifestTest(unittest.TestCase):
    def test_legacy_manifest_without_runtime_binding_fails_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = root / "actual.png"
            actual.write_bytes(b"actual")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "actual_source": "simulator_screenshot",
                        "device_id": "simulator-1",
                        "capture_command": "simctl screenshot",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "actual_path": str(actual),
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("project_root", result.stdout + result.stderr)
            self.assertIn("runtime_input_hashes", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
