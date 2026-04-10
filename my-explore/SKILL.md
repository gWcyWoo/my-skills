---
name: my-explore
description: MUST invoke for ALL code exploration tasks in Codex — search, find, trace, explain, read, analyze. Dispatches a constrained exploration subagent through `my-subagent` so the main session never absorbs raw source.
---

<role>
You are the **my-explore dispatcher**, executing in the **main session**. Your only job is to dispatch the constrained exploration subagent and relay its structured summary back to the caller. You never read source code yourself, and you never investigate code in the main session.
</role>

<context>
**Why this dispatcher exists.** Code exploration is high-volume: many tool calls, many file reads, many false starts. Doing it in the main session pollutes context with raw source and tool noise. So all exploration is delegated to an isolated subagent via `my-subagent`. The subagent runs the full exploration playbook in `~/.agents/skills/my-explore/dispatch-prompt.md` and returns a structured `file:line` summary, never raw source.

**Continuation pattern.** Keep the returned `agent_id`. For follow-up questions on the SAME topic, send a new message to that same agent via `send_input`. The agent retains its full prior context, so a follow-up only spends what is needed for the missing piece. Spawn a fresh agent only when the new question is genuinely unrelated to the prior one.

**When to use `my-explore-0` instead.** If you are running inside a subagent yourself, you cannot recursively dispatch. Use the `my-explore-0` skill instead. It runs the same playbook directly in your current session.
</context>

<instructions>
1. Invoke the `my-subagent` skill with these exact effective inputs:
   - `agent_type: "explorer"`
   - `task_prompt`: the template defined in the `## Subagent prompt template` section below, with `{{QUESTION}}` substituted by the user's exploration query verbatim. Change no other text.
   - `model: "gpt-5.4"`
2. Wait for the subagent to return its structured summary.
3. Relay the summary back to the caller **verbatim**. Do not paraphrase, do not supplement with your own observations, and do not read any source files yourself.
4. **If the caller asks a follow-up on the SAME topic** (clarification, deeper drill, "and what calls X?"): do not dispatch a new subagent, and do not read source in the main session. Instead, continue the same subagent via `send_input` on the saved `agent_id`. Repeat from step 2 with the new summary.
5. **Only if the new question is genuinely unrelated** to the prior one should you spawn a fresh exploration subagent by going back to step 1.
6. The dispatched subagent MUST follow `~/.agents/skills/my-explore/dispatch-prompt.md` exactly, including the hard rule that every tool call is immediately preceded by the required `→ <tool> <target> (need: <what>; miss → <fallback>)` line. If that rule is violated, the exploration run is invalid.
</instructions>

<input>
- {{QUESTION}}: the user's exploration query, passed verbatim from the caller.
</input>

## Subagent prompt template

This is the prompt the dispatcher sends through `my-subagent` in step 1. Substitute `{{QUESTION}}` with the user's query verbatim. **Do not modify any other text**.

```text
Read ~/.agents/skills/my-explore/dispatch-prompt.md and follow its instructions strictly. Treat the QUESTION below as the <query> referenced in that document.

You are running inside Codex. For source-code exploration, use only the Codex toolset referenced by that document:
- `mcp__probe__extract_code`
- `mcp__probe__search_code`
- `mcp__ast_grep__find_code`
- `mcp__ast_grep__find_code_by_rule`
- `mcp__ast_grep__dump_syntax_tree`
- `mcp__language_server__*`
- `rg -n` for non-source text or a first scoped anchor only

Do NOT use built-in `Read` / built-in `Search` / `cat` / `head` / `tail` / `sed` on source code. Do NOT do MCP resource discovery before exploration.

<query>
{{QUESTION}}
</query>
```

<examples>
<example>
SCENARIO: Caller asks "What does the handleSubmit function in classroom/page.tsx do?"
ACTIONS:
  1. Invoke `my-subagent` with `agent_type: "explorer"`, `model: "gpt-5.4"`, and the prompt template above.
  2. The subagent returns: Files / Symbols / Behavior / Confidence, all with `file:line` precision and no raw source.
  3. Relay the summary verbatim to the caller. Done.
</example>

<example>
SCENARIO: After the above, caller asks "and what calls handleSubmit?"
ACTIONS:
  1. Recognize same topic and continue the same `agent_id` via `send_input`.
  2. The subagent returns call edges from language-server references, with `file:line`.
  3. Relay verbatim. Done.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Reading `classroom/page.tsx` in the main session "to get a quick look first." Never.
ANTI-PATTERN B: Spawning a new exploration subagent for the follow-up instead of continuing the same `agent_id`.
ANTI-PATTERN C: Paraphrasing or "improving" the subagent's summary before relaying it.
ANTI-PATTERN D: Modifying the prompt template's wording, other than substituting `{{QUESTION}}`.
ANTI-PATTERN E: Bypassing `my-subagent` and calling `spawn_agent` directly.
</example>
</examples>

<output_format>
The dispatcher returns to its caller **exactly** what the subagent returned, verbatim. No additional commentary, no summarization, no synthesis. For reference, the subagent's `<output_format>` is defined in `~/.agents/skills/my-explore/dispatch-prompt.md`:

Files:      path:line per relevant location
Symbols:    name at file:line, one-line role each
Behavior:   2–4 sentences on what the code does
Call edges: caller → callee with file:line   (Trace queries only)
Confidence: high | medium | low, with the gap if not high
</output_format>

<success_criteria>
The dispatch is complete when ALL of these hold:
- The exploration subagent was invoked through `my-subagent`.
- The exploration subagent followed `dispatch-prompt.md`, including the required commitment line immediately above every tool call.
- The subagent returned a structured summary with all applicable `<output_format>` slots filled.
- The summary was relayed to the caller verbatim, without paraphrasing or supplementing.
- No source code was read in the main session by the dispatcher itself.

Stop the moment those hold. For follow-ups on the same topic, continue the same `agent_id`. Do not re-run step 1.
</success_criteria>

<final_reminders>
P0 — Main session NEVER reads source code. All source goes through the subagent.
P0 — Use `my-subagent`. Never bypass it with direct child-agent calls.
P0 — Pass the prompt template VERBATIM. Only substitute `{{QUESTION}}`.
P0 — The subagent's tool calls are invalid unless each one is immediately preceded by the required `→ <tool> <target> (need: <what>; miss → <fallback>)` line from `dispatch-prompt.md`.
P0 — Relay the subagent's summary verbatim to the caller. No paraphrasing, no synthesis.
P1 — Follow-up on same topic means `send_input` to the existing `agent_id`, not a new subagent.
P1 — Spawn a fresh exploration subagent only when the new question is genuinely unrelated to the prior one.
P1 — If you are already inside a subagent, abort this dispatcher and use `my-explore-0` instead.
</final_reminders>
