# Structural — find all code matching an AST pattern

## Rules

- After each step, check: do you have enough matches to answer the question? If yes → stop.
- NEVER use `rg` regex to simulate structural search. Use `mcp__ast_grep__find_code` or `mcp__ast_grep__find_code_by_rule`.

## Steps

### Step 1 — Search by code structure

For a simple pattern (single AST node):

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "fetch('/api/$$$')",
  "language": "typescript"
})
```

For a relational pattern (node inside/having another node):

```
mcp__ast_grep__find_code_by_rule({
  "project_folder": "/absolute/project/root",
  "yaml": "id: find-fetch-in-async\nlanguage: typescript\nrule:\n  pattern: fetch($$$)\n  inside:\n    kind: function_declaration\n    stopBy: end"
})
```

If unsure about the AST structure, dump it first:

```
mcp__ast_grep__dump_syntax_tree({
  "code": "await fetch('/api/classrooms', { method: 'POST' })",
  "language": "typescript",
  "format": "cst"
})
```

### Step 2 — Narrow results (only if too many matches)

Add `inside`, `has`, or `follows` constraints to the YAML rule. For example, restrict to matches inside a specific function:

```
mcp__ast_grep__find_code_by_rule({
  "project_folder": "/absolute/project/root",
  "yaml": "id: narrowed\nlanguage: typescript\nrule:\n  pattern: fetch($$$)\n  inside:\n    pattern: async function handleCreateClass($$$) { $$$ }\n    stopBy: end"
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
