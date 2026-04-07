<!--

## Declaration gate — write this sentence before any tool call

> Task type: **[Pinpoint | Trace | Discovery | Structural]**. Reason: [one sentence]. First action: **[tool name]** on **[concrete target]**.

Write a new declaration when the task type shifts mid-investigation.

## Classify — BEFORE any tool call

Classify the task and read the matching file before any search/read/extract call:

| Type           | Signal                                           | File to Read    |
| -------------- | ------------------------------------------------ | --------------- |
| **Pinpoint**   | Component/function name or UI label known        | `pinpoint.md`   |
| **Trace**      | How data/control flows across files              | `trace.md`      |
| **Discovery**  | No specific symbol known, only abstract concepts | `discovery.md`  |
| **Structural** | Find all code matching an AST pattern            | `structural.md` |

Follow the file's steps exactly. After each tool call: answer found? → stop.

## Capability tips — features the hook translation can't teach

- **`probe extract_code` with `lsp: true`** — returns call hierarchy + references in one call. Skip separate LSP calls.
- **`probe extract_code` with batched `files` array** — multiple files in one call. Always prefer over per-file loops.
- **`probe search_code` with `exact: true`** — precise symbol name lookup, no stemming.
- **`ast-grep find_code`** — structural search, no false positives from comments/strings (unlike Grep+regex).
- **`ast-grep find_code_by_rule`** — `inside` / `has` / `follows` filters for complex patterns.
- **`ast-grep analyze-imports`** — `mode: "usage"` for refactoring, `mode: "discovery"` for exploration.
- **NEVER Grep for callee/callback names** — `extract_code` with `lsp: true` already returns their positions. -->
