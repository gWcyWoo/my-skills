#!/usr/bin/env python3
"""Inject iFF implementation rules and optional case memory into project AGENTS.md."""

from __future__ import annotations

import argparse
from pathlib import Path


RULES_START = "<!-- IFF:IMPL-RULES:START — generated from iff/implementation_rules.md, do not edit inside this block -->"
RULES_END = "<!-- IFF:IMPL-RULES:END -->"
MEM_START = "<!-- IFF:CASE-MEMORY:START — generated from iff/evolution/case_memory.md, do not edit inside this block -->"
MEM_END = "<!-- IFF:CASE-MEMORY:END -->"


def validate_markers(text: str, start: str, start_prefix: str, end: str) -> None:
    starts = text.count(start_prefix)
    ends = text.count(end)
    if starts != ends or starts > 1:
        raise ValueError(
            f"unbalanced managed markers: {start_prefix} count={starts}, {end} count={ends}"
        )
    if starts == 1 and start not in text:
        raise ValueError(f"invalid managed start marker: expected {start}")
    if starts == 1 and text.index(start) > text.index(end):
        raise ValueError(f"managed markers out of order: {start_prefix} must precede {end}")


def inject_block(text: str, start: str, end: str, block: str) -> str:
    """Replace one managed block or append it while preserving project-authored text."""
    if start in text and end in text:
        pre = text.split(start)[0].rstrip()
        post = text.split(end, 1)[1].lstrip()
        parts = [part for part in (pre, block.strip(), post) if part]
        return "\n\n".join(parts) + "\n"
    if text.strip():
        return text.rstrip() + "\n\n" + block
    return block


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", required=True, help="path to implementation_rules.md")
    parser.add_argument("--memory", help="optional path to evolution/case_memory.md")
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()

    agents = Path(args.project_root) / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    validate_markers(text, RULES_START, "<!-- IFF:IMPL-RULES:START", RULES_END)
    validate_markers(text, MEM_START, "<!-- IFF:CASE-MEMORY:START", MEM_END)

    rules = Path(args.rules).read_text(encoding="utf-8").rstrip()
    text = inject_block(
        text,
        RULES_START,
        RULES_END,
        f"{RULES_START}\n\n{rules}\n\n{RULES_END}\n",
    )
    injected = ["rules"]

    if args.memory:
        memory_path = Path(args.memory)
        if memory_path.is_file():
            memory = memory_path.read_text(encoding="utf-8").rstrip()
            if "## CASE-" in memory:
                text = inject_block(
                    text,
                    MEM_START,
                    MEM_END,
                    f"{MEM_START}\n\n{memory}\n\n{MEM_END}\n",
                )
                injected.append("case-memory")

    agents.write_text(text, encoding="utf-8")
    print(f"synced {'+'.join(injected)} -> {agents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
