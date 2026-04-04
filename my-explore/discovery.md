# Discovery — no specific symbol known

## Rules

- After each step, check: do you now have a concrete file or symbol? If yes → switch to Pinpoint or Trace.
- Maximum 3 search calls before you must narrow down. If still no results after 3, stop and report.

## Steps

### Step 1 — Search by domain concept

Use semantic search scoped to the likely directory:

```
mcp__probe__search_code({
  "path": "/absolute/project/root",
  "query": "user authentication login",
  "exact": false
})
```

Do NOT use `exact: true` for discovery — you do not have an exact symbol name yet.

If `mcp__probe__search_code` is unavailable, fall back to `rg`:

```
exec_command: rg -n -e 'auth.*login' 'src/'
```

### Step 2 — Narrow down

Once you have a concrete `file:line` or symbol name from step 1:

- If the question is "what is this / how does it work" → switch to **Pinpoint** (read `pinpoint.md`)
- If the question is "how does data flow through this" → switch to **Trace** (read `trace.md`)

Do NOT continue broad searching. Extract the code and work from there.

### Step 3 — Second attempt (only if step 1 returned 0 results)

Try alternative terms. For example if "authentication" returned nothing, try:

```
mcp__probe__search_code({
  "path": "/absolute/project/root",
  "query": "session token credential",
  "exact": false
})
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
