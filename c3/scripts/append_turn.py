#!/usr/bin/env python3
"""Append a complete C3 turn to conversations.md."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib


def format_turn(recipient: str, message: str) -> str:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"- {timestamp} To {recipient}:"]
    for line in message.rstrip().splitlines() or [""]:
        lines.append(f"  - {line}")
    lines.append("  - done")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a complete C3 turn.")
    parser.add_argument("conversation", help="Path to conversations.md")
    parser.add_argument("recipient", choices=["codex", "claude"], help="Turn recipient")
    parser.add_argument("message", nargs="?", help="Message text")
    parser.add_argument("--message-file", help="Read message text from a file")
    args = parser.parse_args()

    if args.message_file:
        message = pathlib.Path(args.message_file).read_text(encoding="utf-8")
    elif args.message is not None:
        message = args.message
    else:
        parser.error("provide message or --message-file")

    path = pathlib.Path(args.conversation)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_blank = path.exists() and path.read_text(encoding="utf-8").strip()
    with path.open("a", encoding="utf-8") as handle:
        if needs_blank:
            handle.write("\n")
        handle.write(format_turn(args.recipient, message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
