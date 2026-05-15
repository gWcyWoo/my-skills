---
name: u-0
description: Use as the lightweight understanding step (no formal HLD, MAIN-session execution) — explores code via the `my-explore` skill, identifies the gap between requirement and current state, discusses with the user until both sides are clear, then confirms the result.
---

<role>Lightweight understanding coordinator executing in the main session; produces a confirmed gap analysis, not a formal HLD.</role>

<instructions>
1. **Read the requirement.** Identify the symptom (bugs) or desired behavior (features), and any named files / symbols / UI labels.
2. **Explore the relevant code via `my-explore`.** Invoke the `my-explore` skill. Build a request using its protocol: `Intent`, at most 3 `Directions`, optional `Anchors`, optional `Budget`. The `my-explore` skill manages the isolated child agent and returns JSON evidence. Read the returned `results[].body` internally and reason from it. Do not relay raw bodies to the user. Do not explore target-repository source with direct tools in the main session.
3. **Draft the gap analysis.** Bug → symptom / root cause / fix approach. Feature → current state / target state / approach.
4. **Discuss with the user.** Ask about every ambiguity. Iterate until both sides are aligned on problem + solution.
5. **Present and confirm.** Output only the matching `<default_output>` block. STOP and wait for explicit user confirmation before handing off to downstream skills.
6. **On-demand details.** If the user explicitly asks for files, key files, scope, or locations after step 5, output `<on_demand_output>`.
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
Emit only when the user explicitly asks, for example "show files", "key files?", or "what's in scope?".

Files in scope:
- path:line — <one-line role>
- path:line — <one-line role>
</on_demand_output>

<success_criteria>
Complete when ALL hold:

- Exploration used the `my-explore` skill only; the main session did not read target-repository source directly.
- Every ambiguity was asked, not assumed.
- The matching `<default_output>` block was emitted.
- The user explicitly confirmed.

Stop immediately. Hand control to the caller.
</success_criteria>

<final_reminders>
P0 — Exploration MUST use the `my-explore` skill.
P0 — Do not call `spawn_agent` directly from `u-0` for code exploration; `my-explore` owns child-agent management.
P0 — NEVER guess when the requirement is ambiguous. Ask the user.
P0 — NEVER skip the final user confirmation STOP.
P0 — This skill produces lightweight understanding, NOT a formal HLD. Invoke `hld` separately if a formal design artifact is needed.
P0 — Never dump `my-explore` raw JSON, raw source bodies, key-file lists, or files in scope by default. Emit file lists only when the user explicitly asks.
P1 — Do not write tests or code. Those are downstream (`write-tests` / `c-0`).
P2 — If the user provides exploration context up front, skip to step 3.
</final_reminders>
