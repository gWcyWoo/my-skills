# Structural — find all code matching a pattern

## Steps

1. **Search by code structure** — use `mcp__ast_grep__find_code` or `mcp__ast_grep__find_code_by_rule`.
2. **Narrow results** — add `inside` / `has` constraints if too many matches.
3. **Analyze dependencies** — if dependency analysis is required, batch `mcp__probe__extract_code` on the matched `file:line` results and inspect the imports or calls there. Codex does not expose Claude's `analyze-imports` step in this skill.
