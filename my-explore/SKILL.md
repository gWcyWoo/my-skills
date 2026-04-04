---
name: my-explore
description: MUST invoke for ALL code tasks — search, find, trace, explain, read, analyze. Loads MCP tool schemas and navigation rules.
---

# Code Navigation

You MUST execute these ToolSearch calls before any exploration. Do NOT skip:

1. ToolSearch("ast-grep")
2. ToolSearch("probe")
3. ToolSearch("LSP")

If a ToolSearch returns no results, that tool is unavailable — skip it.

## Classify FIRST — BEFORE any tool call

You MUST classify and Read the corresponding file BEFORE making any search/read/extract call:

| Type | Signal | File to Read |
|------|--------|-------------|
| **Pinpoint** | Component/function name or UI label known | `pinpoint.md` |
| **Trace** | How data/control flows across files | `trace.md` |
| **Discovery** | No specific symbol known, only abstract concepts | `discovery.md` |
| **Structural** | Find all code matching an AST pattern | `structural.md` |

Read the file, then follow its steps and tool rules exactly. After each tool call: answer found? → stop.

## Tool preference (fallback when classification files are not loaded)

Grep is ONLY for initial text lookup. Once you have file:line, use these:

| After you have file:line, use | **NEVER** | Returns → use for |
|------|-----|------|
| **Probe extract_code** (`file#symbol` or `file:line`) | Read entire file | complete function/class body → read the code to answer the question or decide what to trace next |
| **Probe extract_code** with `lsp: true` | Read + separate LSP calls | code body + call hierarchy + references → call hierarchy contains callee file:line (extract_code them directly, NO Grep), references contain caller file:line (trace callbacks/props upstream) |
| **Probe search_code** | Grep when name is unknown | file:line candidates ranked by relevance → extract_code the top match to confirm it's the right code |
| **Probe search_code** with `exact: true` | Grep for exact symbol name | file:line of exact symbol → extract_code to read the implementation |
| **ast-grep find_code** | Grep with regex | file:line of each structural match → extract_code to read, no false positives from comments/strings |
| **ast-grep find_code_by_rule** | find_code for complex patterns | file:line of matches filtered by `inside`/`has`/`follows` → extract_code to read |
| **ast-grep analyze-imports** | manual import tracing | import usage map → identify which modules depend on what, find unused imports (`mode: "usage"`) or explore all imports (`mode: "discovery"`) |
| Batch multiple files in one `files` array | One extract_code per file | combine multiple file:line into one call to reduce total tool calls |

**NEVER Grep for callee/callback names** — extract_code with `lsp: true` already returns their positions.
