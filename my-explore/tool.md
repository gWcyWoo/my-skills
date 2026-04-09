# Tool Reference

Shared by `my-explore` and `my-explore-0`.

## `probe extract_code` — three modes

1. **`file#symbol` or `file:line`** — returns the function or class body at the exact anchor (~30 lines).
   - Use when the symbol name is known, or a `file:line` is already available from another tool's output.
   - Not `Read`: `Read` returns the whole file (200+ lines); `extract_code` returns only the target symbol.
   - **Line ranges are forbidden.** `file:320-480` is invalid. Use a single anchor. If the symbol name is unknown, call `LSP documentSymbol filePath="<file>"` first to list symbols, then use `file#<symbol>`.
   - **Bare file paths are invalid.** The anchor (`#symbol` or `:line`) is required on every entry.

2. **`lsp: true` flag** — returns the body, callees, and callers in one response.
   - Expensive: 10–15k tokens per hot symbol.
   - Use only at the entry hop of a Trace. Every other hop uses plain `extract_code`.
   - Not a general replacement for LSP. It is a three-dimensional snapshot for one anchor.

3. **Batched `files` array** — returns multiple symbols in one response.
   - Use when inspecting N related symbols together.
   - Prefer one batched call over N narrow calls. Every entry must still be `file#symbol` or `file:line`.

---

## Other Tools

- **`probe search_code`** — semantic search by concept. First choice when the exact path is unknown. Always set `path`. **One-shot bootstrap: at most two calls per query.** Stop the moment a concrete symbol surfaces.
- **`ast-grep find_code`** — AST pattern match. `$NAME` matches one node; `$$$` matches zero or more. Prefer over `Grep` for code structure; no false positives from comments or string literals.
- **`ast-grep find_code_by_rule`** — the same, with `inside` / `has` / `follows` relations for structural queries.
- **`ast-grep dump_syntax_tree`** — inspect the AST of a known-good example when a pattern fails to match.
- **`ast-grep analyze-imports`** — import dependency map. Use `mode: "usage"` for refactoring, `mode: "discovery"` for exploration.
- **LSP** — `documentSymbol` lists symbols in a file; `workspaceSymbol` finds a symbol by name project-wide; `findReferences` returns callers (**never `Grep` for this**); `goToDefinition`, `goToImplementation`, and `hover` navigate from a position.
- **`Grep`** — text search on **non-source files only** (`.md/.json/.yaml/.toml/.txt`, configs, logs). Never run on source code.
- **`Glob`** — find files by name or path pattern. Replaces `ls` and `find`.

---

## Tool Selection Matrix

| Intent | Tool |
|---|---|
| List symbols in a file | `LSP documentSymbol filePath="<file>"` |
| Find a symbol by name, project-wide | `LSP workspaceSymbol query="<name>"` |
| Read one symbol's body | `probe extract_code files=["<file>#<symbol>"]` |
| Read multiple related symbols | `probe extract_code files=["a#x","b#y","c#z"]` (batched) |
| Find who calls a symbol | `LSP findReferences symbol="<name>" in="<file>"` |
| Find what a symbol calls | `probe extract_code` the body, read the calls inside |
| Trace entry: body + callers + callees in one | `probe extract_code files=["<file>#<symbol>"] lsp=true` (once only) |
| Concept → concrete symbol bootstrap | `probe search_code query="<keywords>" path="<dir>"` |
| Files by path pattern (e.g. all `route.ts`) | `Glob pattern="<glob>"` |
| AST-shape matches | `ast-grep find_code pattern="<pattern>"` |
| Text in non-source files | `Grep pattern="<text>" path="<dir>"` |

---

## `lsp: true` Gate

Open `lsp: true` only when **all three** conditions hold:

1. The exact `file#symbol` is already known (no `workspaceSymbol` or `documentSymbol` step required first).
2. `extract_code` and `findReferences` will run on the **same** symbol back-to-back.
3. Callees are also required in the same response.

If any condition fails, use the targeted tool instead (plain `extract_code`, a separate `findReferences`, or `documentSymbol`). Targeted calls are 3–5× cheaper.

---

## Priority Under Ambiguity

`LSP` (position known) > `ast-grep` (code shape known) > `Grep` (literal text, non-source only) > `probe search_code` (concept only).

---

## Recovery Rules

- A tool errored or returned less than expected → fix the arguments and retry the same tool. Never switch to `Read` as a workaround.
- A suggested file path does not exist → do not enumerate `Glob` variants. Use `probe search_code` with a concept keyword to locate the real file.
- A location has already been identified → do not re-search to verify. Trust the authoritative tool.
