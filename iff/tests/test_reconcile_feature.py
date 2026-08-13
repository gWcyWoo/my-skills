from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_feature.py"


class ReconcileFeatureTest(unittest.TestCase):
    def test_existing_route_with_new_state_is_a_variant_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            page = project / "lib/features/home/presentation/home_page.dart"
            page.parent.mkdir(parents=True)
            page.write_text("class HomePage {}\n", encoding="utf-8")
            manifests = project / ".iff/features"
            manifests.mkdir(parents=True)
            (manifests / "home.json").write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "route": "/home",
                        "pageWidget": "HomePage",
                        "states": {"default": {"canvasPath": "default_canvas.dart"}},
                    }
                ),
                encoding="utf-8",
            )
            out = project / "reconcile.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--lib-root",
                    str(project / "lib"),
                    "--manifest-root",
                    str(manifests),
                    "--title",
                    "Home approved",
                    "--route-hint",
                    "/home",
                    "--state-hint",
                    "approved",
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            decision = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("home", decision["candidateFeature"])
            self.assertEqual(["default"], decision["existingStates"])
            self.assertEqual("variant:home", decision["recommendedDecision"])
            self.assertEqual("approved", decision["recommendedStateKey"])

    def test_existing_state_is_a_revision_candidate_not_a_new_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            manifests = project / ".iff/features"
            manifests.mkdir(parents=True)
            (manifests / "home.json").write_text(
                json.dumps(
                    {
                        "featureId": "home",
                        "route": "/home",
                        "states": {"default": {"revision": 1}},
                    }
                ),
                encoding="utf-8",
            )
            out = project / "reconcile.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--lib-root",
                    str(project / "lib"),
                    "--manifest-root",
                    str(manifests),
                    "--title",
                    "Home default redesign",
                    "--route-hint",
                    "/home",
                    "--state-hint",
                    "default",
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            decision = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("revision:home:default", decision["recommendedDecision"])


if __name__ == "__main__":
    unittest.main()
