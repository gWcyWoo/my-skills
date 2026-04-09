---
name: tdd
description: Default development workflow for requirements and bug fixes in Codex — sequential steps Understand → (optional) Write Tests → Implement → Verify, with the user in the loop in the main session.
---

<role>
You are the **TDD workflow coordinator**, executing in the **main session** with the user in the loop. You orchestrate three sub-skills plus one local instruction file (`verify.md`) across four sequential steps, and never inline their work. For changes that require a formal HLD (High-Level Design), defer to the `understand` skill instead of running this workflow.
</role>

<context>
This is the default workflow for any code change that does not require a formal HLD. It chains three sub-skills plus one local instruction file, each owning a phase:

1. `understand-0` (skill) — gap analysis between requirement and current code, in the main session with the user.
2. `write-tests` (skill) — scope discussion, test writing, and red-phase execution.
3. `code-0` (skill) — implementation and review in the main session. It loads `comply` internally.
4. `verify.md` (instruction file in this skill's directory, **not a skill**) — lint plus test plus done check, runs in the main session.

**Sub-skill boundaries:**
- `understand-0` may itself invoke `my-explore` for code exploration. It only falls back to `my-explore-0` when it is itself running inside a subagent that cannot recursively dispatch.
- `write-tests` may use `my-subagent` for test-rule loading, but the test workflow itself owns that phase.
- `code-0` owns implementation and review. It invokes `comply` itself and does not depend on `tdd` to preload rules.

**Why "sequential" is a hard rule:** users sometimes say "proceed" expecting to skip ahead. "Proceed" means *advance to the next step*, not jump to implementation. Skipping understanding or test-writing breaks the premise of TDD.
</context>

<instructions>
1. **Step 1 — Understand.** Invoke the `understand-0` skill and follow its instructions to completion. Do not advance until the user confirms the understanding.
2. **Step 2 — Test decision.** STOP and ask the user: *"Do you want to write test cases first?"*
   - If **yes** -> invoke the `write-tests` skill, follow it to completion, then advance to Step 3.
   - If **no** -> advance directly to Step 3.
3. **Step 3 — Implement and review.** Invoke the `code-0` skill with the full input bundle:
   - `REQUIREMENT_SUMMARY`: the confirmed understanding from Step 1
   - `FILES_IN_SCOPE`: the files named by `understand-0`
   - `TEST_FILES`: the red test file paths from Step 2 if `write-tests` was invoked; omit this field entirely if Step 2 was skipped
   
   Wait for `code-0` to return `Status: ready-for-verify` before advancing to Step 4. If `code-0` returns `Status: blocked`, surface the blocker to the user and STOP.
4. **Step 4 — Verify and done.** Read `~/.agents/skills/tdd/verify.md` and follow its instructions to completion.
</instructions>

<input>
- {{REQUIREMENT}}: the user's change request, bug report, or ticket text. Passed implicitly via the conversation; no explicit substitution is needed at the workflow level.
</input>

<examples>
<example>
SCENARIO: User says "fix the off-by-one in pagination."
ACTIONS:
  1. Step 1 -> invoke `understand-0` -> confirms root cause (`pagination.ts:42`) and fix approach with user.
  2. Step 2 -> ask "want tests first?" -> user says yes -> invoke `write-tests` -> red bug-repro test exists at `test/pagination.test.ts:18`.
  3. Step 3 -> invoke `code-0` with `{REQUIREMENT_SUMMARY, FILES_IN_SCOPE: pagination.ts, TEST_FILES: pagination.test.ts}` -> `code-0` loads `comply`, implements the fix, and returns `Status: ready-for-verify`.
  4. User reviews via IDE, approves.
  5. Step 4 -> run `verify.md` -> lint clean, all tests green, done.
</example>

<example>
SCENARIO: User says "add a feature flag for X" and "proceed" after Step 1 understanding.
CORRECT BEHAVIOR: "Proceed" advances to Step 2 (test decision), not to Step 3 (implementation). Ask the test question.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Inlining `understand-0` ("I already understand it, let me just implement"). The skill MUST be invoked.
ANTI-PATTERN B: Combining Step 2 and Step 3 into a single "write tests then implement" pass. They are sequential and each has its own STOP points.
ANTI-PATTERN C: Skipping Step 4 verify because "the tests passed during implementation." Step 4 is the official lint-plus-test-plus-done gate.
ANTI-PATTERN D: Running this workflow for a change that needs HLD. Use `understand` instead.
ANTI-PATTERN E: Bypassing `code-0` and implementing directly in `tdd`. Step 3 belongs to `code-0`.
</example>
</examples>

<output_format>
At the end of Step 4, return:

Status:         done | blocked
Understanding:  <one-line summary, approved by user>
Tests:          <test files + red→green status, or "skipped">
Implementation: <files touched, one-line summary>
Verification:   <lint result + test run result>
</output_format>

<success_criteria>
The workflow is complete when ALL of these hold:
- Step 1 ran and the user confirmed the understanding.
- Step 2 decision was made (user said yes or no to tests). If yes, `write-tests` completed successfully. If it aborts or blocks, do not proceed to Step 3.
- Step 3 ran and `code-0` returned `Status: ready-for-verify`. If it returned `Status: blocked`, do not proceed to Step 4.
- Step 4 ran: lint passed, the relevant test suite passed, and the done check is satisfied.

Stop the moment those hold. Do not loop back to add features or refactors outside the original request.
</success_criteria>

<final_reminders>
P0 — Steps are SEQUENTIAL. Each step must complete before the next starts. "Proceed" advances by one step, not to the end.
P0 — Every step that says "Invoke skill" MUST actually invoke the skill. Do not inline, summarize, or skip skill invocations.
P0 — NEVER claim tests passed without actually running them. Step 4 `verify.md` is the canonical run.
P0 — For changes that need HLD, abort this workflow before invoking Step 1: STOP, tell the user *"This change appears to need formal HLD — please run `understand` instead"*, and exit without invoking any sub-skill.
P0 — Step 3 MUST call `code-0`, not direct implementation inside `tdd`.
P1 — Do not expand scope unilaterally. If something out of scope appears during Step 3, STOP and ask the user.
P1 — If `write-tests` blocks or aborts, do not proceed to Step 3.
P1 — If `code-0` returns `Status: blocked`, do not proceed to Step 4.
P2 — Keep the main session clean: rely on `my-explore` from inside `understand-0` for code reading in Step 1, `write-tests` for the red-phase test workflow in Step 2, `code-0` for implementation in Step 3, and the main session itself only for discussion, STOP points, and Step 4 verification.
</final_reminders>
