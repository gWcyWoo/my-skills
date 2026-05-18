---
name: u0
description: Lightweight understanding step in the main session. First clarify the user's requirement via discussion (NO code lookup). Then explore code — main session uses the `my-explore-0` palette directly when ≤2 directions, spawns the `my-explore` subagent when ≥3. Produce a concise gap-analysis, get explicit user confirmation, then hand off or iterate.
---

<role>
Lightweight understanding coordinator in the main session. Absorbs ALL user dialogue (there is no separate discussion skill — discussion happens inside Step 1 and Step 4 here). Produces a confirmed gap analysis, not a formal HLD.
</role>

<instructions>

## Step 1 — Understand the requirement (NO code lookup)

Read the user's opening. Identify symptom (bugs) or desired behavior (features) and any named files / symbols / UI labels they mentioned. Ask the user about EVERY ambiguity — never assume.

Iterate with the user until the requirement is concrete enough to drive specific exploration directions. Then convert the clarified requirement into internal *directions* — a list of concrete, retrievable questions ("does X exist?", "what calls Y?", "what is the body of Z?", "where is feature F's entry point?").

This conversion is **model-internal**. Do NOT print the directions list to the user. The user sees only your clarifying questions and (eventually) the Step 3 summary.

HARD RULE for this step: you NEVER touch code. No `Read`, `Grep`, `Glob`, `extract_code`, LSP, `ast-grep`, `search_code`, and no `Agent(subagent_type="my-explore")`. Code lookup only starts at Step 2.

## Step 2 — Explore code (routed by direction count)

Count the independent directions produced in Step 1. Route by single gate:

### Route A — ≤2 directions → main session, palette direct

Read `~/.claude/skills/my-explore-0/SKILL.md` and `~/.claude/skills/my-explore-0/TOOLS.md` as the palette manual, then call the listed tools **directly in the main session**:
`extract_code` (mcp__probe) · LSP `documentSymbol` / `findReferences` / `get_symbol_definitions` · `ast-grep` · `Glob` · `Grep` · `search_code`.

Follow palette priority: `extract_code > findReferences > LSP documentSymbol > ast-grep > Grep > search_code`. Trade-off: the result bodies land in main context — that is the accepted cost of the lightweight path.

### Route B — ≥3 directions → `my-explore` subagent

Dispatch via `Agent(subagent_type="my-explore", prompt=<request>)`. Build the request body per `~/.claude/agents/my-explore/PROTOCOL.md` (Intent + ≤3 Directions per request + Anchors + optional Budget). The subagent returns JSON with `results[]` — each entry has a `body` field with verbatim source. **Read the bodies, reason on them; never paste raw JSON to the user.**

### Overrides

- The user explicitly says "走 subagent" / "用 my-explore" / equivalent → Route B regardless of direction count.
- The user explicitly says "别开 subagent" / "主会话查就行" → Route A regardless.
- **Mid-flight escalation:** if a Route A direction balloons (each one expands into several sub-questions, or main context starts visibly polluting) → pivot the remaining directions to Route B for the next batch.

## Step 3 — Synthesize and present

Emit ONLY the `<default_output>` block below. STOP. Wait for the user's **explicit** confirmation before doing anything else.

## Step 4 — Decide next step (with user)

After confirmation, ask the user which:

- **(a) Refine directions and re-explore** → back to Step 2 with new/sharper directions.
- **(b) Requirement itself needs reshaping** → back to Step 1.
- **(c) List candidates / trade-offs** based on EXISTING evidence → produce 2 named directions, each with a one-line trade-off. **No new exploration.** This is the only place candidate-generation lives now; do not invoke it spontaneously.
- **(d) Hand off to `c-0` / `write-tests`** → emit final summary, stop.

If the user explicitly asks for "files / scope / locations" at any time after Step 2 has produced evidence, emit `<on_demand_output>`.

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
Emit ONLY when the user explicitly asks (e.g. "show files", "key files?", "what's in scope?"):

Files in scope:
- path:line — <one-line role>
- path:line — <one-line role>
</on_demand_output>

<success_criteria>
Complete when ALL hold:

- Step 1 finished BEFORE any code lookup; every ambiguity was asked, not assumed.
- Step 2 routed correctly by direction count (≤2 → Route A, ≥3 → Route B), with any mid-flight escalation noted.
- The `<default_output>` block was emitted (concise — no file lists, no exploration dumps).
- The user explicitly confirmed.
- Step 4 next-step decision recorded.

Stop. Hand control to the caller or the chosen downstream skill.
</success_criteria>

<final_reminders>
P0 — Step 1 NEVER reads code. Code lookup begins only at Step 2.
P0 — Step 1's converted directions are model-internal. Do NOT print them to the user — that is the d0-style ceremony we deleted.
P0 — NEVER guess when the requirement is ambiguous. Ask.
P0 — Step 2 routing is mechanical: count independent directions. ≤2 → main-session palette; ≥3 → my-explore subagent. No fuzz, no "feels light enough".
P0 — NEVER skip the Step 3 STOP-and-confirm.
P0 — NEVER dump raw exploration results, my-explore subagent JSON, or "Files in scope" by default. The default user-visible output is the concise `<default_output>` only. File lists are emitted ONLY when the user explicitly asks.
P0 — Candidate-generation lives ONLY in Step 4 branch (c), only when the user asks. Never volunteer candidates mid-flow — that was d0's job, and d0 has been retired.
P1 — Do not write tests or code. Those are downstream (`write-tests` / `c-0`).
P2 — If the user provides exploration context up front, you may skip to Step 3.
P2 — Mirror the user's language.
</final_reminders>
