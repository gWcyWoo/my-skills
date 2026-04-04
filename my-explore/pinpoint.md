# Pinpoint — component/function name or UI label known

## Steps

1. **Find the location** — Grep the known text scoped to the likely directory.
2. **Extract the code** — **Probe extract_code** with `file#symbol` or `file:line`.
3. **Follow delegations** — LSP goToDefinition at the call site.
4. If Grep returns 0, widen the pattern (e.g. `handle.*Class`) or use search_code.
