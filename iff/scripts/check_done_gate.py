#!/usr/bin/env python3
"""The ONE deterministic gate that must pass before a sheet row is written done.

Run 1 exposed the enforcement gap this closes: wiring_report said ok=false and
per-state pixel diffs never ran, yet the row was marked done by hand. Every
check below is a file-level fact — the orchestrator's judgment is not part of
the gate.

Checks (per feature spec root, i.e. lanhu/specs/<feature>/ with one subdir per
design board):
  boards   every board dir has: render_fidelity report (ok=true AND
           assetShapeChecked=true), artifact_digest.json,
           shared_components.local.json with NO status=missing entry.
  plan     an implementation_plan.json exists under the spec root (board- or
           feature-level), machine-prefilled, zero __MODEL__ leftovers.
  interaction a current interaction_gate_report whose contract/source/state/anchor/plan,
              case-level Flutter machine red/green, public-UI coverage, source wiring, and
              cross-page flow are recomputed before done; report `ok` is never trusted alone.
  tdd/wiring legacy aggregate evidence remains required in addition to the recomputed gate.
  api      api_integration_report.json missing==[].
  pixels   a diff_report.json exists (final state, pixel diagnostics are
           mandatory evidence even though thresholds are diagnostic-only);
           flat-region REAL defects gate: assetIssues pixelMismatch > --asset-tol
           or textIssues pixelMismatch > --text-tol fail (wrong glyph / clipped
           text — the "davs" class that bbox/color fidelity cannot see).
  manifest a visual_manifest.json with actual_source=simulator_screenshot.
  context  worker compliance and model_context_report are recomputed against
           current role contracts, rule/source hashes, byte limits and actions.
"""

from __future__ import annotations

import argparse
import glob as globmod
import json
from pathlib import Path

from common import load_json
from check_visual_board import validate_board
from check_visual_feature import validate_feature
from check_state_change_scope import validate_state_change_scope, validate_state_changes
from check_feature_manifest import validate_manifest
from check_interaction_feature import validate_interaction_feature
from check_data_feature import validate_data_feature
from check_model_context import build_report as build_model_context_report
from check_visual_provenance import validate_visual_provenance


def find_one(root: Path, pattern: str) -> Path | None:
    hits = sorted(root.rglob(pattern))
    return hits[0] if hits else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True, help="lanhu/specs/<feature>")
    parser.add_argument("--asset-tol", type=float, default=0.10)
    parser.add_argument("--text-tol", type=float, default=0.30)
    parser.add_argument("--feature-manifest")
    parser.add_argument("--state-key")
    parser.add_argument("--changed-files")
    parser.add_argument("--state-changes")
    parser.add_argument("--out")
    args = parser.parse_args()

    root = Path(args.spec_root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"ERROR: spec root not found: {root}")
    boards = [
        d for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith(".")
    ]
    if not boards:
        raise SystemExit(f"ERROR: no board dirs under {root}")

    failures: list[str] = []

    feature_manifest = None
    if args.feature_manifest:
        feature_manifest = load_json(Path(args.feature_manifest))
        failures.extend(validate_feature(root, feature_manifest))
        failures.extend(
            validate_manifest(
                feature_manifest,
                str(feature_manifest.get("featureId") or Path(args.feature_manifest).stem),
            )
        )
    else:
        failures.append("feature manifest is required")
    if args.state_changes and (args.state_key or args.changed_files):
        failures.append(
            "--state-changes cannot be combined with --state-key/--changed-files"
        )
    elif args.state_changes:
        if feature_manifest is None:
            failures.append("state changes require --feature-manifest")
        else:
            try:
                state_changes = load_json(Path(args.state_changes))
                failures.extend(validate_state_changes(feature_manifest, state_changes))
            except (OSError, json.JSONDecodeError, ValueError) as error:
                failures.append(f"state changes unreadable: {error}")
    elif not args.state_key and not args.changed_files:
        failures.append(
            "state change evidence is required (--state-changes or --state-key + --changed-files)"
        )
    elif bool(args.state_key) != bool(args.changed_files):
        failures.append("--state-key and --changed-files must be provided together")
    elif args.state_key and args.changed_files:
        if feature_manifest is None:
            failures.append("state change scope requires --feature-manifest")
        else:
            changed = [
                line.strip()
                for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            failures.extend(validate_state_change_scope(feature_manifest, args.state_key, changed))

    for board in boards:
        tag = board.name
        fidelity_files = sorted(board.glob("render_fidelity*.json"))
        if not fidelity_files:
            failures.append(f"{tag}: no render_fidelity report")
        for f in fidelity_files:
            rep = load_json(f)
            if not rep.get("ok"):
                failures.append(f"{tag}: fidelity failed ({f.name}: {rep.get('byCategory')})")
            if not rep.get("assetShapeChecked"):
                failures.append(f"{tag}: fidelity ran without --diff-report ({f.name}) — "
                                "icon/asset shape channel unchecked")
        if not (board / "artifact_digest.json").is_file():
            failures.append(f"{tag}: artifact_digest.json missing (reading discipline not executed)")
        local = board / "shared_components.local.json"
        if local.is_file():
            for comp in (load_json(local).get("components") or []):
                if comp.get("status") == "missing":
                    failures.append(f"{tag}: shared component unresolved (status=missing, "
                                    f"sig {str(comp.get('signature'))[:16]}) — registry never built")
                if comp.get("status") == "candidate":
                    failures.append(
                        f"{tag}: unresolved semantic component candidate "
                        f"(sig {str(comp.get('signature'))[:16]})"
                    )
        else:
            failures.append(f"{tag}: shared_components.local.json missing (detection never ran)")

        diff = board / "diff_report.json"
        if not diff.is_file():
            failures.append(f"{tag}: diff_report.json missing")
        else:
            diff_report = load_json(diff)
            for issue in diff_report.get("assetIssues") or []:
                mismatch = float(issue.get("pixelMismatch") or 0)
                if mismatch > args.asset_tol:
                    failures.append(
                        f"{tag}: asset region real defect: {issue.get('node')} "
                        f"mismatch={mismatch:.3f} > {args.asset_tol}"
                    )
            for issue in diff_report.get("textIssues") or []:
                mismatch = float(issue.get("pixelMismatch") or 0)
                if mismatch > args.text_tol:
                    failures.append(
                        f"{tag}: text region real defect (clipped/wrong glyphs): "
                        f"{issue.get('node')} mismatch={mismatch:.3f} > {args.text_tol}"
                    )

        manifest = board / "visual_manifest.json"
        if not manifest.is_file():
            failures.append(f"{tag}: visual_manifest.json missing")
        elif load_json(manifest).get("actual_source") != "simulator_screenshot":
            failures.append(f"{tag}: visual_manifest actual_source must be simulator_screenshot")

        for failure in validate_board(board):
            failures.append(f"{tag}: {failure}")
        for failure in validate_visual_provenance(board):
            failures.append(f"{tag}: {failure}")

    plan = find_one(root, "implementation_plan.json")
    if not plan:
        failures.append("implementation_plan.json missing under spec root")
    else:
        text = plan.read_text(encoding="utf-8")
        if "__MODEL__" in text:
            failures.append(f"{plan.name}: unfilled __MODEL__ placeholders")
        if "prefilledBy" not in text:
            failures.append(f"{plan.name}: not machine-prefilled (prefill_implementation_plan.py)")

    evidence = find_one(root, "interaction_test_evidence.json")
    if not evidence:
        failures.append("interaction_test_evidence.json missing")
    else:
        ev = load_json(evidence)

        def exit_code(phase: str):
            d = ev.get(phase) or {}
            return d.get("exit_code", d.get("exitCode"))

        if exit_code("red") in (0, None):
            failures.append("red evidence invalid (exit_code must be nonzero)")
        if exit_code("green") != 0:
            failures.append("green evidence invalid (exit_code must be 0)")

    wiring = find_one(root, "wiring_report.json")
    if not wiring:
        failures.append("wiring_report.json missing")
    elif not load_json(wiring).get("ok"):
        failures.append(f"wiring not ok: unwired={load_json(wiring).get('unwired')}")

    interaction_gate = find_one(root, "interaction_gate_report.json")
    if not interaction_gate:
        failures.append("interaction_gate_report.json missing")
    elif not args.feature_manifest:
        failures.append("interaction gate recompute requires --feature-manifest")
    else:
        interaction_report = load_json(interaction_gate)
        project_root_value = interaction_report.get("projectRoot")
        if not project_root_value:
            failures.append("interaction gate report missing projectRoot")
        elif Path(str(interaction_report.get("specRoot") or "")).resolve() != root:
            failures.append("interaction gate report specRoot mismatch")
        elif Path(str(interaction_report.get("featureManifest") or "")).resolve() != Path(
            args.feature_manifest
        ).resolve():
            failures.append("interaction gate report featureManifest mismatch")
        else:
            interaction_failures, current_inputs = validate_interaction_feature(
                root,
                Path(str(project_root_value)).resolve(),
                Path(args.feature_manifest).resolve(),
            )
            if interaction_failures:
                failures.append(
                    "interaction gate recompute failed: " + " | ".join(interaction_failures)
                )
            elif interaction_report.get("inputs") != current_inputs:
                failures.append("interaction gate report stale: current input fingerprints differ")
            elif not interaction_report.get("ok"):
                failures.append("interaction gate report is not ok")

    new_data_artifacts = any(
        find_one(root, name)
        for name in (
            "oas.json",
            "api_contract.json",
            "data_slot_bindings.json",
            "data_runtime_manifest.json",
            "data_gate_report.json",
        )
    )
    if new_data_artifacts:
        data_gate = find_one(root, "data_gate_report.json")
        if not data_gate:
            failures.append("data_gate_report.json missing")
        else:
            data_report = load_json(data_gate)
            project_value = data_report.get("projectRoot")
            runtime_value = data_report.get("runtimeManifest")
            if Path(str(data_report.get("specRoot") or "")).resolve() != root:
                failures.append("data gate report specRoot mismatch")
            elif not project_value or not runtime_value:
                failures.append("data gate report missing projectRoot/runtimeManifest")
            else:
                live_value = data_report.get("liveApiReport")
                data_failures, current_inputs, live_verified = validate_data_feature(
                    root,
                    Path(str(project_value)).resolve(),
                    Path(str(runtime_value)).resolve(),
                    Path(str(live_value)).resolve() if live_value else None,
                    bool(data_report.get("requireLiveApi", False)),
                )
                if data_failures:
                    failures.append(
                        "data gate recompute failed: " + " | ".join(data_failures)
                    )
                elif data_report.get("inputs") != current_inputs:
                    failures.append("data gate report stale: current input fingerprints differ")
                elif data_report.get("liveApiVerified") != live_verified:
                    failures.append("data gate report liveApiVerified mismatch")
                elif not data_report.get("ok"):
                    failures.append("data gate report is not ok")

    api = find_one(root, "api_integration_report.json")
    if not api:
        failures.append("api_integration_report.json missing")
    elif load_json(api).get("missing"):
        failures.append(f"api endpoints not integrated: {load_json(api).get('missing')}")

    if not find_one(root, "*.receipt.json"):
        failures.append("worker receipt missing")
    model_context_path = find_one(root, "model_context_report.json")
    if not model_context_path:
        failures.append("model_context_report.json missing")
    else:
        stored_context = load_json(model_context_path)
        project_value = stored_context.get("projectRoot")
        if not project_value:
            failures.append("model context report missing projectRoot")
        elif not args.feature_manifest:
            failures.append("model context recompute requires --feature-manifest")
        else:
            current_context = build_model_context_report(
                root,
                Path(str(project_value)).expanduser().resolve(),
                Path(__file__).resolve().parents[1],
                Path(args.feature_manifest).expanduser().resolve(),
            )
            if current_context.get("failures"):
                failures.append(
                    "model context recompute failed: "
                    + " | ".join(current_context["failures"])
                )
            elif stored_context != current_context:
                failures.append("model context report stale: current inputs differ")

    report = {"specRoot": str(root), "boards": [b.name for b in boards],
              "ok": not failures, "failures": failures}
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        print(f"FAIL done gate ({len(failures)}):")
        for f in failures:
            print("  - " + f)
        return 1
    print(f"ok done gate: {len(boards)} board(s) fully evidenced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
