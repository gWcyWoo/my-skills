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

3.  Classify the query and emit a three-line plan block before the first tool call:

        Classification: <Pinpoint | Trace | Discovery | Structural>
        Evidence: "<exact words from the query that determine the type>"
        Plan: <one-sentence first action>

    Classification rules — each rule names the playbook you MUST read for this query:
    - A specific symbol, file, or UI label is named → **Pinpoint** → MUST read ~/.claude/skills/my-explore/pinpoint.md
    - The query asks how data or control flows from A to B → **Trace** → MUST read ~/.claude/skills/my-explore/trace.md
    - Only abstract concepts appear; nothing is named → **Discovery** → MUST read ~/.claude/skills/my-explore/discovery.md
    - "Find all code matching pattern P" → **Structural** → MUST read ~/.claude/skills/my-explore/structural.md
    - Domain words alone (e.g. "rate limiting") are insufficient for Pinpoint — treat as Discovery.

4.  Before every tool call, Must print a three-line data block that commits you to one `tool.md` scenario:

    Have: <data already in hand — file path, symbol name, partial output, or "nothing yet">
    Want: <data needed next — symbol body, file outline, call sites, etc.>
    Via: <the exact <intent> from tool.md that supplies Want>

5.  until every item in `<target>` has been reported. Stop immediately — do not run "one more check".
    </steps>

<NEVER>
- **NEVER use `Read` on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source always goes through `probe extract_code` (`file#symbol` or `file:line`). `Read` is permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
</NEVER>
