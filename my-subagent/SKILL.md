---
name: my-subagent
description: Use when a task must run in an isolated agent context but the parent session still needs observable progress, file-backed heartbeats, liveness checks, and resume-by-id behavior.
---

# My Subagent

## Overview

Wrap `spawn_agent` with a file-backed event channel in `/tmp` so the parent session can observe progress even when agent messages are not surfaced in real time.

Core rule: the child agent owns execution, but the parent session owns observability.

## Inputs

The caller must provide:
- `task_prompt` — the original task for the child agent
- `agent_type` — optional; default `default`
- `model` — optional; choose explicitly when needed
- `reasoning_effort` — optional; choose explicitly when needed

## Log Contract

Before spawning the child agent, the parent session must create a unique event log path:

```text
/tmp/codex-subagent-<timestamp>-<shortid>.log
```

The child agent must append one line per event in this format:

```text
<unix_ms> | <event_type> | <details>
```

Allowed `event_type` values:
- `start`
- `tool`
- `live`
- `status`
- `error`

Examples:

```text
1774000000000 | start | task accepted
1774000005123 | tool | rg -n "auth" src
1774000010123 | live | heartbeat
1774000018456 | status | NEEDS_CLARIFICATION
1774000029999 | status | COMPLETE
```

## Required Child-Agent Instructions

When spawning the child agent, append these instructions to the provided `task_prompt`:

```text
You must use this event log path for all observability:
<event_log_path>

Rules:
1. Append one event line to the log immediately on startup using event_type `start`.
2. Before every new action, append one event line using event_type `tool`.
3. “New action” includes any meaningful step such as reading files, writing files, searching, calling tools, running commands, or entering a new analysis phase.
4. Every `tool` line must describe the concrete action in `details`. The parent session must be able to tell what you are doing from the log alone.
5. Valid examples:
   - `tool | read file: src/app/page.tsx`
   - `tool | search text: rg -n "auth" src`
   - `tool | write file: /tmp/codex-subagent-123.log`
   - `tool | run command: npm test`
   - `tool | compute step: add 17 to partial sum`
6. Invalid examples:
   - `tool | working`
   - `tool | processing`
   - `tool | next step`
   - `tool | iteration 17`
7. If no event has been written for 5 seconds, append a `live` heartbeat line.
8. `live` is mandatory. It is the parent session's only authoritative signal that you are still alive between action events.
9. If you fail to write `live` within any 5-second quiet window, the parent session may use that as evidence that observability is degraded, but it must still follow this skill's parent-side liveness rule before classifying the run as stuck or closing it.
10. On terminal completion, append `status | COMPLETE` before returning your final response.
11. On clarification stop, append `status | NEEDS_CLARIFICATION` before returning your final response.
12. On failure you can detect, append `error | <summary>`.
13. Keep writing to the log throughout the run. Do not buffer events for later.
```

If the child agent cannot write to the event log, the parent session must treat the run as invalid.

## Parent Workflow

### Step 1: Prepare Event Log

1. Generate a unique `/tmp` log path.
2. Create an empty file at that path.
3. Record:
   - `agent_id`
   - `event_log_path`
   - `last_read_offset`
   - `last_seen_event_unix_ms`
   - `consecutive_quiet_checks`

### Step 2: Spawn Isolated Agent

Spawn with:
- `fork_context: false`
- explicit `message` containing:
  - the caller's task
  - the injected child-agent instructions above
  - the exact `event_log_path`

Save the returned `agent_id` immediately.

### Step 3: Tail Every 20 Seconds

Every 20 seconds, the parent session must:
1. Read only the newly appended portion of the event log
2. Print the new lines to the terminal
3. Update:
   - `last_read_offset`
   - `last_seen_event_unix_ms`
   - reset `consecutive_quiet_checks` to `0` if any new event line was observed
   - otherwise increment `consecutive_quiet_checks` by `1`

Do not wait for the agent to finish before showing these events.

### Step 4: Liveness Rule

While the child has not reached terminal status, the parent session must treat silence as "still working" unless the silence threshold below has been reached.

If the parent session reaches 100 consecutive 20-second checks with no new event-log line, mark the child agent as:

```text
SUSPECTED_STUCK
```

This is a parent-side health judgment, not a child terminal status. One hundred consecutive quiet checks mean the child has produced no event-log activity for about 33 minutes and may be hung.

Before the parent session reaches 100 consecutive quiet checks, it must:
- continue the 20-second tail loop
- assume the child is still working
- avoid treating silence alone as failure
- avoid closing or replacing the child solely because it is quiet

When this happens, the parent session must tell the user:
- the agent is suspected stuck
- the last observed event
- the log path

If the child prompt explicitly declared missing `live` as a close condition, the parent session may close the agent only after the liveness rule above has classified the run as `SUSPECTED_STUCK` and the parent has reported that state to the user.

## Completion Handling

The run is complete only when both are true:
- the child agent reaches a terminal response
- the event log contains a terminal `status` line

After successful completion:
1. read any final appended lines
2. print them to the terminal
3. delete the `/tmp` event log file

## Clarification / Resume

If the child agent returns `STATUS: NEEDS_CLARIFICATION`:
1. keep the same `agent_id`
2. keep the same `event_log_path`
3. send the user's answer back with `send_input`
4. continue the same 20-second tail loop

Do not create a new agent unless the original agent cannot be resumed.

## Close Rules

Do not call `close_agent` while any of the following is true:
- the child agent has not reached terminal status
- new log events are still appearing
- `live` heartbeats are still arriving
- the agent may still be resumed

Only close an agent after terminal completion, explicit abandonment, or explicit user instruction.

## Common Mistakes

- Treating `wait_agent` as the observability channel. It is not; the log file is.
- Printing the whole file every cycle instead of only new lines.
- Replacing the original agent after clarification when resume is possible.
- Closing the agent because a single read cycle was quiet.
- Forgetting to delete the `/tmp` event log after successful completion.

## Minimal Parent Pattern

```text
prepare /tmp log
spawn isolated agent with injected log instructions
every 20 seconds:
  read appended lines
  print delta
  if new lines appeared:
    reset consecutive_quiet_checks to 0
    update last-seen timestamp
  else:
    increment consecutive_quiet_checks
  if consecutive_quiet_checks >= 100:
    report SUSPECTED_STUCK
when terminal:
  print final delta
  delete /tmp log
```
