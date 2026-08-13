#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from validate_skill_structure import validate_skill


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        skill_dir = Path(raw) / "iff"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: iff\ndescription: Deterministic test skill.\n---\n\n# Body\n",
            encoding="utf-8",
        )
        assert validate_skill(skill_dir) == []
        skill_file.write_text("---\nname: iff\n---\n\n# Body\n", encoding="utf-8")
        assert any("frontmatter fields" in error for error in validate_skill(skill_dir))
        skill_file.write_text(
            "---\nname: iff\ndescription: Test.\n---\n" + "body\n" * 496,
            encoding="utf-8",
        )
        assert validate_skill(skill_dir) == []
        skill_file.write_text(
            "---\nname: iff\ndescription: Test.\n---\n" + "body\n" * 497,
            encoding="utf-8",
        )
        assert any("exceeds 500 lines" in error for error in validate_skill(skill_dir))
    print("ok dependency-free skill structure validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
