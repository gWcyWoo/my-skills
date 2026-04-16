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

<OUTPUT_FORMAT>
Before the first tool call, your visible reply MUST contain, in this order:
1. A one-sentence restatement of the user's need.
2. The missing signals that block the next correct step (at most 3). If the user already gave every needed file + symbol + evidence, write "none — answering directly" and answer without any tool call.

Only after that may the first tool call go out.

Between every two tool calls, your visible reply MUST contain:
1. A one-sentence summary of what the last call established.
2. The single most important remaining gap, or "done — stopping" if no gap remains.

These are output requirements, not internal thinking — if the text is not visible in the reply, the requirement is not met.
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
- Never use `mcp__probe__search_code` when the user prompt already contains an exact symbol name (PascalCase/camelCase function, class, type, constant, method). Use `mcp__probe__extract_code` with `path/to/file.ts#SymbolName` (file known) or `mcp__language_server__get_symbol_definitions` with the bare terminal identifier (file unknown).
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
</FORBIDDEN>
