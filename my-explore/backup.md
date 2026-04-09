<!--

## Declaration gate — write this sentence before any tool call

> Task type: **[Pinpoint | Trace | Discovery | Structural]**. Reason: [one sentence]. First action: **[tool name]** on **[concrete target]**.

Write a new declaration when the task type shifts mid-investigation.

## Classify — BEFORE any tool call

Classify the task and read the matching file before any search or extract call:

| Type           | Signal                                           | File to Read    |
| -------------- | ------------------------------------------------ | --------------- |
| **Pinpoint**   | Component/function name or UI label known        | `pinpoint.md`   |
| **Trace**      | How data/control flows across files              | `trace.md`      |
| **Discovery**  | No specific symbol known, only abstract concepts | `discovery.md`  |
| **Structural** | Find all code matching an AST pattern            | `structural.md` |

Follow the file's steps exactly. After each tool call: answer found? → stop.

## Capability tips — features the hook translation can't teach

- **`mcp__probe__extract_code` with `lsp: true`** — returns call hierarchy plus references in one call. Skip separate caller lookup only when this already answers the question.
- **`mcp__probe__extract_code` with batched `files` array** — multiple files in one call. Prefer over per-file loops.
- **`mcp__probe__search_code`** — semantic bootstrap from concept to symbol.
- **`mcp__ast_grep__find_code`** — structural search, no false positives from comments or strings.
- **`mcp__ast_grep__find_code_by_rule`** — `inside` / `has` / `follows` filters for complex patterns.
- **Never `rg` for callers** — use `mcp__language_server__get_symbol_references`.
-->
