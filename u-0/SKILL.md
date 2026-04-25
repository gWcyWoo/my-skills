---
name: u-0
description: Use as the lightweight understanding step (no formal HLD, MAIN-session execution) — explores code via `my-explore-0`, identifies the gap between requirement and current state, discusses with the user until both sides are clear, then confirms the result.
---

<role>Lightweight understanding coordinator executing in the main session; produces a confirmed gap analysis, not a formal HLD.</role>

<instructions>
1. **Read the requirement.** Identify the symptom (bugs) or desired behavior (features), and any named files / symbols / UI labels.
2. **Explore the relevant code.** Invoke the `my-explore-0` skill in quiet mode for u-0. A `-0` skill stays in the main session and only calls other `-0` or non-dispatching skills.
3. **Draft the gap analysis internally.** Bug → symptom / root cause / fix approach. Feature → current state / target state / approach.
4. **Discuss with the user.** Ask only about ambiguities that block the next correct step. Iterate until both sides are aligned on problem + solution.
5. **Present and confirm.** Output only the concise `<output_format>` block by default. STOP and wait for explicit user confirmation before handing off to downstream skills.
</instructions>

<output_format>
**Summary:** <one to three sentences covering the confirmed current behavior, root gap, and intended approach>

**Needs Confirmation:** <only the specific scope/behavior question that requires user confirmation before implementation; if there is no unresolved ambiguity, ask the user to confirm the summarized scope>
</output_format>

<detail_policy>
- Do not print key files, file:line evidence, execution paths, structure maps, hypothesis plans, or raw exploration notes by default.
- Keep those details available internally for downstream work.
- Print detailed evidence only when the user explicitly asks for it, or when a concrete file reference is necessary to make the confirmation question understandable.
- If details are requested, keep them short and relevant to the active scope.
</detail_policy>

<success_criteria>
Complete when ALL hold:

- Exploration used `my-explore-0` only, no direct `Read` on source.
- Every ambiguity was asked, not assumed.
- The applicable output block is concise and contains only summary plus required confirmation.
- The user explicitly confirmed.

Stop immediately. Hand control to the caller.
</success_criteria>

<final_reminders>
P0 — Exploration MUST use `my-explore-0`.
P0 — NEVER guess when the requirement is ambiguous. Ask the user.
P0 — NEVER skip the final user confirmation STOP.
P0 — This skill produces lightweight understanding, NOT a formal HLD. Invoke `hld` separately if a formal design artifact is needed.
P0 — Do not print detailed investigation output unless the user explicitly asks for it.
P1 — Do not write tests or code. Those are downstream (`write-tests` / `c-0`).
P2 — If the user provides exploration context up front, skip to step 3.
</final_reminders>
