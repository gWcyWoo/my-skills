#!/usr/bin/env python3
"""Read-only, fail-fast preflight surfaces for ICP P1a.

P1a implements only the read-only half of the pipeline:

* a hard platform/profile/capability support gate that fail-closes every
  registered platform (returns ``unsupported_platform`` before any TaskSource
  access for all seven);
* direct, independently-testable preflight functions for the CSV TaskSource,
  the ``lanhu-figma`` DesignSource locator, and the project root.

No function in this module mutates task bytes, project-root contents, or row
state, and none ever leaves a probe file behind.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import icp_common

import platform_package_resolver_v1 as _package_resolver
from platforms import platform_package_contract_v1 as _package_contract

SCRIPT_NAME = "preflight_selection.py"

# P1 canonical CSV headers (P2 owns aliases such as the Chinese forms).
P1_STATUS_HEADER = "status"
P1_DESIGN_URL_HEADER = "design_url"
P1_REQUIRED_HEADERS = (P1_STATUS_HEADER, P1_DESIGN_URL_HEADER)
P1_VALID_STATUSES = frozenset({"", "doing", "done", "error"})

# Design locator (lanhu-figma) syntax check: https URL on a lanhu or figma host
# with a non-empty path. P1a does no network/auth checks.
_DESIGN_LOCATOR_RE = re.compile(
    r"^https://([a-z0-9-]+\.)*(lanhuapp\.com|figma\.com)/.+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    code: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _ok(details: dict[str, Any] | None = None) -> PreflightResult:
    return PreflightResult(ok=True, details=details or {})


def _fail(code: str, message: str) -> PreflightResult:
    return PreflightResult(ok=False, code=code, message=message)


# ---------------------------------------------------------------------------
# Support gate: platform / profile / capability. Fail-closed for all 7 in P1a.
# ---------------------------------------------------------------------------


def support_gate(config: dict[str, Any], registries: dict[str, Any]) -> PreflightResult:
    """Hard support gate. Returns before any TaskSource access in P1a."""
    platform = config.get("platform")
    platforms = registries.get("platforms", {})
    if platform not in platforms:
        return _fail(
            icp_common.UNSUPPORTED_PLATFORM,
            f"unsupported platform: {platform!r}; allowed: {sorted(platforms)}",
        )
    entry = platforms[platform] or {}
    if not entry.get("activated"):
        return _fail(
            icp_common.UNSUPPORTED_PLATFORM,
            f"platform not yet activated in P1a: {platform!r}",
        )
    # Profile is validated upstream by resolve_run_config; double-check anyway.
    profile = config.get("profile")
    valid_profiles = entry.get("profiles") or []
    if profile is not None and profile not in valid_profiles:
        return _fail(
            icp_common.UNSUPPORTED_PROFILE,
            f"unsupported profile {profile!r} for platform {platform!r}",
        )
    # Capability check (relevant once platforms activate in P2).
    cap = _check_mandatory_capabilities(registries)
    if cap is not None:
        return cap
    return _ok({"platform": platform, "profile": profile})


def _check_mandatory_capabilities(registries: dict[str, Any]) -> PreflightResult | None:
    """Return a missing_mandatory_capability failure if any 'required' capability
    is recorded as 'unsupported'. In P1a no capability is recorded unsupported,
    so this always returns None; the function exists so the gate is honest."""
    states = set(registries.get("capability_states", []))
    capabilities = registries.get("capabilities", {})
    for op_id, state in capabilities.items():
        if state not in states:
            return _fail(
                icp_common.MISSING_MANDATORY_CAPABILITY,
                f"capability {op_id!r} has unknown state {state!r}",
            )
    return None


# ---------------------------------------------------------------------------
# CSV TaskSource direct preflight (reused by P1b/P2).
# ---------------------------------------------------------------------------


def _parse_p1_csv(data: bytes) -> tuple[bool, str, dict[str, Any]]:
    """Return (ok, message, info). info contains header indices on success.

    Structurally strict: uses the standard library CSV parser in ``strict``
    mode so an actually unclosed quoted field (``csv.Error: unexpected end of
    data``) is rejected, while RFC 4180 quoted fields with embedded newlines
    are accepted. Also rejects duplicate canonical ``status`` / ``design_url``
    headers, missing headers, invalid statuses, and column-count mismatches.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, f"CSV must be UTF-8: {exc}", {}
    if text == "":
        return False, "CSV is empty", {}

    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        return False, f"CSV parse error: {exc}", {}
    if not rows:
        return False, "CSV is empty", {}
    headers = rows[0]

    header_counts: dict[str, int] = {}
    for h in headers:
        header_counts[h] = header_counts.get(h, 0) + 1
    for canonical in P1_REQUIRED_HEADERS:
        if header_counts.get(canonical, 0) > 1:
            return False, (
                f"CSV has duplicate {canonical!r} header; headers={headers!r}"
            ), {}

    header_index = {name: idx for idx, name in enumerate(headers)}
    missing = [h for h in P1_REQUIRED_HEADERS if h not in header_index]
    if missing:
        return False, f"CSV missing required P1 header(s) {missing}; headers={headers!r}", {}
    status_idx = header_index[P1_STATUS_HEADER]
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(headers):
            return False, (
                f"CSV row {row_number} has {len(row)} columns; expected {len(headers)}"
            ), {}
        status_value = row[status_idx]
        if status_value not in P1_VALID_STATUSES:
            return False, (
                f"CSV row {row_number} has invalid status {status_value!r}; "
                f"allowed: {sorted(P1_VALID_STATUSES)}"
            ), {}
    return True, "", {"rows": len(rows) - 1, "headers": headers}


def _probe_atomic_replace(directory: Path) -> str | None:
    """Create/write/fsync/rename/delete a probe in ``directory``.

    Returns an error message string on failure or ``None`` on success. Never
    leaves a probe file behind: the cleanup is in a finally block.
    """
    directory = Path(directory)
    try:
        fd, name_a = tempfile.mkstemp(
            prefix=".icp-probe-", suffix=".tmp", dir=str(directory)
        )
    except OSError as exc:
        return f"cannot create probe in task directory {directory}: {exc}"
    path_a = Path(name_a)
    path_b = directory / f"{path_a.name}.rename"
    try:
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(b"icp-probe")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            return f"probe write/fsync failed in {directory}: {exc}"
        try:
            os.replace(path_a, path_b)
        except OSError as exc:
            return f"probe atomic-replace failed in {directory}: {exc}"
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            return f"probe directory fsync failed in {directory}: {exc}"
    finally:
        for leftover in (path_a, path_b):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                return f"probe cleanup failed for {leftover}: {exc}"
    # Only reason about the exact temporary paths this invocation owned; never
    # scan the directory for arbitrary names containing "probe" (that would
    # falsely reject a pre-existing file like ``customer_probe_data.txt``).
    return None


def preflight_csv_task_source(path: Path | str) -> PreflightResult:
    """Read-only CSV TaskSource preflight.

    * ``.csv`` only; ``.xlsx`` (and any other suffix) returns
      ``unsupported_task_format``.
    * Existing ordinary non-symlink file.
    * Parseable CSV with the exact P1 canonical headers ``status`` and
      ``design_url`` (P2 owns aliases).
    * Every status cell is one of empty/doing/done/error.
    * Acquires and releases a ``fcntl.flock`` shared lock during inspection.
    * A same-directory create/write/fsync/rename/delete probe proves
      atomic-replace directory access.
    * Never modifies task bytes, row state, or leaves a probe.
    """
    task_path = Path(path)
    suffix = task_path.suffix.lower()
    if suffix == ".xlsx":
        return _fail(
            icp_common.UNSUPPORTED_TASK_FORMAT,
            ".xlsx task format is not supported in P1a",
        )
    if suffix != ".csv":
        return _fail(
            icp_common.UNSUPPORTED_TASK_FORMAT,
            f"unsupported task format suffix: {suffix or '<none>'}; only .csv is accepted",
        )
    if task_path.is_symlink():
        return _fail(
            icp_common.TASK_PREFLIGHT_FAILED,
            f"task path must not be a symlink: {task_path}",
        )
    try:
        st = task_path.stat()
    except FileNotFoundError:
        return _fail(
            icp_common.TASK_PREFLIGHT_FAILED,
            f"task file not found: {task_path}",
        )
    except OSError as exc:
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, f"cannot stat task file: {exc}")
    if not stat.S_ISREG(st.st_mode):
        return _fail(
            icp_common.TASK_PREFLIGHT_FAILED,
            f"task path is not a regular file: {task_path}",
        )

    try:
        before = task_path.read_bytes()
    except OSError as exc:
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, f"cannot read task file: {exc}")

    parse_ok, parse_msg, parse_info = _parse_p1_csv(before)
    if not parse_ok:
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, parse_msg)

    # Acquire/release a shared flock while re-reading to ensure consistent
    # snapshot. The file is opened read-only; the lock releases on close.
    locked_read: bytes | None = None
    try:
        with task_path.open("rb") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
                locked_read = handle.read()
            finally:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError as exc:
        try:
            after = task_path.read_bytes()
        except OSError:
            after = before
        if after != before:
            return _fail(
                icp_common.TASK_PREFLIGHT_FAILED,
                f"task bytes changed during failed lock: {exc}",
            )
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, f"cannot lock/read task file: {exc}")

    if locked_read is not None and locked_read != before:
        return _fail(
            icp_common.TASK_PREFLIGHT_FAILED,
            "task file changed between initial read and locked read",
        )

    probe_error = _probe_atomic_replace(task_path.parent)
    if probe_error is not None:
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, probe_error)

    try:
        after = task_path.read_bytes()
    except OSError as exc:
        return _fail(icp_common.TASK_PREFLIGHT_FAILED, f"cannot re-read task file: {exc}")
    if after != before:
        return _fail(
            icp_common.TASK_PREFLIGHT_FAILED,
            "task bytes changed during preflight",
        )

    details = {
        "sha256": icp_common.sha256_hex(before),
        "rows": parse_info.get("rows", 0),
        "size": len(before),
    }
    return _ok(details)


# ---------------------------------------------------------------------------
# DesignSource (lanhu-figma) locator validation: syntax only, no network.
# ---------------------------------------------------------------------------


def preflight_design_locator(locator: Any) -> PreflightResult:
    if not isinstance(locator, str) or locator == "":
        return _fail(
            icp_common.DESIGN_PREFLIGHT_FAILED,
            "design locator must be a non-empty string",
        )
    if not _DESIGN_LOCATOR_RE.match(locator):
        return _fail(
            icp_common.DESIGN_PREFLIGHT_FAILED,
            f"malformed design locator (expected https://...lanhuapp.com|figma.com/...): {locator!r}",
        )
    return _ok({"locator": locator})


# ---------------------------------------------------------------------------
# Project root preflight: existing ordinary non-symlink directory.
# ---------------------------------------------------------------------------


def preflight_project_root(path: Path | str) -> PreflightResult:
    root = Path(path)
    if root.is_symlink():
        return _fail(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root must not be a symlink: {root}",
        )
    try:
        st = root.stat()
    except FileNotFoundError:
        return _fail(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root not found: {root}",
        )
    except OSError as exc:
        return _fail(icp_common.PROJECT_PREFLIGHT_FAILED, f"cannot stat project root: {exc}")
    if not stat.S_ISDIR(st.st_mode):
        return _fail(
            icp_common.PROJECT_PREFLIGHT_FAILED,
            f"project root is not a directory: {root}",
        )
    return _ok({"path": str(root)})


# ---------------------------------------------------------------------------
# Config-driven preflight entrypoint.
# ---------------------------------------------------------------------------

RESOLVED_REQUIRED_KEYS = (
    "task_source",
    "task_ref",
    "design_source",
    "platform",
    "project_root",
)
RESOLVED_ALLOWED_KEYS = frozenset(RESOLVED_REQUIRED_KEYS) | frozenset({"profile"})


def validate_resolved_config(config: Any) -> PreflightResult | None:
    """Return a failure result if ``config`` is not a valid resolved run-config.

    Accepts the exact shape emitted by ``resolve_run_config.py``: five required
    non-empty string fields plus an optional ``profile`` that is either null or
    a non-empty string. Any other shape (non-dict, missing/extra fields,
    wrong types) returns ``invalid_input``. Returns ``None`` when valid.
    """
    if not isinstance(config, dict):
        return _fail(
            icp_common.INVALID_INPUT,
            f"resolved config must be a JSON object, got {type(config).__name__}",
        )
    keys = set(config.keys())
    missing = [k for k in RESOLVED_REQUIRED_KEYS if k not in config]
    if missing:
        return _fail(
            icp_common.INVALID_INPUT,
            f"resolved config missing required field(s): {sorted(missing)}",
        )
    unexpected = sorted(keys - RESOLVED_ALLOWED_KEYS)
    if unexpected:
        return _fail(
            icp_common.INVALID_INPUT,
            f"resolved config has unexpected field(s): {unexpected}",
        )
    for key in RESOLVED_REQUIRED_KEYS:
        value = config[key]
        if not isinstance(value, str) or value == "":
            return _fail(
                icp_common.INVALID_INPUT,
                f"resolved config field {key!r} must be a non-empty string",
            )
    profile = config.get("profile")
    if profile is not None and not (isinstance(profile, str) and profile != ""):
        return _fail(
            icp_common.INVALID_INPUT,
            "resolved config field 'profile' must be null or a non-empty string",
        )
    return None


def preflight_from_config(config: dict[str, Any], registries: dict[str, Any]) -> PreflightResult:
    """Hard-ordered preflight: support gate first; never touches task_ref before it.

    In P1a every registered platform fails the gate (none activated), so this
    returns ``unsupported_platform`` without opening or stat-ing ``task_ref``.
    """
    validation = validate_resolved_config(config)
    if validation is not None:
        return validation
    gate = support_gate(config, registries)
    if not gate.ok:
        return gate
    # P2 will continue with task/design/project preflight here once platforms
    # activate. P1a never reaches this branch.
    return _ok({"platform": config.get("platform")})


# ---------------------------------------------------------------------------
# P3b1b2 inactive package-aware support gate.
# ---------------------------------------------------------------------------

_CODE_PLATFORM_PACKAGE_INACTIVE = "platform_package_inactive"
_CODE_INVALID_PLATFORM_PACKAGE = "invalid_platform_package"


def support_gate_package_aware(
    config: dict[str, Any],
    registries: dict[str, Any],
    package_resolution: dict[str, Any],
) -> PreflightResult:
    """Package-aware support gate (P3b1b2 inactive entry seam).

    Hard-ordered gate layered on top of :func:`support_gate`:

    1. ``support_gate(config, registries)`` first; return its exact result
       unchanged when it fails (so live registries still fail
       ``unsupported_platform`` before any package consultation).
    2. Verify the resolution document via
       ``platform_package_resolver_v1.verify_resolution``.
    3. Match the resolution's platform / profile to ``config``.
    4. Recompute the registry digest and selected-profile digest from the
       supplied ``registries`` and require equality with the resolution.
    5. A valid current v1 resolution is ``activation_state=inactive`` /
       ``executable=False`` (verifier-enforced), so the gate fails
       ``platform_package_inactive``.

    Any malformed / tampered / mismatched package context returns
    ``invalid_platform_package`` with a controlled safe message; no exception
    escapes. Never returns ok for a current valid v1 resolution.
    """
    # 1. Existing support gate first; propagate its exact failure unchanged.
    base = support_gate(config, registries)
    if not base.ok:
        return base

    # 2-4. Verify, match, and recompute digests inside a single defensive
    # try/except so any malformed / tampered / mismatched context fails closed
    # with the controlled ``invalid_platform_package`` code and a safe message
    # that never embeds paths / secrets / commands / row contents.
    try:
        if not isinstance(package_resolution, dict):
            raise ValueError("package_resolution must be an object")
        _package_resolver.verify_resolution(package_resolution)

        platform_id = config.get("platform")
        profile_id = config.get("profile")
        if package_resolution["platform_id"] != platform_id:
            raise ValueError("platform_id mismatch")
        if package_resolution["profile_id"] != profile_id:
            raise ValueError("profile_id mismatch")

        recomputed_registry_digest = (
            _package_contract.compute_registry_digest(registries)
        )
        if package_resolution["registry_digest"] != recomputed_registry_digest:
            raise ValueError("registry_digest drift")
        recomputed_selected_profile_digest = (
            _package_contract.compute_selected_profile_digest(
                registries, package_resolution["platform_id"],
                package_resolution["profile_id"],
            )
        )
        if (
            package_resolution["selected_profile_digest"]
            != recomputed_selected_profile_digest
        ):
            raise ValueError("selected_profile_digest drift")
    except Exception:  # noqa: BLE001
        return _fail(
            _CODE_INVALID_PLATFORM_PACKAGE,
            "invalid platform package context",
        )

    # 5. Only a verified active/executable package may enter task preparation.
    if package_resolution["activation_state"] != "active" or package_resolution["executable"] is not True:
        return _fail(
            _CODE_PLATFORM_PACKAGE_INACTIVE,
            "platform package is inactive and non-executable",
        )
    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Run read-only ICP preflight on a resolved run-config.",
    )
    parser.add_argument("--config", required=True, help="Path to a resolved run-config JSON file.")
    args = parser.parse_args(argv)

    def _emit(code: str, message: str) -> int:
        sys.stderr.write(icp_common.failure_json(code, message).decode("utf-8"))
        return 1

    # Read the config bytes and strict-decode: non-object roots, duplicate
    # keys, malformed JSON, and non-UTF-8 are all rejected as invalid_input
    # without a traceback.
    try:
        config_path = Path(args.config).expanduser()
        raw = config_path.read_bytes()
    except FileNotFoundError as exc:
        return _emit(icp_common.INVALID_INPUT, f"config not found: {exc}")
    except OSError as exc:
        return _emit(icp_common.INVALID_INPUT, f"cannot read config: {exc}")

    try:
        config = icp_common.decode_strict_config(raw)
    except icp_common.ConfigError as exc:
        return _emit(exc.code, exc.message)

    # Validate resolved-config shape before any registry access.
    validation = validate_resolved_config(config)
    if validation is not None:
        return _emit(validation.code, validation.message)

    try:
        registries = icp_common.load_registries()
    except icp_common.ConfigError as exc:
        return _emit(exc.code, exc.message)

    result = preflight_from_config(config, registries)
    if result.ok:
        payload = {"ok": True, "code": "", "message": "", "details": result.details}
        sys.stdout.write(icp_common.canonical_json_bytes(payload).decode("utf-8"))
        return 0
    sys.stderr.write(
        icp_common.failure_json(result.code, result.message).decode("utf-8")
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
