#!/usr/bin/env python3
"""Runtime integrity gate for the ICP P2a iFF v1 compatibility capsule.

This module is the installed runtime gate. It verifies the capsule under
``vendor/iff_v1/scripts/`` against the committed manifest
(``references/baselines/iff-v1-vendor.json``) and the P0 baseline binding
(``references/baselines/iff-v1.json``).

Behaviour guarantees:

* It resolves its own skill root from its installed file location and
  accepts no root, manifest, registry, or scripts-directory override.
* It works when ``iff/`` is absent and never imports, reads, executes, or
  follows a symlink into ``iff/**``.
* It never follows a symlink anywhere from the skill root through a target
  capsule file.
* It fails closed on any integrity violation: missing/extra/mutated/
  symlinked/non-regular/unreadable files; duplicate JSON keys; wrong
  schema; unsafe relative paths; manifest/baseline binding mismatch; and
  file-set/count mismatch.

CLI output is exactly one canonical JSON object on stdout for success
(exit 0) or one canonical JSON object on stderr for failure (exit 2). No
traceback. Errors are local to this integrity tool and never add
undeclared ICP pre-claim public error codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
KIND = "icp.iff-v1-vendor-capsule"
SCRIPT_NAME = "verify_vendor_iff_v1.py"

# Fixed production paths derived from this module's installed location.
# The verifier accepts NO override; this is the runtime gate.
SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SKILL_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
BASELINE_PATH = SKILL_ROOT / "references" / "baselines" / "iff-v1.json"

# Local error code. This is NOT an ICP pre-claim code and does not extend
# icp_common.ALL_ERROR_CODES.
CODE_INTEGRITY = "capsule_integrity_failed"


class CapsuleIntegrityError(ValueError):
    """Raised on any capsule/manifest/baseline integrity violation."""


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
            raise CapsuleIntegrityError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _is_safe_basename(name: Any) -> bool:
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or name in {".", ".."} or "\x00" in name:
        return False
    if name != os.path.basename(name):
        return False
    return name.endswith(".py")


def _check_safe_relative_path(rel: Any, role: str) -> None:
    if not isinstance(rel, str) or not rel:
        raise CapsuleIntegrityError(f"{role}: empty relative path")
    if rel.startswith("/"):
        raise CapsuleIntegrityError(f"{role}: absolute path: {rel!r}")
    if "\x00" in rel:
        raise CapsuleIntegrityError(f"{role}: NUL in path: {rel!r}")
    parts = rel.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise CapsuleIntegrityError(f"{role}: unsafe path components: {rel!r}")


def _check_regular_file(path: Path, role: str) -> None:
    """Refuse symlinks / non-regular / unreadable files."""
    try:
        if path.is_symlink():
            raise CapsuleIntegrityError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise CapsuleIntegrityError(f"{role}: cannot lstat {path}: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise CapsuleIntegrityError(f"{role}: not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise CapsuleIntegrityError(f"{role}: unreadable file: {path}")


def _check_regular_dir(path: Path, role: str) -> None:
    """Refuse symlinks / non-directories."""
    try:
        if path.is_symlink():
            raise CapsuleIntegrityError(f"{role}: refusing symlink dir: {path}")
        st = path.lstat()
    except OSError as exc:
        raise CapsuleIntegrityError(f"{role}: cannot lstat dir {path}: {exc}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise CapsuleIntegrityError(f"{role}: not a directory: {path}")


def _check_path_chain_no_symlink(path: Path, role: str) -> None:
    """Reject if any existing component of the absolute form of ``path`` is a
    symlink. Does NOT call ``.resolve()`` on the whole path — the user-supplied
    path identity is preserved and inspected component-by-component.

    On macOS, ``os.path.abspath`` does NOT resolve symlinks; it only normalizes
    ``.`` and ``..``. So caller-supplied symlinks are preserved and detected,
    while the OS-level ``/var -> /private/var`` symlink is only encountered if
    the caller explicitly passes a ``/var`` prefix (the canonical ``/private/var``
    form is never affected).
    """
    abs_path = Path(os.path.abspath(str(path)))
    root = abs_path.anchor or "/"
    current = Path(root)
    for part in abs_path.parts[1:]:
        current = current / part
        if os.path.islink(str(current)):
            raise CapsuleIntegrityError(
                f"{role}: refusing symlink in path chain: {current}"
            )


# ---------------------------------------------------------------------------
# Manifest load + shape validation.
# ---------------------------------------------------------------------------


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise CapsuleIntegrityError(f"refusing symlink manifest: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CapsuleIntegrityError(f"cannot read manifest {path}: {exc}") from exc
    try:
        manifest = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise CapsuleIntegrityError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise CapsuleIntegrityError("manifest root must be a JSON object")
    return manifest


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("kind") != KIND:
        raise CapsuleIntegrityError(
            f"manifest kind mismatch: {manifest.get('kind')!r}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CapsuleIntegrityError(
            f"manifest schema_version mismatch: {manifest.get('schema_version')!r}"
        )
    capsule_root = manifest.get("capsule_root")
    _check_safe_relative_path(capsule_root, "capsule_root")
    baseline = manifest.get("baseline")
    if not isinstance(baseline, dict):
        raise CapsuleIntegrityError("manifest baseline missing")
    if baseline.get("path") != "references/baselines/iff-v1.json":
        raise CapsuleIntegrityError(
            f"manifest baseline.path not canonical: {baseline.get('path')!r}"
        )
    baseline_sha = baseline.get("sha256")
    if (
        not isinstance(baseline_sha, str)
        or len(baseline_sha) != 64
        or not baseline_sha.islower()
    ):
        raise CapsuleIntegrityError(
            f"manifest baseline.sha256 malformed: {baseline_sha!r}"
        )
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise CapsuleIntegrityError("manifest counts missing")
    for key in ("scripts_total", "scripts_in_required", "scripts_not_in_required"):
        if not isinstance(counts.get(key), int) or counts[key] < 0:
            raise CapsuleIntegrityError(
                f"manifest counts.{key} not a non-negative int"
            )
    scripts = manifest.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise CapsuleIntegrityError("manifest scripts missing/empty")
    if counts["scripts_total"] != len(scripts):
        raise CapsuleIntegrityError(
            f"counts.scripts_total={counts['scripts_total']} != "
            f"len(scripts)={len(scripts)}"
        )
    seen: set[str] = set()
    n_required = 0
    n_non_required = 0
    for entry in scripts:
        if not isinstance(entry, dict):
            raise CapsuleIntegrityError("manifest script entry not an object")
        name = entry.get("name")
        if not _is_safe_basename(name):
            raise CapsuleIntegrityError(f"manifest script name unsafe: {name!r}")
        if name in seen:
            raise CapsuleIntegrityError(f"manifest script duplicate: {name!r}")
        seen.add(name)
        for key in ("source_path", "dest_path", "sha256"):
            v = entry.get(key)
            if not isinstance(v, str) or not v:
                raise CapsuleIntegrityError(
                    f"manifest script {name} missing {key}"
                )
        sp = entry["source_path"]
        if sp != "iff/scripts/" + name:
            raise CapsuleIntegrityError(
                f"manifest source_path not canonical: {sp!r}"
            )
        dp = entry["dest_path"]
        if dp != "scripts/" + name:
            raise CapsuleIntegrityError(
                f"manifest dest_path not canonical: {dp!r}"
            )
        sha = entry["sha256"]
        if len(sha) != 64 or not sha.islower() or not all(
            c in "0123456789abcdef" for c in sha
        ):
            raise CapsuleIntegrityError(
                f"manifest script {name} sha256 malformed: {sha!r}"
            )
        irr = entry.get("in_required_registry")
        if not isinstance(irr, bool):
            raise CapsuleIntegrityError(
                f"manifest script {name} in_required_registry not bool"
            )
        if irr:
            n_required += 1
        else:
            n_non_required += 1
    if n_required != counts["scripts_in_required"]:
        raise CapsuleIntegrityError(
            f"counts.scripts_in_required={counts['scripts_in_required']} "
            f"!= actual={n_required}"
        )
    if n_non_required != counts["scripts_not_in_required"]:
        raise CapsuleIntegrityError(
            f"counts.scripts_not_in_required={counts['scripts_not_in_required']} "
            f"!= actual={n_non_required}"
        )


# ---------------------------------------------------------------------------
# Verify skill: the testable entry point.
# ---------------------------------------------------------------------------


def verify_skill(skill_root: Path) -> dict[str, Any]:
    """Verify the installed capsule for the given skill root.

    Returns a success payload on match; raises :class:`CapsuleIntegrityError`
    on any integrity violation. Never imports or reads ``iff/**``.
    """
    # Do NOT call .resolve() on the caller-supplied skill root — that would
    # erase symlink identity. Instead, inspect every path component for
    # symlinks. A symlinked skill root or any intermediate symlink in the
    # skill-root chain is rejected before any traversal.
    _check_path_chain_no_symlink(skill_root, "skill-root")
    manifest_path = skill_root / "references" / "baselines" / "iff-v1-vendor.json"
    baseline_path = skill_root / "references" / "baselines" / "iff-v1.json"

    # Top-level skill root must be a regular dir (no symlinks).
    _check_regular_dir(skill_root, "skill-root")

    # Manifest path: parents must be regular dirs (no symlinks in the chain).
    references = skill_root / "references"
    baselines = references / "baselines"
    _check_regular_dir(references, "references")
    _check_regular_dir(baselines, "baselines")

    manifest = _load_manifest(manifest_path)
    _validate_manifest_shape(manifest)

    capsule_rel = manifest["capsule_root"]
    capsule_root = skill_root / capsule_rel
    scripts_dir = capsule_root / "scripts"

    # Walk capsule ancestors; every component from skill_root down to scripts
    # must be a regular directory (no symlinks anywhere on the chain).
    current = capsule_root
    chain: list[Path] = []
    while current != skill_root and skill_root in current.parents:
        chain.append(current)
        current = current.parent
    for p in reversed(chain):
        _check_regular_dir(p, f"capsule-ancestor {p.relative_to(skill_root)}")
    _check_regular_dir(capsule_root, "capsule-root")
    _check_regular_dir(scripts_dir, "scripts-dir")

    # Baseline binding: manifest baseline.sha256 must equal the actual bytes
    # of the installed iff-v1.json baseline. The verifier reads iff-v1.json
    # (committed data) but never reads or imports live iff/**.
    _check_regular_file(baseline_path, "baseline")
    actual_baseline_sha = _sha256_file(baseline_path)
    if actual_baseline_sha != manifest["baseline"]["sha256"]:
        raise CapsuleIntegrityError(
            f"baseline binding mismatch: "
            f"manifest={manifest['baseline']['sha256']} "
            f"actual={actual_baseline_sha}"
        )

    # Verify each capsule file's SHA; refuse symlinks / non-regular files.
    expected_names = {entry["name"] for entry in manifest["scripts"]}
    for entry in sorted(manifest["scripts"], key=lambda e: e["name"]):
        target = scripts_dir / entry["name"]
        # No symlink from capsule_root through target. Parents already
        # checked above; here we only need to check the file itself.
        _check_regular_file(target, f"capsule file {entry['name']}")
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise CapsuleIntegrityError(
                f"cannot read capsule file {entry['name']}: {exc}"
            ) from exc
        actual = _sha256_bytes(data)
        if actual != entry["sha256"]:
            raise CapsuleIntegrityError(
                f"capsule SHA mismatch for {entry['name']}: "
                f"manifest={entry['sha256']} actual={actual}"
            )

    # Detect extras: anything in scripts_dir not in the manifest set fails.
    # There is no __pycache__ exemption — the capsule must contain exactly
    # the 165 manifest entries and nothing else.
    try:
        listing = list(scripts_dir.iterdir())
    except OSError as exc:
        raise CapsuleIntegrityError(
            f"cannot list capsule scripts dir: {exc}"
        ) from exc
    for item in listing:
        if item.is_dir():
            raise CapsuleIntegrityError(
                f"unexpected directory in capsule scripts: {item.name}"
            )
        if item.is_symlink():
            raise CapsuleIntegrityError(
                f"unexpected symlink in capsule scripts: {item.name}"
            )
        # Every remaining entry must be a regular .py file in the manifest.
        if item.name not in expected_names:
            raise CapsuleIntegrityError(
                f"unexpected extra file in capsule scripts: {item.name}"
            )

    return {
        "ok": True,
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "capsule_root": capsule_rel,
        "scripts_total": len(manifest["scripts"]),
        "scripts_in_required": manifest["counts"]["scripts_in_required"],
        "scripts_not_in_required": manifest["counts"]["scripts_not_in_required"],
    }


# ---------------------------------------------------------------------------
# CLI (no override flags; one canonical JSON object; no traceback).
# ---------------------------------------------------------------------------


def _emit(stream, payload: dict[str, Any]) -> None:
    stream.write(_canonical_json_bytes(payload).decode("utf-8"))
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    # The runtime verifier accepts NO CLI override. The only acceptable
    # invocation is the bare command (or --help). Anything else is a CLI
    # error, surfaced as one canonical JSON object on stderr.
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw:
        _emit(
            sys.stderr,
            {
                "ok": False,
                "code": CODE_INTEGRITY,
                "message": (
                    f"{SCRIPT_NAME} accepts no arguments; got {raw!r}. "
                    "It derives its skill root from its installed location."
                ),
            },
        )
        return 2
    try:
        result = verify_skill(SKILL_ROOT)
        _emit(sys.stdout, result)
        return 0
    except CapsuleIntegrityError as exc:
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
                "code": CODE_INTEGRITY,
                "message": f"{type(exc).__name__}: {exc}",
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
