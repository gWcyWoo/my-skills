#!/usr/bin/env python3
"""Strict JSON run-config resolver for ICP P1a.

CLI:
    resolve_run_config.py --config CONFIG.json --cwd DIR

The executable input is exactly one JSON object with required keys
``task_source``, ``task_ref``, ``design_source``, ``platform``, ``project_root``
and the single optional key ``profile``. Anything else (unknown keys,
non-string values, empty strings, duplicate JSON keys, non-object roots,
missing keys) returns ``invalid_input``. ID and profile values must be exact
registry allowlist entries; ``task_ref`` and ``project_root`` are pure path
locators canonicalized against the explicit ``--cwd``.

Success emits canonical JSON (sorted keys, two-space indent) to stdout.
Failure emits exactly one JSON object to stderr with ``ok=false``, a public
``code``, and a ``message``; never a traceback.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import icp_common

REQUIRED_KEYS = (
    "task_source",
    "task_ref",
    "design_source",
    "platform",
    "project_root",
)
OPTIONAL_KEYS = ("profile",)
ALLOWED_KEYS = frozenset(REQUIRED_KEYS) | frozenset(OPTIONAL_KEYS)

SCRIPT_NAME = "resolve_run_config.py"


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _resolve_locator(base: Path, rel: str) -> str:
    """Convert a relative path locator to a normalized absolute path against
    ``base``.

    Intermediate symlinks in the parent chain are resolved (so ``..`` and
    ``.`` collapse and the absolute root is canonical), but the **final path
    component is never dereferenced**: a ``task_ref`` or ``project_root`` that
    is itself a symlink stays a symlink so the read-only preflight symlink gate
    can detect and reject it. Shell-looking characters in a legitimate path
    remain inert because this function never passes the string to a shell.
    """
    full = base / rel
    lex = Path(os.path.normpath(str(full)))
    parent_lex = lex.parent
    if str(parent_lex) in ("", "."):
        resolved_parent = base.resolve()
    else:
        try:
            resolved_parent = parent_lex.resolve()
        except OSError:
            resolved_parent = parent_lex
    return str(resolved_parent / lex.name)


def resolve_config(config: dict[str, Any], cwd: Path, registries: dict[str, Any]) -> dict[str, Any]:
    """Resolve an already-decoded config object against ``registries``.

    Raises :class:`icp_common.ConfigError` with a public code on any deviation.
    """
    keys = set(config.keys())
    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise icp_common.ConfigError(
            icp_common.INVALID_INPUT,
            f"missing required key(s): {sorted(missing)}",
        )
    unknown = sorted(keys - ALLOWED_KEYS)
    if unknown:
        raise icp_common.ConfigError(
            icp_common.INVALID_INPUT,
            f"unknown config key(s): {unknown}; only {sorted(ALLOWED_KEYS)} are accepted",
        )

    # Every value present must be a non-empty string (profile is checked below).
    for key in REQUIRED_KEYS:
        if not _is_nonempty_str(config[key]):
            raise icp_common.ConfigError(
                icp_common.INVALID_INPUT,
                f"{key} must be a non-empty string",
            )

    profile: Any = None
    if "profile" in config:
        profile = config["profile"]
        if not _is_nonempty_str(profile):
            raise icp_common.ConfigError(
                icp_common.INVALID_INPUT,
                "profile must be a non-empty string when present",
            )

    task_source = config["task_source"]
    if task_source not in registries["task_sources"]:
        raise icp_common.ConfigError(
            icp_common.UNSUPPORTED_TASK_SOURCE,
            f"unsupported task_source: {task_source!r}; allowed: {registries['task_sources']}",
        )

    design_source = config["design_source"]
    if design_source not in registries["design_sources"]:
        raise icp_common.ConfigError(
            icp_common.UNSUPPORTED_DESIGN_SOURCE,
            f"unsupported design_source: {design_source!r}; allowed: {registries['design_sources']}",
        )

    platform = config["platform"]
    platforms = registries["platforms"]
    if platform not in platforms:
        raise icp_common.ConfigError(
            icp_common.UNSUPPORTED_PLATFORM,
            f"unsupported platform: {platform!r}; allowed: {sorted(platforms)}",
        )
    platform_entry = platforms[platform]
    valid_profiles = platform_entry.get("profiles") or []
    if profile is None or profile == "":
        profile = platform_entry.get("default_profile")
    else:
        if profile not in valid_profiles:
            raise icp_common.ConfigError(
                icp_common.UNSUPPORTED_PROFILE,
                f"unsupported profile {profile!r} for platform {platform!r}; "
                f"allowed: {valid_profiles}",
            )

    # task_ref and project_root are path locators only: resolve relative to the
    # explicit --cwd, normalize lexically and resolve intermediate symlinks,
    # but preserve the final component so the preflight symlink gate works.
    # Never execute or pass these strings to a shell.
    base = Path(cwd).expanduser().resolve()
    task_ref = _resolve_locator(base, config["task_ref"])
    project_root = _resolve_locator(base, config["project_root"])

    return {
        "task_source": task_source,
        "task_ref": task_ref,
        "design_source": design_source,
        "platform": platform,
        "profile": profile,
        "project_root": project_root,
    }


def _emit_failure(code: str, message: str) -> int:
    sys.stderr.write(icp_common.failure_json(code, message).decode("utf-8"))
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Resolve a strict ICP JSON run-config to canonical form.",
    )
    parser.add_argument("--config", required=True, help="Path to the JSON run-config file.")
    parser.add_argument("--cwd", required=True, help="Directory against which relative paths resolve.")
    args = parser.parse_args(argv)

    try:
        cwd = Path(args.cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise icp_common.ConfigError(
                icp_common.INVALID_INPUT,
                f"--cwd is not an existing directory: {cwd}",
            )
        config_path = Path(args.config).expanduser()
        raw = config_path.read_bytes()
    except icp_common.ConfigError as exc:
        return _emit_failure(exc.code, exc.message)
    except FileNotFoundError as exc:
        return _emit_failure(icp_common.INVALID_INPUT, f"config file not found: {exc}")
    except OSError as exc:
        return _emit_failure(icp_common.INVALID_INPUT, f"cannot read config: {exc}")

    try:
        config = icp_common.decode_strict_config(raw)
        registries = icp_common.load_registries()
        resolved = resolve_config(config, cwd, registries)
    except icp_common.ConfigError as exc:
        return _emit_failure(exc.code, exc.message)

    sys.stdout.write(icp_common.canonical_json_bytes(resolved).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
