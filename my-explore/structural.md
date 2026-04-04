# Structural — find all code matching an AST pattern

## Rules

- After each step, check: do you have enough matches to answer the question? If yes → stop.
- NEVER use `rg` regex to simulate structural search. Use `mcp__ast_grep__find_code` or `mcp__ast_grep__find_code_by_rule`.
- For `.tsx` files, use `language: "tsx"`. For `.ts` files, use `language: "typescript"`. If unsure, run the search twice with both languages.

## Steps

### Step 0 — ALWAYS test your rule before searching the project

**DO NOT run `find_code_by_rule` on the whole project until you have verified the rule matches on a known code sample.**

Take a small code snippet you expect to match, and test it:

```
mcp__ast_grep__test_match_code_rule({
  "code": "if (isDemoMode) {\n  toast({ title: 'Demo' });\n  return;\n}",
  "yaml": "id: test\nlanguage: tsx\nrule:\n  kind: if_statement\n  has:\n    pattern: isDemoMode\n    stopBy: end"
})
```

If the test returns 0 matches → your rule is wrong. Fix it before searching the project.
If the test returns a match → proceed to step 1.

### Step 1 — Search by code structure

**Simple pattern** — when you know the exact code shape (single AST node):

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "fetch('/api/$$$')",
  "language": "tsx"
})
```

**Relational pattern** — when you need "X inside Y" or "X containing Y":

```
mcp__ast_grep__find_code_by_rule({
  "project_folder": "/absolute/project/root",
  "yaml": "id: my-rule\nlanguage: tsx\nrule:\n  kind: if_statement\n  has:\n    pattern: isDemoMode\n    stopBy: end"
})
```

**Critical: `stopBy: end`** — without `stopBy: end`, `has` and `inside` only check DIRECT children. To search the entire subtree, you MUST add `stopBy: end`. This is the most common mistake.

### Common YAML rule patterns

**Find if-statements containing a specific expression:**
```yaml
id: if-contains-expr
language: tsx
rule:
  kind: if_statement
  has:
    pattern: isDemoMode
    stopBy: end
```

**Find if-statements containing BOTH a specific check AND a return:**
```yaml
id: guard-clause
language: tsx
rule:
  kind: if_statement
  all:
    - has:
        pattern: isDemoMode
        stopBy: end
    - has:
        kind: return_statement
        stopBy: end
```

**Find function calls inside a specific block:**
```yaml
id: toast-in-if
language: tsx
rule:
  pattern: toast($$$)
  inside:
    kind: if_statement
    has:
      pattern: isDemoMode
      stopBy: end
    stopBy: end
```

**Find a pattern NOT inside a specific context:**
```yaml
id: fetch-outside-try
language: tsx
rule:
  pattern: fetch($$$)
  not:
    inside:
      kind: try_statement
      stopBy: end
```

### If ast-grep rules return 0 matches after testing

1. Use `dump_syntax_tree` to inspect the actual AST of a known matching code sample:

```
mcp__ast_grep__dump_syntax_tree({
  "code": "if (isDemoMode) { toast({}); return; }",
  "language": "tsx",
  "format": "cst"
})
```

2. Check: is the `kind` name correct? (e.g., `if_statement` vs `if_expression` depends on language)
3. Check: is `stopBy: end` present on every `has` and `inside`?
4. If you still can't get the rule right after 2 attempts, fall back: use `find_code` with a simple pattern to get all occurrences, then `mcp__probe__extract_code` to verify each match manually.

### Step 2 — Narrow results (only if too many matches)

Add `inside`, `has`, or `follows` constraints to the YAML rule. For example, restrict to matches inside a specific function:

```
mcp__ast_grep__find_code_by_rule({
  "project_folder": "/absolute/project/root",
  "yaml": "id: narrowed\nlanguage: tsx\nrule:\n  pattern: fetch($$$)\n  inside:\n    pattern: async function handleCreateClass($$$) { $$$ }\n    stopBy: end"
})
```

### Step 3 — Extract and analyze matched code

Take the `file:line` results from step 1 or 2 and batch extract:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": [
    "/absolute/path/to/file1.tsx:42",
    "/absolute/path/to/file2.ts:88"
  ],
  "format": "markdown",
  "timeout": 30
})
```

### Step 4 — Analyze dependencies (only if the question requires it)

If you need to know import/dependency relationships:

```
mcp__ast_grep__analyze-imports({
  "path": "src/components/",
  "mode": "usage"
})
```

Use `mode: "usage"` to find where imports are actually used (good for refactoring).
Use `mode: "discovery"` to explore all imports (good for understanding structure).
