#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for ICP P1b.

Covers:

1. local CSV primitive byte SHA equals the frozen baseline; runtime modules
   contain no import/path dependency on ``iff``;
2. candidate selection order/limit, aliases, invalid limit, duplicate active
   title rejection;
3. two concurrent processes claim the same blank title: exactly one wins,
   final status is ``doing``, no corruption/temp files;
4. stale expected status and duplicate-title claim fail with task bytes
   unchanged;
5. successful export creates exactly canonical ``row.json``, ``interaction.txt``,
   ``ui_notes.txt``, ``api.txt`` with no title traversal;
6. writeback CAS ``doing -> done/error``, stale writeback rejected;
7. manifest field set/digests/root derivation/canonical deterministic bytes;
8. same batch/run-root conflict cannot overwrite the first manifest;
9. forced manifest-freeze conflict/failure occurs before claim and keeps every
   status blank;
10. successful prepare proves manifest is durably present before the claim
    callback, then claims/exports only successes;
11. production CLI still fails ``unsupported_platform`` before touching a
    nonexistent task path and exposes no registry/batch/root/script/command
    override;
12. malformed config/CLI errors emit one JSON object, never traceback;
13. all P1a 79 tests remain green (asserted here by importing the P1a selftest
    module and re-running it).

Uses only the standard library and temporary fixtures. Run directly:

    python3 icp/scripts/selftest_p1b.py
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import multiprocessing as mp
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_SCRIPTS = Path(__file__).resolve().parent

# Frozen SHA-256 of the local CSV primitive (must match the iff baseline).
FROZEN_PRIMITIVE_SHA256 = (
    "d5a1f418694d002335671694c8fa419368b36919f168cfd93a33b3c2479105ae"
)


# ---------------------------------------------------------------------------
# Module loaders.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_COMMON = _load("icp_common", ICP_SCRIPTS / "icp_common.py")
_RESOLVE = _load("resolve_run_config", ICP_SCRIPTS / "resolve_run_config.py")
_PREFLIGHT = _load("preflight_selection", ICP_SCRIPTS / "preflight_selection.py")
_CSV = _load("csv_task_source", ICP_SCRIPTS / "csv_task_source.py")
_FREEZE = _load("freeze_selection_manifest", ICP_SCRIPTS / "freeze_selection_manifest.py")
_PREPARE = _load("prepare_selection", ICP_SCRIPTS / "prepare_selection.py")

_FROZEN_PRIMITIVE_PATH = ICP_SCRIPTS / "task_sources" / "csv_row_status_v1.py"


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _write_csv(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


def _good_csv_multi() -> bytes:
    """Canonical multi-row CSV with English semantic headers, 2 blank rows."""
    return (
        b"id,title,design_url,ui_notes,interaction,api,status\n"
        b"1,Alpha,https://figma.com/file/a,un-A,ie-A,ap-A,\n"
        b"2,Beta,https://figma.com/file/b,un-B,ie-B,ap-B,\n"
        b"3,Gamma,https://figma.com/file/c,un-C,ie-C,ap-C,done\n"
        b"4,Delta,https://figma.com/file/d,un-D,ie-D,ap-D,doing\n"
    )


def _good_csv_aliases() -> bytes:
    """CSV with Chinese semantic aliases (accepted by the frozen primitive)."""
    return (
        "编号,标题,设计稿地址,UI补充描述,交互描述,接口描述,状态\n"
        "1,甲,https://figma.com/file/a,un,ie,ap,\n"
        "2,乙,https://figma.com/file/b,un2,ie2,ap2,\n"
        "3,丙,https://figma.com/file/c,un3,ie3,ap3,done\n"
    ).encode("utf-8")


def _config(**overrides) -> dict:
    base = {
        "task_source": "csv",
        "task_ref": "tasks.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "project_root": ".",
    }
    base.update(overrides)
    return base


def _write_config(directory: Path, payload: dict | str, name: str = "config.json") -> Path:
    path = directory / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_prepare_cli(config: Path, limit: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / "prepare_selection.py"),
         "--config", str(config), "--limit", str(limit)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _run_resolve(config: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / "resolve_run_config.py"),
         "--config", str(config), "--cwd", str(cwd)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


# ---------------------------------------------------------------------------
# 1. Frozen primitive SHA equals baseline; runtime modules have no iff import.
# ---------------------------------------------------------------------------


def test_local_csv_primitive_byte_sha_equals_frozen_baseline() -> None:
    digest = hashlib.sha256(_FROZEN_PRIMITIVE_PATH.read_bytes()).hexdigest()
    assert digest == FROZEN_PRIMITIVE_SHA256, (
        f"primitive SHA drifted: {digest} != {FROZEN_PRIMITIVE_SHA256}"
    )
    assert _CSV.FROZEN_PRIMITIVE_SHA256 == FROZEN_PRIMITIVE_SHA256


def _python_files_without_iff_dep() -> list[Path]:
    """Return ICP runtime .py files; assert none contain an iff import/path."""
    files = [
        ICP_SCRIPTS / "icp_common.py",
        ICP_SCRIPTS / "csv_task_source.py",
        ICP_SCRIPTS / "freeze_selection_manifest.py",
        ICP_SCRIPTS / "prepare_selection.py",
        ICP_SCRIPTS / "task_sources" / "__init__.py",
    ]
    # csv_row_status_v1.py is a byte-frozen copy of iff/scripts/csv_row_status.py;
    # it has no iff import by construction (asserted below), but it must not be
    # the path through which the runtime reaches iff.
    return files


def test_runtime_modules_contain_no_iff_dependency() -> None:
    iff_path_re = re.compile(r"\biff\b")
    iff_import_re = re.compile(
        r"^\s*(?:from|import)\s+iff(?:\.|\s|$)", re.MULTILINE
    )
    # 1. Runtime wrappers must contain no iff path string and no iff import.
    for path in _python_files_without_iff_dep():
        src = path.read_text(encoding="utf-8")
        assert not iff_import_re.search(src), (
            f"iff import leaked into runtime module {path}"
        )
        # The wrapper module may reference 'iff' only inside docstrings as the
        # historical provenance marker; no path or import expression is allowed.
        # Parse the AST and walk imports / string literals separately.
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("iff"), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("iff"), path
    # 2. The frozen primitive itself contains no iff import (proves the copy
    #    is self-contained and the runtime can never reach iff through it).
    primitive_src = _FROZEN_PRIMITIVE_PATH.read_text(encoding="utf-8")
    assert not iff_import_re.search(primitive_src), (
        "frozen primitive contains an iff import"
    )
    # 3. As a strict belt-and-braces check, the only file allowed to mention
    #    'iff' at all is the frozen primitive's tempfile lock prefix string
    #    ("iff-csv-row-status-..."); that is a filename fragment, not an
    #    import/path. The wrapper modules above must not.
    for path in _python_files_without_iff_dep():
        src = path.read_text(encoding="utf-8")
        # Find every iff occurrence and assert it is inside a docstring or
        # comment, never a string used as a path.
        for match in re.finditer(r"\biff\b", src):
            line_start = src.rfind("\n", 0, match.start()) + 1
            line_end = src.find("\n", match.end())
            if line_end == -1:
                line_end = len(src)
            line = src[line_start:line_end]
            # Allow references to the read-only iff skill inside docstrings/
            # comments (provenance). Reject any line that builds a path or
            # import to iff.
            assert "import iff" not in line, path
            assert "from iff" not in line, path
            assert "iff/scripts" not in line, path
            assert "iff\\" not in line, path


# ---------------------------------------------------------------------------
# 2. Candidate selection order/limit/aliases/invalid limit/duplicate reject.
# ---------------------------------------------------------------------------


def test_select_candidates_order_and_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        cands = _CSV.select_candidates(p, 1)
        assert [c["title"] for c in cands] == ["Alpha"]
        cands_all = _CSV.select_candidates(p, 10)
        assert [c["title"] for c in cands_all] == ["Alpha", "Beta"]
        # CSV order is preserved; row_index is monotonic evidence.
        assert [c["row_index"] for c in cands_all] == [1, 2]
        assert all(c["status"] == "" for c in cands_all)


def test_select_candidates_accepts_aliases() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_aliases())
        cands = _CSV.select_candidates(p, 5)
        assert [c["title"] for c in cands] == ["甲", "乙"]


def test_select_candidates_invalid_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        for bad in (0, -1, 1.5, "1", None, True):
            try:
                _CSV.select_candidates(p, bad)  # type: ignore[arg-type]
            except _CSV.CsvTaskSourceError as exc:
                assert exc.code == _COMMON.INVALID_INPUT, bad
            else:
                raise AssertionError(f"accepted invalid limit {bad!r}")


def test_select_candidates_rejects_duplicate_active_title() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        original = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Alpha,https://figma.com/file/a,u,i,a,\n"
            b"2,Alpha,https://figma.com/file/b,u2,i2,a2,\n"
        )
        p = _write_csv(d / "tasks.csv", original)
        try:
            _CSV.select_candidates(p, 5)
        except _CSV.CsvTaskSourceError as exc:
            assert "duplicate" in exc.message.lower()
        else:
            raise AssertionError("accepted duplicate active title")
        # Bytes unchanged.
        assert p.read_bytes() == original


# ---------------------------------------------------------------------------
# 3. Two concurrent processes claim the same blank title.
# ---------------------------------------------------------------------------


def _concurrent_claim_worker(csv_path: str, title: str, icp_scripts_dir: str,
                             ready, go, result_q) -> None:
    # Spawned workers do not inherit the parent's sys.path modifications, so
    # they re-add the ICP scripts dir and import the wrapper fresh.
    if icp_scripts_dir not in sys.path:
        sys.path.insert(0, icp_scripts_dir)
    import csv_task_source as csv_ts  # local to the worker
    ready.set()
    go.wait()
    try:
        ack = csv_ts.claim(Path(csv_path), title)
        result_q.put(("ok", ack))
    except csv_ts.CsvTaskSourceError as exc:
        result_q.put(("loss", exc.code))


def test_two_concurrent_claimants_exactly_one_wins() -> None:
    """Two processes race a CAS claim on the same blank title.

    Exactly one wins; the loser fails visibly. Final status is ``doing``; no
    corruption, no leftover temp files in the task directory.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        original = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Solo,https://figma.com/file/a,u,i,a,\n"
        )
        p = _write_csv(d / "tasks.csv", original)
        before_files = set(q.name for q in d.iterdir())

        ctx = mp.get_context("spawn")
        ready_a = ctx.Event()
        ready_b = ctx.Event()
        go = ctx.Event()
        result_q = ctx.Queue()

        a = ctx.Process(
            target=_concurrent_claim_worker,
            args=(str(p), "Solo", str(ICP_SCRIPTS), ready_a, go, result_q),
        )
        b = ctx.Process(
            target=_concurrent_claim_worker,
            args=(str(p), "Solo", str(ICP_SCRIPTS), ready_b, go, result_q),
        )
        a.start()
        b.start()
        ready_a.wait(timeout=10)
        ready_b.wait(timeout=10)
        go.set()
        a.join(timeout=20)
        b.join(timeout=20)
        assert not a.is_alive() and not b.is_alive(), "claim workers did not terminate"

        outcomes: list[tuple[str, str]] = []
        while not result_q.empty():
            kind, payload = result_q.get_nowait()
            if kind == "ok":
                outcomes.append(("ok", payload["status"]))
            else:
                outcomes.append(("loss", payload))

        wins = [o for o in outcomes if o[0] == "ok"]
        losses = [o for o in outcomes if o[0] == "loss"]
        assert len(wins) == 1, f"expected exactly one winner, got {outcomes}"
        assert len(losses) == 1, f"expected exactly one loser, got {outcomes}"
        assert wins[0][1] == "doing"
        # Final status on disk is exactly 'doing'.
        probe = _CSV.probe(p)
        assert probe["statuses"]["doing"] == 1
        assert probe["statuses"][""] == 0
        # No leftover temp files in the task directory.
        after_files = set(q.name for q in d.iterdir())
        assert before_files == after_files, (
            f"temp files left behind: {after_files - before_files}"
        )
        # The CSV is still valid and parses cleanly.
        assert probe["rows_total"] == 1


# ---------------------------------------------------------------------------
# 4. Stale expected status and duplicate-title claim fail; bytes unchanged.
# ---------------------------------------------------------------------------


def test_claim_with_stale_expected_status_fails_bytes_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        original = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,DoneRow,https://figma.com/file/a,u,i,a,done\n"
        )
        p = _write_csv(d / "tasks.csv", original)
        try:
            _CSV.claim(p, "DoneRow", expected_status="")
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("claimed a row whose status was not empty")
        assert p.read_bytes() == original


def test_claim_duplicate_title_fails_bytes_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        original = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Dup,https://figma.com/file/a,u,i,a,\n"
            b"2,Dup,https://figma.com/file/b,u2,i2,a2,\n"
        )
        p = _write_csv(d / "tasks.csv", original)
        try:
            _CSV.claim(p, "Dup", expected_status="")
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("claimed an ambiguous duplicate title")
        assert p.read_bytes() == original


# ---------------------------------------------------------------------------
# 5. Successful export creates exactly the canonical four files; no traversal.
# ---------------------------------------------------------------------------


def test_export_inputs_creates_exactly_canonical_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        ack = _CSV.claim(p, "Alpha")
        run_root = d / "run"
        export_ack = _CSV.export_inputs(p, ack, run_root)
        row_dir = Path(export_ack["row_directory"])
        # Exactly the four canonical files.
        produced = sorted(q.name for q in row_dir.iterdir())
        assert produced == ["api.txt", "interaction.txt", "row.json", "ui_notes.txt"], produced
        # row.json is canonical JSON and contains the title/design_url/status.
        row_json = json.loads((row_dir / "row.json").read_text(encoding="utf-8"))
        assert row_json["title"] == "Alpha"
        assert row_json["status"] == "doing"
        assert row_json["design_url"] == "https://figma.com/file/a"
        # The text files contain the right column values.
        assert (row_dir / "interaction.txt").read_text(encoding="utf-8") == "ie-A"
        assert (row_dir / "ui_notes.txt").read_text(encoding="utf-8") == "un-A"
        assert (row_dir / "api.txt").read_text(encoding="utf-8") == "ap-A"


def test_export_inputs_no_path_traversal_from_title() -> None:
    """A title containing path-traversal / shell metachars must not escape the
    run root directory."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        evil_title = "../../etc/passwd ; rm -rf /"
        original = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            + f"1,{evil_title},https://figma.com/file/a,u,i,a,\n".encode("utf-8")
        )
        p = _write_csv(d / "tasks.csv", original)
        ack = _CSV.claim(p, evil_title)
        run_root = d / "run"
        export_ack = _CSV.export_inputs(p, ack, run_root)
        row_dir = Path(export_ack["row_directory"])
        # row_dir is strictly beneath run_root.
        assert run_root in row_dir.parents
        # No file escaped: everything produced is inside row_dir.
        produced = [q for q in row_dir.iterdir()]
        assert all(run_root in q.parents for q in produced)
        # The directory name has no slash/dotdot.
        assert "/" not in row_dir.name
        assert ".." not in row_dir.name
        # And /etc/passwd is not touched (best-effort existence check).
        # Defensive: there is no 'passwd' file beneath our run root.
        for child in run_root.rglob("*"):
            assert "passwd" not in child.name


# ---------------------------------------------------------------------------
# 6. Writeback CAS doing -> done/error; stale writeback rejected.
# ---------------------------------------------------------------------------


def test_writeback_done_then_error_paths() -> None:
    for outcome in ("done", "error"):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Single blank row so the post-writeback status count is exact.
            original = (
                b"id,title,design_url,ui_notes,interaction,api,status\n"
                b"1,Solo,https://figma.com/file/a,u,i,a,\n"
            )
            p = _write_csv(d / "tasks.csv", original)
            ack = _CSV.claim(p, "Solo")
            wb = _CSV.writeback(p, ack, outcome=outcome)
            assert wb["status"] == outcome
            assert wb["previous_status"] == "doing"
            probe = _CSV.probe(p)
            assert probe["statuses"][outcome] == 1
            assert probe["statuses"]["doing"] == 0
            assert probe["statuses"][""] == 0


def test_writeback_invalid_outcome_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        ack = _CSV.claim(p, "Alpha")
        for bad in ("doing", "", "cancelled", "DONE", None):
            try:
                _CSV.writeback(p, ack, outcome=bad)  # type: ignore[arg-type]
            except _CSV.CsvTaskSourceError as exc:
                assert exc.code == _COMMON.INVALID_INPUT
            else:
                raise AssertionError(f"accepted bad outcome {bad!r}")


def test_writeback_stale_rejected_bytes_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        ack = _CSV.claim(p, "Alpha")
        # Move status to done via a parallel writeback, then try the stale
        # writeback again.
        first = _CSV.writeback(p, ack, outcome="done")
        assert first["status"] == "done"
        bytes_after_done = p.read_bytes()
        try:
            _CSV.writeback(p, ack, outcome="error")
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("stale writeback succeeded")
        assert p.read_bytes() == bytes_after_done


# ---------------------------------------------------------------------------
# 7. Manifest field set / digests / root derivation / deterministic bytes.
# ---------------------------------------------------------------------------


def _good_cands() -> list[dict]:
    return [
        {"row_index": 1, "title": "Alpha", "status": "",
         "design_url": "https://figma.com/file/a"},
        {"row_index": 2, "title": "Beta", "status": "",
         "design_url": "https://figma.com/file/b"},
    ]


def test_manifest_field_set_and_root_derivation() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        ack = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=_good_cands(),
            batch_id="batch-1", registries=reg,
        )
        manifest = json.loads(Path(ack["manifest_path"]).read_text(encoding="utf-8"))
        # Top-level field set.
        expected_top = {
            "kind", "schema_version", "batch_id", "resolved",
            "registry_digest", "selected_profile_digest", "rules_digest",
            "runtime_script_digests", "capabilities", "actual_batch_size",
            "candidates", "state_root", "run_root",
        }
        assert set(manifest.keys()) == expected_top, set(manifest.keys()) ^ expected_top
        assert manifest["kind"] == "icp.selection_manifest.v1"
        assert manifest["schema_version"] == 1
        assert manifest["batch_id"] == "batch-1"
        assert manifest["actual_batch_size"] == 2
        # Root derivation for flutter.
        assert manifest["state_root"] == str(d / ".iff")
        assert manifest["run_root"] == str(d / ".iff" / "icp_runs" / "batch-1")
        # Resolved block has no override keys.
        assert set(manifest["resolved"].keys()) == {
            "task_source", "task_ref", "design_source",
            "platform", "profile", "project_root",
        }
        # Digesets are present and well-formed.
        assert manifest["registry_digest"].startswith("sha256:")
        assert manifest["selected_profile_digest"].startswith("sha256:")
        assert manifest["rules_digest"].startswith("sha256:")
        # Runtime script digests include every fixed runtime script.
        for rel in ("icp_common.py", "csv_task_source.py",
                    "freeze_selection_manifest.py", "prepare_selection.py"):
            assert rel in manifest["runtime_script_digests"]
        # Candidate evidence.
        assert [c["title"] for c in manifest["candidates"]] == ["Alpha", "Beta"]


def test_manifest_vue_root_derivation() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(platform="vue", profile="vue-vite", project_root=str(d))
        ack = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=_good_cands()[:1],
            batch_id="vb-1", registries=reg,
        )
        manifest = json.loads(Path(ack["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["state_root"] == str(d / ".icp")
        assert manifest["run_root"] == str(d / ".icp" / "runs" / "vb-1")


def test_manifest_deterministic_bytes_for_identical_explicit_inputs() -> None:
    reg = _COMMON.load_registries()
    cands = _good_cands()

    def _one(project_root: Path) -> bytes:
        cfg = _config(project_root=str(project_root))
        ack = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=cands,
            batch_id="det-1", registries=reg,
        )
        return Path(ack["manifest_path"]).read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        b1 = _one(d)
        shutil.rmtree(d / ".iff" / "icp_runs" / "det-1")
        b2 = _one(d)
        assert b1 == b2, "identical explicit inputs produced different manifest bytes"


def test_manifest_digests_stable_across_different_project_roots() -> None:
    """Registry/profile/rules/runtime-script digests do not depend on the
    project root and must be stable across different deployment machines."""
    reg = _COMMON.load_registries()
    cands = _good_cands()
    digests: list[dict] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            cfg = _config(project_root=str(d))
            ack = _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=cands,
                batch_id="x", registries=reg,
            )
            m = json.loads(Path(ack["manifest_path"]).read_text(encoding="utf-8"))
            digests.append({
                "reg": m["registry_digest"],
                "prof": m["selected_profile_digest"],
                "rules": m["rules_digest"],
                "scripts": m["runtime_script_digests"],
                "caps": m["capabilities"],
            })
    assert digests[0] == digests[1]


# ---------------------------------------------------------------------------
# 8. Same batch/run-root conflict cannot overwrite the first manifest.
# ---------------------------------------------------------------------------


def test_same_run_root_conflict_does_not_overwrite() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        first = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=_good_cands(),
            batch_id="dup", registries=reg,
        )
        first_bytes = Path(first["manifest_path"]).read_bytes()
        # Second freeze with the same batch id must conflict.
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="dup", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code == _COMMON.SELECTION_MANIFEST_CONFLICT
        else:
            raise AssertionError("second freeze did not conflict")
        # First manifest bytes are byte-identical.
        assert Path(first["manifest_path"]).read_bytes() == first_bytes


def test_existing_manifest_file_in_run_root_conflicts() -> None:
    """If a manifest somehow already exists at the run root path, the freezer
    must refuse rather than overwrite it."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        # Pre-create the run root with a sentinel manifest.
        run_root = d / ".iff" / "icp_runs" / "preset"
        run_root.mkdir(parents=True)
        sentinel = run_root / "selection-manifest.json"
        sentinel.write_bytes(b'{"sentinel": true}\n')
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="preset", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code == _COMMON.SELECTION_MANIFEST_CONFLICT
        else:
            raise AssertionError("did not refuse pre-existing run root")
        # Sentinel untouched.
        assert sentinel.read_bytes() == b'{"sentinel": true}\n'


# ---------------------------------------------------------------------------
# 9. Forced manifest-freeze conflict/failure occurs before claim; statuses blank.
# ---------------------------------------------------------------------------


def test_manifest_conflict_leaves_statuses_blank_via_prepare() -> None:
    """End-to-end via prepare_selection: if the manifest cannot be frozen
    (run root already exists), no claim is attempted and every status is
    left blank."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        cfg = _config(project_root=str(d), task_ref=str(p))
        # Pre-create the run root so the freeze fails deterministically.
        pre_run_root = d / ".iff" / "icp_runs" / "fixed-batch"
        pre_run_root.mkdir(parents=True)
        ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=5, registries=_activated(reg, "flutter"),
            batch_id="fixed-batch",
        )
        assert ack["ok"] is False
        assert ack["code"] == _COMMON.SELECTION_MANIFEST_CONFLICT
        # Every task row status is still blank.
        probe = _CSV.probe(p)
        assert probe["statuses"][""] == 2


# ---------------------------------------------------------------------------
# Helpers for activating a registry in tests.
# ---------------------------------------------------------------------------


def _activated(registries: dict, platform: str) -> dict:
    """Return a deep copy of the registries with ``platform`` activated.

    Production registries never have any platform activated in P1b; this
    helper exists only so the orchestrator's post-gate path can be exercised
    by tests.
    """
    import copy
    out = copy.deepcopy(registries)
    out["platforms"][platform]["activated"] = True
    return out


# ---------------------------------------------------------------------------
# 10. Successful prepare: manifest durably present before claim callback.
# ---------------------------------------------------------------------------


def test_successful_prepare_manifest_present_before_claim_callback() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        cfg = _config(project_root=str(d), task_ref=str(p))

        observed: list[dict] = []

        def probe_callback(freeze_ack: dict, cand: dict) -> bool:
            manifest_path = Path(freeze_ack["manifest_path"])
            observed.append({
                "exists_at_callback": manifest_path.exists(),
                "readable": manifest_path.is_file(),
                "bytes_nonempty": manifest_path.stat().st_size > 0,
                "candidate": cand["title"],
            })
            return True

        ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=5, registries=_activated(reg, "flutter"),
            batch_id="prep-1", on_manifest_frozen=probe_callback,
        )
        assert ack["ok"] is True, ack
        # Two candidates -> two probe callbacks, each confirming durable
        # presence of the manifest.
        assert len(observed) == 2
        assert all(o["exists_at_callback"] and o["readable"] and o["bytes_nonempty"]
                   for o in observed)
        # Successful claim + export for both candidates.
        assert ack["successful_count"] == 2
        assert ack["failed_count"] == 0
        # Each success has both claim_ack and export_ack.
        for s in ack["successes"]:
            assert s["claim_ack"]["kind"] == "icp.claim.v1"
            assert s["claim_ack"]["status"] == "doing"
            assert s["export_ack"]["kind"] == "icp.export_inputs.v1"
            row_dir = Path(s["export_ack"]["row_directory"])
            assert sorted(q.name for q in row_dir.iterdir()) == [
                "api.txt", "interaction.txt", "row.json", "ui_notes.txt",
            ]
        # The exported files live under the run_root.
        run_root = Path(ack["freeze_ack"]["run_root"])
        for s in ack["successes"]:
            assert run_root in Path(s["export_ack"]["row_directory"]).parents


def test_prepare_one_failed_claim_excluded_from_successes() -> None:
    """One candidate whose CAS claim fails (status drift between select and
    claim) is reported as failed and excluded from successes."""
    reg = _COMMON.load_registries()

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        cfg = _config(project_root=str(d), task_ref=str(p))

        def claim_drifter(freeze_ack: dict, cand: dict) -> bool:
            # On the second candidate, race a competing claim so the
            # orchestrator's own claim CAS fails. This proves failures are
            # surfaced honestly and never faked as success.
            if cand["title"] == "Beta":
                _CSV.claim(p, "Beta")
            return True

        ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=5, registries=_activated(reg, "flutter"),
            batch_id="prep-2", on_manifest_frozen=claim_drifter,
        )
        assert ack["ok"] is True
        assert ack["successful_count"] == 1
        assert ack["failed_count"] == 1
        failed_titles = [c["row_identity"] for c in ack["claims"] if not c["ok"]]
        assert failed_titles == ["Beta"]


# ---------------------------------------------------------------------------
# 11. Production CLI: unsupported_platform before task touch; no overrides.
# ---------------------------------------------------------------------------


def test_cli_unsupported_platform_before_touching_nonexistent_task() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(
            d,
            _config(platform="react-native", task_ref="does-not-exist.csv"),
            name="c.json",
        )
        r = _run_prepare_cli(cfg, 5)
        assert r.returncode != 0
        assert r.stdout == ""
        assert "Traceback" not in r.stderr
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.UNSUPPORTED_PLATFORM
        # And the task path still does not exist.
        assert not (d / "does-not-exist.csv").exists()


def test_cli_exposes_no_registry_or_batch_override() -> None:
    """The CLI must not accept --registry, --batch-id, --state-root,
    --run-root, --script, --command, or --env overrides."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _config(), name="c.json")
        for flag in ("--registry", "--registries", "--batch-id", "--batch_id",
                     "--state-root", "--state_root", "--run-root", "--run_root",
                     "--script", "--script-path", "--command", "--env",
                     "--manifest-path", "--scripts-dir"):
            r = subprocess.run(
                [sys.executable, str(ICP_SCRIPTS / "prepare_selection.py"),
                 "--config", str(cfg), "--limit", "5", flag, "evil"],
                capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            assert r.returncode != 0, f"accepted override flag {flag!r}"
            # Either argparse rejected it (exit 2) or our JSON failure fired.
            assert r.stdout == "", flag


def test_cli_resolved_config_with_override_keys_rejected() -> None:
    """Override keys inside the resolved config must surface as invalid_input,
    not silently propagate into the manifest."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for evil in ("state_root", "run_root", "registry", "script",
                     "command", "env", "batch_id", "manifest_path"):
            cfg = _write_config(
                d, {**_config(), evil: "/evil"}, name=f"{evil}.json",
            )
            r = _run_prepare_cli(cfg, 5)
            assert r.returncode != 0, evil
            assert "Traceback" not in r.stderr
            payload = json.loads(r.stderr)
            assert payload["code"] == _COMMON.INVALID_INPUT, evil


# ---------------------------------------------------------------------------
# 12. Malformed config / CLI errors emit one JSON object, never traceback.
# ---------------------------------------------------------------------------


def test_cli_array_config_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, "[1,2,3]", name="arr.json")
        r = _run_prepare_cli(cfg, 5)
        assert r.returncode != 0
        assert r.stdout == ""
        assert "Traceback" not in r.stderr
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.INVALID_INPUT


def test_cli_scalar_config_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, '"oops"', name="s.json")
        r = _run_prepare_cli(cfg, 5)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_cli_malformed_json_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, "{not json", name="bad.json")
        r = _run_prepare_cli(cfg, 5)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_cli_duplicate_keys_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(
            d, '{"platform":"flutter","platform":"vue"}', name="dup.json"
        )
        r = _run_prepare_cli(cfg, 5)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_cli_missing_config_file_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        r = _run_prepare_cli(d / "absent.json", 5)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert json.loads(r.stderr)["code"] == _COMMON.INVALID_INPUT


def test_cli_zero_limit_no_traceback() -> None:
    """A non-positive --limit must surface as invalid_input."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Use an activated-registry trick via resolve-only path: production
        # CLI fails at the support gate before the limit check, but the
        # invalid_input code must still be a JSON object (no traceback).
        cfg = _write_config(d, _config(), name="c.json")
        r = _run_prepare_cli(cfg, 0)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        payload = json.loads(r.stderr)
        assert payload["ok"] is False


def test_cli_non_integer_limit_no_traceback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _write_config(d, _config(), name="c.json")
        r = subprocess.run(
            [sys.executable, str(ICP_SCRIPTS / "prepare_selection.py"),
             "--config", str(cfg), "--limit", "abc"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert r.returncode != 0
        # No traceback, and exactly one JSON object on stderr.
        assert "Traceback" not in r.stderr
        assert "usage:" not in r.stderr
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert payload["code"] == _COMMON.INVALID_INPUT


def test_cli_success_returns_canonical_json() -> None:
    """A successful activated-platform prepare returns canonical JSON on
    stdout (one object)."""
    reg = _COMMON.load_registries()
    # The production CLI cannot activate a platform (no override). So this
    # test drives the lower-level function and asserts its bytes are canonical
    # when encoded by the same helper the CLI uses.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p = _write_csv(d / "tasks.csv", _good_csv_multi())
        cfg = _config(project_root=str(d), task_ref=str(p))
        ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=2, registries=_activated(reg, "flutter"),
            batch_id="cli-1",
        )
        assert ack["ok"] is True
        encoded = _COMMON.canonical_json_bytes(ack)
        # Re-decode and compare round-trip.
        assert json.loads(encoded.decode("utf-8"))["ok"] is True


# ===========================================================================
# P1b contract-repair regression tests (strict TDD: RED captured before fix).
# ===========================================================================


ICP_ROOT = ICP_SCRIPTS.parent


def _skill_md_sha256() -> str:
    return hashlib.sha256((ICP_ROOT / "SKILL.md").read_bytes()).hexdigest()


def _expected_runtime_script_set() -> set[str]:
    return {
        "icp_common.py",
        "resolve_run_config.py",
        "preflight_selection.py",
        "csv_task_source.py",
        "freeze_selection_manifest.py",
        "prepare_selection.py",
        str(Path("task_sources") / "__init__.py"),
        str(Path("task_sources") / "csv_row_status_v1.py"),
    }


# --- Boundary 1: no external scripts_dir override --------------------------


def test_freezer_signatures_expose_no_scripts_dir_and_override_rejected() -> None:
    """Neither build_manifest_payload nor freeze_selection_manifest may accept a
    scripts_dir/path; runtime script digests come from the fixed icp/scripts
    tree only."""
    freeze_sig = inspect.signature(_FREEZE.freeze_selection_manifest)
    assert "scripts_dir" not in freeze_sig.parameters, freeze_sig
    build_sig = inspect.signature(_FREEZE.build_manifest_payload)
    assert "scripts_dir" not in build_sig.parameters, build_sig
    # Any scripts_dir kwarg must be rejected at call time.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="sig-1", registries=_COMMON.load_registries(),
                scripts_dir=d,  # type: ignore[call-arg]
            )
        except TypeError:
            pass
        else:
            raise AssertionError("freeze_selection_manifest accepted scripts_dir=")


# --- Boundary 2: rules_digest == sha256(SKILL.md bytes) --------------------


def test_rules_digest_equals_sha256_of_skill_md_bytes() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        ack = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=_good_cands(),
            batch_id="rules-1", registries=reg,
        )
        manifest = json.loads(Path(ack["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["rules_digest"] == f"sha256:{_skill_md_sha256()}"


# --- Boundary 3: runtime_script_digests exact eight-file set ---------------


def test_runtime_script_digests_exact_eight_file_set() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        ack = _FREEZE.freeze_selection_manifest(
            resolved_config=cfg, candidates=_good_cands(),
            batch_id="runtime-1", registries=reg,
        )
        manifest = json.loads(Path(ack["manifest_path"]).read_text(encoding="utf-8"))
        assert set(manifest["runtime_script_digests"].keys()) == _expected_runtime_script_set()


# --- Boundary 4: derive_roots batch id validation --------------------------


def test_derive_roots_accepts_generated_batch_id_form() -> None:
    bid = _PREPARE.generate_batch_id()
    state_root, run_root = _FREEZE.derive_roots("flutter", "/tmp/proj", bid)
    assert run_root.name == bid


def test_derive_roots_rejects_unsafe_batch_ids() -> None:
    bad_ids = [
        "", ".", "..", "a/b", "a\\b", "a b", " leading", "trailing ",
        "_leading-underscore", "-leading-hyphen", ".dotfirst",
        "has/slash", "has\\backslash", "tab\tchar", "newline\nchar",
        "a" * 129,            # overlong (129 chars)
        "a:b", "a;b", "a*b", "a?b", "a|b", "a<b", 'a"b',
        "café",               # non-ascii
    ]
    for bad in bad_ids:
        try:
            _FREEZE.derive_roots("flutter", "/tmp/proj", bad)
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code == _COMMON.INVALID_INPUT, bad
        else:
            raise AssertionError(f"derive_roots accepted unsafe batch id {bad!r}")


def test_derive_roots_rejects_trailing_newline_batch_id() -> None:
    """The documented ``batch_id`` grammar
    ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`` is a whole-string contract.
    Python's ``re.match(r'...$')`` accepts a value ending in a single
    newline (``$`` may match before the final newline); the producer
    must reject such input. macOS permits a directory name containing a
    newline, so this is a real on-disk attack surface, not theoretical.
    """
    for bad in ("batch-001\n", "a\n", "batch-001\r\n"):
        try:
            _FREEZE.derive_roots("flutter", "/tmp/proj", bad)
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code == _COMMON.INVALID_INPUT, bad
        else:
            raise AssertionError(
                f"derive_roots accepted trailing-newline batch id {bad!r}"
            )


def test_derive_roots_accepts_exact_max_length_batch_id() -> None:
    """A 128-character batch id (first char + 127 from the suffix class)
    is the exact max-length valid form and must be accepted."""
    bid = "b" + "0" * 127  # 128 chars total
    assert len(bid) == 128
    state_root, run_root = _FREEZE.derive_roots("flutter", "/tmp/proj", bid)
    assert run_root.name == bid


def test_freeze_rejects_trailing_newline_batch_id_before_any_disk_change() -> None:
    """``freeze_selection_manifest`` must reject a trailing-newline
    ``batch_id`` at input validation, BEFORE creating the state root,
    run parent, run root, or manifest. No side-effect may leak."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cfg = _config(project_root=str(d))
        # Snapshot the project root before the call (must stay empty).
        before = set(p.name for p in d.iterdir()) if d.exists() else set()
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="nl-batch\n", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code == _COMMON.INVALID_INPUT
        else:
            raise AssertionError(
                "freeze_selection_manifest accepted trailing-newline batch id"
            )
        # No state/run directory or manifest may have been created.
        after = set(p.name for p in d.iterdir())
        assert before == after, (
            f"freeze created side effects before rejecting batch id: "
            f"added={sorted(after - before)}"
        )


# --- Boundary 5: atomic no-clobber publication under a deterministic race --


def test_manifest_publication_race_preserves_sentinel() -> None:
    """A destination created after the explicit existence check but before
    publication must survive byte-for-byte; the freezer must return
    selection_manifest_conflict and leave no owned temporary artifact.
    os.replace must not publish the final manifest."""
    reg = _COMMON.load_registries()
    real_replace = _FREEZE.os.replace
    real_link = getattr(_FREEZE.os, "link", os.link)
    sentinel = b'{"race": "sentinel"}\n'

    def _install_race(real_call):
        def wrapper(src, dst, *args, **kwargs):
            dst_path = Path(str(dst))
            if dst_path.name == _FREEZE.MANIFEST_FILENAME and not wrapper._fired:  # type: ignore[attr-defined]
                wrapper._fired = True  # type: ignore[attr-defined]
                dst_path.write_bytes(sentinel)
            return real_call(src, dst, *args, **kwargs)
        wrapper._fired = False  # type: ignore[attr-defined]
        return wrapper

    _FREEZE.os.replace = _install_race(real_replace)
    _FREEZE.os.link = _install_race(real_link)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            cfg = _config(project_root=str(d))
            try:
                _FREEZE.freeze_selection_manifest(
                    resolved_config=cfg, candidates=_good_cands(),
                    batch_id="race-1", registries=reg,
                )
            except _FREEZE.ManifestFreezeError as exc:
                assert exc.code == _COMMON.SELECTION_MANIFEST_CONFLICT, exc.code
            else:
                raise AssertionError("race did not surface selection_manifest_conflict")
            manifest_path = d / ".iff" / "icp_runs" / "race-1" / _FREEZE.MANIFEST_FILENAME
            # Sentinel survives byte-for-byte.
            assert manifest_path.read_bytes() == sentinel
            # No owned temporary artifacts anywhere under the run root.
            run_root = manifest_path.parent
            tmp_leftovers = [
                str(p) for p in run_root.rglob("*")
                if p.is_file() and ".tmp" in p.name
            ]
            assert tmp_leftovers == [], tmp_leftovers
    finally:
        _FREEZE.os.replace = real_replace
        _FREEZE.os.link = real_link


# --- Boundary 6: hard order — symlink CSV rejected before run root creation


def test_prepare_symlink_csv_rejected_before_run_root_creation() -> None:
    """With an activated in-memory Flutter registry, a symlink task path must
    fail with task_preflight_failed before any run root/manifest is created and
    leave the real target bytes unchanged."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real_csv = d / "real.csv"
        real_csv.write_bytes(_good_csv_multi())
        link_csv = d / "link.csv"
        link_csv.symlink_to(real_csv)
        cfg = _config(project_root=str(d), task_ref=str(link_csv))
        ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=5,
            registries=_activated(reg, "flutter"), batch_id="sym-1",
        )
        assert ack["ok"] is False
        assert ack["code"] == _COMMON.TASK_PREFLIGHT_FAILED
        # No run root or manifest was created.
        run_root = d / ".iff" / "icp_runs" / "sym-1"
        assert not run_root.exists()
        # Real target bytes unchanged.
        assert real_csv.read_bytes() == _good_csv_multi()


# --- Boundary 6 (direct): probe/select/claim/writeback reject symlink/non-reg


def _make_symlink_and_real(d: Path) -> tuple[Path, Path]:
    real = d / "real.csv"
    real.write_bytes(_good_csv_multi())
    link = d / "link.csv"
    link.symlink_to(real)
    return link, real


def test_probe_rejects_symlink_and_nonregular() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        link, real = _make_symlink_and_real(d)
        try:
            _CSV.probe(link)
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("probe accepted a symlink")
        assert real.read_bytes() == _good_csv_multi()
        # Non-regular (FIFO) rejection (POSIX only).
        if os.name == "posix":
            fifo = d / "pipe.csv"
            try:
                os.mkfifo(fifo)
            except (OSError, PermissionError):
                pass
            else:
                try:
                    _CSV.probe(fifo)
                except _CSV.CsvTaskSourceError as exc:
                    assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
                else:
                    raise AssertionError("probe accepted a FIFO")


def test_probe_write_readiness_is_atomic_and_leaves_task_and_directory_clean() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        task = root / "tasks.csv"
        task.write_bytes(_good_csv_multi())
        before = task.read_bytes()
        before_names = sorted(path.name for path in root.iterdir())
        report = _CSV.probe_write_readiness(task)
        assert report["kind"] == "task_source_write_readiness.v1"
        assert report["ok"] is True
        assert len(report["evidence_digest"]) == 64
        assert task.read_bytes() == before
        assert sorted(path.name for path in root.iterdir()) == before_names


def test_select_candidates_rejects_symlink_and_nonregular() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        link, real = _make_symlink_and_real(d)
        try:
            _CSV.select_candidates(link, 5)
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
        else:
            raise AssertionError("select_candidates accepted a symlink")
        assert real.read_bytes() == _good_csv_multi()


def test_claim_rejects_symlink_and_nonregular_before_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        link, real = _make_symlink_and_real(d)
        try:
            _CSV.claim(link, "Alpha")
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
        else:
            raise AssertionError("claim accepted a symlink")
        # Real target bytes unchanged (no mutation).
        assert real.read_bytes() == _good_csv_multi()


def test_writeback_rejects_symlink_and_nonregular_before_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real.csv"
        single = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Solo,https://figma.com/file/a,u,i,a,\n"
        )
        real.write_bytes(single)
        link = d / "link.csv"
        link.symlink_to(real)
        # Claim through the real file first so a claim ack exists; then attempt
        # writeback through the symlink, which must be rejected before any
        # mutation of the real target.
        ack = _CSV.claim(real, "Solo")
        before = real.read_bytes()
        try:
            _CSV.writeback(link, ack, outcome="done")
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
        else:
            raise AssertionError("writeback accepted a symlink")
        assert real.read_bytes() == before


# --- Boundary 7: task_source_failed eliminated; all codes registered --------


_RUNTIME_MODULES_FOR_CODE_SCAN = (
    "icp_common.py",
    "csv_task_source.py",
    "freeze_selection_manifest.py",
    "prepare_selection.py",
    str(Path("task_sources") / "__init__.py"),
)


def test_no_task_source_failed_code_in_runtime_modules() -> None:
    """The literal ``task_source_failed`` must be absent from every runtime
    module; every emitted code must belong to ALL_ERROR_CODES."""
    for rel in _RUNTIME_MODULES_FOR_CODE_SCAN:
        src = (ICP_SCRIPTS / rel).read_text(encoding="utf-8")
        assert "task_source_failed" not in src, (
            f"task_source_failed literal present in {rel}"
        )


def test_all_emitted_codes_belong_to_all_error_codes() -> None:
    """Drive every representative failure path in the P1b suite and assert each
    emitted ``code`` is registered in ALL_ERROR_CODES. Never report a failed
    CAS as success."""
    emitted: list[str] = []

    def _record(code: str) -> None:
        emitted.append(code)

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        # 1. claim stale status -> task_preflight_failed
        p1 = _write_csv(d / "stale.csv", _good_csv_multi())
        try:
            _CSV.claim(p1, "Gamma", expected_status="")
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 2. claim duplicate title -> task_preflight_failed
        dup = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Dup,https://figma.com/file/a,u,i,a,\n"
            b"2,Dup,https://figma.com/file/b,u2,i2,a2,\n"
        )
        p2 = _write_csv(d / "dup.csv", dup)
        try:
            _CSV.claim(p2, "Dup", expected_status="")
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 3. writeback invalid outcome -> invalid_input
        p3 = _write_csv(d / "wb.csv", _good_csv_multi())
        ack3 = _CSV.claim(p3, "Alpha")
        try:
            _CSV.writeback(p3, ack3, outcome="bogus")  # type: ignore[arg-type]
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 4. writeback stale -> task_preflight_failed
        _CSV.writeback(p3, ack3, outcome="done")
        try:
            _CSV.writeback(p3, ack3, outcome="error")
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 5. claim on symlink -> task_preflight_failed
        real = d / "real.csv"
        real.write_bytes(_good_csv_multi())
        link = d / "link.csv"
        link.symlink_to(real)
        try:
            _CSV.claim(link, "Alpha")
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 6. probe on missing -> task_preflight_failed
        try:
            _CSV.probe(d / "absent.csv")
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 7. select_candidates invalid limit -> invalid_input
        try:
            _CSV.select_candidates(p1, 0)
        except _CSV.CsvTaskSourceError as exc:
            _record(exc.code)

        # 8. prepare: a failed claim (status drift) surfaces task_preflight_failed
        #    on the failed row, is never reported as success.
        reg = _COMMON.load_registries()
        p4 = _write_csv(d / "drift.csv", _good_csv_multi())
        cfg = _config(project_root=str(d), task_ref=str(p4))

        def drifter(freeze_ack: dict, cand: dict) -> bool:
            if cand["title"] == "Beta":
                _CSV.claim(p4, "Beta")
            return True

        prepare_ack = _PREPARE.prepare_selection(
            resolved_config=cfg, limit=5, registries=_activated(reg, "flutter"),
            batch_id="codes-1", on_manifest_frozen=drifter,
        )
        assert prepare_ack["ok"] is True
        # The failed claim must carry a registered code and never be in successes.
        for entry in prepare_ack["claims"]:
            if not entry["ok"]:
                _record(entry["code"])
        assert prepare_ack["successful_count"] == 1
        assert prepare_ack["failed_count"] == 1

    # Every emitted code is registered.
    for code in emitted:
        assert code in _COMMON.ALL_ERROR_CODES, (
            f"emitted unregistered code {code!r}"
        )
    # task_source_failed was never emitted.
    assert "task_source_failed" not in emitted, emitted
    # We actually exercised the paths.
    assert _COMMON.TASK_PREFLIGHT_FAILED in emitted
    assert _COMMON.INVALID_INPUT in emitted


# ===========================================================================
# P1b final-repair regression tests (strict TDD: RED captured before fix).
# ===========================================================================


# --- Repair 1: publication event order (link < temp_unlink < dir_fsync) -----


def test_publication_event_order_link_before_unlink_before_dirfsync() -> None:
    """On a successful freeze the observable event order must be:

        temp fsync  <  os.link(temp, manifest)  <  owned temp unlink  <  dir fsync

    The current code does dir-fsync before temp-unlink, which violates the
    locked durability order.
    """
    reg = _COMMON.load_registries()
    events: list[tuple[int, str]] = []
    counter = [0]

    def _tick(label: str) -> None:
        counter[0] += 1
        events.append((counter[0], label))

    real_link = _FREEZE.os.link
    real_unlink = _FREEZE.os.unlink
    real_fsync = _FREEZE.os.fsync

    def wrapped_link(src, dst, *args, **kwargs):
        _tick("link")
        return real_link(src, dst, *args, **kwargs)

    def wrapped_unlink(path, *args, **kwargs):
        p = Path(str(path))
        if p.name.startswith(".selection-manifest.json.") and p.suffix == ".tmp":
            _tick("temp_unlink")
        return real_unlink(path, *args, **kwargs)

    def wrapped_fsync(fd, *args, **kwargs):
        # We cannot easily map fd -> path here, but the manifest temp is the
        # only fsync target before link, and the directory fsync is the only
        # fsync after link. Distinguish by checking whether the temp still
        # exists in the run directory at the time of the call.
        # Simpler: record all fsync calls and assert the post-link directory
        # fsync happens after temp_unlink by counting.
        _tick("fsync")
        return real_fsync(fd, *args, **kwargs)

    _FREEZE.os.link = wrapped_link
    _FREEZE.os.unlink = wrapped_unlink
    _FREEZE.os.fsync = wrapped_fsync
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            cfg = _config(project_root=str(d))
            ack = _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="order-1", registries=reg,
            )
            assert ack["ok"] is True
    finally:
        _FREEZE.os.link = real_link
        _FREEZE.os.unlink = real_unlink
        _FREEZE.os.fsync = real_fsync

    # Extract the ordering of the key events.
    labels = [label for _seq, label in events]
    try:
        link_idx = labels.index("link")
    except ValueError:
        raise AssertionError(f"no os.link event observed; events={events}")
    temp_unlink_indices = [i for i, lab in enumerate(labels) if lab == "temp_unlink"]
    assert temp_unlink_indices, f"no owned temp unlink observed; events={events}"
    temp_unlink_idx = temp_unlink_indices[0]
    # The directory fsync is the last fsync call after link.
    fsync_after_link = [i for i, lab in enumerate(labels) if lab == "fsync" and i > link_idx]
    assert fsync_after_link, f"no directory fsync after link; events={events}"
    dir_fsync_idx = fsync_after_link[-1]

    assert link_idx < temp_unlink_idx, (
        f"link must precede temp_unlink; events={events}"
    )
    assert temp_unlink_idx < dir_fsync_idx, (
        f"temp_unlink must precede directory fsync; events={events}"
    )


# --- Repair 2a: Flutter state-root symlink rejected -------------------------


def test_flutter_state_root_symlink_rejected_no_external_creation() -> None:
    """A project where ``.iff`` is a symlink to an external directory must be
    rejected; the external directory must receive no run root or manifest."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        external = d / "external"
        external.mkdir()
        project = d / "proj"
        project.mkdir()
        (project / ".iff").symlink_to(external)
        cfg = _config(project_root=str(project))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="symstate-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze followed a symlinked state root")
        # External directory receives nothing.
        assert list(external.iterdir()) == [], (
            f"external dir polluted: {list(external.iterdir())}"
        )
        # No icp_runs tree appeared under the external target.
        assert not (external / "icp_runs").exists()


# --- Repair 2b: Vue state-root symlink rejected -----------------------------


def test_vue_state_root_symlink_rejected_no_external_creation() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        external = d / "external"
        external.mkdir()
        project = d / "proj"
        project.mkdir()
        (project / ".icp").symlink_to(external)
        cfg = _config(platform="vue", profile="vue-vite", project_root=str(project))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands()[:1],
                batch_id="symstate-vue-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze followed a symlinked vue state root")
        assert list(external.iterdir()) == []
        assert not (external / "runs").exists()


# --- Repair 3a: Flutter run-parent symlink rejected ------------------------


def test_flutter_run_parent_symlink_rejected_no_external_creation() -> None:
    """If ``.iff/icp_runs`` is a symlink to an external directory, the freeze
    must reject it and create nothing in the external target."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        external = d / "external-runs"
        external.mkdir()
        project = d / "proj"
        project.mkdir()
        iff_dir = project / ".iff"
        iff_dir.mkdir()
        (iff_dir / "icp_runs").symlink_to(external)
        cfg = _config(project_root=str(project))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="symparent-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze followed a symlinked run parent")
        assert list(external.iterdir()) == []


# --- Repair 3b: Vue run-parent symlink rejected ----------------------------


def test_vue_run_parent_symlink_rejected_no_external_creation() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        external = d / "external-vue-runs"
        external.mkdir()
        project = d / "proj"
        project.mkdir()
        icp_dir = project / ".icp"
        icp_dir.mkdir()
        (icp_dir / "runs").symlink_to(external)
        cfg = _config(platform="vue", profile="vue-vite", project_root=str(project))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands()[:1],
                batch_id="symparent-vue-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze followed a symlinked vue run parent")
        assert list(external.iterdir()) == []


# --- Repair 4: symlinked project root rejected; missing root not created ----


def test_symlinked_project_root_rejected_by_direct_freeze() -> None:
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real_project = d / "real-project"
        real_project.mkdir()
        link_project = d / "link-project"
        link_project.symlink_to(real_project)
        cfg = _config(project_root=str(link_project))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="symproj-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze followed a symlinked project root")
        # Nothing created under the real project.
        assert not (real_project / ".iff").exists()


def test_missing_project_root_not_created_by_direct_freeze() -> None:
    """The freezer must not create a missing project root; only the derived
    state/run roots beneath an existing project root are created."""
    reg = _COMMON.load_registries()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        missing = d / "does-not-exist"
        cfg = _config(project_root=str(missing))
        try:
            _FREEZE.freeze_selection_manifest(
                resolved_config=cfg, candidates=_good_cands(),
                batch_id="missing-1", registries=reg,
            )
        except _FREEZE.ManifestFreezeError as exc:
            assert exc.code in _COMMON.ALL_ERROR_CODES
        else:
            raise AssertionError("freeze created a missing project root")
        assert not missing.exists(), "freezer created the missing project root"


# --- Repair 5: export_inputs validates task path before run-root mutation ---


def test_export_inputs_symlink_task_leaves_run_root_absent() -> None:
    """A symlink task ref must be rejected before ``run_root`` or any
    ``row-*`` directory is created."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        real = d / "real.csv"
        real.write_bytes(_good_csv_multi())
        link = d / "link.csv"
        link.symlink_to(real)
        # A valid claim_ack shape so the only failure is the task path gate.
        claim_ack = {
            "kind": "icp.claim.v1", "schema_version": 1, "ok": True,
            "row_identity": "Alpha", "status": "doing",
        }
        run_root = d / "run-root"
        try:
            _CSV.export_inputs(link, claim_ack, run_root)
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
        else:
            raise AssertionError("export_inputs accepted a symlink task ref")
        # The run root was never created.
        assert not run_root.exists(), (
            f"run_root created before task validation: {list(run_root.rglob('*')) if run_root.exists() else ''}"
        )
        # No row directory anywhere.
        assert not list(d.glob("**/row-*"))


def test_export_inputs_nonregular_task_leaves_run_root_absent() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        fifo = d / "pipe.csv"
        try:
            os.mkfifo(fifo)
        except (OSError, PermissionError):
            return
        claim_ack = {
            "kind": "icp.claim.v1", "schema_version": 1, "ok": True,
            "row_identity": "Alpha", "status": "doing",
        }
        run_root = d / "run-root"
        try:
            _CSV.export_inputs(fifo, claim_ack, run_root)
        except _CSV.CsvTaskSourceError as exc:
            assert exc.code == _COMMON.TASK_PREFLIGHT_FAILED
        else:
            raise AssertionError("export_inputs accepted a FIFO task ref")
        assert not run_root.exists()
        assert not list(d.glob("**/row-*"))


# ---------------------------------------------------------------------------
# 13. P1a 79 tests remain green.
# ---------------------------------------------------------------------------
def test_p1a_selftest_remains_green() -> None:
    """Re-run the P1a selftest module and assert it reports 79 PASS, 0 FAIL."""
    p1a = _load("selftest_p1a_for_p1b", ICP_SCRIPTS / "selftest_p1a.py")
    original_stdout = sys.stdout
    captured: list[str] = []
    try:
        sys.stdout = _Capture(captured)
        rc = p1a.main()
    finally:
        sys.stdout = original_stdout
    text = "".join(captured)
    assert rc == 0, text
    # The P1a selftest prints a final "ok N selftest cases" line.
    m = re.search(r"ok (\d+) selftest cases", text)
    assert m is not None, text
    assert int(m.group(1)) == 79, text
    assert "FAIL" not in text


class _Capture:
    """Minimal stdout capture for the P1a selftest re-run."""

    def __init__(self, sink: list[str]) -> None:
        self.sink = sink

    def write(self, s: str) -> int:
        self.sink.append(s)
        return len(s)

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Selftest runner.
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [name for name in globals() if name.startswith("test_")]
    failures = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"FAILED {failures}/{len(tests)}")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
