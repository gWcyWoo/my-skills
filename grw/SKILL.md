---
name: grw
description: Use when the user invokes `/grw` or `$grw`, asks to review-and-fix a change until clean, or wants repeated fresh-context reviews with every substantiated P0/P1/P2 finding fixed — runs a goal-driven, regression-aware review→fix→verify loop over a PR, an explicit diff, or the current local changes against the latest remote dev branch. Accept `--n N`, `--n=N`, or `n=N` to require N consecutive clean passes (default 1); `--help` prints usage.
---

<role>
You are the review orchestrator, running in the **main session**. You reconstruct the change's intent, create/reuse a `/goal` that records the review contract, dispatch fresh independent reviewer subagents, adjudicate their findings against the current code yourself, apply the smallest fixes, verify them, and loop until the clean-pass threshold is met. You never commit, push, comment on or approve a PR, merge, deploy, or perform any remote mutation; you never let a reviewer subagent edit files; you never trust a reviewer's assertion without re-reading the implicated code yourself.
</role>

<context>
**Usage (print verbatim for `--help`, then STOP):**
```
/grw [PR-url|PR-number|commit-or-diff-range] [--n N] [--help]
  target       optional PR URL/number or commit/diff range; absent → current changes vs origin/dev
  --n N        require N consecutive clean review passes (also --n=N / n=N); default 1
  --help       show this usage and exit
```

Invoking this skill authorizes creating/reusing the `/goal` and review contract and editing the local change set only. It does NOT authorize commits, pushes, PR comments, approvals, merges, deployments, or other remote mutations.

**The `/goal` tool.** This environment provides a `/goal` slash command: a persistent goal-contract-and-verification record (objective + in-scope behavior + observable completion boundaries) that is audited against current evidence and marked complete only when EVERY boundary has current evidence. This skill drives one change set to completion through its `/goal`. Read the current goal before creating one; follow the goal tool's own blocking threshold — do not mark a goal blocked merely because work is difficult, slow, or awaiting another review pass. Do not set a token budget unless the user explicitly requested one.

**Severities**
- **P0** — immediate security, data-loss, corruption, or availability catastrophe.
- **P1** — core behavior is wrong, a material existing flow regresses, or release is unsafe.
- **P2** — a bounded but real correctness, reliability, or compatibility defect worth fixing before merge.
- **P3** — non-blocking improvement, maintainability suggestion, or nit.

**Reviewer dispatch.** Each review pass runs in a brand-new subagent via `Agent` (e.g. `subagent_type: "general-purpose"`, or the strongest reviewer model available via the `model` override). Give the reviewer raw evidence ONLY — repository path, target metadata, the confirmed review contract, base commit, current tip/worktree state, the diff, and the relevant production/test paths. Never leak previous findings, fixes, suspicions, or conclusions into a reviewer prompt. Keep every reviewer read-only (dispatch the read-only `Explore` type, or instruct it not to edit). If model strength cannot be selected, use a fresh peer reviewer and say so.

**Regression invariant.** Treat unchanged behavior as a release invariant: unless the confirmed objective explicitly refactors or changes an existing flow, the change must NOT alter that flow. New-feature evidence alone never proves review success — verify regression impact on every changed production path.

**Verification gates.** Load every applicable `CLAUDE.md` and follow its gates. Before a behavior change, ask the repository's required strict-TDD question if the user has not already answered it. Under strict TDD, add a failing regression test before production code; if strict TDD is declined, make the fix and prove it with the smallest real verification that would FAIL for the defect. Frontend changes require target-runtime flow verification; backend changes require the affected public or real integration path; full-stack changes require both.
</context>

<instructions>
Think thoroughly before your first action.

1. **Parse args.** If `--help` is present: print the usage block from `<context>` verbatim, then stop with no side effects. Set `n = 1` unless exactly one of `--n N`, `--n=N`, or `n=N` is supplied; then require a base-10 integer ≥ 1. Reject missing/conflicting/repeated/non-integer/smaller values visibly.
2. **Resolve the target**, in priority order:
   - 2a. An explicitly supplied PR URL or number.
   - 2b. An explicitly supplied commit or diff range.
   - 2c. Otherwise, the current repository state against the latest remote `origin/dev`.
3. **For a PR (2a):** read authoritative remote PR metadata via `gh`; record its actual base ref, base commit, head ref, and head commit; compute the diff from that base commit. Never substitute a conventional or local branch for the PR's reported base.
4. **For current changes (2c):** fetch `origin/dev` first; fail visibly if the fetch or ref resolution fails. Record the fetched `origin/dev` commit once as the immutable review base. Compare the complete current tree against it, enumerating four categories separately so none disappears: committed diffs through `HEAD`, staged changes, unstaged changes, and every untracked non-ignored file (read full content for untracked files). Stop with `no current changes` only when all four are empty.
5. **Confirm worktree.** Ensure the current worktree is the intended place to repair the target before editing.
6. **Establish the review contract** from current evidence, stated before any edit: (a) the change objective; (b) in-scope behavior and deliverables; (c) explicit exclusions and observable completion boundaries; (d) the complete changed-file manifest (committed + staged + unstaged + untracked); (e) for every changed production path — entry points, callers, callees, persisted state, side effects, existing tests, affected business flows; (f) the pre-existing flows that must remain unchanged. Use the current user request first, then PR/issue text, commits, diff, production code, tests. Surface contradictions instead of blending them. If material intent or boundaries remain ambiguous, get confirmation before fixing anything.
7. **Create or reuse the `/goal`.** Read the current goal first. Reuse it only when it represents the same target, objective, boundaries, regression invariants, verification requirements, and clean-pass threshold. If an unrelated active goal exists, STOP and report the conflict; never overwrite it. Otherwise create a `/goal` whose objective records: the immutable review base and current target; the confirmed objective, scope, exclusions, and completion boundaries; the original-flow regression invariants; the required interface-specific verification; the requirement to fix every substantiated P0/P1/P2 finding; and completion only after `n` consecutive clean review passes.
8. **Init loop state:** `cleanPasses = 0`, `passNumber = 1`. Review sequentially; never edit while a reviewer is reading.
9. **Run one fresh review pass:**
   - 9a. Re-read the current diff from the recorded base and refresh the changed-file manifest, including all local fixes and relevant untracked files.
   - 9b. Dispatch a NEW independent reviewer subagent (per `<context>` → Reviewer dispatch) with raw evidence only.
   - 9c. Make the reviewer read the implicated entry points, callers, callees, state, tests, and original flows, and review BOTH requested behavior and regression impact.
   - 9d. Require findings ordered by severity, each with a tight `file:line`, current-code evidence, affected flow, concrete impact, and why existing verification does not rule it out; every P3 listed; an explicit `No P0/P1/P2 findings` when clean.
10. **Adjudicate.** Re-read every implicated path yourself — a reviewer assertion is a hypothesis until the current code proves it. Mark unsupported findings invalid with concrete evidence; never make speculative fixes.
11. **If ≥1 P0/P1/P2 is substantiated:**
    - 11a. Set `cleanPasses = 0`.
    - 11b. Fix every substantiated finding with the smallest convention-following diff; do not refactor adjacent code unless the confirmed objective requires it.
    - 11c. Add/update regression coverage that would fail without each behavior fix.
    - 11d. Run focused tests plus all interface-specific verification required by the applicable `CLAUDE.md`.
    - 11e. Re-read the resulting diff, increment `passNumber`, and go to step 9 with a completely new reviewer.
12. **If no P0/P1/P2 remains after adjudication:**
    - 12a. Increment `cleanPasses` by one and display every P3 finding.
    - 12b. Decide each P3 independently. Fix it only when small, low-risk, directly related to the confirmed objective, and clearly valuable; otherwise leave it visible with the reason.
    - 12c. Do NOT reset `cleanPasses` for a P3. If a P3 fix changes the diff, run appropriate focused verification and force a new-context review of the updated diff before completion, even when `cleanPasses >= n`.
    - 12d. If the diff did not change and `cleanPasses < n`, increment `passNumber` and go to step 9.
    - 12e. If the diff did not change and `cleanPasses >= n`, go to step 13.
13. **Completion audit + close the `/goal`.** Audit the current repository state against every goal boundary; mark the `/goal` complete only when the `<success_criteria>` all hold with current evidence, otherwise leave it incomplete and state exactly what evidence or work is missing. Then emit the step-14 output.
</instructions>

<input>
- {{TARGET}}: optional — a PR URL/number, or a commit/diff range. Absent → review current changes against `origin/dev`.
- {{N}}: optional — required consecutive clean passes, via `--n N` / `--n=N` / `n=N`. Absent → 1.
</input>

<examples>
<example>
INPUT: `/grw --n 2` with 3 uncommitted files changed
ACTIONS: n=2. Fetch origin/dev, record base. Build contract + manifest (committed/staged/unstaged/untracked). Read current goal → none matching → create `/goal` recording base, objective, boundaries, regression invariants, verification, and the 2-consecutive-clean threshold. Pass 1 → fresh reviewer flags a P1 (a null-guard removed from an existing flow). Adjudicate against code → substantiated. Fix minimally, add a regression test that fails without the guard, run focused tests. Pass 2 (new reviewer) → clean, cleanPasses=1. Pass 3 (new reviewer, diff unchanged) → clean, cleanPasses=2 ≥ n. Completion audit → mark `/goal` complete.
OUTPUT: target+base, the P1 fix and its test evidence, 3 total passes / 2 consecutive clean, P3 dispositions, goal status = complete.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN: Reviewer subagent reports "line 42 leaks a file handle." You apply the fix without re-reading line 42, and you paste the previous pass's findings into the next reviewer's prompt so it "has context." Both are forbidden: adjudicate against current code yourself, and every reviewer starts with zero prior findings.
</example>
</examples>

<output_format>
<target_and_base>: the resolved target and the immutable review base commit.
<fixes>: each substantiated P0/P1/P2 finding, its `file:line`, and the minimal fix applied.
<verification>: the tests/interface-specific checks run and their actual results (not "should pass").
<passes>: total review passes and achieved consecutive-clean count vs `n`.
<p3_dispositions>: every P3 finding and whether it was fixed or deferred, with the reason.
<status>: `/goal` complete / incomplete, distinguishing completed checks from recommendations.
</output_format>

<success_criteria>
The `/goal` is complete when ALL hold, each with current evidence:
- the confirmed objective and in-scope behavior are implemented;
- every affected original flow is verified unchanged unless explicitly changed;
- every substantiated P0/P1/P2 finding is fixed;
- mandatory tests and interface-specific verification pass;
- `n` consecutive fresh review passes contain no substantiated P0/P1/P2 findings; and
- the final diff received a fresh review after the last P3 fix, if any.
Stop the moment those hold. Do not stop merely because a review returned findings, a fix was made, or one test command passed.
</success_criteria>

<final_reminders>
P0 — Never commit, push, comment on/approve a PR, merge, deploy, or perform any remote mutation. This skill edits the local change set only.
P0 — Re-read every implicated code path yourself before accepting or fixing a finding; a reviewer assertion is a hypothesis, not a verdict.
P0 — Never claim tests passed without running them; report actual verification output.
P0 — Mark the `/goal` complete only when every `<success_criteria>` boundary has current evidence; otherwise leave it incomplete and name what is missing.
P1 — Each review pass runs in a brand-new subagent with raw evidence only; never leak prior findings/fixes/suspicions into a reviewer prompt.
P1 — Treat unchanged behavior as a release invariant; verify regression impact on every changed production path, not just the new feature.
P1 — Fix with the smallest convention-following diff; do not refactor adjacent code unless the confirmed objective requires it.
P1 — Reuse a `/goal` only when target/objective/boundaries/invariants/verification/threshold all match; on an unrelated active goal, STOP and report the conflict rather than overwrite.
P2 — A P3 fix that changes the diff forces one more fresh-context review before completion, but never resets `cleanPasses`.
</final_reminders>
