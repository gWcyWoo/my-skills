---
name: my-explore
description: MUST invoke for ALL code exploration tasks — search, find, trace, explain, read, analyze. Dispatches a constrained Explore subagent so the main session never absorbs raw source.
---

Call the `Agent` tool with `subagent_type: "Explore"`, set `name: "explore"` (so the agent can be continued later), and exactly this prompt (substitute `{{QUESTION}}` with the user's question verbatim, change nothing else):

```
Read ~/.claude/skills/my-explore/dispatch-prompt.md and follow its instructions strictly. Treat the QUESTION below as the <query> referenced in that document.

<query>
{{QUESTION}}
</query>
```

**If the returned summary is insufficient**, do NOT dispatch a new Agent and do NOT read source in the main session. Instead, **continue the same subagent** with `SendMessage(to: "explore", message: "<sharper follow-up>")`. The subagent retains its full prior context — file structure, classifications, tool results — so a follow-up only spends what is needed for the missing piece.

Only spawn a fresh Explore agent when the new question is **unrelated** to the prior one.
