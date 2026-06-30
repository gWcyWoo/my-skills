#!/usr/bin/env python3
"""Generate the spawn prompt for the per-design self-evolution subagent.

The orchestrator calls this AFTER a design's worker finishes, passing that worker's failure record,
then spawns a subagent with the emitted prompt. The subagent works in an isolated git worktree of the
skill repo, routes each failure (A/B/C) per SELF_IMPROVE.md, and opens ONE PR — without touching the
running task, `main`, or the test project. Imperative + tool-forcing, like make_worker_prompt.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", required=True, help="iFF skill dir (~/.claude/skills/iFF)")
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

    prompt = f"""Run the iFF per-design SELF-EVOLUTION step by EXECUTING TOOLS. Do not reply with prose; run
commands/edits and end by printing the PR/MR URL.

CONTEXT: design「{a.design_name}」just finished. Its worker failure record is at:
  {rec_path}
{preview}
You evolve the SKILL ONLY ({skill}). NEVER touch the test project, the running task, or `main`.
All work happens in an isolated git worktree and lands as ONE pull request (human-reviewed, not auto-merged).

FIRST ACTIONS (run now, in order):
  1. python3 {skill}/scripts/classify_blocker.py --failure {rec_path} --out /tmp/iff_route_{slug}.json
  2. Read {skill}/SELF_IMPROVE.md  — follow it EXACTLY (it is the authoritative procedure).

THEN:
  3. Create the worktree + branch off {a.base_branch}:
       git -C {skill}/.. worktree add {worktree} -b {branch} {a.base_branch}
     (do ALL edits inside that worktree; it is a separate checkout — `main` is untouched.)
  4. Route every item per SELF_IMPROVE.md:
       • A 确定性  → patch the script + add a MINIMAL single-concern fixture under evolution/regression/<NNNN>/;
                     prove RED on the pre-patch script (git show HEAD:<script>), then GREEN + full corpus green
                     via selftest_canvas.py. No fixture / corpus not green → do NOT commit that fix.
       • B 判断    → add or update a precedent in evolution/case_memory.md (signature/decision/why/from/seen).
                     Increment seen only for a confirmed-correct reuse; a contradicting case = counterexample →
                     rewrite it, reset seen. If a case reaches seen>=3 with zero counterexamples → GRADUATE it:
                     prefer patching the script (e.g. bind_data_slots) to feed it correctly, else add a check_*,
                     then DELETE the case from case_memory.md.
       • C 边界 / ESCALATE / NEEDS_PROBE → do NOT auto-change; record in evolution/ceilings.md (with a probe)
                     and mark the PR body `NEEDS-HUMAN`. NEVER relax an invariant to make a gate pass.
  5. Commit inside the worktree (imperative messages; reference the origin design + any corpus case id).
  6. Open the PR — ROUTER IS THE MERGE GATE (read /tmp/iff_route_{slug}.json):
       • autoEvolvable=true (only AUTO_FIX/RECORD_CEILING — NO ESCALATE/NEEDS_PROBE/REVIEW) AND full
         corpus green → pass --auto-merge (opens PR then merges; A is proven by red/green+corpus, B
         case-memory is advisory & self-correcting, so neither needs a human).
       • ANY ESCALATE/NEEDS_PROBE/REVIEW present → DO NOT pass --auto-merge; leave the PR open, body
         marked NEEDS-HUMAN. Invariant-touching changes are never auto-merged.
       python3 {skill}/scripts/open_pr.py --branch {branch} --target {a.base_branch} [--auto-merge] \\
         --title "iFF evo: {a.design_name}" --body "<A fixes / B cases / C escalations; NEEDS-HUMAN if any>"
  7. Clean up: git -C {skill}/.. worktree remove {worktree}

HARD RULES:
  • classify_blocker exiting non-zero (ESCALATE/NEEDS_PROBE/REVIEW present) means a human must decide those
    items — handle the A/B items, but leave the flagged ones as NEEDS-HUMAN in the PR; do not force them.
  • Every A patch MUST ship with a red-before/green-after corpus fixture; the whole corpus must stay green.
  • Never edit the test project. Never commit to `main`. Never auto-merge.

END by printing exactly: the PR/MR URL (from open_pr.py), and a one-line summary of A-fixes / B-cases / C-escalations.
"""
    if a.out:
        Path(a.out).write_text(prompt, encoding="utf-8")
        print(a.out)
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
