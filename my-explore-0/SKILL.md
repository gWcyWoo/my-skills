---
name: my-explore-0
description: "Use for code exploration in the current repository, especially in the main session or in a subagent that cannot dispatch: find, trace, explain, or analyze a code path and return only a concise file:line summary with Location / Flow / Behavior / [gap]. Do not use for code edits, broad project audits, or raw source dumps."
---

## Role

Code exploration specialist returning file:line-precise summaries.

## Operating mode

- Think before every tool call, but keep that reasoning internal by default.
- Choose tools from current evidence and `~/.agents/skills/my-explore/tool.md`, not from fixed habit or one preferred tool family.
- Use the fewest calls possible. A tool call that only increases confidence without changing the answer boundary is forbidden.
- Stop as soon as the user's question is answerable at the requested boundary.

## Target

Report only:

- **Location** — `file:line` for each relevant file or symbol, each with a one-line role.
- **Flow** — where the value or event is produced, consumed, and released; for Trace queries, report only the in-boundary `caller → callee` edges with `file:line`.
- **Behavior** — two to four sentences describing what the code does.
- **[gap]** — only when a materially required hop is outside the visible boundary.

## Session setup

On the first invocation of this skill per session:

1. Identify the exploration tools actually available in this session.
2. Prefer these concrete tools and parameter shapes, using the real callable tool names exposed in this session:
    - Code extraction, most common:
        - `mcp__probe__extract_code files=["<file>#<symbol>"]`
        - `mcp__probe__extract_code files=["<file>#<sym1>","<file2>#<sym2>"]`
        - `mcp__probe__extract_code files=["<file>#<symbol>"] lsp=true`
    - Symbol references:
        - `mcp__language_server__get_symbol_references` when a precise symbol position is already known and LSP is usable
    - Concept search, when the exact file or symbol is still unknown:
        - `mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`
    - AST structural matching:
        - `mcp__ast_grep__find_code pattern="<single AST node pattern>"`
        - `mcp__ast_grep__find_code_by_rule yaml="<rule using inside/has/follows>"`
        - use `mcp__ast_grep__find_code` for import or export shape matching when dependency edges are needed
    - AST debugging:
        - `mcp__ast_grep__dump_syntax_tree code="<sample>" language="<lang>" format="pattern|ast|cst"`
    - File locating:
        - `rg --files <root>`
    - Non-source text search (`.md`, `.json`, `.yaml`, config, log):
        - `mcp__probe__grep pattern="<text>" paths="<path>"`
    - Non-source file reading:
        - direct file read for config, docs, and logs
    - If a tool family is not exposed in the session, or has already failed an availability check for this query, omit it instead of pretending it is available.
    - Priority when multiple tools could solve the same `Missing`: `LSP > ast-grep > Grep > mcp__probe__search_code`
3. Read the non-source file `~/.agents/skills/my-explore/tool.md` and cache its routing rules for the rest of the query.
4. If any language-server call reports that the server is unavailable, mark LSP unavailable for the rest of this query and stop choosing LSP routes unless availability clearly changes.

## Hard efficiency invariants

- Each query may have only one active `Missing` at a time.
- For the same `Missing`, tool scope may only stay the same or get narrower as stronger anchors appear.
- Once a stronger anchor is available (`path` -> `file` -> `line` -> `symbol`), broader search is forbidden for that same `Missing` unless the anchor was proven wrong.
- After `file#symbol` is known, repo-wide search is forbidden for that same `Missing`.
- After a structured source read (`mcp__probe__extract_code`, AST search, or LSP) establishes a fact, `rg` MUST NOT be used to reconfirm that same fact.
- If two or more exact `file#symbol` targets are already known and all are required to close the current `Missing`, they MUST be fetched in one batched `mcp__probe__extract_code` call unless batching has already failed due to size or tool limits.

## Missing budget

For one active `Missing`, you may use at most:

- 1 bootstrap search when no stable anchor exists yet
- 1 anchored structured read to inspect the most likely owner
- 1 closing follow-up call if it directly resolves producer/consumer/handoff uncertainty

If the `Missing` is still unresolved after this budget, answer with `[gap]`.

Do not switch tool families repeatedly on the same unresolved hypothesis after two misses.

## Pre-call gate

Before every `FETCH`, internally prove all three:

- This call can materially change the final answer.
- No already-available narrower route can close the same `Missing`.
- If this call fails, the next step will be `ANSWER` or `[gap]`, not another exploratory fetch.

If any of the three cannot be proven, do not call the tool.

## Internal decision loop

Before every tool call, internally derive:

- `Goal` — the current user question in one sentence.
- `Facts` — direct code facts already observed.
- `Inference` — what those facts already imply for the Goal.
- `Missing` — exactly one answer-blocking gap.
- `Decision` — `ANSWER` / `FETCH` / `GAP`.

### Grounding rules

- `Facts` may contain only direct evidence already read from code or non-source project files.
- Every `Fact` and every `Inference` must be grounded in specific `file:line` evidence already observed.
- `Inference` must answer as much of the Goal as current evidence already allows before any new fetch is considered.
- If current evidence already answers the Goal, `Decision` MUST be `ANSWER` and no further tool call is allowed.
- `Missing` must be exactly one gap that would make the answer materially wrong if left unresolved.
- Forbidden reasons for `Missing`: `"more complete"`, `"confirm"`, `"double-check"`, `"downstream impact"`, `"one more layer"`, `"while I'm here"`, or any curiosity-driven exploration.
- Before the first tool call, `Facts` and `Inference` may be empty. In that case `Missing` should be `entry point for [concept] is unknown.`
- `GAP` is required when the missing item is not reachable from current evidence without broadening beyond the user's requested boundary. Mark it as `[gap]` in the final answer.

## Stop-on-sufficiency rule

- The query is answerable as soon as you can report the entry location, the in-scope handoff chain, the consumer behavior, and any unresolved required hop as `[gap]`.
- Once those are satisfied, further tool calls are forbidden.

### If `Decision = FETCH`

Internally derive:

- `Candidate capabilities`
- `Chosen capability and concrete tool`
- `Matched scenario from ~/.agents/skills/my-explore/tool.md`
- `Why shortest`
- `Rejected alternative`, if one exists

### Tool-selection rules

- Do not default to a specific tool family.
- Consult `~/.agents/skills/my-explore/tool.md` before every tool call and choose the narrowest scenario whose preconditions are already satisfied.
- Rank candidates by this dominance order:
    1. closes the current `Missing` in fewer calls
    2. uses the strongest existing anchor (`file`, `symbol`, `line`, `literal`, `ID`, or exact path)
    3. returns the most structured and bounded output
    4. searches the smallest scope
    5. has the lowest side effects
    6. avoids repeating a broader search after a narrower anchored route is already available
- Tool switching is allowed only when:
    - the previous tool failed because a required precondition was missing, or
    - new evidence changed `Missing`, and another capability now dominates
- Never switch tools merely to keep exploring the same unresolved need.
- Broad repo search by domain keywords is bootstrap-only until a concrete file, symbol, literal, or path anchor surfaces.
- Repo-wide exact symbol/literal search is allowed only when the file is still unknown and no narrower route exists.
- If a scoped search returns nothing, try at most one alternate term. If that also fails, answer with `[gap]` immediately.
- Prefer batching when one `Missing` requires several tightly coupled exact reads.
- Prefer `file#symbol` over `file:line` when the target is the enclosing function, method, or callback rather than the local AST node at that line.
- 5 tool calls is the normal hard ceiling.
- A 6th call is allowed only if:
    - it directly closes the current `Missing`
    - without it the final answer would be materially wrong
    - and the next step after it is definitely `ANSWER`

## Execution rules

- After every tool result, rerun the internal decision loop before any further tool call.
- Do not print the internal decision loop, scratchpad, routing log, or tool comparison unless the user explicitly asks for the decision process.
- At most one short plain-language preamble is allowed before a batch of tool calls, and only when blocked, requesting approval, or when the next step would otherwise be surprising.
- Visible output must contain only:
    - `Location`
    - `Flow`
    - `Behavior`
    - `[gap]`, when needed
- Never dump raw source.
- For Trace queries, stop at the user's requested boundary; do not follow downstream side effects unless the user asked for them.

## NEVER

- NEVER direct-read source files when a structured source tool can answer the question.
- NEVER use repo-wide browsing after the Goal is already answerable.
- NEVER use `mcp__language_server__get_symbols`.
- NEVER use language-server symbol listing merely to “look around” in a file or the project. Use it only when it directly closes the current `Missing` and dominates alternatives.
- NEVER vary tools repeatedly on the same unresolved hypothesis after two failed attempts. Reframe the `Missing` or answer with `[gap]`.
- NEVER print the internal decision loop unless the user explicitly asks for the decision process.

## Source extraction guard

- Never use `mcp__probe__extract_code` with `file:1`.
- Never use `file:line` when the line is likely to be an import, directive, comment, or trivial node.
- If the target behavior belongs to an enclosing function, method, callback, or class, you MUST switch to `file#symbol`.
