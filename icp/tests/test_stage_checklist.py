from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from icp.scripts.stage_checklist import (
    ChecklistError,
    complete,
    create,
    node,
    require_complete,
)


class StageChecklistTest(unittest.TestCase):
    def test_changed_upstream_evidence_rewinds_every_dependent_node_and_resumes_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checklist.json"
            nodes = [
                node("begin", "Begin the stage."),
                node("derive", "Derive stage data.", ["begin"]),
                node("verify", "Verify stage data.", ["derive"]),
            ]
            create(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                initially_completed=["begin"],
            )
            complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                node_id="derive",
                evidence_sha256="b" * 64,
            )
            complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                node_id="verify",
                evidence_sha256="c" * 64,
            )
            require_complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
            )

            complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                node_id="derive",
                evidence_sha256="d" * 64,
            )

            with self.assertRaises(ChecklistError) as failure:
                require_complete(
                    path,
                    stage="fixture",
                    input_sha256="a" * 64,
                    nodes=nodes,
                )
            self.assertEqual(failure.exception.code, "checklist_incomplete")
            self.assertIn("resume_from_node=verify", failure.exception.message)
            self.assertIn("revalidate_nodes=verify", failure.exception.message)

            complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                node_id="verify",
                evidence_sha256="e" * 64,
            )
            checklist = require_complete(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
            )
            self.assertTrue(
                all(item["status"] == "completed" for item in checklist["nodes"])
            )

    def test_completion_cannot_skip_a_required_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checklist.json"
            nodes = [
                node("begin", "Begin the stage."),
                node("derive", "Derive stage data.", ["begin"]),
                node("verify", "Verify stage data.", ["derive"]),
            ]
            create(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                initially_completed=["begin"],
            )

            with self.assertRaises(ChecklistError) as failure:
                complete(
                    path,
                    stage="fixture",
                    input_sha256="a" * 64,
                    nodes=nodes,
                    node_id="verify",
                    evidence_sha256="b" * 64,
                )
            self.assertEqual(failure.exception.code, "checklist_incomplete")
            self.assertIn("resume_from_node=derive", failure.exception.message)

    def test_end_validation_rejects_a_node_marked_complete_without_execution_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checklist.json"
            nodes = [
                node("begin", "Begin the stage."),
                node("verify", "Verify the stage.", ["begin"]),
            ]
            create(
                path,
                stage="fixture",
                input_sha256="a" * 64,
                nodes=nodes,
                initially_completed=["begin"],
            )
            # Simulate a buggy executor that updates the summary status but skips
            # the required per-step execution record.
            inconsistent = json.loads(path.read_text(encoding="utf-8"))
            inconsistent["nodes"][1]["status"] = "completed"
            inconsistent["nodes"][1]["evidence_sha256"] = "b" * 64
            path.write_text(json.dumps(inconsistent), encoding="utf-8")

            with self.assertRaises(ChecklistError) as failure:
                require_complete(
                    path,
                    stage="fixture",
                    input_sha256="a" * 64,
                    nodes=nodes,
                )
            self.assertEqual(failure.exception.code, "checklist_drift")


if __name__ == "__main__":
    unittest.main()
