---
name: my-explore-0
description: Use when Codex needs lightweight code exploration in an unfamiliar or non-trivial codebase. Tells Codex how to analyze a need and what is forbidden; tool choice is Codex's own judgment within these constraints.
---

<GOAL>
Turn the user prompt into the minimum decisive context for the next step.
</GOAL>

<TOOLS>
- `mcp__probe__search_code` — semantic/keyword search across the repo.
- `mcp__probe__extract_code` — extract code from a specific file + position or file + `#SymbolName`.
- `mcp__ast_grep__find_code` — structural pattern match across the repo.
- `mcp__language_server__get_symbol_definitions` — canonical definition of a symbol; accepts a bare terminal identifier.
- `mcp__language_server__get_symbol_references` — callers and usages of a symbol.
- `mcp__language_server__get_diagnostics` — compiler, type, and lint errors.
</TOOLS>

<TOOL_USAGE_TEMPLATES>
These are the canonical call shapes. Copy the pattern; do not invent parameters you have not seen in one of these templates.

probe.search_code — first-call discovery by concept (no exact symbol known)
```
{
  "path": "<repo root>",
  "query": "resume parse pipeline",
  "lsp": true
}
```
- Natural-language phrase, 2–5 words. No `exact:true`. No `AND`/`OR` across short common words. No quoted literals.

probe.extract_code — extract by file + symbol
```
{
  "path": "<repo root>",
  "files": ["src/server/infrastructure/llm/factory.ts#LLMFactory"],
  "format": "markdown",
  "lsp": true,
  "allowTests": false
}
```
- `files[]` entries must be `realFilePath#SymbolName` or `realFilePath:line`. Never directory#Symbol, never `:1`, never URL-encoded paths. Decode `%28`→`(` etc. before passing paths returned by LSP.

probe.extract_code — extract by file + line range
```
{
  "path": "<repo root>",
  "files": ["src/server/application/task/task-executor.factory.ts:33-45"],
  "format": "markdown",
  "lsp": true
}
```

ast_grep.find_code — structural pattern match
```
{
  "pattern": "fetch($URL, { method: 'POST' })",
  "path": "<repo root>",
  "lang": "typescript"
}
```
- Pattern must include real structure around `$VAR` metavariables. Never bare `$FUNC(...)` or bare `$X`.

language_server.get_symbol_definitions — bare-name lookup (file unknown)
```
{ "symbolName": "findLLMSetting" }
```
- Terminal identifier only. Never `Class.method`, never `ns::Class::method`, never dotted access.

language_server.get_symbol_references — bare-name lookup (if tool supports it)
```
{ "symbolName": "createExecutor" }
```
- Same rule: terminal identifier. If the tool requires coordinates, pass `file_path`, `line`, `character` from a prior definition call.

language_server.get_diagnostics — file-scoped errors
```
{ "filePath": "src/server/infrastructure/llm/factory.ts" }
```
- Use the real filesystem path, not a URL-encoded one.
</TOOL_USAGE_TEMPLATES>

<OUTPUT_FORMAT>
Before the first tool call, your visible reply MUST contain, in this order:
1. A one-sentence restatement of the user's need.
2. The missing signals that block the next correct step (at most 3). If the user already gave every needed file + symbol + evidence, write "none — answering directly" and answer without any tool call.
3. A **file-centric hypothesis plan**. Unit of reasoning is the FILE, not the symbol. Format: one line per file, `<path> → expected: <what you expect to see there>`. Example:

   ```
   Hypothesis plan:
     - src/server/infrastructure/llm/factory.ts → expected: LLMFactory class + 4 create* methods + vendor switch
     - src/server/application/llm/interface/chat.interface.ts → expected: ChatInterface shape
   ```

   Then pick the call strategy by file knowledge:
   - **All files in the plan are known paths** → first call is a single `extract_code(files=[...])` covering every file. Do NOT write one plan line per symbol; group symbols under their file.
   - **No file known, only symbol names (1 symbol)** → `get_symbol_definitions({symbolName})` to discover the file, then add the file to the plan.
   - **No file known, ≥ 2 related symbols** → ONE `probe.search_code` with a 2–4 word concept phrase to discover files, then ONE batched `extract_code(files=[...])`. Do NOT fire `get_symbol_definitions` once per symbol.

Only after that may the first tool call go out.

Between every two tool calls, your visible reply MUST be ONE line in this EXACT format:

  `→ <result>. <shortname1>[<tag>] <shortname2>[<tag>] ... next: <tool | done>`

Tags (use the basename of the file, not the full path):
  - `[COMPLETE L1-Ln]` — returned body covers L1..Ltotal for that file
  - `[OPEN L<a>-?]` — partial body; Ltotal unknown or not yet covered
  - `[missing-in-complete]` — symbol expected in a `[COMPLETE]` file, not in the body → conclusive absent
  - `[unknown-file]` — symbol needed but file not yet located

For non-file calls (`search_code`, `get_symbol_definitions`, `wc -l`), use:
  `→ <result>. candidates=[f1,f2,...] | symbol-not-found | sizes={f1:n1,f2:n2}. next: <tool | done>`

Rules enforced by the tags:
  - `[OPEN]` with unknown Ltotal → next tool MUST be `wc -l`.
  - `[missing-in-complete]` → named blacklist applies; do NOT verify with any other tool.
  - All plan entries resolved (each is `[COMPLETE]`, `[missing-in-complete]`, or satisfied) → output the final `<output_format>` block from the u-0 skill (Feature/change or Bug fix), then `done — stopping`. Do NOT truncate.

These are output requirements, not internal thinking. A multi-line or verbose inter-call narration is itself a rule violation — collapse to the single line above.
</OUTPUT_FORMAT>

<EVIDENCE_CHECKLIST>
Pick the one that matches the user's intent. These are the minimum evidence to stop; do not keep exploring past them.
- Locate behavior: one candidate owner + one exact extract.
- Explain a method: exact method extract + direct references only if callers matter.
- Trace impact: definition + references + nearest affected boundary.
- Scope a refactor: canonical abstraction + structurally similar sites + validation surface.
- Match a code shape: one structural-match query + one representative extract confirming a real match.
- Diagnose a type or compile error: diagnostics first, then definition of the offending symbol.
</EVIDENCE_CHECKLIST>

<STOP_RULE>
Stop when the owner, execution path, impact surface, and validation path are clear enough to answer correctly. If the next output will ask the user to pick between design options, each option must first be anchored in real code evidence — not guesses.
</STOP_RULE>

<BUDGET>
Maximum 6 tool calls per exploration.
Calls beyond 3 are allowed only when you can name the specific unresolved gap that still blocks a correct answer.
If you cannot name that gap, stop.
</BUDGET>

<FORBIDDEN>
- Never read an entire code file at once.
- Never run `mcp__probe__extract_code` with `:1`. Use the exact matched line from search results, or prefer `#SymbolName`.
- Never pass a directory path or repo root to `mcp__probe__extract_code` with a `#SymbolName` suffix. `#SymbolName` only works when anchored to a concrete file path.
- Never pass a URL-encoded file path (containing `%28`, `%29`, `%20`, etc.) to `mcp__probe__extract_code` or any filesystem-level tool. Decode to the real filesystem path (`(`, `)`, space) first. LSP tools often return URL-encoded paths — decode them before forwarding.
- Never pass `exact:true` to `mcp__probe__search_code`. The exact mode defeats the semantic index and routinely returns zero results. If you need an exact symbol match, use `mcp__language_server__get_symbol_definitions` with the bare terminal identifier instead.
- Never combine multiple short common words with `AND` in a `mcp__probe__search_code` query (e.g. `"Job" AND "Task"`). Probe's AND needs a distinctive co-occurrence to succeed — two generic nouns almost always return zero. If you want both symbols, call `get_symbol_definitions` for each, in parallel.
- Never use `mcp__probe__search_code` when the user prompt contains exactly ONE exact symbol name and its file is unknown. Use `mcp__probe__extract_code` with `path/to/file.ts#SymbolName` (file known) or `mcp__language_server__get_symbol_definitions` with the bare terminal identifier (file unknown). EXCEPTION: when the user prompt names 2+ exact symbols belonging to the same feature/area with unknown files, ONE `probe.search_code` with a concept phrase is preferred over N sequential `get_symbol_definitions` turns — use it as the first call to locate all files, then batch everything into one `extract_code(files=[...])`.
- Never retry `mcp__probe__search_code` with broader or reworded queries after a zero-result call for an exact symbol. Pivot to `mcp__probe__extract_code` with `#SymbolName` or `mcp__language_server__get_symbol_definitions`. Reworded re-search is only allowed when the original query was conceptual and returned no credible owner; state why the first one failed.
- Never fall back to `mcp__probe__search_code` or any regex/text search after `mcp__probe__extract_code` with `#SymbolName` returns zero results. Pivot to `mcp__language_server__get_symbol_definitions` with the bare terminal identifier.
- Any search or pattern-matching tool — `mcp__probe__search_code`, `mcp__ast_grep__find_code`, native `grep` / `rg` / `Search`, or any regex/text match over source — may only appear as the FIRST tool call of the turn, used to break open an unknown problem. After that first call, every search/pattern-matching tool is forbidden for the rest of the turn. All subsequent calls must be `mcp__probe__extract_code` or a `mcp__language_server__*` tool.
- Never use any regex or text search (native `grep`, `rg`, `Search`, or any similar tool) to locate an exact PascalCase/camelCase symbol name. Use `mcp__language_server__get_symbol_definitions` with the bare terminal identifier instead. This rule applies to every tool that runs a pattern over source files, not just `mcp__probe__search_code`.
- Never run a shotgun `A|B|C|...` regex that combines multiple exact symbol names into one query. Query each symbol separately via `mcp__language_server__get_symbol_definitions`; batch the calls in parallel if they are independent.
- Never broaden the search space once an exact target is already known.
- Never pass a dotted call expression (`Foo.bar`, `ns::Foo::bar`) as a symbol name to any language_server tool. Use the terminal identifier only.
- Never run `mcp__ast_grep__find_code` with an overly generic pattern (bare `$FUNC(...)`, bare `$X`). Anchor the pattern to meaningful structure.
- Never call `mcp__language_server__get_symbol_references` or `get_symbol_definitions` without a concrete `file_path` and position, unless the tool explicitly supports bare-name lookup.
- Never edit code when the load-bearing conclusion rests on output from a single tool. Confirm it with a second, different tool first; the verification call counts against the budget.
- Never call `mcp__language_server__get_symbol_definitions` OR `mcp__language_server__get_symbol_references` more than ONCE per exploration turn. Multi-symbol exploration goes through `probe.search_code` (concept phrase) + a single batched `extract_code(files=[...])`, not through N sequential `get_symbol_definitions` / `get_symbol_references` calls. A 4-symbol exploration must resolve in ≤ 2 turns, not 4.
- Never use `get_symbol_definitions` to read a full method or class body. It returns a truncated snippet (roughly the first 5 lines). Once a definition reveals the real `file_path`, pivot to `extract_code(files=["file_path#SymbolName"])` for the full body. Body reads go through `extract_code`, not `get_symbol_definitions`.
- Never re-read `SKILL.md` (this file) during an exploration turn. If a tool errors or returns empty, pivot per the rules above — do not re-open instructions mid-run.
- When any `language-server.*` tool returns `No language servers are currently running` or an equivalent infra-level error once, treat the ENTIRE `language-server.*` family as UNAVAILABLE for the rest of this turn. Retry ban — no second attempt on the same tool, no attempt on any sibling `language-server.*` tool. Pivot immediately: `probe.search_code` with the symbol name for caller lookup, or `Grep` for pattern-based caller search. Calling another `language-server.*` tool after this error = rule violation.
- Never treat a batched `extract_code` result as N independent symbol lookups. The returned file body IS the complete content of that file when line range covers L1–L_total. If a symbol listed in your plan is absent from a `[COMPLETE]` file body, conclude "that symbol does not exist in this file" — conclusive negative, no verification allowed.
- **Named blacklist** — after a file is marked `[COMPLETE]` in narration, NEVER call any of the following to "verify" a missing symbol in that same file: `language-server.get_symbols`, `language-server.get_server_projects`, `language-server.get_server_status`, `language-server.start_server`, `language_server.get_symbol_definitions` (for a symbol name expected in the complete file), a second `probe.extract_code` on the same file with any `#Symbol` or line range, `probe.search_code` scoped to that file, `ast_grep.find_code` scoped to that file, `language-server.get_diagnostics` on that file. Call any of these = rule violation, stop immediately.
- **Whitelist for file boundary** — `wc -l <path>` (via bash / shell) is the ONLY allowed way to confirm a file's total line count when the extract result did not expose it. Never use `start_server` + `get_symbols` as a substitute; it costs a 120s timeout and returns the same information. **Batch required**: when ≥ 2 files need boundary check, issue ONE call `wc -l <f1> <f2> <f3> ...` — `wc` natively accepts multiple paths and returns all sizes in one invocation. Sequential one-file-per-call `wc -l` is a rule violation.
- Never express the hypothesis plan as a flat list of symbol names. Plan units are FILES — group symbols under their file and write one `<path> → expected: ...` line per file. A symbol-only plan is a rule violation; rewrite it before the first call.
</FORBIDDEN>
