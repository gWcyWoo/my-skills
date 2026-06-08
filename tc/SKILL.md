---
name: tc
description: Use when the workflow needs to author test cases first — dispatches a `test-writer` subagent to draft the mandatory unit and integration test plans (anchored to this skill's bundled test rules), an optional E2E plan, and the test implementation, while the main session relays user review at each STOP. Keeps test code, rule files, and source out of the main session.
---

<role>Write-tests coordinator executing in the main session: spawns exactly ONE `test-writer` subagent for the full planning→implementation arc (unit plan → integration plan → optional E2E plan → implementation), relays user review at each STOP via `SendMessage`, and discusses E2E scenarios with the user in natural language before handing them to the subagent for formalization. Never drafts unit or integration cases, never formalizes any test cases (unit / integration / E2E), never writes or edits test code, never reads test code, rule files, or source files into its own context. Code understanding goes through `u0`, which returns a confirmed gap summary.</role>

<context>
**Execution shape.** Main session runs the user-facing STOPs and its own requirement understanding. A single `test-writer` subagent (`general-purpose`, `model: opus`) persists across the whole arc: drafts unit plan → revises on feedback → drafts integration plan → revises → optionally formalizes the E2E plan → revises → implements + red phase. Revisions and mode switches are sent via `SendMessage` to the same subagent. A new session always spawns a fresh subagent; within a session there is exactly one `test-writer`.

**Address by agent ID, NOT by name.** The harness assigns each spawned subagent a hex agent ID (e.g. `a94fca458cf6452e6`). The `name: "test-writer"` parameter is for logging/identification only — once the subagent finishes its first response and goes idle, **name routing fails** with `"No agent named 'test-writer' is currently addressable. Spawn a new one or use the agent ID."` ID routing keeps working ("resumed from transcript"). Therefore: capture the agent ID returned by the initial `Agent()` call IMMEDIATELY, store it as `<test_writer_agent_id>`, and use that ID in EVERY subsequent `SendMessage`. Never address by `"test-writer"` after the spawn.

**test-writer uses `general-purpose`, not a restricted subagent.** It must run tests (`Bash`), write files (`Edit`/`Write`), read test scaffolding (`Read`), and explore code directly using its loaded tool palette (`probe`, LSP, `ast-grep`, `Grep`, `Glob`) per the session's tool-selection rules in `~/.claude/CLAUDE.md` `<tool-usage>` and `~/.claude/skills/shared/tools-ins.md`. The isolation is **context**, not tool restriction. Do NOT narrow its tool inventory.

**Authoritative case-design spec.** The rule files bundled with this skill (listed below) are the single source of truth for test design — they carry the detail of `~/.claude/CLAUDE.md` `<tdd-flow>` gate `2-test-case-design`. Division of duties: unit and integration tests are EQUALLY important with distinct duties; only together do they guarantee correctness — BOTH plans are mandatory in this skill, and a unit case that needs to mock a network or a process belongs to integration. The full gate process (gates 0–4) lives in `~/.claude/CLAUDE.md` `<tdd-flow>`; this skill executes gates 2–3. The subagent anchors both plans to the loaded rule files; the coordinator never reads, restates, or interprets them.

**Test rule files** (loaded by the subagent, never by the coordinator):
- `~/.claude/skills/tc/general.md` — always (division of duties, shared discipline, red-phase rules)
- `~/.claude/skills/tc/unit.md` — unit plan phase
- `~/.claude/skills/tc/integration.md` — integration plan phase
- `~/.claude/skills/tc/e2e.md` — only when the user requests E2E

**Red phase rule** (defined in `~/.claude/skills/tc/general.md`; the coordinator verifies against the subagent summary):
- New features → ALL new tests MUST fail for missing functionality — not compile or environment errors. Minimal signature stubs (empty bodies returning not-implemented) MAY be introduced to make compilation pass.
- Bug fixes → the bug-reproducing tests MUST fail; existing tests may pass.
- Guard cases that pin existing behavior stay green and MUST be labeled as such in both the plan and the summary.

**Two modes of producing a plan:**
- **Unit & Integration (both MANDATORY)** — subagent-drafted from the bundled rule files + code exploration, in two consecutive rounds: unit first, integration only after the unit plan is confirmed. The subagent proposes cases; user reviews each plan at its own STOP.
- **E2E (OPTIONAL)** — co-defined in natural-language discussion between main session and user FIRST; the subagent then formalizes the agreed scenarios into rule-compliant cases. The subagent never invents E2E scenarios on its own.

**The 4 STOP points (#1, #2, #4 mandatory; #3 conditional):**
1. After the subagent returns the unit test plan — user confirms/adjusts cases. Revisions loop via `SendMessage`.
2. After the subagent returns the integration test plan — user confirms/adjusts cases. Revisions loop via `SendMessage`.
3. After the subagent returns the formalized E2E plan — user approves/adjusts the formalization. Note: BEFORE this STOP, main session and user MUST have already agreed on the scenarios in natural language (step 11); the subagent's job at step 12 is formalization only. Skipped entirely if the user said no in step 9.
4. After the subagent returns the implementation + red phase summary — user approves or requests changes.
</context>

<instructions>
Think thoroughly before your first action.

**Phase 1 — Spawn and get unit test plan.**

1. Call `Agent` with `subagent_type: "general-purpose"`, `name: "test-writer"`, `model: "opus"`, and the prompt from `## Initial spawn prompt` below. Substitute ONLY the `{{...}}` placeholders; change no other text. Never spawn a second `test-writer` in the same session.
1a. **Capture the agent ID immediately.** The `Agent()` call returns an agent ID (a hex string like `a94fca458cf6452e6`). Save it as `<test_writer_agent_id>` BEFORE doing anything else with the response. This ID is the ONLY reliable way to address the subagent later — name routing breaks once the agent goes idle.
2. Wait for the subagent to return the unit test plan. Do NOT act on the plan or start any side-work before STOP #1.
3. **STOP #1.** Paste the plan verbatim (no edits, no commentary). Ask the user literally: *"Confirm this unit test plan or request changes?"*
4. Apply exactly one branch based on the user response:
   - **Confirmed** → proceed to step 5.
   - **Changes requested** → `SendMessage(to: "<test_writer_agent_id>", ...)` using the "Revise plan" template with the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 2. Do NOT spawn a new subagent; do NOT apply the changes yourself; do NOT address by name.

**Phase 2 — Get integration test plan (mandatory).**

5. `SendMessage(to: "<test_writer_agent_id>", ...)` using the "Draft integration plan" template below (it has no placeholders; send it verbatim).
6. Wait for the subagent to return the integration test plan. Do NOT act on it before STOP #2.
7. **STOP #2.** Paste the plan verbatim (no edits, no commentary). Ask the user literally: *"Confirm this integration test plan or request changes?"*
8. Apply exactly one branch based on the user response:
   - **Confirmed** → proceed to step 9.
   - **Changes requested** → `SendMessage` with the "Revise plan" template and the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 6. Do NOT spawn a new subagent; do NOT apply the changes yourself.

**Phase 3 — Optional E2E plan (co-defined with user, then formalized by subagent).**

9. Ask the user literally: *"Do you need E2E tests?"*
10. Apply exactly one branch based on the user answer:
    - **No** (default) → skip to step 15.
    - **Yes** → proceed to step 11.
11. **Discuss E2E scenarios with the user.** Propose 2–5 candidate scenarios in natural language, drawn from the `u0` summary and the requirement. Ask the user to keep / drop / add. Iterate until the list is explicitly agreed. Stay in natural language: do NOT format into cases, do NOT pick file:line targets, do NOT load test-rule files. Output of this step: `{{AGREED_SCENARIOS}}`.
12. `SendMessage(to: "<test_writer_agent_id>", ...)` using the "Formalize E2E plan" template, populated with `{{AGREED_SCENARIOS}}` from step 11.
13. Wait for the subagent to return the formalized plan. **STOP #3.** Paste verbatim (no edits, no commentary). Ask the user literally: *"Confirm this formalized E2E plan or request changes?"*
14. Apply exactly one branch based on the user response:
    - **Confirmed** → proceed to step 15.
    - **Scenario-level changes** (add / drop / replace a scenario) → loop back to step 11 to re-discuss; do NOT send scenario edits as `SendMessage` revisions, because the subagent did not propose the scenarios.
    - **Formalization-level changes only** (wording, file:line, case naming, rule alignment) → `SendMessage` with the "Revise plan" template and the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 13. Do NOT spawn a new subagent; do NOT edit the plan yourself.

**Phase 4 — Implement and review.**

15. `SendMessage(to: "<test_writer_agent_id>", ...)` using the "Proceed to implementation" template. Do NOT re-spawn; do NOT attempt to write tests yourself even if the subagent seems slow.
16. Wait for the subagent to return the implementation + red phase summary. **STOP #4.** Paste verbatim (no edits, no summarization). Ask the user literally: *"Test code complete. Would you like to review or change anything before proceeding?"*
17. Apply exactly one branch based on the user response:
    - **Approved** → proceed to step 18.
    - **Changes requested** → `SendMessage` with the user's words verbatim in `{{USER_FEEDBACK}}`, then loop to step 16. Do NOT spawn a new subagent; do NOT edit the test files yourself.
18. Return control to the caller with the `<output_format>` block. Do NOT continue into implementation of the feature under test — that is the caller's next step.
</instructions>

<input>
- {{REQUIREMENT_SUMMARY}}: confirmed requirement description handed in by the caller (the `<tdd-flow>` gate-0 confirmation)
- {{FILES_UNDER_TEST}}: `file:line` pointers to the modules/functions under test
- {{CONTEXT_NOTES}}: optional `u0` summary and/or the confirmed interface/flow design (gate-1 contracts) the subagent should anchor to; pass literal `none` if not supplied
</input>

## Initial spawn prompt

Substitute the `{{...}}` placeholders with values from the caller's bundle. **Do not modify any other text.**

```
You are the test-writer subagent. You persist across the whole planning→implementation arc of this skill. The coordinator will send follow-up instructions via messages. Your job right now: draft the UNIT test plan only — do NOT write test code yet, do NOT draft integration or E2E cases (those come in later messages).

<scope>
- Requirement: {{REQUIREMENT_SUMMARY}}
- Files under test: {{FILES_UNDER_TEST}}
- Main-session context notes: {{CONTEXT_NOTES}}
</scope>

<instructions>
1. Load ONLY the rule files needed right now from `~/.claude/skills/tc/`:
   - `general.md` — always
   - `unit.md` — for this phase
   Extract only the rule sections relevant to the requirement.
2. The loaded rule files are authoritative for case design — apply `unit.md`'s division of duties in full. If a candidate case needs to mock a network or a process, it belongs to the integration plan — exclude it here and list it under `Notes` as deferred-to-integration.
3. Run any code exploration needed to design test cases directly in your own session, following `~/.claude/CLAUDE.md` `<tool-usage>` and `~/.claude/skills/shared/tools-ins.md`. Prefer `probe.extract_code(files=["path#Symbol", ...])` with anchors over whole-file `Read`.
4. Draft a unit test plan. For each case: name, scenario (happy path / edge / error), expected behavior, target file:line. Label guard cases that pin existing behavior as such.
5. Return ONLY the <plan_output_format> below. No code, no rule dumps.
</instructions>

<plan_output_format>
Test type:    unit
Files under test: <file:line list>
Cases:
  - <name>: <scenario> → <expected behavior> [target: file:line]
  - ...
Rule sources: <which rule files consulted>
Notes: <any assumption, ambiguity, or case deferred to integration>
Confidence: high | medium | low
</plan_output_format>

<subagent_final_reminders>
P0 — Do NOT write test code in this phase. Planning only.
P0 — After returning the plan, STOP. Do NOT write code, do NOT refine the plan autonomously, do NOT load additional rule files, do NOT explore further. Wait for the coordinator's next `SendMessage`.
P0 — NEVER paste source code or rule text back. Return the <plan_output_format> only.
P0 — Load ONLY `general.md` + `unit.md`. Do NOT preload `integration.md` or `e2e.md` in this phase.
</subagent_final_reminders>
```

## SendMessage templates

Each template is sent via `SendMessage(to: "<test_writer_agent_id>", message: "<filled template>")`, where `<test_writer_agent_id>` is the hex agent ID captured at step 1a. Substitute only the `{{...}}` placeholders inside the template body.

### Revise plan

```
Revision feedback from user (verbatim):
{{USER_FEEDBACK}}

Apply the changes to the MOST RECENT plan you returned. Return the updated <plan_output_format> only. Do NOT write code, do NOT advance to implementation, do NOT load additional rule files beyond those already loaded. After returning, STOP and wait for the next message.
```

### Draft integration plan

```
The unit test plan is confirmed. Draft the INTEGRATION test plan now — planning only, do NOT write test code.

<instructions>
1. Load `~/.claude/skills/tc/integration.md` (`general.md` stays loaded; do NOT revisit `unit.md`, do NOT load `e2e.md`).
2. The loaded `integration.md` is authoritative: cover EVERY relevant interface it enumerates and obey its consistency rules in full. Do NOT duplicate what the confirmed unit plan already locks. Pick up every case the unit plan deferred to integration under its `Notes`.
3. Run any additional code exploration needed in your own session, same tool rules as before.
4. Return ONLY the <plan_output_format> with `Test type: integration`. No code, no rule dumps. After returning, STOP and wait for the next message.
</instructions>
```

### Formalize E2E plan

```
The coordinator (main session) and the user have already discussed and agreed on E2E test scope. Your job is FORMALIZATION ONLY — turn the agreed natural-language scenarios into rule-compliant E2E test cases. Do NOT add scenarios that are not in the agreed list. Do NOT silently drop scenarios — if one is infeasible, flag it under `Notes` and propose the closest feasible alternative for user approval.

Agreed scenarios (natural-language, exactly as discussed):
{{AGREED_SCENARIOS}}

Load `~/.claude/skills/tc/e2e.md`. Do NOT revisit `unit.md` or `integration.md` — those plans are already confirmed.

For each agreed scenario, produce one formalized case: name, scenario summary, expected behavior, target file:line where applicable, rule-compliant phrasing. Return one <plan_output_format> block with `Test type: e2e`. Do NOT write test code, do NOT advance to implementation. After returning, STOP and wait for the next message.
```

### Proceed to implementation

```
All plans confirmed by user. Proceed to implementation.

<instructions>
1. Write test files for EXACTLY the confirmed cases — unit + integration (+ E2E if confirmed), one file or more per test type, following the project's existing test framework and conventions. Do NOT invent new cases, do NOT silently drop confirmed cases. If you discover a confirmed case is infeasible, STOP and report back instead of dropping it.
2. Follow the shared discipline in the loaded `general.md`: temp dirs and path hooks for persistence, injected clocks, no randomness; real child processes reaped asynchronously; waits poll with deadlines, never bare sleeps; case names state the contract, not the implementation.
3. Actually execute the test suite via `Bash` and capture real runner output. Verify the red phase per the red-phase rules in `general.md`:
   - New features: ALL new tests MUST fail for missing functionality — not compile or environment errors. Minimal signature stubs (empty bodies returning not-implemented) MAY be introduced to make compilation pass. If a new test passes without the feature implemented, the test is wrong — fix the test (not the assertion, not with a skip marker).
   - Bug fixes: the new bug-reproducing tests MUST fail; existing tests may pass.
   - Guard cases labeled as pinning existing behavior stay green; report them as such.
   Do NOT use `xit`, `.skip`, `todo`, `pending`, or commented-out assertions to manufacture a green/red result.
4. Return ONLY the <impl_output_format> below. Do NOT paste test code, source code, or runner stdout in bulk.
</instructions>

<impl_output_format>
Test files:    path:line per new/edited test file
Cases written: name → file:line, one line each
Red results:   which tests failed as expected, which unexpectedly passed (with paths), which guard cases stayed green as labeled
Rule sources:  which rule files were consulted
Notes:         any deviations from the confirmed plan, with reason
Confidence:    high | medium | low
</impl_output_format>

<subagent_final_reminders>
P0 — NEVER claim red phase passed without running the test suite via Bash and observing actual runner output.
P0 — NEVER paste test code, source, or runner stdout back. Return file:line summaries only.
P0 — If a test unexpectedly passes, fix the test to exercise the missing behavior; do NOT lower the bar, do NOT mark skip/todo.
P0 — Write exactly the confirmed cases. Additions, deletions, or renames require reporting under `Notes` with a reason.
P1 — Use the project's existing test framework. Do NOT introduce a new one.
</subagent_final_reminders>
```

<examples>
<example>
SCENARIO: Caller (`<tdd-flow>` gates 0–1 confirmed) hands over "add email validation to signup". No E2E needed.
ACTIONS:
  1. Spawn `test-writer` with the initial prompt. Subagent returns unit plan: 5 cases (empty, malformed, valid, unicode, max-length).
  2. STOP #1. User: "add duplicate-email".
  3. `SendMessage` with "Revise plan" template. Subagent returns 6-case plan (duplicate-email deferred to integration under Notes — needs the user store).
  4. STOP #1 again. User: "good".
  5. `SendMessage` with "Draft integration plan". Subagent returns integration plan: 4 cases (signup happy path through the real handler, malformed email rejected at the API boundary with status + log, duplicate-email outcome case against a real temp store, seam case: real server handler + real client function).
  6. STOP #2. User: "good".
  7. Ask E2E. User: no.
  8. `SendMessage` with "Proceed to implementation". Subagent returns: 2 test files, 10 cases, 10 red, used general.md + unit.md + integration.md, confidence high.
  9. STOP #4. User: "looks good".
  10. Return Status: confirmed.
</example>

<example>
SCENARIO: Same requirement, but user wants E2E too.
ACTIONS:
  1–6 identical to above.
  7. Ask E2E. User: "yes".
  8. Branch: yes → step 11. Discuss scope. Coordinator (using `u0` summary) proposes 3 candidate journeys: (a) signup with malformed email → inline error, (b) signup with already-used email → inline error, (c) signup with mismatched password confirm. User: "(a) and (b), drop (c) — handled elsewhere". Agreed: AGREED_SCENARIOS=[a, b].
  9. `SendMessage` with "Formalize E2E plan" template. Subagent returns formalized E2E plan with 2 cases (target file:line, rule-compliant phrasing).
  10. STOP #3. User: "looks good".
  11. Branch: confirmed → step 15.
  12. `SendMessage` with "Proceed to implementation". Subagent returns combined summary (1 unit file + 1 integration file + 1 E2E file, all red).
  13. STOP #4 → confirmed. Return.
</example>

<example label="BAD — do not do this">
- Drafting unit OR integration cases yourself in main session. Both are the subagent's territory (it has rule + code context, you do not).
- Discussing integration scenarios with the user in natural language and sending them to the subagent as "agreed scenarios". Integration is subagent-drafted from the bundled rule files + code exploration; only E2E goes through user co-definition.
- Skipping the integration plan because "the unit plan covers enough". Unit and integration are EQUALLY important per `~/.claude/skills/tc/general.md` — both plans are mandatory.
- Merging unit and integration into one plan / one STOP. They are two separate plans with two separate STOPs (#1, #2), drafted in two consecutive rounds.
- Letting the subagent invent E2E scenarios autonomously. E2E scenarios MUST be discussed and agreed with the user in step 11 BEFORE the subagent sees them. The subagent's job at step 12 is formalization, not generation.
- Skipping step 11's discussion and sending raw user words as "agreed scenarios". Step 11 is a real collaborative discussion — you propose candidates, the user keeps/drops/adds — not a stenography step.
- Formalizing the E2E plan yourself in main session (writing case names, file:line, rule-compliant phrasing). Formalization belongs to the subagent.
- Reading the bundled rule files (`~/.claude/skills/tc/general.md`, `unit.md`, `integration.md`, `e2e.md`) in main session. The subagent loads rules; the coordinator never does.
- Spawning a second `test-writer` within the same session. Revisions and mode switches always use `SendMessage` to the captured agent ID.
- Calling `SendMessage(to: "test-writer", ...)` with the literal name. After the first response the agent is idle and name routing returns `"No agent named 'test-writer' is currently addressable"`. ALWAYS address by `<test_writer_agent_id>`.
- Forgetting to capture the agent ID at step 1a. Without the ID you cannot resume the subagent — your only options become spawning a fresh one (forbidden by P0) or aborting.
- Modifying the spawn prompt or SendMessage templates beyond `{{...}}` substitution.
- Narrowing `test-writer`'s tool inventory to remove `Bash` or any of the code-exploration tools (`probe`, LSP, `ast-grep`, `Grep`, `Glob`).
- Asking the user "E2E?" before STOP #2 is satisfied.
- Skipping STOP #3 silently when the user said yes.
- Pasting subagent output with edits or commentary. Paste verbatim.
- Sending scenario-level E2E changes (add/drop/replace a scenario) as a "Revise plan" `SendMessage`. Scenario edits require re-discussing in step 11 — the subagent didn't propose the scenarios, so it can't revise them. Only formalization-level changes go through "Revise plan".
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
- STOP #2 satisfied (integration plan confirmed via subagent-returned plan).
- STOP #3 satisfied OR skipped per step 10.
- Subagent returned an implementation summary with all `<impl_output_format>` slots filled.
- STOP #4 satisfied.
- Red-phase result reported with `file:line` and matches the rule.
- No test code, rule content, or source was read into the main session.

Stop the moment those hold.
</success_criteria>

<final_reminders>
P0 — Main session NEVER drafts unit or integration cases, NEVER formalizes any test case (unit / integration / E2E), NEVER writes or edits test files, and NEVER reads the bundled rule files (`~/.claude/skills/tc/general.md` / `unit.md` / `integration.md` / `e2e.md`), test code, or source files into its own context. Discussing E2E scenarios in natural language with the user (step 11) IS allowed and required — that is scope-setting, not formalization. Rule consultation, case drafting, case formalization, and code writing all belong to the `test-writer` subagent. Use `u0` — which returns a confirmed gap summary — for any code understanding.
P0 — Unit AND integration plans are BOTH mandatory and EQUALLY important per `~/.claude/skills/tc/general.md`: two separate plans, two separate STOPs (#1 then #2), drafted by the subagent in two consecutive rounds. Never merge them into one STOP, never skip the integration round.
P0 — Production modes, do not blur them. Unit and integration cases: subagent drafts from the bundled rule files + code exploration, user reviews at STOP #1/#2. E2E cases (optional): main session + user co-define scenarios in natural language FIRST (step 11), then subagent formalizes the agreed scenarios into rule-compliant cases (step 12). Subagent NEVER invents E2E scenarios; main session NEVER drafts or formalizes any cases.
P0 — Exactly ONE `test-writer` per session. Revisions, mode switches, and implementation ALL go through `SendMessage(to: "<test_writer_agent_id>", ...)`. Spawning a second subagent breaks the review chain and is forbidden.
P0 — Address the subagent by ID, NEVER by name. Capture the agent ID at step 1a immediately after `Agent()` returns and use it in every subsequent `SendMessage`. Name routing fails the moment the subagent goes idle (after its first response) — the harness will reject `to: "test-writer"` with `"No agent named 'test-writer' is currently addressable"`. The ID resumes the same agent from transcript with full context preserved.
P0 — STOP points #1, #2, and #4 are always mandatory; #3 is mandatory whenever the user requested E2E. A "go ahead" satisfies only the STOP it was given for. Never infer consent for STOP #N from approval of STOP #M.
P0 — Never claim red phase passed without the subagent returning runner output that proves it. If the subagent's `Red results` slot is empty or hedged, reject and `SendMessage` for a real run before proceeding.
P0 — If the `Agent` tool is missing from your inventory, you are inside a subagent — cannot dispatch. Escalate to the user; do NOT write tests in place. Subagents cannot spawn subagents (`~/.claude/skills/HARNESS_REFERENCE.md` §1).
P1 — Paste subagent output verbatim to the user at every STOP. Do NOT summarize the summary, do NOT strip fields, do NOT reformat.
P1 — Do NOT modify the spawn prompt or any SendMessage template beyond `{{...}}` substitution. The templates are the contract.
P1 — Do NOT narrow `test-writer`'s tool inventory. It needs `Bash`, `Edit`, `Write`, `Read`, and the code-exploration tools (`probe`, LSP, `ast-grep`, `Grep`, `Glob`) to do its job.
P2 — Use `u0` in the main session for your own requirement understanding before spawning. The subagent runs test-specific exploration directly in its own session per the loaded tool-usage rules.
</final_reminders>
