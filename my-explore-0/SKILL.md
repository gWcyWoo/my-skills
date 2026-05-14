---
name: my-explore-0
description: Tool selection palette for code exploration. Consumed by the `my-explore` subagent at boot. Do NOT invoke this skill directly — all callers should dispatch the `my-explore` subagent via `Agent(subagent_type="my-explore", ...)`, which reads this file as its tool-palette reference.
---

<NEVER>

- NEVER call `search_code` | `Grep` more than once per request. Got a symbol name? Switch to `extract_code` / `findReferences`.
- NEVER pass regex syntax (`|`, `\(`, `\b`) to `search_code` — it is a concept search engine, not grep. Use `Grep` for regex.

</NEVER>

<tool_selection>

| Known context                       | Tool                                                                                        | Key args                             |
| ----------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------ |
| file + symbol name                  | extract_code                                                                                | files=["file#symbol"]                |
| file + multiple symbols             | extract_code                                                                                | files=["f#a","f#b","g#c"]            |
| file:line:col known, find callers   | LSP findReferences                                                                          | operation, filePath, line, character |
| only have symbol name, want callers | seed first (search_code / ast-grep / extract_code → file:line:col), then LSP findReferences | two-step                             |
| file path pattern                   | Glob                                                                                        | pattern                              |
| exact string or regex               | Grep                                                                                        | pattern, path                        |
| AST structural pattern              | ast-grep find_code                                                                          | pattern                              |
| no file, no symbol (≤1 call)        | search_code                                                                                 | query (2-3 keywords), path           |

Priority: `extract_code > findReferences > ast-grep > Grep > search_code`

</tool_selection>
