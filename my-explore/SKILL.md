---
name: my-explore
description: MUST invoke for ALL code tasks — search, find, trace, explain, read, analyze. Classifies the question, then loads the matching per-type playbook on demand.
---

## Step 0: Load tool schemas (once per session)

Run these once, skip any that return no results:

1. `ToolSearch("ast-grep")`
2. `ToolSearch("probe")`
3. `ToolSearch("LSP")`

---

## Step 1: Classify and load the matching playbook

Pick **one** type from the table, output `[Type: X] reason: ...`, then **Read exactly one** playbook file and follow its steps.

| Type | Signal | Example | Playbook |
|------|--------|---------|----------|
| **Pinpoint** | Question identifies ANY of: symbol name, file name, UI label/button text, area + element combo | "What does `handleSubmit` do?" / "What's the View Details button in classroom?" | `~/.claude/skills/my-explore/pinpoint.md` |
| **Trace** | Question asks how data or control flows across files | "How does login data reach the dashboard?" / "Who calls `createInvoice`?" | `~/.claude/skills/my-explore/trace.md` |
| **Discovery** | No symbol, file, or UI element identifiable — only abstract domain concepts | "Does this project have rate limiting?" / "Where's the permission system?" | `~/.claude/skills/my-explore/discovery.md` |
| **Structural** | Question asks for all code matching a syntactic pattern | "Find all API route handlers" / "All `useEffect` with empty deps" | `~/.claude/skills/my-explore/structural.md` |

**Tie-breaker:** if Pinpoint is even partially possible, choose Pinpoint. Discovery is the last resort.

**Load exactly one playbook.** If mid-task the type genuinely changes (e.g. Discovery turns up a concrete symbol → switch to Pinpoint), load the new playbook and continue.

---

## Step 2: Stop check

After every tool call, ask: **does the result answer the question?**
- **Yes** → stop. Report.
- **No** → identify the specific gap, then pick exactly one next tool from the playbook. Do not parallel-fire "just in case."

Parallel calls are allowed **only** when answering **independent** sub-questions.

---

## Tool quick reference (details live in playbooks)

- **`probe extract_code`** — read source by `file#symbol` / `file:line` / batched `files`. Use `lsp:true` to also return call hierarchy + references in one shot. **Replaces Read for source code.**
- **`probe search_code`** — semantic keyword search. **Discovery only.** Always set `path`.
- **`ast-grep find_code` / `find_code_by_rule`** — AST pattern match. Always preferred over Grep for code structure.
- **`ast-grep analyze-imports`** — import dependency map.
- **LSP** — `documentSymbol`, `workspaceSymbol`, `goToDefinition`, `goToImplementation`, `findReferences`, `hover`.
- **Grep** — text search for non-source files (md/json/yaml/configs/logs), comments, string literals. **Always pass `path` or `glob`.**
- **Glob** — find files by name/path pattern. Replaces `ls` / `find`.

**Priority when multiple tools could answer:** LSP (position known) > ast-grep (code shape known) > Grep (literal text) > probe search_code (concept only).
