# Pinpoint — component/function name or UI label known

## Steps

1. **Find the location** — use `rg -n` on the known text, scoped to the likely directory. If the symbol name is known exactly, `mcp__language_server__get_project_symbols` or `mcp__ast_grep__find_code` also works.
2. **Extract the code** — use **`mcp__probe__extract_code`** with `file#symbol` or `file:line`.
3. **Follow delegations** — use `mcp__language_server__get_symbol_definitions` at the call site.
4. If `rg -n` returns 0, widen the pattern (for example, `handle.*Class`) or use `mcp__probe__search_code`.
