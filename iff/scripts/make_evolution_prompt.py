#!/usr/bin/env python3
"""Generate a scoped improvement prompt only for a user-requested iFF improvement.

The caller supplies the authorized scope when dispatching; this generator does not authorize
edits, memory updates, Git publication, or merging. It only emits prompt text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", required=True, help="iFF skill dir (~/.agents/skills/iff)")
    ap.add_argument("--design-name", required=True, help="the design just processed, e.g. 取款页")
    ap.add_argument("--failure-record", required=True, help="path to the worker's result JSON")
    ap.add_argument("--base-branch", default="main", help="branch the evolution branch is cut from")
    ap.add_argument("--out", help="write prompt here (default: stdout)")
    a = ap.parse_args()

    skill = Path(a.skill_dir).resolve()
    rec_path = Path(a.failure_record).resolve()
    # slug for branch/worktree names (ascii-safe). Chinese names strip to empty → use a deterministic
    # short hash so each design gets a UNIQUE branch (no collision on a generic 'design').
    ascii_slug = re.sub(r"[^A-Za-z0-9._-]", "", a.design_name)
    slug = ascii_slug or ("d" + hashlib.md5(a.design_name.encode("utf-8")).hexdigest()[:8])
    branch = f"iff-evo-{slug}"
    worktree = f"../{branch}"

    # quick router preview so the prompt can state what's expected (the subagent re-runs it for real)
    preview = ""
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        n_block = len(rec.get("blockers") or [])
        n_manual = len(rec.get("manual_judgements") or [])
        preview = f"(record has {n_block} blockers + {n_manual} manual_judgements to route)"
    except Exception:
        preview = "(could not pre-read record; the subagent reads it for real)"

    prompt = f"""Review the iFF improvement request for design「{a.design_name}」.
Failure record: {rec_path}
{preview}
Skill: {skill}
Read {skill}/SELF_IMPROVE.md and follow the user's authorized scope. This prompt does not
itself authorize edits, memory updates, delegation, push, PR creation, or merge. If the
parent did not provide that scope, return findings and the missing authorization.

For an authorized implementation, work only in the isolated skill worktree {worktree},
branch {branch} from {a.base_branch}; preserve the test project and the running task.
Classify the failures with scripts/classify_blocker.py, fix supported causes, and retain
valid RED/GREEN plus the applicable corpus evidence. Do not relax an acceptance invariant.
Update case memory only when explicitly requested; repeated matches do not prove universality.

If PR delivery is authorized, use scripts/open_pr.py without --auto-merge. Classification
and passing tests are not merge approval. Preserve unfinished work during cleanup.
Return the actual changes/findings, validation limits, blockers, and PR URL only if created.
"""
    if a.out:
        Path(a.out).write_text(prompt, encoding="utf-8")
        print(a.out)
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
