#!/usr/bin/env python3
"""Render the accumulated flow graph as a user-story journey map + E2E checklist.

Run at goal level once every sheet row is done: the mermaid graph is the human
review artifact; the journeys list (entry-to-terminal paths) is the checklist
the final on-device E2E replay must walk. pending_route edges render dashed —
they are unbuilt product surface, not defects.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True, help="<project>/.iff/flow_graph.json")
    parser.add_argument("--out", required=True, help="journey_map.md")
    parser.add_argument("--max-depth", type=int, default=12)
    args = parser.parse_args()

    graph = load_json(args.graph)
    edges = list((graph.get("edges") or {}).values())
    if not edges:
        raise SystemExit("ERROR: flow graph has no edges — nothing to map")

    def node_id(name: str) -> str:
        return "n" + str(abs(hash(name)) % 10**8)

    lines = ["# 用户故事地图(由 flow_graph.json 生成)", "", "```mermaid", "flowchart LR"]
    nodes = {}
    for e in edges:
        src = str(e.get("from"))
        dst = str(e.get("to_board") or e.get("to_route") or "pending")
        nodes.setdefault(src, node_id(src))
        nodes.setdefault(dst, node_id(dst))
        arrow = "-.->" if e.get("pending_route") else "-->"
        label = str(e.get("trigger") or "").replace('"', "'")[:24]
        lines.append(f'    {nodes[src]}["{src}"] {arrow}|"{label}"| {nodes[dst]}["{dst}"]')
    lines.append("```")

    # entry nodes = never a target; walk out every acyclic path as a journey.
    targets = {str(e.get("to_board") or e.get("to_route") or "pending") for e in edges}
    sources = {str(e.get("from")) for e in edges}
    entries = sorted(sources - targets) or sorted(sources)
    out_edges: dict[str, list] = {}
    for e in edges:
        out_edges.setdefault(str(e.get("from")), []).append(e)

    journeys: list[list[str]] = []

    def walk(node: str, path: list[str]) -> None:
        nexts = [e for e in out_edges.get(node, []) if not e.get("pending_route")]
        if not nexts or len(path) >= args.max_depth:
            if len(path) > 1:
                journeys.append(path)
            return
        for e in nexts:
            dst = str(e.get("to_board") or e.get("to_route"))
            if dst in path:
                journeys.append(path + [f"{dst}(循环)"])
                continue
            walk(dst, path + [dst])

    for entry in entries:
        walk(entry, [entry])

    lines += ["", f"## E2E 回放清单({len(journeys)} 条 journey,真机逐条走通)", ""]
    for i, j in enumerate(journeys, 1):
        lines.append(f"{i}. " + " → ".join(j))
    pending = [e for e in edges if e.get("pending_route")]
    if pending:
        lines += ["", f"## 待建目标(pending_route,{len(pending)} 条——后续行的工作清单)", ""]
        for e in pending:
            lines.append(f"- {e.get('from')} --{e.get('trigger')}→ (未实现,规则 {e.get('ruleId')})")

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"ok journey map: {len(nodes)} nodes, {len(edges)} edges, "
          f"{len(journeys)} journeys, {len(pending)} pending -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
