"""Tests for contract.py — API/interaction extraction."""
import json
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from contract import build_contract

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "contract.py")


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
            "interactions": [{"id": "ix_1", "type": "data", "trigger": "submit"}],
        }
        contract = build_contract(binding)
        self.assertEqual(contract["metrics"]["contract_apis"], 1)
        self.assertEqual(contract["metrics"]["contract_components"], 2)
        self.assertEqual(contract["metrics"]["contract_interactions"], 1)
        self.assertEqual(contract["metrics"]["contract_component_types"]["new"], 2)

    def test_empty(self):
        contract = build_contract({"platform": {}, "apis": [], "components": [], "interactions": []})
        self.assertEqual(contract["metrics"]["contract_apis"], 0)
        self.assertEqual(contract["metrics"]["contract_components"], 0)
        self.assertEqual(contract["metrics"]["contract_interactions"], 0)


class TestInteractionPassthrough(unittest.TestCase):
    def test_stage2_interactions_passed_through(self):
        stage2_ix = [
            {"id": "ix_1", "component": "LoginForm", "type": "data",
             "condition": None, "trigger": "点击发送", "behavior": "loading",
             "result": "发送验证码", "api": "/auth/otp", "triggers": ["ix_2"]},
        ]
        binding = {
            "platform": {}, "apis": [{"endpoint": "/auth/otp", "trigger": "click"}],
            "components": [{"component_name": "LoginForm", "component_type": "new",
                            "group_name": "g", "params": ["onClick"]}],
            "interactions": stage2_ix,
        }
        contract = build_contract(binding)
        self.assertEqual(contract["interactions"], stage2_ix)
        self.assertIn("triggers", contract["interactions"][0])

    def test_empty_interactions_list(self):
        binding = {
            "platform": {}, "apis": [],
            "components": [], "interactions": [],
        }
        contract = build_contract(binding)
        self.assertEqual(contract["interactions"], [])

    def test_absent_interactions_yields_empty(self):
        """No interactions key must not synthesize phantom interactions."""
        binding = {
            "platform": {},
            "apis": [{"semantic_hint": "获取验证码", "resolved": {"path": "/auth/otp"}}],
            "components": [{"component_name": "Login", "component_type": "new",
                            "group_name": "g", "params": ["onClick"]}],
        }
        contract = build_contract(binding)
        self.assertEqual(contract["interactions"], [])
        self.assertEqual(contract["metrics"]["contract_interactions"], 0)

    def test_mock_marking(self):
        """APIs with resolved=None get mock=True."""
        binding = {
            "platform": {}, "interactions": [],
            "apis": [
                {"semantic_hint": "A", "resolved": {"path": "/a"}},
                {"semantic_hint": "B", "resolved": None},
            ],
            "components": [],
        }
        contract = build_contract(binding)
        self.assertNotIn("mock", contract["apis"][0])
        self.assertTrue(contract["apis"][1]["mock"])
        self.assertEqual(contract["metrics"]["contract_apis_resolved"], 1)
        self.assertEqual(contract["metrics"]["contract_apis_mock"], 1)

    def test_type_dist_default_is_new(self):
        """Missing component_type defaults to 'new', not 'unknown'."""
        binding = {
            "platform": {}, "apis": [], "interactions": [],
            "components": [{"component_name": "X", "group_name": "g", "params": []}],
        }
        contract = build_contract(binding)
        self.assertIn("new", contract["metrics"]["contract_component_types"])
        self.assertNotIn("unknown", contract["metrics"]["contract_component_types"])


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
        r = self._run_cli({"platform": {}, "apis": [], "components": [], "interactions": []})
        self.assertNotEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["error"], "stage2_incomplete")

    def test_absent_interactions_accepted(self):
        r = self._run_cli({
            "platform": {"name": "android"},
            "apis": [],
            "components": [{"component_name": "X", "component_type": "new",
                            "group_name": "g", "params": []}],
        })
        self.assertEqual(r.returncode, 0)

    def test_valid_input_accepted(self):
        r = self._run_cli({
            "platform": {"name": "android"},
            "apis": [],
            "components": [{"component_name": "X", "component_type": "new",
                            "group_name": "g", "params": []}],
            "interactions": [],
        })
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
