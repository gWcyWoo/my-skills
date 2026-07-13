from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iff.scripts.verify_pipeline_scripts import build_report


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts/make_worker_prompt.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class WorkerContractTest(unittest.TestCase):
    def test_board_cli_emits_one_bounded_v3_worker_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            spec = project / "spec/home/default"
            spec.mkdir(parents=True)
            row = project / "spec/home/row.json"
            manifest = project / ".iff/features/home.json"
            preflight = project / ".iff/preflight_report.json"
            out = project / "spec/home/.iff/workers/board--default.prompt.md"
            write_json(row, {"title": "home", "design_url": "https://design/1"})
            write_json(
                manifest,
                {
                    "featureId": "home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        }
                    },
                },
            )
            write_json(preflight, build_report(SKILL_DIR))

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--skill-dir",
                    str(SKILL_DIR),
                    "--row-json",
                    str(row),
                    "--spec-dir",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--mode",
                    "board",
                    "--feature-manifest",
                    str(manifest),
                    "--preflight-report",
                    str(preflight),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            prompt = out.read_text(encoding="utf-8")
            self.assertLessEqual(out.stat().st_size, 8192)
            self.assertIn("IFF_WORKER_CONTRACT v3", prompt)
            self.assertIn("read ONLY visual_model_packet.json", prompt)
            self.assertNotIn(f"Read {SKILL_DIR / 'SKILL.md'} completely", prompt)


if __name__ == "__main__":
    unittest.main()
