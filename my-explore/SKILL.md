---
name: my-explore
description: MUST invoke for ALL code exploration tasks — search, find, trace, explain, read, analyze. Dispatches the custom `my-explore` subagent (defined at ~/.claude/agents/my-explore.md, with Bash/Edit/Write physically removed by the tool whitelist) so the main session never absorbs raw source.
---

<role>
You are the **my-explore dispatcher**, executing in the **main session**. Your only job is to dispatch the constrained `my-explore` subagent and relay its structured summary back to the caller. You never read source code yourself, and you never investigate code in the main session.
</role>

<context>
**Why this dispatcher exists.** Code exploration is high-volume — many tool calls, many file reads, many false starts. Doing it in the main session pollutes context with raw source and tool noise. So all exploration is delegated to a custom subagent (`~/.claude/agents/my-explore.md`) that has a strict tool whitelist:

- **Removed by harness (not in subagent inventory):** `Bash`, `Edit`, `Write`, `Agent`, `WebFetch`, `WebSearch`, etc.
- **Available to subagent:** `Read` (non-source only), `Glob`, `Grep`, `LSP`, `mcp__probe__*`, `mcp__ast-grep__*`.

The subagent runs the full exploration playbook in `~/.claude/skills/my-explore/dispatch-prompt.md` and returns a structured `file:line` summary — never raw source.

**Continuation pattern.** The dispatched agent is named `"explore"`. For follow-up questions on the SAME topic, send a new message to that named agent via `SendMessage(to: "explore", ...)`. The agent retains its full prior context (file structure, classifications, tool results), so a follow-up only spends what is needed for the missing piece. Spawn a fresh agent ONLY when the new question is genuinely unrelated to the prior one (different feature, different concern, different file area).

**When to use `my-explore-0` instead.** If you are running inside a subagent yourself, you cannot recursively dispatch — use the `my-explore-0` skill instead. It runs the same playbook directly in your current session. **Detection: if the `Agent` tool is missing from your tool inventory, you are inside a subagent.**
</context>

<instructions>
1. Call the `Agent` tool with these exact parameters:
   - `subagent_type: "my-explore"` — references the custom subagent at `~/.claude/agents/my-explore.md`. Do NOT use the built-in `"Explore"`; it has `Bash` and the model will fall back to `find`/`ls`/`cat`.
   - `name: "explore"` — the named handle for follow-ups via `SendMessage`.
   - `model: "opus"` — explicitly pin to Opus 4.6. Redundant with the agent frontmatter (`model: opus`) and the global env var (`CLAUDE_CODE_SUBAGENT_MODEL=opus`), but belt-and-suspenders: if either of those layers is later removed or overridden, the explicit invocation parameter keeps Opus in force. Prevents silent regression to Sonnet (which has capacity constraints).
   - `prompt`: the template defined in the `## Subagent prompt template` section below, with `{{QUESTION}}` substituted by the user's exploration query verbatim. Change no other text.
2. Wait for the subagent to return its structured summary.
3. Relay the summary back to the caller **verbatim** — do NOT paraphrase, do NOT supplement with your own observations, and do NOT read any source files yourself.
4. **If the caller asks a follow-up on the SAME topic** (clarification, deeper drill, "and what calls X?"): do NOT call `Agent` again, and do NOT read source in the main session. Instead, continue the same subagent via `SendMessage(to: "explore", message: "<sharper follow-up>")`. Repeat from step 2 with the new summary.
5. **Only if the new question is genuinely unrelated** to the prior one (different feature area, different concern): spawn a fresh `my-explore` agent by going back to step 1.
</instructions>

<input>
- {{QUESTION}}: the user's exploration query, passed verbatim from the caller.
</input>

## Subagent prompt template

This is the prompt the dispatcher sends to the `my-explore` subagent in step 1. Substitute `{{QUESTION}}` with the user's query verbatim. **Do not modify any other text** — the subagent's behavior depends on the exact wording.

```
Read ~/.claude/skills/my-explore/dispatch-prompt.md and follow its instructions strictly. Treat the QUESTION below as the <query> referenced in that document.

<query>
{{QUESTION}}
</query>
```

<examples>
<example>
SCENARIO: Caller asks "What does the handleSubmit function in classroom/page.tsx do?"
ACTIONS:
  1. Agent({subagent_type: "my-explore", name: "explore", model: "opus", prompt: <template with QUESTION substituted>}).
  2. Subagent returns: Files / Symbols / Behavior / Confidence — all `file:line` precision, no raw source.
  3. Relay summary verbatim to caller. Done.
</example>

<example>
SCENARIO: After the above, caller asks "and what calls handleSubmit?"
ACTIONS:
  1. Recognize same topic → SendMessage(to: "explore", message: "What calls handleSubmit?")
  2. Subagent returns: Call edges from LSP `findReferences`, with file:line. Cheap, because the prior agent already located handleSubmit.
  3. Relay verbatim. Done.
</example>

<example label="BAD — do not do this">
ANTI-PATTERN A: Reading `classroom/page.tsx` with the `Read` tool in the main session "to get a quick look first." Never. The whole point of the dispatcher is to keep source out of main.
ANTI-PATTERN B: Spawning a new `my-explore` agent for the follow-up "what calls handleSubmit?" instead of `SendMessage`. The named agent's prior context is wasted, and you pay the bootstrap cost again.
ANTI-PATTERN C: Paraphrasing or "improving" the subagent's summary before relaying it. Pass it through verbatim.
ANTI-PATTERN D: Modifying the prompt template's wording (other than substituting `{{QUESTION}}`). The subagent's behavior depends on the exact wording.
ANTI-PATTERN E: Using `subagent_type: "Explore"` (built-in) instead of `"my-explore"` (custom). The built-in still has `Bash` — the whole point of the custom one is that it doesn't.
</example>
</examples>

<output_format>
The dispatcher returns to its caller **exactly** what the subagent returned, verbatim. No additional commentary, no summarization, no synthesis. For reference, the subagent's `<output_format>` (defined in `~/.claude/skills/my-explore/dispatch-prompt.md`) is:

Files:      path:line per relevant location
Symbols:    name at file:line, one-line role each
Behavior:   2–4 sentences on what the code does
Call edges: caller → callee with file:line   (Trace queries only)
Confidence: high | medium | low, with the gap if not high
</output_format>

<success_criteria>
The dispatch is complete when ALL of these hold:
- The `Agent` tool was called with `subagent_type: "my-explore"`, `name: "explore"`, and `model: "opus"`.
- The subagent returned a structured summary with all applicable `<output_format>` slots filled.
- The summary was relayed to the caller verbatim, without paraphrasing or supplementing.
- No source code was read in the main session by the dispatcher itself.

Stop the moment those hold. For follow-ups on the same topic, use `SendMessage(to: "explore", ...)` — do NOT re-run step 1.
</success_criteria>

<final_reminders>
P0 — Main session NEVER reads source code. All source goes through the subagent. If you find yourself wanting to `Read` a `.ts`/`.py`/etc. file in main, STOP — that is the subagent's job, not yours.
P0 — Use `subagent_type: "my-explore"` (custom). NEVER use the built-in `"Explore"` — it still has `Bash` in its tool inventory and the model will fall back to `find`/`ls`/`cat`.
P0 — Set `name: "explore"` so the agent can be continued via `SendMessage`.
P0 — Pass the prompt template VERBATIM. Only substitute `{{QUESTION}}`. The subagent's behavior depends on the exact wording.
P0 — Relay the subagent's summary verbatim to the caller. No paraphrasing, no synthesis, no "let me also add...".
P1 — Follow-up on same topic → `SendMessage(to: "explore", message: "...")`. Do NOT spawn a new agent.
P1 — Spawn a fresh `my-explore` agent ONLY when the new question is genuinely unrelated to the prior one.
P1 — If you are running inside a subagent yourself (detection: the `Agent` tool is missing from your inventory), you CANNOT dispatch. **Abort this skill** by: (1) NOT calling `Agent` (the call would fail anyway), (2) telling your caller *"I am inside a subagent and cannot dispatch — please use the `my-explore-0` skill instead, which runs the same playbook in the current session"*, and (3) exiting this skill without producing the dispatcher's `<output_format>`. This is a hard execution prerequisite, not a stylistic preference.
</final_reminders>
