from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_visual_model_packet.py"


class MakeVisualModelPacketTest(unittest.TestCase):
    def test_visual_packet_exposes_only_one_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "artifact_digest.json").write_text(
                json.dumps({"scene": {"nodeCount": 2}}), encoding="utf-8"
            )
            (board / "shared_components.local.json").write_text(
                json.dumps(
                    {
                        "components": [
                            {"signature": "struct:b", "kind": "header", "status": "candidate"},
                            {"signature": "struct:a", "kind": "dialog", "status": "candidate"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("resolve_component_semantics", action["kind"])
            self.assertEqual("struct:a", action["candidate"]["signature"])
            self.assertNotIn("candidates", action)

    def test_visual_packet_exposes_only_one_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "artifact_digest.json").write_text(
                json.dumps({"scene": {"nodeCount": 2}}), encoding="utf-8"
            )
            (board / "visual_gate_report.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "hardFailures": [
                            {"category": "text", "node": "b"},
                            {"category": "viewport", "node": None},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("fix_hard_failure", action["kind"])
            self.assertEqual({"category": "text", "node": "b"}, action["hardFailure"])
            self.assertNotIn("hardFailures", action)

    def test_visual_packet_exposes_only_one_plan_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "artifact_digest.json").write_text(
                json.dumps({"scene": {"nodeCount": 2}}), encoding="utf-8"
            )
            (board / "implementation_plan.json").write_text(
                json.dumps(
                    {
                        "components": {
                            "header": {"family": "__MODEL__"},
                            "footer": {"family": "__MODEL__"},
                        },
                        "modelFields": [
                            {"path": "components.header.family"},
                            {"path": "components.footer.family"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--spec-dir", str(board), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual("fill_plan_judgment", action["kind"])
            self.assertEqual({"path": "components.header.family"}, action["modelField"])
            self.assertNotIn("modelFields", action)

    def test_default_budget_rejects_visual_packet_over_8192_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "artifact_digest.json").write_text(
                json.dumps({"classification": {"currentFact": "x" * 9000}}),
                encoding="utf-8",
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("8192", result.stdout + result.stderr)
            self.assertFalse(out.exists())

    def test_passing_visual_gate_stops_even_when_old_repair_plan_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "artifact_digest.json").write_text(
                json.dumps({"scene": {"nodeCount": 2}}), encoding="utf-8"
            )
            (board / "repair_plan_top.json").write_text(
                json.dumps(
                    {
                        "summary": {"p0Count": 1},
                        "topAction": {"category": "shape_region", "node": "old"},
                    }
                ),
                encoding="utf-8",
            )
            (board / "visual_gate_report.json").write_text(
                json.dumps({"ok": True, "hardFailures": []}), encoding="utf-8"
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                {"kind": "none", "reason": "visual_gate_passed"},
                packet["action"],
            )

    def test_repair_packet_contains_only_digest_and_top_repair_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            (board / "scene.json").write_text(
                json.dumps({"nodes": [{"id": str(i), "payload": "x" * 200} for i in range(500)]}),
                encoding="utf-8",
            )
            (board / "artifact_digest.json").write_text(
                json.dumps(
                    {
                        "classification": {"type": "screen", "states": ["default"]},
                        "scene": {"nodeCount": 500, "textNodes": 20},
                        "renderPlan": {
                            "requiredVisibleNodeCount": 80,
                            "byImplementation": {"text": 20, "shape": 60},
                        },
                        "sharedComponents": [],
                    }
                ),
                encoding="utf-8",
            )
            (board / "repair_plan.json").write_text(
                json.dumps({"actions": [{"payload": "y" * 500} for _ in range(300)]}),
                encoding="utf-8",
            )
            top_action = {
                "category": "shape_region",
                "node": "card",
                "repairAction": "match radius",
            }
            (board / "repair_plan_top.json").write_text(
                json.dumps({"summary": {"p0Count": 1}, "topAction": top_action}),
                encoding="utf-8",
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                    "--max-bytes",
                    "3000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("apply_one_repair", packet["action"]["kind"])
            self.assertEqual(top_action, packet["action"]["topAction"])
            self.assertNotIn("nodes", json.dumps(packet))
            self.assertLess(out.stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
