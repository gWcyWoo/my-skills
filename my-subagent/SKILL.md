---
name: my-subagent
description: Use when a task must run in an isolated agent context but the parent session still needs liveness checks and resume-by-id behavior.
---

# My Subagent

## Overview

Wrap the `Agent` tool with a parent-owned polling workflow so the parent session can observe completion and resumability even when agent messages are not surfaced in real time.

Core rule: the child agent owns execution, but the parent session owns observability.

## Inputs

The caller must provide:
- `task_prompt` — the original task for the child agent
- `subagent_type` — optional; default `coder`
- `model` — optional; choose explicitly when needed

## Required Child-Agent Instructions

When dispatching the child agent via the `Agent` tool, append these instructions to the provided `task_prompt`:

```text
Rules:
1. On terminal completion, begin your final response with `STATUS: COMPLETE` on its own line.
2. On clarification stop, begin your final response with `STATUS: NEEDS_CLARIFICATION` on its own line.
3. Put the substantive summary, question, or result after the status line.
4. Do not rely on side channels for terminal state; the parent session will read the returned response.
```

## Parent Workflow

### Step 1: Dispatch Isolated Agent

Dispatch with the `Agent` tool:
- `run_in_background: true`
- `prompt` containing:
  - the caller's task
  - the injected child-agent instructions above

Save the returned `agent_id` immediately and record:
- `agent_id`
- `consecutive_quiet_checks`

### Step 2: Poll Every 120 Seconds

Every 120 seconds, the parent session must:
1. Call `TaskOutput` on the same `agent_id` with `block: true` and a 120-second timeout
2. If the agent has not reached terminal status, increment `consecutive_quiet_checks` by `1`
3. If the agent reaches terminal status, stop the poll loop and inspect the returned response for the required `STATUS:` line

Do not block indefinitely on a single wait. The 120-second loop is the observability mechanism.

### Step 3: Liveness Rule

While the child has not reached terminal status, the parent session must treat silence as "still working" unless the silence threshold below has been reached.

If the parent session reaches 100 consecutive 120-second checks with no terminal response, mark the child agent as:

```text
SUSPECTED_STUCK
```

This is a parent-side health judgment, not a child terminal status. One hundred consecutive quiet checks mean the child has produced no terminal response for about 200 minutes and may be hung.

Before the parent session reaches 100 consecutive quiet checks, it must:
- continue the 120-second poll loop
- assume the child is still working
- avoid treating silence alone as failure
- avoid closing or replacing the child solely because it is quiet

When this happens, the parent session must tell the user:
- the agent is suspected stuck
- the `agent_id`

## Completion Handling

The run is complete only when both are true:
- the child agent reaches a terminal response
- the response begins with a terminal `STATUS:` line

After successful completion:
1. capture the terminal response
2. use the `STATUS:` line to decide whether the run is complete or needs clarification

## Clarification / Resume

If the child agent returns `STATUS: NEEDS_CLARIFICATION` in its terminal response:
1. keep the same `agent_id`
2. send the user's answer back with `Agent(resume: agent_id, prompt: "...")`
3. continue the same 120-second poll loop

Do not create a new agent unless the original agent cannot be resumed.

## Close Rules

Do not call `TaskStop` while any of the following is true:
- the child agent has not reached terminal status
- the agent may still be resumed

Only stop an agent after terminal completion, explicit abandonment, or explicit user instruction.

## Common Mistakes

- Calling `TaskOutput` without a timeout and blocking the session indefinitely.
- Replacing the original agent after clarification when resume is possible.
- Closing the agent because a single read cycle was quiet.
- Ignoring the required `STATUS:` prefix in the child agent's terminal response.

## Minimal Parent Pattern

```text
dispatch isolated agent via Agent tool with injected status instructions
every 120 seconds:
  call TaskOutput(agent_id, block: true, timeout: 120)
  if no terminal response:
    increment consecutive_quiet_checks
  if consecutive_quiet_checks >= 100:
    report SUSPECTED_STUCK
when terminal:
  inspect STATUS line
```
