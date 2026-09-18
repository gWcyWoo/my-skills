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


_DEFAULT_SPEC = {"components": [{"name": "g", "role": "content", "members": []}]}


def run_check(binding, spec=None, expect=0):
    with tempfile.TemporaryDirectory() as td:
        bp = Path(td) / "binding.json"
        bp.write_text(json.dumps(binding))
        sp = Path(td) / "spec.json"
        sp.write_text(json.dumps(spec or _DEFAULT_SPEC))
        argv = [sys.executable, SCRIPT, "check-interactions", "--binding", str(bp),
                "--component-spec", str(sp)]
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

    def test_primitive_array_types_survive_validation_and_contract_cli(self):
        # Formal item schemas must survive the public Stage 2 -> Stage 3 path;
        # projecting integer IDs to [{}] would silently change the wire type.
        contract_script = Path(SCRIPT).parents[2] / "implementation/scripts/contract.py"
        for item_type in ("integer", "string", "number", "boolean"):
            with self.subTest(item_type=item_type), tempfile.TemporaryDirectory() as td:
                response = {
                    "ids": [item_type],
                    "details": {"must_ids": [item_type]},
                    "rows": [{"option_ids": [item_type]}],
                }
                b = _binding([{"semantic_hint": "/x", "resolved": {
                    "auth": "public", "path": "/x", "method": "GET",
                    "response": response,
                }}])
                bp, sp, cp = (Path(td) / name for name in
                              ("binding.json", "spec.json", "contract.json"))
                bp.write_text(json.dumps(b))
                original = bp.read_bytes()
                sp.write_text(json.dumps(_DEFAULT_SPEC))
                check = subprocess.run(
                    [sys.executable, SCRIPT, "check-interactions", "--binding", str(bp),
                     "--component-spec", str(sp)], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertTrue(json.loads(check.stdout)["ok"])
                export = subprocess.run(
                    [sys.executable, str(contract_script), "--binding", str(bp),
                     "--output", str(cp)], capture_output=True, text=True)
                self.assertEqual(export.returncode, 0, export.stdout + export.stderr)
                self.assertEqual(json.loads(cp.read_text())["apis"][0]["resolved"]["response"], response)
                self.assertEqual(bp.read_bytes(), original)

    def test_invalid_array_descriptors_remain_rejected(self):
        for descriptor in ([], [{}, {}], ["integer", "string"], ["array"],
                           ["unknown"], [1], [True], [None], [{"ids": ["unknown"]}]):
            with self.subTest(descriptor=descriptor):
                b = _binding([{"semantic_hint": "/x", "resolved": {
                    "auth": "public", "path": "/x", "method": "GET",
                    "response": {"details": {"items": descriptor}},
                }}])
                out = run_check(b, expect=1)
                self.assertFalse(out["ok"])
                self.assertEqual(len(out["errors"]), 1)
                error = out["errors"][0]
                self.assertEqual(error["type"], "invalid_response_schema")
                self.assertEqual(error["api"], "/x")
                self.assertEqual(error["field"], "details.items[].ids" if
                                 descriptor == [{"ids": ["unknown"]}] else "details.items")

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
