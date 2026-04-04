# Trace — how data/control flows across files

## Steps

1. **Find the entry point** — **Probe search_code** or Grep for literal text.
2. **Extract with call hierarchy** — **Probe extract_code** with `lsp: true`.
3. **Identify callees** — from step 2's call hierarchy, skip built-in/framework calls.
4. **Trace callees** — batch all into one extract_code call, repeat from step 3 for deeper hops.
5. If `#symbol` returns only a single line, retry with `file:line` format.
6. **Summarize** the full flow.
