#!/usr/bin/env python3
"""Cross-process mutex for the shared emulator/simulator window (steps 9-11).

Fan-out is truly parallel; the ONLY contended resource is the device
(install/launch/screenshot). Workers must hold this lock for their device
window and release it in every exit path. mkdir is the atomic primitive, so
the lock works across independent worker processes with no daemon.

  acquire: python3 device_lock.py acquire --lock <proj>/.iff/device.lock --label <row> [--timeout 900] [--stale 1800]
  release: python3 device_lock.py release --lock <proj>/.iff/device.lock
  status:  python3 device_lock.py status  --lock <proj>/.iff/device.lock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def read_owner(lock: Path) -> dict:
    try:
        return json.loads((lock / "owner.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def acquire(lock: Path, label: str, timeout: float, stale: float) -> int:
    deadline = time.time() + timeout
    while True:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.mkdir()  # atomic
            (lock / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "label": label, "acquired_at": time.time()}),
                encoding="utf-8")
            print(f"ok device lock acquired by {label!r}")
            return 0
        except FileExistsError:
            age = time.time() - lock.stat().st_mtime
            if age > stale:
                owner = read_owner(lock)
                print(f"WARNING: breaking stale device lock (age {age:.0f}s > {stale:.0f}s, "
                      f"owner {owner.get('label')!r} pid {owner.get('pid')})", file=sys.stderr)
                try:
                    (lock / "owner.json").unlink(missing_ok=True)
                    lock.rmdir()
                except OSError:
                    pass
                continue
            if time.time() >= deadline:
                owner = read_owner(lock)
                print(f"ERROR: device lock timeout after {timeout:.0f}s "
                      f"(held by {owner.get('label')!r} pid {owner.get('pid')})", file=sys.stderr)
                return 1
            time.sleep(2)


def release(lock: Path) -> int:
    try:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()
        print("ok device lock released")
    except FileNotFoundError:
        print("WARNING: device lock was not held", file=sys.stderr)
    except OSError as exc:
        print(f"ERROR: device lock release failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["acquire", "release", "status"])
    parser.add_argument("--lock", required=True, help="lock directory path, e.g. <project>/.iff/device.lock")
    parser.add_argument("--label", default=f"pid-{os.getpid()}", help="who is asking (row title)")
    parser.add_argument("--timeout", type=float, default=900, help="acquire wait seconds")
    parser.add_argument("--stale", type=float, default=1800, help="break locks older than this many seconds")
    args = parser.parse_args()

    lock = Path(args.lock).expanduser()
    if args.action == "acquire":
        return acquire(lock, args.label, args.timeout, args.stale)
    if args.action == "release":
        return release(lock)
    owner = read_owner(lock) if lock.is_dir() else {}
    print(json.dumps({"held": lock.is_dir(), **owner}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
