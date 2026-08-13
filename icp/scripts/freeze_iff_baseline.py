#!/usr/bin/env python3
"""Deterministic, evidence-backed freezer for the iFF baseline (ICP phase P0).

Produces a canonical machine-readable snapshot of the current iFF skill:

* parses the live ``REQUIRED`` literal from ``verify_pipeline_scripts.py`` via
  ``ast`` (no execution of iFF modules);
* enumerates every top-level ``scripts/*.py`` and hashes the bytes;
* records AST/literal-proven relationships only (callers/importers, consumed
  and produced artifacts, gate evidence) using canonical ``path:line`` strings;
* runs the fixed current verifier with ``sys.executable``, ``shell=False`` and a
  sanitized environment, recording the command, exit code and stdout;
* writes the canonical JSON atomically (same-directory temp file, fsync,
  ``os.replace``) and refuses a symlink output;
* in ``--check`` mode, recomputes the snapshot and exits non-zero with a
  concise drift report when the committed snapshot differs.

No iFF file is ever edited, executed or imported as a module by analysis.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
KIND = "iff-baseline-freeze"
SCRIPT_NAME = "freeze_iff_baseline.py"
OWNER_UNCLASSIFIED = "unclassified"
MIGRATION_HOLD = "hold"

# Canonical relative path prefix for everything under iff.
IFF_PREFIX = "iff"

# Recognised read-function names (call targets whose first/positional file
# argument is being consumed). Conservative: only well-known stdlib + iff
# common.py helpers.
READ_FUNCS = {
    "load_json",
    "read_text",
    "read_bytes",
    "png_size",
    "load",
    "read",
    "loadtxt",
    "np.load",
}

WRITE_FUNCS = {
    "dump_json",
    "write_text",
    "write_bytes",
    "dump",
    "save",
    "to_csv",
    "to_json",
}

# Functions that wrap a path string and then read/write (Path(...).read_text()).
PATH_METHOD_READS = {"read_text", "read_bytes"}
PATH_METHOD_WRITES = {"write_text", "write_bytes"}

PATH_METHOD_OPEN_READS = {"open"}  # Path(...).open() with no 'w'/'a'

PATH_LIKE_FUNCS = {"Path", "PurePath", "PosixPath"}


def _fail(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)


def _rel(path: Path, root: Path) -> str:
    """Return ``path`` relative to ``root`` as a forward-slashed string."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# REQUIRED registry parsing (AST-only, no execution).
# ---------------------------------------------------------------------------


class RequiredParseError(ValueError):
    """Raised when REQUIRED deviates from the strict literal contract."""


def parse_required_registry(verifier_path: Path) -> list[dict[str, str]]:
    """Parse the live ``REQUIRED`` literal from the verifier.

    Returns a deterministic list of ``{"name", "evidence"}`` entries where
    ``evidence`` is ``iff/scripts/verify_pipeline_scripts.py:<line>``.

    Reject non-literal, duplicate, traversal, missing or non-``.py`` entries.
    """
    verifier_path = verifier_path.resolve()
    src = verifier_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(verifier_path))
    required_node: ast.List | None = None
    for node in tree.body:  # only top-level assignment, never inside branches
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REQUIRED" and isinstance(node.value, ast.List):
                    required_node = node.value
                    break
            if required_node is not None:
                break
    if required_node is None:
        raise RequiredParseError("REQUIRED literal list not found at module top level")

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    rel_verifier = f"{IFF_PREFIX}/scripts/{verifier_path.name}"
    for element in required_node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            raise RequiredParseError(
                f"REQUIRED contains a non-literal element at line {element.lineno}"
            )
        name = element.value.strip()
        if not name:
            raise RequiredParseError(f"REQUIRED has empty element at line {element.lineno}")
        if "/" in name or "\\" in name or name != os.path.basename(name):
            raise RequiredParseError(
                f"REQUIRED traversal/non-basename entry at line {element.lineno}: {name!r}"
            )
        if not name.endswith(".py") or not re.fullmatch(r"[A-Za-z0-9_\-]+\.py", name):
            raise RequiredParseError(
                f"REQUIRED non-.py entry at line {element.lineno}: {name!r}"
            )
        if name in seen:
            raise RequiredParseError(f"REQUIRED duplicate entry at line {element.lineno}: {name!r}")
        seen.add(name)
        entries.append({"name": name, "evidence": f"{rel_verifier}:{element.lineno}"})
    return entries


# ---------------------------------------------------------------------------
# Script enumeration + hashing.
# ---------------------------------------------------------------------------


def enumerate_scripts(iff_root: Path) -> list[dict[str, Any]]:
    """Return sorted inventory of every top-level ``scripts/*.py``.

    Each entry contains ``path`` (canonical relative) and ``sha256``.
    """
    iff_root = iff_root.resolve()
    scripts_dir = iff_root / "scripts"
    if not scripts_dir.is_dir():
        raise FileNotFoundError(f"scripts dir not found: {scripts_dir}")
    out: list[dict[str, Any]] = []
    for path in sorted(scripts_dir.glob("*.py")):
        if not path.is_file():
            continue
        if path.parent != scripts_dir:
            raise ValueError(f"unexpected symlink/collapsing path: {path}")
        out.append({
            "path": _rel(path, iff_root.parent),
            "sha256": _sha256_file(path),
        })
    return out


def compute_counts(
    required: list[dict[str, str]],
    scripts: list[dict[str, Any]],
) -> dict[str, int]:
    required_names = {entry["name"] for entry in required}
    in_required = 0
    for entry in scripts:
        if Path(entry["path"]).name in required_names:
            in_required += 1
    return {
        "scripts_total": len(scripts),
        "required_registry_total": len(required),
        "scripts_in_required": in_required,
        "scripts_not_in_required": len(scripts) - in_required,
    }


# ---------------------------------------------------------------------------
# AST-only relationship extraction (callers/importers, consumes, produces).
# ---------------------------------------------------------------------------


def _extract_literal_path(node: ast.AST | None) -> str | None:
    """Return a literal string path embedded in ``node`` if provable.

    Handles:
      * bare string constants;
      * ``Path("...")`` / ``PurePath("...")`` constructor calls;
      * path-division/modulus BinOps (``x / "scene.json"``) by taking the
        literal side that is provably a string.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_LIKE_FUNCS:
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Mod)):
        right = _extract_literal_path(node.right)
        if right is not None:
            return right
        return _extract_literal_path(node.left)
    if isinstance(node, ast.JoinedStr):
        return None  # f-strings are non-deterministic; never infer.
    return None


def _literal_mode_arg(node: ast.Call) -> str:
    if (
        len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ):
        return node.args[1].value
    return ""


_WRITE_MODES = {"w", "wb", "a", "ab", "x", "xb", "w+", "wb+", "a+", "ab+"}


def _looks_like_artifact(name: str) -> bool:
    if not name:
        return False
    if any(ch in name for ch in (" ", "\n", "\t")):
        return False
    return ("." in name) or ("/" in name) or ("\\" in name)


def _classify_call(node: ast.Call) -> tuple[str, str] | None:
    """Classify a Call as a literal read/write; return (kind, artifact)."""
    func = node.func
    func_name = func.id if isinstance(func, ast.Name) else None
    attr_name = func.attr if isinstance(func, ast.Attribute) else None

    if attr_name in PATH_METHOD_READS or attr_name in PATH_METHOD_WRITES:
        art = _extract_literal_path(func.value)
        if art is None or not _looks_like_artifact(art):
            return None
        kind = "read" if attr_name in PATH_METHOD_READS else "write"
        return (kind, art)

    if attr_name == "open":
        art = _extract_literal_path(func.value)
        if art is None or not _looks_like_artifact(art):
            return None
        mode = _literal_mode_arg(node)
        return ("write", art) if mode in _WRITE_MODES else ("read", art)

    if func_name == "open":
        if not node.args:
            return None
        art = _extract_literal_path(node.args[0])
        if art is None or not _looks_like_artifact(art):
            return None
        mode = _literal_mode_arg(node)
        return ("write", art) if mode in _WRITE_MODES else ("read", art)

    if func_name in READ_FUNCS or func_name in WRITE_FUNCS:
        # write helpers (dump_json, dump, to_json) take (data, path)
        if func_name in {"dump_json", "dump", "to_json"}:
            art_node: ast.AST | None = node.args[1] if len(node.args) > 1 else None
        else:
            art_node = node.args[0] if node.args else None
        art = _extract_literal_path(art_node)
        if art is None or not _looks_like_artifact(art):
            return None
        kind = "read" if func_name in READ_FUNCS else "write"
        return (kind, art)

    return None


def compute_relationships(iff_root: Path) -> list[dict[str, Any]]:
    """Return one relationship entry per live top-level script.

    Each entry has ``path``, ``direct_callers_or_importers``, ``consumes``,
    ``produces``. The ``gates``/``owner_candidate``/``migration_action``/
    ``deletion_evidence``/``in_required_registry``/``sha256`` fields are merged
    later in :func:`build_snapshot` to keep this function dependency-free.
    """
    iff_root = iff_root.resolve()
    scripts_dir = iff_root / "scripts"
    script_paths = sorted(
        p for p in scripts_dir.glob("*.py") if p.is_file() and p.parent == scripts_dir
    )
    script_names = {p.name for p in script_paths}

    callers: dict[str, list[str]] = {p.name: [] for p in script_paths}
    consumes: dict[str, list[str]] = {p.name: [] for p in script_paths}
    produces: dict[str, list[str]] = {p.name: [] for p in script_paths}

    for path in script_paths:
        rel_t = _rel(path, iff_root.parent)
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as exc:
            raise SyntaxError(f"cannot parse {rel_t}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise ValueError(f"cannot decode {rel_t}: {exc}") from exc
        except OSError as exc:
            raise OSError(f"cannot read {rel_t}: {exc}") from exc

        rw_artifacts_at_line: set[tuple[int, str]] = set()
        rw_events: list[tuple[int, str, str]] = []
        literal_refs: list[tuple[int, str]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    target = top + ".py"
                    if target in script_names and target != path.name:
                        callers[target].append(f"{rel_t}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    target = top + ".py"
                    if target in script_names and target != path.name:
                        callers[target].append(f"{rel_t}:{node.lineno}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.strip()
                if val in script_names and val != path.name:
                    literal_refs.append((node.lineno, val))
            elif isinstance(node, ast.Call):
                result = _classify_call(node)
                if result is not None:
                    kind, art = result
                    rw_events.append((node.lineno, kind, art))
                    rw_artifacts_at_line.add((node.lineno, art))

        for lineno, val in literal_refs:
            # Do not double-count a literal that is actually a read/write
            # artifact on the same line (e.g. ``load_json("common.py")`` is
            # a data read, not a script invocation reference).
            if (lineno, val) in rw_artifacts_at_line:
                continue
            callers[val].append(f"{rel_t}:{lineno}")

        for lineno, kind, art in rw_events:
            if kind == "read":
                consumes[path.name].append(f"{rel_t}:{lineno}:{art}")
            elif kind == "write":
                produces[path.name].append(f"{rel_t}:{lineno}:{art}")

    entries: list[dict[str, Any]] = []
    for path in script_paths:
        entries.append({
            "path": _rel(path, iff_root.parent),
            "direct_callers_or_importers": sorted(set(callers[path.name])),
            "consumes": sorted(set(consumes[path.name])),
            "produces": sorted(set(produces[path.name])),
        })
    return entries


# ---------------------------------------------------------------------------
# Gate evidence + fail-safe migration defaults.
# ---------------------------------------------------------------------------


def default_owner() -> str:
    return OWNER_UNCLASSIFIED


def default_migration() -> str:
    return MIGRATION_HOLD


def default_deletion_evidence() -> list[Any]:
    return []


def gate_evidence(
    required_entries: list[dict[str, str]],
    iff_root: Path,
) -> dict[str, list[str]]:
    """Map script name -> list of exact gate-source ``path:line`` evidence.

    The only structurally-proven gate at P0 is the REQUIRED registry itself: a
    script registered there is referenced by the literal line in
    ``verify_pipeline_scripts.py`` (the pipeline preflight gate). Filenames are
    never classified as gates from their name alone.
    """
    scripts_dir = iff_root.resolve() / "scripts"
    out: dict[str, list[str]] = {
        path.name: []
        for path in scripts_dir.glob("*.py")
        if path.is_file() and path.parent == scripts_dir
    }
    for entry in required_entries:
        out[entry["name"]] = [entry["evidence"]]
    return out


# ---------------------------------------------------------------------------
# Fixed verifier execution.
# ---------------------------------------------------------------------------


def _canonical_iff_root(iff_root: Path) -> str:
    """Return the canonical relative iff root used for command recording."""
    return IFF_PREFIX


def _canonical_verifier_path(iff_root: Path) -> str:
    return f"{IFF_PREFIX}/scripts/verify_pipeline_scripts.py"


def run_verifier(iff_root: Path) -> dict[str, Any]:
    """Run the fixed verifier and record command/exit_code/stdout.

    The subprocess uses ``sys.executable``, ``shell=False``, a sanitized
    environment with ``PYTHONDONTWRITEBYTECODE=1`` and the canonical
    ``--iff-root`` only. The recorded command/stdout use source-root-neutral
    relative paths so the snapshot is portable across machines.
    """
    iff_root = iff_root.resolve()
    verifier_path = iff_root / "scripts" / "verify_pipeline_scripts.py"
    if not verifier_path.is_file():
        raise FileNotFoundError(f"verifier not found: {verifier_path}")

    argv = [str(verifier_path), "--skill-dir", str(iff_root)]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Preserve a minimal locale surface so output encoding stays deterministic.
    for key in ("LC_ALL", "LC_CTYPE", "LANG"):
        if key in os.environ:
            env[key] = os.environ[key]

    completed = subprocess.run(
        [sys.executable, *argv],
        env=env,
        shell=False,
        capture_output=True,
        text=True,
    )
    abs_root = str(iff_root)
    abs_scripts = str(iff_root / "scripts")
    rel_root = _canonical_iff_root(iff_root)
    rel_scripts = f"{rel_root}/scripts"

    def _normalize(text: str) -> str:
        return (
            text.replace(abs_scripts, rel_scripts)
                .replace(abs_root + "/", rel_root + "/")
                .replace(abs_root, rel_root)
        )

    canonical_command = [
        "python3",
        _canonical_verifier_path(iff_root),
        "--skill-dir",
        rel_root,
    ]
    return {
        "command": canonical_command,
        "exit_code": completed.returncode,
        "stdout": _normalize(completed.stdout),
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Freeze or check the deterministic iFF baseline snapshot.",
    )
    parser.add_argument(
        "--iff-root",
        required=True,
        type=lambda p: Path(p).expanduser().resolve(),
        help="Path to the live iff skill root (read-only).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    # Output/baseline paths keep their user-supplied identity (no resolve()):
    # write_atomic()/check_snapshot() must lstat the original path so a symlink
    # destination is refused instead of silently dereferenced.
    mode.add_argument("--write", metavar="OUTPUT",
                      type=lambda p: Path(p).expanduser(),
                      help="Write canonical snapshot to OUTPUT atomically.")
    mode.add_argument("--check", metavar="OUTPUT",
                      type=lambda p: Path(p).expanduser(),
                      help="Recompute snapshot and exit nonzero on drift.")
    return parser


def canonical_json_bytes(snapshot: dict[str, Any]) -> bytes:
    """Encode a snapshot deterministically for writing and comparison."""
    return (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def build_snapshot(iff_root: Path) -> tuple[dict[str, Any], bytes]:
    """Build the complete deterministic iFF baseline snapshot in memory."""
    iff_root = iff_root.expanduser().resolve()
    skill_path = iff_root / "SKILL.md"
    verifier_path = iff_root / "scripts" / "verify_pipeline_scripts.py"
    if not skill_path.is_file():
        raise FileNotFoundError(f"skill contract not found: {skill_path}")

    required = parse_required_registry(verifier_path)
    base_scripts = enumerate_scripts(iff_root)
    live_names = {Path(entry["path"]).name for entry in base_scripts}
    missing_required = sorted(
        entry["name"] for entry in required if entry["name"] not in live_names
    )
    if missing_required:
        raise FileNotFoundError(
            "REQUIRED scripts missing from live iFF: " + ", ".join(missing_required)
        )

    relationships = {
        entry["path"]: entry for entry in compute_relationships(iff_root)
    }
    gates_by_name = gate_evidence(required, iff_root)
    required_names = {entry["name"] for entry in required}
    scripts: list[dict[str, Any]] = []
    for base in base_scripts:
        path = base["path"]
        name = Path(path).name
        relationship = relationships[path]
        scripts.append(
            {
                "path": path,
                "sha256": base["sha256"],
                "in_required_registry": name in required_names,
                "direct_callers_or_importers": relationship[
                    "direct_callers_or_importers"
                ],
                "consumes": relationship["consumes"],
                "produces": relationship["produces"],
                "gates": gates_by_name[name],
                "owner_candidate": "unclassified",
                "migration_action": "hold",
                "deletion_evidence": [],
            }
        )

    verifier = run_verifier(iff_root)
    if verifier["exit_code"] != 0:
        raise RuntimeError(
            "iFF verifier failed with exit code " + str(verifier["exit_code"])
        )

    snapshot: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "iff_root": "iff",
            "skill_md": {
                "path": "iff/SKILL.md",
                "sha256": _sha256_file(skill_path),
            },
            "verify_pipeline_scripts": {
                "path": "iff/scripts/verify_pipeline_scripts.py",
                "sha256": _sha256_file(verifier_path),
            },
        },
        "required_registry": required,
        "counts": compute_counts(required, base_scripts),
        "scripts": scripts,
        "verifier": verifier,
    }
    return snapshot, canonical_json_bytes(snapshot)


def write_atomic(output: Path, payload: bytes) -> None:
    """Atomically replace a regular output file; never follow output symlinks."""
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise OSError(f"refusing symlink output: {output}")
    if output.exists() and not output.is_file():
        raise OSError(f"output is not a regular file: {output}")

    fd, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output.is_symlink():
            raise OSError(f"refusing symlink output: {output}")
        os.replace(temporary, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def check_snapshot(iff_root: Path, baseline_path: Path) -> int:
    """Return zero only when the stored baseline matches the live snapshot."""
    baseline_path = baseline_path.expanduser()
    if baseline_path.is_symlink():
        raise OSError(f"refusing symlink baseline: {baseline_path}")
    stored = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict):
        raise ValueError("baseline root must be a JSON object")

    current, current_bytes = build_snapshot(iff_root)
    if baseline_path.read_bytes() == current_bytes:
        print(f"ok {baseline_path}")
        return 0

    changed_sections = sorted(
        key
        for key in set(stored) | set(current)
        if stored.get(key) != current.get(key)
    )
    print("drift: changed sections: " + ", ".join(changed_sections))
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.write is not None:
            _, encoded = build_snapshot(args.iff_root)
            write_atomic(args.write, encoded)
            print(f"wrote {args.write}")
            return 0
        if args.check is not None:
            return check_snapshot(args.iff_root, args.check)
    except (OSError, RuntimeError, SyntaxError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error("exactly one of --write or --check is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
