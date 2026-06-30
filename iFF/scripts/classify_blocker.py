#!/usr/bin/env python3
"""Self-improvement ROUTER: classify each worker-reported failure and route it safely.

A self-improving skill must NEVER silently relax an invariant to make a gate pass (that is the
meta-form of 不变量⑤ "严禁为过门放宽真实缺陷判定/放宽阈值"). So every failure is routed to exactly
ONE of four outputs, and any fix that would touch an invariant is FORCED to ESCALATE:

  ① AUTO_FIX_SCRIPT   — a deterministic script didn't feed/handle a value (root cause
                        script-missing-value / skill-flow). The skill may self-patch the script,
                        but ONLY with a red-before/green-after fixture added to evolution/regression/
                        and the whole corpus staying green (selftest_canvas.py).
  ② STRENGTHEN_CONTRACT — a natural-language judgment (binding/extraction/orchestration) slipped a
                        gate. Don't change script logic; tighten the contract/gate so the model is
                        forced to land the judgment as verifiable runtime evidence.
  ③ ESCALATE          — the fix would RELAX/RESHAPE an invariant (e.g. allow a full-artboard asset,
                        permit Offstage, loosen a threshold, re-enable golden-vs-golden). Freeze;
                        a human decides. The skill may never auto-relax an invariant.
  ④ RECORD_CEILING    — environment/data/physical limit (native SDK absent, cross-engine AA, baked
                        status bar, vector shape with no exported asset). Record, don't fix. A
                        ceiling claim must carry a probe (see --require-probe) or it is re-routed.

Deterministic part (this script): the INVARIANT-touch guard and the keyword routing are mechanical
and own the SAFETY boundary. The fine category/nature can be confirmed by the model afterward.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Any fix described with these would alter an invariant → must ESCALATE, never auto-apply.
INVARIANT_TOUCH = re.compile(
    r"放宽|relax|loosen|降低阈值|lower (the )?threshold|allow.*(forbid|禁止|整图铺底|full[- ]artboard|"
    r"offstage|golden)|(forbid|禁止|整图铺底|offstage|golden).*(allow|允许)|整图铺底|Offstage|"
    r"golden[- ]vs[- ]golden|不变量|invariant|disable.*(check|gate|门)|exclude.*(generated|canvas)|"
    r"analysis_options.*exclude", re.I)

# A genuine ceiling must be backed by one of these probes (else re-route — anti "偷懒造天花板").
CEILING_PROBE = re.compile(
    r"MissingPluginException|no such (endpoint|method)|not in (the )?OAS|无此端点|"
    r"cross[- ]engine|antialias|抗锯齿|status[- ]bar|状态栏|no exported (slice|asset)|无切图|"
    r"native (plugin|sdk).*(absent|not in|缺)|camera.*(absent|no )|license", re.I)

CEILING_HINT = re.compile(r"native|sdk|相机|camera|liveness|活体|oss|抗锯齿|antialias|status[- ]bar|状态栏|天花板|ceiling", re.I)

# Root-cause tag → default deterministic-vs-NL route (workers already tag blockers).
ROOT_AUTOFIX = re.compile(r"script-missing-value|skill-flow|missing-value|未喂|没产出", re.I)
ROOT_CONTRACT = re.compile(r"rule-unclear|contract|completeness|未写清|漏抽|needsModelBinding", re.I)

# Which pipeline phase (read/plan/impl/check) a blocker belongs to, by mentioned script/step.
PHASE = [
    ("read",  re.compile(r"fetch|scene|tokens|assets|classif|render_plan|design_artifacts|group", re.I)),
    ("plan",  re.compile(r"interaction|parse|component_manifest|bind_data|implementation_plan|completeness", re.I)),
    ("impl",  re.compile(r"generate_canvas|canvas|fixture|repository|dto|widget|form|capture|repair", re.I)),
    ("check", re.compile(r"check_|fidelity|wiring|coverage|api_integration|fixture_source|trace|analyze|selftest", re.I)),
]


def phase_of(text: str) -> str:
    for name, rx in PHASE:
        if rx.search(text):
            return name
    return "unknown"


def route_one(text: str) -> dict:
    t = text or ""
    if INVARIANT_TOUCH.search(t):
        return {"route": "ESCALATE", "nature": "rule-boundary",
                "why": "fix would relax/reshape an invariant — a human must decide; never auto-apply"}
    if CEILING_HINT.search(t):
        has_probe = bool(CEILING_PROBE.search(t))
        return {"route": "RECORD_CEILING" if has_probe else "NEEDS_PROBE",
                "nature": "ceiling",
                "why": ("backed by a concrete probe" if has_probe else
                        "claims a ceiling WITHOUT a probe — re-run or prove the dependency truly can't "
                        "run here, else re-route as ①/②")}
    if ROOT_CONTRACT.search(t):
        return {"route": "STRENGTHEN_CONTRACT", "nature": "NL-judgment",
                "why": "a natural-language judgment slipped a gate — tighten contract/gate, model fills"}
    if ROOT_AUTOFIX.search(t):
        return {"route": "AUTO_FIX_SCRIPT", "nature": "determinism",
                "why": "a deterministic script didn't feed/handle a value — self-patch + red-before/"
                       "green-after corpus fixture + full selftest green"}
    return {"route": "REVIEW", "nature": "unclassified",
            "why": "no deterministic signal — model must classify before routing"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure", required=True, help="worker result JSON (has blockers[] + manual_judgements[])")
    ap.add_argument("--out")
    a = ap.parse_args()

    rec = json.loads(Path(a.failure).read_text(encoding="utf-8"))
    items = []
    for b in (rec.get("blockers") or []):
        items.append(("blocker", b))
    # a manual_judgement that worked AROUND something is also a failure signal
    for j in (rec.get("manual_judgements") or []):
        if re.search(r"curat|workaround|exclude|手动|绕过|reverted|stub", str(j), re.I):
            items.append(("manual_workaround", j))

    routed = []
    for kind, text in items:
        r = route_one(str(text))
        r.update({"kind": kind, "phase": phase_of(str(text)), "item": str(text)[:240]})
        routed.append(r)

    counts = {}
    for r in routed:
        counts[r["route"]] = counts.get(r["route"], 0) + 1
    # The skill may proceed AUTONOMOUSLY only if nothing requires a human and nothing is unproven.
    blocked = [r for r in routed if r["route"] in ("ESCALATE", "NEEDS_PROBE", "REVIEW")]
    report = {
        "autoEvolvable": len(blocked) == 0 and len(routed) > 0,
        "counts": counts,
        "needsHumanOrProof": [{"route": r["route"], "phase": r["phase"], "item": r["item"]} for r in blocked],
        "routed": routed,
    }
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"autoEvolvable": report["autoEvolvable"], "counts": counts,
                      "escalations": len(blocked)}, ensure_ascii=False))
    for r in routed:
        print(f"  [{r['route']}] ({r['phase']}/{r['nature']}) {r['item'][:120]}")
    # exit non-zero if a human/proof is required, so an automated loop pauses for it.
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
