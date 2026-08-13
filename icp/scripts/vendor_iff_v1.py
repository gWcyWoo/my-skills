#!/usr/bin/env python3
"""Maintenance-only refresh/check tool for the ICP P2a iFF v1 capsule.

This tool is NOT part of normal ICP execution. It rebuilds the vendored
``vendor/iff_v1/scripts/`` capsule from a read-only ``iff/`` source using
the fixed P0 baseline (``references/baselines/iff-v1.json``) as the sole
source of truth for the copy set and the expected SHA-256 values. Live
source bytes are never used to generate expectations; only the P0 baseline
is.

The capsule and manifest are published atomically. A failure preserves an
existing capsule byte-for-byte and leaves no temporary tree behind.

Source ``--iff-root`` and output ``--capsule-root`` are the explicit CLI
inputs. The P0 baseline path and the manifest output path are derived from
this file's installed location (no override) so production runs always bind
to the committed baseline.

CLI output is exactly one canonical JSON object on stdout for success (exit
0) or one canonical JSON object on stderr for failure (exit 2). No
traceback. Errors are local to this maintenance/integrity tool and never
add undeclared ICP pre-claim public error codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
KIND = "icp.iff-v1-vendor-capsule"
SCRIPT_NAME = "vendor_iff_v1.py"

# Fixed production layout (relative to the ICP skill root). Both the
# baseline path and the manifest path are derived from this module's
# installed location; no override.
SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = SKILL_ROOT / "references" / "baselines" / "iff-v1.json"
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
DEFAULT_CAPSULE_REL = "vendor/iff_v1"

# Local error codes for the maintenance CLI surface. These are NOT ICP
# pre-claim codes and never extend icp_common.ALL_ERROR_CODES.
CODE_CLI = "vendor_cli_error"
CODE_INTEGRITY = "vendor_integrity_failed"


class VendorError(ValueError):
    """A local maintenance-tool failure."""


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise VendorError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _is_safe_basename(name: str) -> bool:
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or name in {".", ".."} or "\x00" in name:
        return False
    if name != os.path.basename(name):
        return False
    return name.endswith(".py")


def _check_regular_file(path: Path, role: str) -> None:
    """Verify path is a regular non-symlink file with read access."""
    try:
        if path.is_symlink():
            raise VendorError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise VendorError(f"{role}: cannot lstat {path}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise VendorError(f"{role}: not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise VendorError(f"{role}: unreadable file: {path}")


def _check_regular_dir(path: Path, role: str) -> None:
    """Verify path is a regular non-symlink directory."""
    try:
        if path.is_symlink():
            raise VendorError(f"{role}: refusing symlink dir: {path}")
        st = path.lstat()
    except OSError as exc:
        raise VendorError(f"{role}: cannot lstat dir {path}: {exc}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise VendorError(f"{role}: not a directory: {path}")


def _check_path_chain_no_symlink(path: Path, role: str) -> None:
    """Reject if any existing component of the absolute form of ``path`` is a
    symlink. Does NOT call ``.resolve()`` on the whole path — the user-supplied
    path identity is preserved and inspected component-by-component.

    This catches intermediate symlinks, not only the leaf. On macOS,
    ``os.path.abspath`` does NOT resolve symlinks (only normalizes ``.`` and
    ``..``), so caller-supplied symlinks are preserved and detected.
    """
    abs_path = Path(os.path.abspath(str(path)))
    root = abs_path.anchor or "/"
    current = Path(root)
    for part in abs_path.parts[1:]:
        current = current / part
        if os.path.islink(str(current)):
            raise VendorError(
                f"{role}: refusing symlink in path chain: {current}"
            )


def _check_safe_relative_path(rel: str, role: str) -> None:
    """A relative path used in the manifest must be POSIX, no '..'/NUL/abs."""
    if not isinstance(rel, str) or not rel:
        raise VendorError(f"{role}: empty relative path")
    if rel.startswith("/"):
        raise VendorError(f"{role}: absolute path: {rel!r}")
    if "\x00" in rel:
        raise VendorError(f"{role}: NUL in path: {rel!r}")
    parts = rel.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise VendorError(f"{role}: unsafe path components: {rel!r}")


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# P0 baseline loader (the sole source of truth).
# ---------------------------------------------------------------------------


def load_baseline(baseline_path: Path) -> dict[str, Any]:
    """Load and validate the fixed P0 baseline JSON.

    The baseline is the only source of truth for the copy set and SHA values.
    """
    _check_regular_file(baseline_path, "baseline")
    try:
        raw = baseline_path.read_bytes()
    except OSError as exc:
        raise VendorError(f"cannot read baseline {baseline_path}: {exc}") from exc
    try:
        baseline = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise VendorError(f"baseline is not valid JSON: {exc}") from exc
    if not isinstance(baseline, dict):
        raise VendorError("baseline root must be a JSON object")
    if baseline.get("kind") != "iff-baseline-freeze":
        raise VendorError(f"baseline kind unexpected: {baseline.get('kind')!r}")
    sv = baseline.get("schema_version")
    if not isinstance(sv, int) or sv != 1:
        raise VendorError(f"baseline schema_version unexpected: {sv!r}")
    scripts = baseline.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise VendorError("baseline scripts missing/empty")
    for entry in scripts:
        if not isinstance(entry, dict):
            raise VendorError("baseline script entry not an object")
        sp = entry.get("path")
        if not isinstance(sp, str) or not sp.startswith("iff/scripts/"):
            raise VendorError(f"baseline script path unexpected: {sp!r}")
        name = sp.rsplit("/", 1)[-1]
        if not _is_safe_basename(name):
            raise VendorError(f"baseline script name unsafe: {sp!r}")
        sha = entry.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or not sha.islower():
            raise VendorError(f"baseline sha256 malformed: {sha!r}")
        if not isinstance(entry.get("in_required_registry"), bool):
            raise VendorError(f"baseline in_required_registry not bool: {sp!r}")
    counts = baseline.get("counts")
    if isinstance(counts, dict):
        for key in ("scripts_total", "scripts_in_required", "scripts_not_in_required"):
            if not isinstance(counts.get(key), int):
                raise VendorError(f"baseline counts.{key} not int")
    return baseline


def expected_copy_set(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the deterministic copy list, derived only from the P0 baseline.

    Each entry has ``name``, ``source_path`` (``iff/scripts/<name>``),
    ``dest_path`` (``scripts/<name>``), ``sha256`` (from baseline), and
    ``in_required_registry``. Sorted by source path for determinism.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in sorted(baseline["scripts"], key=lambda e: e["path"]):
        name = entry["path"].rsplit("/", 1)[-1]
        if name in seen:
            raise VendorError(f"baseline duplicate basename: {name!r}")
        seen.add(name)
        out.append(
            {
                "name": name,
                "source_path": entry["path"],
                "dest_path": "scripts/" + name,
                "sha256": entry["sha256"],
                "in_required_registry": bool(entry["in_required_registry"]),
            }
        )
    return out


def manifest_payload(
    copy_set: list[dict[str, Any]],
    baseline_path: Path,
    capsule_rel: str,
) -> dict[str, Any]:
    """Build the canonical manifest payload (deterministic)."""
    _check_safe_relative_path(capsule_rel, "capsule_root")
    counts_required = sum(1 for e in copy_set if e["in_required_registry"])
    counts_non_required = sum(1 for e in copy_set if not e["in_required_registry"])
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "capsule_root": capsule_rel,
        "baseline": {
            "path": "references/baselines/iff-v1.json",
            "sha256": _sha256_file(baseline_path),
        },
        "counts": {
            "scripts_total": len(copy_set),
            "scripts_in_required": counts_required,
            "scripts_not_in_required": counts_non_required,
        },
        "scripts": copy_set,
    }


def manifest_bytes(
    copy_set: list[dict[str, Any]],
    baseline_path: Path,
    capsule_rel: str,
) -> bytes:
    return _canonical_json_bytes(
        manifest_payload(copy_set, baseline_path, capsule_rel)
    )


# ---------------------------------------------------------------------------
# Capsule comparison + publication.
# ---------------------------------------------------------------------------


def _read_existing_capsule_files(capsule_root: Path) -> dict[str, bytes]:
    """Read every .py file under capsule_root/scripts/. Refuse extras.

    There is no ``__pycache__`` exemption: the exact capsule set is exactly
    the 165 manifest entries.
    """
    scripts_dir = capsule_root / "scripts"
    if not scripts_dir.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for item in sorted(scripts_dir.iterdir()):
        if item.is_dir():
            raise VendorError(
                f"existing capsule has unexpected directory: {item.name}"
            )
        if item.is_symlink():
            raise VendorError(
                f"existing capsule has symlink: {item.name}"
            )
        _check_regular_file(item, f"existing capsule file {item.name}")
        if not item.name.endswith(".py"):
            raise VendorError(
                f"existing capsule has non-.py file: {item.name}"
            )
        out[item.name] = item.read_bytes()
    return out


def _existing_capsule_matches(
    capsule_root: Path, expected: dict[str, bytes]
) -> bool:
    """True iff capsule_root/scripts/ contains exactly expected bytes."""
    if capsule_root.is_symlink():
        raise VendorError(f"refusing symlink capsule-root: {capsule_root}")
    if not capsule_root.exists():
        return False
    _check_regular_dir(capsule_root, "existing-capsule")
    existing = _read_existing_capsule_files(capsule_root)
    if set(existing) != set(expected):
        return False
    return all(existing[name] == expected[name] for name in expected)


def _stage_capsule(
    copy_set: list[dict[str, Any]],
    iff_scripts: Path,
    staging_scripts: Path,
) -> None:
    """Stage every capsule file under staging_scripts; verify SHAs from baseline."""
    staging_scripts.mkdir(mode=0o755, exist_ok=False)
    for entry in copy_set:
        src = iff_scripts / entry["name"]
        _check_regular_file(src, f"source {entry['name']}")
        data = src.read_bytes()
        actual_sha = _sha256_bytes(data)
        if actual_sha != entry["sha256"]:
            raise VendorError(
                f"source SHA mismatch for {entry['name']}: "
                f"expected={entry['sha256']} actual={actual_sha}"
            )
        dst = staging_scripts / entry["name"]
        if dst.exists():
            raise VendorError(f"staging collision: {dst}")
        with open(dst, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())


def refresh(
    iff_root: Path,
    capsule_root: Path,
    baseline_path: Path,
    manifest_path: Path,
    capsule_rel: str,
) -> dict[str, Any]:
    """Refresh the capsule + manifest.

    Publication is failure-preserving: if this process newly publishes the
    capsule and a later manifest publication step fails, the newly published
    capsule is rolled back (removed), the manifest remains absent, and no
    staging residue is left. A pre-existing identical capsule is never
    deleted or rolled back.

    Refuses to overwrite an existing non-identical capsule or manifest.
    Rejects symlinks for every caller-controlled path component (not only
    the leaf).
    """
    iff_root = iff_root.expanduser()
    capsule_root = capsule_root.expanduser()
    baseline_path = baseline_path.expanduser()
    manifest_path = manifest_path.expanduser()

    # Check every caller-controlled path component for symlinks. This rejects
    # intermediate symlinks, not only leaf symlinks. Do NOT .resolve() the
    # whole path — that would erase symlink identity.
    _check_path_chain_no_symlink(iff_root, "iff-root")
    _check_path_chain_no_symlink(capsule_root, "capsule-root")
    _check_path_chain_no_symlink(baseline_path, "baseline-path")
    _check_path_chain_no_symlink(manifest_path, "manifest-path")

    # Leaf checks (regular dir/file, non-symlink).
    _check_regular_dir(iff_root, "iff-root")
    iff_scripts = iff_root / "scripts"
    _check_regular_dir(iff_scripts, "iff-scripts")
    capsule_parent = capsule_root.parent
    if capsule_parent.exists():
        _check_regular_dir(capsule_parent, "capsule-parent")
    manifest_parent = manifest_path.parent
    if manifest_parent.exists():
        _check_regular_dir(manifest_parent, "manifest-parent")
    else:
        # The maintenance tool never creates the manifest parent in production;
        # it always exists. For test fixtures we create it explicitly.
        manifest_parent.mkdir(parents=True, exist_ok=False)

    baseline = load_baseline(baseline_path)
    copy_set = expected_copy_set(baseline)
    # Read every source file defensively so a missing/unreadable source is
    # surfaced as a VendorError (not a raw FileNotFoundError). The SHA is
    # expected only from the baseline; live source bytes are never used to
    # derive expectations.
    expected_files: dict[str, bytes] = {}
    for entry in copy_set:
        src = iff_scripts / entry["name"]
        _check_regular_file(src, f"source {entry['name']}")
        try:
            src_bytes = src.read_bytes()
        except OSError as exc:
            raise VendorError(
                f"cannot read source {entry['name']}: {exc}"
            ) from exc
        actual = _sha256_bytes(src_bytes)
        if actual != entry["sha256"]:
            raise VendorError(
                f"source SHA mismatch for {entry['name']}: "
                f"expected={entry['sha256']} actual={actual}"
            )
        expected_files[entry["name"]] = src_bytes

    new_manifest_bytes = manifest_bytes(copy_set, baseline_path, capsule_rel)

    # Compare with existing BEFORE any publication. If anything differs,
    # fail closed without mutating anything.
    existing_capsule = None
    if capsule_root.exists():
        existing_capsule = _read_existing_capsule_files(capsule_root)
        if set(existing_capsule) != set(expected_files) or any(
            existing_capsule[n] != expected_files[n] for n in expected_files
        ):
            raise VendorError(
                "existing capsule differs from refresh; refusing to overwrite"
            )
    existing_manifest_bytes: bytes | None = None
    if manifest_path.exists():
        _check_regular_file(manifest_path, "existing-manifest")
        existing_manifest_bytes = manifest_path.read_bytes()
        if existing_manifest_bytes != new_manifest_bytes:
            raise VendorError(
                "existing manifest differs from refresh; refusing to overwrite"
            )

    # Stage a complete sibling temporary tree. The capsule staging dir is a
    # sibling of capsule_root (in capsule_parent). The manifest staging file
    # is a sibling of manifest_path (in manifest_parent). Use mkstemp for
    # exclusive creation (never mktemp which is racy).
    staging_root = Path(
        tempfile.mkdtemp(prefix=".iff_v1_stage.", dir=str(capsule_parent))
    )
    fd, staging_manifest_name = tempfile.mkstemp(
        prefix=".iff-v1-vendor.", dir=str(manifest_parent)
    )
    os.close(fd)
    staging_manifest = Path(staging_manifest_name)

    capsule_published_by_us = False
    manifest_published_by_us = False
    try:
        staging_scripts = staging_root / "scripts"
        _stage_capsule(copy_set, iff_scripts, staging_scripts)
        _fsync_dir(staging_scripts)

        with open(staging_manifest, "wb") as handle:
            handle.write(new_manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        # Publish capsule: identical re-run (no-op) or fresh atomic move.
        capsule_action: str
        if existing_capsule is not None:
            capsule_action = "identical"
        else:
            # Re-check capsule_root chain is not a symlink at publication time.
            _check_path_chain_no_symlink(capsule_root, "capsule-root-publish")
            if capsule_root.is_symlink():
                raise VendorError(
                    f"refusing symlink capsule-root at publish: {capsule_root}"
                )
            if capsule_root.exists():
                raise VendorError(
                    f"capsule-root appeared during refresh: {capsule_root}"
                )
            os.replace(staging_root, capsule_root)
            _fsync_dir(capsule_parent)
            capsule_published_by_us = True
            capsule_action = "published"

        # Publish manifest: identical re-run (no-op) or atomic no-clobber link.
        manifest_action: str
        if existing_manifest_bytes is not None:
            manifest_action = "identical"
        else:
            _check_path_chain_no_symlink(manifest_path, "manifest-publish")
            if manifest_path.is_symlink():
                raise VendorError(
                    f"refusing symlink manifest at publish: {manifest_path}"
                )
            try:
                os.link(staging_manifest, manifest_path)
            except FileExistsError as exc:
                raise VendorError(
                    "manifest exists after race; refusing overwrite"
                ) from exc
            manifest_published_by_us = True
            _fsync_dir(manifest_parent)
            manifest_action = "published"

        # Success: clean up staging manifest (capsule staging was consumed by
        # os.replace or is identical to existing and can be discarded).
        return {
            "ok": True,
            "kind": KIND,
            "schema_version": SCHEMA_VERSION,
            "scripts_total": len(copy_set),
            "scripts_in_required": sum(
                1 for e in copy_set if e["in_required_registry"]
            ),
            "scripts_not_in_required": sum(
                1 for e in copy_set if not e["in_required_registry"]
            ),
            "capsule_action": capsule_action,
            "manifest_action": manifest_action,
        }
    except BaseException:
        # Transactional rollback: if this process newly published the capsule
        # and/or manifest and a later step failed, roll back in reverse order.
        # NEVER delete or roll back a pre-existing identical capsule/manifest
        # (those are tracked by the *_published_by_us flags).
        if manifest_published_by_us:
            try:
                manifest_path.unlink()
            except OSError:
                pass
            try:
                _fsync_dir(manifest_parent)
            except OSError:
                pass
        if capsule_published_by_us:
            try:
                shutil.rmtree(capsule_root, ignore_errors=True)
            except OSError:
                pass
            try:
                _fsync_dir(capsule_parent)
            except OSError:
                pass
        raise
    finally:
        # Always clean up staging residue. If capsule was published via
        # os.replace, staging_root no longer exists. If capsule was
        # pre-existing/identical, staging_root still exists and must be
        # cleaned up. The staging_manifest file always needs cleanup.
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        if staging_manifest.exists():
            try:
                staging_manifest.unlink()
            except OSError:
                pass


def check(
    iff_root: Path,
    capsule_root: Path,
    baseline_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Verify a capsule + manifest against the baseline. Read-only.

    Returns a success payload on match; raises ``VendorError`` on mismatch.
    Rejects symlinks for every caller-controlled path component (not only
    the leaf).
    """
    iff_root = iff_root.expanduser()
    capsule_root = capsule_root.expanduser()
    baseline_path = baseline_path.expanduser()
    manifest_path = manifest_path.expanduser()

    # Check every caller-controlled path component for symlinks.
    _check_path_chain_no_symlink(iff_root, "iff-root")
    _check_path_chain_no_symlink(capsule_root, "capsule-root")
    _check_path_chain_no_symlink(baseline_path, "baseline-path")
    _check_path_chain_no_symlink(manifest_path, "manifest-path")

    _check_regular_dir(iff_root, "iff-root")
    iff_scripts = iff_root / "scripts"
    _check_regular_dir(iff_scripts, "iff-scripts")
    _check_regular_file(baseline_path, "baseline")

    baseline = load_baseline(baseline_path)
    copy_set = expected_copy_set(baseline)
    new_manifest_bytes = manifest_bytes(
        copy_set, baseline_path, capsule_rel=DEFAULT_CAPSULE_REL
    )

    # Manifest must exist and be byte-identical.
    _check_regular_file(manifest_path, "manifest")
    actual_manifest = manifest_path.read_bytes()
    if actual_manifest != new_manifest_bytes:
        raise VendorError(
            "manifest drifts from a fresh deterministic build for this baseline"
        )

    # Capsule must contain exactly the expected files with matching SHAs.
    # No __pycache__ exemption: the capsule must contain exactly the 165
    # manifest entries and nothing else.
    if not capsule_root.exists():
        raise VendorError(f"capsule missing: {capsule_root}")
    _check_regular_dir(capsule_root, "capsule-root")
    scripts_dir = capsule_root / "scripts"
    if not scripts_dir.is_dir():
        raise VendorError(f"capsule scripts dir missing: {scripts_dir}")
    existing_names: set[str] = set()
    for item in sorted(scripts_dir.iterdir()):
        if item.is_dir():
            raise VendorError(f"unexpected directory in capsule scripts: {item.name}")
        if item.is_symlink():
            raise VendorError(f"unexpected symlink in capsule scripts: {item.name}")
        _check_regular_file(item, f"capsule file {item.name}")
        if not item.name.endswith(".py"):
            raise VendorError(f"unexpected non-.py file in capsule: {item.name}")
        existing_names.add(item.name)
    expected_names = {entry["name"] for entry in copy_set}
    if existing_names != expected_names:
        raise VendorError(
            f"capsule file set mismatch: "
            f"extras={sorted(existing_names - expected_names)} "
            f"missing={sorted(expected_names - existing_names)}"
        )
    for entry in copy_set:
        target = scripts_dir / entry["name"]
        _check_regular_file(target, f"capsule file {entry['name']}")
        actual_sha = _sha256_file(target)
        if actual_sha != entry["sha256"]:
            raise VendorError(
                f"capsule SHA mismatch for {entry['name']}: "
                f"expected={entry['sha256']} actual={actual_sha}"
            )

    return {
        "ok": True,
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "scripts_total": len(copy_set),
        "scripts_in_required": sum(
            1 for e in copy_set if e["in_required_registry"]
        ),
        "scripts_not_in_required": sum(
            1 for e in copy_set if not e["in_required_registry"]
        ),
    }


# ---------------------------------------------------------------------------
# CLI (one canonical JSON object; no traceback).
# ---------------------------------------------------------------------------


class _JSONArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises VendorError instead of exiting on errors."""

    def error(self, message: str) -> "None":  # type: ignore[override]
        raise VendorError(f"cli: {message}")


def _build_parser() -> _JSONArgumentParser:
    parser = _JSONArgumentParser(
        prog=SCRIPT_NAME,
        description="Refresh or check the ICP P2a iFF v1 vendor capsule.",
        add_help=True,
    )
    parser.add_argument(
        "--iff-root",
        required=True,
        type=lambda p: Path(p).expanduser(),
        help="Path to the read-only source iff skill root.",
    )
    parser.add_argument(
        "--capsule-root",
        required=True,
        type=lambda p: Path(p).expanduser(),
        help="Path to the capsule root (e.g. icp/vendor/iff_v1).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh the capsule and manifest from the source iff.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check that the capsule and manifest match the baseline.",
    )
    return parser


def _emit(stream, payload: dict[str, Any]) -> None:
    stream.write(_canonical_json_bytes(payload).decode("utf-8"))
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _build_parser()
        args = parser.parse_args(argv)
        capsule_rel = DEFAULT_CAPSULE_REL
        if args.refresh:
            result = refresh(
                iff_root=args.iff_root,
                capsule_root=args.capsule_root,
                baseline_path=DEFAULT_BASELINE,
                manifest_path=DEFAULT_MANIFEST,
                capsule_rel=capsule_rel,
            )
            _emit(sys.stdout, result)
            return 0
        if args.check:
            result = check(
                iff_root=args.iff_root,
                capsule_root=args.capsule_root,
                baseline_path=DEFAULT_BASELINE,
                manifest_path=DEFAULT_MANIFEST,
            )
            _emit(sys.stdout, result)
            return 0
        raise VendorError("cli: no mode selected")
    except VendorError as exc:
        _emit(
            sys.stderr,
            {"ok": False, "code": CODE_INTEGRITY, "message": str(exc)},
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        _emit(
            sys.stderr,
            {
                "ok": False,
                "code": CODE_CLI,
                "message": f"{type(exc).__name__}: {exc}",
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
