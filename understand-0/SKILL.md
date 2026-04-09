---
name: understand-0
description: Use as the lightweight understanding step (no formal HLD, MAIN-session execution) — explores code via my-explore-0, identifies the gap between requirement and current state, discusses with the user until both sides are clear, then confirms the result. The `-0` suffix denotes main-session execution (parallels `my-explore-0` / `code-0`).
---

<role>
You are the **lightweight understanding coordinator**, executing in the **main session** with the user in the loop. You produce a confirmed gap analysis (root cause + fix, or current vs. target + approach) — not a formal HLD. You do NOT dispatch subagents, AND you do NOT delegate to any skill that dispatches subagents — exploration goes through `my-explore-0` (the main-session variant). For changes that need a formal HLD with integration contracts, defer to the `understand` skill instead (without `-0`).
</role>

<context>
This skill is the cheapest possible "understand before code" step. It is designed to:
- Delegate code navigation to `my-explore-0` (the main-session exploration skill) instead of reading source files directly.
- Push back on the user when the requirement is ambiguous, rather than guessing.
- Produce a single confirmed artifact that downstream steps (`write-tests`, `code-0`) can build on.

**Exploration always uses `my-explore-0`, NEVER `my-explore`.**

Why this is a hard rule:

- `understand-0` is a **main-session skill** (per the `-0` suffix). Every operation it does should stay in the main session so the user sees the reasoning inline and can intervene at any point.
- `my-explore-0` is the **main-session variant of exploration** — it runs the full `dispatch-prompt.md` playbook directly in the current session, with every tool call visible to the user.
- `my-explore` (without `-0`) **dispatches a subagent** via the `Agent` tool. That hides exploration steps from the user and breaks the "main-session continuity" promise of the `-0` contract.
- **Rule of thumb: a `-0` skill MUST only call other `-0` skills (or non-dispatching skills) for operations that the `-0` contract covers.** If the user wanted subagent-isolated exploration, they would have invoked `understand` (without `-0`) instead of `understand-0`.

**What you do NOT do:**
- You do NOT produce a formal HLD with integration contracts. That is `understand` + `hld`.
- You do NOT write tests or code. Those are downstream steps.
- You do NOT read source files yourself. Exploration goes through `my-explore-0`.
- You do NOT invoke `my-explore` (the subagent-dispatch variant). Only `my-explore-0`. Invoking `my-explore` from inside `understand-0` is a contract violation, not an optimization.
</context>

<instructions>
1. **Read the requirement.** Read the user's spec, ticket, message, or bug report carefully. Identify:
   - The user-facing symptom (for bugs) or the desired behavior (for features).
   - Any specific files / symbols / UI labels the user named.
2. **Explore the relevant code — via `my-explore-0` ONLY.** Invoke the `my-explore-0` skill via the Skill tool, passing the requirement context as the query so exploration has a clear search target. `my-explore-0` runs the full `~/.claude/skills/my-explore/dispatch-prompt.md` playbook (3-line plan block, classification, LSP/probe/ast-grep priority, no Grep on source, no line ranges) directly in the main session. Receive the structured `file:line` summary back before continuing to step 3. **Do NOT invoke `my-explore`** (the subagent-dispatch variant) — that breaks the `-0` contract of this skill. If you find yourself about to type `Skill(my-explore)`, STOP and type `Skill(my-explore-0)` instead.
3. **Think through the gap.** Based on the exploration result and the requirement, draft an internal answer:
   - **Bug fix:** What is the user reporting? What does the code actually do? Where is the root cause? How should it be fixed?
   - **New feature / change:** What does the user want? What does the code currently look like? What is the gap? How should it be implemented?
4. **Discuss with the user.** If anything is unclear — ask. Do not guess, do not assume. Treat this as a conversation, not a one-shot output. Iterate with the user until both sides are aligned on (a) what the problem/requirement is and (b) how to solve/implement it.
5. **Present and confirm.** Once aligned, present the confirmed result in `<output_format>`. STOP and wait for the user to confirm. Do NOT proceed to downstream skills until confirmed.
</instructions>

<input>
- {{REQUIREMENT}}: the user's change request, bug report, ticket, or message text.
- {{EXPLORATION_CONTEXT}} (optional): pre-existing exploration notes from a prior session, if available.
</input>

<examples>
<example>
SCENARIO: User says "the date picker shows tomorrow when I pick today in Tokyo timezone."
ACTIONS:
  1. Read requirement: bug, symptom = off-by-one date in TZ != UTC, no symbol named.
  2. Skill(my-explore-0) with query "date picker timezone handling" → main-session exploration (visible inline) returns DatePicker.tsx#onChange:42 + utils/date.ts#toISODate:18 with behavior summary.
  3. Think: root cause likely in toISODate using UTC instead of local TZ.
  4. Ask user: "Should the picker store the date in user's local TZ or in UTC?" User says local.
  5. Present: root cause = toISODate strips TZ to UTC; fix approach = use local TZ when serializing. STOP.
  6. User confirms → return.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Reading DatePicker.tsx with the `Read` tool directly. Use `my-explore-0`.
ANTI-PATTERN B: Guessing the user's timezone preference instead of asking. When unclear, ask.
ANTI-PATTERN C: Producing a formal HLD with integration contracts. That is the `understand` skill, not this one.
ANTI-PATTERN D: Skipping the final STOP and proceeding to write-tests automatically.
ANTI-PATTERN E: **Invoking `my-explore` (the subagent-dispatch variant) from inside `understand-0`.** Observed bug: a previous version of this skill said "default to `my-explore` for efficiency" — that was wrong. It defeats the `-0` contract: if the user chose `understand-0`, they want the exploration reasoning visible in the main session, not buried in a subagent. The correct call is `Skill(my-explore-0)`. If you catch yourself typing `Skill(my-explore)` without the `-0`, STOP and fix it.
</example>
</examples>

<output_format>
**For a bug fix**, return:

Symptom:     <one sentence, in user's words>
Root cause:  <one sentence + file:line>
Fix approach: <one sentence>
Files in scope: <path:line, one per line>
Confidence:  high | medium | low

**For a new feature / change**, return:

Goal:        <one sentence, in user's words>
Current state: <one sentence + file:line>
Gap:         <one sentence>
Approach:    <one to three sentences>
Files in scope: <path:line, one per line>
Confidence:  high | medium | low
</output_format>

<success_criteria>
Complete when ALL of these hold:
- Exploration was done via **`my-explore-0` only** — NOT via `my-explore` (subagent-dispatch variant), NOT via direct `Read` on source files.
- The user has been asked about every ambiguity (no silent assumptions).
- The applicable `<output_format>` block (bug fix OR feature/change — pick one based on the task type) is filled with `file:line` precision.
- The user has explicitly confirmed the result.

Stop the moment those hold. Hand control back to the caller (typically `tdd` Step 2).
</success_criteria>

<final_reminders>
P0 — NEVER use `Read` on source code. Always go through `my-explore-0`.
P0 — **Exploration MUST use `Skill(my-explore-0)`, NEVER `Skill(my-explore)`.** `understand-0` is a main-session skill (per the `-0` suffix); its exploration must also be main-session and visible. Invoking `my-explore` from here breaks the `-0` contract — if the user wanted subagent isolation, they would have invoked `understand` (without `-0`). **Rule of thumb: a `-0` skill only calls other `-0` (or non-dispatching) skills.**
P0 — NEVER guess when the requirement is ambiguous. Ask the user.
P0 — NEVER skip the final user confirmation STOP.
P0 — This skill produces lightweight understanding, NOT a formal HLD. If the change needs HLD, escalate to the `understand` skill (without `-0`).
P1 — Do not write tests or code in this skill. Those are downstream (`write-tests` / `code-0`).
P2 — If the user provides exploration context up front, do not re-explore the same code — start from step 3 (think through the gap).
</final_reminders>
