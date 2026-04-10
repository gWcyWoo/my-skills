---
name: code
description: Implementation via isolated `implementer` subagent. Loads coding standards via `comply`, then dispatches.
---

<role>Coordinator: validate inputs, dispatch `implementer` through `my-subagent`, relay summary.</role>

<instructions>

**Phase 1 — Validate inputs (main session).**

1. Confirm required inputs are present:
    - `{{REQUIREMENT_SUMMARY}}` — if missing → STOP: _"Invoke `understand-0` or `understand` first."_
    - `{{FILES_IN_SCOPE}}` — if missing → STOP and ask: _"Which files should the implementation touch?"_
2. Confirm `{{FILES_IN_SCOPE}}` is non-empty. Empty scope → return `Status: blocked`.

**Phase 2 — Dispatch the `implementer` subagent.**

3. Invoke the `my-subagent` skill with these exact effective inputs:
    - `agent_type: "worker"`
    - `model: "gpt-5.4"`
    - `task_prompt`: the template defined in the `## Subagent prompt template` section below, with `{{...}}` placeholders substituted from the input bundle. Change no other text in the template.
4. Save the returned `agent_id` immediately and treat it as the `implementer` handle for follow-up feedback.

**Phase 3 — Review the subagent summary (main session).**

5. When the subagent returns terminal `STATUS: COMPLETE`, present the structured summary that follows the status line to the user **verbatim**. Then ask: _"Implementation complete. Would you like to review the diffs in your IDE before running lint and tests?"_
6. **STOP** and wait for the user.
    - **"no"** / **"proceed"** / **"继续"** / **"skip"** / **"ok"** → return `Status: ready-for-verify` with the relayed summary.
    - **"yes"** or specific change requests → `send_input(target: "<agent_id>", message: "<feedback verbatim>")`, wait for new summary, loop back to step 5.
      </instructions>

## Subagent prompt template

Substitute `{{...}}` placeholders with values from the input bundle. **Do not modify any other text.**

```
You are the `implementer` subagent. Write implementation code, load rules from diff, self-check, return a structured summary (no diffs).

<task>
Requirement: {{REQUIREMENT_SUMMARY}}
Files in scope (touch ONLY these): {{FILES_IN_SCOPE}}
Red test files (optional — your goal is to make them turn green): {{TEST_FILES}}
</task>

<instructions>
1. Think through the requirement against the files in scope. For any code exploration, invoke the `my-explore-0` skill (never use Read/Grep/probe/LSP on source directly).
2. If red test files were passed, use `my-explore-0` to read and understand the test contract. Do NOT modify the tests.
3. Implement the change, touching ONLY files listed in `<task>` → `Files in scope`. Use `apply_patch` for manual edits, including genuinely new files when needed.
4. **Load coding standards from diff.** Run `git diff` on the changed files, then invoke the `comply` skill, passing the diff and the file list.
5. **Self-check against comply rules**: re-read each rule section comply returned and verify the diff complies. Fix any violations before returning.
6. **Red-test reasoning**: if red test files were passed, REASON whether your implementation would turn them green. If any red test already passes BEFORE your implementation (tautology), surface it in Notes with Status:blocked.
7. Return ONLY the structured summary in the subagent output_format below after the terminal `STATUS:` line required by `my-subagent`. No diff paste, no code blocks longer than 3 lines, no rule text dumps.
</instructions>

<subagent_output_format>
Status:        ready-for-verify | blocked
Files touched: path → one-line description per file (new / edited / deleted)
Rules applied: which rule sections from comply were enforced (list titles, not content)
Test targets:  which red tests the implementation targets (if TEST_FILES was passed), or "n/a"
Notes:         any deviations from the plan, defects surfaced (e.g. tautology tests), assumptions
Confidence:    high | medium | low
</subagent_output_format>

<subagent_final_reminders>
P0 — NEVER run any test runner (vitest / pytest / npm test / go test / etc.). REASON about correctness only; verification is the parent workflow's Step 4.
P1 — Do not add error handling, validation, fallbacks, or feature flags the <rules> did not require.
P1 — Do not add comments or docstrings to code you did not change.
</subagent_final_reminders>
```

<output_format>
Status: ready-for-verify | blocked
Files touched: <from subagent>
Rules applied: <from subagent>
Test targets: <from subagent, or "n/a">
Review: accepted | accepted-after-changes | (not requested)
Notes: <from subagent>
</output_format>

<final_reminders>
P0 — ALWAYS create child agents through `my-subagent`. Never bypass it with direct `spawn_agent`.
P0 — If `my-subagent` is unavailable in your tool inventory, you cannot preserve this workflow. STOP and escalate: *"Use `code-0` instead."*
</final_reminders>
