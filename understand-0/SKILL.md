---
name: understand-0
description: Use as the lightweight understanding step (no formal HLD, MAIN-session execution) — explores code via `my-explore-0`, identifies the gap between requirement and current state, discusses with the user until both sides are clear, then confirms the result.
---

<role>Lightweight understanding coordinator executing in the main session; produces a confirmed gap analysis, not a formal HLD.</role>

<instructions>
1. **Read the requirement.** Identify the symptom (bugs) or desired behavior (features), and any named files / symbols / UI labels.
2. **Explore the relevant code.** Invoke the `my-explore-0` skill. A `-0` skill stays in the main session and only calls other `-0` or non-dispatching skills.
3. **Draft the gap analysis.** Bug → symptom / root cause / fix approach. Feature → current state / target state / approach.
4. **Discuss with the user.** Ask about every ambiguity. Iterate until both sides are aligned on problem + solution.
5. **Present and confirm.** Output the applicable `<output_format>` block. STOP and wait for explicit user confirmation before handing off to downstream skills.
</instructions>

<output_format>
**Bug fix:**

Symptom: <one sentence, user's words>
Root cause: <one sentence + file:line>
Fix approach: <one sentence>

Key files:
- <path:line> — <one-line role>
- <path:line> — <one-line role>

**Feature / change:**

Goal: <one sentence, user's words>

Structure: (if the query involves a page or UI, list the layout top-to-bottom as bullet points)
- <section>: <component name> — <one-line role>
- <section>: <component name> — <one-line role>

Key files:
- <path:line> — <one-line role>
- <path:line> — <one-line role>

Gap: <one sentence>
Approach: <one to three sentences>
</output_format>

<success_criteria>
Complete when ALL hold:

- Exploration used `my-explore-0` only, no direct `Read` on source.
- Every ambiguity was asked, not assumed.
- The applicable output block is filled with file:line precision.
- The user explicitly confirmed.

Stop immediately. Hand control to the caller.
</success_criteria>

<final_reminders>
P0 — Exploration MUST use `my-explore-0`.
P0 — NEVER guess when the requirement is ambiguous. Ask the user.
P0 — NEVER skip the final user confirmation STOP.
P0 — This skill produces lightweight understanding, NOT a formal HLD. Invoke `hld` separately if a formal design artifact is needed.
P1 — Do not write tests or code. Those are downstream (`write-tests` / `code-0`).
P2 — If the user provides exploration context up front, skip to step 3.
</final_reminders>
