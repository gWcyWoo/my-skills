# Discovery — no specific symbol known

## Rules

- After each step, check: do you now have a concrete file or symbol? If yes → switch to Pinpoint or Trace.
- Maximum 3 search calls before you must narrow down. If still no results after 3, stop and report.

## Steps

### Step 1 — Search by domain concept

Use `rg` with broad keywords scoped to the likely directory:

```
exec_command: rg -n -e 'demo.*class' 'src/'
```

If `rg` returns too many or too few results, use ast-grep for structural search:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "isDemoMode",
  "language": "tsx"
})
```

If you need a fuzzy/semantic search (e.g., the concept could be named many ways), use `mcp__probe__search_code` as last resort:

```
mcp__probe__search_code({
  "path": "/absolute/project/root",
  "query": "demo class trial experience",
  "exact": false
})
```

### Step 2 — Narrow down

Once you have a concrete `file:line` or symbol name from step 1:

- If the question is "what is this / how does it work" → switch to **Pinpoint** (read `pinpoint.md`)
- If the question is "how does data flow through this" → switch to **Trace** (read `trace.md`)

Do NOT continue broad searching. Extract the code and work from there.

### Step 3 — Second attempt (only if step 1 returned 0 results)

Try alternative terms or a different tool:

```
exec_command: rg -n -i -e 'trial|sample|experience' 'src/'
```

Or use structural search if you know the code shape:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "async function $FUNC($$$) { $$$ }",
  "language": "typescript"
})
```

If still 0 results → stop. Report "no matching code found for this concept" to the user.
