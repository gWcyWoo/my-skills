---
name: understand-method
description: Use when the user wants a deep explanation of one existing method or function, including purpose, signature, implementation steps, and important call sites with one-hop input provenance.
---

# Understand Method

Investigate ONE method and produce a structured three-section explanation. In Codex, the synthesis stays in the main session, but all source-code navigation must go through `my-explore`.

## When to Use

- The user wants to understand one method or function in depth.
- The user needs purpose, signature, implementation flow, and caller context.
- The user may follow up with edits after understanding the current behavior.

## When NOT to Use

- The user is asking for broad architecture or multi-module data flow.
- The user wants requirements analysis for a change rather than explanation of existing code.
- The user needs only a quick summary instead of a method-level walkthrough.

## Code Navigation Rule

**The `my-explore` skill is the ONLY permitted code navigation methodology.** `understand-method` does not define alternate source-reading tools, fallback tools, or direct main-session code reads.

## Process

### Step 1: Launch Focused Exploration

Invoke `my-explore` with a question that preserves this exact scope:

```text
Understand exactly one method/function: {{TARGET}}.

Return a structured summary with file:line precision for these three sections only:
1. Purpose & Signature
2. Implementation walkthrough
3. Call sites & input provenance

Requirements:
- If {{TARGET}} is already `file#symbol` or `file:line`, use it directly. Otherwise locate the method first.
- Read the method body.
- Find callers with the authoritative navigation tool, not text grep.
- Read call sites in batch.
- Trace input provenance one hop only for computed arguments unless the user explicitly asked for full-flow tracing.
- Stop once all three sections are filled.
- If there are many callers, group by scenario, show the 3-5 most important, and mention the total count.
- Do not expand into architecture, unrelated flows, or speculative behavior.
```

### Step 2: Refine Without Respawning

If the first result is missing one section, lacks important call sites, or over-expands:

1. Do **not** read source directly in the main session.
2. Do **not** spawn a fresh subagent for the same method.
3. Send a narrower follow-up to the same `my-explore` agent specifying the missing piece only.

Stop refining once the three output sections are complete with file:line support.

### Step 3: Present the Explanation

Return the final answer in this structure.

## Output Format

### 1. Purpose & Signature

- **Purpose:** one sentence on what this method does and what concept it implements.
- **Inputs:** each parameter as `name: type` with a one-line meaning.
- **Output:** `type` with a one-line meaning.
- **Side effects (if any):** state mutations, I/O, async operations.

### 2. Implementation Walkthrough

Walk through how inputs are transformed into the output, anchored to `file:line` for every meaningful step. Include:

- Key branches and why they exist.
- Side effects, state mutations, async boundaries.
- External dependencies with `file:line` where invoked.

Use one bullet per step. Keep it tight.

### 3. Call Sites & Input Provenance

For each significant caller:

- **`caller at file:line`** — scenario that triggers this call.
- **Input construction:** for each argument, one line on how it is built:
  - Literal: note the value or shape.
  - Computed: trace one hop back to the source with `file:line`.
  - Passed through: name the outer function, prop, or state source it came from.

If there are more than about five callers, group by scenario, show the three to five most important, and mention the total count.
