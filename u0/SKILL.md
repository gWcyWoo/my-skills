---
name: u0
description: Main-session requirement-understanding step. Step 1 clarifies the requirement with the user (no code lookup). Step 2 explores code in the main session per the loaded tool-selection rules (`~/.claude/CLAUDE.md` `<tool-usage>` + `~/.claude/skills/shared/tools-ins.md`). Step 3 emits a gap analysis and STOPS for explicit user confirmation. Step 4 routes to refine / reshape / list-candidates / hand-off.
---

<role>
Main-session coordinator. Absorbs all user dialogue inside Step 1 and Step 4. Output is a confirmed gap analysis.
</role>

<instructions>

## Step 1 — Clarify the requirement (NO code lookup)

Identify, from the user's message: symptom (bug) or desired behavior (feature), and every named file / symbol / UI label. Ask the user about every ambiguity. Do not assume.

Iterate until the requirement resolves into concrete exploration *directions* — each a retrievable question: "does X exist?", "what calls Y?", "what is the body of Z?", "where is feature F's entry point?".

Directions are model-internal. Do NOT print them to the user.

HARD RULE: Step 1 runs zero code-lookup tools. No `Read`, `Grep`, `Glob`, `extract_code`, LSP, `ast-grep`, `search_code`.

## Step 2 — Explore code in the main session

Run exploration per the session's loaded rules:

- `~/.claude/CLAUDE.md` `<exploration>` and `<tool-usage>` — loop discipline and per-task tool choice.
- `~/.claude/skills/shared/tools-ins.md` — the per-call "To get {want}, call {invocation}" line and the bottom-up scenario palette.

Do NOT read `my-explore-0/SKILL.md`, do NOT read `my-explore-0/TOOLS.md`, do NOT dispatch `Agent(subagent_type="my-explore")`. All three are retired.

Escalation trigger: if any single direction produces more than 2 tool calls OR more than one direction expands into sub-questions during execution, STOP exploration, report current evidence to the user, and ask whether to continue, narrow, or split. Do not silently grow the exploration.

## Step 3 — Emit gap analysis and STOP

Emit ONLY the `<default_output>` block. STOP. Wait for the user's explicit confirmation (a "yes" / "go" / equivalent) before any further action.

## Step 4 — Route next step (with user)

After confirmation, ask the user which of:

- **(a) Refine directions and re-explore** → return to Step 2 with new directions.
- **(b) Reshape requirement** → return to Step 1.
- **(c) List candidates / trade-offs from existing evidence** → emit exactly 2 named directions, each with a one-line trade-off. No new exploration.
- **(d) Hand off to `c-0` / `write-tests`** → emit final summary, stop.

If the user requests "files / scope / locations" any time after Step 2 has evidence, emit `<on_demand_output>`.

</instructions>

<default_output>
**Bug fix:**

Symptom: <one sentence, user's words>
Root cause: <one sentence + file:line>
Fix approach: <one sentence>

**Feature / change:**

Goal: <one sentence, user's words>
Current state: <one sentence + file:line>
Gap: <one sentence>
Approach: <one to three sentences>
</default_output>

<on_demand_output>
Emit ONLY when the user requests files / scope / locations:

Files in scope:
- path:line — <one-line role>
- path:line — <one-line role>
</on_demand_output>

<success_criteria>
Complete when ALL hold:

- Step 1 finished before any code-lookup tool call.
- Every ambiguity was asked, not assumed.
- Step 2 ran in the main session per `<tool-usage>` + `shared/tools-ins.md`. No `my-explore-0/*` read. No `Agent(subagent_type="my-explore")` dispatch.
- `<default_output>` was emitted (no file lists, no exploration dumps).
- User confirmed explicitly.
- Step 4 route recorded.
</success_criteria>

<final_reminders>
P0 — Step 1 calls zero code-lookup tools.
P0 — Step 1 directions are model-internal. Do not print them.
P0 — Ask on ambiguity. Do not guess.
P0 — Step 2 runs in the main session. Do not read `my-explore-0/SKILL.md` or `my-explore-0/TOOLS.md`. Do not call `Agent(subagent_type="my-explore")`.
P0 — Step 3 STOPS and waits for explicit confirmation.
P0 — Default user output is `<default_output>` only. Emit `<on_demand_output>` only on explicit user request.
P0 — Candidate generation runs only in Step 4 branch (c), only on user request.
P1 — Do not write tests or code. Hand off to `write-tests` / `c-0`.
P2 — Skip to Step 3 if the user supplies exploration context up front.
P2 — Mirror the user's language.
</final_reminders>
