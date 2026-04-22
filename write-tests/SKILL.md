---
name: write-tests
description: Use when the workflow needs to author test cases first — discusses scope with the user in main session, then dispatches a subagent to write test code and run the red phase. Keeps test code, rule files, and source out of the main session.
---

<role>Write-tests coordinator executing in the main session: owns the user-facing scope discussion, dispatches the `test-writer` subagent for all test code and rule work, and never reads test code, rule files, or source itself.</role>

<context>
**Why the split:** main session stays clean for the implementation step that follows (`c-0`). The `test-writer` subagent loads rules, writes test files, and runs the red phase.

**test-writer uses `general-purpose`, not a restricted subagent.** It must run tests (`Bash`), write files (`Edit`/`Write`), and read test scaffolding (`Read`). The isolation is **context**, not tool restriction. Do NOT narrow its tool inventory.

**Test rule files** (loaded by the subagent, never by the coordinator):
- `~/.claude/skills/auto-testcase/general.md` — always
- `~/.claude/skills/auto-testcase/unit.md` — unit tests
- `~/.claude/skills/auto-testcase/integration.md` — integration tests
- `~/.claude/skills/auto-testcase/e2e.md` — e2e tests

**Red phase rule** (verify against the subagent summary):
- New features → ALL new tests MUST fail.
- Bug fixes → the bug-reproducing tests MUST fail; existing tests may pass.

**The 3 mandatory STOP points:**
1. After drafting the unit test plan — user confirms/adjusts cases.
2. After asking about integration/e2e — if yes, user specifies and confirms those cases.
3. After the subagent returns its summary — user approves or requests changes.
</context>

<instructions>
**Phase 1 — Draft and confirm scope (main session).**

1. Draft a unit test plan from the requirement summary: functions/modules under test, scenarios (happy path, edge cases, errors), expected behavior per case. For code inspection, invoke `my-explore-0`.
2. **STOP #1.** Present the plan. Wait for the user to confirm or adjust.
3. Ask literally: *"Do you need integration or E2E tests?"*
4. **STOP #2** (if yes). Collect the cases, present them back, wait for explicit confirmation. If no, skip.
5. Assemble the bundle: test types, files under test with `file:line`, cases per type, requirement summary.

**Phase 2 — Dispatch the subagent.**

6. Call `Agent` with `subagent_type: "general-purpose"`, `name: "test-writer"`, `model: "opus"`, and the prompt from `## Subagent prompt template` below. Substitute ONLY the `{{...}}` placeholders; change no other text.

**Phase 3 — Review (main session).**

7. Paste the subagent's summary verbatim. Ask literally: *"Test code complete. Would you like to review or change anything before proceeding?"*
8. **STOP #3.** On user changes → `SendMessage(to: "test-writer", message: "<feedback verbatim>")` and loop back to step 7. Spawn a fresh `test-writer` only if the scope fundamentally changed (different module, different test type). Case edits within the same scope always use `SendMessage`.
9. Return control to the caller with the `<output_format>` block.
</instructions>

## Subagent prompt template

Substitute the `{{...}}` placeholders with values from the bundle in step 5. **Do not modify any other text.**

```
You are the test-writer subagent. Your job: load the relevant test rules, write test code, and run the red phase. Return a SHORT structured summary — never paste test code back into your reply.

<scope>
- Test types: {{TEST_TYPES}}
- Files under test: {{FILES}}
- Confirmed test cases:
{{CASES}}
- Requirement summary: {{REQUIREMENT_SUMMARY}}
</scope>

<instructions>
1. Load ONLY the matching rule files from `~/.claude/skills/auto-testcase/`:
   - Always → `general.md`
   - Unit tests → `unit.md`
   - Integration tests → `integration.md`
   - E2E tests → `e2e.md`
   Extract only the rule sections relevant to this task.
2. Write the test files according to the confirmed cases and the loaded rules. Use the project's existing test framework and conventions.
3. Run the test suite to verify the red phase:
   - New features: ALL new tests MUST fail. If any pass without implementation, the test is wrong — fix it.
   - Bug fixes: the new bug-reproducing tests MUST fail; existing tests may pass.
4. Return ONLY the structured summary in <subagent_output_format> below. No test code, no rule dumps.
</instructions>

<subagent_output_format>
Test files:    path:line per new/edited test file
Cases written: name → file:line, one line each
Red results:   which tests failed as expected, which unexpectedly passed (with paths)
Rule sources:  which rule files were consulted
Notes:         any deviations from the confirmed plan, with reason
Confidence:    high | medium | low
</subagent_output_format>

<subagent_final_reminders>
P0 — NEVER claim red phase passed without actually running the test suite.
P0 — NEVER paste test code back. Return file:line summaries only.
P0 — If a test unexpectedly passes, fix the test; do not lower the bar.
P1 — Use the project's existing test framework. Do not introduce a new one.
</subagent_final_reminders>
```

<examples>
<example>
SCENARIO: Caller (`tdd` Step 2) hands over a confirmed requirement summary "add email validation to signup".
ACTIONS:
  1. Draft unit plan: validateEmail() — empty, malformed, valid, unicode, max-length.
  2. STOP #1. User adds "duplicate-email" case.
  3. Ask integration/E2E. User: no.
  4. Skip STOP #2.
  5. Assemble bundle → `Agent({subagent_type:"general-purpose", name:"test-writer", model:"opus", prompt:<filled template>})`.
  6. Subagent returns: 1 test file, 6 cases, 6 red, used unit.md + general.md, confidence high.
  7. Paste summary verbatim, ask review.
  8. STOP #3. User: "looks good".
  9. Return to `tdd` with Status:confirmed.
</example>

<example label="BAD — do not do this">
- Writing test code yourself in main session "because it's small".
- Reading `~/.claude/skills/auto-testcase/*.md` in main session. The subagent loads rules; the coordinator never does.
- Skipping a STOP. "Go ahead" on an earlier step does NOT satisfy a later one.
- Spawning a fresh `test-writer` for a case edit. Use `SendMessage`.
- Reviewing test code in main session. Review is against the subagent's *summary*.
- Modifying the subagent prompt template beyond `{{...}}` substitution.
- Narrowing `test-writer`'s tool inventory to remove `Bash`. It needs Bash to run the tests.
</example>
</examples>

<output_format>
Status:        confirmed | aborted
Test files:    <copied verbatim from subagent summary>
Red results:   <copied verbatim from subagent summary>
Notes:         <any user-requested deviations resolved during review>
</output_format>

<success_criteria>
Complete when ALL of these hold:
- STOP #1 satisfied (unit plan confirmed).
- STOP #2 satisfied OR skipped per step 4.
- Subagent returned a summary with all `<subagent_output_format>` slots filled.
- STOP #3 satisfied.
- Red-phase result reported with `file:line` and matches the rule.
- No test code, rule content, or source was read into the main session.

Stop immediately when these hold.
</success_criteria>

<final_reminders>
P0 — Main session NEVER reads `~/.claude/skills/auto-testcase/*.md`, test code, or source files. Use `my-explore-0` for any source inspection.
P0 — All 3 STOP points are mandatory. A "go ahead" satisfies only the STOP it was given for.
P0 — Never claim red phase passed without the subagent reporting actual runner output.
P0 — If the `Agent` tool is missing from your inventory, you are inside a subagent — cannot dispatch. Escalate to the user; do NOT write tests in place. Subagents cannot spawn subagents (`~/.claude/skills/HARNESS_REFERENCE.md` §1).
P1 — Subagent name is `test-writer`. Reuse via `SendMessage` for follow-ups; spawn fresh only on fundamental scope change.
P1 — Paste the subagent summary verbatim. Do not summarize the summary.
P1 — Do not modify the prompt template beyond `{{...}}` substitution.
P1 — Do not narrow `test-writer`'s tool inventory.
</final_reminders>
