# Pinpoint — component/function name or UI label known

## Rules

- After each step, check: does the extracted code answer the question? If yes → stop.
- NEVER read entire files. Extract only the symbol or line range you need.

## Steps

### Step 1 — Find the location

Use `rg` scoped to the likely directory:

```
exec_command: rg -n --fixed-strings -- 'ComponentName' 'src/components/'
```

If `rg` returns 0 results, widen the pattern:

```
exec_command: rg -n -e 'handle.*Class' 'src/'
```

If `rg` still returns 0, fall back to ast-grep structural search:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "ComponentName",
  "language": "tsx"
})
```

If still 0 → try with `"typescript"` language. If both return 0 → stop. Report "symbol not found" to the user.

### Step 2 — Extract the code

Take the best `file:line` from step 1. Call:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": ["/absolute/path/to/file.tsx#SymbolName"],
  "format": "markdown",
  "timeout": 30
})
```

If `#symbol` returns only a single line, retry with `file:line`:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": ["/absolute/path/to/file.tsx:42"],
  "format": "markdown",
  "timeout": 30
})
```

Answer the question if the code is sufficient. Otherwise continue to step 3.

### Step 3 — Follow delegations (only if needed)

If the extracted code delegates to another function/component and you need its implementation:

**Option A — LSP available:**

```
mcp__language_server__get_symbol_definitions({
  "file_path": "/absolute/path/to/file.tsx",
  "line": 41,
  "character": 10
})
```

(LSP positions are zero-based. If the tool that found the call site showed line 42, pass `line: 41`.)

Then extract the definition with `mcp__probe__extract_code`.

**Option B — LSP unavailable:**

Find the delegation target with `rg`:

```
exec_command: rg -n --fixed-strings -- 'delegatedFunction' 'src/'
```

Then extract with `mcp__probe__extract_code`.
