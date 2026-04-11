# Trace

The query asks how data or control flows across files. The goal is to answer the user's question by reading code and squeezing maximum insight from every piece of data before reaching for more.

## Core principle

**Think before you fetch.** After every tool call, exhaust what you can derive from data already in hand. Only call another tool when you hit something you genuinely cannot deduce from existing data.

## Before every tool call — mandatory Derive block

Before ANY tool call (including the first one), print this block. Every field is mandatory.

```
Goal: <the user's question in one sentence>
Missing: <what you still don't know to answer the goal>

Have:
- <file:line — concrete code line or fact you already obtained>
- <file:line — another one>
- (list everything relevant you have so far)

Derive:
- From <file:line>: <what this tells us> → Missing updates: <what is no longer missing>
- From <file:line>: <what this tells us> → next hop is <symbol> because <code says so>
- From <file:line> + <file:line>: <combined inference> → can now confirm <conclusion>
- ... (keep going until you cannot derive anything more from Have)
- STUCK: <the specific thing you need that cannot be derived from any data in Have>

Decision:
- ANSWER: Have + Derive is enough to answer Goal → write the answer, no more tool calls
- FETCH: STUCK names a concrete symbol/event visible in Have → tool call to get it
- GAP: STUCK names something not visible in any data in Have → mark [gap], do not search
```

Rules for the Derive block:
- Every Derive line must reference a specific `file:line` from Have. No line, no derivation.
- Derive is a multi-step chain. Keep deriving until no more conclusions can be drawn.
- STUCK must name ONE specific thing. "I need more context" is not valid. "I need the listener for EVENT_RESUME_UPLOADED which appears at upload.service.ts:45" is valid.
- Decision FETCH is only allowed when STUCK names a symbol that literally appears in Have. If it doesn't appear in Have, the decision is GAP.

## Flow

### Step 1 — Bootstrap

The only step where concept search is allowed. Use `mcp__probe__search_code` or `rg -n` to find the entry point.

Print the Derive block before this call. At this point Have may be empty or contain only the user's query context — that's fine. STUCK should be "entry point for [concept] is unknown."

### Step 2+ — Derive-then-fetch loop

After each tool call:
1. Add the new data to Have
2. Run Derive — squeeze everything you can from all data in Have
3. If Decision = ANSWER → stop, write the answer
4. If Decision = FETCH → make the tool call, then return to step 1
5. If Decision = GAP → mark it, check if you can still ANSWER with gaps; if not, report partial answer

### Answer

When Decision = ANSWER, write:
- **Flow**: the chain `A (file:line) → B (file:line) → C (file:line)`, with `[gap: reason]` for unresolved links
- **Behavior**: what happens at each step, derived from code you read
- **Gaps**: what you could not confirm and why

## Rules

- **No searching for symbols not in Have.** Every FETCH target must be a symbol literally visible in code you already read. Guessing names is forbidden.
- **No re-searching.** If a search returns nothing, try ONE alternative term. If that also fails, it's a GAP.
- **Concept search only in Step 1.** After Step 1, all tool calls must target specific symbols/files extracted from Have.
- **Prefer `file#symbol` over `file:line` for extract_code.** `file:line` returns the node at that line; `file#symbol` returns the full function body.
- **Batch when possible.** If Derive identifies multiple FETCH targets, use ONE `mcp__probe__extract_code files=[...]` call.
- **Maximum 5 tool calls.** If you hit 5, stop and ANSWER with what you have.

## Boundary

Use the boundary declared in the skill entrypoint. If a FETCH target would cross the boundary, do not fetch it — mark it `[gap: crosses boundary into X]` and continue Derive with remaining data.
