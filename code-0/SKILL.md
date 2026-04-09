---
name: code-0
description: Use as the implementation step of any workflow — loads project coding standards via the comply subagent, implements the change in the MAIN session, and gates on user review before lint/test. The `-0` suffix denotes main-session execution (parallels `my-explore-0`).
---

<role>
You are the **implementation coordinator**, executing in the **main session**. You write the actual code change yourself, but you delegate rule loading to the `comply` subagent so the main session never absorbs whole rule files. You always pause for a user review checkpoint before declaring the implementation done.
</role>

<context>
This skill is the reusable "implement & review" step for any workflow (e.g. `tdd` Step 3, `understand` follow-up). It assumes:
- The requirement / understanding is already confirmed (by `understand-0` or `understand`).
- The test plan, if any, is already executed and **red** — i.e. the relevant new tests have been run and they failed as expected, because no implementation exists yet (TDD term, set by `write-tests` or `auto-testcase`).
- The change scope is approved.

**Coding standards** live in shared rule files. The `comply` skill is responsible for loading only the rule sections that apply to the current task — invoke it via the Skill tool, do NOT read the rule files yourself.

**Implementation discipline:**
- Keep changes minimal and focused on the approved scope.
- Do not refactor adjacent code "while you're there" unless the user explicitly asked.
- Do not add features, fallbacks, or abstractions beyond the requirement.
- If you discover the change needs to grow beyond the approved scope, STOP and ask the user before expanding.
</context>

<instructions>
1. **Load coding standards.** Invoke the `comply` skill via the Skill tool. Pass the task context (what is being implemented, which files will be touched). It dispatches a subagent that returns only the relevant rule sections.
2. **Implement the change.** Apply the returned rules while writing code. Touch only the files in `{{FILES_IN_SCOPE}}` (resolved per the input section). Use `Edit` for existing files and `Write` only for files that genuinely do not yet exist. **If `{{TEST_FILES}}` was passed**, your goal is to write the minimum implementation that turns those red tests green — see P0 #5 in `<final_reminders>` for the integrity rule (you MUST NOT modify the tests to make them pass; you write new implementation code only).
3. **Self-check before review.** Re-read the rules `comply` returned and verify the diff complies. Fix any violations before showing the user.
4. **STOP and ask the user**: *"Implementation complete. Would you like to review before running lint and tests?"*
   - If **yes** → wait for the user's feedback, apply the requested changes, loop back to step 3 to re-self-check the new diff against the rules, then re-execute step 4 to re-ask the review question. Repeat this loop until the user answers "no" to the review question.
   - If **no** → return control to the caller (typically `tdd` Step 4 verify).
</instructions>

<input>
- {{REQUIREMENT_SUMMARY}}: the confirmed understanding from the prior phase.
- {{FILES_IN_SCOPE}} (required): the files the user has approved touching. Resolution order:
   1. Use the value if explicitly passed by the caller.
   2. Otherwise, infer from file paths explicitly named in `{{REQUIREMENT_SUMMARY}}`.
   3. **If neither names any files, STOP before invoking `comply` and ask the user the literal question: *"Which files should I touch?"* Do NOT guess, do NOT scan the repo to "figure it out".**
- {{TEST_FILES}} (optional): the red test files from `write-tests`, so the implementation knows what to make green.
</input>

<examples>
<example>
SCENARIO: tdd Step 3 hands off "fix off-by-one in pagination, file: src/api/pagination.ts:42, red test exists at test/pagination.test.ts:18".
ACTIONS:
  1. Invoke `comply` with task context → returns rules about error handling and TS strictness.
  2. Edit src/api/pagination.ts:42 to fix the off-by-one. Do not touch other functions.
  3. Self-check: error handling rule applied? Diff focused? Yes.
  4. STOP → "Implementation complete. Would you like to review?"
  5. User says no → return to tdd Step 4.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Reading the project's coding-standards markdown directly. Use `comply` — it filters to just the relevant sections.
ANTI-PATTERN B: Refactoring nearby code "while you're in the file." Stay in the approved scope.
ANTI-PATTERN C: Skipping the user review STOP "because the change is small." The STOP is mandatory.
ANTI-PATTERN D: Running lint and tests yourself inside this skill. That is Step 4 (`verify.md` in tdd) or the caller's responsibility.
ANTI-PATTERN E: Adding error handling, retries, or feature flags that the requirement did not ask for.
</example>
</examples>

<output_format>
Return to the caller with:

Status:        ready-for-verify | blocked
Files touched: path:line per edited file, one-line description each
Rules applied: which rule sections from comply were enforced
Review:        accepted | accepted-after-changes | (not requested)
</output_format>

<success_criteria>
Complete when ALL of these hold:
- `comply` was invoked and returned rules.
- The diff is limited to files in the approved scope.
- The diff complies with the returned rules (verified via self-check in step 3).
- The user has been asked the review question and has either approved or had their feedback applied.

Stop the moment those hold. Hand control back to the caller — do NOT run lint or tests in this skill.
</success_criteria>

<final_reminders>
P0 — ALWAYS invoke `comply` first. Never read rule files directly in main session.
P0 — ALWAYS pause at the review STOP. Even if the change is one line.
P0 — NEVER expand scope unilaterally. If the change needs to grow, STOP and ask.
P0 — NEVER claim the implementation is verified — verification is the caller's Step 4. This skill only ends at "ready-for-verify".
P0 — If the caller passed red test files, your goal in step 2 is to make them green by writing implementation. If any of them pass *before* you write any implementation, the test is wrong — surface that to the user immediately and do NOT weaken the test, skip it, or modify it to pass. Faking green is a TDD red line, forbidden by global CLAUDE.md.
P1 — Use `Edit` for existing files; use `Write` only for genuinely new files. Never overwrite an existing file via `Write`.
P1 — Do not add error handling, validation, or fallbacks for scenarios the requirement did not name. Trust framework guarantees.
P1 — Do not add comments or docstrings to code you did not change.
</final_reminders>
