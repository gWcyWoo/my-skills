from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts/sync_project_rules.py"


class SyncProjectRulesTest(unittest.TestCase):
    def test_cli_syncs_managed_rules_into_agents_md_and_preserves_project_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            agents.write_text("# Project rules\n\nKeep this.\n", encoding="utf-8")
            rules = root / "implementation_rules.md"
            rules.write_text("# Managed rules\n\nUse the public surface.\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--rules",
                    str(rules),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            written = agents.read_text(encoding="utf-8")
            self.assertIn("# Project rules", written)
            self.assertIn("Keep this.", written)
            self.assertIn("# Managed rules", written)
            self.assertIn("IFF:IMPL-RULES:START", written)
            self.assertIn("IFF:IMPL-RULES:END", written)

    def test_cli_fails_without_changing_agents_md_when_managed_markers_are_unbalanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            original = "Project text\n\n<!-- IFF:IMPL-RULES:START — damaged -->\n"
            agents.write_text(original, encoding="utf-8")
            rules = root / "implementation_rules.md"
            rules.write_text("# Managed rules\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--rules",
                    str(rules),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("unbalanced managed markers", result.stdout + result.stderr)
            self.assertEqual(original, agents.read_text(encoding="utf-8"))

    def test_cli_rejects_a_rewritten_managed_start_marker_without_appending_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            original = (
                "Project text\n\n"
                "<!-- IFF:IMPL-RULES:START — rewritten -->\n"
                "old rules\n"
                "<!-- IFF:IMPL-RULES:END -->\n"
            )
            agents.write_text(original, encoding="utf-8")
            rules = root / "implementation_rules.md"
            rules.write_text("# Managed rules\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--rules",
                    str(rules),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("invalid managed start marker", result.stdout + result.stderr)
            self.assertEqual(original, agents.read_text(encoding="utf-8"))

    def test_cli_rejects_reversed_managed_markers_without_changing_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            original = (
                "<!-- IFF:IMPL-RULES:END -->\n"
                "old rules\n"
                "<!-- IFF:IMPL-RULES:START — generated from iff/implementation_rules.md, "
                "do not edit inside this block -->\n"
            )
            agents.write_text(original, encoding="utf-8")
            rules = root / "implementation_rules.md"
            rules.write_text("# Managed rules\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--rules",
                    str(rules),
                    "--project-root",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("managed markers out of order", result.stdout + result.stderr)
            self.assertEqual(original, agents.read_text(encoding="utf-8"))

    def test_cli_is_idempotent_and_never_changes_claude_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            rules = root / "implementation_rules.md"
            rules.write_text("# Managed rules\n", encoding="utf-8")
            claude = project / "CLAUDE.md"
            claude.write_text("Claude-owned guidance\n", encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPT),
                "--rules",
                str(rules),
                "--project-root",
                str(project),
            ]

            first = subprocess.run(command, capture_output=True, text=True, check=False)
            second = subprocess.run(command, capture_output=True, text=True, check=False)

            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            written = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(1, written.count("IFF:IMPL-RULES:START"))
            self.assertEqual(1, written.count("IFF:IMPL-RULES:END"))
            self.assertEqual("Claude-owned guidance\n", claude.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
