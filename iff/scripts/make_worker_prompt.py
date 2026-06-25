#!/usr/bin/env python3
"""Create the exact prompt used to spawn one iFF worker."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_row(path: str | None) -> dict:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--row-json", help="One claimed CSV/Excel row serialized as JSON.")
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    scripts_dir = skill_dir / "scripts"
    required = [skill_md, test_rules, scripts_dir / "verify_pipeline_scripts.py"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("ERROR: worker prompt inputs missing:\n" + "\n".join(missing))

    row = load_row(args.row_json)
    hashes = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "verify_pipeline_scripts_sha256": digest(scripts_dir / "verify_pipeline_scripts.py"),
    }
    prompt = f"""IFF_WORKER_BOOTSTRAP v1
You are one iFF worker for exactly one claimed row. Do not rely on automatic skill loading.

Before reading or editing the Flutter project:
1. Read {skill_md} completely.
2. Read {test_rules} completely.
3. Run: python3 {scripts_dir / "verify_pipeline_scripts.py"} --skill-dir {skill_dir}
4. Write {Path(args.spec_dir) / "worker_compliance.json"} with:
   - loaded_files: [{str(skill_md)!r}, {str(test_rules)!r}]
   - skill_md_sha256: {hashes["skill_md_sha256"]}
   - test_rules_sha256: {hashes["test_rules_sha256"]}
   - verify_pipeline_scripts_sha256: {hashes["verify_pipeline_scripts_sha256"]}
   - pipeline_scripts_ok: true
   - worker_bootstrap_version: IFF_WORKER_BOOTSTRAP v1

Hard gates:
- Follow the fixed iFF pipeline from SKILL.md; do not skip or merge steps.
- Use only scripts under {scripts_dir} for deterministic artifacts.
- Compile interaction into contract/test plan and prove coverage with red/green evidence.
- Implement UI from scene/tokens/assets/layout/render/interaction contracts, not from visual guesswork.
- Never use the full design reference as a widget background or visible layer.
- Return paths for spec_dir, worker_compliance.json, interaction_test_evidence.json, visual_manifest.json, actual.png, diff_report.json, and any required dependency/route/DI/asset registrations.

Row JSON:
{json.dumps(row, ensure_ascii=False, indent=2)}

Project root: {Path(args.project_root).resolve()}
Spec dir: {Path(args.spec_dir).resolve()}
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
