# Code Navigation Methodology

How to extract maximum understanding from code navigation results and minimize unnecessary tool calls.

## Processing Code Navigation Results

After any CodeGraph or LSP call, process the results before making the next tool call:

### Step A: Extract What You Already Have

From the returned results (code snippets, symbol info, relationship data, reference sites), extract and list:

1. **Symbols & relationships** — which functions/modules exist, who calls whom
2. **Interface shapes** — parameter types, return types, property names visible in the results
3. **Data flow direction** — what data goes in, what comes out, what gets transformed, what events are emitted

### Step B: Identify Gaps (be specific)

For each piece of information your task needs, ask: **do I already have it from Step A?**

- "I need the User schema fields" → Check: did the results show the schema? If it showed `name, email` but your task mentions `role`, that's a specific gap: "field `role` — not visible in results"
- "I need to understand the upload flow" → Check: did the results show `eventBus.emit('FILE_UPLOADED')`? Then you already know the event name and trigger — that's not a gap. But if you need to know who handles that event, that's a specific gap: "handler for FILE_UPLOADED not visible in results"

**A gap is NOT:** "I want to see the full file to be sure." That's uncertainty, not a gap.
**A gap IS:** "The results show `processFile(buffer)` is called but I can't see what it returns — I need the return type."

### Step C: Fill Each Gap — Decision at the Symbol

When you have a symbol and need more information, your next action depends on **what you want to know** and **what kind of symbol it is**.

#### Rule 1: "Who uses/consumes/handles this?" → `LSP findReferences`

**Do NOT guess the consumer's name and search for it.** Use `findReferences` on the symbol you already have.

**When you MUST use findReferences:** If you see any of these in codegraph results and need to answer the corresponding question, use `findReferences` **first** — before any `codegraph_search`:

| You see in results... | You need to know... | Action |
|---|---|---|
| An event constant (`EVENT_NAME`) | Who listens/handles this event? | `findReferences(EVENT_NAME)` |
| An exported function or service method | Who calls this? | `findReferences(functionName)` |
| An interface definition | Who implements this? | `findReferences(InterfaceName)` |
| A type used as a parameter/return | Where is this type consumed? | `findReferences(TypeName)` |

**The anti-pattern to avoid:** seeing `UPLOAD_EVENT` in results, then thinking "the handler is probably called UploadEventHandler" and doing `codegraph_search("UploadEventHandler")`. This is **guessing a name** instead of **following references**. `findReferences(UPLOAD_EVENT)` discovers the actual handlers directly.

**How to call findReferences:** CodeGraph results (`codegraph_context`, `codegraph_node`, `codegraph_search`) include each symbol's `filePath` and `line`. Use these directly as LSP parameters:

```
codegraph_context returned:
  FILE_UPLOADED_EVENT — filePath: "src/events/constants.ts", line: 5

→ LSP findReferences(filePath: "src/events/constants.ts", line: 5, character: 14)
← returns ALL files that reference FILE_UPLOADED_EVENT
```

For `character`, use the column where the symbol name starts on that line (e.g., `export const FILE_UPLOADED_EVENT` → character 14).

**Trust the results:** `findReferences` returns the complete list of reference sites from the language server. Do NOT verify with `Grep` or `Read` after a successful `findReferences` call — the LSP result is authoritative. If you need to understand the code at a reference site, use `codegraph_node` on the symbol at that location, not `Read` on the entire file.

#### Rule 2: "What is this symbol?" → `codegraph_node`, but branch on kind

**Before calling `codegraph_node`, check the symbol's kind** (returned by `codegraph_context` or `codegraph_search`):

| Symbol kind | `includeCode` | Why |
|-------------|---------------|-----|
| interface, type, enum, constant | `false` (or omit) | Signature IS the complete definition. There is no implementation body. |
| function, method, class | `true` | You need to see the implementation logic. |

**Do NOT use `includeCode: true` on types/interfaces/enums/constants** — the result is identical to signature-only because these symbols have no implementation body. And do NOT call signature-only first then upgrade to includeCode — decide once based on kind.

**Do NOT use `Read` for either case.** `codegraph_node` returns only that symbol's code (~25 lines), while `Read` returns the entire file (~100+ lines).

#### Rule 3: Signature already in previous results → Do nothing

If `codegraph_context` or a previous call already showed the signature, do NOT call `codegraph_node` again to re-fetch it. You already have it.

#### Rule 4: Precise inferred type → `LSP hover`

For generics, unions, or complex inferred types that `codegraph_node` signatures don't fully resolve.

#### Rule 5: Cross-function control flow in one file → `Read` (with line range)

This is the ONLY valid use of `Read` for code files. When you need to see how multiple functions interact within the same file — not for understanding a single symbol.

### Quick Reference

| I want to know... | Action | WRONG — do not use |
|---|---|---|
| Who uses/calls/imports/handles X? | **`LSP findReferences(X)`** | ~~codegraph_search("guessed consumer name")~~ ~~codegraph_callers~~ |
| What is this type/interface/enum/constant? | **`codegraph_node(includeCode: false)`** | ~~codegraph_node(includeCode: true)~~ ~~Read~~ |
| How does this function/method/class work? | **`codegraph_node(includeCode: true)`** | ~~Read~~ ~~codegraph_node then upgrade~~ |
| Signature already in results? | **Do nothing** | ~~codegraph_node~~ ~~Read~~ |
| Exact inferred type? | **`LSP hover`** | |
| Multiple functions interacting in one file? | **`Read` (line range)** | Only valid `Read` use for code |

**Workflow after `codegraph_context`:**
1. `codegraph_context` returns entry-point symbols **with signatures and code snippets already included**. Run Step A (Extract) — signatures, field names, parameter types, and relationships are already there.
2. **`LSP findReferences`** on entry-point symbols — especially event constants, exported functions, and interfaces — to discover callers, handlers, and implementors. Do NOT guess consumer names and search.
3. For symbols where you need more detail, **check the kind first**:
   - type / interface / enum / constant → `codegraph_node` signature only
   - function / method / class → `codegraph_node(includeCode: true)`
   - Do NOT use `Read` for either case.

### Step D: Stop When Your Task Questions Are Answered

After each tool call, check: **can I now answer the questions my task requires?**

- YES → stop exploring, proceed with your task
- NO → go back to Step B, identify the next specific gap

Do NOT explore "just in case" or "to be thorough." Every tool call must target a specific gap.

## Example: Good vs Bad

**Bad — pattern 1 (guessing consumer name instead of findReferences):**
```
Saw eventBus.emit('FILE_UPLOADED') in context results
codegraph_search "FileUploadHandler" → guessed a name, found nothing!
codegraph_search "FileEventService" → guessed another name!
→ Wasted 2 calls. Should have used: LSP findReferences on FILE_UPLOADED
  (using its filePath + line from context results) — returns ALL actual consumers in one call.
```

**Bad — pattern 2 (includeCode on type, then duplicate fetch):**
```
codegraph_node("IUser", includeCode: false) → got { name, email, role }
...later...
codegraph_node("IUser", includeCode: true) → got the same { name, email, role }
→ Wasted 2 calls. IUser is an interface — signature IS the full definition.
  Should have called once with includeCode: false (or not at all if already in context).
```

**Bad — pattern 3 (Read instead of codegraph_node):**
```
Need to see how createUser works internally?
  WRONG: Read user-service.ts (full file, ~120 lines) → got createUser + 5 other functions you don't need
  RIGHT: codegraph_node(includeCode: true) createUser → got only createUser's code (~25 lines)
→ Read wastes ~80% of the context on code you didn't ask for.
```

**Good (correct tool for each gap):**
```
codegraph_context → found 6 symbols with snippets
  Step A (Extract from results):
    - IUser (interface): signature shows { name, email, role } → ALREADY HAVE full definition
    - createUser (function): signature shows (data: IUser) => Promise<User> → HAVE signature
    - UPLOAD_EVENT (constant): visible in results → ALREADY HAVE
  Step B (Gaps):
    - Gap 1: who calls createUser? → findReferences (not search!)
    - Gap 2: who handles UPLOAD_EVENT? → findReferences (not "search EventHandler"!)
    - Gap 3: how does createUser work? → codegraph_node(includeCode: true) — it's a function
    - NOT a gap: IUser fields — already in context, no call needed
    - NOT a gap: UPLOAD_EVENT value — already in context, no call needed
LSP findReferences(filePath + line from createUser's codegraph result, character at "createUser")
  → 3 call sites (RegisterPage, AdminPanel, test)
LSP findReferences(filePath + line from UPLOAD_EVENT's codegraph result, character at "UPLOAD_EVENT")
  → 2 consumers (EventListener, NotificationService)
  Gaps 1, 2 filled. Discovered actual consumers without guessing names.
codegraph_node(includeCode: true) createUser → function body with validation + DB call
  Gap 3 filled.
→ 4 tool calls, 0 file reads, 0 name guesses, 0 redundant fetches
```
