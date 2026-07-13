from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_component_model_packet.py"


class MakeComponentModelPacketTest(unittest.TestCase):
    def test_packet_contains_exactly_one_candidate_with_variation_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch.json"
            batch.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "signature": "struct:b",
                                "kind": "header",
                                "status": "candidate",
                                "variations": [{"index": 1, "fields": {"text": ["A", "B"]}}],
                                "rows": [{"spec_dir": "/b", "group_name": "Header B", "bbox": [0, 0, 320, 56]}],
                                "related_signatures": ["struct:a"],
                            },
                            {
                                "signature": "struct:a",
                                "kind": "dialog",
                                "status": "candidate",
                                "variations": [{"index": 2, "fields": {"text": ["Cancel", "Delete"]}}],
                                "rows": [{"spec_dir": "/a", "group_name": "Confirm", "bbox": [20, 80, 280, 200]}],
                                "related_signatures": ["struct:b"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            facts = root / "business.json"
            facts.write_text(json.dumps({"feature": "account", "state": "delete"}), encoding="utf-8")
            out = root / "packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--batch",
                    str(batch),
                    "--business-facts",
                    str(facts),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            packet = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("resolve_component_semantics", packet["action"]["kind"])
            self.assertEqual("struct:a", packet["action"]["candidate"]["signature"])
            self.assertNotIn("candidates", packet["action"])
            self.assertEqual(
                [{"signature": "struct:b", "kind": "header", "groupNames": ["Header B"]}],
                packet["action"]["candidate"]["relatedCandidates"],
            )
            self.assertEqual({"feature": "account", "state": "delete"}, packet["businessFacts"])
            self.assertLessEqual(out.stat().st_size, 8192)


if __name__ == "__main__":
    unittest.main()
