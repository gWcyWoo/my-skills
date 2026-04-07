---
name: my-explore
description: MUST invoke for ALL code exploration tasks in Codex — search, find, trace, explain, read, analyze. Dispatches a constrained subagent via my-subagent so the main session never absorbs raw source.
---

# My Explore (Codex)

For ANY code exploration task, dispatch the work to an isolated subagent using the `my-subagent` skill. The main session must NOT read source code directly.

## How to dispatch

Invoke the `my-subagent` skill with these inputs (substitute `{{QUESTION}}` with the user's verbatim question, change nothing else):

- `agent_type`: `default`
- `task_prompt`:

```
Read ~/.agents/skills/my-explore/dispatch-prompt.md and follow its instructions strictly. Treat the QUESTION below as the <query> referenced in that document.

You are running inside Codex. You MUST use only the Codex tool whitelist defined in dispatch-prompt.md:
- `rg -n` via shell (literal/text anchors only)
- `mcp__probe__search_code`, `mcp__probe__extract_code`
- `mcp__ast_grep__find_code`, `mcp__ast_grep__find_code_by_rule`, `mcp__ast_grep__dump_syntax_tree`, `mcp__ast_grep__test_match_code_rule`
- `mcp__language_server__*` navigation tools

Do NOT use built-in Read / Search / Grep / cat / head / tail / sed on source code. Do NOT call any MCP "list resources / load templates" step before exploration.

<query>
{{QUESTION}}
</query>
```

Follow the my-subagent parent workflow exactly: spawn with `fork_context: false`, poll with `wait_agent` every 120 seconds, respect the liveness rules, and only close on terminal status.

## Follow-up / refinement

**If the returned summary is insufficient, do NOT spawn a new subagent and do NOT read source in the main session.** Instead, send a sharper follow-up to the same `agent_id` via `send_input` (per my-subagent's clarification/resume rules). The subagent retains its full prior context — file structure, classifications, tool results — so a follow-up only spends what is needed for the missing piece.

Only spawn a fresh subagent when the new question is **unrelated** to the prior one.
