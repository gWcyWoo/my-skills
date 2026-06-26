#!/usr/bin/env python3
"""Register a design asset directory in pubspec.yaml deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pubspec", required=True)
    parser.add_argument("--asset", required=True)
    args = parser.parse_args()

    pubspec = Path(args.pubspec)
    asset = args.asset.rstrip("/") + "/"
    if not pubspec.is_file():
        raise SystemExit(f"ERROR: pubspec not found: {pubspec}")
    text = pubspec.read_text(encoding="utf-8")
    entry = f"    - {asset}"
    if entry in text:
        print(f"already registered {asset}")
        return 0

    lines = text.splitlines()
    flutter_idx = next((i for i, line in enumerate(lines) if line == "flutter:"), None)
    if flutter_idx is None:
        lines.extend(["", "flutter:", "  assets:", entry])
    else:
        assets_idx = None
        for i in range(flutter_idx + 1, len(lines)):
            if lines[i] and not lines[i].startswith(" "):
                break
            if lines[i].strip() == "assets:":
                assets_idx = i
                break
        if assets_idx is None:
            insert_at = flutter_idx + 1
            lines.insert(insert_at, "  assets:")
            lines.insert(insert_at + 1, entry)
        else:
            insert_at = assets_idx + 1
            while insert_at < len(lines) and lines[insert_at].startswith("    - "):
                insert_at += 1
            lines.insert(insert_at, entry)
    pubspec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"registered {asset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
