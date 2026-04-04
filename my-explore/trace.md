# Trace — how data/control flows across files

## Rules

- After each step, check: does the extracted code answer the question? If yes → skip to step 7.
- NEVER search for a function name, variable name, or code line that already appeared in a previous extract_code result. You already have that information — re-read the output instead of making a new tool call.
- `rg` is allowed when you see a callee name in extracted code but do NOT know which file defines it. `rg` is NOT allowed to re-search code you already extracted.
- Total tool calls for a typical trace: 4–6. If you are past 10, you are off track — stop and summarize what you have.

## Steps

### Step 1 — Find the entry point

If you know the exact text (component name, function name):

```
exec_command: rg -n --fixed-strings -- 'CreateClassDialog' 'src/'
```

If `rg` returns 0 results, fall back to ast-grep structural search:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "function CreateClassDialog($$$) { $$$ }",
  "language": "tsx"
})
```

If the function might be an arrow or export, try variations:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "CreateClassDialog",
  "language": "tsx"
})
```

If both return 0 → stop. Report "entry point not found" to the user.

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

**If `lsp: true` fails or returns no hierarchy data**, that is OK. Go to step 3 instead of using LSP data.

### Step 3 — STOP. Plan ALL files BEFORE making any more tool calls.

**DO NOT skip this step. DO NOT call any tool (rg, extract_code, search_code) until you have written out the full file plan below.**

You have the entry point code from step 2. Read it now. Find EVERY external call (fetch, imported function, class method, callback prop). For each one, decide whether you already know the file path or need `rg`. Write out TWO buckets:

**Split every callee into two buckets:**

**Bucket A — path known (no tool call needed):**

| Pattern in extracted code | How to derive the file path |
|---|---|
| `fetch('/api/some/path')` or `fetch('/api/some/path', ...)` | Next.js convention: `app/api/some/path/route.ts` |
| `fetch('/api/some/path/' + variable)` | Same: `app/api/some/path/route.ts` (dynamic segments are `[param]/route.ts`) |
| `import { foo } from './bar'` or `import { foo } from '../bar'` | Resolve the relative path from the current file's directory |
| `import { foo } from '@/lib/bar'` | `@/` = project root, so `lib/bar.ts` |

**Bucket B — path unknown (needs ONE round of `rg`):**

| Pattern in extracted code | What to `rg` for |
|---|---|
| `SomeClass.someMethod(...)` where `SomeClass` is imported but the file is not obvious | `rg -n --fixed-strings -- 'someMethod' 'server/'` |
| `someFunction(...)` where the import path is not in the extracted code | `rg -n --fixed-strings -- 'export.*someFunction' 'src/'` |
| `props.onCallback(...)` — need to find the parent that passes this prop | `rg -n --fixed-strings -- '<ComponentName' 'app/'` |

**You MUST write out a one-line plan summary before calling any tool. If you skip this and jump to rg or extract_code, you are violating this skill.**

Format:

```
=== PLAN: [N] files known, [M] needs rg ===
```

Example:

```
=== PLAN: 3 files known (classrooms/route.ts, students/route.ts, create-class.tsx), 2 needs rg (createClassroom, bulkCreateStudents) ===
```

**Only after writing this line, proceed to step 4.**

### Step 4 — Resolve Bucket B with rg (ONE round)

Issue ALL `rg` calls for Bucket B at once. After all return, you now have `file:line` for every callee.

Once `rg` gives you a `file:line`, you are done with that callee. Do NOT also call `mcp__ast_grep__find_code` or `mcp__probe__search_code` for the same symbol.

If `rg` finds call sites but NOT the definition, use `mcp__ast_grep__find_code` to locate the definition:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "createClassroom: async ($$$) => { $$$ }",
  "language": "typescript"
})
```

Or for a simpler match:

```
mcp__ast_grep__find_code({
  "project_folder": "/absolute/project/root",
  "pattern": "createClassroom: async ($$$) => $$$",
  "language": "typescript"
})
```

### Step 5 — Batch extract ALL files (ONE call)

Combine Bucket A paths + Bucket B `rg` results into ONE extract_code call:

```
mcp__probe__extract_code({
  "path": "/absolute/project/root",
  "files": [
    "/absolute/path/to/app/api/classrooms/join/route.ts#POST",
    "/absolute/path/to/app/api/auth/basic/signup/student/route.ts#POST",
    "/absolute/path/to/app/api/auth/student/login/route.ts#POST",
    "/absolute/path/to/server/repos/classroom/classroom.repo.ts:142",
    "/absolute/path/to/server/repos/student/student-enrollment.repo.ts:53"
  ],
  "format": "markdown",
  "timeout": 30
})
```

**Handling bad extract results:**
- If `#symbol` returns only a single line or the wrong node → retry with `file:line` using a line number from your earlier `rg` output.
- If `file:line` returns only a trivial line (e.g., `'use client'`, an import, a type declaration) → the line number was wrong. Use a line number closer to the actual function definition. Check your `rg` output for the correct line.
- NEVER use `:1` as a line number unless you specifically need line 1. Use the line number that `rg` or `find_code` gave you.

### Step 6 — One more hop (only if needed)

If the extracted callees have their OWN downstream calls that matter to the trace, repeat steps 3–5 for those. **Maximum 2 rounds total** (entry → first layer → second layer). If the trace goes deeper, summarize and stop.

### Step 7 — Trace upstream callers (only if the question requires it)

If the question asks "who triggers this" or "where is this called from":

Use the entry point's caller locations from step 2's LSP output. Or if LSP was unavailable:

```
rg -n --fixed-strings -- 'functionName' 'src/'
```

Then extract the relevant callers with `mcp__probe__extract_code`.

### Step 8 — Summarize

Output the full trace as a chain:

```
Caller → EntryPoint → Callee1 → Callee2
  file:line    file:line    file:line    file:line
```

Describe what each node does in one sentence. Flag any issues found (missing data, error handling gaps, etc.).
