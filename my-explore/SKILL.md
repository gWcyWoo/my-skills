---
name: my-explore
description: MUST invoke for ALL code tasks — search, find, trace, explain, read, analyze. Loads MCP tool schemas and navigation rules.
---

# Code Navigation

Run these once to load tool schemas (skip any that return no results):

1. ToolSearch("ast-grep")
2. ToolSearch("probe")
3. ToolSearch("LSP")

## What each tool is for

**`probe extract_code`** — three modes, pick by intent:

1. **`file#symbol` or `file:line`**
   - Returns: function/class body of that exact symbol or line range (~30 lines)
   - Use when: you know the symbol name, OR you have file:line from another tool's output
   - **NOT Read** — Read returns the whole file (200+ lines); this returns only what you need

2. **`lsp: true` flag**
   - Returns: code body + call hierarchy (callees with file:line) + references (callers with file:line), all in one response
   - Use when: tracing data flow upstream/downstream, finding all callers/callees, building cross-file mental models
   - **NOT separate LSP `prepareCallHierarchy` / `findReferences`** — `lsp: true` already includes both
   - **NOT Grep for callee/callback names** — `lsp: true` already returns their positions

3. **batched `files` array**
   - Returns: multiple files in one response
   - Use when: you have N related files to inspect together (e.g., container + child components + types)
   - **NOT a per-file loop** — wastes tool calls and dilutes attention with separate responses

---

- **`probe search_code`** — semantic search by keyword. **First choice when you don't know the exact path** — use this before Glob, to avoid guessing loops. Use `exact: true` for precise symbol lookup.
- **`ast-grep find_code`** — find code by AST pattern (function calls, declarations, JSX, object literals, generics). **Always use over Grep for code structure** — no false positives from comments/strings.
- **`ast-grep find_code_by_rule`** — same with `inside` / `has` / `follows` filters for complex relational patterns.
- **`ast-grep analyze-imports`** — import dependency map. `mode: "usage"` for refactoring, `mode: "discovery"` for exploration.
- **LSP** — `documentSymbol` (symbols in a file), `workspaceSymbol` (find symbol project-wide), `findReferences` / `goToDefinition` for navigation.
- **Grep** — text search. Use for: non-source files (md/json/yaml/configs/logs), comments, string literals, error messages. **NOT for code structure** — use ast-grep instead.
- **Glob** — find files by name/path pattern. Replaces `ls` / `find`.
