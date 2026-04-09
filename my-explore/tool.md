# Tool reference

## `mcp__probe__extract_code` — three modes, pick by intent

1. **`file#symbol` or `file:line`**
   - Returns: function or class body for that exact symbol or line anchor, usually about 30 lines
   - Use when: you know the symbol name, or you have `file:line` from another tool's output
   - **Not direct file reads** — direct reads return the whole file; this returns only what you need

2. **`lsp: true` flag**
   - Returns: code body plus call hierarchy (callees with `file:line`) plus references (callers with `file:line`) in one response
   - **Expensive** — payload can be 10–15k tokens for hot symbols
   - Use **only** when actively tracing a call chain
   - Default to plain `file#symbol` or `file:line`; open `lsp: true` only at the specific hop you are tracing
   - **Not separate call-hierarchy plus references calls** when this one response already answers both

3. **Batched `files` array**
   - Returns: multiple code locations in one response
   - Use when: you have several related files to inspect together
   - **Not a per-file loop**

---

- **`mcp__probe__search_code`** — semantic search by keyword. First choice when you do not know the exact path. Once a concrete symbol surfaces, stop searching and switch to `extract_code`.
- **`mcp__ast_grep__find_code`** — find code by AST pattern. Prefer over `rg` for code structure; no false positives from comments or strings.
- **`mcp__ast_grep__find_code_by_rule`** — same with `inside` / `has` / `follows` filters for relational patterns.
- **Language server** — `get_symbols` (symbols in a file), `get_project_symbols` (find symbol project-wide), `get_symbol_references` / `get_symbol_definitions` for navigation. Use `get_symbol_references` to find callers; never `rg` for that.
- **`rg -n`** — text search. Use for non-source files, comments, string literals, error messages, or a first scoped anchor. Not for code structure, and not for finding callers.
