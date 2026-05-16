---
name: u0
description: "Lightweight understanding step in the main session. First clarify the user's requirement via discussion with no code lookup. Then explore code: the main session uses the `my-explore-0` palette directly for up to 2 directions, and dispatches the `my-explore` custom agent for 3 or more. Produce a concise gap analysis, get explicit user confirmation, then hand off or iterate."
---

<role>
Lightweight understanding coordinator in the main session. Absorbs ALL user dialogue; there is no separate discussion skill. Discussion happens inside Step 1 and Step 4 here. Produces a confirmed gap analysis, not a formal HLD.
</role>

<instructions>

## Step 1 - Understand the requirement (NO code lookup)

Read the user's opening. Identify the symptom for bugs, the desired behavior for features, and any named files, symbols, UI labels, routes, commands, or errors they mentioned. Ask the user about EVERY ambiguity; never assume.

Iterate with the user until the requirement is concrete enough to drive specific exploration directions. Then convert the clarified requirement into internal `directions`: concrete, retrievable questions such as "does X exist?", "what calls Y?", "what is the body of Z?", or "where is feature F's entry point?".

This conversion is model-internal. Do NOT print the directions list to the user. The user sees only your clarifying questions and, eventually, the Step 3 summary.

HARD RULE for this step: NEVER touch target code. Do not use `mcp__probe__search_code`, `mcp__probe__extract_code`, `mcp__ast_grep__find_code`, any `mcp__language_server__*` tool, native `rg`, `grep`, `git grep`, `find` over target source, `cat`, `head`, `tail`, `sed`, `awk`, any Codex/browser/IDE source-reading equivalent, or the `my-explore` custom agent. Code lookup starts only at Step 2.

## Step 2 - Explore code (routed by direction count)

Count the independent directions produced in Step 1. Route by one mechanical gate:

### Route A - <=2 directions: main session, palette direct

Read `/Users/Woo/.agents/skills/my-explore-0/SKILL.md` as the palette manual, then call the listed Codex MCP tools directly in the main session. Use only the tools and call shapes allowed by that palette, including:

- `mcp__probe__extract_code`
- `mcp__probe__search_code`
- `mcp__ast_grep__find_code`
- `mcp__language_server__get_symbol_definitions`
- `mcp__language_server__get_symbol_references`
- `mcp__language_server__get_diagnostics`

Follow the palette priority, forbidden rules, stop rule, and call budget. Trade-off: result bodies land in main context. That is the accepted cost of the lightweight path.

### Route B - >=3 directions: `my-explore` custom agent

Dispatch the Codex `my-explore` custom agent using the available custom-agent entrypoint. Build the request with `Intent`, up to 3 `Directions` per request, optional `Anchors`, and optional `Budget`. Request concise evidence. The custom agent returns evidence; read the evidence bodies and reason on them. Never paste raw agent output or raw JSON to the user.

### Overrides

- If the user explicitly says to use `my-explore`, a subagent, or equivalent, use Route B regardless of direction count.
- If the user explicitly says not to use a subagent, or says the main session should check directly, use Route A regardless of direction count.
- Mid-flight escalation: if a Route A direction expands into several distinct sub-questions, or the main context starts visibly polluting, pivot remaining directions to Route B for the next batch.

## Step 3 - Synthesize and present

Emit ONLY the `<default_output>` block below. Use clickable Codex file links for every code-backed claim: `[path](/absolute/path:line)`. STOP. Wait for the user's explicit confirmation before doing anything else.

## Step 4 - Decide next step (with user)

After confirmation, ask the user which:

- **(a) Refine directions and re-explore** - return to Step 2 with new or sharper directions.
- **(b) Requirement itself needs reshaping** - return to Step 1.
- **(c) List candidates / trade-offs** based on EXISTING evidence - produce 2 named directions, each with a one-line trade-off. No new exploration. Candidate generation lives only here; do not invoke it spontaneously.
- **(d) Hand off to `c-0` / `write-tests` / `hld`** - emit the final summary, stop, and let the downstream skill take over.

If the user explicitly asks for "files", "scope", or "locations" at any time after Step 2 has produced evidence, emit `<on_demand_output>`.

</instructions>

<default_output>
**Bug fix:**

Symptom: <one sentence, user's words>
Root cause: <one sentence + clickable file link>
Fix approach: <one sentence>

**Feature / change:**

Goal: <one sentence, user's words>
Current state: <one sentence + clickable file link>
Gap: <one sentence>
Approach: <one to three sentences>
</default_output>

<on_demand_output>
Emit ONLY when the user explicitly asks, for example "show files", "key files?", or "what's in scope?".

Files in scope:
- [path](/absolute/path:line) - <one-line role>
- [path](/absolute/path:line) - <one-line role>
</on_demand_output>

<success_criteria>
Complete when ALL hold:

- Step 1 finished BEFORE any code lookup; every ambiguity was asked, not assumed.
- Step 2 routed correctly by direction count (<=2 -> Route A, >=3 -> Route B), with any mid-flight escalation noted.
- The `<default_output>` block was emitted, concise, with no file lists and no exploration dumps.
- Every code-backed claim uses a clickable Codex file link with a concrete line number.
- The user explicitly confirmed.
- Step 4 next-step decision was recorded.

Stop. Hand control to the caller or the chosen downstream skill.
</success_criteria>

<final_reminders>
P0 - Step 1 NEVER reads code. Code lookup begins only at Step 2.
P0 - Step 1's converted directions are model-internal. Do NOT print them to the user; that is the d0-style ceremony that was deleted.
P0 - NEVER guess when the requirement is ambiguous. Ask.
P0 - Step 2 routing is mechanical: count independent directions. <=2 -> main-session palette; >=3 -> `my-explore` custom agent. No fuzz, no "feels light enough".
P0 - Route A must follow `/Users/Woo/.agents/skills/my-explore-0/SKILL.md`.
P0 - NEVER skip the Step 3 STOP-and-confirm.
P0 - NEVER dump raw exploration results, `my-explore` agent output, or files in scope by default. The default user-visible output is the concise `<default_output>` only. File lists are emitted ONLY when the user explicitly asks.
P0 - Candidate generation lives ONLY in Step 4 branch (c), only when the user asks. Never volunteer candidates mid-flow; that was d0's job, and d0 has been retired.
P1 - Do not write tests or code. Those are downstream (`write-tests` / `c-0`).
P2 - If the user provides exploration context up front, you may skip to Step 3.
P2 - Mirror the user's language.
</final_reminders>
