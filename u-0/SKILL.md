---
name: u-0
description: Use as the lightweight understanding step (no formal HLD, MAIN-session execution) — explores code via the `my-explore` subagent, identifies the gap between requirement and current state, discusses with the user until both sides are clear, then confirms the result.
---

<role>Lightweight understanding coordinator executing in the main session; produces a confirmed gap analysis, not a formal HLD.</role>

<instructions>
1. **Read the requirement.** Identify the symptom (bugs) or desired behavior (features), and any named files / symbols / UI labels.
2. **Explore the relevant code via `my-explore` subagent.** Build a request per `~/.claude/agents/my-explore/PROTOCOL.md` (Intent + ≤3 Directions + optional Anchors + optional Budget) and dispatch via `Agent(subagent_type="my-explore", prompt=<request>)`. The subagent returns JSON with `results[]` — each entry includes a `body` field with verbatim source code. Read those raw bodies and reason from them. Do NOT relay them to the user. Do NOT explore via direct tool calls in the main session; the subagent boundary is what keeps main context clean.
3. **Draft the gap analysis.** Bug → symptom / root cause / fix approach. Feature → current state / target state / approach.
4. **Discuss with the user.** Ask about every ambiguity. Iterate until both sides are aligned on problem + solution.
5. **Present and confirm.** Output ONLY the `<default_output>` block (the concise gap-analysis summary). STOP and wait for explicit user confirmation before handing off to downstream skills.
6. **On-demand details.** If — and only if — the user explicitly asks for files / key files / scope / locations after step 5, output the `<on_demand_output>` block.
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

- Exploration used `my-explore` subagent only, no direct `Read` on source.
- Every ambiguity was asked, not assumed.
- The `<default_output>` block was emitted (concise — no file lists, no exploration dumps).
- The user explicitly confirmed.

Stop immediately. Hand control to the caller.
</success_criteria>

<final_reminders>
P0 — Exploration MUST use `my-explore` subagent.
P0 — NEVER guess when the requirement is ambiguous. Ask the user.
P0 — NEVER skip the final user confirmation STOP.
P0 — NEVER dump `my-explore` subagent's raw output, key-files lists, or "Files in scope" by default. The default user-visible output is the concise `<default_output>` summary only. File lists are emitted ONLY when the user explicitly asks.
P1 — Do not write tests or code. Those are downstream (`write-tests` / `c-0`).
P2 — If the user provides exploration context up front, skip to step 3.
</final_reminders>
