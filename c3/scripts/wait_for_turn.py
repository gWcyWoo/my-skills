"""Wait for pending inbound C3 turns in conversations.md.

The primary wake path uses watchdog filesystem events when installed:
`pip install watchdog`. If watchdog is unavailable, the script falls back to
the polling cadence specified by `--poll-seconds`.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import threading
import time
from typing import Any


TURN_RE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) To (?P<to>claude|codex):\s*$",
    re.IGNORECASE,
)

Turn = dict[str, Any]


def parse_turns(text: str) -> list[Turn]:
    turns: list[Turn] = []
    current: Turn | None = None

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


def is_done(turn: Turn) -> bool:
    lines = [line.strip() for line in turn["lines"] if str(line).strip()]
    return bool(lines) and lines[-1] == "- done"


def peer_for(recipient: str) -> str:
    return "claude" if recipient == "codex" else "codex"


def pending_inbound_turns(path: pathlib.Path, recipient: str) -> list[Turn]:
    if not path.exists():
        return []

    turns = parse_turns(path.read_text(encoding="utf-8"))
    complete_turns = [turn for turn in turns if is_done(turn)]
    peer = peer_for(recipient)

    last_outbound_index = -1
    for index, turn in enumerate(complete_turns):
        if turn["to"] == peer:
            last_outbound_index = index

    return [
        turn
        for turn in complete_turns[last_outbound_index + 1 :]
        if turn["to"] == recipient
    ]


def render_turn(turn: Turn) -> str:
    lines = "\n".join(str(line) for line in turn["lines"]).rstrip()
    return f"- {turn['timestamp']} To {turn.get('display_to', turn['to'])}:\n{lines}"


def render_turns(turns: list[Turn]) -> str:
    return "\n\n".join(render_turn(turn) for turn in turns)


def timed_out(start: float, timeout_seconds: float) -> bool:
    return bool(timeout_seconds) and time.monotonic() - start > timeout_seconds


def check_pending(path: pathlib.Path, recipient: str) -> str | None:
    turns = pending_inbound_turns(path, recipient)
    return render_turns(turns) if turns else None


def wait_with_polling(
    path: pathlib.Path,
    recipient: str,
    poll_seconds: float,
    timeout_seconds: float,
    start: float,
) -> int:
    while True:
        rendered = check_pending(path, recipient)
        if rendered is not None:
            print(rendered)
            return 0

        if timed_out(start, timeout_seconds):
            print(f"Timed out waiting for complete To {recipient} turn in {path}", file=sys.stderr)
            return 2

        time.sleep(poll_seconds)


def wait_with_watchdog(
    path: pathlib.Path,
    recipient: str,
    poll_seconds: float,
    timeout_seconds: float,
    start: float,
) -> int | None:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        return None

    changed = threading.Event()
    watched_path = path.resolve()

    class TranscriptHandler(FileSystemEventHandler):
        def on_any_event(self, event: object) -> None:
            src_path = pathlib.Path(str(getattr(event, "src_path", ""))).resolve()
            dest = getattr(event, "dest_path", None)
            dest_path = pathlib.Path(str(dest)).resolve() if dest else None
            if src_path == watched_path or dest_path == watched_path:
                changed.set()

    path.parent.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(TranscriptHandler(), str(path.parent), recursive=False)
    observer.start()
    try:
        while True:
            rendered = check_pending(path, recipient)
            if rendered is not None:
                print(rendered)
                return 0

            if timed_out(start, timeout_seconds):
                print(f"Timed out waiting for complete To {recipient} turn in {path}", file=sys.stderr)
                return 2

            changed.wait(timeout=poll_seconds)
            changed.clear()
    finally:
        observer.stop()
        observer.join()


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for pending inbound C3 turns.")
    parser.add_argument("transcript", help="Path to conversations.md")
    parser.add_argument("recipient", help="Inbound recipient to wait for: codex or claude, case-insensitive")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="0 means wait forever")
    args = parser.parse_args()

    path = pathlib.Path(args.transcript)
    recipient = args.recipient.lower()
    if recipient not in {"codex", "claude"}:
        parser.error("recipient must be codex or claude")

    start = time.monotonic()
    rendered = check_pending(path, recipient)
    if rendered is not None:
        print(rendered)
        return 0

    watchdog_result = wait_with_watchdog(
        path=path,
        recipient=recipient,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
        start=start,
    )
    if watchdog_result is not None:
        return watchdog_result

    return wait_with_polling(
        path=path,
        recipient=recipient,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
        start=start,
    )


if __name__ == "__main__":
    raise SystemExit(main())
