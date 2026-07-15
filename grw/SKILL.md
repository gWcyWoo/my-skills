---
name: grw
description: Run a goal-driven, regression-aware code review and repair loop over a pull request, explicit diff, or current local changes against the latest remote dev branch. Use when the user invokes `$grw`, asks to review and fix a change until clean, or wants repeated fresh reviews with all substantiated P0/P1/P2 findings fixed. Accept `--n N`, `--n=N`, or `n=N` to require N consecutive clean review passes; default to one.
---

# Goal Review Workflow

Drive one change set from reconstructed intent through independent review, surgical fixes, required verification, and consecutive clean review passes. Invoking this skill explicitly authorizes creating or reusing the matching goal and editing the local change set; it does not authorize commits, pushes, PR comments, approvals, merges, deployments, or other remote mutations.

## Parse the Request

Set `n = 1` unless exactly one of `--n N`, `--n=N`, or `n=N` is supplied. Require a base-10 integer greater than or equal to one. Reject missing, conflicting, repeated, non-integer, or smaller values visibly.

Resolve the review target in this order:

1. Use an explicitly supplied PR URL or number.
2. Use an explicitly supplied commit or diff range.
3. Otherwise review the current repository state against the latest remote `origin/dev`.

For a PR, read authoritative remote PR metadata and record its actual base ref, base commit, head ref, and head commit before computing the diff from that base commit. Never substitute a conventional or local branch for the PR's reported base.

For current changes, fetch `origin/dev` first and fail visibly if the fetch or ref resolution fails. Record the fetched `origin/dev` commit once as the immutable review base. Compare the complete current tree directly with that commit; include committed differences through `HEAD`, staged changes, unstaged changes, and every untracked non-ignored file. Enumerate those categories separately so none can disappear through Git's default diff behavior. Read full content for untracked files because a normal Git diff does not contain it. Stop with `no current changes` only when all four categories are empty.

Ensure the current worktree is the intended place to repair the target before editing it.

Load every applicable `AGENTS.md` and follow its gates. Before a behavior change, ask the repository's required strict-TDD question if the user has not already answered it. Under strict TDD, add a failing regression test before production code; if strict TDD is declined, make the fix and prove it with the smallest real verification that would fail for the defect.

## Establish the Review Contract

Reconstruct and state these facts from current evidence before editing:

1. The change objective.
2. In-scope behavior and deliverables.
3. Explicit exclusions and observable completion boundaries.
4. The complete changed-file manifest, including committed, staged, unstaged, and untracked files that belong to the target.
5. For every changed production path, the relevant entry points, callers, callees, persisted state, side effects, existing tests, and affected business flows.
6. The pre-existing flows that must remain unchanged.

Use the current user request first, then PR or issue text, commits, diff, production code, and tests as evidence. Surface contradictions instead of blending them. If material intent or boundaries remain ambiguous, obtain confirmation before fixing anything.

Treat unchanged behavior as a release invariant: unless the confirmed objective explicitly refactors or changes an existing flow, the change must not alter that flow. New-feature evidence alone never proves review success; verify regression impact on every changed production path.

## Create or Reuse the Goal

Read the current goal before creating one. Reuse it only when it represents the same target, objective, boundaries, regression invariants, verification requirements, and clean-pass threshold. If an unrelated active goal exists, stop and report the conflict; never overwrite it.

Otherwise create a goal whose objective records:

- the immutable review base and current target;
- the confirmed objective, scope, exclusions, and completion boundaries;
- the original-flow regression invariants;
- the required interface-specific verification;
- the requirement to fix every substantiated P0/P1/P2 finding; and
- completion only after `n` consecutive clean review passes.

Do not set a token budget unless the user explicitly requested one.

## Run Fresh Review Passes

Maintain `cleanPasses = 0` and `passNumber = 1`. Review sequentially; never edit while a reviewer is reading.

For every pass:

1. Re-read the current diff from the recorded base and refresh the changed-file manifest. Include all local fixes and relevant untracked files.
2. Start a new independent reviewer with no prior conversation context. Use the strongest reviewer model available when the environment exposes model selection; otherwise use a fresh peer reviewer and state that model strength cannot be selected.
3. Give the reviewer raw evidence only: repository path, target metadata, confirmed review contract, base commit, current tip and worktree state, diff, and relevant production and test paths. Do not leak previous findings, fixes, suspicions, or conclusions.
4. Make the reviewer read the implicated entry points, callers, callees, state, tests, and original flows. Require review of both requested behavior and regression impact.
5. Keep the reviewer read-only. Require findings ordered by severity, each with a tight file and line location, current-code evidence, affected flow, concrete impact, and why existing verification does not rule it out. Require every P3 to be listed and an explicit `No P0/P1/P2 findings` result when clean.

Use these severities:

- **P0:** immediate security, data-loss, corruption, or availability catastrophe.
- **P1:** core behavior is wrong, a material existing flow regresses, or release is unsafe.
- **P2:** a bounded but real correctness, reliability, or compatibility defect worth fixing before merge.
- **P3:** non-blocking improvement, maintainability suggestion, or nit.

## Adjudicate, Fix, and Verify

Re-read every implicated code path yourself. A reviewer assertion is a hypothesis until the current code proves it. Mark unsupported findings invalid with concrete evidence; never make speculative fixes.

If one or more P0/P1/P2 findings are substantiated:

1. Set `cleanPasses = 0`.
2. Fix every substantiated finding with the smallest convention-following diff. Do not refactor adjacent code unless the confirmed objective requires it.
3. Add or update regression coverage that would fail without each behavior fix.
4. Run focused tests plus all interface-specific verification required by the applicable `AGENTS.md`. Frontend changes require target-runtime flow verification; backend changes require the affected public or real integration path; full-stack changes require both.
5. Re-read the resulting diff, increment `passNumber`, and start a completely new review pass. Do not reuse a reviewer that saw an earlier pass.

If no P0/P1/P2 finding remains after evidence-based adjudication:

1. Increment `cleanPasses` by one and display every P3 finding.
2. Decide each P3 independently. Fix it only when the change is small, low risk, directly related to the confirmed objective, and clearly valuable; otherwise leave it visible with the reason.
3. Do not reset `cleanPasses` for a P3 finding or fix. If a P3 fix changes the diff, run appropriate focused verification and force a new-context review of the updated diff before completion, even when `cleanPasses >= n`.
4. If the diff did not change and `cleanPasses < n`, increment `passNumber` and start another new-context review.
5. If the diff did not change and `cleanPasses >= n`, perform the completion audit.

Do not stop merely because a review returned findings, a fix was made, or one test command passed. Continue until the threshold is met or a genuine blocker requires user authority or external state.

## Complete the Goal

Audit the current repository state against every goal boundary. Mark the goal complete only when all of the following have current evidence:

- the confirmed objective and in-scope behavior are implemented;
- every affected original flow is verified unchanged unless explicitly changed;
- every substantiated P0/P1/P2 finding is fixed;
- mandatory tests and interface-specific verification pass; and
- `n` consecutive fresh review passes contain no substantiated P0/P1/P2 findings; and
- the final diff has received a fresh review after the last P3 fix, if any.

Leave the goal incomplete when any boundary or verification remains unmet. Follow the goal tool's blocking threshold; do not mark a goal blocked merely because work is difficult, slow, or awaiting another review pass.

Report the target and base, fixes made, verification evidence, total review passes, achieved consecutive-clean count, every P3 finding and its disposition, and goal status. Clearly distinguish completed checks from recommendations. Do not claim remote PR state changed unless separately authorized and performed.
