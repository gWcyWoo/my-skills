#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime


def clip(value, limit=2000):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def render(event):
    event_type = event.get("type")
    if event_type == "item.completed":
        item = event.get("item") or {}
        item_type = item.get("type")
        if item_type == "agent_message" and item.get("text"):
            return [item["text"]]
        if item_type == "command_execution":
            exit_code = item.get("exit_code")
            command = clip(item.get("command", ""), 500)
            lines = [f"[command] exit={exit_code} {command}"]
            if exit_code not in (None, 0) and item.get("aggregated_output"):
                lines.append(clip(item["aggregated_output"]))
            return lines
    if event_type in {"turn.failed", "error"}:
        return [f"[{event_type}] {clip(event.get('error') or event.get('message') or event)}"]
    return []


def main():
    if len(sys.argv) != 4:
        print("usage: fmt.py <log-path> <title> <pid>", file=sys.stderr)
        return 2
    log_path, title, pid = sys.argv[1:]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        os.chmod(log_path, 0o600)
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {title} pid={pid}", file=log)
        for raw in sys.stdin:
            try:
                lines = render(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                print(f"[unparsed] {raw.rstrip()}", file=log, flush=True)
                lines = []
            for line in lines:
                if line:
                    print(line, flush=True)
                    print(line, file=log, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
