#!/usr/bin/env python3
"""Wait until a pending inbound C3 turn batch arrives, then print to stdout and exit.

Claude-side c3-v2 read helper. Event-driven via `watchdog` (FSEvents on macOS,
inotify on Linux), with a polling fallback if `watchdog` is not installed.
Implements the I3 batch-processing invariant from c3-v2 solutions.md:
returns ALL complete inbound turns appearing after the recipient's last
complete outbound turn, as one ordered batch in append order.

Requires: pip install watchdog (optional — falls back to polling on ImportError).

Usage:
  wait_for_turn.py <transcript> <recipient> [--poll-seconds 60.0] [--timeout-seconds 0.0]

Recipient: 'claude' or 'codex' (case-insensitive). Per c3 protocol, header
addressing is `To <recipient>:`. Outbound for `claude` is `To codex:` and vice
versa.

Exit codes:
  0 — pending inbound batch printed.
  2 — timed out waiting (only when --timeout-seconds > 0).
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import threading
import time


TURN_RE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) To (?P<to>claude|codex|user):\s*$",
    re.IGNORECASE,
)


def parse_turns(text: str) -> list[dict[str, object]]:
    turns: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        match = TURN_RE.match(line)
        if match:
            if current is not None:
                turns.append(current)
            current = {
                "timestamp": match.group("ts"),
                "to": match.group("to").lower(),
                "display_to": match.group("to"),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current is not None:
        turns.append(current)
    return turns


def is_done(turn: dict[str, object]) -> bool:
    lines = [line.strip() for line in turn["lines"] if str(line).strip()]
    return bool(lines) and lines[-1] == "- done"


def pending_inbound_turns(
    path: pathlib.Path, recipient: str
) -> list[dict[str, object]]:
    """Return all complete `To <recipient>` turns appearing after the recipient's
    last complete outbound turn (i.e. after the last `To <peer>` turn the
    recipient has authored). Stateless; derived from append order alone.
    """
    if not path.exists():
        return []
    turns = parse_turns(path.read_text(encoding="utf-8"))
    if not turns:
        return []
    peer = "codex" if recipient == "claude" else "claude"
    last_outbound_idx = -1
    for i, turn in enumerate(turns):
        if turn["to"] == peer and is_done(turn):
            last_outbound_idx = i
    return [
        turn
        for turn in turns[last_outbound_idx + 1 :]
        if turn["to"] == recipient and is_done(turn)
    ]


def render_turns(turns: list[dict[str, object]]) -> str:
    """Render turns in append order, each with header + body, separated by a single
    blank line (matching transcript visual separator). Each turn body already
    contains its `- done` line via the original lines."""
    blocks = []
    for turn in turns:
        body = "\n".join(str(line) for line in turn["lines"]).rstrip()
        blocks.append(
            f"- {turn['timestamp']} To {turn.get('display_to', turn['to'])}:\n{body}"
        )
    return "\n\n".join(blocks)


def _try_watchdog():
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        return Observer, FileSystemEventHandler
    except ImportError:
        return None, None


def _wait_event_driven(
    Observer, FileSystemEventHandler, path: pathlib.Path, recipient: str,
    poll_seconds: float, timeout_seconds: float, start: float,
) -> int:
    wake_event = threading.Event()

    class Handler(FileSystemEventHandler):  # type: ignore[misc, valid-type]
        def on_any_event(self, event):
            src = getattr(event, "src_path", None)
            dest = getattr(event, "dest_path", None)
            if src == str(path) or dest == str(path):
                wake_event.set()

    observer = Observer()
    parent = path.parent if path.parent.exists() else pathlib.Path(".")
    observer.schedule(Handler(), str(parent), recursive=False)
    observer.start()
    try:
        while True:
            wake_event.wait(timeout=poll_seconds)
            wake_event.clear()
            pending = pending_inbound_turns(path, recipient)
            if pending:
                print(render_turns(pending))
                return 0
            if timeout_seconds and (time.monotonic() - start) > timeout_seconds:
                print(
                    f"Timed out waiting for pending To {recipient} turn in {path}",
                    file=sys.stderr,
                )
                return 2
    finally:
        observer.stop()
        observer.join()


def _wait_polling(
    path: pathlib.Path, recipient: str,
    poll_seconds: float, timeout_seconds: float, start: float,
) -> int:
    while True:
        time.sleep(poll_seconds)
        pending = pending_inbound_turns(path, recipient)
        if pending:
            print(render_turns(pending))
            return 0
        if timeout_seconds and (time.monotonic() - start) > timeout_seconds:
            print(
                f"Timed out waiting for pending To {recipient} turn in {path}",
                file=sys.stderr,
            )
            return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wait for the pending inbound C3 turn batch."
    )
    parser.add_argument("transcript", help="Path to conversations.md")
    parser.add_argument(
        "recipient",
        help="Inbound recipient to wait for: codex or claude (case-insensitive)",
    )
    parser.add_argument(
        "--poll-seconds", type=float, default=60.0,
        help="Safety-net poll heartbeat (default 60s; primary wake is fsevent if "
             "watchdog is installed)",
    )
    parser.add_argument(
        "--timeout-seconds", type=float, default=0.0,
        help="0 = wait forever (default)",
    )
    args = parser.parse_args()

    path = pathlib.Path(args.transcript)
    recipient = args.recipient.lower()
    if recipient not in {"codex", "claude"}:
        parser.error("recipient must be codex or claude")

    # Step A: initial parse — return immediately if pending batch already exists.
    pending = pending_inbound_turns(path, recipient)
    if pending:
        print(render_turns(pending))
        return 0

    start = time.monotonic()
    Observer, FileSystemEventHandler = _try_watchdog()

    if Observer is not None:
        return _wait_event_driven(
            Observer, FileSystemEventHandler, path, recipient,
            args.poll_seconds, args.timeout_seconds, start,
        )
    return _wait_polling(
        path, recipient, args.poll_seconds, args.timeout_seconds, start,
    )


if __name__ == "__main__":
    raise SystemExit(main())
