---
name: c3
description: Use when coordinating Codex and Claude through a shared conversations.md transcript, agreeing on solutions.md, pausing for user ownership confirmation, then implementing and reviewing.
---

# C3

C3 coordinates Codex and Claude through `./c3/{date}/{session-name}/`.

Required files:
- `target.md`: target problem or solution.
- `conversations.md`: the only synchronization transcript.
- `solutions.md`: the agreed implementation contract.
- `notes-{ts}.md`: optional evidence for substantial analysis or review.

## Protocol Invariants

- P0: Transcript first. Every material artifact write or state transition must be followed by a complete `To <other>` turn in `conversations.md` naming the artifact path when relevant.
- P0: Filesystem events are wake signals only; `conversations.md` is the synchronization source of truth.
- P0: `wait_for_turn.py` returns all complete inbound turns after this side's last outbound as one ordered batch. Process the full batch before replying.
- P0: Waiting must be quiet and blocking. After invoking `wait_for_turn.py`, do not emit periodic "still waiting" updates, do not use short visible polling intervals, and do not report that no turn has arrived unless `wait_for_turn.py` exits with a real timeout/error. Let the script's watchdog/file-event path wake on transcript changes; if the tool layer requires checking a still-running process, keep those checks silent and never present them as C3 progress.
- P0: C3 completion requires peer convergence in `conversations.md`. Codex must not answer, summarize, implement, or declare a conclusion from local code/file exploration alone after C3 is invoked. Every substantive conclusion must be sent as a `To <other>` turn, reviewed by the peer, and either incorporated into an agreed `solutions.md` or explicitly confirmed in the transcript before user-facing delivery.
- P0: After `solutions.md` is written and peer-reviewed, halt for user confirmation. Do not implement before the user confirms.
- P0: The user chooses ownership at the gate. If unspecified, default to Claude implements and Codex reviews.
- P0: Append order is canonical; timestamps are advisory only.
- P0: Implementation/review liveness. After user ownership is confirmed, C3 must stay inside the implementation-review loop until both sides have explicitly converged on completion in `conversations.md`. A reviewer turn with `Changes requested` is not a stopping point; immediately wait for the implementer’s next complete turn. An implementer turn with “fixed” or “done” is not a stopping point; review it and reply in the transcript. Do not send a final user-facing answer while the peer owes a follow-up or while unresolved review findings remain.
- P0: User-facing completion requires transcript completion. Codex may only final-answer the user after a complete inbound/outbound transcript sequence shows either `No blocking issues` from the reviewer and implementer acknowledgement, or an equivalent explicit mutual completion statement. If the latest transcript turn is `Changes requested`, `starting implementation`, `implementation done`, `please review`, or any other non-terminal state, continue waiting/reviewing instead of ending the turn.

## I/O

```bash
python3 ~/.agents/skills/c3/scripts/append_turn.py ./c3/{date}/{session-name}/conversations.md claude --message-file /tmp/c3_block_{ts}.txt
```

```bash
python3 ~/.agents/skills/c3/scripts/wait_for_turn.py ./c3/{date}/{session-name}/conversations.md codex
```

`- done` must be the final standalone line of every turn. Ignore incomplete turns.

Run `wait_for_turn.py` as a blocking wait. Prefer the longest practical tool wait window so the script can return only when a complete inbound turn exists. Do not wrap it in a manual loop that prints status every N seconds.

## Start

If Codex starts:
1. Write `target.md` clearly, create a short session name, and create `conversations.md`.
2. Use `u-0` to understand the target before the first turn.
3. Append `To claude` with Codex's target understanding and proposed solution.
4. Wait for Claude with `wait_for_turn.py`.

If Claude already started:
1. Read `target.md`.
2. Wait for or read the pending `To codex` batch in `conversations.md`.
3. Continue from the reply loop.

## Reply Loop

For every inbound batch:
1. Use `u-0` to understand the other side's view.
2. Evaluate whether each claim helps solve `target.md`.
3. Reply with Support or Changes requested, citing evidence for disagreements.
4. Keep discussion tied to `target.md` and agreement on `solutions.md`.

Do not collapse the reply loop into a solo answer. Reading code, reading docs, or finding enough evidence locally is only input to the next `To <other>` turn; it is never a substitute for peer discussion when C3 has been invoked.

## solutions.md

When both sides agree in `conversations.md`, either side may write `solutions.md`, then must append a `To <other>` turn announcing it. The peer reviews against `target.md` and `conversations.md`.

If review finds issues, reply `Changes requested` with required fixes. If review passes, reply `solutions.md confirmed; awaiting user gate`, then halt for user ownership.

## Implementation And Review

After user confirmation, follow the selected ownership. If unspecified, Claude implements and Codex reviews.

Implementation-ready turns must include changed files, test/lint/type-check commands and results, and exact blockers. Review against `solutions.md`, not a new interpretation.

If review finds issues, reply `Changes requested`; the implementer fixes and reruns checks. After appending `Changes requested`, immediately invoke `wait_for_turn.py` and stay quiet until the implementer posts the next complete turn. Do not summarize to the user, stop the turn, or wait for the user to tell you Claude has updated.

For each implementer follow-up, review the changed implementation against `solutions.md` and the unresolved findings. Then append exactly one review state:
- `Changes requested` with remaining blocking issues.
- `No blocking issues` when the implementation satisfies `solutions.md`.

If none remain, reply `No blocking issues` and wait for the implementer to acknowledge completion or otherwise converge in `conversations.md`. Complete only when both sides agree no blocking issues remain. The implementation-review loop is terminal only after transcript convergence, not after a single review message.

### Reviewer Loop Guardrails

- After any outbound `Changes requested`, the next C3 action is `wait_for_turn.py`.
- After any inbound implementer `implementation done`, `fixed`, `please review`, or equivalent, the next C3 action is review, not a user-facing summary.
- A user message such as “Claude updated”, “review again”, or “continue” is only a wake signal. If Codex is already the reviewer, Codex should have been waiting; handle the inbound transcript batch and continue the loop.
- Do not leave a `wait_for_turn.py` session running if the user redirects the task. Stop or abandon the wait before changing workflows.
