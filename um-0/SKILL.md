---
name: um-0
description: Deep understanding of a single method/function — purpose & signature, implementation walkthrough, and call sites with input provenance. Runs in the MAIN session; does not dispatch a subagent.
---

<role>Method analyst in main session. Never read source directly — all exploration via `my-explore-0`.</role>

<instructions>
1. **Explore.** Invoke `my-explore-0` to collect all data needed to fill the three output sections below.
2. **Present.** Fill the `<output_format>` with file:line precision. Stop.
</instructions>

<output_format>
### 1. Purpose & Signature

- **Purpose:** one sentence on what this method does.
- **Inputs:** `name: type` — one-line meaning each.
- **Output:** `type` — one-line meaning.
- **Side effects (if any):** state mutations, I/O, async operations.

### 2. Implementation Walkthrough

One bullet per step, anchored to `file:line`:
- Key branches and why they exist.
- Side effects, state mutations, async boundaries.
- External dependencies (libraries, DB, APIs) with `file:line`.

### 3. Call Sites & Input Provenance

Per significant caller:
- **`caller at file:line`** — scenario that triggers this call.
- **Input construction:** one line per argument:
  - Literal → note the value.
  - Computed → trace one hop to the source with `file:line`.
  - Passed through → name the outer function or prop.

If > 5 callers, group by scenario, show the 3–5 most important, mention the total count.
</output_format>

<final_reminders>
P0 — ALL code exploration MUST use `my-explore-0`. No direct Read/Grep/LSP/probe on source.
P0 — Stop when all three output sections are filled with file:line precision.
P1 — Trace input provenance ONE hop only unless the user explicitly asks for more.
</final_reminders>
