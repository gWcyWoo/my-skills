---
name: my-explore
description: Use when code exploration must run in an isolated Codex child agent that fetches bounded source evidence and returns JSON only.
---

# My Explore

## Codex Shape

Codex does not currently expose a documented `~/.codex/agents/<name>/AGENT.md` format that adds a custom `agent_type`.

Implement `my-explore` as a session-scoped child agent:
- First use: call `spawn_agent` with `agent_type: "default"`, `fork_context: false`, and the prompt from [agent-prompt.md](references/agent-prompt.md) plus the caller request.
- Later uses in the same conversation: reuse the stored `<my_explore_agent_id>` with `send_input`.
- If the agent is closed, call `resume_agent` on `<my_explore_agent_id>` before `send_input`.
- Do not spawn a second `my-explore` child in the same conversation unless the previous agent cannot be resumed.

The parent session owns the child-agent ID and liveness. The child owns code exploration.

## Caller Protocol

Send requests in this exact format:

```text
Intent: <one sentence>

Directions:
  1. <specific code-evidence question>
  2. <optional>
  3. <optional>

Anchors: <optional known files/symbols>
Budget: <optional integer, default 6>
```

Rules:
- At most 3 directions.
- Each direction must be answerable by code evidence.
- Open-ended design or implementation questions are invalid.
- Include anchors whenever known.

## Parent Workflow

1. Validate the request shape. If malformed, fix it before sending.
2. Ensure exactly one `my-explore` child agent exists for this conversation.
3. Send the request verbatim.
4. Wait for the child response.
5. Accept only a single JSON object matching [protocol.md](references/protocol.md).
6. If the child returns prose, markdown fences, recommendations, or non-JSON output, send a correction to the same agent ID and require JSON-only output.
7. Do not read target-repository source in the parent session to compensate for a child failure.

## Child Contract

The child must:
- Explore only the requested directions.
- Use only the tool palette and limits in [agent-prompt.md](references/agent-prompt.md).
- Return raw source bodies in JSON.
- Stop after the JSON response.

The child must not:
- Speak to the user.
- Recommend next steps.
- Edit files.
- Spawn agents.
- Explore beyond the caller request.

## Output Handling

The parent may summarize the returned JSON for the user, but must preserve evidence fidelity:
- cite exact `file` and `lines`;
- do not claim facts not present in `body`;
- if `skipped` is non-empty, report the missing directions.
