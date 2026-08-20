from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "incident_recovery.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class IncidentRecoveryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.project)], check=True, capture_output=True
        )
        (self.project / "app.kt").write_text("fun app() = 1\n", encoding="utf-8")
        write_json(
            self.project / ".icp" / "component-design" / "state.json",
            {"stage": "component-design", "state": "complete"},
        )
        write_json(self.root / "command.json", ["python3", "tool.py", "compile"])
        (self.root / "stderr.txt").write_text(
            "component lock targets another source bundle\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def record_incident(self) -> dict:
        recorded = self.run_cli(
            "record",
            "--project-root",
            str(self.project),
            "--stage",
            "orchestration",
            "--failed-command",
            str(self.root / "command.json"),
            "--exit-code",
            "2",
            "--error-output",
            str(self.root / "stderr.txt"),
            "--last-checkpoint",
            ".icp/component-design/state.json",
            "--state-file",
            ".icp/component-design/state.json",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        return json.loads(recorded.stdout)

    def recovery_input(self, incident_id: str) -> Path:
        path = self.root / "recovery.json"
        write_json(
            path,
            {
                "schema": "icp.incident.temporary-recovery.v1",
                "incident_id": incident_id,
                "strategy": "Use a semantically identical run-local input without changing frozen evidence.",
                "recovery_data_paths": [
                    f".icp/incidents/{incident_id}/recovery-data/source-bundle.json"
                ],
                "resume_command": ["python3", "tool.py", "compile", "--source-bundle", "snapshot.json"],
                "invariant_checks": [
                    {
                        "name": "canonical source identity preserved",
                        "passed": True,
                        "evidence": "Both source documents have the same canonical digest.",
                    }
                ],
                "limitations": ["The underlying ICP tool defect remains unresolved."],
            },
        )
        return path

    def test_records_incident_then_accepts_only_append_only_icp_recovery_data(self) -> None:
        result = self.record_incident()
        incident_id = result["incident_id"]
        incident_path = self.project / result["incident_file"]
        incident = json.loads(incident_path.read_text(encoding="utf-8"))
        self.assertEqual(incident["status"], "open")
        self.assertIsNone(incident["root_cause"])
        self.assertEqual(incident["failed_command"], ["python3", "tool.py", "compile"])

        recovery_data = (
            self.project
            / ".icp"
            / "incidents"
            / incident_id
            / "recovery-data"
            / "source-bundle.json"
        )
        write_json(recovery_data, {"same": "semantic-input"})
        recovered = self.run_cli(
            "record-recovery",
            "--project-root",
            str(self.project),
            "--incident-id",
            incident_id,
            "--recovery",
            str(self.recovery_input(incident_id)),
        )

        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        recovery = json.loads(
            (
                self.project
                / ".icp"
                / "incidents"
                / incident_id
                / "recovery.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(recovery["status"], "temporarily_recovered")
        pending = self.run_cli("pending", "--project-root", str(self.project))
        self.assertEqual(pending.returncode, 0, pending.stdout + pending.stderr)
        self.assertEqual(json.loads(pending.stdout)["incidents"][0]["incident_id"], incident_id)

    def test_recovery_rejects_changes_outside_icp(self) -> None:
        result = self.record_incident()
        incident_id = result["incident_id"]
        recovery_data = (
            self.project
            / ".icp"
            / "incidents"
            / incident_id
            / "recovery-data"
            / "source-bundle.json"
        )
        write_json(recovery_data, {"same": "semantic-input"})
        (self.project / "app.kt").write_text("fun app() = 2\n", encoding="utf-8")

        rejected = self.run_cli(
            "record-recovery",
            "--project-root",
            str(self.project),
            "--incident-id",
            incident_id,
            "--recovery",
            str(self.recovery_input(incident_id)),
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("outside_icp_workspace_changed", rejected.stderr)

    def test_recovery_rejects_mutation_of_frozen_icp_evidence(self) -> None:
        result = self.record_incident()
        incident_id = result["incident_id"]
        write_json(
            self.project / ".icp" / "component-design" / "state.json",
            {"stage": "component-design", "state": "changed"},
        )

        rejected = self.run_cli(
            "record-recovery",
            "--project-root",
            str(self.project),
            "--incident-id",
            incident_id,
            "--recovery",
            str(self.recovery_input(incident_id)),
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("frozen_icp_evidence_changed", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
