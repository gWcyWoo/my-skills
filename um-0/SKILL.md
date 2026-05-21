---
name: um-0
description: Analyze one method/function in main session. Output signature, implementation steps, call sites, and one-hop input provenance.
---

<role>Main-session method analyst. Do not dispatch agents.</role>

<instructions>
1. **Explore.** Follow the active `AGENTS.md` source-exploration rules. Do not dispatch an exploration agent.
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
- Branch condition and branch effect.
- Side effects, state mutations, async boundaries.
- External dependencies (libraries, DB, APIs) with `file:line`.

### 3. Call Sites & Input Provenance

Per direct caller:
- **`caller at file:line`** — scenario that triggers this call.
- **Input construction:** one line per argument:
  - Literal → note the value.
  - Computed → trace one hop to the source with `file:line`.
  - Passed through → name the outer function or prop.

If > 5 direct callers exist, group by trigger scenario, list the first 5 callers returned by the reference tool, and state the total count.
</output_format>

<final_reminders>
P0 — Code exploration MUST follow the active `AGENTS.md` source-exploration rules. No raw shell reads or `rg` on source.
P0 — Stop when all three output sections are filled with file:line precision.
P1 — Trace input provenance ONE hop only unless the user explicitly asks for more.
</final_reminders>
