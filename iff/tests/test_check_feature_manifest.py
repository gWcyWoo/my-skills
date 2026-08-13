from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_feature_manifest.py"


class CheckFeatureManifestTest(unittest.TestCase):
    def test_each_state_declares_canvas_and_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "route": "/home",
                        "states": {"approved": {}},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("approved has no canvasPath", result.stdout)
            self.assertIn("approved generatedFiles must be a non-empty list", result.stdout)

    def test_states_cannot_own_the_same_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "route": "/home",
                        "states": {
                            "default": {
                                "canvasPath": "lib/features/home/default_canvas.dart",
                                "generatedFiles": ["lib/features/home/home_binding.dart"],
                            },
                            "approved": {
                                "canvasPath": "lib/features/home/approved_canvas.dart",
                                "generatedFiles": ["lib/features/home/home_binding.dart"],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("states share generated file", result.stdout)
            self.assertIn("home_binding.dart", result.stdout)

    def test_states_cannot_share_the_same_canvas_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "pagePath": "lib/features/home/home_page.dart",
                        "route": "/home",
                        "states": {
                            "default": {"canvasPath": "lib/features/home/home_canvas.dart"},
                            "approved": {"canvasPath": "lib/features/home/home_canvas.dart"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("states share canvasPath", result.stdout)

    def test_protected_existing_file_cannot_be_worker_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "pagePath": "lib/features/home/home_page.dart",
                        "route": "/home",
                        "states": {
                            "default": {"canvasPath": "lib/features/home/default_canvas.dart"},
                            "approved": {"canvasPath": "lib/features/home/approved_canvas.dart"},
                        },
                        "protectedFiles": ["lib/features/home/home_page.dart"],
                        "generatedFiles": ["lib/features/home/home_page.dart"],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("file is both protected and generated", result.stdout)

    def test_state_worker_cannot_own_a_protected_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "home.json"
            manifest.write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "route": "/home",
                        "states": {
                            "approved": {
                                "canvasPath": "lib/features/home/approved_canvas.dart",
                                "generatedFiles": ["lib/features/home/home_page.dart"],
                            }
                        },
                        "protectedFiles": ["lib/features/home/home_page.dart"],
                        "generatedFiles": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("approved generates protected file", result.stdout)

    def test_two_features_cannot_claim_the_same_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for feature in ("home", "duplicate_home"):
                (root / f"{feature}.json").write_text(
                    json.dumps(
                        {
                            "featureId": feature,
                            "route": "/home",
                            "states": {
                                "default": {"canvasPath": f"lib/{feature}_canvas.dart"},
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("route /home is claimed by multiple features", result.stdout)


if __name__ == "__main__":
    unittest.main()
