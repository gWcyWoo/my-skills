# c3-v2 — Event-Driven c3 Protocol Redesign

## Goal
Negotiate c3 v2 architecture between Claude and Codex. After agreement, cross-modify each other's SKILL.md (Codex rewrites Claude's, Claude rewrites Codex's) to enforce shared understanding.

## Motivation
Both sides currently wrap inbound waiting in polling/wakeup loops:
- Claude side: `/loop /c3 <session>` + `ScheduleWakeup(30)` + `c3-io.sh r exit-1` → reschedule. Runtime clamps `delaySeconds` to `[60, 3600]`, so SKILL's `ScheduleWakeup(30)` is silently bumped to 60s — the SKILL is lying.
- Codex side: `wait_for_turn.py` blocks via `time.sleep(30)`. Better than tick-based, but still 30s worst-case latency on the read.

Both can be replaced with OS filesystem events (`watchdog` / FSEvents / inotify) → end-to-end latency drops from 30–60s to ~50ms.

## Proposed v2 (refined in conversations.md)
1. Event-driven `wait_for_turn.py` — `watchdog` library, polling fallback as safety net.
2. Single bash call from Claude Code: `python3 wait_for_turn.py $dialog claude` blocks until inbound. Use `run_in_background=true` so Claude doesn't burn turn-time waiting; harness notifies on subprocess exit.
3. Unified write path: `append_turn.py --message-file /tmp/c3_block_{ts}.txt`. Deprecate `c3-io.sh w / wf`.
4. SKILL.md: drop `/loop`, `ScheduleWakeup`, `c3-io.sh r exit-1`, and `wf` 3-step protocol from instructions. Linear flow: wait → process → append → wait → …
5. Decide script ownership: single source of truth at `~/.agents/skills/c3/scripts/` vs parallel copies at each side.

## Out of scope
- Behavioral rules (observer-only output, file:line evidence, scope guard, pre-review test/lint gate) — stay as-is.
- target.md / solutions.md / notes-{ts}.md naming and roles — confirm in v2 but not redesign.

## Success criteria
- v2 SKILL.md (both sides) ≤ 60 lines each.
- End-to-end inbound latency ≤ 1s (Codex writes `- done` → Claude starts processing).
- Zero `ScheduleWakeup` references in either SKILL.md.
- Zero shell-escaping concerns in write path (no heredoc, no shell-arg bodies).
