#!/usr/bin/env python3
"""Fail if required iFF deterministic pipeline scripts are missing."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
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
    "check_interaction_contract.py",
    "make_interaction_tests_plan.py",
    "run_interaction_tests.py",
    "run_interaction_device_tests.py",
    "check_interaction_device_evidence.py",
    "check_implementation_plan.py",
    "check_implementation_map.py",
    "copy_assets.py",
    "update_pubspec_assets.py",
    "capture_runtime_screenshot.py",
    "visual_diff.py",
    "make_repair_plan.py",
    "check_visual_manifest.py",
    "check_fixture_source.py",
    "check_render_plan.py",
    "check_interaction_coverage.py",
    "check_interaction_feature.py",
    "make_interaction_model_packet.py",
    "make_worker_prompt.py",
    "check_worker_compliance.py",
    # Track B: component synthesis + interaction wiring + real API integration.
    "reconcile_feature.py",
    "normalize_api_contract.py",
    "make_component_manifest.py",
    "bind_data_slots.py",
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
    "check_model_context.py",
    "check_interaction_wiring.py",
    "check_interaction_completeness.py",
    "check_api_integration.py",
    # Structured per-component render fidelity (replaces golden-vs-golden): trace the REAL
    # render of the keyed online page and diff it against render_plan-derived expectations.
    "gen_layout_trace_test.py",
    "check_render_fidelity.py",
    # Core visible-layer generator + project-rule injection — were missing from the preflight,
    # so a deletion of the single most important script would have gone undetected.
    "generate_canvas.py",
    "sync_project_rules.py",
    # Shared-component reuse: cross-row detection + project registry, so nav
    # headers / bottom tab bars are implemented once and mounted everywhere.
    "detect_shared_components.py",
    "register_shared_component.py",
    "merge_shared_expected.py",
    # Speed/token discipline: device mutex for true-parallel fan-out, artifact digest
    # replacing whole-file reads, machine-prefilled implementation plan.
    "device_lock.py",
    "summarize_spec_artifacts.py",
    "prefill_implementation_plan.py",
    # Visual/interaction/efficiency round 2: deterministic done gate, interaction
    # grounding (board index + anchors), state machine, cross-page flow graph.
    "check_done_gate.py",
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
    "make_board_index.py",
    "model_context_contract.py",
    "run_fetch_pipeline.py",
    "make_implementation_map.py",
    "apply_model_decision.py",
    "run_client_device_tests.py",
    "complete_worker.py",
    "resolve_interaction_anchors.py",
    "make_state_machine.py",
    "update_flow_graph.py",
    "make_journey_map.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def build_report(skill_dir: Path) -> dict:
    scripts_dir = skill_dir.expanduser().resolve() / "scripts"
    local_modules = {path.stem for path in scripts_dir.glob("*.py")}
    entries = []
    failures = []
    inserted = False
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
        inserted = True
    try:
        for name in REQUIRED:
            path = scripts_dir / name
            if not path.is_file() or path.parent != scripts_dir:
                failures.append(f"required script missing or outside scripts dir: {path}")
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as error:
                failures.append(f"script syntax invalid: {path}: {error}")
                continue
            unresolved = []
            for module in sorted(imported_roots(tree)):
                if module in sys.stdlib_module_names or module in local_modules:
                    continue
                try:
                    found = importlib.util.find_spec(module)
                except (ImportError, ModuleNotFoundError, ValueError):
                    found = None
                if found is None:
                    unresolved.append(module)
            if unresolved:
                failures.append(f"script imports unresolved modules: {name}: {', '.join(unresolved)}")
            entries.append(
                {"path": name, "sha256": sha256(path), "unresolvedImports": unresolved}
            )
    finally:
        if inserted:
            sys.path.remove(str(scripts_dir))
    return {
        "version": 2,
        "skillDir": str(skill_dir.expanduser().resolve()),
        "scripts": entries,
        "ok": not failures,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the iff skill directory.",
    )
    parser.add_argument("--out")
    args = parser.parse_args()
    report = build_report(Path(args.skill_dir))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["failures"]:
        print("invalid iff pipeline scripts:", file=sys.stderr)
        for failure in report["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"ok {len(REQUIRED)} scripts in {Path(args.skill_dir).resolve() / 'scripts'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
