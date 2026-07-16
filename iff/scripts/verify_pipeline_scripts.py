#!/usr/bin/env python3
"""Fail if required iFF deterministic pipeline scripts are missing."""

from __future__ import annotations

import argparse
from pathlib import Path

from validate_skill_structure import validate_skill
import sys


REQUIRED = [
    "classify_design.py",
    "fetch.py",
    "write.py",
    "download_cover.py",
    "export_figma_scene.py",
    "export_tokens.py",
    "export_assets_manifest.py",
    "check_figma_scene.py",
    "check_design_artifacts.py",
    "group_figma_layout.py",
    "make_figma_layout_contract.py",
    "make_render_plan.py",
    "make_visual_fixture.py",
    "parse_interactions.py",
    "make_interaction_tests_plan.py",
    "check_implementation_plan.py",
    "check_implementation_map.py",
    "make_implementation_map.py",
    "copy_assets.py",
    "update_pubspec_assets.py",
    "prepare_assembly_packaging.py",
    "assembly_tdd_guard.py",
    "capture_runtime_screenshot.py",
    "check_capture_readiness.py",
    "select_runtime_device.py",
    "physical_device_preview.py",
    "validate_skill_structure.py",
    "visual_diff.py",
    "make_repair_plan.py",
    "visual_repair_budget.py",
    "check_visual_manifest.py",
    "check_fixture_source.py",
    "check_render_plan.py",
    "check_interaction_coverage.py",
    "selftest_check_interaction_coverage_adoption.py",
    "check_contract_artifacts.py",
    "make_worker_prompt.py",
    "selftest_contract_artifacts_gate.py",
    "selftest_contract_worker_anchor_gate.py",
    "make_shared_component_jobs.py",
    "prepare_shared_component_assets.py",
    "retire_stale_flutter_template_tests.py",
    "selftest_shared_component_pipeline.py",
    "check_worker_compliance.py",
    # Track B: component synthesis + interaction wiring + real API integration.
    "reconcile_feature.py",
    "oas_ref_resource_cache.py",
    "selftest_oas_ref_resource_cache.py",
    "normalize_api_contract.py",
    "selftest_normalize_api_contract.py",
    "scope_api_contract.py",
    "selftest_feature_api_contract.py",
    "selftest_api_integration.py",
    "make_component_manifest.py",
    "bind_data_slots.py",
    "check_interaction_wiring.py",
    "check_interaction_completeness.py",
    "promote_interaction_rules.py",
    "selftest_interaction_contract_convergence.py",
    "selftest_interaction_source_provenance.py",
    "check_api_integration.py",
    # Structured per-component render fidelity (replaces golden-vs-golden): trace the REAL
    # render of the keyed online page and diff it against render_plan-derived expectations.
    "gen_layout_trace_test.py",
    "layout_trace_contract.py",
    "dynamic_content_contract.py",
    "check_render_fidelity.py",
    "selftest_render_fidelity_api_dynamic_content.py",
    "selftest_visual_diff_api_dynamic_content.py",
    "selftest_visual_diff_asset_descendant_mask.py",
    "selftest_render_fidelity_asset_real_defect.py",
    "selftest_layout_trace_expected_contract.py",
    "selftest_merge_shared_expected_strict.py",
    "check_responsive_layout.py",
    "selftest_responsive_layout_contract.py",
    "selftest_component_bbox_adaptation.py",
    "selftest_generate_canvas_text_layout.py",
    # Core visible-layer generator + project-rule injection — were missing from the preflight,
    # so a deletion of the single most important script would have gone undetected.
    "generate_canvas.py",
    "sync_project_rules.py",
    # Shared-component reuse: cross-row detection + project registry, so nav
    # headers / bottom tab bars are implemented once and mounted everywhere.
    "detect_shared_components.py",
    "register_shared_component.py",
    "generate_shared_component_test.py",
    "merge_shared_expected.py",
    # Speed/token discipline: device mutex for true-parallel fan-out, artifact digest
    # replacing whole-file reads, machine-prefilled implementation plan.
    "device_lock.py",
    "summarize_spec_artifacts.py",
    "prefill_implementation_plan.py",
    "assembly_plan_batch.py",
    "assembly_completion.py",
    "assembly_worker_supervisor.py",
    "shared_worker_supervisor.py",
    "selftest_assembly_bounded_context.py",
    "selftest_assembly_completion_evidence.py",
    "selftest_assembly_worker_supervisor.py",
    "selftest_runtime_device_fallback.py",
    "selftest_capture_readiness.py",
    "selftest_capture_frame_stability.py",
    "selftest_assembly_runtime_device_contract.py",
    "selftest_shared_worker_supervisor.py",
    "selftest_assembly_plan_batch_apply.py",
    "selftest_assembly_plan_cli_contract.py",
    "selftest_assembly_worker_board_audits.py",
    # Visual/interaction/efficiency round 2: deterministic done gate, interaction
    # grounding (board index + anchors), state machine, cross-page flow graph.
    "check_done_gate.py",
    "selftest_check_done_gate_real_defect_scope.py",
    "selftest_check_done_gate_adoption.py",
    "make_board_index.py",
    "resolve_interaction_anchors.py",
    "make_state_machine.py",
    "update_flow_graph.py",
    "make_journey_map.py",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the iff skill directory.",
    )
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    scripts_dir = skill_dir / "scripts"
    missing = [name for name in REQUIRED if not (scripts_dir / name).is_file()]
    outside = [path for path in scripts_dir.glob("*.py") if path.parent != scripts_dir]

    if missing:
        print("missing required iff scripts:", file=sys.stderr)
        for name in missing:
            print(f"- {scripts_dir / name}", file=sys.stderr)
    if outside:
        print("unexpected script path outside iff/scripts:", file=sys.stderr)
        for path in outside:
            print(f"- {path}", file=sys.stderr)
    if missing or outside:
        return 1

    structure_errors = validate_skill(skill_dir)
    if structure_errors:
        print("invalid iff skill structure:", file=sys.stderr)
        for error in structure_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"ok {len(REQUIRED)} scripts in {scripts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
