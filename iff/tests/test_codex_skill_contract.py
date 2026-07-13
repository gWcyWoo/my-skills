from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iff.scripts.fetch import resolve_cookie


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class CodexSkillContractTest(unittest.TestCase):
    def test_skill_declares_the_current_codex_collaboration_lifecycle(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        for required in (
            "spawn_agent",
            "wait_agent",
            "send_message",
            "followup_task",
            'fork_turns: "none"',
        ):
            self.assertIn(required, text)
        for obsolete in (
            "multi_agent_v1",
            "send_input",
            "close_agent",
        ):
            self.assertNotIn(obsolete, text)

    def test_skill_exposes_the_complete_current_four_domain_pipeline(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        for required in (
            "board-worker",
            "assembly-worker",
            "detect_shared_components.py",
            "make_visual_model_packet.py",
            "make_interaction_model_packet.py",
            "make_data_model_packet.py",
            "check_render_fidelity.py",
            "run_client_device_tests.py",
            "check_done_gate.py",
            "model_context_report.json",
            "~/.agents/skills/iff",
            "AGENTS.md",
        ):
            self.assertIn(required, text)
        self.assertNotIn("~/.claude/skills/iFF", text)
        self.assertNotIn("CLAUDE.md", text)

    def test_runtime_contracts_have_no_claude_specific_operational_dependency(self) -> None:
        paths = [
            SKILL,
            SKILL.parent / "SCRIPTS_INDEX.md",
            SKILL.parent / "SELF_IMPROVE.md",
            SKILL.parent / "implementation_rules.md",
            SKILL.parent / "test_rules.md",
            *(SKILL.parent / "scripts").glob("*.py"),
        ]
        forbidden = (
            "~/.claude/skills/iFF",
            "CLAUDE.md",
            "Claude Code",
            "mcp__apifox-new-mcp__read_project_oas",
        )
        violations = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                if value in text:
                    violations.append(f"{path.relative_to(SKILL.parent)}: {value}")

        self.assertEqual([], violations)

    def test_skill_uses_the_explicit_codex_goal_lifecycle(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        for required in ("get_goal", "create_goal", "update_goal"):
            self.assertIn(required, text)
        self.assertIn("不得从普通 iFF 请求推断或创建 goal", text)
        self.assertIn("check_done_gate.py exit 0", text)

    def test_api_normalizer_fails_loudly_without_binding_to_one_tool_name(self) -> None:
        script = SKILL.parent / "scripts/normalize_api_contract.py"
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "oas.json"
            out = Path(tmp) / "api_contract.json"
            result = subprocess.run(
                [sys.executable, str(script), "--oas", str(missing), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("current environment", result.stdout + result.stderr)
        self.assertNotIn("mcp__", result.stdout + result.stderr)

    def test_api_contract_depends_on_the_available_oas_capability_not_one_transport(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("当前环境实际暴露的 Apifox OAS 工具", text)
        self.assertNotIn("Apifox MCP", text)

    def test_lanhu_cookie_prefers_the_codex_mcp_config_before_the_legacy_claude_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_env = home / ".codex/mcp/lanhu-mcp/.env"
            codex_env.parent.mkdir(parents=True)
            codex_env.write_text('LANHU_COOKIE="codex-cookie"\n', encoding="utf-8")
            claude_env = home / ".claude/mcp/lanhu-mcp/.env"
            claude_env.parent.mkdir(parents=True)
            claude_env.write_text('LANHU_COOKIE="legacy-cookie"\n', encoding="utf-8")
            environment = {key: value for key, value in os.environ.items() if key != "LANHU_COOKIE"}
            environment["HOME"] = str(home)

            with patch.dict(os.environ, environment, clear=True):
                cookie = resolve_cookie(None)

        self.assertEqual("codex-cookie", cookie)


if __name__ == "__main__":
    unittest.main()
