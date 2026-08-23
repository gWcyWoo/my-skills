"""Tests for contract.py — API/interaction extraction."""
import json
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from contract import extract_interactions, build_contract

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "contract.py")


class TestExtractInteractions(unittest.TestCase):
    def test_api_call(self):
        binding = {"apis": [{"endpoint": "/pay", "trigger": "click button"}], "components": []}
        result = extract_interactions(binding)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "api_call")
        self.assertEqual(result[0]["endpoint"], "/pay")

    def test_navigation(self):
        binding = {
            "apis": [],
            "components": [{"component_name": "HomeScreen", "params": ["navController"]}],
        }
        result = extract_interactions(binding)
        self.assertTrue(any(i["type"] == "navigation" for i in result))

    def test_callback(self):
        binding = {
            "apis": [],
            "components": [{"component_name": "PayButton", "params": ["onClick", "enabled"]}],
        }
        result = extract_interactions(binding)
        callbacks = [i for i in result if i["type"] == "callback"]
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0]["param"], "onClick")

    def test_no_callback_for_lowercase(self):
        binding = {
            "apis": [],
            "components": [{"component_name": "Card", "params": ["amount", "title"]}],
        }
        result = extract_interactions(binding)
        self.assertEqual(len(result), 0)


class TestBuildContract(unittest.TestCase):
    def test_full(self):
        binding = {
            "platform": {"name": "android", "framework": "compose"},
            "apis": [{"endpoint": "/feedback", "trigger": "submit"}],
            "components": [
                {"component_name": "FeedbackScreen", "component_type": "new", "group_name": "root",
                 "params": ["navController"], "source_path": None, "affected": None},
                {"component_name": "SubmitButton", "component_type": "new", "group_name": "submit",
                 "params": ["onClick", "enabled"], "source_path": None, "affected": None},
            ],
        }
        contract = build_contract(binding)
        self.assertEqual(contract["metrics"]["contract_apis"], 1)
        self.assertEqual(contract["metrics"]["contract_components"], 2)
        self.assertGreaterEqual(contract["metrics"]["contract_interactions"], 2)
        self.assertEqual(contract["metrics"]["contract_component_types"]["new"], 2)

    def test_empty(self):
        contract = build_contract({"platform": {}, "apis": [], "components": []})
        self.assertEqual(contract["metrics"]["contract_apis"], 0)
        self.assertEqual(contract["metrics"]["contract_components"], 0)


class TestGateStage2Incomplete(unittest.TestCase):
    def _run_cli(self, binding_data):
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "binding.json"
            bp.write_text(json.dumps(binding_data))
            out = Path(td) / "contract.json"
            r = subprocess.run(
                [sys.executable, SCRIPT, "--binding", str(bp), "--output", str(out)],
                capture_output=True, text=True,
            )
            return r

    def test_stub_rejected(self):
        r = self._run_cli({"page": "首页", "route": "home", "components_bound": True})
        self.assertNotEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["error"], "stage2_incomplete")

    def test_empty_components_rejected(self):
        r = self._run_cli({"platform": {}, "apis": [], "components": []})
        self.assertNotEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["error"], "stage2_incomplete")

    def test_valid_input_accepted(self):
        r = self._run_cli({
            "platform": {"name": "android"},
            "apis": [],
            "components": [{"component_name": "X", "component_type": "new",
                            "group_name": "g", "params": []}],
        })
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
