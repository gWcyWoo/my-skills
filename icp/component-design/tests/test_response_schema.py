"""Tests for resolved.response schema validation + auth enum check."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "validate.py")


def _binding(apis):
    return {
        "components": [{"component_name": "X", "group_name": "g", "component_type": "new",
                        "params": [], "source_path": None, "affected": None}],
        "interactions": [],
        "apis": apis,
    }


def run_check(binding, spec=None, expect=0):
    with tempfile.TemporaryDirectory() as td:
        bp = Path(td) / "binding.json"
        bp.write_text(json.dumps(binding))
        argv = [sys.executable, SCRIPT, "check-interactions", "--binding", str(bp)]
        if spec:
            sp = Path(td) / "spec.json"
            sp.write_text(json.dumps(spec))
            argv += ["--component-spec", str(sp)]
        r = subprocess.run(argv, capture_output=True, text=True)
        assert r.returncode == expect, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        return json.loads(r.stdout)


class TestAuthEnum(unittest.TestCase):

    def test_valid_auth_values_pass(self):
        for val in ("public", "bearer", "optional"):
            b = _binding([{"semantic_hint": "/x", "resolved": {"auth": val, "path": "/x", "method": "GET"}}])
            out = run_check(b)
            self.assertTrue(out["ok"], f"auth={val} should pass")

    def test_invalid_auth_rejected(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {"auth": "token", "path": "/x", "method": "GET"}}])
        out = run_check(b, expect=1)
        self.assertEqual(out["errors"][0]["type"], "invalid_auth")

    def test_null_resolved_skipped(self):
        b = _binding([{"semantic_hint": "/x", "resolved": None}])
        out = run_check(b)
        self.assertTrue(out["ok"])


class TestResponseSchema(unittest.TestCase):

    def test_valid_leaf_types(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": {"name": "string", "age": "integer", "score": "number", "active": "boolean"},
        }}])
        out = run_check(b)
        self.assertTrue(out["ok"])

    def test_nested_object_valid(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": {"user": {"name": "string"}},
        }}])
        out = run_check(b)
        self.assertTrue(out["ok"])

    def test_array_valid(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": {"offers": [{"id": "string", "amount": "integer"}]},
        }}])
        out = run_check(b)
        self.assertTrue(out["ok"])

    def test_invalid_leaf_type_rejected(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": {"status": "array"},
        }}])
        out = run_check(b, expect=1)
        self.assertEqual(out["errors"][0]["type"], "invalid_response_schema")

    def test_array_must_have_one_object(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": {"items": ["string"]},
        }}])
        out = run_check(b, expect=1)
        errs = [e for e in out["errors"] if e["type"] == "invalid_response_schema"]
        self.assertTrue(len(errs) > 0)

    def test_response_not_object_rejected(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": "just a string",
        }}])
        out = run_check(b, expect=1)
        self.assertEqual(out["errors"][0]["type"], "invalid_response_schema")

    def test_null_response_ok(self):
        b = _binding([{"semantic_hint": "/x", "resolved": {
            "auth": "public", "path": "/x", "method": "GET",
            "response": None,
        }}])
        out = run_check(b)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
