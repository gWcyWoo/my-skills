#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2.5a2 Flutter expected/slots
adapter (``platforms/flutter_expected_slots_adapter_v1.py``).

P2.5a2 adds exactly one platform post-step to ``flutter.visible_codegen.v1``
between ``generate_canvas`` and ``make_implementation_map``: the
``adapt_expected_slots`` step. That step runs this adapter, which:

  1. reads ONLY the exact ``<canvas>.expected.json`` and ``<canvas>.slots.json``
     sidecars emitted by the immediately preceding ``generate_canvas`` step;
  2. reconstructs the platform-neutral ``icp.shared.expected-slots-projection.v1``
     losslessly from those sidecars;
  3. calls the existing SharedCore producer
     (``shared_core/expected_slots_projection_v1.build_legacy_bytes``) loaded
     only from the fixed installed sibling path;
  4. requires byte-for-byte equality between both rebuilt sidecars and the
     original raw bytes; and
  5. only then atomically persists the byte-identical SharedCore output as
     the final expected/slots truth, preserving each original file's mode.

The adapter is fail-closed: missing, malformed, noncanonical, duplicate-key,
oversized, symlinked, out-of-root, changed-during-read, or parity-divergent
inputs raise a typed ``ExpectedSlotsAdapterError`` and write nothing. Failures
surface only the type name (no traceback, no raw input/path leak).

Run directly::

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25a2_flutter_expected_slots_adapter.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
SHARED_CORE_DIR = ICP_SCRIPTS / "shared_core"
ADAPTER_PATH = PLATFORMS_DIR / "flutter_expected_slots_adapter_v1.py"
PROJECTION_PATH = SHARED_CORE_DIR / "expected_slots_projection_v1.py"
OPERATIONS_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
CAPSULE_GENERATE_CANVAS = CAPSULE_SCRIPTS / "generate_canvas.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"

KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1

# Maximum sidecar size the adapter must accept (16 MiB).
MAX_SIDECAR_BYTES = 16 * 1024 * 1024

# Hard forbidden tokens for the production adapter source. Lives in TEST only.
# These are *import / execution surface* tokens, not bare word mentions: the
# adapter docstring legitimately references generate_canvas as context.
FORBIDDEN_TOKENS = (
    "import socket",
    "import urllib",
    "import http.client",
    "import requests",
    "shell=True",
    "os.system",
    "os.popen",
    "os.exec",
    "os.spawn",
    "os.fork",
    "__import__",
    "import generate_canvas",
    "from generate_canvas",
    "vendor.iff_v1",
    "import iff",
    "from iff",
)


# ---------------------------------------------------------------------------
# Module loaders.
# ---------------------------------------------------------------------------


def _load_adapter(name: str = "p25a2_adapter"):
    spec = importlib.util.spec_from_file_location(name, str(ADAPTER_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_projection(name: str = "p25a2_proj"):
    spec = importlib.util.spec_from_file_location(name, str(PROJECTION_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_operations(name: str = "p25a2_ops"):
    spec = importlib.util.spec_from_file_location(name, str(OPERATIONS_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_capsule_generate_canvas():
    spec = importlib.util.spec_from_file_location(
        "p25a2_capsule_generate_canvas", str(CAPSULE_GENERATE_CANVAS)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25a2_capsule_generate_canvas"] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p25a2_"):
    """A temp dir whose path is realpath-canonicalized (macOS /tmp symlink)."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


def _run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(ADAPTER_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_bytes(path: Path, data: bytes) -> bytes:
    path.write_bytes(data)
    return data


def _write_json(path: Path, payload: Any) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(data)
    return data


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


# ---------------------------------------------------------------------------
# Corpus (reuses the P2.5a1 differential corpus shape: Unicode text, dynamic
# slot, styled runs, non-text shape, non-default scale, deterministic order).
# ---------------------------------------------------------------------------


def _build_corpus_render_plan() -> dict[str, Any]:
    def text_node(
        node_id: str, bbox: list[float], text: str, font_size: float,
        weight: Any = None, fills=None, runs=None,
    ) -> dict[str, Any]:
        return {
            "name": node_id, "bbox": bbox, "implementation": "text",
            "parent": "root", "children": [], "text": text,
            "textRuns": runs or [], "fills": fills if fills is not None else ["#000000"],
            "rawFills": [], "border": [], "radius": 0, "shadow": [],
            "opacity": 1, "visible": True, "required": True,
            "fontSize": font_size, "weight": weight,
        }

    def shape_node(node_id: str, bbox: list[float], fills=None, radius=None) -> dict[str, Any]:
        return {
            "name": node_id, "bbox": bbox, "implementation": "shape_container",
            "parent": "root", "children": [],
            "fills": fills if fills is not None else ["#FFFFFF"],
            "rawFills": [], "border": [],
            "radius": radius if radius is not None else 0,
            "shadow": [], "opacity": 1, "visible": True, "required": True,
        }

    return {
        "rootNode": None,
        "nodes": {
            "root": {
                "name": "root", "bbox": [0, 0, 750, 1624],
                "implementation": "shape_container", "parent": None,
                "children": ["card_bg", "title", "amount", "subtitle", "french", "vector_deco"],
                "fills": ["#FAFAFA"], "rawFills": [], "border": [], "radius": 0,
                "shadow": [], "opacity": 1, "visible": True, "required": True,
            },
            "card_bg": shape_node(
                "card_bg", [40, 120, 670, 300], fills=["#3366FF"],
                radius={"topLeft": 16, "topRight": 16, "bottomLeft": 16, "bottomRight": 16},
            ),
            "title": text_node(
                "title", [60, 140, 400, 20], "你好,世界 🌍 — café",
                font_size=16, weight=700, fills=["#222222"],
            ),
            "amount": text_node(
                "amount", [60, 180, 200, 20], "$1,234.56",
                font_size=16, weight=400, fills=["#FFFFFF"],
            ),
            "subtitle": text_node(
                "subtitle", [60, 220, 320, 16], "BoldRed NormGreen",
                font_size=14, fills=["#000000"],
                runs=[
                    {"content": "BoldRed", "font": {"size": 14, "fontWeight": 700}, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                    {"content": " NormGreen", "font": {"size": 14, "fontWeight": 400}, "color": {"r": 0, "g": 0.5, "b": 0, "a": 1}},
                ],
            ),
            "french": text_node(
                "french", [60, 260, 200, 14], "ÉàÜ — 中文 — 한국어",
                font_size=12, fills=["#FFFFFF"],
            ),
            "vector_deco": shape_node(
                "vector_deco", [700, 1400, 24, 24], fills=[], radius=0,
            ),
        },
    }


def _build_corpus_classification() -> dict[str, Any]:
    return {"artboard": {"width": 750, "height": 1624, "scale": 2},
            "viewport": {"width": 375, "height": 812}}


def _build_corpus_component_manifest() -> dict[str, Any]:
    return {
        "source": "test_fixture",
        "components": [{
            "name": "AmountSlot", "kind": "slot", "rootNode": "amount",
            "bbox": [60, 180, 200, 20],
            "dynamicSlots": [{"node": "amount", "role": "dynamic_text_slot"}],
            "staticTextLabels": [], "nodes": [],
        }],
    }


@contextlib.contextmanager
def _run_real_capsule_for_corpus(tmp: Path):
    """Run the frozen generate_canvas.py for the corpus, yield the paths to
    the produced canvas.dart and its expected/slots sidecars."""
    gc = _load_capsule_generate_canvas()
    render_plan_path = tmp / "render_plan.json"
    classification_path = tmp / "design_classification.json"
    component_manifest_path = tmp / "component_manifest.json"
    out_dart = tmp / "canvas.dart"
    _write_json(render_plan_path, _build_corpus_render_plan())
    _write_json(classification_path, _build_corpus_classification())
    _write_json(component_manifest_path, _build_corpus_component_manifest())
    original_argv = sys.argv[:]
    sys.argv = [
        str(CAPSULE_GENERATE_CANVAS),
        "--render-plan", str(render_plan_path),
        "--classification", str(classification_path),
        "--component-manifest", str(component_manifest_path),
        "--out", str(out_dart),
        "--class-name", "DiffCanvas",
    ]
    try:
        rc = gc.main()
    finally:
        sys.argv = original_argv
    assert rc == 0, f"capsule main() returned rc={rc}"
    yield (
        out_dart,
        Path(str(out_dart) + ".expected.json"),
        Path(str(out_dart) + ".slots.json"),
    )


# ---------------------------------------------------------------------------
# Test project builder (a project-root tree containing a canvas + sidecars).
# ---------------------------------------------------------------------------


def _build_project_with_canvas(tmp: Path) -> tuple[Path, Path, Path, Path]:
    """Create a project root with lib/canvas/canvas.dart + sidecars from the
    real capsule. Returns (project_root, canvas_path, expected_path, slots_path)."""
    proj = tmp / "proj"
    (proj / "lib" / "canvas").mkdir(parents=True)
    canvas = proj / "lib" / "canvas" / "canvas.dart"
    # Run the capsule into the project root's lib/canvas/ directory.
    canvas.write_text("// placeholder\n", encoding="utf-8")
    with _run_real_capsule_for_corpus(tmp) as (out_dart, exp, slots):
        # The capsule writes sidecars next to out_dart. We gave it the real
        # canvas path so the sidecars land in the project tree directly.
        pass
    # The capsule wrote into tmp/canvas.dart{.expected.json,.slots.json}.
    # Move them into the project tree next to the real canvas.
    side_exp = Path(str(canvas) + ".expected.json")
    side_slots = Path(str(canvas) + ".slots.json")
    # Re-run with the real project canvas path so sidecars land in-place.
    exp_src = tmp / "canvas.dart.expected.json"
    slots_src = tmp / "canvas.dart.slots.json"
    if exp_src.exists():
        side_exp.write_bytes(exp_src.read_bytes())
    if slots_src.exists():
        side_slots.write_bytes(slots_src.read_bytes())
    return proj, canvas, side_exp, side_slots


# ===========================================================================
# 0. Precondition: capsule is verified clean.
# ===========================================================================


def test_frozen_capsule_verifies_clean() -> None:
    r = subprocess.run(
        [sys.executable, str(ICP_SCRIPTS / "verify_vendor_iff_v1.py")],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


# ===========================================================================
# 1. Adapter module surface, types, and static boundaries.
# ===========================================================================


def test_adapter_module_loads() -> None:
    module = _load_adapter("p25a2_load")
    assert hasattr(module, "ExpectedSlotsAdapterError")
    assert issubclass(module.ExpectedSlotsAdapterError, Exception)


def test_adapter_has_main() -> None:
    module = _load_adapter("p25a2_main")
    assert callable(module.main)


def test_adapter_exposes_only_approved_public_api() -> None:
    module = _load_adapter("p25a2_pubapi")
    assert hasattr(module, "main")
    assert hasattr(module, "ExpectedSlotsAdapterError")
    public_funcs = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    # main() is the only approved public function.
    assert set(public_funcs) == {"main"}, f"unexpected public funcs: {set(public_funcs)}"
    public_classes = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"ExpectedSlotsAdapterError"}, public_classes


def test_adapter_imports_only_standard_library() -> None:
    import ast
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {
        "ast", "json", "os", "re", "stat", "sys", "tempfile", "hashlib",
        "argparse", "importlib", "importlib.util", "typing", "functools",
        "itertools", "collections", "pathlib", "__future__", "io",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            assert top in allowed, f"non-stdlib from-import: {node.module}"


def test_adapter_has_no_forbidden_tokens() -> None:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    leaks = [tok for tok in FORBIDDEN_TOKENS if tok in source]
    assert leaks == [], f"adapter leaks forbidden tokens: {leaks}"


def test_adapter_does_not_subprocess_or_network() -> None:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "import socket" not in source
    assert "import urllib" not in source


def test_adapter_suppresses_bytecode_emission() -> None:
    """The adapter must set sys.dont_write_bytecode = True so loading
    SharedCore does not litter __pycache__ under shared_core/."""
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "sys.dont_write_bytecode" in source


def test_adapter_loads_projection_only_from_fixed_sibling_path() -> None:
    """The adapter source must derive the SharedCore path only from
    __file__ (no caller override)."""
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    # Must reference the shared_core sibling via __file__-relative derivation.
    assert "__file__" in source
    assert "shared_core" in source
    # Must NOT accept any override parameter for the projection path.
    assert "projection_path_override" not in source
    assert "shared_core_override" not in source


# ===========================================================================
# 2. CLI boundary: exact arguments, sanitized failures.
# ===========================================================================


def test_cli_rejects_missing_args() -> None:
    r = _run_cli()
    assert r.returncode != 0
    # No traceback leak.
    assert "Traceback" not in r.stderr
    assert "Traceback" not in r.stdout


def test_cli_rejects_unknown_arg() -> None:
    """An otherwise completely valid real-corpus invocation with one extra
    unknown flag must fail BEFORE any sidecar is touched. Both sidecars'
    bytes AND lstat identities must remain unchanged; no temp files may
    be left behind. This isolates the unknown-argument cause rather than
    passing because of an unrelated path/file error."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        st_exp_before = side_exp.lstat()
        st_slots_before = side_slots.lstat()
        r = _run_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--evil", "yes",
        )
        assert r.returncode != 0, "unknown flag accepted"
        assert "Traceback" not in r.stderr
        assert "Traceback" not in r.stdout
        # Bytes unchanged.
        assert side_exp.read_bytes() == before_exp
        assert side_slots.read_bytes() == before_slots
        # Identity (inode/mtime/mode/owner) unchanged.
        st_exp_after = side_exp.lstat()
        st_slots_after = side_slots.lstat()
        assert (st_exp_after.st_ino, st_exp_after.st_mtime_ns,
                st_exp_after.st_mode, st_exp_after.st_uid) == (
            st_exp_before.st_ino, st_exp_before.st_mtime_ns,
            st_exp_before.st_mode, st_exp_before.st_uid,
        )
        assert (st_slots_after.st_ino, st_slots_after.st_mtime_ns,
                st_slots_after.st_mode, st_slots_after.st_uid) == (
            st_slots_before.st_ino, st_slots_before.st_mtime_ns,
            st_slots_before.st_mode, st_slots_before.st_uid,
        )
        # No temp files left behind.
        sidecar_dir = side_exp.parent
        leftover = [p for p in sidecar_dir.iterdir()
                    if p.name != "canvas.dart"
                    and p.name != "canvas.dart.expected.json"
                    and p.name != "canvas.dart.slots.json"
                    and not p.name.startswith("colors")]
        assert leftover == [], f"adapter left temp files: {leftover}"


def test_cli_rejects_relative_project_root() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        canvas = proj / "c.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        r = _run_cli("--project-root", "relative/path", "--canvas", str(canvas))
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_cli_rejects_relative_canvas() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        r = _run_cli("--project-root", str(proj), "--canvas", "relative.dart")
    assert r.returncode != 0


def test_cli_rejects_non_dart_canvas() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        canvas = proj / "c.txt"
        canvas.write_text("x", encoding="utf-8")
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_cli_rejects_canvas_outside_project_root() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        outside = tmp / "elsewhere"
        outside.mkdir()
        canvas = outside / "c.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_cli_rejects_nonexistent_project_root() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        canvas = proj / "c.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        r = _run_cli("--project-root", str(tmp / "missing"), "--canvas", str(canvas))
    assert r.returncode != 0


def test_cli_rejects_nonnormalized_project_root() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        canvas = proj / "c.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        bad = str(proj) + "/."
        r = _run_cli("--project-root", bad, "--canvas", str(canvas))
    assert r.returncode != 0


# ===========================================================================
# 3. Real frozen-capsule sidecars -> adapter -> byte-identical, stable summary.
# ===========================================================================


def test_real_corpus_adapter_preserves_bytes_exact() -> None:
    """Run the real capsule for the corpus, then run the adapter CLI on the
    resulting canvas. Both sidecars must remain byte-identical (the adapter
    rebuilds via SharedCore and only persists because parity holds)."""
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        (proj / "lib" / "canvas").mkdir(parents=True)
        canvas = proj / "lib" / "canvas" / "canvas.dart"
        canvas.write_text("// placeholder\n", encoding="utf-8")
        with _run_real_capsule_for_corpus(tmp) as (out_dart, exp, slots):
            side_exp = Path(str(canvas) + ".expected.json")
            side_slots = Path(str(canvas) + ".slots.json")
            side_exp.write_bytes(exp.read_bytes())
            side_slots.write_bytes(slots.read_bytes())
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        mode_exp = stat.S_IMODE(side_exp.lstat().st_mode)
        mode_slots = stat.S_IMODE(side_slots.lstat().st_mode)
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode == 0, f"adapter failed: rc={r.returncode} stderr={r.stderr!r}"
        after_exp = side_exp.read_bytes()
        after_slots = side_slots.read_bytes()
        assert after_exp == before_exp, "adapter mutated expected bytes"
        assert after_slots == before_slots, "adapter mutated slots bytes"
        # Mode preserved.
        assert stat.S_IMODE(side_exp.lstat().st_mode) == mode_exp
        assert stat.S_IMODE(side_slots.lstat().st_mode) == mode_slots


def test_real_corpus_adapter_summary_is_stable_and_sanitized() -> None:
    """The adapter's stdout summary must be deterministic across calls and
    must not leak raw sidecar contents."""
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        (proj / "lib" / "canvas").mkdir(parents=True)
        canvas = proj / "lib" / "canvas" / "canvas.dart"
        canvas.write_text("// placeholder\n", encoding="utf-8")
        with _run_real_capsule_for_corpus(tmp):
            pass
        side_exp = Path(str(canvas) + ".expected.json")
        side_slots = Path(str(canvas) + ".slots.json")
        side_exp.write_bytes((tmp / "canvas.dart.expected.json").read_bytes())
        side_slots.write_bytes((tmp / "canvas.dart.slots.json").read_bytes())
        r1 = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        r2 = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout == r2.stdout, "adapter summary not stable"
    # The summary must be valid JSON.
    payload = json.loads(r1.stdout)
    # It must carry the projection kind + schema version it proved parity for.
    assert payload.get("kind") == KIND
    assert payload.get("schema_version") == SCHEMA_VERSION
    # No raw sidecar contents leak into stdout (check a known Unicode marker).
    assert "你好" not in r1.stdout
    assert "BoldRed" not in r1.stdout


def test_corpus_covers_required_kinds() -> None:
    """Sanity: the corpus produces a non-trivial sidecar set covering
    Unicode text, dynamic slot, styled runs, non-text node, non-default
    scale, deterministic insertion order."""
    with _canonical_tempdir() as tmp:
        with _run_real_capsule_for_corpus(tmp) as (_out, exp, slots):
            exp_doc = json.loads(exp.read_bytes())
            slots_doc = json.loads(slots.read_bytes())
            raw_exp = exp.read_bytes()
        assert exp_doc["designPixelScale"] == 2, "non-default scale required"
        impls = {n["impl"] for n in exp_doc["nodes"].values()}
        assert "text" in impls and "shape_container" in impls, impls
        assert "amount" in slots_doc, "dynamic slot required"
        assert "你好".encode("utf-8") in raw_exp, "Unicode must be present"
        assert b"BoldRed" in raw_exp, "styled runs must be present"


# ===========================================================================
# 4. Mutation / parity divergence leaves both originals unchanged.
# ===========================================================================


def test_mutation_bbox_in_expected_breaks_parity_and_writes_nothing() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        (proj / "lib" / "canvas").mkdir(parents=True)
        canvas = proj / "lib" / "canvas" / "canvas.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        with _run_real_capsule_for_corpus(tmp):
            pass
        side_exp = Path(str(canvas) + ".expected.json")
        side_slots = Path(str(canvas) + ".slots.json")
        side_exp.write_bytes((tmp / "canvas.dart.expected.json").read_bytes())
        side_slots.write_bytes((tmp / "canvas.dart.slots.json").read_bytes())
        # Mutate one bbox value in the expected sidecar.
        doc = json.loads(side_exp.read_bytes())
        # Find a text node and bump its bbox.
        for nid, node in doc["nodes"].items():
            node["bbox"] = [v + 1.0 for v in node["bbox"]]
            break
        side_exp.write_bytes(
            json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        )
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode != 0, "mutated bbox must fail closed"
        assert "Traceback" not in r.stderr
        # Both originals unchanged.
        assert side_exp.read_bytes() == before_exp
        assert side_slots.read_bytes() == before_slots


def test_mutation_slot_text_breaks_parity_and_writes_nothing() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        (proj / "lib" / "canvas").mkdir(parents=True)
        canvas = proj / "lib" / "canvas" / "canvas.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        with _run_real_capsule_for_corpus(tmp):
            pass
        side_exp = Path(str(canvas) + ".expected.json")
        side_slots = Path(str(canvas) + ".slots.json")
        side_exp.write_bytes((tmp / "canvas.dart.expected.json").read_bytes())
        side_slots.write_bytes((tmp / "canvas.dart.slots.json").read_bytes())
        slots_doc = json.loads(side_slots.read_bytes())
        for k in slots_doc:
            slots_doc[k] = "MUTATED_TEXT"
            break
        side_slots.write_bytes(
            json.dumps(slots_doc, ensure_ascii=False, indent=2).encode("utf-8")
        )
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode != 0
        assert side_exp.read_bytes() == before_exp
        assert side_slots.read_bytes() == before_slots


# ===========================================================================
# 5. Rejection: missing / malformed / oversize / wrong shape / noncanonical.
# ===========================================================================


def _setup_clean_sidecars(tmp: Path) -> tuple[Path, Path, Path, Path]:
    proj = tmp / "proj"
    (proj / "lib" / "canvas").mkdir(parents=True)
    canvas = proj / "lib" / "canvas" / "canvas.dart"
    canvas.write_text("// x\n", encoding="utf-8")
    with _run_real_capsule_for_corpus(tmp):
        pass
    side_exp = Path(str(canvas) + ".expected.json")
    side_slots = Path(str(canvas) + ".slots.json")
    side_exp.write_bytes((tmp / "canvas.dart.expected.json").read_bytes())
    side_slots.write_bytes((tmp / "canvas.dart.slots.json").read_bytes())
    return proj, canvas, side_exp, side_slots


def test_rejects_missing_expected_sidecar() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_exp.unlink()
        before_slots = side_slots.read_bytes()
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode != 0
        # Slots sidecar untouched.
        assert side_slots.read_bytes() == before_slots


def test_rejects_missing_slots_sidecar() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_slots.unlink()
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_invalid_utf8_expected() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_exp.write_bytes(b'{"artboardWidth": 1.0,\xff}\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_rejects_invalid_utf8_slots() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_slots.write_bytes(b'{"a": "\xff"}\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_duplicate_json_keys_expected() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_exp.write_bytes(b'{"artboardWidth": 1.0, "artboardWidth": 2.0}\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_duplicate_json_keys_slots() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_slots.write_bytes(b'{"dup": "a", "dup": "b"}\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_noncanonical_trailing_newline_expected() -> None:
    """The frozen capsule emits no trailing newline; the adapter must reject
    a sidecar whose bytes do not match the canonical (no-newline) form even
    if the JSON itself parses."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Append a trailing newline.
        side_exp.write_bytes(side_exp.read_bytes() + b"\n")
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_noncanonical_trailing_newline_slots() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_slots.write_bytes(side_slots.read_bytes() + b"\n")
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_expected_root_not_object() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_exp.write_bytes(b'[1, 2, 3]\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_slots_root_not_object() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        side_slots.write_bytes(b'[1, 2, 3]\n')
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_expected_nodes_not_object() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        doc = json.loads(side_exp.read_bytes())
        doc["nodes"] = [1, 2, 3]
        side_exp.write_bytes(json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"))
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_slot_id_in_slots_not_in_expected_nodes() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        slots_doc = json.loads(side_slots.read_bytes())
        slots_doc["__nonexistent__"] = "ghost"
        side_slots.write_bytes(json.dumps(slots_doc, ensure_ascii=False, indent=2).encode("utf-8"))
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_expected_missing_top_level_keys() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        doc = json.loads(side_exp.read_bytes())
        del doc["designPixelScale"]
        side_exp.write_bytes(json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"))
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


def test_rejects_oversize_expected_sidecar() -> None:
    """A sidecar > 16 MiB must be rejected without reading fully into a
    shape that could be abused."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Build a doc whose serialized form exceeds 16 MiB.
        doc = json.loads(side_exp.read_bytes())
        doc["nodes"]["__huge__"] = {
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "logicalBbox": [0.0, 0.0, 1.0, 1.0],
            "horizontalAnchor": {"mode": "left"},
            "impl": "shape_container", "text": None, "sourceText": None,
            "textRuns": [], "fontSize": None, "weight": None,
            "colorHex": None, "radius": None,
        }
        # Pad with a huge string field that the projection rejects anyway.
        doc["nodes"]["__huge__"]["colorHex"] = "#%s" % ("0" * (MAX_SIDECAR_BYTES + 64))
        side_exp.write_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


# ===========================================================================
# 6. Path validation: symlinks (leaf and ancestor), directory, FIFO.
# ===========================================================================


def test_rejects_symlinked_canvas_leaf() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        link = proj / "lib" / "canvas" / "link.dart"
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(canvas, link)
        r = _run_cli("--project-root", str(proj), "--canvas", str(link))
    assert r.returncode != 0


def test_rejects_symlinked_canvas_ancestor() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Create a symlinked ancestor directory pointing at lib/canvas.
        link_dir = proj / "linkdir"
        if link_dir.exists() or link_dir.is_symlink():
            link_dir.unlink()
        os.symlink(proj / "lib" / "canvas", link_dir)
        link_canvas = link_dir / "canvas.dart"
        r = _run_cli("--project-root", str(proj), "--canvas", str(link_canvas))
    assert r.returncode != 0


def test_rejects_canvas_is_directory() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        bad = proj / "lib" / "canvas" / "subdir.dart"
        bad.mkdir()
        r = _run_cli("--project-root", str(proj), "--canvas", str(bad))
    assert r.returncode != 0


def test_rejects_project_root_is_file() -> None:
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.write_text("x", encoding="utf-8")
        canvas = tmp / "c.dart"
        canvas.write_text("// x\n", encoding="utf-8")
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
    assert r.returncode != 0


# ===========================================================================
# 7. Atomicity / TOCTOU: source identity change between read and replace.
# ===========================================================================


def test_source_identity_change_between_read_and_replace_aborts_no_partial_write() -> None:
    """Install a narrow test seam that mutates the expected sidecar AFTER the
    adapter reads but BEFORE it replaces. The revalidation must detect the
    change, abort, leave BOTH originals at their pre-mutation bytes, and
    leave no temp files behind."""
    module = _load_adapter("p25a2_toctou")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        original_hook = getattr(module, "_TEST_PRE_REPLACE_HOOK", None)
        mutated = {"done": False}

        def _hook():
            if mutated["done"]:
                return
            mutated["done"] = True
            # Mutate expected sidecar after adapter read.
            side_exp.write_bytes(before_exp + b"\n")

        module._TEST_PRE_REPLACE_HOOK = _hook
        try:
            rc = module.main(["--project-root", str(proj), "--canvas", str(canvas)])
            assert rc != 0, "TOCTOU mutation was not rejected"
        finally:
            if original_hook is None:
                if hasattr(module, "_TEST_PRE_REPLACE_HOOK"):
                    del module._TEST_PRE_REPLACE_HOOK
            else:
                module._TEST_PRE_REPLACE_HOOK = original_hook
        # The slots sidecar (not mutated by the hook) must be unchanged.
        assert side_slots.read_bytes() == before_slots, "slots mutated by aborted adapter"
        # No temp files left behind in the sidecar directory.
        sidecar_dir = side_exp.parent
        leftover = [p for p in sidecar_dir.iterdir()
                    if p.name != "canvas.dart"
                    and p.name != "canvas.dart.expected.json"
                    and p.name != "canvas.dart.slots.json"
                    and not p.name.startswith("colors")]
        assert leftover == [], f"adapter left temp files: {leftover}"


def test_same_bytes_different_inode_aborts_no_partial_write() -> None:
    """Atomically replace one sidecar with a NEW regular file containing
    the exact same bytes AFTER the adapter reads but BEFORE it replaces.
    Bytes match, but the inode identity must differ, so the adapter must
    fail closed, must not replace the OTHER sidecar, and must clean both
    temps.

    This is the real source-identity TOCTOU: a re-read of bytes alone
    would not detect the substitution. The adapter must compare lstat
    identity tuples captured at read time against those re-lstat'd
    immediately before the first replace."""
    module = _load_adapter("p25a2_toctou_inode")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        st_slots_before = side_slots.lstat()
        original_hook = getattr(module, "_TEST_PRE_REPLACE_HOOK", None)
        swapped = {"done": False}

        def _hook():
            if swapped["done"]:
                return
            swapped["done"] = True
            # Atomically replace the expected sidecar with a brand-new
            # regular file holding the exact same bytes. The new file has
            # a different inode and (almost certainly) a different
            # mtime_ns from the original.
            tmp_path = side_exp.with_suffix(".swap.tmp")
            tmp_path.write_bytes(before_exp)
            os.replace(tmp_path, side_exp)

        module._TEST_PRE_REPLACE_HOOK = _hook
        try:
            rc = module.main(["--project-root", str(proj), "--canvas", str(canvas)])
            assert rc != 0, "same-bytes/different-inode swap was not rejected"
        finally:
            if original_hook is None:
                if hasattr(module, "_TEST_PRE_REPLACE_HOOK"):
                    del module._TEST_PRE_REPLACE_HOOK
            else:
                module._TEST_PRE_REPLACE_HOOK = original_hook
        # The adapter must NOT have replaced the slots sidecar.
        assert side_slots.read_bytes() == before_slots, (
            "slots mutated by aborted adapter"
        )
        st_slots_after = side_slots.lstat()
        assert (st_slots_after.st_ino, st_slots_after.st_mtime_ns) == (
            st_slots_before.st_ino, st_slots_before.st_mtime_ns,
        ), "slots inode/mtime changed: adapter partially replaced"
        # No temp files left behind.
        sidecar_dir = side_exp.parent
        leftover = [p for p in sidecar_dir.iterdir()
                    if p.name != "canvas.dart"
                    and p.name != "canvas.dart.expected.json"
                    and p.name != "canvas.dart.slots.json"
                    and not p.name.startswith("colors")]
        assert leftover == [], f"adapter left temp files: {leftover}"


def test_read_time_inode_swap_aborts_before_replace_no_partial_write() -> None:
    """Deterministically substitute one sidecar with a NEW regular file
    containing the exact same bytes DURING the bounded-read phase (not via
    the pre-replace hook). The read-time identity window must catch this:
    the adapter captures identity before each bounded read, reads the
    file, immediately re-lstats it, and requires exact equality of
    ``(st_dev, st_ino, st_size, st_mtime_ns, st_mode, st_uid)`` across
    that read. The post-read identities become the expected identities
    for the existing pre-replace revalidation.

    This test proves the adapter fails closed before either replace, the
    other sidecar remains unchanged in bytes AND identity, no adapter
    temp files remain, and no traceback/raw file contents/supplied path
    leak occurs.

    The test uses a dedicated post-read test seam so the swap happens
    inside the bounded-read window (between the pre-read lstat and the
    post-read lstat), not at the pre-replace hook."""
    module = _load_adapter("p25a2_read_toctou")
    # The post-read seam must exist as a module-level attribute;
    # production leaves it ``None``.
    assert hasattr(module, "_TEST_POST_READ_HOOK"), (
        "production must expose a _TEST_POST_READ_HOOK test seam"
    )
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        st_slots_before = side_slots.lstat()
        st_exp_before = side_exp.lstat()
        original_post_read_hook = getattr(module, "_TEST_POST_READ_HOOK", None)
        original_pre_replace_hook = getattr(module, "_TEST_PRE_REPLACE_HOOK", None)
        swapped = {"done": False}

        def _post_read_hook(role: str) -> None:
            """Fire after each bounded read. On the FIRST call (the
            expected sidecar read), atomically replace the expected
            sidecar with a brand-new regular file holding the exact same
            bytes. The new file has a different inode and (almost
            certainly) a different mtime_ns from the original."""
            if swapped["done"]:
                return
            if role != "expected":
                return
            swapped["done"] = True
            tmp_path = side_exp.with_suffix(".readswap.tmp")
            tmp_path.write_bytes(before_exp)
            os.replace(tmp_path, side_exp)

        module._TEST_POST_READ_HOOK = _post_read_hook
        # Ensure the pre-replace hook is NOT set, so the only way the
        # adapter can detect the swap is via the read-time identity
        # window.
        module._TEST_PRE_REPLACE_HOOK = None
        try:
            rc = module.main([
                "--project-root", str(proj),
                "--canvas", str(canvas),
            ])
            assert rc != 0, (
                "read-time same-bytes/different-inode swap was not rejected"
            )
        finally:
            if original_post_read_hook is None:
                if hasattr(module, "_TEST_POST_READ_HOOK"):
                    del module._TEST_POST_READ_HOOK
            else:
                module._TEST_POST_READ_HOOK = original_post_read_hook
            if original_pre_replace_hook is None:
                if hasattr(module, "_TEST_PRE_REPLACE_HOOK"):
                    module._TEST_PRE_REPLACE_HOOK = None
            else:
                module._TEST_PRE_REPLACE_HOOK = original_pre_replace_hook
        # The slots sidecar must be unchanged in bytes AND identity
        # (the adapter must not have reached the first replace).
        assert side_slots.read_bytes() == before_slots, (
            "slots bytes mutated by aborted adapter"
        )
        st_slots_after = side_slots.lstat()
        assert (st_slots_after.st_ino, st_slots_after.st_mtime_ns,
                st_slots_after.st_mode, st_slots_after.st_uid) == (
            st_slots_before.st_ino, st_slots_before.st_mtime_ns,
            st_slots_before.st_mode, st_slots_before.st_uid,
        ), "slots identity changed: adapter partially replaced"
        # The expected sidecar on disk is the swapped file (the hook
        # replaced it); its bytes must still equal the original bytes
        # (same content, different inode). This proves the adapter did
        # NOT overwrite it (no partial replace).
        assert side_exp.read_bytes() == before_exp, (
            "expected bytes changed by aborted adapter"
        )
        st_exp_after = side_exp.lstat()
        assert st_exp_after.st_ino != st_exp_before.st_ino, (
            "expected inode did not change: hook did not run"
        )
        # No temp files left behind.
        sidecar_dir = side_exp.parent
        leftover = [p for p in sidecar_dir.iterdir()
                    if p.name != "canvas.dart"
                    and p.name != "canvas.dart.expected.json"
                    and p.name != "canvas.dart.slots.json"
                    and not p.name.startswith("colors")]
        assert leftover == [], f"adapter left temp files: {leftover}"


def test_read_time_inode_swap_failure_sanitizes_no_leak() -> None:
    """The read-time inode swap failure must NOT leak a traceback, raw
    file contents, or the supplied project/canvas paths. Isolates the
    error-boundary cause from the identity-abort cause.

    Uses ``module.main()`` in-process (not the CLI subprocess) so the
    post-read test seam fires; captures stderr/stdout via redirect."""
    import io
    module = _load_adapter("p25a2_read_toctou_sanitize")
    assert hasattr(module, "_TEST_POST_READ_HOOK")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        original_post_read_hook = getattr(module, "_TEST_POST_READ_HOOK", None)
        original_pre_replace_hook = getattr(module, "_TEST_PRE_REPLACE_HOOK", None)
        swapped = {"done": False}

        def _post_read_hook(role: str) -> None:
            if swapped["done"]:
                return
            if role != "expected":
                return
            swapped["done"] = True
            tmp_path = side_exp.with_suffix(".san.tmp")
            tmp_path.write_bytes(before_exp)
            os.replace(tmp_path, side_exp)

        module._TEST_POST_READ_HOOK = _post_read_hook
        module._TEST_PRE_REPLACE_HOOK = None
        # Capture stderr/stdout written by main() on failure.
        err_buf = io.StringIO()
        out_buf = io.StringIO()
        saved_stderr, saved_stdout = sys.stderr, sys.stdout
        try:
            sys.stderr = err_buf
            sys.stdout = out_buf
            rc = module.main([
                "--project-root", str(proj),
                "--canvas", str(canvas),
            ])
        finally:
            sys.stderr = saved_stderr
            sys.stdout = saved_stdout
            if original_post_read_hook is None:
                if hasattr(module, "_TEST_POST_READ_HOOK"):
                    del module._TEST_POST_READ_HOOK
            else:
                module._TEST_POST_READ_HOOK = original_post_read_hook
            if original_pre_replace_hook is None:
                if hasattr(module, "_TEST_PRE_REPLACE_HOOK"):
                    module._TEST_PRE_REPLACE_HOOK = None
            else:
                module._TEST_PRE_REPLACE_HOOK = original_pre_replace_hook
        assert rc != 0, "read-time swap accepted"
        combined = err_buf.getvalue() + out_buf.getvalue()
        assert "Traceback" not in combined, "traceback leaked"
        # No raw sidecar contents (a known Unicode marker from the
        # corpus) may appear in the failure output.
        assert "你好" not in combined, "raw file content leaked"
        # The supplied paths must not appear in the failure output.
        assert str(proj) not in combined, "supplied project path leaked"
        assert str(canvas) not in combined, "supplied canvas path leaked"
        assert str(side_exp) not in combined, "derived sidecar path leaked"


def test_no_partial_replace_when_only_one_sidecar_parity_fails() -> None:
    """If only one sidecar's rebuilt bytes diverge, NEITHER file is replaced."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Corrupt the slots sidecar so SharedCore's rebuilt slots bytes will
        # not match (extra key the projection will not reproduce).
        slots_doc = json.loads(side_slots.read_bytes())
        slots_doc["__extra__ghost__"] = "x"
        side_slots.write_bytes(json.dumps(slots_doc, ensure_ascii=False, indent=2).encode("utf-8"))
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode != 0
        # Neither file changed.
        assert side_exp.read_bytes() == before_exp
        assert side_slots.read_bytes() == before_slots


def test_mode_preserved_on_successful_replace() -> None:
    """A successful adapter run must preserve each sidecar's file mode."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Tighten modes to a known unusual value.
        os.chmod(side_exp, 0o600)
        os.chmod(side_slots, 0o640)
        mode_exp = stat.S_IMODE(side_exp.lstat().st_mode)
        mode_slots = stat.S_IMODE(side_slots.lstat().st_mode)
        r = _run_cli("--project-root", str(proj), "--canvas", str(canvas))
        assert r.returncode == 0, r.stderr
        assert stat.S_IMODE(side_exp.lstat().st_mode) == mode_exp
        assert stat.S_IMODE(side_slots.lstat().st_mode) == mode_slots


def test_no_pycache_created_under_shared_core() -> None:
    """Running the adapter via CLI must not create __pycache__ under
    shared_core/ even if the runner forgot PYTHONDONTWRITEBYTECODE."""
    cache_dir = SHARED_CORE_DIR / "__pycache__"
    pre = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        # Explicitly do NOT set PYTHONDONTWRITEBYTECODE.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        r = subprocess.run(
            [sys.executable, str(ADAPTER_PATH),
             "--project-root", str(proj), "--canvas", str(canvas)],
            capture_output=True, text=True, env=env,
        )
        assert r.returncode == 0, r.stderr
    post = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    new = {p for p in (post - pre) if "expected_slots_projection_v1" in p.name}
    assert not new, f"adapter created __pycache__: {sorted(p.name for p in new)}"


# ===========================================================================
# 8. Operations-module integration: the fourth visible-codegen step.
# ===========================================================================


def test_operations_visible_codegen_has_four_ordered_steps_with_adapter_second() -> None:
    module = _load_operations("p25a2_ops_steps")
    # The visible_codegen step spec must now carry exactly four steps with
    # the adapter in position 1 (immediately after generate_canvas).
    spec = module._VISIBLE_STEPS_SPEC
    assert [s["step_id"] for s in spec] == [
        "generate_canvas", "adapt_expected_slots",
        "make_implementation_map", "make_status_bar_policy",
    ]
    # The adapter step carries platform origin.
    adapt = next(s for s in spec if s["step_id"] == "adapt_expected_slots")
    assert adapt["primitive"] == "flutter_expected_slots_adapter_v1.py"
    assert adapt.get("script_origin") == "platform"
    # Every other visible step defaults to capsule origin.
    for s in spec:
        if s["step_id"] != "adapt_expected_slots":
            assert s.get("script_origin", "capsule") == "capsule", s["step_id"]


def test_operations_has_fixed_platform_scripts_dir() -> None:
    module = _load_operations("p25a2_ops_psdir")
    assert hasattr(module, "PLATFORM_SCRIPTS_DIR")
    expected = module.ICP_ROOT / "scripts" / "platforms"
    assert module.PLATFORM_SCRIPTS_DIR == expected


def test_operations_platform_script_resolves_and_hashes() -> None:
    """The platform script must exist as a non-symlink regular file and its
    SHA-256 must be reproducible. The collision check against the capsule
    manifest map is exercised explicitly (the production helper requires
    the strict loaded manifest map and rejects any basename collision)."""
    module = _load_operations("p25a2_ops_sha")
    p = module.PLATFORM_SCRIPTS_DIR / "flutter_expected_slots_adapter_v1.py"
    assert p.is_file()
    assert not p.is_symlink()
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = module._manifest_sha_map(manifest)
    # The platform basename must NOT collide with any capsule primitive.
    capsule_names = set(sha_map.keys())
    assert "flutter_expected_slots_adapter_v1.py" not in capsule_names
    # The production helper requires the manifest map and recomputes the
    # SHA from the file. Do NOT make sha_map optional in production.
    sha = module._lookup_platform_script_sha(
        "flutter_expected_slots_adapter_v1.py", sha_map
    )
    assert sha == _sha256_file(p)
    # A second call is stable (recompute is deterministic).
    assert module._lookup_platform_script_sha(
        "flutter_expected_slots_adapter_v1.py", sha_map
    ) == sha
    # A collision attempt (a capsule basename) must be rejected.
    capsule_basename = next(iter(capsule_names))
    try:
        module._lookup_platform_script_sha(capsule_basename, sha_map)
    except module.OperationPlanError:
        pass
    else:
        raise AssertionError("platform collision with capsule basename accepted")


def test_operations_build_visible_codegen_emits_four_steps_with_platform_path() -> None:
    """End-to-end build of visible_codegen emits a 4-step plan whose
    adapt_expected_slots step points at the platform script path."""
    module = _load_operations("p25a2_ops_build4")
    # Patch capsule verify + manifest for an isolated build.
    saved_vc = module._verify_capsule
    saved_lm = module._load_manifest
    module._verify_capsule = lambda: {
        "kind": "icp.iff-v1-vendor-capsule-verify", "ok": True,
        "capsule_root": "vendor/iff_v1",
    }
    real_manifest = module._load_manifest()
    module._load_manifest = lambda: real_manifest
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            (proj / "lib" / "canvas").mkdir(parents=True)
            (proj / "lib" / "status").mkdir(parents=True)
            for n in ("render_plan", "scene", "classification", "component_manifest"):
                _write_json(run / f"{n}.json", {"a": 1})
            request = {
                "project_root": str(proj), "run_root": str(run),
                "package_name": "my_app", "feature_id": "fancy_widget",
                "render_plan": "render_plan.json", "scene": "scene.json",
                "classification": "classification.json",
                "component_manifest": "component_manifest.json",
                "canvas_out": "lib/canvas/canvas.dart",
                "colors_out": "lib/canvas/colors.dart",
                "colors_import_path": "lib/canvas/colors.dart",
                "implementation_map_out": "implementation_map.json",
                "status_bar_out": "lib/status/status_bar.dart",
                "canvas_class_name": "CanvasWidget",
                "status_bar_class_name": "StatusBarWidget",
            }
            plan = module.build("flutter.visible_codegen.v1", request)
    finally:
        module._verify_capsule = saved_vc
        module._load_manifest = saved_lm
    assert len(plan["steps"]) == 4
    adapt = plan["steps"][1]
    assert adapt["step_id"] == "adapt_expected_slots"
    assert adapt["primitive"] == "flutter_expected_slots_adapter_v1.py"
    # argv[1] must point at the platform scripts dir, not the capsule dir.
    assert adapt["argv"][1] == str(
        module.PLATFORM_SCRIPTS_DIR / "flutter_expected_slots_adapter_v1.py"
    )
    # The SHA must equal the current file's SHA.
    assert adapt["primitive_sha256"] == _sha256_file(
        module.PLATFORM_SCRIPTS_DIR / "flutter_expected_slots_adapter_v1.py"
    )
    # The adapt step's argv structure: interpreter, platform script,
    # --project-root <abs>, --canvas <abs .dart>, --run-root <abs>,
    # --feature-id <id> (P2.5b extended the adapter to additionally
    # publish the canonical projection artifact).
    flags = adapt["argv"][2:]
    assert flags == [
        "--project-root", str(proj),
        "--canvas", str(proj / "lib" / "canvas" / "canvas.dart"),
        "--run-root", str(run),
        "--feature-id", "fancy_widget",
    ], flags


def test_operations_verify_plan_rejects_tampered_platform_script_path() -> None:
    """verify_plan must reject a plan whose adapt step argv[1] is redirected
    away from the fixed platform script path."""
    module = _load_operations("p25a2_ops_tamper_path")
    saved_vc = module._verify_capsule
    saved_lm = module._load_manifest
    module._verify_capsule = lambda: {
        "kind": "icp.iff-v1-vendor-capsule-verify", "ok": True,
        "capsule_root": "vendor/iff_v1",
    }
    real_manifest = module._load_manifest()
    module._load_manifest = lambda: real_manifest
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            (proj / "lib" / "canvas").mkdir(parents=True)
            (proj / "lib" / "status").mkdir(parents=True)
            for n in ("render_plan", "scene", "classification", "component_manifest"):
                _write_json(run / f"{n}.json", {"a": 1})
            request = {
                "project_root": str(proj), "run_root": str(run),
                "package_name": "my_app", "feature_id": "fancy_widget",
                "render_plan": "render_plan.json", "scene": "scene.json",
                "classification": "classification.json",
                "component_manifest": "component_manifest.json",
                "canvas_out": "lib/canvas/canvas.dart",
                "colors_out": "lib/canvas/colors.dart",
                "colors_import_path": "lib/canvas/colors.dart",
                "implementation_map_out": "implementation_map.json",
                "status_bar_out": "lib/status/status_bar.dart",
                "canvas_class_name": "CanvasWidget",
                "status_bar_class_name": "StatusBarWidget",
            }
            plan = module.build("flutter.visible_codegen.v1", request)
            # Tamper the adapt step's argv[1] to a fake path.
            plan["steps"][1]["argv"][1] = "/tmp/evil_adapter.py"
            try:
                module.verify_plan(plan)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("tampered platform script path accepted")
    finally:
        module._verify_capsule = saved_vc
        module._load_manifest = saved_lm


# ===========================================================================
# 9. Selftest runner.
# ===========================================================================


def main() -> int:
    tests = [name for name in globals() if name.startswith("test_")]
    failures = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            import traceback
            tb = traceback.format_exc()
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
            print(tb)
    if failures:
        print(f"FAILED {failures}/{len(tests)}")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
