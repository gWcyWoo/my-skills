from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iff.scripts.model_context_contract import render_contract
from iff.tests.model_context_fixture import prepare_v3_context, run_script, write_json


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "check_model_context.py"


def prepare_context(root: Path) -> tuple[Path, Path, Path]:
    project, spec, out, _ = prepare_v3_context(root)
    return project, spec, out


def run_check(project: Path, spec: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skill-dir",
            str(SKILL_DIR),
            "--spec-root",
            str(spec),
            "--project-root",
            str(project),
            "--feature-manifest",
            str(project / ".iff/features/home.json"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def regenerate_receipt(project: Path, spec: Path, worker_id: str) -> None:
    workers = spec / ".iff/workers"
    result = run_script(
        "complete_worker.py",
        "--skill-dir",
        SKILL_DIR,
        "--feature-manifest",
        project / ".iff/features/home.json",
        "--contract-input",
        workers / f"{worker_id}.contract.json",
        "--result",
        workers / f"{worker_id}.result.json",
        "--out",
        workers / f"{worker_id}.receipt.json",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


class CheckModelContextTest(unittest.TestCase):
    def test_current_bounded_context_passes_and_reports_total_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))

            result = run_check(project, spec, out)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(6, len(report["modelFiles"]))
            self.assertEqual(
                sum(item["bytes"] for item in report["modelFiles"]),
                report["currentRetainedInputBytes"],
            )
            self.assertTrue(all(item["bytes"] <= 8192 for item in report["modelFiles"]))
            rule_bytes = sum(
                (SKILL_DIR / name).stat().st_size
                for name in ("SKILL.md", "test_rules.md", "implementation_rules.md")
            )
            self.assertEqual(2 * rule_bytes, report["avoidedRepeatedRuleBytes"])
            self.assertEqual(
                report["generatedInputBytes"] + report["avoidedRepeatedRuleBytes"],
                report["controlledBaselineBytes"],
            )
            self.assertTrue(report["unmeasuredChannels"])

    def test_packet_with_multiple_actions_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            packet = spec / "data_model_packet.json"
            value = json.loads(packet.read_text(encoding="utf-8"))
            value["actions"] = [{"kind": "second_action"}]
            write_json(packet, value)

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("exactly one action", result.stdout + result.stderr)

    def test_prompt_that_requires_full_rule_reads_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            workers = spec / ".iff/workers"
            contract_path = workers / "board--default.contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["body"] += f"\nRead {SKILL_DIR / 'SKILL.md'} completely\n"
            write_json(contract_path, contract)
            (workers / "board--default.prompt.md").write_bytes(render_contract(contract))
            regenerate_receipt(project, spec, "board--default")

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("forbidden full rule read", result.stdout + result.stderr)

    def test_prompt_that_requires_full_implementation_rules_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            workers = spec / ".iff/workers"
            contract_path = workers / "board--default.contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["body"] += (
                f"\nRead {SKILL_DIR / 'implementation_rules.md'} completely\n"
            )
            write_json(contract_path, contract)
            (workers / "board--default.prompt.md").write_bytes(render_contract(contract))
            regenerate_receipt(project, spec, "board--default")

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("forbidden full rule read", result.stdout + result.stderr)

    def test_missing_rule_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            contract = spec / ".iff/workers/board--default.contract.json"
            value = json.loads(contract.read_text(encoding="utf-8"))
            value["fingerprints"].pop("skill_md_sha256")
            write_json(contract, value)
            (spec / ".iff/workers/board--default.prompt.md").write_bytes(
                render_contract(value)
            )

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("skill_md_sha256", result.stdout + result.stderr)

    def test_changed_packet_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            write_json(spec / "default/artifact_digest.json", {"changed": True})

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("source stale", result.stdout + result.stderr)

    def test_hand_expanded_packet_over_budget_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out = prepare_context(Path(tmp))
            packet = spec / "data_model_packet.json"
            value = json.loads(packet.read_text(encoding="utf-8"))
            value["padding"] = "x" * 9000
            write_json(packet, value)

            result = run_check(project, spec, out)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("exceeds 8192 bytes", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
