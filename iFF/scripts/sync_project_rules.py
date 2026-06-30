#!/usr/bin/env python3
"""Inject the iFF implementation rules (and, optionally, the case memory) into a target
project's CLAUDE.md.

Why a script (deterministic): the single source of truth for the rules is
`iFF/implementation_rules.md`, and for the accumulated B-type judgment precedents it is
`iFF/evolution/case_memory.md`. This copies them into the project so every agent working there
(iFF workers and others) loads the same standards AND the same prior-case decisions before it
makes any binding/judgment call. Each is written inside its own delimited block, and re-syncing
replaces only the managed block — any project-authored CLAUDE.md content outside is preserved.
The check-if-present / inject-if-absent behaviour makes it safe to run on every worker startup.
"""
from __future__ import annotations

import argparse
from pathlib import Path

RULES_START = "<!-- IFF:IMPL-RULES:START — generated from iFF/implementation_rules.md, do not edit inside this block -->"
RULES_END = "<!-- IFF:IMPL-RULES:END -->"
MEM_START = "<!-- IFF:CASE-MEMORY:START — generated from iFF/evolution/case_memory.md, do not edit inside this block -->"
MEM_END = "<!-- IFF:CASE-MEMORY:END -->"


def inject_block(text: str, start: str, end: str, block: str) -> str:
    """Replace the managed [start..end] block if present, else append it. Preserve everything else."""
    if start in text and end in text:
        pre = text.split(start)[0].rstrip()
        post = text.split(end, 1)[1].lstrip()
        parts = [p for p in (pre, block.strip(), post) if p]
        return "\n\n".join(parts) + "\n"
    if text.strip():
        return text.rstrip() + "\n\n" + block
    return block


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True, help="path to implementation_rules.md")
    ap.add_argument("--memory", help="optional path to evolution/case_memory.md")
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()

    claude = Path(args.project_root) / "CLAUDE.md"
    text = claude.read_text(encoding="utf-8") if claude.is_file() else ""

    rules = Path(args.rules).read_text(encoding="utf-8").rstrip()
    text = inject_block(text, RULES_START, RULES_END, f"{RULES_START}\n\n{rules}\n\n{RULES_END}\n")
    injected = ["rules"]

    # Case memory is optional — inject only when the file exists and carries at least one case,
    # so an empty memory never bloats CLAUDE.md.
    if args.memory:
        mem_path = Path(args.memory)
        if mem_path.is_file():
            mem = mem_path.read_text(encoding="utf-8").rstrip()
            if "## CASE-" in mem:
                text = inject_block(text, MEM_START, MEM_END, f"{MEM_START}\n\n{mem}\n\n{MEM_END}\n")
                injected.append("case-memory")

    claude.write_text(text, encoding="utf-8")
    print(f"synced {'+'.join(injected)} -> {claude}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
