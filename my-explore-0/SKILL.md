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
1. On the first invocation of this skill per session, you MUST identify the available Codex exploration tool families for this session:

       `mcp__probe__*`
       `mcp__ast_grep__*`
       `mcp__language_server__*`
       `rg -n` for non-source text or a first scoped anchor only

2.  On the first invocation of this skill per session, you MUST read `~/.agents/skills/my-explore/tool.md`. Reuse it on follow-up turns.

3.  Classify the query and emit a one-line classification before the first tool call:

        ⊕ <Pinpoint|Trace|Discovery|Structural>: "<evidence>" → <first action>

    Classification rules — each rule names the playbook you MUST read for this query:
    - A specific symbol, file, or UI label is named → **Pinpoint** → MUST read `~/.agents/skills/my-explore/pinpoint.md`
    - The query asks how data or control flows from A to B → **Trace** → MUST read `~/.agents/skills/my-explore/trace.md`
    - Only abstract concepts appear; nothing is named → **Discovery** → MUST read `~/.agents/skills/my-explore/discovery.md`
    - "Find all code matching pattern P" → **Structural** → MUST read `~/.agents/skills/my-explore/structural.md`
    - Domain words alone (e.g. "rate limiting") are insufficient for Pinpoint — treat as Discovery.

4.  Before every tool call, MUST print one structured `Thinking:` line:

        Thinking: state=<current>; need=<what>; action=<tool> <target>; hit=<next>; miss=<fallback>

    This line is a hard precondition for the tool call itself.
    - The tool call is invalid unless it is immediately preceded by exactly one such `Thinking:` line.
    - Do not place any prose, summary, separator, or extra commentary between the `Thinking:` line and the tool call.
    - If a tool call happens without that line, treat the run as invalid and restart from the missing thinking step.

5.  Execute the playbook until every item in `<target>` has been reported. Every failed tool call must do exactly one of:
    - Fix bad arguments and retry, or
    - State a new hypothesis and choose the appropriate tool.

    Never switch tools only to "keep trying" the same unresolved need.
    </steps>

<NEVER>
- **NEVER use direct file reads on source files** (`.ts/.tsx/.js/.jsx/.py/.go/.rs/.java/.rb/.php/.c/.cpp/.swift/.kt/.vue/.svelte`). Source always goes through `mcp__probe__extract_code` (`file#symbol` or `file:line`). Direct reads are permitted only for non-source files (`.md/.json/.yaml/.toml/.txt`, configs, logs).
- **NEVER issue a tool call without the required `Thinking: state=<current>; need=<what>; action=<tool> <target>; hit=<next>; miss=<fallback>` line immediately above it.** That is an invalid run.
</NEVER>
