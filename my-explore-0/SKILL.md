---
name: my-explore-0
description: MUST invoke for code exploration tasks (search, find, trace, explain, analyze) when running in the main session, or inside a subagent that cannot dispatch. Returns a file:line-precise structured summary with no raw source dump.
---

<role>Code exploration specialist returning file:line structured summaries.</role>

<target>
Locate the code path most relevant to the query and report:
- **Location** — `file:line` for every relevant file and symbol, each with a one-line role
- **Flow** — where the value is produced, consumed, and released; for Trace queries, report only the in-boundary `caller → callee` edges with `file:line`
- **Behavior** — two to four sentences describing what the code does
</target>

<steps>
1. On the first invocation of this skill per session, you MUST identify the available Codex exploration tool families for this session:

       `mcp__probe__*`
       `mcp__ast_grep__*`
       `mcp__language_server__*`
       `rg -n` for non-source text or a first scoped anchor only

2.  On the first invocation of this skill per session, you MUST read `~/.agents/skills/my-explore/tool.md`. Reuse it on follow-up turns.

3.  Before every tool call, MUST print exactly one `Thinking` block:

        Goal: <the user's question in one sentence>
        Missing: <what you still don't know to answer the goal>

        Thinking:
        - From <file:line>: <what this tells us> → Missing updates: <what is no longer missing>
        - From <file:line> + <file:line>: <combined inference> → can now confirm <conclusion>
        - ... (keep deriving until no more conclusions can be drawn from data you already read)
        - STUCK: <the specific thing you need that cannot be derived from any code already read>

        Decision: ANSWER / FETCH / GAP
        (if FETCH):
        Tool: <chosen tool>(key params)
        Rejected: <alternative tool>(key params) | none
        Reason: chosen matches tool.md scenario: "<quote the matching scenario>"; reject <alternative tool or none> because <specific reason tied to tool.md, NEVER rules, scope fit, or token cost>

    Rules:
    - Every Thinking line must reference a specific `file:line` from code you already read. No citation, no derivation.
    - Keep deriving until no more conclusions can be drawn. Do not stop after one line.
    - STUCK must name ONE specific thing with a concrete symbol reference. "I need more context" is not valid.
    - ANSWER: Thinking is enough to answer Goal → write the answer, no more tool calls.
    - FETCH: STUCK names a concrete symbol that literally appears in code you already read → tool call to get it.
    - GAP: STUCK names something not visible in any code you already read → mark [gap], do not search.
    - `Rejected` must name one plausible alternative if one exists; otherwise write `none`.
    - `Reason` must justify both sides: why the chosen tool fits and why the rejected alternative loses. Generic claims like "better", "simpler", or "more appropriate" are invalid.
    - Before the first tool call, you have no code data yet — STUCK should be "entry point for [concept] is unknown."
    - Concept search (`mcp__probe__search_code`) is only allowed for the first tool call (bootstrap). After that, all FETCH targets must come from symbols in read code.
    - If a search returns nothing, try ONE alternative term. If that also fails, it's a GAP.
    - Batch when possible: if Thinking identifies multiple FETCH targets, use ONE `mcp__probe__extract_code files=[...]` call.
    - Prefer `file#symbol` over `file:line` for extract_code. `file:line` returns the node at that line; `file#symbol` returns the full function body.
    - Maximum 5 tool calls. If you hit 5, stop and ANSWER with what you have.

4.  Execute until every item in `<target>` has been reported. Every failed tool call must do exactly one of:
    - Fix bad arguments and retry, or
    - State a new hypothesis and choose the appropriate tool.

    Never switch tools only to "keep trying" the same unresolved need.

<NEVER>
- **NEVER use direct file reads on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source always goes through `mcp__probe__extract_code` (`file#symbol` or `file:line`). Direct reads are permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
- **NEVER call `mcp__language_server__get_symbols` or `mcp__language_server__get_project_symbols`.** These tools are banned — they return massive symbol lists that waste tokens. Use `mcp__probe__search_code` or `mcp__ast_grep__find_code` to locate unknown symbols, then `mcp__probe__extract_code file#symbol` to get the body.
- **NEVER issue a tool call without the required `Thinking` block immediately above it.** That is an invalid run.
- **NEVER use `Thinking` as a fill-in form.** Every line must reference concrete `file:line` and derive a specific conclusion.
</NEVER>
