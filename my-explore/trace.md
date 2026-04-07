# Trace — how data/control flows across files

## Steps

1. **Find the entry point** — **Probe search_code** (concept) or **LSP workspaceSymbol** (name known).
2. **Extract entry with `lsp: true`** — **only at the entry hop**. This gives body + callees + callers in one shot.
3. **Identify callees** from step 2's call hierarchy, skip built-in/framework calls.
4. **Trace callees with plain `extract_code`** (batched `files` array, NOT `lsp: true`). Only re-open `lsp: true` at a hop where you need its callees too.
5. **Find callers** — use **LSP findReferences**, never Grep.
6. If `#symbol` returns only a single line, retry with `file:line` format.
7. **Summarize** the full flow.

**Cost rule:** `lsp: true` payloads can be 10–15k tokens each. Use it at most 2–3 times in one Trace task. Plain `extract_code` is the default for all other hops.
