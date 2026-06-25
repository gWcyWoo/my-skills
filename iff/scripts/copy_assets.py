#!/usr/bin/env python3
"""Copy all exported design assets referenced by a manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from common import dump_json, load_json


def iter_assets(manifest):
    if isinstance(manifest, dict):
        for key, value in manifest.items():
            if isinstance(value, str):
                yield key, value
            elif isinstance(value, dict):
                path = value.get("path") or value.get("asset") or value.get("file")
                if isinstance(path, str):
                    yield key, path
    elif isinstance(manifest, list):
        for item in manifest:
            if isinstance(item, str):
                yield Path(item).stem, item
            elif isinstance(item, dict):
                path = item.get("path") or item.get("asset") or item.get("file")
                key = item.get("id") or item.get("node") or (Path(path).stem if path else None)
                if isinstance(path, str) and key:
                    yield str(key), path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    base = manifest_path.parent
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    manifest = load_json(manifest_path)
    copied = {}
    missing = []
    for key, rel in iter_assets(manifest):
        src = Path(rel)
        if not src.is_absolute():
            src = base / src
        if not src.is_file():
            missing.append(str(src))
            continue
        dest = target / src.name
        shutil.copy2(src, dest)
        copied[key] = str(dest)
    if missing:
        raise SystemExit("ERROR: missing assets:\n" + "\n".join(missing))
    if not copied:
        raise SystemExit("ERROR: assets manifest contained no copyable assets.")
    dump_json(copied, target / "manifest.json")
    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
