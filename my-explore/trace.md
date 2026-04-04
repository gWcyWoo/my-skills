# Trace — how data/control flows across files

## Rules

- After each step, check: does the extracted code answer the question? If yes → skip to step 6.
- NEVER search for a function name, variable name, or code line that already appeared in a previous extract_code result. You already have that information — re-read the output instead of making a new tool call.
- `rg` is allowed when you see a callee name in extracted code but do NOT know which file defines it. `rg` is NOT allowed to re-search code you already extracted.
- Total tool calls for a typical trace: 3–6. If you are past 10, you are off track — stop and summarize what you have.

## Steps

### Step 1 — Find the entry point

If you know the exact text (component name, function name):

```
exec_command: rg -n --fixed-strings -- 'CreateClassDialog' 'src/'
```

If `rg` returns 0 results, fall back:

```
mcp__probe__search_code({
  "path": "/absolute/project/root",
  "query": "CreateClassDialog",
  "exact": false
})
```

If `mcp__probe__search_code` also returns 0 results, try `exact: true` with quoted query:

```
mcp__probe__search_code({
  "path": "/absolute/project/root",
  "query": "\"CreateClassDialog\"",
  "exact": true,
  "strictElasticSyntax": true
})
```

If all three return 0 → stop. Report "entry point not found" to the user.

### Step 2 — Extract entry point with call hierarchy

Take the `file:line` or `file#symbol` from step 1. Call:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": ["/absolute/path/to/file.tsx#SymbolName"],
  "format": "markdown",
  "lsp": true,
  "timeout": 30
})
```

This returns:
- The full function/class body
- (If LSP is available) call hierarchy: callee locations, caller locations

**If `lsp: true` fails or returns no hierarchy data**, that is OK. Go to step 3A instead of step 3B.

### Step 3A — LSP unavailable: identify callees manually from extracted code

Read the code body returned in step 2. Identify callee names by looking for these patterns:

| Pattern in extracted code | How to find the file | Example |
|---|---|---|
| `fetch('/api/some/path')` | Next.js convention: the handler is at `app/api/some/path/route.ts` | `fetch('/api/classrooms')` → `app/api/classrooms/route.ts` |
| `SomeClass.someMethod(...)` | You know the method name but NOT which file defines it. Use `rg` to find the definition. | `Classroom.createClassroom(...)` → `exec_command: rg -n --fixed-strings -- 'createClassroom' 'server/'` |
| `someFunction(...)` where the function is imported | Same — use `rg` to find the definition file. | `getUser()` → `exec_command: rg -n --fixed-strings -- 'export.*getUser' 'src/'` |
| `props.onSomething(...)` or callback passed from parent | Trace upstream — find the parent component that renders this component. Use `rg` to find `<ComponentName` or the prop assignment. | `onClassCreated(...)` → `exec_command: rg -n --fixed-strings -- 'onClassCreated=' 'src/'` |

For each callee, once `rg` gives you a `file:line`, you are done with that callee. Collect all `file:line` results and go DIRECTLY to step 4. Do NOT also call `mcp__probe__search_code` for the same symbol — `rg` already found it.

**When to use `rg` vs when NOT to:**
- ✅ You see `Classroom.createClassroom(...)` in extracted code and need to find which file defines `createClassroom` → use `rg`
- ❌ `rg` already returned `classroom.repo.ts:71` for `createClassroom` and you want to "double check" with `mcp__probe__search_code` → do NOT. Go to step 4.
- ❌ You already extracted `create-class-dialog.tsx#CreateClassDialog` and now want to search for `handleCreateClass` inside it → do NOT. You already have the code body.

### Step 3B — LSP available: identify callees from call hierarchy

From step 2's LSP output, collect callee `file:line` entries. Skip built-in/framework calls (React hooks, Next.js internals, console.*, etc.). Go to step 4.

### Step 4 — Batch extract all callees

Combine all targets into ONE call:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": [
    "/absolute/path/to/api/route.ts:92",
    "/absolute/path/to/repo/some.repo.ts#createSomething",
    "/absolute/path/to/hooks.ts#useMyHook"
  ],
  "format": "markdown",
  "timeout": 30
})
```

**Handling bad extract results:**
- If `#symbol` returns only a single line or the wrong node → retry with `file:line` using a line number from your earlier `rg` output.
- If `file:line` returns only a trivial line (e.g., `'use client'`, an import, a type declaration) → the line number was wrong. Use a line number closer to the actual function definition. Check your `rg` output for the correct line.
- NEVER use `:1` as a line number unless you specifically need line 1. Use the line number that `rg` or `search_code` gave you.

If any callee has its own downstream calls that matter to the trace, repeat step 3A/3B → step 4 for one more hop. **Maximum 3 hops total.** If the trace goes deeper, summarize and stop.

### Step 5 — Trace upstream callers (only if the question requires it)

If the question asks "who triggers this" or "where is this called from":

Use the entry point's caller locations from step 2's LSP output. Or if LSP was unavailable:

```
rg -n --fixed-strings -- 'functionName' 'src/'
```

Then extract the relevant callers with `mcp__probe__extract_code`.

### Step 6 — Summarize

Output the full trace as a chain:

```
Caller → EntryPoint → Callee1 → Callee2
  file:line    file:line    file:line    file:line
```

Describe what each node does in one sentence. Flag any issues found (missing data, error handling gaps, etc.).
