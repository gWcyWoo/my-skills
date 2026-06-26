#!/usr/bin/env python3
"""Inject the iFF implementation rules into a target project's CLAUDE.md.

Why a script (deterministic): the rules' single source of truth is
`iFF/implementation_rules.md`; this copies them into the project so every agent
working in that project (iFF workers and others) loads the same standards. The
content is written inside a delimited block so any project-authored CLAUDE.md
content outside the block is preserved across re-syncs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

START = "<!-- IFF:IMPL-RULES:START — generated from iFF/implementation_rules.md, do not edit inside this block -->"
END = "<!-- IFF:IMPL-RULES:END -->"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True, help="path to implementation_rules.md")
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()

    rules = Path(args.rules).read_text(encoding="utf-8").rstrip()
    block = f"{START}\n\n{rules}\n\n{END}\n"

    claude = Path(args.project_root) / "CLAUDE.md"
    if claude.is_file():
        text = claude.read_text(encoding="utf-8")
        if START in text and END in text:
            # Replace only the managed block, keep everything else intact.
            pre = text.split(START)[0].rstrip()
            post = text.split(END, 1)[1].lstrip()
            parts = [p for p in (pre, block.strip(), post) if p]
            new = "\n\n".join(parts) + "\n"
        else:
            # Append the managed block after existing project content.
            new = text.rstrip() + "\n\n" + block
    else:
        new = block

    claude.write_text(new, encoding="utf-8")
    print(f"synced rules -> {claude}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
