#!/usr/bin/env python3
"""Validate iFF skill metadata without third-party YAML dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [f"missing {skill_file}"]
    text = skill_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) > 500:
        errors.append(f"SKILL.md exceeds 500 lines: {len(lines)}")
    if not lines or lines[0] != "---":
        return [*errors, "SKILL.md must start with YAML frontmatter delimiter ---"]
    try:
        close = lines.index("---", 1)
    except ValueError:
        return [*errors, "SKILL.md frontmatter is missing its closing --- delimiter"]
    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:close], start=2):
        if not line.strip():
            continue
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):\s*(.+)", line)
        if not match:
            errors.append(f"unsupported frontmatter syntax at line {number}")
            continue
        key, value = match.groups()
        if key in fields:
            errors.append(f"duplicate frontmatter field: {key}")
        fields[key] = value.strip()
    if set(fields) != {"name", "description"}:
        errors.append(
            f"frontmatter fields must be exactly name and description: {sorted(fields)}"
        )
    name = fields.get("name", "")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        errors.append(f"invalid skill name: {name!r}")
    if name and name != skill_dir.name:
        errors.append(f"skill name {name!r} does not match directory {skill_dir.name!r}")
    if not fields.get("description", ""):
        errors.append("skill description must be non-empty")
    if close + 1 >= len(lines) or not any(line.strip() for line in lines[close + 1 :]):
        errors.append("SKILL.md body must be non-empty")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_dir")
    args = parser.parse_args()
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    errors = validate_skill(skill_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"ok skill structure: {skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
