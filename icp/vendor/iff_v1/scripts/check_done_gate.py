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
  packaging assembly_packaging.json: current board assets/fonts/pubspec registrations verify.
  tdd      interaction_test_evidence.json: red missing_feature_behavior/nonzero, green exitCode == 0.
  wiring   wiring_report.json ok=true.
  api      validated feature_api_contract.json + hash-bound integration report proving every selection.
  pixels   a diff_report.json exists (final state, pixel diagnostics are
           mandatory evidence even though thresholds are diagnostic-only);
           every board-scoped diff uses AA-filtered pixelMismatchRealDefect
           (legacy fallback: pixelMismatch) for asset/text real-defect gates
           or textIssues pixelMismatch > --text-tol fail (wrong glyph / clipped
           text — the "davs" class that bbox/color fidelity cannot see).
  manifest a visual_manifest.json with actual_source=simulator_screenshot.
  compliance worker_compliance.json exists somewhere under the spec root.
"""

from __future__ import annotations

import argparse
import glob as globmod
import json
from pathlib import Path

from common import load_json
from prepare_assembly_packaging import validate_evidence
from assembly_tdd_guard import validate_tdd_chronology
from layout_trace_contract import LayoutTraceContractError, load_actual_layout_trace
from check_responsive_layout import responsive_failures
from scope_api_contract import (
    ApiScopeError,
    feature_operations,
    file_sha256,
    validate_feature_contract_files,
)


def find_one(root: Path, pattern: str) -> Path | None:
    hits = sorted(root.rglob(pattern))
    return hits[0] if hits else None


def scoped_diff_reports(root: Path) -> list[Path]:
    board_reports = [
        directory / "diff_report.json"
        for directory in sorted(root.iterdir())
        if directory.is_dir() and (directory / "diff_report.json").is_file()
    ]
    if board_reports:
        return board_reports
    root_report = root / "diff_report.json"
    return [root_report] if root_report.is_file() else []


def real_defect_mismatch(issue: dict) -> float:
    value = issue.get("pixelMismatchRealDefect")
    if value is None:
        value = issue.get("pixelMismatch")
    return float(value or 0)


def api_gate_failures(root: Path) -> list[str]:
    failures: list[str] = []
    names = {
        "project": "api_contract.json",
        "row": "row.json",
        "interaction": "interaction_contract.json",
        "selection": "api_endpoint_selection.json",
        "feature": "feature_api_contract.json",
        "report": "api_integration_report.json",
    }
    paths = {name: find_one(root, filename) for name, filename in names.items()}
    for name, filename in names.items():
        if paths[name] is None:
            failures.append(f"{filename} missing")
    if any(paths[name] is None for name in ("project", "row", "interaction", "selection", "feature")):
        return failures
    try:
        feature_contract = validate_feature_contract_files(
            paths["project"],
            paths["row"],
            paths["interaction"],
            paths["selection"],
            paths["feature"],
        )
        operations = feature_operations(feature_contract)
    except (ApiScopeError, OSError) as exc:
        failures.append(f"feature API contract invalid: {exc}")
        return failures
    if paths["report"] is None:
        return failures
    report = load_json(paths["report"])
    selected = [f"{method} {path}" for path, method in operations]
    if report.get("contractScope") != "feature":
        failures.append("api integration report is silently unscoped")
    if report.get("contractSha256") != file_sha256(paths["feature"]):
        failures.append("api integration report contract hash is stale or mismatched")
    if report.get("apiRequired") is not feature_contract.get("apiRequired"):
        failures.append("api integration report apiRequired differs from feature contract")
    if report.get("operationCount") != len(operations) or report.get("selected") != selected:
        failures.append("api integration report does not cover exactly the selected operations")
    if report.get("missing"):
        failures.append(f"api endpoints not integrated: {report.get('missing')}")
    if report.get("integrated") != selected or report.get("ok") is not True:
        failures.append("api integration report does not prove every selected endpoint")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True, help="lanhu/specs/<feature>")
    parser.add_argument("--asset-tol", type=float, default=0.10)
    parser.add_argument("--text-tol", type=float, default=0.30)
    parser.add_argument("--out")
    args = parser.parse_args()

    root = Path(args.spec_root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"ERROR: spec root not found: {root}")
    boards = [d for d in sorted(root.iterdir()) if d.is_dir()]
    if not boards:
        raise SystemExit(f"ERROR: no board dirs under {root}")

    failures: list[str] = []
    failures.extend(
        f"assembly packaging: {failure}"
        for failure in validate_evidence(root / "assembly_packaging.json")
    )
    failures.extend(
        f"assembly TDD chronology: {failure}"
        for failure in validate_tdd_chronology(root)
    )

    green_started_at_ns = None
    tdd_evidence_path = find_one(root, "interaction_test_evidence.json")
    if tdd_evidence_path:
        green = load_json(tdd_evidence_path).get("green") or {}
        candidate = green.get("started_at_ns", green.get("startedAtNs"))
        if isinstance(candidate, int):
            green_started_at_ns = candidate

    for board in boards:
        tag = board.name
        trace_path = board / "actual_layout_trace.json"
        if not trace_path.is_file():
            failures.append(f"{tag}: actual layout trace missing")
        else:
            try:
                load_actual_layout_trace(trace_path, min_mtime_ns=green_started_at_ns)
            except LayoutTraceContractError as exc:
                failures.append(f"{tag}: actual layout trace invalid ({exc})")
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
        responsive_contract = board / "responsive_layout_contract.json"
        responsive_report = board / "responsive_layout_report.json"
        failures.extend(
            f"{tag}: {failure}"
            for failure in responsive_failures(responsive_contract, responsive_report)
        )
        if not (board / "artifact_digest.json").is_file():
            failures.append(f"{tag}: artifact_digest.json missing (reading discipline not executed)")
        local = board / "shared_components.local.json"
        if local.is_file():
            for comp in (load_json(local).get("components") or []):
                if comp.get("status") == "missing":
                    failures.append(f"{tag}: shared component unresolved (status=missing, "
                                    f"sig {str(comp.get('signature'))[:16]}) — registry never built")
        else:
            failures.append(f"{tag}: shared_components.local.json missing (detection never ran)")

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

        adoption = ev.get("adoption") or {}
        preexisting_green = adoption.get("authorization") == "preexisting-green"
        if not preexisting_green:
            if exit_code("red") in (0, None):
                failures.append("red evidence invalid (exit_code must be nonzero)")
            red = ev.get("red") or {}
            red_failure_kind = red.get("failure_kind", red.get("failureKind"))
            if red_failure_kind != "missing_feature_behavior":
                failures.append(
                    "red evidence invalid (failure_kind must be missing_feature_behavior)"
                )
        if exit_code("green") != 0:
            failures.append("green evidence invalid (exit_code must be 0)")

    wiring = find_one(root, "wiring_report.json")
    if not wiring:
        failures.append("wiring_report.json missing")
    elif not load_json(wiring).get("ok"):
        failures.append(f"wiring not ok: unwired={load_json(wiring).get('unwired')}")

    capture_readiness = find_one(root, "capture_readiness.json")
    if not capture_readiness:
        failures.append("capture_readiness.json missing")
    else:
        capture_report = load_json(capture_readiness)
        if not capture_report.get("ok"):
            failures.append(
                "capture readiness not ok: "
                f"reason={capture_report.get('reason')}"
            )

    failures.extend(api_gate_failures(root))

    diffs = scoped_diff_reports(root)
    if not diffs:
        failures.append("diff_report.json missing (final-state pixel diagnostics are mandatory evidence)")
    else:
        for diff in diffs:
            d = load_json(diff)
            for issue in d.get("assetIssues") or []:
                mismatch = real_defect_mismatch(issue)
                if mismatch > args.asset_tol:
                    failures.append(f"asset region real defect: {issue.get('node')} "
                                    f"mismatch={mismatch:.3f} > {args.asset_tol}")
            for issue in d.get("textIssues") or []:
                mismatch = real_defect_mismatch(issue)
                if mismatch > args.text_tol:
                    failures.append(f"text region real defect (clipped/wrong glyphs): {issue.get('node')} "
                                    f"mismatch={mismatch:.3f} > {args.text_tol}")

    manifest = find_one(root, "visual_manifest.json")
    if not manifest:
        failures.append("visual_manifest.json missing")
    else:
        sources = [load_json(m).get("actual_source") for m in root.rglob("visual_manifest.json")]
        if "simulator_screenshot" not in sources:
            failures.append(f"no visual_manifest with actual_source=simulator_screenshot (saw {set(sources)})")

    if not find_one(root, "worker_compliance.json"):
        failures.append("worker_compliance.json missing")

    failures = list(dict.fromkeys(failures))
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
