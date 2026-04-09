# Structural

Find all code matching an AST pattern.

Examples: "all `useEffect` calls with empty dependency arrays", "all functions returning `Promise<void>`".

## Steps

1. **Match the pattern.** -> `mcp__ast_grep__find_code pattern="<language pattern>"`. Use `$NAME` for one node and `$$$` for zero or more nodes.

2. **Narrow the results.** -> if the match set is too large, switch to `mcp__ast_grep__find_code_by_rule` with `inside`, `has`, or `follows` constraints.

3. **Debug a non-matching pattern.** -> run `mcp__ast_grep__dump_syntax_tree` on a known-good example to inspect the AST shape, then rewrite the pattern.

4. **Scan dependencies** when relevant -> batch `mcp__probe__extract_code` on the matched anchors and inspect imports or calls there.

**Stop condition:** every match has been enumerated with `file:line`. Typical cost: 1–2 tool calls.
