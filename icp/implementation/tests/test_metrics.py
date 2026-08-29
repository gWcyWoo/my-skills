"""Tests for metrics.py — step extraction logic."""
import json
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from metrics import (
    extract_step6,
    extract_step7,
    extract_step8,
    extract_step9,
)

import tempfile


class _WorkDirMixin:
    def _write(self, td, name, data):
        p = Path(td) / name
        p.write_text(json.dumps(data))


class TestExtractStep6(_WorkDirMixin, unittest.TestCase):
    def test_gate_included(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "struct-diff.json", {
                "metrics": {"struct_texts_matched": 5},
                "gate": {"ok": True, "coverage": 0.9},
            })
            r = extract_step6(Path(td))
            self.assertEqual(r["gate"]["ok"], True)
            self.assertEqual(r["struct_texts_matched"], 5)

    def test_no_gate_key(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "struct-diff.json", {
                "metrics": {"struct_texts_matched": 3},
            })
            r = extract_step6(Path(td))
            self.assertNotIn("gate", r)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = extract_step6(Path(td))
            self.assertEqual(r["status"], "missing")


class TestExtractStep7(_WorkDirMixin, unittest.TestCase):
    def test_field_names(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "visual-diff.json", {
                "pass": True,
                "issues_remaining": [{"id": 1}],
            })
            r = extract_step7(Path(td))
            self.assertTrue(r["visual_pass"])
            self.assertEqual(len(r["visual_issues"]), 1)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = extract_step7(Path(td))
            self.assertEqual(r["status"], "not_run")


class TestExtractStep8(_WorkDirMixin, unittest.TestCase):
    def test_unique_rounds(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "attribution-ledger.json", [
                {"round": 1, "attribution": "codegen"},
                {"round": 1, "attribution": "codegen"},
                {"round": 2, "attribution": "environment"},
            ])
            r = extract_step8(Path(td))
            self.assertEqual(r["total_rounds"], 2)
            self.assertEqual(r["attributions"]["codegen"], 2)
            self.assertEqual(r["attributions"]["environment"], 1)

    def test_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "attribution-ledger.json", [])
            r = extract_step8(Path(td))
            self.assertEqual(r["status"], "no_fixes_needed")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = extract_step8(Path(td))
            self.assertEqual(r["status"], "not_run")


class TestExtractStep9(_WorkDirMixin, unittest.TestCase):
    def test_positive_negative_restructure(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "behavior-result.json", {
                "behavior_total": 10,
                "positive": {"total": 6, "passed": 5},
                "negative": {"total": 4, "passed": 3},
                "quality_check": {"rewrites": 2},
                "mock_violations": [{"file": "x.kt"}],
            })
            self._write(td, "api-contract.json", {
                "metrics": {"contract_interactions": 8},
            })
            r = extract_step9(Path(td))
            self.assertEqual(r["behavior_total"], 10)
            self.assertEqual(r["positive_total"], 6)
            self.assertEqual(r["positive_passed"], 5)
            self.assertEqual(r["negative_total"], 4)
            self.assertEqual(r["negative_passed"], 3)
            self.assertEqual(r["mock_violations"], 1)
            self.assertEqual(r["quality_rewrites"], 2)
            self.assertEqual(r["interaction_gap"], 2)

    def test_interaction_gap_zero_when_no_contract_interactions(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "behavior-result.json", {
                "behavior_total": 3,
                "positive": {"total": 2, "passed": 2},
                "negative": {"total": 1, "passed": 1},
            })
            self._write(td, "api-contract.json", {
                "metrics": {"contract_interactions": 0},
            })
            r = extract_step9(Path(td))
            self.assertEqual(r["interaction_gap"], 0)

    def test_missing_contract_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "behavior-result.json", {
                "behavior_total": 1,
                "positive": {"total": 1, "passed": 1},
                "negative": {"total": 0, "passed": 0},
            })
            r = extract_step9(Path(td))
            self.assertEqual(r["interaction_gap"], 0)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = extract_step9(Path(td))
            self.assertEqual(r["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
