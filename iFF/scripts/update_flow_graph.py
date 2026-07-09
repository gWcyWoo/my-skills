#!/usr/bin/env python3
"""Project-level cross-page interaction graph — accumulated like the shared
component registry, one merge per fan-in.

add:   merge a feature's edges (from-board --trigger--> to-route/board) into
       <project>/.iff/flow_graph.json. Same edge key updates in place; two
       different targets for one (from, trigger) fail loudly.
check: every edge whose to_route is set must exist in the given routes file
       (deterministic route inventory extracted by the fan-in session, one
       route name per line). pending_route edges are reported, not failed —
       they become the worklist for later rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import dump_json, load_json


def edge_key(e: dict) -> str:
    return f"{e.get('from')}|{e.get('trigger')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, help="<project>/.iff/flow_graph.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--edges", required=True,
                       help="JSON file: [{from, trigger, to_route|to_board|pending_route, ruleId, feature}]")
    p_add.add_argument("--force", action="store_true")

    p_check = sub.add_parser("check")
    p_check.add_argument("--routes", required=True,
                         help="text file with one registered route per line")
    args = parser.parse_args()

    graph_path = Path(args.graph).expanduser()
    try:
        graph = load_json(graph_path)
    except FileNotFoundError:
        graph = {"version": 1, "edges": {}}

    if args.cmd == "add":
        new_edges = load_json(args.edges)
        if not isinstance(new_edges, list):
            raise SystemExit("ERROR: --edges must be a JSON list")
        added = updated = 0
        for e in new_edges:
            if not e.get("from") or not e.get("trigger"):
                raise SystemExit(f"ERROR: edge missing from/trigger: {json.dumps(e, ensure_ascii=False)}")
            key = edge_key(e)
            old = graph["edges"].get(key)
            if old and not args.force:
                for field in ("to_route", "to_board"):
                    if old.get(field) and e.get(field) and old[field] != e[field]:
                        raise SystemExit(f"ERROR: edge {key!r} already targets {old[field]!r} "
                                         f"but new edge says {e[field]!r}; resolve or --force")
            graph["edges"][key] = {**(old or {}), **e}
            added += 0 if old else 1
            updated += 1 if old else 0
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(graph, graph_path)
        pend = sum(1 for e in graph["edges"].values() if e.get("pending_route"))
        print(f"ok flow graph: +{added} new, {updated} updated, {len(graph['edges'])} total edges "
              f"({pend} pending_route)")
        return 0

    routes = {line.strip() for line in Path(args.routes).read_text(encoding="utf-8").splitlines()
              if line.strip()}
    broken = []
    pending = []
    for key, e in sorted(graph["edges"].items()):
        if e.get("pending_route"):
            pending.append(key)
        elif e.get("to_route") and e["to_route"] not in routes:
            broken.append(f"{key} -> {e['to_route']}")
    if broken:
        print(f"FAIL flow graph: {len(broken)} edge(s) target unregistered routes:")
        for b in broken:
            print("  - " + b)
        return 1
    print(f"ok flow graph: {len(graph['edges'])} edges, all targeted routes registered"
          + (f"; {len(pending)} pending_route awaiting future rows: {', '.join(pending[:5])}" if pending else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
