# my-explore — Tool Palette (intent-keyed)

This is the COMPLETE tool palette. Anything not listed here is forbidden for code exploration. Match each direction's *intent* to a scenario below; the named tool is the only correct call for that intent.

**Single source of truth.** This file lives at `/Users/Woo/.claude/skills/my-explore-0/TOOLS.md` and is shared by both the main session (via the `my-explore-0` skill) and the `my-explore` subagent (referenced from its `AGENT.md`). Do NOT duplicate it under `~/.claude/agents/my-explore/`.

## LSP schema reminder (read before using any LSP op)

The `LSP` tool requires `operation`, `filePath`, `line`, `character` — **all four, always**.

- Valid `operation` values: `goToDefinition`, `findReferences`, `hover`, `documentSymbol`, `workspaceSymbol`, `goToImplementation`, `prepareCallHierarchy`, `incomingCalls`, `outgoingCalls`. Any other op name → `InputValidationError`.
- Whole-file ops (`documentSymbol`, `workspaceSymbol`) functionally ignore `line`/`character` but the schema still rejects calls that omit them. Pass `line=1, character=1`.
- There is no `LSP get_symbol_definitions`, `LSP get_symbol_references`, or `LSP get_diagnostics`. Use the operations above.

## Scenarios

### Get the body of ONE specific symbol — file + symbol known
**Tool:** `mcp__probe__extract_code files=["<path>#<Symbol>"]`
**Replaces:** opening the file with `Read`, dumping with `cat`, scrolling with `head`/`tail`.

### Get the bodies of N related symbols (single call)
**Tool:** `mcp__probe__extract_code files=["a#X", "b#Y", "c#Z"]` — batched.
**Rule:** ALWAYS one batched call, never N separate calls.
**Replaces:** looping `cat`, sequential `Read`s.

### Get a body by file + line range (symbol name unknown, range known)
**Tool:** `mcp__probe__extract_code files=["<path>:<L1>-<L2>"]`.
**Replaces:** `sed -n 'L1,L2p'`, `head -L2 | tail -...`.

### Discover every symbol in a file (file path known, symbol names unknown)
**Tool:** `LSP(operation="documentSymbol", filePath="<path>", line=1, character=1)`.
Returns the name + range of every class / method / interface / const — compact metadata, no bodies. THEN feed names into `extract_code`.

### Find every caller of a symbol — file:line:col already known
**Tool:** `LSP(operation="findReferences", filePath, line, character)`.
**Replaces:** `Bash(grep -rn '<Symbol>(' ...)` — and `findReferences` is semantically aware: it does NOT miss renamed imports, destructured calls, or namespace references.

### Find every caller of a symbol — only the bare name is known
**Tool:** two-step. First locate the definition via `mcp__probe__search_code` (concept) or `mcp__ast-grep__find_code` (structural pattern). Then `LSP findReferences` at the resolved file:line:col.
**Replaces:** any combination of `grep` / `rg`.

### Jump to the definition of a symbol — call site (file:line:col) known
**Tool:** `LSP(operation="goToDefinition", filePath, line, character)`.

### Search for a symbol by bare name across the whole workspace
**Tool:** `LSP(operation="workspaceSymbol", filePath="<any-existing-source-file>", line=1, character=1)` — `filePath`/`line`/`character` are required by the schema but the search itself is workspace-wide. If this returns nothing, fall back to the bootstrap scenario (`search_code`).

### Find files whose PATHS match a glob pattern (no content needed)
**Tool:** `Glob pattern="<glob>"`.
**Replaces `find` and `ls`.** Whenever the question is "which files match path X" — Glob, never `Bash(find ...)`, never `Bash(ls ...)`. If the glob alone won't narrow enough, ALSO use `Glob`, just with a smarter pattern.

### Find a code construct by AST shape (not by text)
**Tool:** `mcp__ast-grep__find_code pattern="<lang pattern>"`. `$NAME` matches one node; `$$$` matches zero or more.
**Replaces:** regex `Grep` on source — `ast-grep` won't false-positive on comments or strings.

### Constrain AST matches by enclosing/contained/adjacent structure
**Tool:** `mcp__ast-grep__find_code_by_rule` with `inside` / `has` / `follows`.

### Bootstrap when only domain concepts are given (no file, no symbol)
**Tool:** `mcp__probe__search_code query="<2–4 word phrase>" path="<scoped dir>"`.
**Cap:** at most ONE `search_code` per request. Once a concrete file:line surfaces → pivot to `extract_code`.
**Rule:** never pass regex (`|`, `\(`, `\b`) — concept engine, not regex. For regex on non-source files, use `Grep`.

### Look up text inside NON-source files (`.md`, `.json`, `.yaml`, configs, logs)
**Tool:** `Grep pattern="<text>" path="<dir>"`. Always pass `path` or `glob`.
**Reserved for non-source files ONLY.** Never run `Grep` on `.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.c/.cpp/.rb/.swift/.kt` — for those use `LSP`, `ast-grep`, or `probe`.
**Replaces:** `Bash(grep ...)` / `Bash(rg ...)`.

### Read an entire non-source file end-to-end (docs / configs)
**Tool:** `Read path="..."` — ONLY for `.md`, `.yaml`, `.yml`, `.toml`, `.json`, `.env`, `.txt`, `.ini`.
**Never `Read` on source code** — source goes through `extract_code`.

### Out of scope: type / compile diagnostics
The `LSP` tool exposed to this agent does NOT have a diagnostics operation. `mcp__ide__getDiagnostics` exists in the broader environment but is not in this agent's tool list. If a direction asks for type errors, return `"no match"` and let the caller handle it.

## Forbidden (no exceptions)

- `Bash(find:*)` / `Bash(ls:*)` / `Bash(cat:*)` / `Bash(head:*)` / `Bash(tail:*)` / `Bash(wc:*)` / `Bash(xargs:*)` / `Bash(grep:*)` / `Bash(rg:*)` / `Bash(tree:*)`
- `Read` on source-code files
- LSP op names not in the schema list above (e.g. `get_symbol_definitions`, `get_symbol_references`, `get_diagnostics`)
- LSP calls that omit `line` / `character`

If you find yourself reaching for any of the above, you have either:
1. mis-classified the intent — re-read the scenarios and pick the right one, OR
2. encountered an intent not covered here — STOP, do not improvise; the palette is closed.
