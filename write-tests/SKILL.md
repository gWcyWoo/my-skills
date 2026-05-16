---
name: write-tests
description: Use when the workflow needs to author test cases first in Codex — dispatches a `test-writer` subagent to plan, revise, and implement tests, while the main session relays user review at each STOP. Keeps test code, rule files, and source out of the main session.
---

<role>Write-tests coordinator executing in the main session: invokes exactly ONE `test-writer` subagent through `my-subagent` for the full planning→implementation arc, relays user review at each STOP via `send_input`, and discusses integration/E2E scenarios with the user in natural language before handing them to the subagent for formalization. Never drafts unit cases, never formalizes any test cases (unit / integration / E2E), never writes or edits test code, never reads test code, rule files, or source files into its own context. Code understanding goes through `u0`, which returns summaries and routes any needed exploration.</role>

<context>
**Execution shape.** Main session runs the user-facing STOPs and its own requirement understanding. A single `test-writer` subagent (`agent_type: "worker"`, `model: "gpt-5.4"`) persists across the whole arc: drafts unit plan → revises on feedback → optionally drafts integration/E2E plan → revises → implements + red phase. Revisions and mode switches are sent via `send_input` to the same subagent. A new session always invokes a fresh subagent; within a session there is exactly one `test-writer`.

**Address by agent ID, NOT by name.** The Codex child-agent tool returns an agent ID. Capture the `agent_id` returned by the initial `my-subagent` invocation IMMEDIATELY, store it as `<test_writer_agent_id>`, and use that ID in EVERY subsequent `send_input`. Never address by `"test-writer"` after the initial invocation.

**test-writer uses a normal Codex child-agent toolset, not a restricted subagent.** It must run tests (`exec_command`), write files (`apply_patch` or project-native formatting tools), read test scaffolding through allowed Codex exploration tools, and explore code through `my-explore-0` first, escalating to custom agent `my-explore` only when needed. The isolation is **context**, not tool restriction. Do NOT narrow its tool inventory.

**Test rule files** (loaded by the subagent, never by the coordinator):
- `~/.agents/skills/auto-testcase/general.md` — always
- `~/.agents/skills/auto-testcase/unit.md` — unit tests
- `~/.agents/skills/auto-testcase/integration.md` — integration tests
- `~/.agents/skills/auto-testcase/e2e.md` — e2e tests

**Red phase rule** (verify against the subagent summary):
- New features → ALL new tests MUST fail.
- Bug fixes → the bug-reproducing tests MUST fail; existing tests may pass.

**Two modes of producing a plan:**
- **Unit** — subagent-drafted from rules + code exploration. The subagent proposes cases; user reviews.
- **Integration / E2E** — co-defined in natural-language discussion between main session and user FIRST; the subagent then formalizes the agreed scenarios into rule-compliant cases. The subagent never invents integration/E2E scenarios on its own.

**The 3 mandatory STOP points:**
1. After the subagent returns the unit test plan — user confirms/adjusts cases. Revisions loop via `send_input`.
2. After the subagent returns the formalized integration/E2E plan — user approves/adjusts the formalization. Note: BEFORE this STOP, main session and user MUST have already agreed on the scenarios in natural language (step 7); the subagent's job at step 8 is formalization only. Skipped entirely if the user said no in step 5.
3. After the subagent returns the implementation + red phase summary — user approves or requests changes.
</context>

<instructions>
Think thoroughly before your first action.

**Phase 1 — Spawn and get unit test plan.**

1. Invoke `my-subagent` with `agent_type: "worker"`, `model: "gpt-5.4"`, and `task_prompt` set to the prompt from `## Initial spawn prompt` below. Substitute ONLY the `{{...}}` placeholders; change no other text. Never invoke a second `test-writer` in the same session.
1a. **Capture the agent ID immediately.** The `my-subagent` invocation returns an `agent_id`. Save it as `<test_writer_agent_id>` BEFORE doing anything else with the response. This ID is the ONLY reliable way to address the subagent later.
2. Wait for the subagent to return the unit test plan. Do NOT act on the plan or start any side-work before STOP #1.
3. **STOP #1.** Paste the plan verbatim (no edits, no commentary). Ask the user literally: *"Confirm this unit test plan or request changes?"*
4. Apply exactly one branch based on the user response:
   - **Confirmed** → proceed to step 5.
   - **Changes requested** → call `send_input(target: "<test_writer_agent_id>", ...)` using the "Revise plan" template with the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 2. Do NOT invoke a new subagent; do NOT apply the changes yourself; do NOT address by name.

**Phase 2 — Optional integration/E2E plan (co-defined with user, then formalized by subagent).**

5. Ask the user literally: *"Do you need integration or E2E tests?"*
6. Apply exactly one branch based on the user answer:
   - **No** (default) → skip to step 11.
   - **Yes** → proceed to step 7.
7. **Discuss scope and scenarios collaboratively with the user.** Cover two things in the same conversation: (a) which test type(s) they want — integration, e2e, or both; (b) which target scenarios. Lead by proposing 2–5 candidate scenarios in plain natural language, drawn from your own understanding (`u0` context, the requirement, key user journeys, integration boundaries, critical-path flows). Ask the user to keep / drop / add. Iterate until you BOTH have an explicit, agreed list. Stay in natural language — do NOT format into cases, do NOT pick file:line targets, do NOT invoke any test-rule files. The output of this step is two pieces of state: `{{TEST_TYPES}}` and `{{AGREED_SCENARIOS}}`.
8. Call `send_input(target: "<test_writer_agent_id>", ...)` using the "Formalize integration/E2E plan" template, populated with `{{TEST_TYPES}}` and `{{AGREED_SCENARIOS}}` from step 7.
9. Wait for the subagent to return the formalized plan. **STOP #2.** Paste verbatim (no edits, no commentary). Ask the user literally: *"Confirm this formalized integration/E2E plan or request changes?"*
10. Apply exactly one branch based on the user response:
    - **Confirmed** → proceed to step 11.
    - **Scenario-level changes** (add / drop / replace a scenario) → loop back to step 7 to re-discuss; do NOT send scenario edits as `send_input` revisions, because the subagent did not propose the scenarios.
    - **Formalization-level changes only** (wording, file:line, case naming, rule alignment) → call `send_input` with the "Revise plan" template and the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 9. Do NOT invoke a new subagent; do NOT edit the plan yourself.

**Phase 3 — Implement and review.**

11. Call `send_input(target: "<test_writer_agent_id>", ...)` using the "Proceed to implementation" template. Do NOT re-invoke; do NOT attempt to write tests yourself even if the subagent seems slow.
12. Wait for the subagent to return the implementation + red phase summary. **STOP #3.** Paste verbatim (no edits, no summarization). Ask the user literally: *"Test code complete. Would you like to review or change anything before proceeding?"*
13. Apply exactly one branch based on the user response:
    - **Approved** → proceed to step 14.
    - **Changes requested** → call `send_input` with the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 12. Do NOT invoke a new subagent; do NOT edit the test files yourself.
14. Return control to the caller with the `<output_format>` block. Do NOT continue into implementation of the feature under test — that is the caller's next step.
</instructions>

<input>
- {{REQUIREMENT_SUMMARY}}: confirmed requirement description handed in by the caller (e.g., `tdd` Step 2)
- {{FILES_UNDER_TEST}}: `file:line` pointers to the modules/functions under test
- {{CONTEXT_NOTES}}: (optional) anything the main session learned via `u0` that the subagent should know; pass literal `none` if not supplied
</input>

## Initial spawn prompt

Substitute the `{{...}}` placeholders with values from the caller's bundle. **Do not modify any other text.**

```text
You are the test-writer subagent. You persist across the whole planning→implementation arc of this skill. The coordinator will send follow-up instructions via `send_input`. Your job right now: draft the UNIT test plan only — do NOT write test code yet.

<scope>
- Requirement: {{REQUIREMENT_SUMMARY}}
- Files under test: {{FILES_UNDER_TEST}}
- Main-session context notes: {{CONTEXT_NOTES}}
</scope>

<instructions>
1. Load ONLY the rule files needed right now from `~/.agents/skills/auto-testcase/`:
   - `general.md` — always
   - `unit.md` — for this phase
   Extract only the rule sections relevant to the requirement.
2. Use `my-explore-0` first for any code exploration needed to design test cases. Escalate to custom agent `my-explore` only when exploration is broad, needs context isolation, or the user explicitly requires it. Do NOT read source files with raw shell file-read commands when exploration is non-trivial.
3. Draft a unit test plan. For each case: name, scenario (happy path / edge / error), expected behavior, target file:line.
4. Return ONLY the <plan_output_format> below. No code, no rule dumps.
</instructions>

<plan_output_format>
Test type:    unit
Files under test: <file:line list>
Cases:
  - <name>: <scenario> → <expected behavior> [target: file:line]
  - ...
Rule sources: <which rule files consulted>
Notes: <any assumption or ambiguity>
Confidence: high | medium | low
</plan_output_format>

<subagent_final_reminders>
P0 — Do NOT write test code in this phase. Planning only.
P0 — After returning the plan, STOP. Do NOT write code, do NOT refine the plan autonomously, do NOT load additional rule files, do NOT explore further. Wait for the coordinator's next `send_input`.
P0 — NEVER paste source code or rule text back. Return the <plan_output_format> only.
P0 — Load ONLY `general.md` + `unit.md`. Do NOT preload `integration.md` or `e2e.md` in this phase.
</subagent_final_reminders>
```

## send_input templates

Each template is sent via `send_input(target: "<test_writer_agent_id>", message: "<filled template>")`, where `<test_writer_agent_id>` is the agent ID captured at step 1a. Substitute only the `{{...}}` placeholders inside the template body.

### Revise plan

```text
Revision feedback from user (verbatim):
{{USER_FEEDBACK}}

Apply the changes to the MOST RECENT plan you returned. Return the updated <plan_output_format> only. Do NOT write code, do NOT advance to implementation, do NOT load additional rule files beyond those already loaded. After returning, STOP and wait for the next message.
```

### Formalize integration/E2E plan

```text
The coordinator (main session) and the user have already discussed and agreed on integration/E2E test scope. Your job is FORMALIZATION ONLY — turn the agreed natural-language scenarios into rule-compliant test cases. Do NOT add scenarios that are not in the agreed list. Do NOT silently drop scenarios — if one is infeasible, flag it under `Notes` and propose the closest feasible alternative for user approval.

Test types: {{TEST_TYPES}}
Agreed scenarios (natural-language, exactly as discussed):
{{AGREED_SCENARIOS}}

Load the matching rule files from `~/.agents/skills/auto-testcase/`:
  - `integration.md` — if integration tests requested
  - `e2e.md` — if E2E tests requested
Do NOT revisit `unit.md` — the unit plan is already confirmed.

For each agreed scenario, produce one formalized case: name, scenario summary, expected behavior, target file:line where applicable, rule-compliant phrasing. Return one <plan_output_format> block per test type. Do NOT write test code, do NOT advance to implementation. After returning, STOP and wait for the next message.
```

### Proceed to implementation

```text
All plans confirmed by user. Proceed to implementation.

<instructions>
1. Write test files for EXACTLY the confirmed cases — one file or more per test type, following the project's existing test framework and conventions. Do NOT invent new cases, do NOT silently drop confirmed cases. If you discover a confirmed case is infeasible, STOP and report back instead of dropping it.
2. Actually execute the test suite via `exec_command` and capture real runner output. Verify the red phase:
   - New features: ALL new tests MUST fail. If any pass without the feature implemented, the test is wrong — fix the test (not the assertion, not with a skip marker).
   - Bug fixes: the new bug-reproducing tests MUST fail; existing tests may pass.
   Do NOT use `xit`, `.skip`, `todo`, `pending`, or commented-out assertions to manufacture a green/red result.
3. Return ONLY the <impl_output_format> below. Do NOT paste test code, source code, or runner stdout in bulk.
</instructions>

<impl_output_format>
Test files:    path:line per new/edited test file
Cases written: name → file:line, one line each
Red results:   which tests failed as expected, which unexpectedly passed (with paths)
Rule sources:  which rule files were consulted
Notes:         any deviations from the confirmed plan, with reason
Confidence:    high | medium | low
</impl_output_format>

<subagent_final_reminders>
P0 — NEVER claim red phase passed without running the test suite via `exec_command` and observing actual runner output.
P0 — NEVER paste test code, source, or runner stdout back. Return file:line summaries only.
P0 — If a test unexpectedly passes, fix the test to exercise the missing behavior; do NOT lower the bar, do NOT mark skip/todo.
P0 — Write exactly the confirmed cases. Additions, deletions, or renames require reporting under `Notes` with a reason.
P1 — Use the project's existing test framework. Do NOT introduce a new one.
</subagent_final_reminders>
```

<examples>
<example>
SCENARIO: Caller (`tdd` Step 2) hands over "add email validation to signup". No integration/E2E needed.
ACTIONS:
  1. Invoke `test-writer` through `my-subagent` with the initial prompt. Subagent returns unit plan: 5 cases (empty, malformed, valid, unicode, max-length).
  2. STOP #1. User: "add duplicate-email".
  3. `send_input` with "Revise plan" template. Subagent returns 6-case plan.
  4. STOP #1 again. User: "good".
  5. Ask integration/E2E. User: no.
  6. `send_input` with "Proceed to implementation". Subagent returns: 1 test file, 6 cases, 6 red, used unit.md + general.md, confidence high.
  7. STOP #3. User: "looks good".
  8. Return Status: confirmed.
</example>

<example>
SCENARIO: Same requirement, but user wants E2E too.
ACTIONS:
  1–4 identical to above.
  5. Ask integration/E2E. User: "yes, E2E".
  6. Branch: yes → step 7.
  7. Discuss scope. Coordinator (using u0 context) proposes 3 candidate journeys: (a) signup with malformed email → inline error, (b) signup with already-used email → inline error, (c) signup with mismatched password confirm. User: "(a) and (b), drop (c) — handled elsewhere". Agreed: TEST_TYPES=e2e, AGREED_SCENARIOS=[a, b].
  8. `send_input` with "Formalize integration/E2E plan" template. Subagent returns formalized E2E plan with 2 cases (target file:line, rule-compliant phrasing).
  9. STOP #2. User: "looks good".
  10. Branch: confirmed → step 11.
  11. `send_input` with "Proceed to implementation". Subagent returns combined summary (1 unit file + 1 E2E file, all red).
  12. STOP #3 → confirmed. Return.
</example>

<example label="BAD — do not do this">
- Drafting unit test cases yourself in main session. Unit cases are the subagent's territory (it has rule + code context, you do not).
- Letting the subagent invent integration/E2E scenarios autonomously. Integration/E2E scenarios MUST be discussed and agreed with the user in step 7 BEFORE the subagent sees them. The subagent's job at step 8 is formalization, not generation.
- Skipping step 7's discussion and sending raw user words as "agreed scenarios". Step 7 is a real collaborative discussion — you propose candidates, the user keeps/drops/adds — not a stenography step.
- Formalizing the integration/E2E plan yourself in main session (writing case names, file:line, rule-compliant phrasing). Formalization belongs to the subagent.
- Reading `~/.agents/skills/auto-testcase/*.md` in main session. The subagent loads rules; the coordinator never does.
- Invoking a second `test-writer` within the same session. Revisions and mode switches always use `send_input` to the captured agent ID.
- Forgetting to capture the agent ID at step 1a. Without the ID you cannot resume the subagent — your only options become invoking a fresh one (forbidden by P0) or aborting.
- Modifying the initial prompt or `send_input` templates beyond `{{...}}` substitution.
- Narrowing `test-writer`'s tool inventory to remove `exec_command`, block `my-explore-0`, or block escalation to custom agent `my-explore`.
- Asking the user "integration/E2E?" before STOP #1 is satisfied.
- Skipping STOP #2 silently when the user said yes.
- Pasting subagent output with edits or commentary. Paste verbatim.
- Sending scenario-level changes (add/drop/replace a scenario) as a "Revise plan" `send_input`. Scenario edits require re-discussing in step 7 — the subagent didn't propose the scenarios, so it can't revise them. Only formalization-level changes go through "Revise plan".
</example>
</examples>

<output_format>
Status:        confirmed | aborted
Test files:    <copied verbatim from subagent implementation summary>
Red results:   <copied verbatim from subagent implementation summary>
Notes:         <any user-requested deviations resolved during review>
</output_format>

<success_criteria>
Complete when ALL of these hold:
- STOP #1 satisfied (unit plan confirmed via subagent-returned plan).
- STOP #2 satisfied OR skipped per step 6.
- Subagent returned an implementation summary with all `<impl_output_format>` slots filled.
- STOP #3 satisfied.
- Red-phase result reported with `file:line` and matches the rule.
- No test code, rule content, or source was read into the main session.

Stop the moment those hold.
</success_criteria>

<final_reminders>
P0 — Main session NEVER drafts unit cases, NEVER formalizes any test case (unit / integration / E2E), NEVER writes or edits test files, and NEVER reads `~/.agents/skills/auto-testcase/*.md`, test code, or source files into its own context. Discussing integration/E2E scenarios in natural language with the user (step 7) IS allowed and required — that is scope-setting, not formalization. Rule consultation, case formalization, and code writing all belong to the `test-writer` subagent. Use `u0` — which returns summaries and routes any needed exploration — for any code understanding.
P0 — Two production modes, do not blur them. Unit cases: subagent drafts from rules + code, user reviews. Integration/E2E cases: main session + user co-define scenarios in natural language FIRST (step 7), then subagent formalizes the agreed scenarios into rule-compliant cases (step 8). Subagent NEVER invents integration/E2E scenarios; main session NEVER formalizes any cases.
P0 — Exactly ONE `test-writer` per session. Revisions, mode switches, and implementation ALL go through `send_input(target: "<test_writer_agent_id>", ...)`. Invoking a second subagent breaks the review chain and is forbidden.
P0 — Address the subagent by ID. Capture the agent ID at step 1a immediately after `my-subagent` returns and use it in every subsequent `send_input`. The ID resumes the same agent from transcript with full context preserved.
P0 — All 3 STOP points are mandatory. A "go ahead" satisfies only the STOP it was given for. Never infer consent for STOP #N from approval of STOP #M.
P0 — Never claim red phase passed without the subagent returning runner output that proves it. If the subagent's `Red results` slot is empty or hedged, reject and `send_input` for a real run before proceeding.
P0 — If child-agent dispatch is unavailable, stop and tell the user; do NOT write tests in place.
P1 — Paste subagent output verbatim to the user at every STOP. Do NOT summarize the summary, do NOT strip fields, do NOT reformat.
P1 — Do NOT modify the initial prompt or any `send_input` template beyond `{{...}}` substitution. The templates are the contract.
P1 — Do NOT narrow `test-writer`'s tool inventory. It needs `exec_command`, file editing tools, file reading through allowed exploration tools, `my-explore-0`, and escalation to custom agent `my-explore` to do its job.
P2 — Use `u0` in the main session for your own requirement understanding before spawning. The subagent uses `my-explore-0` first for test-specific exploration and escalates to custom agent `my-explore` only when needed.
</final_reminders>
