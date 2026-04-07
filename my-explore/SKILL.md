---
name: my-explore
description: MUST invoke for ALL code exploration tasks — search, find, trace, explain, read, analyze. Dispatches a constrained Explore subagent so the main session never absorbs raw source.
---

Call the `Agent` tool with `subagent_type: "Explore"` and exactly this prompt (substitute `{{QUESTION}}` with the user's question verbatim, change nothing else):

```
Read ~/.claude/skills/my-explore/dispatch-prompt.md and follow its instructions strictly. Treat the QUESTION below as the <query> referenced in that document.

<query>
{{QUESTION}}
</query>
```

If the returned summary is insufficient, **dispatch again with a sharper question** — never fall back to exploring in the main session yourself.
