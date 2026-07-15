from __future__ import annotations

import unittest

from iFF.scripts.verify_pipeline_scripts import REQUIRED


class VerifyPipelineScriptsTest(unittest.TestCase):
    def test_visual_correctness_pipeline_scripts_are_required(self) -> None:
        expected = {
            "check_visual_board.py",
            "check_component_contract.py",
            "check_shared_component_consumers.py",
            "check_feature_manifest.py",
            "check_visual_feature.py",
            "make_visual_gate_report.py",
            "check_visual_provenance.py",
            "check_state_change_scope.py",
            "make_visual_model_packet.py",
            "make_component_model_packet.py",
        }

        self.assertEqual(set(), expected - set(REQUIRED))

    def test_interaction_accuracy_pipeline_scripts_are_required(self) -> None:
        expected = {
            "check_interaction_contract.py",
            "run_interaction_tests.py",
            "run_interaction_device_tests.py",
            "check_interaction_device_evidence.py",
            "check_interaction_feature.py",
            "make_interaction_model_packet.py",
        }

        self.assertEqual(set(), expected - set(REQUIRED))

    def test_data_accuracy_pipeline_scripts_are_required(self) -> None:
        expected = {
            "check_data_bindings.py",
            "check_data_runtime.py",
            "check_data_coverage.py",
            "run_data_device_tests.py",
            "check_data_device_evidence.py",
            "run_live_api_tests.py",
            "check_live_api_evidence.py",
            "run_data_tests.py",
            "run_feature_tests.py",
            "data_test_cases.py",
            "check_data_evidence.py",
            "merge_feature_data.py",
            "check_data_feature.py",
            "make_data_model_packet.py",
        }

        self.assertEqual(set(), expected - set(REQUIRED))
        self.assertNotIn("make_data_device_evidence.py", REQUIRED)

    def test_token_efficiency_pipeline_scripts_are_required(self) -> None:
        expected = {
            "make_worker_prompt.py",
            "check_worker_compliance.py",
            "make_visual_model_packet.py",
            "make_interaction_model_packet.py",
            "make_data_model_packet.py",
            "check_model_context.py",
        }

        self.assertEqual(set(), expected - set(REQUIRED))


if __name__ == "__main__":
    unittest.main()
