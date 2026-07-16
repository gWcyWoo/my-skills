#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime


def clip(value, limit=240):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(event):
    event_type = event.get("type")
    if event_type == "assistant":
        message = event.get("message") or {}
        lines = []
        for block in message.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                lines.append(block["text"])
            elif block.get("type") == "tool_use":
                lines.append(f"[tool] {block.get('name', 'unknown')} {clip(block.get('input', {}))}")
        return lines
    if event_type == "result":
        result = event.get("result")
        return [result] if isinstance(result, str) and result else []
    if event_type == "system":
        subtype = event.get("subtype")
        return [f"[system] {subtype}"] if subtype else []
    return []


def main():
    if len(sys.argv) != 4:
        print("usage: fmt.py <log-path> <title> <pid>", file=sys.stderr)
        return 2

    log_path, title, pid = sys.argv[1:]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        os.chmod(log_path, 0o600)
        header = f"\n[{datetime.now().isoformat(timespec='seconds')}] {title} pid={pid}"
        print(header, file=log, flush=True)
        for raw in sys.stdin:
            raw = raw.rstrip("\n")
            if not raw:
                continue
            try:
                event = json.loads(raw)
                lines = render(event)
            except (json.JSONDecodeError, TypeError):
                lines = [raw]
            for line in lines:
                print(line, flush=True)
                print(line, file=log, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
