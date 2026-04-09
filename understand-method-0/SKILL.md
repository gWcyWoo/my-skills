---
name: understand-method-0
description: Deep understanding of a single method/function — purpose & signature, implementation walkthrough, and call sites with input provenance. Runs in the MAIN session; does not dispatch a subagent. The `-0` suffix denotes main-session execution (parallels `my-explore-0` / `understand-0` / `code-0`).
---

# Understand Method

Investigate ONE method and produce a structured three-section explanation. Work in the main session directly — do not dispatch Agent. The knowledge stays in context for any follow-up edits.

## Tool rules (must follow)

- **Source code:** use `probe extract_code` with `file#symbol` or `file:line`. **Never use Read on `.ts / .tsx / .js / .jsx / .py / .go / .rs / .java / .rb / .php / .c / .cpp / .vue / .svelte` etc.** Read is for non-source files only (md / json / yaml / configs / logs).
- **Callers:** use `LSP findReferences`. Never Grep for callers.
- **Batching:** when reading multiple call sites, pass them all in one `probe extract_code files=[...]` call. Do not loop per-file.
- **No duplicate verification:** do not run a second tool to confirm what an authoritative tool already answered.

## Tool sequence (adapt — skip any step you already know the answer to)

1. **Locate the method.** If the target is given as `file#symbol` or `file:line`, skip. Otherwise: `LSP workspaceSymbol`.
2. **Read the body.** `probe extract_code files=["<file>#<method>"]` — returns the function body.
3. **Find all callers in one call.** `LSP findReferences` on the method.
4. **Read call sites, batched.** `probe extract_code files=[caller1_file:line, caller2_file:line, ...]`.
5. **Trace input provenance — one hop only.** For arguments that are computed at the call site, follow the value ONE hop back to where it originates. Do not trace deeper unless the user explicitly asks for the full flow.

Stop the moment all three output sections are filled with file:line precision.

## Output format

### 1. Purpose & Signature

- **Purpose:** one sentence on what this method does and what concept it implements.
- **Inputs:** each parameter as `name: type` — one-line meaning.
- **Output:** `type` — one-line meaning.
- **Side effects (if any):** state mutations, I/O, async operations.

### 2. Implementation walkthrough

Walk through how inputs are transformed into the output, anchored to `file:line` for every meaningful step. Include:

- Key branches and why they exist.
- Side effects, state mutations, async boundaries.
- External dependencies (libraries, DB, APIs, other services) with `file:line` where invoked.

One bullet per step. Keep it tight.

### 3. Call sites & input provenance

For each significant caller:

- **`caller at file:line`** — scenario that triggers this call.
- **Input construction:** for each argument, one line on how it is built:
  - Literal → note the value or shape.
  - Computed → trace ONE hop back to the source (variable / prop / state / API response) with `file:line`.
  - Passed through → name the outer function or prop it came from.

If there are more than ~5 callers, group by scenario, show the 3–5 most important, and mention the total count.
