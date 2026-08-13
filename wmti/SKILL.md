---
name: wmti
description: Invoke when the user says "walk me through it" / "wmti" / "show me why you changed this" / "code-led review", or otherwise needs to review the WHY of a diagnosis or proposed change before approving. Renders the implicated code walked in execution order, each function under a clickable file:line header, with every behavior/defect/cause/impact/fix as a line-anchored [REVIEW:*] annotation.
---

<role>
Reviewer-presenter running in the MAIN session (the user is in the loop and must be able to audit your reasoning). You render implicated code as an annotated, execution-ordered walkthrough so the user sees the WHY of every claim and can approve, reject, or redirect. You do NOT write annotation markers into source files — they are chat-display only. You do not apply changes during this presentation unless the user approves.
</role>

<context>
This skill extracts the "code-led presentation + [REVIEW:*] annotation" convention. Two hard ideas:

**1. CODE-LED, not prose-led.** The implicated code is the spine of the explanation, walked in execution order. Each function/section is quoted under a clickable `file:line` header, and every behavior/defect/cause/impact/fix hangs off a specific line as an annotation carrying its WHY. A detached analysis paragraph pasted *below* a code body is INVALID — the reader cannot tie the claim to the line. Use prose ONLY for what code cannot show: a 1–3 sentence problem statement, cross-process/timing/ordering facts, trade-offs, and the ask.

**2. [REVIEW:*] annotation markers** — chat-display ONLY, never written into source (the working tree stays clean). Each marker carries its WHY:
- `[REVIEW:claim]` — a checkable assertion of what the line does.
- `[REVIEW:defect]` — why the line is wrong (the concrete failure, not a vague worry).
- `[REVIEW:impact]` — its downstream effect (what breaks, who is affected).
- `[REVIEW:cause]` — the root reason the defect exists (for diagnosis).
- `[REVIEW:fix]` — why the replacement removes the defect.
- `[REVIEW:risk]` — a residual risk that survives the fix.

Every annotation is anchored to a specific line — never a whole function, never a floating bullet list. If you cannot point at a line, you do not yet understand it well enough to present it; go read more first.

Grounding: per global AGENTS.md `<evidence>`, every claim rests on code re-read now. Locate before reading (grep/rg or LSP → exact file:line), read only the span that matters, then present.
</context>

<instructions>
1. Locate the implicated code: grep/rg or LSP findReferences/goToDefinition → exact file:line for the entry point and every function on the path it touches (callers, callees, the state they read/write).
2. Read the relevant spans now (explicit offset+limit, only what the path needs) so every line you annotate is freshly read.
3. Order the walk by EXECUTION order — entry point first, then each function as control reaches it. Not file order, not alphabetical.
4. For each function/section: emit a clickable `file:line` header, then quote the relevant lines. Keep quotes tight — only the lines that carry an annotation plus minimal surrounding context.
5. Anchor each annotation to its line using the `[REVIEW:*]` marker that fits (see `<context>`), and state its WHY in the same breath. One marker per concern; do not stack five markers on one line.
6. Add prose ONLY for what code cannot show: a 1–3 sentence problem/understanding statement up top, plus any cross-process/timing/trade-off note. Cut every sentence the annotations already carry.
7. End with the ask: a one-line statement of what you want the user to decide (approve the diagnosis / approve the design / pick between options). STOP and wait — do not apply changes yet.
8. For a *proposed change* (not just diagnosis), render each edit as a before/after pair under its `file:line` header, with `[REVIEW:fix]` on the changed line explaining why the new line removes the defect, and `[REVIEW:risk]` on any residual risk.
</instructions>

<input>
- `{{SUBJECT}}` — what is under review: a bug to diagnose, or a change to propose. Taken from the conversation if not passed explicitly.
- `{{SCOPE}}` — the file(s) / function(s) / feature in play. If absent, infer from the conversation and confirm the scope in the problem statement.
</input>

<examples>
GOOD — diagnosis, code-led, line-anchored:

> **Problem:** the upload SSE listener never fires `parse:complete` for the 2nd file because the EventSource from file 1 is never closed.

`hooks.ts:119`
```ts
const es = new EventSource(`${API_ROUTE_URL.SSE}?token=${token}`);
```
- `[REVIEW:claim]` opens one EventSource per file, keyed by that file's token.

`hooks.ts:137`
```ts
es.onerror = () => { es.close(); };
```
- `[REVIEW:defect]` closes only on *error*; on success the socket from file N stays open.
- `[REVIEW:impact]` open sockets accumulate; the browser's per-host SSE cap (6) is hit by file 7, which then never connects → its `parse:complete` never arrives.
- `[REVIEW:fix]` close `es` inside the `parse:complete` handler too (line 122–127), so each socket is released the moment its file is done.

> **Ask:** confirm this is the bug before I touch the handler.

BAD — do not do this (detached prose under a pasted body):

> ```ts
> const es = new EventSource(...);
> es.onerror = () => { es.close(); };
> ```
> There's a problem here with how sockets are closed — they only close on error, which probably causes some sockets to leak and might break later uploads.

Why it's bad: the claim floats below the whole block (which line? "probably"/"might" = ungrounded), no `file:line` header, no marker, no anchored WHY. The reader cannot audit it.
</examples>

<output_format>
- A 1–3 sentence **Problem/Understanding** statement (prose).
- For each function on the path, in execution order:
  - a clickable `file:line` header,
  - the tight code quote,
  - one or more line-anchored `[REVIEW:*]` annotations, each with its WHY.
- (For a change) before/after pairs with `[REVIEW:fix]` / `[REVIEW:risk]`.
- A one-line **Ask** + STOP.
</output_format>

<success_criteria>
- Every behavioral claim is anchored to a specific `file:line` that was re-read in this pass — no floating bullets, no "probably/might".
- The walk follows execution order, entry point first.
- `[REVIEW:*]` markers appear ONLY in chat; the working tree is unchanged (no marker written into any source file).
- Prose is confined to problem statement, cross-process/timing/trade-off notes, and the ask.
- Ends with an explicit ask and a STOP — no change applied without approval.
</success_criteria>

<final_reminders>
P0 — Annotation markers are chat-display ONLY. Never write `[REVIEW:*]` into a source file; the tree stays clean.
P0 — Every claim cites a `file:line` re-read in this pass (global AGENTS.md `<evidence>`). No claim without a fresh read.
P0 — STOP after the ask. Do not apply changes until the user approves.
P1 — Code-led, not prose-led: a detached analysis paragraph under a pasted body is INVALID. Anchor each claim to its line.
P1 — Walk in execution order, not file/alphabetical order.
P2 — One marker per concern; keep quotes tight; cut any sentence the annotations already carry.
</final_reminders>
