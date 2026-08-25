"""Device dispatcher — import the right device module by --target."""
from __future__ import annotations

import importlib
import subprocess


def run(cmd, timeout=60, check=True, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstderr: {r.stderr[:500]}")
    return r

TARGET_MODULES = {
    "android": "device_android",
    "ios": "device_ios",
    "web": "device_web",
}


def load(target: str):
    return importlib.import_module(TARGET_MODULES[target])
