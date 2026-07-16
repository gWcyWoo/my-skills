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
    ap.add_argument("--title", required=True, help="incoming row title, e.g. 首页")
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

    # heuristic candidate: a feature dir or page whose name relates to the title token.
    token = re.sub(r"[^A-Za-z0-9]", "", args.title).lower()
    candidates = [f["feature"] for f in features
                  if token and token in f["feature"].lower()] or \
                 [f["feature"] for f in features if f["feature"] == "home"] if "首页" in args.title or "home" in args.title.lower() else []

    decision = {
        "title": args.title,
        "existingFeatures": features,
        "candidateMatches": candidates,
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
