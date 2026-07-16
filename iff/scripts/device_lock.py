#!/usr/bin/env python3
"""Cross-process mutex for the shared emulator/simulator I/O window (steps 9-11).

Fan-out is truly parallel; the ONLY contended resource is device I/O
(install/launch/screenshot — builds and repair edits stay OUTSIDE the lock).
Workers must hold this lock for each short capture window and release it in
every exit path. mkdir is the atomic primitive, so the lock works across
independent worker processes with no daemon.

Single device (default, unchanged):
  acquire: python3 device_lock.py acquire --lock <proj>/.iff/device.lock --label <row> [--timeout 900] [--stale 1800]
  release: python3 device_lock.py release --lock <proj>/.iff/device.lock
  status:  python3 device_lock.py status  --lock <proj>/.iff/device.lock

Device pool (identical emulator profiles required — width/density/banner/clock):
  acquire: python3 device_lock.py acquire --lock <proj>/.iff/device.lock --pool "emulator-5554,emulator-5556" --label <row>
           -> grabs the first free device; stdout last line is JSON {"device": ..., "lock": ...}
  release: python3 device_lock.py release --lock <proj>/.iff/device.lock --device emulator-5554
  status:  python3 device_lock.py status  --lock <proj>/.iff/device.lock --pool "emulator-5554,emulator-5556"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def pool_lock_path(base: Path, device: str) -> Path:
    return base.with_name(base.name + "." + re.sub(r"[^A-Za-z0-9._-]", "_", device))


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


def try_once(lock: Path, label: str, stale: float) -> bool:
    """One non-blocking acquire attempt with stale-breaking. True = lock held."""
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.mkdir()  # atomic
        (lock / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "label": label, "acquired_at": time.time()}),
            encoding="utf-8")
        return True
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except FileNotFoundError:
            return False  # raced with a release; next round retries
        if age > stale:
            owner = read_owner(lock)
            print(f"WARNING: breaking stale device lock (age {age:.0f}s > {stale:.0f}s, "
                  f"owner {owner.get('label')!r} pid {owner.get('pid')})", file=sys.stderr)
            try:
                (lock / "owner.json").unlink(missing_ok=True)
                lock.rmdir()
            except OSError:
                pass
        return False


def acquire_pool(base: Path, devices: list[str], label: str, timeout: float, stale: float) -> int:
    deadline = time.time() + timeout
    while True:
        for device in devices:
            lock = pool_lock_path(base, device)
            if try_once(lock, label, stale):
                print(f"ok device lock acquired by {label!r} on {device}", file=sys.stderr)
                print(json.dumps({"device": device, "lock": str(lock)}, ensure_ascii=False))
                return 0
        if time.time() >= deadline:
            owners = {d: read_owner(pool_lock_path(base, d)).get("label") for d in devices}
            print(f"ERROR: device pool lock timeout after {timeout:.0f}s (owners: {owners})",
                  file=sys.stderr)
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
    parser.add_argument("--pool", help="comma-separated device ids; acquire grabs the first free one "
                                       "and prints JSON {'device':...,'lock':...} on stdout")
    parser.add_argument("--device", help="pool mode: which device's lock to release / inspect")
    args = parser.parse_args()

    lock = Path(args.lock).expanduser()
    devices = [d.strip() for d in (args.pool or "").split(",") if d.strip()]
    if args.action == "acquire":
        if devices:
            return acquire_pool(lock, devices, args.label, args.timeout, args.stale)
        return acquire(lock, args.label, args.timeout, args.stale)
    if args.action == "release":
        if args.device:
            return release(pool_lock_path(lock, args.device))
        return release(lock)
    if devices:
        print(json.dumps({d: {"held": pool_lock_path(lock, d).is_dir(),
                              **read_owner(pool_lock_path(lock, d))} for d in devices},
                         ensure_ascii=False))
        return 0
    owner = read_owner(lock) if lock.is_dir() else {}
    print(json.dumps({"held": lock.is_dir(), **owner}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
