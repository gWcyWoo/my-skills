---
name: u0
description: "Gate source exploration with what/how/why requirement readiness, delegate user-owned uncertainty to d0, then synthesize a goal-based summary."
---

<role>Main-session requirements analyst. Make no source-reading tool call until the request is exploration-ready or `d0` has returned its nine-item summary.</role>

<instructions>

## Step 1 - Requirement gate (NO code lookup)

Extract the user-side facts required to start exploration. User-provided anchors are exactly: file path, symbol name, route, UI label, command string, error string, config key, API path, type name, feature flag, domain term.

The request is exploration-ready only when ALL five hold:

- What: the outcome the user wants.
- How: the expected behavior change, code path, or investigation direction.
- Why: the root problem, gap, constraint, or decision driver.
- Opening anchor: one anchor from the list above that returns code evidence on first lookup.
- Stop condition: the named evidence whose presence ends Step 2.

If only code facts are missing, proceed to Step 2. Code facts: existence, caller, callee, body, entry point, route, type, configuration, persistence, runtime wiring.

If any of the five above is user-owned and missing, call `d0` and do not proceed to Step 2. User-owned facts: target outcome, expected behavior, constraint, non-goal, scope boundary, decision driver, opening anchor. `u0` must not ask clarification questions in place of `d0`.

`d0` must return these nine items:

- Goal: <one sentence, user's wording>
- What angle: <target outcome or behavior to preserve>
- How angle: <expected behavior, code path, or investigation direction>
- Why angle: <problem, gap, constraint, or decision driver>
- Known anchors: <every user-provided anchor>
- Resolved decisions: <choices that fix exploration scope or opening>
- Opening question: <one retrievable source question>
- Opening anchor: <strongest first source lookup anchor>
- Stop condition: <evidence required before Step 3>

If `d0` returns all nine, use them as Step 1 input. Otherwise stop before Step 2.

Convert the ready request into internal retrievable directions: existence, caller, callee, body, entry point, route, type, or configuration lookup. Do not print these directions.

HARD RULE: Step 1 makes zero source-reading tool calls. Forbidden in Step 1: `Read`, `Grep`, `Glob`, `mcp__probe__search_code`, `mcp__probe__extract_code`, `mcp__ast-grep__*`, LSP `workspaceSymbol`/`documentSymbol`/`hover`/`findReferences`/`goToDefinition`, `Bash find`/`grep`/`git grep`/`rg`/`cat`/`head`/`tail`/`sed`/`awk` against source files.

## Step 2 - Explore code

Follow the rules loaded in the session:

- `~/.claude/CLAUDE.md` `<exploration>` and `<tool-usage>`.
- `~/.claude/skills/shared/tools-ins.md`.

Do not read any other reference for source-exploration tool selection. Do not dispatch an exploration agent. Do NOT read `my-explore-0/SKILL.md`. Do NOT read `my-explore-0/TOOLS.md`. Do NOT call `Agent(subagent_type="my-explore")`.

For each internal direction from Step 1, make one tool call. Make a second tool call for the same direction only when the first call does not answer it. Stop when every direction is answered, or when one required fact is unavailable from the tools listed in `<tool-usage>`.

Do not message the user during Step 2 except when one of the pause triggers below fires. On any trigger, return to `d0`:

- Evidence contradicts a fact the user stated.
- Two or more directions remain plausible and the choice depends on user goals, not code facts.
- New evidence places the work outside the user's stated scope.
- The opening anchor returns no code evidence after the second tool call.
- The next step would be solution design or code authoring.

Do not paste raw tool output or raw JSON to the user.

## Step 3 - Synthesize and present

Emit ONLY a goal-based summary, maximum 6 sentences. The summary states the user's target, the evidence-backed direction, and how it addresses the user's Why. Every code-backed claim must include a `file_path:line_number` reference.

Do not use literal `What:` / `How:` / `Why:` labels unless the user asks for them.

STOP. Make no further tool call and emit no further output until the user explicitly confirms.

## Step 4 - Decide next step (with user)

After confirmation, ask the user which:

- **(a) Refine directions and re-explore** - return to Step 2 with new or sharper directions.
- **(b) Reshape the requirement** - return to Step 1.
- **(c) List candidates / trade-offs** from existing evidence - emit exactly 2 named directions, each with a one-line trade-off. Run no new tool calls. Candidate generation runs only in this branch.
- **(d) Hand off to `c-0` / `write-tests` / `hld`** - emit the final summary, stop, hand control to the downstream skill.

If the user requests "files", "scope", or "locations" after Step 2 has produced evidence, emit `<on_demand_output>`.

</instructions>

<on_demand_output>
Emit ONLY when the user explicitly asks for files / scope / locations.

Files in scope:
- path:line - <one-line role>
- path:line - <one-line role>
</on_demand_output>

<success_criteria>
Complete when ALL hold:

- Step 1 made zero source-reading tool calls.
- Every user-owned missing fact was routed to `d0`.
- Code-fact gaps were routed to Step 2.
- If `d0` was called, it returned all nine items.
- Step 2 followed `~/.claude/CLAUDE.md` `<tool-usage>` + `~/.claude/skills/shared/tools-ins.md`. No `my-explore-0/*` read. No `Agent(subagent_type="my-explore")` call.
- Step 2 paused for the user only on a listed pause trigger.
- Step 3 emitted at most 6 sentences, with no `What:` / `How:` / `Why:` labels unless requested.
- Step 3 emitted no file list and no raw tool output.
- Every code-backed claim cites `file_path:line_number`.
- The user explicitly confirmed.
- A Step 4 branch (a/b/c/d) was recorded.

Stop. Hand control to the caller or the chosen downstream skill.
</success_criteria>

<final_reminders>
P0 - Step 1 makes zero source-reading tool calls.
P0 - Internal directions are never printed.
P0 - User-owned gap → `d0`. Code-fact gap → Step 2.
P0 - Step 3 STOPs and waits for explicit user confirmation.
P0 - Default output is the Step 3 summary only. `<on_demand_output>` runs only on explicit user request.
P0 - Candidate generation runs only in Step 4 branch (c), only on user request.
P1 - Do not write tests or code. Hand off to `write-tests` / `c-0`.
P2 - If the user supplies all Step 1 facts up front, skip to Step 3.
P2 - Mirror the user's language.
</final_reminders>
</content>
