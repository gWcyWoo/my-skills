"""Tests for check-codegen DTO coverage check."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate import _snake_to_camel, _extract_response_fields

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "validate.py")


class TestSnakeToCamel(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_snake_to_camel("offer_id"), "offerId")

    def test_multi_part(self):
        self.assertEqual(_snake_to_camel("max_loan_amount"), "maxLoanAmount")

    def test_no_underscore(self):
        self.assertEqual(_snake_to_camel("status"), "status")

    def test_single_char_parts(self):
        self.assertEqual(_snake_to_camel("a_b"), "aB")


class TestExtractResponseFields(unittest.TestCase):
    def test_flat(self):
        schema = {"offer_id": "string", "home_status": "integer"}
        fields = _extract_response_fields(schema)
        camels = {c for _, c in fields}
        self.assertIn("offerId", camels)
        self.assertIn("homeStatus", camels)

    def test_nested_object(self):
        schema = {"user": {"first_name": "string"}}
        fields = _extract_response_fields(schema)
        camels = {c for _, c in fields}
        self.assertIn("user", camels)
        self.assertIn("firstName", camels)

    def test_array(self):
        schema = {"offers": [{"offer_id": "string", "max_amount": "integer"}]}
        fields = _extract_response_fields(schema)
        camels = {c for _, c in fields}
        self.assertIn("offers", camels)
        self.assertIn("offerId", camels)
        self.assertIn("maxAmount", camels)

    def test_returns_both_forms(self):
        schema = {"offer_id": "string"}
        fields = _extract_response_fields(schema)
        self.assertEqual(fields, [("offer_id", "offerId")])


class TestDtoCoverageCheck(unittest.TestCase):
    def _run(self, contract_apis, kotlin_source, expect=0):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "blueprint.json"
            bp.write_text(json.dumps({"components": []}))
            ct = td / "contract.json"
            ct.write_text(json.dumps({"apis": contract_apis, "interactions": []}))
            gd = td / "gen"
            gd.mkdir()
            (gd / "Dto.kt").write_text(kotlin_source)
            r = subprocess.run(
                [sys.executable, SCRIPT, "check-codegen",
                 "--blueprint", str(bp), "--contract", str(ct), "--gen-dir", str(gd),
                 "--platform", "compose"],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, expect, f"rc={r.returncode}\n{r.stdout}")
            return json.loads(r.stdout)

    def test_all_fields_present_passes(self):
        apis = [{"semantic_hint": "/offers", "resolved": {
            "response": {"offer_id": "string", "home_status": "integer"},
        }}]
        source = "data class OffersDto(val offerId: String, val homeStatus: Int)"
        out = self._run(apis, source)
        dto_errs = [e for e in out.get("errors", []) if e["type"] == "missing_dto_field"]
        self.assertEqual(len(dto_errs), 0)

    def test_missing_field_reported(self):
        apis = [{"semantic_hint": "/offers", "resolved": {
            "response": {"offer_id": "string", "home_status": "integer", "max_amount": "integer"},
        }}]
        source = "data class OffersDto(val homeStatus: Int)"
        out = self._run(apis, source, expect=1)
        dto_errs = [e for e in out["errors"] if e["type"] == "missing_dto_field"]
        self.assertEqual(len(dto_errs), 1)
        self.assertIn("offerId", dto_errs[0]["missing"])
        self.assertIn("maxAmount", dto_errs[0]["missing"])

    def test_null_resolved_skipped(self):
        apis = [{"semantic_hint": "/offers", "resolved": None}]
        source = "class Empty"
        out = self._run(apis, source)
        dto_errs = [e for e in out.get("errors", []) if e["type"] == "missing_dto_field"]
        self.assertEqual(len(dto_errs), 0)


if __name__ == "__main__":
    unittest.main()
