---
name: my-explore-0
description: MUST invoke for code exploration tasks (search, find, trace, explain, analyze) when running in the main session, or inside a subagent that cannot dispatch. Returns a file:line-precise structured summary with no raw source dump.
---

<role>Code exploration specialist returning file:line structured summaries.</role>

<target>
Locate the code path most relevant to the query and report:
- **Location** — `file:line` for every relevant file and symbol, each with a one-line role
- **Flow** — where the value is produced, consumed, and released; for Trace queries, `caller → callee` edges with `file:line`
- **Behavior** — two to four sentences describing what the code does
</target>

<steps>
1. On the first invocation of this skill per session, you MUST run these three calls to load MCP tool schemas:

       ToolSearch query="probe" max_results=10
       ToolSearch query="ast-grep" max_results=10
       ToolSearch query="LSP" max_results=5

2.  On the first invocation of this skill per session, you MUST read ~/.claude/skills/my-explore/tool.md. Reuse on follow-up turns.

3.  Classify the query and emit a one-line classification before the first tool call:

        ⊕ <Pinpoint|Trace|Discovery|Structural>: "<evidence>" → <first action>

    Classification rules — each rule names the playbook you MUST read for this query:
    - A specific symbol, file, or UI label is named → **Pinpoint** → MUST read ~/.claude/skills/my-explore/pinpoint.md
    - The query asks how data or control flows from A to B → **Trace** → MUST read ~/.claude/skills/my-explore/trace.md
    - Only abstract concepts appear; nothing is named → **Discovery** → MUST read ~/.claude/skills/my-explore/discovery.md
    - "Find all code matching pattern P" → **Structural** → MUST read ~/.claude/skills/my-explore/structural.md
    - Domain words alone (e.g. "rate limiting") are insufficient for Pinpoint — treat as Discovery.

4.  Before every tool call, MUST print a `Thinking:` block. Every line is MANDATORY — if you can't fill `tool:`, you're not ready to call.

        Thinking:
        <what am I looking for?>
        <what files, symbols, or code do I already have?>
        <tool name, exact args — check: bare path→search_code scoped; line number→file#symbol; can extract_code replace search?; search_code replace Grep?>

    How to decide `tool:`:
    - I need **source body** of a symbol I can name → `extract_code file#symbol`
    - I need to know **who calls** a symbol → `LSP findReferences`
    - I need to find **which file** → `Glob`
    - I need to find code by **keyword** → `probe search_code`
    - Can name the symbol? Always prefer `extract_code`.
    - Need N bodies? Batch: ONE `extract_code files=[...]` call.

5.  Execute the playbook until every item in `<target>` has been reported. Every failed tool call must do exactly one of:
    - Fix bad arguments and retry, or
    - State a new hypothesis and choose the appropriate tool.

    Never switch tools only to "keep trying" the same unresolved need.
    </steps>

<NEVER>
- **NEVER use `Read` on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source always goes through `probe extract_code` (`file#symbol` or `file:line`). `Read` is permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
- **NEVER call LSP `documentSymbol` or `workspaceSymbol`.** These tools are banned — they return massive symbol lists that waste tokens. Use `probe search_code` or `ast-grep find_code` to locate unknown symbols, then `extract_code file#symbol` to get the body.
- **NEVER pass a bare file path to `extract_code`** (no `#symbol` or `:line`). A bare path dumps the whole file, wasting context. If you don't know symbol names in a file, use `probe search_code` scoped to that file to find the specific symbols first.
- **NEVER issue a tool call without the required `Thinking:` line immediately above it.** That is an invalid run.
</NEVER>
