from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts/verify_pipeline_scripts.py"


class PipelineInventoryTest(unittest.TestCase):
    def test_preflight_requires_the_complete_current_pipeline(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--skill-dir", str(SKILL_DIR)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("ok 88 scripts", result.stdout)

    def test_skill_contains_the_runtime_rules_and_evolution_corpus(self) -> None:
        required = (
            "SCRIPTS_INDEX.md",
            "SELF_IMPROVE.md",
            "implementation_rules.md",
            "test_rules.md",
            "evolution/case_memory.md",
            "evolution/ceilings.md",
            "evolution/regression/0001_full/classification.json",
            "evolution/regression/0001_full/meta.json",
            "evolution/regression/0001_full/render_plan.json",
            "evolution/regression/0002_backonly/classification.json",
            "evolution/regression/0002_backonly/meta.json",
            "evolution/regression/0002_backonly/render_plan.json",
        )

        missing = [relative for relative in required if not (SKILL_DIR / relative).is_file()]
        self.assertEqual([], missing)

    def test_regression_suite_contains_the_source_baseline_and_codex_adapters(self) -> None:
        modules = sorted((SKILL_DIR / "tests").glob("test_*.py"))
        self.assertEqual(64, len(modules))

    def test_skill_exposes_codex_interface_metadata(self) -> None:
        metadata = SKILL_DIR / "agents/openai.yaml"
        self.assertTrue(metadata.is_file())
        text = metadata.read_text(encoding="utf-8")
        self.assertIn('display_name: "iFF"', text)
        self.assertIn("short_description:", text)
        self.assertIn('default_prompt: "Use $iff ', text)
        self.assertIn("active goal", text)

    def test_retired_generic_visual_compilers_are_not_shipped(self) -> None:
        retired = (
            "scripts/export_scene.py",
            "scripts/group_layout.py",
            "scripts/make_layout_contract.py",
        )

        present = [relative for relative in retired if (SKILL_DIR / relative).exists()]
        self.assertEqual([], present)


if __name__ == "__main__":
    unittest.main()
