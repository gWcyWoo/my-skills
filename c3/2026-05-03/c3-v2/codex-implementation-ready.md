Implementation ready for Codex-side C3 files.

Changed files:
- `~/.agents/skills/c3/SKILL.md`
- `~/.agents/skills/c3/scripts/wait_for_turn.py`
- `~/.agents/skills/c3/scripts/append_turn.py`

Implemented from confirmed `solutions.md`:
- Standardized Codex C3 skill on `conversations.md`.
- Added protocol invariants I1-I6, including transcript-first synchronization, event-wake-only semantics, batch pending-inbound processing, user confirmation gate, user-selected ownership with Claude-implements/Codex-reviews default, and append-order-over-timestamps.
- Rewrote `wait_for_turn.py` to:
  - return all pending inbound turns after this side's last outbound as one ordered batch;
  - use `watchdog` filesystem events as primary wake path;
  - fall back to polling when `watchdog` is unavailable;
  - preserve the existing CLI shape with `transcript`, `recipient`, `--poll-seconds`, and `--timeout-seconds`;
  - document `pip install watchdog`.
- Updated `append_turn.py` help/docstring from `conversation.md` to `conversations.md`; append behavior is unchanged.

Validation run:
- `python3 -m py_compile /Users/Woo/.agents/skills/c3/scripts/wait_for_turn.py /Users/Woo/.agents/skills/c3/scripts/append_turn.py` — passed.
- `rg -n "conversation\\.md|ScheduleWakeup|c3-io\\.sh|/loop /c3|latest_complete_inbound" /Users/Woo/.agents/skills/c3` — no matches.
- `wc -l /Users/Woo/.agents/skills/c3/SKILL.md` — 70 lines.
- Session-restart immediate parse test — passed; returned existing complete inbound immediately.
- I3 batch-processing test — passed; first invocation returned both pending inbound turns, second invocation timed out after one outbound reply answered the batch.
- Event-driven wake test with `watchdog` installed — passed; with `--poll-seconds 60`, delayed file write returned in about 1.03s.
- Polling fallback test with `PYTHONNOUSERSITE=1` — passed; returned on the 0.5s fallback poll.
- `append_turn.py --message-file` special-character body test — passed for `$`, quotes, backticks, backslash, and multiline content.

Dependency note:
- `python3 -m pip install --user watchdog` was blocked by the externally managed Python policy.
- Retried with `python3 -m pip install --user --break-system-packages watchdog`; installed `watchdog-6.0.0` in the user site.

Ready for review against `solutions.md`.
