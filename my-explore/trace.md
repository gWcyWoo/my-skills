# Trace — how data/control flows across files

## Steps

1. **Find the entry point** — use **`mcp__probe__search_code`** for a concept query or **`mcp__language_server__get_project_symbols`** when the name is known.
2. **Extract entry with `lsp: true`** — **only at the entry hop**. This gives body plus callees plus callers in one shot.
3. **Identify callees** from step 2's call hierarchy. Skip built-in or framework calls.
4. **Trace callees with plain `extract_code`** — use a batched `files` array, not `lsp: true`. Re-open `lsp: true` only at a hop where you also need its callees.
5. **Find callers** — use **`mcp__language_server__get_symbol_references`**, never `rg`.
6. If `#symbol` returns only a single line, retry with `file:line`.
7. **Summarize** the full flow.

**Cost rule:** `lsp: true` payloads can be 10–15k tokens each. Use it at most 2–3 times in one Trace task. Plain `extract_code` is the default for all other hops.
