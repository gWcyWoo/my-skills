# Trace

The query asks how data or control flows across files. The goal is to answer the user's question by reading code and squeezing maximum insight from every piece of data before reaching for more.

## Core principle

**Think before you fetch.** After every tool call, exhaust what you can derive from data already in hand. Only call another tool when you hit something you genuinely cannot deduce from existing data.

## Flow

### Step 1 — Bootstrap

The only step where concept search is allowed. Use `mcp__probe__search_code` or `rg -n` to find the entry point.

### Step 2+ — Derive-then-fetch loop

After each tool call:
1. Run the Derive block (defined in SKILL.md) — squeeze everything you can from all code read so far
2. If Decision = ANSWER → stop, write the answer
3. If Decision = FETCH → make the tool call, then return to step 1
4. If Decision = GAP → mark it, check if you can still ANSWER with gaps; if not, report partial answer

### Answer

When Decision = ANSWER, write:
- **Flow**: the chain `A (file:line) → B (file:line) → C (file:line)`, with `[gap: reason]` for unresolved links
- **Behavior**: what happens at each step, derived from code you read
- **Gaps**: what you could not confirm and why

## Rules

- **No searching for symbols not in read code.** Every FETCH target must be a symbol literally visible in code you already read. Guessing names is forbidden.
- **No re-searching.** If a search returns nothing, try ONE alternative term. If that also fails, it's a GAP.
- **Concept search only in Step 1.** After Step 1, all tool calls must target specific symbols/files extracted from read code.
- **Prefer `file#symbol` over `file:line` for extract_code.** `file:line` returns the node at that line; `file#symbol` returns the full function body.
- **Batch when possible.** If Derive identifies multiple FETCH targets, use ONE `mcp__probe__extract_code files=[...]` call.
- **Maximum 5 tool calls.** If you hit 5, stop and ANSWER with what you have.

## Boundary

Use the boundary declared in the skill entrypoint. If a FETCH target would cross the boundary, do not fetch it — mark it `[gap: crosses boundary into X]` and continue Derive with remaining data.
