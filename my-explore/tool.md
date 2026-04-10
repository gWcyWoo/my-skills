<tool_reference>

<scenarios>

<scenario>
<intent>The source body (~30 lines) of a specific symbol, identified by name or line anchor.</intent>
<tool>`mcp__probe__extract_code files=["<file>#<symbol>"]`. If the symbol name is unknown, call `mcp__language_server__get_symbols file_path="<file>"` first to list the file's symbols, then use `file#<symbol>`. When both file and symbol are already known, even approximately, go straight to `file#symbol` — do not call `get_symbols`, `get_project_symbols`, `mcp__probe__search_code`, or `mcp__ast_grep__find_code` first.</tool>
<invalid>Line ranges (`file:320-480`); bare file paths with no anchor; `file:line` when the target is the enclosing block rather than the node at that line.</invalid>
<note>`file:line` is a node anchor, not a guarantee of the enclosing function, method, or callback. If the real target is the containing block, identify the enclosing symbol first, then extract `file#<symbol>`.</note>
</scenario>

<scenario>
<intent>A first scoped anchor inside a known source file or its nearest relevant directory, when the exact file is already known but existence or declaration shape is unresolved.</intent>
<tool>`rg -n "<exact text>" <known-file-or-nearest-dir>`. This is the only allowed `rg` use on source files: the exact path is already known, the exact text being tested is known, and the goal is to anchor existence or declaration shape before switching back to `mcp__probe__extract_code` or `mcp__ast_grep__find_code`.</tool>
<note>Use this to test narrow hypotheses like `POST`, `export`, `handler`, `NextResponse`, or an exact UI literal. Do not use it to browse source broadly. If the exact text is not known, use `mcp__ast_grep__find_code` or `mcp__probe__search_code` instead.</note>
</scenario>

<scenario>
<intent>The bodies of N related symbols returned in a single response.</intent>
<tool>`mcp__probe__extract_code files=["a#x","b#y","c#z"]`. Prefer one batched call over N narrow calls; every entry must still be `file#symbol` or `file:line`.</tool>
</scenario>

<scenario>
<intent>The enclosing function, method, or callback for a matched line or AST hit.</intent>
<tool>If an enclosing symbol exists, identify that symbol first, then use `mcp__probe__extract_code files=["<file>#<symbol>"]`. Use `file:line` only when the local AST node itself is the target, not when the enclosing block is the target.</tool>
</scenario>

<scenario>
<intent>A full outline of every symbol declared in a file.</intent>
<tool>`mcp__language_server__get_symbols file_path="<file>"`. Required before `file#symbol` extraction when the file is known but the symbol name is not.</tool>
<gate>Use ONLY when the file is known but the symbol name is genuinely unknown. If you can name the symbol, even approximately, skip this and go straight to `mcp__probe__extract_code files=["<file>#<symbol>"]`. Do not use `get_symbols` as a "see what's in the file" step before an extraction you already know the target for.</gate>
<note>If the language server reports that it is unavailable or not running, do not keep calling adjacent language-server endpoints on the same query. Switch to non-LSP routes: `mcp__probe__extract_code`, `mcp__probe__search_code`, or `mcp__ast_grep__*`.</note>
</scenario>

<scenario>
<intent>The file:line of every declaration matching a given symbol name, across the project.</intent>
<tool>`mcp__language_server__get_project_symbols query="<name>"`. Use when the name is known but the file is not.</tool>
<gate>Never use when the file is already known — use `mcp__language_server__get_symbols` if the symbol is unknown, or `mcp__probe__extract_code files=["<file>#<symbol>"]` if the symbol is known.</gate>
</scenario>

<scenario>
<intent>Every call site of a symbol — the caller file:line for every reference.</intent>
<tool>`mcp__language_server__get_symbol_references`. Semantically accurate; `rg -n` misses renamed imports, destructured calls, and namespace references.</tool>
</scenario>

<scenario>
<intent>Every outgoing call made from inside a symbol's body (its callees).</intent>
<tool>`mcp__probe__extract_code files=["<file>#<symbol>"]`, then read the call expressions inside the returned body. There is no dedicated outgoing-calls language-server endpoint; the body is the source of truth.</tool>
</scenario>

<scenario>
<intent>The body plus every caller plus every callee of one symbol, delivered in a single response. Used at the entry hop of a Trace.</intent>
<tool>`mcp__probe__extract_code files=["<file>#<symbol>"] lsp=true`. Expensive (10–15k tokens); open at the entry hop only — every subsequent hop uses plain `extract_code`.</tool>
<gate>
Open `lsp: true` only when ALL three conditions hold:
1. The exact `file#symbol` is already known.
2. `extract_code` and `get_symbol_references` would run on the **same** symbol back-to-back.
3. Callees are also required in the same response.
If any condition fails, use targeted tools instead: plain `extract_code` + separate `get_symbol_references` + `get_symbols`.
</gate>
</scenario>

<scenario>
<intent>A concrete file:line for a concept described only by domain keywords (no symbol, file, or UI label named).</intent>
<tool>`mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`. One-shot bootstrap: at most two calls per query. Stop the moment a concrete symbol surfaces and switch to `mcp__probe__extract_code` or `mcp__language_server__get_project_symbols`.</tool>
</scenario>

<scenario>
<intent>The list of files whose paths match a glob pattern.</intent>
<tool>`rg --files <root>` and, if needed, narrow the result set with a second scoped `rg`. Use when the question is "which files match path X", not "which lines contain text Y".</tool>
</scenario>

<scenario>
<intent>Every code location matching a given AST pattern.</intent>
<tool>`mcp__ast_grep__find_code pattern="<language pattern>"`. `$NAME` matches one node; `$$$` matches zero or more. Prefer over `rg -n` for code structure: no false positives from comments or string literals. Pattern must be a parseable single AST node — if `find_code` reports a parse error, shrink it to a smaller node. When file + symbol are already known, do not write an AST pattern to find the declaration — use `mcp__probe__extract_code files=["<file>#<symbol>"]` directly.</tool>
<note>The pattern must parse as a valid single AST node. If ast-grep rejects the pattern, shrink it to a smaller parsable node or debug the shape with `mcp__ast_grep__dump_syntax_tree`. If `file#symbol` is already known, do not use ast-grep to re-find that declaration.</note>
</scenario>

<scenario>
<intent>A subset of AST matches constrained by an enclosing, contained, or adjacent node.</intent>
<tool>`mcp__ast_grep__find_code_by_rule` with `inside` / `has` / `follows`. Use when `find_code` returns too many matches.</tool>
</scenario>

<scenario>
<intent>The raw AST shape of a known-good example, to debug a pattern that fails to match.</intent>
<tool>`mcp__ast_grep__dump_syntax_tree`. Inspect the tree, then rewrite the pattern to match.</tool>
</scenario>

<scenario>
<intent>The import dependency graph of a module or directory.</intent>
<tool>Use `mcp__ast_grep__find_code` scoped to the file or directory for import/export forms such as `import $$$ from $SRC` and `export $$$ from $SRC`. Use this when you need dependency edges and no dedicated import-graph analyzer exists in Codex.</tool>
</scenario>

<scenario>
<intent>Text occurrences inside non-source files (md / json / yaml / configs / logs).</intent>
<tool>`rg -n "<text>" <path>`. Always scope the path. Never run it on source files — use language server, ast-grep, or `mcp__probe__search_code` for those.</tool>
</scenario>

<scenario>
<intent>The raw contents of a non-source file (spec / README / config / log).</intent>
<tool>Direct file read on the non-source path. Permitted for `.md/.json/.yaml/.toml/.txt`, configs, and logs. Not for source code.</tool>
</scenario>

</scenarios>

<priority_under_ambiguity>
Language server (position known) > ast-grep (code shape known) > `rg -n` (literal text, non-source or first scoped source anchor only) > `mcp__probe__search_code` (concept only).
</priority_under_ambiguity>

<recovery>
- A tool errored or returned less than expected → fix the arguments and retry the same tool. Never switch to direct file reads on source as a workaround.
- A suggested file path does not exist → do not enumerate path guesses. Use `mcp__probe__search_code` with a concept keyword to locate the real file.
- A location has already been identified → do not re-search to verify. Trust the authoritative tool.
- You are reaching for regex alternation (`|`) on source files → you are using the wrong tool. Re-classify the query and pick language server, ast-grep, `rg --files`, or `mcp__probe__search_code`.
- A language-server call reports that no server is running or available → mark LSP unavailable for the rest of this query. Do not retry other language-server calls unless the server is explicitly started; switch to `mcp__probe__extract_code`, `mcp__probe__search_code`, or `mcp__ast_grep__*`.
- An exact source file path is already known → keep the search radius file-local until existence and declaration shape are resolved, unless the file path itself is now suspect.
- Two successive calls failed to confirm the same hypothesis → stop varying tools on that hypothesis. State the new hypothesis first, then choose the next tool.
- The current question is already answered at the current layer → stop. Do not drill into downstream callees or side effects unless the query explicitly asks for them.
</recovery>

</tool_reference>
