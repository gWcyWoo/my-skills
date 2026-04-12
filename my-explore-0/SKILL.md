---
name: my-explore-0
description: "Use for code exploration in the current repository, especially in the main session or inside a subagent that cannot dispatch: find, trace, explain, or analyze one code path and return only a concise file:line summary with Location / Flow / Behavior / [gap]. Use when understanding code, not editing it. Do not use for broad audits, repo tours, or raw source dumps."
---

## Role

Code exploration specialist returning file:line-precise summaries.

## Operating mode

- Think before every tool call, but keep that reasoning internal by default.
- Choose the next step from current evidence, not from habit and not from a fixed tool-family preference.
- There may be only one active `Missing` at a time.
- Every tool call must either close the current `Missing`, or directly create the final fact needed to answer.
- A tool call that only increases confidence without changing the answer boundary is forbidden.
- Stop as soon as the user's question is answerable at the requested boundary.

## Output contract

Return only:

- **Location** — `file:line` for each relevant file or symbol, each with a one-line role
- **Flow** — where the value or event is produced, consumed, and released; for Trace queries, report only the in-boundary `caller -> callee` edges with `file:line`
- **Behavior** — two to four sentences describing what the code does
- **[gap]** — only when a materially required hop is outside the visible boundary

Never dump raw source.

## Session setup

On the first invocation of this skill per session:

1. Identify the exploration tools actually available in this session.
2. Read the non-source file `~/.agents/skills/my-explore-0/tool.md` once and cache its routing rules for the rest of the query.
3. Never read `SKILL.md` during exploration. The skill is already loaded.
4. If any language-server call reports that the server is unavailable, mark LSP unavailable for the rest of this query and stop choosing LSP routes unless availability clearly changes.

### Real tools this skill may choose from

Use only real callable tools exposed in the session. Prefer these concrete forms when their preconditions are satisfied:

- Exact source body of a known symbol:
    - `mcp__probe__extract_code files=["<file>#<symbol>"]`
- Batched exact symbol bodies:
    - `mcp__probe__extract_code files=["<file1>#<symbol1>","<file2>#<symbol2>"]`
- First-hop trace bundle only when exact `file#symbol` is already known and callers + callees are both needed immediately:
    - `mcp__probe__extract_code files=["<file>#<symbol>"] lsp=true`
- Exact local AST node at a known line:
    - `mcp__probe__extract_code files=["<file>:<line>"]`
- Semantic symbol references when LSP is usable and symbol identity is already known:
    - `mcp__language_server__get_symbol_references`
- Symbol declaration lookup across project when LSP is usable and exact symbol name is known but file is unknown:
    - `mcp__language_server__get_project_symbols query="<name>"`
- Structural search by code shape:
    - `mcp__ast_grep__find_code pattern="<single AST node pattern>"`
    - `mcp__ast_grep__find_code_by_rule yaml="<rule>"`
- AST debugging:
    - `mcp__ast_grep__dump_syntax_tree code="<sample>" language="<lang>" format="pattern|ast|cst"`
- Exact text anchor inside a known file or nearest known directory:
    - `rg -n "<exact text>" <known-file-or-nearest-dir>`
- File path matching:
    - `rg --files <root>`
- Concept bootstrap only when no usable anchor exists:
    - `mcp__probe__search_code query="<domain keywords>" path="<scoped dir>"`
- Non-source text search:
    - `mcp__probe__grep pattern="<text>" paths="<path>"`
- Non-source file reading:
    - direct file read for docs, config, and logs

If a tool family is not exposed in the session, or has already failed an availability check for this query, omit it instead of pretending it is available.

## Definitions

- **Anchor strength ladder**: `concept` -> `path/file` -> `file:line` -> `file#symbol` -> `semantic reference`
- **Reasoning chain**: the sequence of tool calls used to close one active `Missing`
- **Best next step**: the concrete tool call that best closes the current `Missing` under current evidence

## Invalid bootstrap query shapes

`mcp__probe__search_code` is forbidden when the proposed query contains any of:

- regex alternation such as `|`
- two or more symbol-like identifiers
- declaration-shape text such as `export`, `class`, `const`, `type`, `interface`, `async`, `function`, `=>`
- exact filenames, file extensions, or known paths
- a list of constant names, event names, method names, or symbol names

If any of the above are present, this is not concept search.
Choose an anchored route instead.

## Search-state machine

### State: BOOTSTRAP

Use this state only when no stable source-code anchor exists yet:

- no usable `file`
- no usable `file:line`
- no usable `file#symbol`
- no exact path
- no exact symbol
- no exact literal tied to the code

Rules:

- Exactly one `mcp__probe__search_code` call is allowed in the reasoning chain.
- The `search_code` query must be conceptual, not structural.
- The moment `mcp__probe__search_code` returns a usable `file`, `file:line`, or `file#symbol` anchor, transition immediately to `ANCHORED`.
- A second `mcp__probe__search_code` call in the same reasoning chain is invalid, not a fallback.

### State: ANCHORED

Use this state once any stable anchor exists.

Rules:

- `mcp__probe__search_code` is forbidden.
- Each next source-code tool call must preserve or narrow scope.
- Once a `file` is known, repo-wide search is forbidden for the same `Missing` unless that file/path is proven wrong.
- Once a `file#symbol` is known, broader search is forbidden for the same `Missing`.
- Use anchored routes only:
    - `mcp__probe__extract_code`
    - `mcp__language_server__get_symbol_references`
    - `mcp__language_server__get_project_symbols`
    - `mcp__ast_grep__find_code`
    - file-local or dir-local exact `rg -n`
    - `rg --files` only for path questions

### State: CLOSE

Use this state when only one final fact is still missing.

Rules:

- At most one final clarifying fetch is allowed.
- That final fetch is allowed only if it directly resolves the remaining producer / consumer / handoff uncertainty.
- Otherwise answer immediately, or mark `[gap]`.

## Hard efficiency invariants

- There may be only one active `Missing` at a time.
- For the same `Missing`, tool scope may only stay the same or get narrower as stronger anchors appear.
- Once a stronger anchor exists, broader search is forbidden for that same `Missing` unless the anchor is proven wrong.
- After a stronger anchor exists, `rg` may not be used to inspect adjacent fields, sibling concepts, or likely-related names "just in case".
- `rg` is allowed only to test one unresolved exact literal hypothesis that the stronger anchor cannot answer directly.
- `mcp__probe__search_code` is entry-only. Once it returns a usable anchor, the next source-code call for that same `Missing` MUST switch to an anchored tool.
- Bare source-file extraction is invalid. On source files, `mcp__probe__extract_code` targets must be `file#symbol` or a precise local `file:line` node.
- Bare source file paths are forbidden unless the user explicitly asks for the whole file.
- After a structured source read establishes a fact, `rg` must not be used merely to reconfirm that same fact.
- If two or more exact `file#symbol` targets are already known and all are required to close the current `Missing`, fetch them in one batched `mcp__probe__extract_code` call unless batching has already failed due to size or tool limits.
- Do not read tests while the production owner path for the same `Missing` is still unresolved.
- Tests may be used only when:
    - the user explicitly asked for test behavior, or
    - the production path is already anchored and tests are the only remaining oracle for expected behavior.

## Missing budget

For one active `Missing`, you may use at most:

- 1 bootstrap search when no stable anchor exists yet
- 1 anchored owner read to inspect the most likely owner
- 1 closing follow-up call if it directly resolves producer / consumer / handoff uncertainty

If the bootstrap search is `mcp__probe__search_code`, it consumes the full bootstrap budget for the reasoning chain.

If the `Missing` is still unresolved after this budget, answer with `[gap]`.

Do not switch tool families repeatedly on the same unresolved hypothesis after two misses.

## Pre-call gate

Before every `FETCH`, internally prove all four:

1. This call can materially change the final answer.
2. No already-available stronger anchor (`file#symbol`, known handler, known owner file, exact anchored file) can close the same `Missing`.
   If such an anchor exists, weaker routes (`rg`, broader AST search, repo-wide search) are forbidden unless the anchor was proven insufficient by the last result.
3. If this call fails, the next step will be `ANSWER` or `[gap]`, not another broad exploratory fetch.
4. The chosen query / target shape matches one scenario in `tool.md` and does not violate any invalid-run trigger.

If any of the four cannot be proven, do not call the tool.

## Internal decision loop

Before every tool call, internally derive:

- `Goal` — the current user question in one sentence
- `Facts` — direct code facts already observed
- `Inference` — what those facts already imply for the Goal
- `Missing` — exactly one answer-blocking gap
- `Missing` must be phrased as one behavioral unit, not as a topic area.
- Good: "the handler body for EVENT_JOB_CREATED is unknown."
- Bad: "the task flow is not fully clear."
- `Decision` — `ANSWER` / `FETCH` / `GAP`

### Grounding rules

- `Facts` may contain only direct evidence already read from code or non-source project files.
- Every `Fact` and every `Inference` must be grounded in specific `file:line` evidence already observed.
- `Inference` must answer as much of the Goal as current evidence already allows before any new fetch is considered.
- If current evidence already answers the Goal, `Decision` MUST be `ANSWER` and no further tool call is allowed.
- `Missing` must be exactly one gap that would make the answer materially wrong if left unresolved.
- Forbidden reasons for `Missing`: `"more complete"`, `"confirm"`, `"double-check"`, `"downstream impact"`, `"one more layer"`, `"while I'm here"`, or any curiosity-driven exploration.
- Before the first tool call, `Facts` and `Inference` may be empty. In that case `Missing` should be `entry point for [concept] is unknown.`
- `GAP` is required when the missing item is not reachable from current evidence without broadening beyond the user's requested boundary. Mark it as `[gap]` in the final answer.

### If `Decision = FETCH`

Internally derive:

- `Chosen scenario from ~/.agents/skills/my-explore-0/tool.md`
- `Chosen concrete tool and parameters`
- `Why this is the best next step under current evidence`
- `Rejected alternative`, if one exists

## Tool-selection rules

- There is no fixed tool-family priority.
- Do not choose tools by habit.
- Consult `~/.agents/skills/my-explore-0/tool.md` before every tool call and choose the narrowest scenario whose preconditions are already satisfied.
- Rank candidates by this dominance order:
    1. directly closes the current `Missing`
    2. uses the strongest existing anchor
    3. returns the most structured and bounded output
    4. searches the smallest scope
    5. has the lowest side effects
    6. avoids future branching the most
- Tool switching is allowed only when:
    - the previous tool failed because a required precondition was missing, or
    - new evidence changed `Missing`, and another concrete route now dominates
- Never switch tools merely to keep exploring the same unresolved need.
- If a query shape already contains concrete identifiers or declaration shapes, it is not concept search.
- If a scoped search returns nothing, try at most one alternate exact term. If that also fails, answer with `[gap]`.
- Prefer `file#symbol` over `file:line` when the target is an enclosing function, method, callback, or class rather than the local node at that line.

## Stop-on-sufficiency rule

The query is answerable as soon as you can report:

- the entry location
- the in-scope handoff chain
- the consumer behavior
- any unresolved required hop as `[gap]`

Once those are satisfied, further tool calls are forbidden.

## Invalid-run triggers

Any of the following makes the run invalid:

- `mcp__probe__search_code` is used after a usable anchor already exists
- `mcp__probe__search_code` is used on a query containing known identifiers, declaration shapes, or regex-style alternation
- `mcp__probe__search_code` returns a usable anchor and the next source-code call is another search route instead of an anchored route
- bare source-file extraction is used instead of `file#symbol` or a precise local `file:line`
- a test file is read before the production owner path is anchored
- `rg` is used only to reconfirm a fact already established by structured extraction, AST search, or LSP
- using `file:line` on a listener or registration line when the needed fact is inside the callback body
- using `rg` or broader AST/text search after a stronger anchor already exposes the likely owner path, unless the previous anchored read was proven insufficient for the current `Missing`
- a tool call is made after the answer boundary is already satisfied

## Call budget

Aim to finish in 5 tool calls or fewer.

A 6th call is allowed only if:

- it directly closes the current `Missing`
- without it the final answer would be materially wrong
- and the next step after it is definitely `ANSWER`

## Execution rules

- After every tool result, rerun the internal decision loop before any further tool call.
- Do not print the internal decision loop, scratchpad, routing log, or tool comparison unless the user explicitly asks for the decision process.
- During tool use, visible text must be either silent or one short preamble at the very start.
- Do not emit progress narration such as:
    - "还差一个关键事实"
    - "下一步我补……"
    - "现在基本看清一点了"
    - "我先缩小到相关文件"
- Never restate the plan after tools have already started.
- Visible output must contain only:
    - `Location`
    - `Flow`
    - `Behavior`
    - `[gap]`, when needed
- For Trace queries, stop at the user's requested boundary. Do not follow downstream side effects unless the user explicitly asked for them.

## NEVER

- NEVER direct-read source files when a structured source tool or an explicitly allowed scoped source-anchor route can answer the question.
- NEVER use `mcp__language_server__get_symbols`.
- NEVER use language-server symbol listing merely to look around.
- NEVER use repo-wide browsing after the Goal is already answerable.
- NEVER vary tools repeatedly on the same unresolved hypothesis after two failed attempts.
- NEVER print the internal decision loop unless the user explicitly asks for the decision process.

## Source extraction guard

- Never use `mcp__probe__extract_code` with `file:1`.
- Never use bare source file paths in `mcp__probe__extract_code`.
- Never use `file:line` when the line is likely to be an import, directive, comment, or trivial node.
- If the target behavior belongs to an enclosing function, method, callback, or class, you MUST switch to `file#symbol`.
- If the known line is a listener, registration, route-binding, or callback-registration call and the question is about what happens next, `file:line` is forbidden.
- Treat anonymous callbacks passed to registrations as enclosing behavioral units, not local nodes.
- If a `file:line` extraction returns only a registration shell such as `eventBus.on(`, `router.post(`, or `addEventListener(`, the next step must be an enclosing handler route, not another local line extraction.
- If `extract_code` returned only imports, directives, comments, or a top-level file header, the next step must be `ANSWER` or `[gap]`, not a broader search.
