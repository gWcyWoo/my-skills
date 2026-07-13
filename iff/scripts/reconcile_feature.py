#!/usr/bin/env python3
"""Pipeline entry gate: decide whether a design row is a NEW feature, an EXTENSION of an existing
feature, or just another STATE VARIANT of one already implemented.

Motivation: several design drafts can be the same screen in different states (e.g. multiple "首页"
that differ only by apply_status). Implementing each as a brand-new page duplicates a feature that
should gain a variant. This script does the deterministic part — inventory existing features and
surface name/route overlaps with the incoming row — and leaves the decision to the worker model,
which must understand whether the business logic is the same before choosing reuse vs new.

Output: reconcile_decision.json with the existing inventory, candidate matches, and a `decision`
field the model fills ("new" | "extend:<feature>" | "variant:<feature>") with a reason.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib-root", default="lib")
    ap.add_argument("--manifest-root", help="project .iff/features directory")
    ap.add_argument("--title", required=True, help="incoming row title, e.g. 首页")
    ap.add_argument("--route-hint")
    ap.add_argument("--state-hint")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    lib_root = Path(args.lib_root)
    features_dir = lib_root / "features"
    features = []
    if features_dir.is_dir():
        for d in sorted(p for p in features_dir.iterdir() if p.is_dir()):
            pages = [str(f.relative_to(lib_root)) for f in d.rglob("*_page.dart")]
            cards = [str(f.relative_to(lib_root)) for f in d.rglob("*card*.dart")]
            features.append({"feature": d.name, "pages": pages, "cardFiles": cards})

    manifests: dict[str, dict] = {}
    if args.manifest_root:
        manifest_root = Path(args.manifest_root)
        if manifest_root.is_dir():
            for path in sorted(manifest_root.glob("*.json")):
                doc = json.loads(path.read_text(encoding="utf-8"))
                feature_id = str(doc.get("featureId") or path.stem)
                manifests[feature_id] = doc
                if not any(item["feature"] == feature_id for item in features):
                    features.append({"feature": feature_id, "pages": [], "cardFiles": []})

    # heuristic candidate: a feature dir or page whose name relates to the title token.
    token = re.sub(r"[^A-Za-z0-9]", "", args.title).lower()
    candidates = [f["feature"] for f in features
                  if token and token in f["feature"].lower()] or \
                 [f["feature"] for f in features if f["feature"] == "home"] if "首页" in args.title or "home" in args.title.lower() else []

    route_matches = [
        feature_id
        for feature_id, manifest in manifests.items()
        if args.route_hint and manifest.get("route") == args.route_hint
    ]
    candidate_feature = route_matches[0] if len(route_matches) == 1 else (candidates[0] if len(candidates) == 1 else None)
    existing_states = sorted((manifests.get(candidate_feature, {}).get("states") or {}).keys()) if candidate_feature else []
    recommended = None
    if candidate_feature and args.state_hint:
        if args.state_hint in existing_states:
            recommended = f"revision:{candidate_feature}:{args.state_hint}"
        else:
            recommended = f"variant:{candidate_feature}"

    decision = {
        "title": args.title,
        "existingFeatures": features,
        "candidateMatches": sorted(set(route_matches + candidates)),
        "candidateFeature": candidate_feature,
        "existingStates": existing_states,
        "recommendedDecision": recommended,
        "recommendedStateKey": args.state_hint,
        "decision": None,  # model fills: "new" | "extend:<feature>" | "variant:<feature>"
        "reason": None,    # model fills: same business logic? same screen different state?
        "note": "Deterministic inventory only. The model must decide reuse vs new by reading whether "
                "the business logic matches; multiple drafts of one screen in different states should "
                "become variants of an existing feature, not duplicate pages.",
    }
    Path(args.out).write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok reconcile feature: {len(features)} existing feature(s), "
          f"candidates={candidates or '[]'} (model must set decision) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
