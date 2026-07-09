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
  tdd      interaction_test_evidence.json: red exitCode != 0, green exitCode == 0.
  wiring   wiring_report.json ok=true.
  api      api_integration_report.json missing==[].
  pixels   a diff_report.json exists (final state, pixel diagnostics are
           mandatory evidence even though thresholds are diagnostic-only);
           flat-region REAL defects gate: assetIssues pixelMismatch > --asset-tol
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


def find_one(root: Path, pattern: str) -> Path | None:
    hits = sorted(root.rglob(pattern))
    return hits[0] if hits else None


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

        if exit_code("red") in (0, None):
            failures.append("red evidence invalid (exit_code must be nonzero)")
        if exit_code("green") != 0:
            failures.append("green evidence invalid (exit_code must be 0)")

    wiring = find_one(root, "wiring_report.json")
    if not wiring:
        failures.append("wiring_report.json missing")
    elif not load_json(wiring).get("ok"):
        failures.append(f"wiring not ok: unwired={load_json(wiring).get('unwired')}")

    api = find_one(root, "api_integration_report.json")
    if not api:
        failures.append("api_integration_report.json missing")
    elif load_json(api).get("missing"):
        failures.append(f"api endpoints not integrated: {load_json(api).get('missing')}")

    diff = find_one(root, "diff_report.json")
    if not diff:
        failures.append("diff_report.json missing (final-state pixel diagnostics are mandatory evidence)")
    else:
        d = load_json(diff)
        for issue in d.get("assetIssues") or []:
            if float(issue.get("pixelMismatch") or 0) > args.asset_tol:
                failures.append(f"asset region real defect: {issue.get('node')} "
                                f"mismatch={issue.get('pixelMismatch'):.3f} > {args.asset_tol}")
        for issue in d.get("textIssues") or []:
            if float(issue.get("pixelMismatch") or 0) > args.text_tol:
                failures.append(f"text region real defect (clipped/wrong glyphs): {issue.get('node')} "
                                f"mismatch={issue.get('pixelMismatch'):.3f} > {args.text_tol}")

    manifest = find_one(root, "visual_manifest.json")
    if not manifest:
        failures.append("visual_manifest.json missing")
    else:
        sources = [load_json(m).get("actual_source") for m in root.rglob("visual_manifest.json")]
        if "simulator_screenshot" not in sources:
            failures.append(f"no visual_manifest with actual_source=simulator_screenshot (saw {set(sources)})")

    if not find_one(root, "worker_compliance.json"):
        failures.append("worker_compliance.json missing")

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
