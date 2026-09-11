#!/usr/bin/env python3
import json
import sys
from urllib.parse import parse_qs, urlparse


def main() -> int:
    source_url = sys.argv[1]
    parsed = urlparse(source_url)
    path_parts = parsed.path.strip("/").split("/")
    if (
        parsed.hostname != "docs.google.com"
        or path_parts[:2] != ["spreadsheets", "d"]
        or len(path_parts) < 3
        or not path_parts[2]
    ):
        print(
            json.dumps({"error": "unsupported_source", "url": source_url}),
            file=sys.stderr,
        )
        return 2
    spreadsheet_id = path_parts[2]
    gid = parse_qs(parsed.fragment).get("gid", [None])[0]
    print(
        json.dumps(
            {
                "provider": "google_sheets",
                "spreadsheet_id": spreadsheet_id,
                "gid": gid,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
