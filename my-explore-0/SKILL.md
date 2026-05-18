---
name: my-explore-0
description: Tool selection palette for code exploration. A reference manual readable by either (a) the main session when running lightweight exploration directly, or (b) the `my-explore` subagent at boot when delegated heavier exploration. Maps each retrieval intent to the one correct tool call. The CALLER decides which path (main session vs subagent) — this file only specifies which tool fits which intent.
---

<NEVER>

- NEVER call `search_code` | `Grep` more than once per request. Got a symbol name? Switch to `extract_code` / `findReferences`.
- NEVER pass regex syntax (`|`, `\(`, `\b`) to `search_code` — it is a concept search engine, not grep. Use `Grep` for regex.

</NEVER>

<tool_selection>

| Known context                                | Tool                                                                                        | Key args                             |
| -------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------ |
| file + symbol name                           | extract_code                                                                                | files=["file#symbol"]                |
| file + multiple symbols                      | extract_code                                                                                | files=["f#a","f#b","g#c"]            |
| **file path, NO symbol name yet** (discover) | **LSP documentSymbol** to list all symbols in the file → THEN extract_code with `#symbol`   | operation=documentSymbol, filePath=`...`, line=1, character=1 |
| file path + need a specific structural shape | ast-grep find_code (only when LSP documentSymbol doesn't cover what you want)               | pattern=`export class $X`, `eventBus.on($_, $$$)`, etc. |
| file:line:col known, find callers            | LSP findReferences                                                                          | operation, filePath, line, character |
| only have symbol name, want callers          | seed first (LSP documentSymbol / ast-grep / extract_code → file:line:col), then LSP findReferences | two-step                             |
| file path pattern                            | Glob                                                                                        | pattern                              |
| exact string or regex                        | Grep                                                                                        | pattern, path                        |
| AST structural pattern (cross-file)          | ast-grep find_code                                                                          | pattern                              |
| nested AST (class X containing method Y)     | ast-grep find_code_by_rule                                                                  | inside/has/follows                   |
| no file, no symbol (≤1 call)                 | search_code                                                                                 | query (2-3 keywords), path           |

Priority: `extract_code > findReferences > LSP documentSymbol > ast-grep > Grep > search_code`

**Why `LSP documentSymbol` beats `ast-grep` for discovery:**
- One call returns ALL symbols in a file (class, method, interface, const, type) with `name + kind + range` — no need to write 4 separate ast-grep patterns.
- Returns **metadata only** (names + line ranges), NOT bodies. ast-grep `pattern="export class $X { $$$ }"` returns the full class body for each match, often 1-5k tokens per call. documentSymbol returns ~300 tokens of compact symbol metadata regardless of body size.
- Includes nested symbols (methods inside classes), which `export class $X` patterns miss.
- Cross-language: works for TS/JS/Python/Go/Rust without rewriting patterns.

**Use `ast-grep find_code` instead of documentSymbol only when:**
- The shape you want is NOT a named declaration (e.g., `eventBus.on($_, $$$)` to find event handlers at any call site).
- You need cross-file structural matching (documentSymbol is one-file-at-a-time).

**Never use `extract_code` with `path:1-N` (wide line range) as a substitute for symbol discovery.** If you have a path but not the symbol name, the correct flow is:
1. `LSP(operation="documentSymbol", filePath="...", line=1, character=1)` — returns symbol list with line ranges. `line`/`character` are schema-required even though documentSymbol ignores them; passing `1, 1` is the convention. Omitting them = `InputValidationError`.
2. `extract_code(files=["path#FoundName1", "path#FoundName2", ...])` — batched, with real symbol names.

Wide line ranges like `:1-200`, `:1-300` are gaming the anchor rule — they bypass the spirit of precision exploration and dump whole-file content. Use them only when you legitimately know the target lines (e.g. `:42-58` for a known region).

</tool_selection>
