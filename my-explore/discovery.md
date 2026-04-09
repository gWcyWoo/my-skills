# Discovery — no specific symbol known

## Steps

1. **Search by domain concept** — use **`mcp__probe__search_code`** scoped to the likely directory.
2. **Scan structure** (when you have files but not specific symbols yet) — use **`mcp__ast_grep__find_code`** with patterns like `interface $NAME { $$$ }`, `type $NAME = $$$`, or `export function $NAME` to list what a file or directory contains. Then **`mcp__probe__extract_code`** the symbols you need. If dependency analysis matters, inspect the imports visible in those extracts; Codex does not expose Claude's `analyze-imports` step here.
3. **Narrow down** — once you have a concrete file or function, switch to Pinpoint or Trace.
4. If `mcp__probe__search_code` is unavailable, fall back to `rg -n` with keyword patterns.
