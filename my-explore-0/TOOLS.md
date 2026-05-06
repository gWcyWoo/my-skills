# my-explore — Tool Palette (intent-keyed)

This is the COMPLETE tool palette. Anything not listed here is forbidden for code exploration. Match each direction's *intent* to a scenario below; the named tool is the only correct call for that intent.

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

### Find every caller of a symbol — file:line:col already known
**Tool:** `LSP findReferences` (operation, filePath, line, character).
**Replaces:** `Bash(grep -rn '<Symbol>(' ...)` — and `findReferences` is semantically aware: it does NOT miss renamed imports, destructured calls, or namespace references.

### Find every caller of a symbol — only the bare name is known
**Tool:** two-step. First locate the definition via `mcp__probe__search_code` (concept) or `mcp__ast-grep__find_code` (structural pattern). Then `LSP findReferences` at the resolved file:line:col.
**Replaces:** any combination of `grep` / `rg`.

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

### Get the canonical definition of a symbol — file unknown, only bare name
**Tool:** `LSP get_symbol_definitions symbolName="<bare-terminal-id>"`. Terminal identifier only (no `Class.method`, no `ns::Class::method`).

### Get all references of a symbol via LSP
**Tool:** `LSP get_symbol_references` (with file_path/line/character if required).

### Diagnose type / compile errors in a file
**Tool:** `LSP get_diagnostics filePath="<real path>"`.

## Forbidden (no exceptions)

- `Bash(find:*)` / `Bash(ls:*)` / `Bash(cat:*)` / `Bash(head:*)` / `Bash(tail:*)` / `Bash(wc:*)` / `Bash(xargs:*)` / `Bash(grep:*)` / `Bash(rg:*)` / `Bash(tree:*)`
- `Read` on source-code files

If you find yourself reaching for any of the above, you have either:
1. mis-classified the intent — re-read the scenarios and pick the right one, OR
2. encountered an intent not covered here — STOP, do not improvise; the palette is closed.
