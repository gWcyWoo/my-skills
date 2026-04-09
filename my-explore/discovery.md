# Discovery

The query contains only abstract concepts. No symbol, file, or UI label is named.

Examples: "where does the project handle rate limiting", "find all X that syncs to Y".

## Steps

1. **Bootstrap by concept.** -> `mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`.

2. **Scan structure.** -> once files are found but the target symbol is unclear, use `mcp__ast_grep__find_code` with patterns such as `interface $NAME { $$$ }`, `type $NAME = $$$`, or `export function $NAME`.

3. **Switch playbooks.** -> the moment a concrete file or symbol surfaces, stop searching and switch to Pinpoint or Trace at that location.

## Hard Limits

- `mcp__probe__search_code`: at most two calls per query. It is a bootstrap, not a browser.
- **Never fall back to `rg` on source files.** If `mcp__probe__search_code` is unavailable, use `mcp__language_server__get_project_symbols` for a name hypothesis or `mcp__ast_grep__find_code` for a shape hypothesis.

**Stop condition:** a concrete location has been found and its body has been extracted. Typical cost: 2–3 tool calls, one search plus one or two extracts.
