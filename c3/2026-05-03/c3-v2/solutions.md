# c3-v2 — Agreed Solution (revised after Codex Changes Requested + read-side bug discovery)

## Problem
Both sides of c3 currently wrap inbound waiting in polling/wakeup loops, with worst-case latency 30–60s and dialogue protocol vulnerable to two failure modes uncovered in this very session:

1. **Latency failure (original target)**: Claude side `/loop /c3 <session>` + `ScheduleWakeup(30→60 clamped)` + `c3-io.sh r exit-1` reschedule; Codex side `time.sleep(30)`. Both should be replaced with OS fsevents.

2. **Side-channel artifact failure (uncovered 23:15)**: Claude wrote `solutions.md` and announced it via a `To codex` turn — but if any side writes a state-changing artifact WITHOUT a matching transcript turn, the other side blocks on `wait_for_turn` indefinitely because the wait helper only returns on inbound transcript turns.

3. **Read-side dropped-inbound failure (uncovered 23:17)**: `c3-io.sh r` (Claude) and `wait_for_turn.py:latest_complete_inbound` (Codex) both return ONLY the LAST complete inbound turn. If two inbound turns from the peer arrive without a reply between them (e.g. peer self-corrects, or peer realizes append-order skew), the OLDER one is silently dropped. This is exactly what happened: Codex's `23:15:00 To claude: Changes requested` was masked by his subsequent `23:17:47 To claude: Do not implement` — Claude's `c3-io.sh r` only surfaced the latter.

4. **Implementation-authorization failure (clarified by user via Codex 23:17)**: protocol jumped from "peer agrees with solutions" directly to "implement", bypassing user confirmation. User explicitly requires a HALT after `solutions.md` review for confirmation + ownership assignment.

## Solution

### Protocol Invariants (the actual core of v2)

These invariants override any technical convenience. All implementation steps below MUST satisfy them.

**I1 — Transcript-first invariant.** Every material artifact write or state transition (writing `target.md`, `solutions.md`, `notes-*.md`; starting implementation; submitting for review; flagging blocked; sealing approved) MUST be immediately followed by a complete `To <other>` transcript turn in `conversations.md` that names the artifact path (if any) and ends with `- done`. The transcript is the synchronization source of truth; artifacts are payload references. No side-channel state changes.

**I2 — Filesystem events are the wake mechanism only.** `wait_for_turn.py` watches `conversations.md` via fsevent (with polling fallback). When awakened, it parses the transcript and returns only complete inbound turns. Artifact files (`solutions.md`, `notes-*.md`, source code) are NOT watched as wake signals.

**I3 — No-dropped-inbound / batch-processing invariant.** `wait_for_turn.py` MUST return ALL pending inbound turns as one ordered batch. Definition: "pending inbound" = every complete `To <recipient>` turn appearing AFTER the recipient's last complete `To <peer>` turn in append order. The recipient processes the entire returned batch before appending exactly ONE outbound response; that response counts as the answer to the whole batch. Derivation: stateless, from append order alone — no hidden cursor, no turn IDs, no timestamp ordering. (Codex correction of an earlier per-turn-cursor proposal that was internally contradictory: a single outbound trivially appears after multiple earlier inbounds, making per-turn "unanswered" undefinable without external state.)

**I4 — User confirmation gate after `solutions.md`.** After `solutions.md` is written AND the peer reviews/agrees, the protocol HALTS. Implementation cannot start until the user explicitly confirms. The confirmation message also chooses ownership (see I5). Both sides emit a tick line indicating "awaiting user confirmation" and stop scheduling new wakes until user input arrives.

**I5 — Ownership assignment by user, default Claude-implements / Codex-reviews.** At the user-confirmation gate, the user picks one of:
- (a) Claude implements, Codex reviews [DEFAULT if user says only "confirm" / "go"]
- (b) Codex implements, Claude reviews
- (c) Both modify in parallel (cross-write: each side authors the OTHER side's deliverables)
- (d) User implements, both review
Cross-write is an OPTIONAL execution mode, not a default.

**I6 — Append-order over timestamps.** Timestamps in turn headers are advisory only; the canonical ordering is FILE APPEND ORDER. Reviewers and protocol logic MUST use append order, not timestamp comparison, when reasoning about turn sequence. Clock skew between Claude/Codex is real (observed 6+ min in this session) and is not a protocol concern.

### Technical Implementation Steps (gated on I4)

1. **Rewrite `~/.agents/skills/c3/scripts/wait_for_turn.py`** — preserve CLI signature (`transcript`, `recipient`, `--poll-seconds`, `--timeout-seconds`); add fsevent backend AND fix dropped-inbound bug. Logic order:
   - Step A — initial parse: scan all turns. Find the recipient's last complete `To <peer>` outbound turn in append order. Collect ALL complete `To <recipient>` turns appearing after it (the pending inbound batch). If non-empty → `print(render_turns(turns))` (each turn rendered with header + body + `- done`, separated by a blank line, in append order) + `return 0` immediately.
   - Step B — try `from watchdog.observers import Observer`. On `ImportError`, skip to Step D.
   - Step C — register `FileSystemEventHandler` on `path.parent`, filter on `evt.src_path == str(path) or getattr(evt, "dest_path", None) == str(path)`. Loop: `event.wait(timeout=args.poll_seconds)`; on wake, re-run Step A; exit 0 if matched.
   - Step D (no-watchdog fallback): `while True: ... time.sleep(args.poll_seconds)` calling Step A each loop.
   - Step E (timeout): if `--timeout-seconds > 0` and elapsed exceeds, stderr + `return 2`.
   - File: `~/.agents/skills/c3/scripts/wait_for_turn.py:1-103` → fully rewritten. Rename `latest_complete_inbound` → `pending_inbound_turns` (returns `list[dict]` instead of `dict | None`). Rename `render_turn` → `render_turns` (renders the list in append order, each turn followed by a blank line).

2. **Keep `~/.agents/skills/c3/scripts/append_turn.py` as-is** — `--message-file` (`:25,29`) is the correct unified write path. No edits.

3. **Rewrite `~/.claude/skills/c3/SKILL.md`** (target ≤ 70 lines, slightly raised to fit the I1–I6 invariants):
   - Drop `<role>` references to `/loop`, `ScheduleWakeup`, `c3-io.sh r/w/wf`, `wf` 3-step protocol.
   - I/O helper section reduces to two lines:
     - read: `python3 ~/.agents/skills/c3/scripts/wait_for_turn.py "$dialog" claude` (foreground or `run_in_background=true`).
     - write: Write block body to `/tmp/c3_block_{ts}.txt` → `python3 ~/.agents/skills/c3/scripts/append_turn.py "$dialog" codex --message-file /tmp/c3_block_{ts}.txt`.
   - Instructions become linear: pre-flight `$base`/`$dialog` → wait → process inbound → write outbound → wait. No tick numbering.
   - Enforce I1–I6 explicitly as P0 reminders.
   - Drop P0 reminders about `ScheduleWakeup`, `wf` 3-step, heredoc forbiddance, exit-1 routing.
   - Keep behavioral P0s verbatim: observer rule, file:line evidence from `notes-{ts}.md`, scope guard for implementation edits, pre-review tests+lint+type-check gate, target-tied discussion.
   - Standardize transcript filename to `conversations.md`; drop `conversation.md` fallback.
   - File: `~/.claude/skills/c3/SKILL.md:1-115` → fully rewritten.

4. **Rewrite `~/.agents/skills/c3/SKILL.md`** (target ≤ 70 lines):
   - Standardize transcript filename to `conversations.md` (correcting current `conversation.md` references at `:13,22,48-50,90`).
   - Add I1–I6 invariants as P0s.
   - Add behavioral P0s aligned with Claude side: observer-only output, file:line evidence (optional `notes-{ts}.md` for substantial analysis), scope guard, pre-review tests+lint gate, target-tied discussion.
   - Keep existing linear flow.
   - File: `~/.agents/skills/c3/SKILL.md:1-119` → fully rewritten.

5. **Deprecate `~/.claude/skills/c3/c3-io.sh`** — keep file for one cycle with header comment `# DEPRECATED 2026-05-03: replaced by ~/.agents/skills/c3/scripts/{wait_for_turn,append_turn}.py per c3-v2.` SKILL.md no longer references it.

6. **Clean up `~/.claude/settings.json`** — after migration, remove allow rules: `Bash(bash ~/.claude/skills/c3/c3-io.sh *)`, `Bash(bash /Users/Woo/.claude/skills/c3/c3-io.sh *)`, `Bash(cat > /tmp/c3_block_*)`, `Bash(rm -f /tmp/c3_block_*)`. Add: `Bash(python3 ~/.agents/skills/c3/scripts/* *)`, `Bash(python3 /Users/Woo/.agents/skills/c3/scripts/* *)`. Keep `Write(/tmp/**)`.

7. **`pip install watchdog`** — single new runtime dependency. Document in Step 1's `wait_for_turn.py` docstring.

### Execution Ownership (gated on I4 — to be filled by user)

After user confirms `solutions.md`, fill this section:
- Selected mode: ⬜ (a) Claude implements + Codex reviews [DEFAULT] / ⬜ (b) Codex implements + Claude reviews / ⬜ (c) cross-write / ⬜ (d) user implements + both review
- Implementer: ___
- Reviewer: ___

## Test Plan

Reviewer runs each command and confirms expected behavior. (Tests #1–#7 unchanged from prior revision; #8 NEW for I3 verification.)

1. **fsevent latency** (with `watchdog` installed):
   ```
   rm -f /tmp/c3_test.md
   python3 ~/.agents/skills/c3/scripts/wait_for_turn.py /tmp/c3_test.md claude --poll-seconds 60 &
   PID=$!
   sleep 0.5
   printf -- '- 2026-05-03 23:00:00 To claude:\n  - test body\n  - done\n' > /tmp/c3_test.md
   wait $PID
   ```
   Expect: returns within ~1s, exits 0, prints the block.

2. **Polling fallback** (force `ImportError`): expect returns within ~`--poll-seconds`s of file write.

3. **Session-restart idempotence**:
   ```
   printf -- '- 2026-05-03 23:00:00 To claude:\n  - already done\n  - done\n' > /tmp/c3_test.md
   time python3 ~/.agents/skills/c3/scripts/wait_for_turn.py /tmp/c3_test.md claude
   ```
   Expect: returns immediately (≤100ms wall-clock), prints block.

4. **Write round-trip with special chars** — `--message-file` body preserves `$` / quotes / backticks / newlines verbatim.

5. **End-to-end fresh session** — zero `ScheduleWakeup` / `c3-io.sh` invocations in a complete session including user-confirmation gate.

6. **SKILL.md size**: `wc -l` both ≤ 70.

7. **Reference cleanup**: `grep -nE 'ScheduleWakeup|c3-io\.sh|/loop /c3' ~/.claude/skills/c3/SKILL.md` and `grep -nE 'conversation\.md' ~/.agents/skills/c3/SKILL.md` both empty.

8. **NEW — I3 batch-processing** (regression test for this session's failure, per Codex correction):
   ```
   rm -f /tmp/c3_test.md
   printf -- '- 2026-05-03 23:00:00 To claude:\n  - first\n  - done\n\n- 2026-05-03 23:01:00 To claude:\n  - second\n  - done\n' > /tmp/c3_test.md
   python3 ~/.agents/skills/c3/scripts/wait_for_turn.py /tmp/c3_test.md claude
   # → must print BOTH turns ("first" then "second") as one ordered batch in append order, each with its own header + body + done.
   printf -- '\n- 2026-05-03 23:02:00 To codex:\n  - reply addressing both\n  - done\n' >> /tmp/c3_test.md
   python3 ~/.agents/skills/c3/scripts/wait_for_turn.py /tmp/c3_test.md claude --poll-seconds 0.05 --timeout-seconds 0.2
   # → must time out (exit 2), because the batch has been answered by the single outbound reply.
   ```
   Expect: first invocation prints both turns concatenated; second invocation times out with stderr message + exit 2. Validates pending-batch semantics — single outbound answers the entire batch.

## Acceptance Criteria

- ✅ Protocol invariants I1–I6 explicitly stated in both SKILL.md files as P0 reminders.
- ✅ `wait_for_turn.py` returns ALL pending inbound turns as one ordered batch (I3); test #8 passes (both turns returned together; second invocation times out after one outbound reply answers the batch).
- ✅ `wait_for_turn.py` uses fsevent (watchdog) primary + polling fallback (Step 1 + tests #1, #2).
- ✅ `wait_for_turn.py` instant-returns when message already present (test #3).
- ✅ `--message-file` preserves special chars verbatim (test #4).
- ✅ One end-to-end c3 session completes with zero `ScheduleWakeup` / `c3-io.sh`, including user-confirmation gate fired after `solutions.md` agreement (test #5).
- ✅ Both SKILL.md files ≤ 70 lines (test #6).
- ✅ Zero `ScheduleWakeup` / `c3-io.sh` / `/loop /c3` in Claude SKILL; zero `conversation.md` in Codex SKILL (test #7).
- ✅ Behavioral P0s preserved on both sides: observer-only output, file:line evidence, scope guard, pre-review tests+lint+type-check, target-tied discussion.
- ✅ `~/.claude/settings.json` cleaned and updated.
- ✅ `~/.claude/skills/c3/c3-io.sh` carries `# DEPRECATED` header; not invoked by SKILL.md.
- ✅ `pip install watchdog` documented in `wait_for_turn.py` docstring.
- ✅ Execution Ownership section of this `solutions.md` filled in by user before any implementation begins.
