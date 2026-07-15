#!/usr/bin/env python3
"""Ground each interaction rule's visual references onto concrete design boards.

For every rule in interaction_contract.json, extract its quoted UI strings
(「」『』""''"" quotes) and board-name mentions, then match them against the
deterministic board index (make_board_index.py):
  - exactly one board matches  -> resolution=unique, bound automatically
  - several boards match       -> resolution=ambiguous, the model must set
                                  "confirmed": "<feature>/<board>" (a choice
                                  among listed candidates — a judgment call,
                                  not a search)
  - nothing matches            -> resolution=unresolved; the model must either
                                  set "pending_route": true (target lives in a
                                  not-yet-implemented row; tests then assert
                                  the navigation intent against a mock) or fix
                                  the reference. Unresolved entries FAIL --check.

--check mode re-validates the (model-edited) anchors file before test design.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from common import dump_json, load_json


QUOTE_RE = re.compile(r"[「『\"“'‘]([^」』\"”'’]{1,30})[」』\"”'’]")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def match_query(query: str, boards: list[dict]) -> list[dict]:
    q = norm(query)
    hits = []
    for b in boards:
        match_type = None
        if any(q == t or (len(q) >= 4 and q in t) for t in b["texts"]):
            match_type = "text"
        elif q and (q in norm(b["board"]) or q in norm(b["feature"])):
            match_type = "board_name"
        if match_type:
            hits.append({"feature": b["feature"], "board": b["board"], "matchType": match_type})
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--index", required=True, help="board_index.json")
    parser.add_argument("--out", required=True, help="interaction_anchors.json")
    parser.add_argument("--check", action="store_true",
                        help="validate an existing anchors file: every entry must be "
                             "unique, confirmed, or pending_route")
    args = parser.parse_args()

    if args.check:
        doc = load_json(args.out)
        expected_inputs = {
            "contract": sha256(args.contract),
            "index": sha256(args.index),
        }
        actual_inputs = doc.get("inputs") or {}
        stale = [
            name
            for name, digest in expected_inputs.items()
            if actual_inputs.get(name) != digest
        ]
        if stale:
            print(
                "FAIL anchors: "
                + ", ".join(f"stale {name} hash" for name in stale)
            )
            return 1
        bad = []
        for anchor in doc.get("anchors") or []:
            reason = None
            if anchor.get("resolution") == "ambiguous":
                confirmed = anchor.get("confirmed")
                candidates = {
                    f"{candidate.get('feature')}/{candidate.get('board')}"
                    for candidate in anchor.get("candidates") or []
                }
                if not confirmed:
                    reason = "missing confirmed target"
                elif confirmed not in candidates:
                    reason = "confirmed target is not a candidate"
            elif anchor.get("resolution") == "unresolved":
                if not anchor.get("pending_route"):
                    reason = "missing pending_route"
                elif not str(anchor.get("targetIntent") or "").strip():
                    reason = "pending_route missing targetIntent"
            if reason:
                bad.append((anchor, reason))
        if bad:
            print(f"FAIL anchors: {len(bad)} unresolved visual reference(s):")
            for anchor, reason in bad:
                print(
                    f"  - {anchor.get('rule')}: {anchor.get('query')!r} "
                    f"({anchor.get('resolution')}): {reason}"
                )
            return 1
        print(f"ok anchors: {len(doc.get('anchors') or [])} references all grounded")
        return 0

    contract = load_json(args.contract)
    boards = (load_json(args.index)).get("boards") or []

    # Mention vocabulary for unquoted references (R1's real 交互描述 uses none):
    # board-name segments (首页-首贷 -> 首页/首贷) and the boards' own visible texts.
    mention_terms: set[str] = set()
    for b in boards:
        for seg in re.split(r"[-_ ()()  ]+", b["board"]):
            if len(norm(seg)) >= 2:
                mention_terms.add(norm(seg))
        mention_terms.update(t for t in b["texts"] if len(t) >= 4)

    anchors = []
    for rule in contract.get("rules") or []:
        text = " ".join(str(rule.get(k) or "") for k in ("source", "trigger", "expectation"))
        norm_text = norm(text)
        queries = list(dict.fromkeys(QUOTE_RE.findall(text)))
        queries += sorted(t for t in mention_terms if t in norm_text and t not in map(norm, queries))
        for query in queries:
            hits = match_query(query, boards)
            unique_boards = {(h["feature"], h["board"]) for h in hits}
            resolution = ("unique" if len(unique_boards) == 1
                          else "ambiguous" if unique_boards else "unresolved")
            anchors.append({
                "rule": rule.get("id"),
                "query": query,
                "candidates": hits,
                "resolution": resolution,
                "bound": hits[0] if resolution == "unique" else None,
            })
    unresolved = sum(1 for a in anchors if a["resolution"] != "unique")
    dump_json(
        {
            "contract": args.contract,
            "inputs": {
                "contract": sha256(args.contract),
                "index": sha256(args.index),
            },
            "anchors": anchors,
        },
        args.out,
    )
    print(f"ok anchors: {len(anchors)} visual reference(s), "
          f"{len(anchors) - unresolved} auto-bound, {unresolved} need model confirmation "
          f"(edit {args.out}, then rerun with --check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
