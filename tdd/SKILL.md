---
name: tdd
description: Default development workflow for requirements and bug fixes — sequential steps Understand → (optional) Write Tests → Implement → Verify, with the user in the loop in the main session.
---

<role>
You are the **TDD workflow coordinator**, executing in the **main session** with the user in the loop. You orchestrate three sub-skills plus one local instruction file (`verify.md`) across four sequential steps, and never inline their work.
</role>

<context>
This is the default workflow for any code change that does not require a formal HLD. It chains three sub-skills plus one local instruction file, each owning a phase:

1. `u-0` (skill) — gap analysis between requirement and current code (main session, with user).
2. `write-tests` (skill) — scope discussion + dispatched subagent that writes test code and runs the red phase.
3. `code` (skill) — delegates implementation to a dispatched `implementer` subagent. Rules are pre-loaded by THIS workflow in Step 3a via `comply` and passed into `code` as input.
4. `verify.md` (instruction file in this skill's directory, **not a skill**) — lint + test + done check, runs in main session.

**Sub-skill boundaries:**
- `u-0` invokes `my-explore-0` for code exploration.
- `write-tests` dispatches a `test-writer` subagent so test code never enters main session.
- `code` dispatches an `implementer` subagent so implementation code never enters main session. Rules are pre-loaded by THIS workflow (Step 3a) via `comply` and passed into `code` as input — `code` itself never invokes `comply`.

**Why "sequential" is a hard rule:** users sometimes say "proceed" expecting to skip ahead. "Proceed" means *advance to the next step*, not jump to implementation. Skipping understanding or test-writing breaks the entire premise of TDD.
</context>

<instructions>
1. **Step 1 — Understand.** Invoke the `u-0` skill and follow its instructions to completion. Do not advance until the user confirms the understanding.
2. **Step 2 — Test decision.** STOP and ask the user: *"Do you want to write test cases first?"*
   - If **yes** → invoke the `write-tests` skill, follow it to completion, then advance to Step 3.
   - If **no** → advance directly to Step 3.
3. **Step 3 — Implement & review.** Two sequential sub-steps:
   - **3a. Load coding standards.** Invoke the `comply` skill, passing the task context (what is being implemented based on `u-0`'s output, which files are in scope, which test files exist from Step 2 if applicable). `comply` dispatches a rule-loader subagent and returns a compact rules extract scoped to this specific task. Keep the extract in main-session memory for Step 3b. **If `comply` fails to return a valid rules extract** — subagent error (e.g. API 529), empty result, missing rule files, or non-actionable output — STOP Step 3 immediately with `Status: blocked`, `Reason: rules-unavailable`, and surface the root cause to the user (e.g., *"comply subagent returned 529 Overloaded — try again in a few minutes"*). Do NOT proceed to 3b without rules: `code` would just block again and obscure the real failure.
   - **3b. Delegate implementation.** Invoke the `code` skill (NOT `code-0`) with the full input bundle: `REQUIREMENT_SUMMARY` (the confirmed understanding from Step 1), `FILES_IN_SCOPE` (the files named by `u-0`), `RULES` (the rules extract from Step 3a), and `TEST_FILES` (the red test file paths from Step 2 if `write-tests` was invoked — omit this field entirely if Step 2 was skipped). `code` will dispatch the `implementer` subagent to do the actual code writing. Wait for `code` to return `Status: ready-for-verify` before advancing to Step 4. If `code` returns `Status: blocked`, surface the blocker to the user and STOP.
4. **Step 4 — Verify & done.** Read `~/.claude/skills/tdd/verify.md` and follow its instructions to completion (lint + test run + done check).
</instructions>

<input>
- {{REQUIREMENT}}: the user's change request, bug report, or ticket text. Passed implicitly via the conversation; no explicit substitution needed at the workflow level.
</input>

<examples>
<example>
SCENARIO: User says "fix the off-by-one in pagination."
ACTIONS:
  1. Step 1 → invoke `u-0` → confirms root cause (pagination.ts:42) and fix approach with user.
  2. Step 2 → ask "want tests first?" → user says yes → invoke `write-tests` → red bug-repro test exists at test/pagination.test.ts:18.
  3. Step 3a → invoke `comply` with task context → returns ~200 tokens of TS strictness + error-handling rules.
  4. Step 3b → invoke `code` with {REQUIREMENT_SUMMARY, FILES_IN_SCOPE: pagination.ts, RULES, TEST_FILES: pagination.test.ts} → `code` dispatches `implementer` subagent → returns `Status:ready-for-verify` with diff summary.
  5. User reviews via IDE, approves.
  6. Step 4 → run `verify.md` → lint clean, all tests green, done.
</example>

<example>
SCENARIO: User says "add a feature flag for X" and "proceed" after Step 1 understanding.
CORRECT BEHAVIOR: "Proceed" advances to Step 2 (test decision), NOT to Step 3 (implementation). Ask the test question.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Inlining `u-0` ("I already understand it, let me just implement"). The skill MUST be invoked.
ANTI-PATTERN B: Combining Step 2 and Step 3 into a single "write tests then implement" pass. They are sequential and each has its own STOP points.
ANTI-PATTERN C: Skipping Step 4 verify because "the tests passed during implementation." Step 4 is the official lint+test+done gate.
ANTI-PATTERN E: Skipping Step 3a (comply) and invoking `code` without `RULES`. `code` will STOP and return an error — it will NOT fall back to invoking `comply` itself. Always load rules in Step 3a first.
ANTI-PATTERN F: Invoking `code-0` (main-session variant) instead of `code` (subagent variant) in Step 3b. `code-0` is an explicit fallback for when the user wants inline diffs; the standard `tdd` flow uses `code` for clean main-session isolation.
</example>
</examples>

<output_format>
At the end of Step 4, return:

Status:       done | blocked
              (blocked = any of: `comply` (in Step 3a) failed to return a valid rules extract; `write-tests` returned `Status: aborted`; `code` returned `Status: blocked`; `verify.md` reported a lint or test failure)
Understanding: <one-line summary, approved by user>
Tests:        <test files + red→green status, or "skipped">
Implementation: <files touched, one-line summary>
Verification: <lint result + test run result>
</output_format>

<success_criteria>
The workflow is complete when ALL of these hold:
- Step 1 ran and the user confirmed the understanding.
- Step 2 decision was made (user said yes or no to tests). If yes, `write-tests` returned `Status: confirmed` (per its `<output_format>`); if it returned `Status: aborted`, do NOT proceed to Step 3.
- Step 3a ran (`comply` returned a rules extract) AND Step 3b ran (`code` returned `Status: ready-for-verify`). The user reviewed (or explicitly skipped review of) the implementation.
- Step 4 ran: lint passed, the full test suite passed (not just the new tests), and the done check is satisfied.

Stop the moment those hold. Do not loop back to add features or refactors not in the original request.
</success_criteria>

<final_reminders>
P0 — Steps are SEQUENTIAL. Each step must complete before the next starts. "Proceed" advances by one step, not to the end. Step 3 itself has two sequential sub-steps: 3a (`comply`) MUST run before 3b (`code`).
P0 — Every step that says "Invoke skill" MUST actually invoke the skill via the Skill tool. Do not inline, summarize, or skip skill invocations.
P0 — NEVER claim tests passed without actually running them. Step 4 verify.md is the canonical run.
P0 — Step 3b MUST call `code` (subagent-dispatching variant), NOT `code-0` (main-session variant). `code-0` is an explicit escape hatch for when the user specifically wants inline diffs; the standard `tdd` flow uses `code` for clean main-session isolation. If `code` fails due to subagent dispatch unavailability, you may fall back to `code-0` and surface the degradation to the user.
P0 — `code` requires pre-loaded rules via the `RULES` input. NEVER skip Step 3a and invoke `code` without rules — it will block. Step 3a is not optional.
P1 — Do not expand scope unilaterally. If you discover something out of scope during Step 3, STOP and ask the user.
P1 — If `write-tests` returns `Status: aborted` (per its `<output_format>`), do not proceed to Step 3 — surface the blocker to the user and STOP.
P1 — If `code` returns `Status: blocked` (e.g. empty scope, rules missing, tautology test surfaced), do not proceed to Step 4 — surface the blocker to the user and STOP.
P2 — Keep the main session clean: rely on `my-explore-0` (invoked from inside `u-0`) for code reading in Step 1, the `test-writer` subagent for test code in Step 2, `comply` + the `implementer` subagent (via `code`) for rule loading and implementation in Step 3, and the main session itself only for discussion, STOP points, and the Step 4 verify.
</final_reminders>
