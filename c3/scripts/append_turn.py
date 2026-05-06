#!/usr/bin/env python3
"""Append a complete C3 turn to conversations.md.

Claude-side c3-v2 write helper. Auto-formats the wire envelope:
  - Adds `- {YYYY-MM-DD HH:MM:SS} To <recipient>:` header (current local time)
  - Indents every body line as a `  - <line>` bullet
  - Appends a standalone `  - done` terminator
  - Ensures a blank-line separator before the new turn if the file is non-empty

Usage:
  append_turn.py <conversations.md> <recipient> <message>
  append_turn.py <conversations.md> <recipient> --message-file <path>

Recipient: 'claude' or 'codex'. The header `To <recipient>:` is generated
verbatim — choose the side you are writing TO, not from.

Use --message-file when the message contains shell-special characters
($, quotes, backticks, newlines) — content read from the file is preserved
byte-exact in the bullet body.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib


def format_turn(recipient: str, message: str) -> str:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"- {timestamp} To {recipient}:"]
    body_lines = message.rstrip().splitlines() or [""]
    for line in body_lines:
        lines.append(f"  - {line}")
    lines.append("  - done")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a complete C3 turn.")
    parser.add_argument("conversation", help="Path to conversations.md")
    parser.add_argument(
        "recipient",
        choices=["codex", "claude"],
        help="Turn recipient (the side you are writing TO)",
    )
    parser.add_argument("message", nargs="?", help="Message body (positional)")
    parser.add_argument(
        "--message-file",
        help="Path to a file containing the message body (preferred for content "
             "with shell-special characters)",
    )
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
