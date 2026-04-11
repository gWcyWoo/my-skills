<tool_reference>

<scenarios>

<scenario>
<intent>The source body (~30 lines) of a specific symbol, identified by name or line anchor.</intent>
<tool>`probe extract_code files=["<file>#<symbol>"]`. If the symbol name is unknown, use `probe search_code` or `ast-grep find_code` to locate it first. When both file and symbol are already known (even approximately), go straight to `file#symbol`.</tool>
<note>`file:line` returns the AST node at that line, NOT the enclosing function/method. If you want the enclosing block, find its symbol name first, then use `file#symbol`.</note>
<invalid>Line ranges (`file:320-480`); bare file paths with no anchor; `file:line` when the target is the enclosing block rather than the node at that line.</invalid>
</scenario>

<scenario>
<intent>The bodies of N related symbols returned in a single response.</intent>
<tool>`probe extract_code files=["a#x","b#y","c#z"]`. Prefer one batched call over N narrow calls; every entry must still be `file#symbol` or `file:line`.</tool>
</scenario>



<scenario>
<intent>Every call site of a symbol — the caller file:line for every reference.</intent>
<tool>`LSP findReferences symbol="<name>" in="<file>"`. Semantically accurate; `Grep` misses renamed imports, destructured calls, and namespace references.</tool>
</scenario>

<scenario>
<intent>Every outgoing call made from inside a symbol's body (its callees).</intent>
<tool>`probe extract_code files=["<file>#<symbol>"]`, then read the call expressions inside the returned body. There is no dedicated outgoing-calls LSP endpoint; the body is the source of truth.</tool>
</scenario>

<scenario>
<intent>The body plus every caller plus every callee of one symbol, delivered in a single response. Used at the entry hop of a Trace.</intent>
<tool>`probe extract_code files=["<file>#<symbol>"] lsp=true`. Expensive (10–15k tokens); open at the entry hop only — every subsequent hop uses plain `extract_code`.</tool>
<gate>
Open `lsp: true` only when ALL three conditions hold:
1. The exact `file#symbol` is already known.
2. `extract_code` and `findReferences` will run on the **same** symbol back-to-back.
3. Callees are also required in the same response.
If any condition fails, use targeted tools (plain `extract_code` + separate `findReferences`) — 3–5× cheaper.
</gate>
</scenario>

<scenario>
<intent>A concrete file:line for a concept described only by domain keywords (no symbol, file, or UI label named).</intent>
<tool>`probe search_code query="<domain keywords>" path="<scoped dir>" limit=5-10`. One-shot bootstrap: at most two calls per query. Stop the moment a concrete symbol surfaces and switch to `probe extract_code`.</tool>
</scenario>

<scenario>
<intent>The list of files whose paths match a glob pattern.</intent>
<tool>`Glob pattern="<glob>"`. Replaces `ls` and `find`. Use when the question is "which files match path X", not "which lines contain text Y".</tool>
</scenario>

<scenario>
<intent>Every code location matching a given AST pattern.</intent>
<tool>`ast-grep find_code pattern="<language pattern>"` — `$NAME` matches one node, `$$$` matches zero or more. Prefer over `Grep` for code structure: no false positives from comments or string literals. Pattern must be a parseable single AST node — if `find_code` reports a parse error, shrink the pattern to a smaller node. When file + symbol are already known, do not write an AST pattern to find the declaration — use `extract_code file#symbol` directly.</tool>
</scenario>

<scenario>
<intent>A subset of AST matches constrained by an enclosing, contained, or adjacent node.</intent>
<tool>`ast-grep find_code_by_rule` with `inside` / `has` / `follows`. Use when `find_code` returns too many matches.</tool>
</scenario>

<scenario>
<intent>The raw AST shape of a known-good example, to debug a pattern that fails to match.</intent>
<tool>`ast-grep dump_syntax_tree`. Inspect the tree, then rewrite the pattern to match.</tool>
</scenario>

<scenario>
<intent>The import dependency graph of a module or directory.</intent>
<tool>`ast-grep analyze-imports mode="usage"` (for refactoring) or `mode="discovery"` (for exploration).</tool>
</scenario>

<scenario>
<intent>Text occurrences inside non-source files (md / json / yaml / configs / logs).</intent>
<tool>`Grep pattern="<text>" path="<dir>"`. Always pass `path` or `glob`. Never run on source files — use `LSP`, `ast-grep`, or `probe search_code` for those.</tool>
</scenario>

<scenario>
<intent>The enclosing function / method / callback for a matched line or AST hit.</intent>
<tool>Find the enclosing symbol name first (via `probe search_code` or `probe extract_code files=["<file>#"]`), then `probe extract_code files=["<file>#<enclosing_symbol>"]`. Do NOT use `file:line` — it returns the node at that line, not the enclosing block.</tool>
</scenario>

<scenario>
<intent>The raw contents of a non-source file (spec / README / config / log).</intent>
<tool>`Read file_path="<path>"`. Permitted for `.md/.json/.yaml/.toml/.txt`, configs, and logs. Not for source code.</tool>
</scenario>

</scenarios>

<priority_under_ambiguity>
`LSP` (position known) > `ast-grep` (code shape known) > `Grep` (literal text, non-source only) > `probe search_code` (concept only).
</priority_under_ambiguity>

<recovery>
- A tool errored or returned less than expected → fix the arguments and retry the same tool. Never switch to `Read` as a workaround.
- A suggested file path does not exist → do not enumerate `Glob` variants. Use `probe search_code` with a concept keyword to locate the real file.
- A location has already been identified → do not re-search to verify. Trust the authoritative tool.
- You are reaching for regex alternation (`|`) on source files → you are using the wrong tool. Re-classify the query and pick `LSP` / `ast-grep` / `Glob` / `probe search_code`.
- An LSP call reports "No language servers are currently running" or equivalent → mark LSP unavailable for the rest of this query. Do not retry any LSP calls; switch to `probe extract_code`, `probe search_code`, or `ast-grep`.
- An exact source file path is already known → keep the search radius file-local until existence and declaration shape are resolved, unless the file path itself is now suspect.
- Two successive calls failed to confirm the same hypothesis → stop varying tools on that hypothesis. State the new hypothesis first, then choose the next tool.
- The current question is already answered at this layer → stop. Do not drill into downstream callees or side effects unless the query explicitly asks for them.
</recovery>

</tool_reference>
