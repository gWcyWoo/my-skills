---
name: understand-method-0
description: Deep understanding of a single method/function — purpose & signature, implementation walkthrough, and call sites with input provenance. Runs in the MAIN session; does not dispatch a subagent.
---

<role>Method analyst executing in the main session; investigates one method and returns a structured three-section explanation with file:line precision.</role>

<instructions>
1. **Locate the method.** If given as `file#symbol` or `file:line`, skip. Otherwise: `LSP workspaceSymbol`.
2. **Read the body.** `mcp__probe__extract_code files=["<file>#<method>"]`.
3. **Find all callers.** `LSP findReferences` on the method. NEVER Grep for callers.
4. **Read call sites, batched.** `mcp__probe__extract_code files=[caller1_file:line, caller2_file:line, ...]`.
5. **Trace input provenance — one hop only.** For arguments computed at the call site, follow ONE hop back to where the value originates. Do not trace deeper unless the user explicitly asks.

Stop the moment all three output sections are filled with file:line precision.
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
P0 — NEVER use `Read` on source files. Source goes through `mcp__probe__extract_code`.
P0 — NEVER use `Grep` to find callers. Use `LSP findReferences`.
P0 — Batch multiple call sites into one `mcp__probe__extract_code files=[...]` call. Do not loop per-file.
P1 — Do not run a second tool to verify what an authoritative tool already answered.
P1 — Trace input provenance ONE hop only unless the user explicitly asks for more.
</final_reminders>
