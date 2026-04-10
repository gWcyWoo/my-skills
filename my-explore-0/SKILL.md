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

4.  Before every tool call, MUST print one `Thinking:` line. Every field is MANDATORY.

        Thinking: known=<what data you have>; goal=<what's still missing>; need=<body | callers | file-path | concept-location | references>; tool=<name, exact args, tool.md scenario>; shortest=<why this is the minimum next step>

    If you cannot fill `tool=`, walk through these steps until you can:
    1. What do I already have? (files, symbols, code bodies) → write `known=`
    2. What single piece of data am I missing next? → write `goal=`
    3. What kind of data is that? Pick one:
       - I need the **source body** of a symbol I can name → `need=body` → `tool=extract_code`
       - I need to know **who calls** a symbol → `need=callers` → `tool=LSP findReferences`
       - I need to find **which file** something is in → `need=file-path` → `tool=Glob`
       - I need to find code by **keyword or concept** → `need=concept-location` → `tool=probe search_code`
       - I need **all usages** of a symbol → `need=references` → `tool=LSP findReferences`
    4. If you can name the symbol, always choose `extract_code` over any search tool.
    5. If you need N symbol bodies, batch them: ONE `extract_code files=[...]` call.

5.  Execute the playbook until every item in `<target>` has been reported. Every failed tool call must do exactly one of:
    - Fix bad arguments and retry, or
    - State a new hypothesis and choose the appropriate tool.

    Never switch tools only to "keep trying" the same unresolved need.
    </steps>

<NEVER>
- **NEVER use `Read` on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source always goes through `probe extract_code` (`file#symbol` or `file:line`). `Read` is permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
- **NEVER call LSP `documentSymbol` or `workspaceSymbol`.** These tools are banned — they return massive symbol lists that waste tokens. Use `probe search_code` or `ast-grep find_code` to locate unknown symbols, then `extract_code file#symbol` to get the body.
- **NEVER issue a tool call without the required `Thinking:` line immediately above it.** That is an invalid run.
</NEVER>
