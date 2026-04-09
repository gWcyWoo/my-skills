# Discovery

The query contains only abstract concepts. No symbol, file, or UI label is named.

Examples: "where does the project handle rate limiting", "find all X that syncs to Y".

## Steps

1. **Bootstrap by concept.** — `probe search_code query="<domain keywords>" path="<scoped dir>" limit=5-10`.

2. **Scan structure.** — once files are found but the target symbol is unclear, use `ast-grep find_code` with patterns such as `interface $NAME { $$$ }`, `type $NAME = $$$`, or `export function $NAME`. Alternatively, `ast-grep analyze-imports mode="discovery"` reveals module dependencies.

3. **Switch playbooks.** — the moment a concrete file or symbol surfaces, stop searching and switch to Pinpoint or Trace at that location.

## Hard Limits

- `probe search_code`: at most two calls per query. It is a bootstrap, not a browser.
- **Never fall back to `Grep` on source files.** If `probe` is unavailable, use `LSP workspaceSymbol` (name hypothesis) or `ast-grep find_code` (shape hypothesis).

**Stop condition:** a concrete location has been found and its body has been extracted. Typical cost: 2–3 tool calls (1 search + 1–2 extracts).
