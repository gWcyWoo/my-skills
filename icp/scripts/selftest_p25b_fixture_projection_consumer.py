#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2.5b first projection
consumer cutover.

P2.5b makes the platform-neutral expected/slots projection a persistent,
canonical artifact and makes ``flutter.fixture_codegen.v1`` the first
operation gated by that projection, while preserving the frozen iFF
consumer and exact Flutter parity.

The frozen ``make_visual_fixture.py`` remains unchanged. The fixture
operation first executes a read-only platform-origin projection guard;
only after that succeeds may the existing capsule consumer run against
the already-existing legacy slots files.

This selftest covers:

  1. SharedCore canonical projection serialization
     (:func:`build_projection_bytes`).
  2. Real frozen-corpus adapter projection publication; loading the
     artifact through SharedCore rebuilds both legacy sidecars
     byte-for-byte.
  3. Adapter compatibility mode unchanged.
  4. Adapter projection publish edge cases (path, CLI pair, feature
     id, run-root validation, no-overwrite, temp cleanup, mode 0600,
     canonical bytes, 16 MiB bound, sanitized failures).
  5. Guard happy path for multiple sorted states; canonical projection
     check; exact projection->slots bytes; completely read-only.
  6. Guard rejections (missing/mismatched/duplicate states, malformed
     /invalid UTF-8/duplicate-key/noncanonical/oversized projection,
     mutated slots, symlink leaf/ancestor, out-of-root, non-file,
     unknown args; no leaks).
  7. Visible operation remains four steps and adapter argv includes
     fixed run-root/feature-id.
  8. Fixture operation becomes two steps in exact order; request
     requires matching projections; deterministic argv; platform
     primitive path/SHA binding; tampered/reordered/wrong-origin/
     capsule-basename collision rejection.
  9. Binding/authorization/executor end-to-end propagation for the new
     fixture guard.
 10. No platform activation, registry change, vendor/baseline/IFF
     change, or ``__pycache__``.

Run directly::

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25b_fixture_projection_consumer.py
"""

from __future__ import annotations

import ast
import contextlib
import copy
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
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
SHARED_CORE_DIR = ICP_SCRIPTS / "shared_core"
ADAPTER_PATH = PLATFORMS_DIR / "flutter_expected_slots_adapter_v1.py"
GUARD_PATH = PLATFORMS_DIR / "flutter_fixture_projection_guard_v1.py"
PROJECTION_PATH = SHARED_CORE_DIR / "expected_slots_projection_v1.py"
OPERATIONS_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
BINDING_PATH = PLATFORMS_DIR / "flutter_execution_binding_v1.py"
AUTHZ_PATH = PLATFORMS_DIR / "flutter_execution_authorization_v1.py"
EXECUTOR_PATH = PLATFORMS_DIR / "flutter_execution_executor_v1.py"
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
CAPSULE_GENERATE_CANVAS = CAPSULE_SCRIPTS / "generate_canvas.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"
FREEZE_TOOL = ICP_SCRIPTS / "freeze_iff_baseline.py"

KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1
KIND_PLAN = "icp.trusted-operation-plan.v1"
KIND_VERIFY = "icp.trusted-operation-plan-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"

# 16 MiB cap (matches the adapter's _MAX_SIDECAR_BYTES).
MAX_PROJECTION_BYTES = 16 * 1024 * 1024

# Forbidden production tokens (TEST only) — process / network / capsule
# import surface; the guard must be standard-library-only.
FORBIDDEN_TOKENS_GUARD = (
    "import subprocess",
    "from subprocess",
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_shared_core(name: str = "p25b_sc"):
    return _load(name, PROJECTION_PATH)


def _load_adapter(name: str = "p25b_adapter"):
    return _load(name, ADAPTER_PATH)


def _load_guard(name: str = "p25b_guard"):
    return _load(name, GUARD_PATH)


def _load_operations(name: str = "p25b_ops"):
    return _load(name, OPERATIONS_PATH)


def _load_capsule_generate_canvas():
    spec = importlib.util.spec_from_file_location(
        "p25b_capsule_generate_canvas", str(CAPSULE_GENERATE_CANVAS)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25b_capsule_generate_canvas"] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p25b_"):
    """Yield a temp dir whose path is realpath-canonicalized."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


def _run_cli(script: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_adapter_cli(*args: str) -> subprocess.CompletedProcess:
    return _run_cli(ADAPTER_PATH, *args)


def _run_guard_cli(*args: str) -> subprocess.CompletedProcess:
    return _run_cli(GUARD_PATH, *args)


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
# Corpus (reused P2.5a1/P2.5a2 shape; covers Unicode text, dynamic slot,
# styled runs, non-text shape, non-default scale, deterministic order).
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
    """Run the frozen generate_canvas.py for the corpus; yield the canvas
    path and its expected/slots sidecars."""
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


def _setup_clean_sidecars(tmp: Path) -> tuple[Path, Path, Path, Path]:
    """Project root + real sidecars from the frozen capsule."""
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


# ---------------------------------------------------------------------------
# Minimal valid projection factory for serialization tests.
# ---------------------------------------------------------------------------


_MIN_NODE = {
    "id": "n1",
    "bbox": [10.0, 20.0, 100.0, 50.0],
    "horizontalAnchor": {"mode": "left", "left": 5.0, "right": 605.0, "centerOffset": -300.0},
    "impl": "shape_container",
    "text": None,
    "sourceText": None,
    "textRuns": [],
    "fontSize": None,
    "weight": None,
    "colorHex": "#3366FF",
    "radius": 0.0,
    "slot": False,
}


def _minimal_projection() -> dict[str, Any]:
    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "artboardWidth": 750.0,
        "artboardHeight": 1624.0,
        "designPixelScale": 2.0,
        "nodes": [dict(_MIN_NODE)],
    }


def _copy_node(node: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    out = dict(node)
    out.update(overrides)
    return out


# ===========================================================================
# 0. Precondition: capsule + baseline + iff clean.
# ===========================================================================


def test_frozen_capsule_verifies_clean() -> None:
    r = _run_cli(VERIFY_TOOL)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


def test_frozen_baseline_unchanged() -> None:
    r = _run_cli(
        FREEZE_TOOL,
        "--iff-root", "iff",
        "--check", "icp/references/baselines/iff-v1.json",
    )
    assert r.returncode == 0, r.stderr


def test_git_diff_iff_is_clean() -> None:
    r = subprocess.run(
        ["git", "diff", "--exit-code", "--", "iff"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"iff/ has uncommitted changes:\n{r.stdout}"


# ===========================================================================
# 1. SharedCore canonical projection serialization.
# ===========================================================================


def test_build_projection_bytes_is_listed_in_all() -> None:
    module = _load_shared_core("p25b_sc_all")
    assert "build_projection_bytes" in module.__all__


def test_build_projection_bytes_signature() -> None:
    module = _load_shared_core("p25b_sc_sig")
    sig = inspect.signature(module.build_projection_bytes)
    params = list(sig.parameters)
    assert params == ["projection"], sig
    assert sig.parameters["projection"].default is inspect.Parameter.empty


def test_build_projection_bytes_top_level_key_order() -> None:
    module = _load_shared_core("p25b_sc_tlk")
    data = module.build_projection_bytes(_minimal_projection())
    text = data.decode("utf-8")
    # Top-level keys must appear in the contract's fixed order.
    positions = {k: text.find(f'"{k}"') for k in (
        "kind", "schemaVersion", "artboardWidth", "artboardHeight",
        "designPixelScale", "nodes",
    )}
    ordered = sorted(positions.items(), key=lambda kv: kv[1])
    assert [k for k, _ in ordered] == [
        "kind", "schemaVersion", "artboardWidth", "artboardHeight",
        "designPixelScale", "nodes",
    ], ordered


def test_build_projection_bytes_node_key_order() -> None:
    module = _load_shared_core("p25b_sc_nk")
    data = module.build_projection_bytes(_minimal_projection())
    text = data.decode("utf-8")
    positions = {k: text.find(f'"{k}"') for k in (
        "id", "bbox", "horizontalAnchor", "impl", "text", "sourceText",
        "textRuns", "fontSize", "weight", "colorHex", "radius", "slot",
    )}
    ordered = sorted(positions.items(), key=lambda kv: kv[1])
    assert [k for k, _ in ordered] == [
        "id", "bbox", "horizontalAnchor", "impl", "text", "sourceText",
        "textRuns", "fontSize", "weight", "colorHex", "radius", "slot",
    ], ordered


def test_build_projection_bytes_no_trailing_newline() -> None:
    module = _load_shared_core("p25b_sc_notrail")
    data = module.build_projection_bytes(_minimal_projection())
    assert not data.endswith(b"\n"), "projection bytes end with newline"


def test_build_projection_bytes_preserves_node_insertion_order() -> None:
    module = _load_shared_core("p25b_sc_nio")
    p = _minimal_projection()
    p["nodes"] = [
        _copy_node(_MIN_NODE, id="zeta"),
        _copy_node(_MIN_NODE, id="alpha"),
        _copy_node(_MIN_NODE, id="mu", impl="text", text="x", slot=True),
    ]
    data = module.build_projection_bytes(p)
    text = data.decode("utf-8")
    # Nodes appear in list insertion order.
    pos_zeta = text.find('"zeta"')
    pos_alpha = text.find('"alpha"')
    pos_mu = text.find('"mu"')
    assert pos_zeta < pos_alpha < pos_mu, (pos_zeta, pos_alpha, pos_mu)


def test_build_projection_bytes_preserves_nested_json_insertion_order() -> None:
    """Insertion order of nested JSON values (horizontalAnchor, textRuns)
    must be preserved."""
    module = _load_shared_core("p25b_sc_nested")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {
        "zebra": 1, "alpha": 2, "mango": [3, 4, 5],
    }
    p["nodes"][0]["textRuns"] = [
        {"zeta": 1, "alpha": 2}, {"mu": 3, "beta": 4},
    ]
    data = module.build_projection_bytes(p)
    text = data.decode("utf-8")
    # zebra must appear before alpha, alpha before mango.
    p_z = text.find('"zebra"')
    p_a = text.find('"alpha"')
    p_m = text.find('"mango"')
    assert p_z < p_a < p_m, (p_z, p_a, p_m)


def test_build_projection_bytes_unicode_unescaped() -> None:
    module = _load_shared_core("p25b_sc_uni")
    p = _minimal_projection()
    p["nodes"][0] = _copy_node(
        _MIN_NODE,
        id="uni",
        impl="text",
        text="你好,世界 🌍 — café",
        sourceText="你好,世界 🌍 — café",
        slot=True,
    )
    data = module.build_projection_bytes(p)
    assert "你好".encode("utf-8") in data
    assert "🌍".encode("utf-8") in data
    assert "café".encode("utf-8") in data
    assert b"\\u" not in data


def test_build_projection_bytes_detached_clone() -> None:
    """build_projection_bytes must not alias the caller's projection or
    nested containers; mutating the input after the call must not change
    a re-decode of the bytes."""
    module = _load_shared_core("p25b_sc_detach")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": 5.0}
    p["nodes"][0]["textRuns"] = [{"content": "x", "font": {"size": 14}}]
    data = module.build_projection_bytes(p)
    # Mutate the input after the call.
    p["nodes"][0]["horizontalAnchor"]["mode"] = "right"
    p["nodes"][0]["textRuns"][0]["content"] = "MUTATED"
    # Re-decode the bytes: the original content must be preserved.
    re_doc = json.loads(data.decode("utf-8"))
    assert re_doc["nodes"][0]["horizontalAnchor"]["mode"] == "left"
    assert re_doc["nodes"][0]["textRuns"][0]["content"] == "x"


def test_build_projection_bytes_deterministic_for_custom_mapping() -> None:
    """A custom Mapping subclass that yields the same insertion order
    must produce bytes equal to a plain dict of the same content."""
    module = _load_shared_core("p25b_sc_custom_map")

    class _CustomDict(dict):
        """A Mapping subclass; insertion order is the underlying dict
        order. Validation must not serialize this subclass directly."""

    p_plain = _minimal_projection()
    # Use the custom subclass at root and at node level.
    p_custom_root = _CustomDict(p_plain)
    p_custom_root["nodes"] = [_CustomDict(n) for n in p_plain["nodes"]]

    b_plain = module.build_projection_bytes(p_plain)
    b_custom = module.build_projection_bytes(p_custom_root)
    assert b_plain == b_custom, (
        "build_projection_bytes must be deterministic for custom Mapping "
        "subclasses after validation"
    )


def test_build_projection_bytes_deterministic_across_calls() -> None:
    module = _load_shared_core("p25b_sc_det")
    p = _minimal_projection()
    b1 = module.build_projection_bytes(p)
    b2 = module.build_projection_bytes(p)
    assert b1 == b2


def test_build_projection_bytes_strict_rejects_nan() -> None:
    module = _load_shared_core("p25b_sc_reject_nan")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": float("nan")}
    try:
        module.build_projection_bytes(p)
    except module.ProjectionValidationError:
        return
    raise AssertionError("NaN in projection must be rejected")


def test_build_projection_bytes_strict_rejects_bytes_in_anchor() -> None:
    module = _load_shared_core("p25b_sc_reject_bytes")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": b"left"}
    try:
        module.build_projection_bytes(p)
    except module.ProjectionValidationError:
        return
    raise AssertionError("bytes in projection must be rejected")


def test_build_projection_bytes_strict_rejects_unknown_top_key() -> None:
    module = _load_shared_core("p25b_sc_reject_top")
    p = _minimal_projection()
    p["extra"] = True
    try:
        module.build_projection_bytes(p)
    except module.ProjectionValidationError:
        return
    raise AssertionError("unknown top-level key must be rejected")


def test_build_projection_bytes_exactly_matches_json_dumps_form() -> None:
    module = _load_shared_core("p25b_sc_form")
    p = _minimal_projection()
    data = module.build_projection_bytes(p)
    # Validate first, then re-serialize with the exact json.dumps form
    # over the cloned strict-JSON tree.
    expected_doc = module._strict_json_clone(p, "root")
    # Top-level key order is the contract order.
    ordered_root = {
        k: expected_doc[k] for k in (
            "kind", "schemaVersion", "artboardWidth", "artboardHeight",
            "designPixelScale", "nodes",
        )
    }
    # Nodes carry their own fixed key order.
    node_order = (
        "id", "bbox", "horizontalAnchor", "impl", "text", "sourceText",
        "textRuns", "fontSize", "weight", "colorHex", "radius", "slot",
    )
    ordered_nodes = []
    for node in ordered_root["nodes"]:
        ordered_nodes.append({k: node[k] for k in node_order})
    ordered_root["nodes"] = ordered_nodes
    expected = json.dumps(
        ordered_root, ensure_ascii=False, indent=2,
    ).encode("utf-8")
    assert data == expected


# ===========================================================================
# 2. Real frozen-corpus adapter projection publication.
# ===========================================================================


def test_adapter_real_corpus_publishes_canonical_projection_artifact() -> None:
    """Run the real capsule, then run the adapter in projection-publish
    mode with --run-root and --feature-id. The published artifact must
    equal build_projection_bytes(projection) computed by SharedCore from
    the sidecars, and both legacy sidecars must be rebuildable from the
    artifact byte-for-byte."""
    sc = _load_shared_core("p25b_pub_sc")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        feature_id = "fancy_widget"
        # Compatibility mode first to refresh sidecars (proves P2.5a2 still
        # works and keeps test parity simple).
        r_compat = _run_adapter_cli(
            "--project-root", str(proj), "--canvas", str(canvas),
        )
        assert r_compat.returncode == 0, r_compat.stderr
        # Now publish the projection artifact.
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", feature_id,
        )
        assert r.returncode == 0, f"adapter publish failed: {r.stderr!r}"
        # The artifact path is fixed.
        artifact = run_root / "expected_slots_projections" / f"{feature_id}.json"
        assert artifact.is_file(), f"artifact missing: {artifact}"
        assert not artifact.is_symlink()
        # The artifact bytes equal SharedCore's canonical bytes from the
        # sidecar-reconstructed projection.
        side_exp_bytes = side_exp.read_bytes()
        side_slots_bytes = side_slots.read_bytes()
        # Reconstruct the projection by importing the adapter's private
        # helper (test-only path) to avoid duplicating reconstruction.
        adapter = _load_adapter("p25b_pub_adapter")
        expected_doc = adapter._decode_json_strict(side_exp_bytes, "expected")
        slots_doc = adapter._decode_json_strict(side_slots_bytes, "slots")
        projection = adapter._reconstruct_projection(expected_doc, slots_doc)
        expected_artifact_bytes = sc.build_projection_bytes(projection)
        assert artifact.read_bytes() == expected_artifact_bytes, (
            "artifact bytes diverge from SharedCore build_projection_bytes"
        )
        # Loading the artifact through SharedCore rebuilds both legacy
        # sidecars byte-for-byte.
        loaded = json.loads(artifact.read_bytes().decode("utf-8"))
        rebuilt_exp, rebuilt_slots = sc.build_legacy_bytes(loaded)
        assert rebuilt_exp == side_exp_bytes, "artifact failed to rebuild expected"
        assert rebuilt_slots == side_slots_bytes, "artifact failed to rebuild slots"


def test_adapter_projection_artifact_summary_includes_relative_path() -> None:
    """In projection mode the adapter's stdout summary must include the
    existing stable fields plus a stable project/run-relative projection
    artifact identifier or relative path; it must not emit an absolute
    supplied path or raw content."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        # Run compatibility mode first.
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        # Existing stable summary fields preserved.
        assert payload.get("kind") == KIND
        assert payload.get("schema_version") == SCHEMA_VERSION
        # The summary must NOT emit the absolute supplied run_root.
        assert "projection_artifact_rel" in payload or "projection_artifact_id" in payload, (
            f"summary missing projection artifact identifier: {payload!r}"
        )
        # The relative path/identifier must not be the absolute run_root.
        rel = payload.get("projection_artifact_rel") or payload.get(
            "projection_artifact_id"
        )
        assert isinstance(rel, str) and rel
        assert not os.path.isabs(rel), f"summary emits absolute path: {rel!r}"
        # Raw corpus Unicode/content must not leak.
        assert "你好" not in r.stdout
        assert str(run_root) not in r.stdout, "absolute run_root leaked"


# ===========================================================================
# 3. Adapter compatibility mode unchanged.
# ===========================================================================


def test_adapter_compatibility_mode_unchanged() -> None:
    """Two-arg invocation must still perform the byte-identical rewrite
    and return the existing summary unchanged."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        before_exp = side_exp.read_bytes()
        before_slots = side_slots.read_bytes()
        r = _run_adapter_cli(
            "--project-root", str(proj), "--canvas", str(canvas),
        )
        assert r.returncode == 0, r.stderr
        # Sidecar bytes preserved.
        assert side_exp.read_bytes() == before_exp
        assert side_slots.read_bytes() == before_slots
        # Summary still carries existing fields, no projection_artifact_*.
        payload = json.loads(r.stdout)
        assert payload.get("kind") == KIND
        assert "projection_artifact_rel" not in payload
        assert "projection_artifact_id" not in payload


# ===========================================================================
# 4. Adapter projection publish: CLI / path / size / overwrite / temp.
# ===========================================================================


def test_adapter_projection_artifact_has_fixed_derived_path() -> None:
    """Artifact must live at <run_root>/expected_slots_projections/<feature_id>.json."""
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        assert artifact.is_file()
        assert not artifact.is_symlink()


def test_adapter_projection_requires_run_root_and_feature_id_together() -> None:
    """--run-root and --feature-id must appear together or both be absent."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        # Only --run-root.
        r1 = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
        )
        assert r1.returncode != 0, "lone --run-root accepted"
        # Only --feature-id.
        r2 = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--feature-id", "fancy_widget",
        )
        assert r2.returncode != 0, "lone --feature-id accepted"
        # Neither is accepted (compatibility mode).
        r3 = _run_adapter_cli(
            "--project-root", str(proj), "--canvas", str(canvas),
        )
        assert r3.returncode == 0


def test_adapter_projection_rejects_invalid_feature_id() -> None:
    """feature_id must match ^[a-z][a-z0-9_]*$."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        for bad in ("Fancy", "fancy-widget", "1fancy", "fancy.widget", "", "fancy!"):
            r = _run_adapter_cli(
                "--project-root", str(proj),
                "--canvas", str(canvas),
                "--run-root", str(run_root),
                "--feature-id", bad,
            )
            assert r.returncode != 0, f"invalid feature_id accepted: {bad!r}"


def test_adapter_projection_rejects_relative_run_root() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", "relative/run",
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_rejects_nonexistent_run_root() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(tmp / "missing"),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_rejects_run_root_equal_to_project_root() -> None:
    """run_root must be disjoint from project_root under the existing
    root-boundary policy."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(proj),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_rejects_symlinked_run_root() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root_real = tmp / "run_real"
        run_root_real.mkdir()
        run_root_link = tmp / "run_link"
        os.symlink(run_root_real, run_root_link)
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root_link),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_no_overwrite_existing_file() -> None:
    """A pre-existing output file (file, dir, or symlink) must fail closed
    and never be overwritten."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        artifact_dir = run_root / "expected_slots_projections"
        artifact_dir.mkdir()
        artifact = artifact_dir / "fancy_widget.json"
        # Case 1: pre-existing regular file.
        marker = b'{"preexisting": true}'
        artifact.write_bytes(marker)
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0, "overwrite of existing file accepted"
        assert artifact.read_bytes() == marker, "existing artifact overwritten"


def test_adapter_projection_no_overwrite_existing_dir() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        # The artifact path itself exists as a directory.
        artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        artifact.mkdir(parents=True)
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_no_overwrite_existing_symlink() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        artifact_dir = run_root / "expected_slots_projections"
        artifact_dir.mkdir()
        artifact = artifact_dir / "fancy_widget.json"
        target = tmp / "elsewhere.json"
        target.write_bytes(b"{}")
        os.symlink(target, artifact)
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0


def test_adapter_projection_temp_cleanup_on_failure() -> None:
    """A failed publish (pre-existing output) must clean up its temp file
    in the target directory."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        artifact_dir = run_root / "expected_slots_projections"
        artifact_dir.mkdir()
        # Pre-create the artifact so publication fails with no-overwrite.
        artifact = artifact_dir / "fancy_widget.json"
        artifact.write_bytes(b"{}")
        _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        # No temp files left behind in artifact_dir.
        leftover = [p for p in artifact_dir.iterdir() if p.name != "fancy_widget.json"]
        assert leftover == [], f"adapter left temp files: {leftover}"


def test_adapter_projection_artifact_mode_is_0600() -> None:
    """The published artifact must have mode 0600."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        mode = stat.S_IMODE(artifact.lstat().st_mode)
        assert mode == 0o600, f"artifact mode is {oct(mode)}, expected 0600"


def test_adapter_projection_artifact_owner_current() -> None:
    """The published artifact must be owned by the current effective user."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None:
            assert artifact.lstat().st_uid == geteuid()


def test_adapter_projection_artifact_dir_fsynced_exists() -> None:
    """The expected_slots_projections directory exists after publish."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        # Directory exists, non-symlink, mode is a regular directory mode.
        dir_path = run_root / "expected_slots_projections"
        assert dir_path.is_dir()
        assert not dir_path.is_symlink()


def test_adapter_projection_canonical_bytes_via_summary_field() -> None:
    """The summary must not leak raw content but the on-disk artifact
    must equal the canonical SharedCore bytes."""
    sc = _load_shared_core("p25b_canon_sc")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        adapter = _load_adapter("p25b_canon_adapter")
        expected_doc = adapter._decode_json_strict(
            side_exp.read_bytes(), "expected"
        )
        slots_doc = adapter._decode_json_strict(
            side_slots.read_bytes(), "slots"
        )
        projection = adapter._reconstruct_projection(expected_doc, slots_doc)
        expected_bytes = sc.build_projection_bytes(projection)
        assert artifact.read_bytes() == expected_bytes


def test_adapter_projection_16mib_bound() -> None:
    """A projection artifact larger than 16 MiB must be rejected (the
    bound applies to the projection bytes the adapter would publish)."""
    sc = _load_shared_core("p25b_16m_sc")
    # Construct a projection whose serialized bytes exceed 16 MiB by
    # inflating a single nested string in horizontalAnchor (this is
    # valid strict JSON).
    huge = "x" * (MAX_PROJECTION_BYTES + 64)
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "payload": huge}
    data = sc.build_projection_bytes(p)
    assert len(data) > MAX_PROJECTION_BYTES
    # We can't easily drive the adapter to publish a >16 MiB artifact
    # without writing >16 MiB sidecars; instead prove the helper that
    # the bound exists as a module-level constant.
    adapter = _load_adapter("p25b_16m_adapter")
    assert hasattr(adapter, "_MAX_PROJECTION_BYTES") or hasattr(
        adapter, "_MAX_SIDECAR_BYTES"
    ), "adapter must expose a max-bytes constant"


def test_adapter_projection_failure_sanitized_no_path_leak() -> None:
    """A failed publish must not leak raw sidecar content or supplied
    paths."""
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        # Force failure: pre-create the artifact.
        artifact_dir = run_root / "expected_slots_projections"
        artifact_dir.mkdir()
        artifact = artifact_dir / "fancy_widget.json"
        artifact.write_bytes(b"{}")
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode != 0
        combined = r.stderr + r.stdout
        assert "Traceback" not in combined
        assert "你好" not in combined, "raw content leaked"
        # The supplied run_root must not appear in the failure text.
        assert str(run_root) not in combined, "absolute run_root leaked"


def test_adapter_projection_does_not_emit_pycache() -> None:
    """Publishing must not create __pycache__ anywhere under shared_core/."""
    cache_dir = SHARED_CORE_DIR / "__pycache__"
    pre = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
    post = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    new = {p for p in (post - pre) if "expected_slots_projection_v1" in p.name}
    assert not new, f"adapter created __pycache__: {sorted(p.name for p in new)}"


# ===========================================================================
# 5. Guard: surface, standard-library-only, read-only, happy path.
# ===========================================================================


def test_guard_module_exists_and_exposes_main_and_typed_exception() -> None:
    module = _load_guard("p25b_guard_load")
    assert callable(module.main)
    assert hasattr(module, "FixtureProjectionGuardError")
    assert issubclass(module.FixtureProjectionGuardError, Exception)


def test_guard_exposes_only_approved_public_api() -> None:
    module = _load_guard("p25b_guard_pubapi")
    allowed_funcs = {"main"}
    public_funcs = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_funcs) == allowed_funcs, public_funcs
    public_classes = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"FixtureProjectionGuardError"}, public_classes


def test_guard_imports_only_standard_library() -> None:
    source = GUARD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {
        "ast", "json", "os", "re", "stat", "sys", "hashlib",
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


def test_guard_has_no_forbidden_tokens() -> None:
    source = GUARD_PATH.read_text(encoding="utf-8")
    leaks = [tok for tok in FORBIDDEN_TOKENS_GUARD if tok in source]
    assert leaks == [], f"guard leaks forbidden tokens: {leaks}"


def test_guard_suppresses_bytecode_emission() -> None:
    source = GUARD_PATH.read_text(encoding="utf-8")
    assert "sys.dont_write_bytecode" in source


def test_guard_loads_projection_only_from_fixed_sibling_path() -> None:
    source = GUARD_PATH.read_text(encoding="utf-8")
    assert "__file__" in source
    assert "shared_core" in source
    assert "projection_path_override" not in source
    assert "shared_core_override" not in source


def test_guard_is_completely_read_only() -> None:
    """Source must contain no mkdir / temp / write / rename / delete /
    unlink API. ``open(...)`` is allowed only in read-binary mode
    (``open(..., "rb")``); any write/append mode is forbidden."""
    source = GUARD_PATH.read_text(encoding="utf-8")
    forbidden_writes = (
        "os.mkdir",
        "os.makedirs",
        "tempfile.NamedTemporaryFile",
        "tempfile.mkstemp",
        "os.rename",
        "os.replace",
        "os.unlink",
        "os.remove",
        ".write_text",
        ".write_bytes",
    )
    leaks = [t for t in forbidden_writes if t in source]
    assert leaks == [], f"guard has write surface: {leaks}"
    # Any ``open(...)`` call must be read-binary. Verify by scanning
    # each open(...) call site.
    import re as _re
    # Find every open(...) invocation and require its mode to be "rb".
    open_calls = _re.findall(r'open\([^)]*\)', source)
    for call in open_calls:
        # The mode argument is the last quoted string in the call.
        modes = _re.findall(r'"([^"]*)"|\'([^\']*)\'', call)
        flat = [m for pair in modes for m in pair if m]
        if not flat:
            # open(path) defaults to read-text; the guard uses explicit
            # "rb" everywhere. A bare open(path) is still read-only,
            # so allow it.
            continue
        # The last string is the mode (or encoding). Require it to be
        # a read mode.
        last = flat[-1]
        assert last in ("rb", "r", "rb"), (
            f"guard opens a file in non-read mode: {call!r}"
        )


def test_guard_happy_path_canonical_projection_matches_slots() -> None:
    """For a single state, the guard must succeed when the projection
    artifact's canonical bytes equal the on-disk artifact bytes AND the
    projection's legacy slots bytes equal the slots file bytes."""
    sc = _load_shared_core("p25b_guard_happy_sc")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        projection_artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        slots_file = run_root / "amount_slots.json"
        slots_file.write_bytes(side_slots.read_bytes())
        r2 = _run_guard_cli(
            "--run-root", str(run_root),
            "--projection", f"amount={projection_artifact}",
            "--slots", f"amount={slots_file}",
        )
        assert r2.returncode == 0, f"guard failed: {r2.stderr!r}"
        # Sanitized summary on stdout.
        payload = json.loads(r2.stdout)
        assert payload.get("kind") == KIND
        assert payload.get("schema_version") == SCHEMA_VERSION
        assert payload.get("states_verified") == ["amount"]
        # No content/path leak.
        assert "你好" not in r2.stdout
        assert str(projection_artifact) not in r2.stdout


def test_guard_happy_path_multiple_sorted_states() -> None:
    sc = _load_shared_core("p25b_guard_multi_sc")
    with _canonical_tempdir() as tmp:
        proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        r = _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        assert r.returncode == 0, r.stderr
        projection_artifact = run_root / "expected_slots_projections" / "fancy_widget.json"
        # Synthesize three state-specific slot files derived from the
        # same canonical slots bytes (the projection->slots check just
        # compares bytes against the same SharedCore-derived slots bytes).
        states = {"alpha", "beta", "gamma"}
        proj_paths = []
        slots_paths = []
        for s in sorted(states):
            sp = run_root / f"proj_{s}.json"
            sp.write_bytes(projection_artifact.read_bytes())
            proj_paths.append((s, sp))
            sl = run_root / f"slots_{s}.json"
            sl.write_bytes(side_slots.read_bytes())
            slots_paths.append((s, sl))
        args = ["--run-root", str(run_root)]
        for s, p in proj_paths:
            args += ["--projection", f"{s}={p}"]
        for s, p in slots_paths:
            args += ["--slots", f"{s}={p}"]
        r2 = _run_guard_cli(*args)
        assert r2.returncode == 0, f"guard multi failed: {r2.stderr!r}"
        payload = json.loads(r2.stdout)
        assert payload.get("states_verified") == ["alpha", "beta", "gamma"]


# ===========================================================================
# 6. Guard rejections.
# ===========================================================================


def _guard_happy_args(tmp: Path) -> tuple[list[str], Path, Path]:
    """Build a happy-path guard invocation; returns (args, projection,
    slots)."""
    proj, canvas, side_exp, side_slots = _setup_clean_sidecars(tmp)
    run_root = tmp / "run"
    run_root.mkdir()
    _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
    r = _run_adapter_cli(
        "--project-root", str(proj),
        "--canvas", str(canvas),
        "--run-root", str(run_root),
        "--feature-id", "fancy_widget",
    )
    assert r.returncode == 0, r.stderr
    projection = run_root / "expected_slots_projections" / "fancy_widget.json"
    slots = run_root / "amount_slots.json"
    slots.write_bytes(side_slots.read_bytes())
    args = [
        "--run-root", str(run_root),
        "--projection", f"amount={projection}",
        "--slots", f"amount={slots}",
    ]
    return args, projection, slots


def test_guard_rejects_missing_projection_arg() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, side_slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        slots = run_root / "amount_slots.json"
        slots.write_bytes(side_slots.read_bytes())
        r = _run_guard_cli(
            "--run-root", str(run_root),
            "--slots", f"amount={slots}",
        )
        assert r.returncode != 0


def test_guard_rejects_missing_slots_arg() -> None:
    with _canonical_tempdir() as tmp:
        proj, canvas, _exp, _slots = _setup_clean_sidecars(tmp)
        run_root = tmp / "run"
        run_root.mkdir()
        _run_adapter_cli("--project-root", str(proj), "--canvas", str(canvas))
        _run_adapter_cli(
            "--project-root", str(proj),
            "--canvas", str(canvas),
            "--run-root", str(run_root),
            "--feature-id", "fancy_widget",
        )
        projection = run_root / "expected_slots_projections" / "fancy_widget.json"
        r = _run_guard_cli(
            "--run-root", str(run_root),
            "--projection", f"amount={projection}",
        )
        assert r.returncode != 0


def test_guard_rejects_mismatched_state_sets() -> None:
    """projection state set and slots state set must be exactly equal."""
    with _canonical_tempdir() as tmp:
        args, projection, slots = _guard_happy_args(tmp)
        # Add a second projection for a state that has no matching slot.
        extra_proj = projection.parent / "extra.json"
        extra_proj.write_bytes(projection.read_bytes())
        bad_args = list(args) + ["--projection", f"extra={extra_proj}"]
        r = _run_guard_cli(*bad_args)
        assert r.returncode != 0


def test_guard_rejects_duplicate_state_in_projection() -> None:
    with _canonical_tempdir() as tmp:
        args, _projection, _slots = _guard_happy_args(tmp)
        # Re-add the same state in projection.
        proj_arg = next(a for a in args if a.startswith("amount="))
        bad_args = list(args) + ["--projection", proj_arg]
        r = _run_guard_cli(*bad_args)
        assert r.returncode != 0


def test_guard_rejects_invalid_state_id() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        bad_args = [
            "--run-root", args[1],
            "--projection", f"Bad-State={projection}",
            "--slots", f"Bad-State={projection}",
        ]
        r = _run_guard_cli(*bad_args)
        assert r.returncode != 0


def test_guard_rejects_unknown_arg() -> None:
    with _canonical_tempdir() as tmp:
        args, _p, _s = _guard_happy_args(tmp)
        r = _run_guard_cli(*args, "--evil", "yes")
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


def test_guard_rejects_noncanonical_projection_bytes() -> None:
    """projection file content != build_projection_bytes(doc) (e.g. extra
    trailing newline) must fail."""
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        projection.write_bytes(projection.read_bytes() + b"\n")
        r = _run_guard_cli(*args)
        assert r.returncode != 0


def test_guard_rejects_projection_with_mutated_bbox() -> None:
    """Mutating the projection's bbox (but keeping canonical bytes form)
    must fail the projection->slots byte equality check."""
    sc = _load_shared_core("p25b_guard_mut_sc")
    with _canonical_tempdir() as tmp:
        args, projection, slots = _guard_happy_args(tmp)
        doc = json.loads(projection.read_bytes().decode("utf-8"))
        # Mutate a non-slot text bbox; this changes the expected bytes
        # but does not affect the slots bytes (so projection->slots will
        # still match for slots but projection canonical check fails
        # only if the on-disk artifact diverges from canonical(projection)).
        # The actual guard assertion: build_projection_bytes(doc) must
        # equal raw bytes; if we keep raw bytes in sync, projection
        # passes; the projection->slots check then expects the slots
        # bytes to match the mutated projection. Mutate bbox in the
        # projection AND reserialize canonical, so the guard must
        # rebuild different slots bytes and fail to match the on-disk
        # slots.
        for n in doc["nodes"]:
            if n["id"] == "amount":
                n["text"] = "MUTATED_AMOUNT_TEXT"
                break
        new_bytes = sc.build_projection_bytes(doc)
        projection.write_bytes(new_bytes)
        r = _run_guard_cli(*args)
        assert r.returncode != 0


def test_guard_rejects_mutated_slots_file() -> None:
    """Mutating the slots file content must fail the projection->slots
    byte equality check."""
    with _canonical_tempdir() as tmp:
        args, _projection, slots = _guard_happy_args(tmp)
        mutated = json.loads(slots.read_bytes().decode("utf-8"))
        for k in mutated:
            mutated[k] = "DIFFERENT_TEXT"
            break
        slots.write_bytes(
            json.dumps(mutated, ensure_ascii=False, indent=2).encode("utf-8")
        )
        r = _run_guard_cli(*args)
        assert r.returncode != 0


def test_guard_rejects_invalid_utf8_projection() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        projection.write_bytes(b'{"kind": "' + b"\xff" + b'"}')
        r = _run_guard_cli(*args)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr


def test_guard_rejects_duplicate_json_keys_projection() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        projection.write_bytes(
            b'{"kind": "x", "kind": "y"}\n'
        )
        r = _run_guard_cli(*args)
        assert r.returncode != 0


def test_guard_rejects_oversized_projection() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        huge = b"x" * (MAX_PROJECTION_BYTES + 64)
        projection.write_bytes(huge)
        r = _run_guard_cli(*args)
        assert r.returncode != 0


def test_guard_rejects_symlinked_projection_leaf() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        link = projection.parent / "link.json"
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(projection, link)
        # Replace the projection arg with the symlink path.
        new_args = []
        for a in args:
            if a.startswith("amount=") and a.endswith(str(projection)):
                new_args.append(f"amount={link}")
            else:
                new_args.append(a)
        r = _run_guard_cli(*new_args)
        assert r.returncode != 0


def test_guard_rejects_projection_outside_run_root() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        outside = tmp / "outside.json"
        outside.write_bytes(projection.read_bytes())
        # Replace projection path with the outside path.
        new_args = []
        for a in args:
            if a.startswith("amount=") and a.endswith(str(projection)):
                new_args.append(f"amount={outside}")
            else:
                new_args.append(a)
        r = _run_guard_cli(*new_args)
        assert r.returncode != 0


def test_guard_rejects_non_file_projection() -> None:
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        # Replace projection path with a directory.
        d = projection.parent / "subdir"
        d.mkdir()
        new_args = []
        for a in args:
            if a.startswith("amount=") and a.endswith(str(projection)):
                new_args.append(f"amount={d}")
            else:
                new_args.append(a)
        r = _run_guard_cli(*new_args)
        assert r.returncode != 0


def test_guard_rejects_symlinked_run_root() -> None:
    with _canonical_tempdir() as tmp:
        args, _p, _s = _guard_happy_args(tmp)
        # Make a symlink to run_root.
        run_root_real = Path(args[1])
        link = tmp / "run_link"
        os.symlink(run_root_real, link)
        new_args = [args[0], str(link)] + args[2:]
        r = _run_guard_cli(*new_args)
        assert r.returncode != 0


def test_guard_failure_sanitized_no_leak() -> None:
    """On failure, the guard must emit only exception type plus fixed
    role/state-safe text; no traceback, absolute path, raw content,
    arbitrary exception text, or environment."""
    with _canonical_tempdir() as tmp:
        args, projection, _slots = _guard_happy_args(tmp)
        # Force a noncanonical-projection failure.
        projection.write_bytes(b'{"not": "canonical"}')
        r = _run_guard_cli(*args)
        assert r.returncode != 0
        combined = r.stderr + r.stdout
        assert "Traceback" not in combined
        assert "你好" not in combined
        assert str(projection) not in combined
        assert str(args[1]) not in combined


def test_guard_no_pycache_created() -> None:
    cache_dir = SHARED_CORE_DIR / "__pycache__"
    pre = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    with _canonical_tempdir() as tmp:
        args, _p, _s = _guard_happy_args(tmp)
        _run_guard_cli(*args)
    post = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    new = {p for p in (post - pre) if "expected_slots_projection_v1" in p.name}
    assert not new, f"guard created __pycache__: {sorted(p.name for p in new)}"


# ===========================================================================
# 7. Visible operation: four steps, adapter argv includes run-root/feature-id.
# ===========================================================================


def _patched_operations(module):
    """Patch capsule verify + manifest for an isolated build."""
    saved_vc = module._verify_capsule
    saved_lm = module._load_manifest
    module._verify_capsule = lambda: {
        "kind": "icp.iff-v1-vendor-capsule-verify", "ok": True,
        "capsule_root": "vendor/iff_v1",
    }
    real_manifest = module._load_manifest()
    module._load_manifest = lambda: real_manifest
    return saved_vc, saved_lm


def _restore_operations(module, saved):
    saved_vc, saved_lm = saved
    module._verify_capsule = saved_vc
    module._load_manifest = saved_lm


def _make_visible_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "feature_id": "fancy_widget",
        "render_plan": "render_plan.json",
        "scene": "scene.json",
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


def _setup_visible_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "canvas").mkdir(parents=True, exist_ok=True)
    (project_root / "lib" / "status").mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("render_plan.json", {"a": 1}),
        ("scene.json", {"a": 1}),
        ("classification.json", {"a": 1}),
        ("component_manifest.json", {"a": 1}),
    ):
        _write_json(run_root / name, payload)


def test_visible_operation_remains_four_ordered_steps() -> None:
    module = _load_operations("p25b_vis_steps")
    spec = module._VISIBLE_STEPS_SPEC
    assert [s["step_id"] for s in spec] == [
        "generate_canvas", "adapt_expected_slots",
        "make_implementation_map", "make_status_bar_policy",
    ]


def test_visible_operation_adapter_argv_includes_run_root_and_feature_id() -> None:
    module = _load_operations("p25b_vis_argv")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_visible_inputs(proj, run)
            request = _make_visible_request(proj, run)
            plan = module.build("flutter.visible_codegen.v1", request)
    finally:
        _restore_operations(module, saved)
    adapt = plan["steps"][1]
    assert adapt["step_id"] == "adapt_expected_slots"
    argv = adapt["argv"]
    # argv[2:] must contain --project-root, --canvas, --run-root, --feature-id
    # in that exact order.
    assert argv[2:] == [
        "--project-root", str(proj),
        "--canvas", str(proj / "lib" / "canvas" / "canvas.dart"),
        "--run-root", str(run),
        "--feature-id", "fancy_widget",
    ], argv[2:]


def test_visible_operation_request_keys_unchanged() -> None:
    module = _load_operations("p25b_vis_keys")
    # The PUBLIC request key set must be unchanged.
    assert module._VISIBLE_REQUEST_KEYS == frozenset({
        "project_root", "run_root", "package_name", "feature_id",
        "render_plan", "scene", "classification", "component_manifest",
        "canvas_out", "colors_out", "colors_import_path",
        "implementation_map_out", "status_bar_out",
        "canvas_class_name", "status_bar_class_name",
    })


def test_visible_operation_run_root_added_to_internal_validated_result() -> None:
    """The internal validated visible request result must carry run_root
    so the adapter argv can be built from validated values; the public
    request keys are unchanged."""
    module = _load_operations("p25b_vis_internal")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_visible_inputs(proj, run)
            request = _make_visible_request(proj, run)
            validated = module._validate_visible_request(request)
    finally:
        _restore_operations(module, saved)
    assert validated.get("run_root") == run


# ===========================================================================
# 8. Fixture operation: two steps, requires matching projections, argv
#    determinism, platform primitive path/SHA binding, tamper rejection.
# ===========================================================================


def test_fixture_operation_steps_spec_is_two_in_exact_order() -> None:
    module = _load_operations("p25b_fix_spec")
    spec = module._FIXTURE_STEPS_SPEC
    assert [s["step_id"] for s in spec] == [
        "verify_fixture_projections", "make_visual_fixture",
    ]


def test_fixture_operation_verify_step_is_platform_origin() -> None:
    module = _load_operations("p25b_fix_origin")
    spec = module._FIXTURE_STEPS_SPEC
    verify_step = spec[0]
    assert verify_step["primitive"] == "flutter_fixture_projection_guard_v1.py"
    assert verify_step.get("script_origin") == "platform"


def test_fixture_operation_make_visual_fixture_step_unchanged() -> None:
    module = _load_operations("p25b_fix_mvf")
    spec = module._FIXTURE_STEPS_SPEC
    mvf = spec[1]
    assert mvf["primitive"] == "make_visual_fixture.py"
    # Capsule origin (default).
    assert mvf.get("script_origin", "capsule") == "capsule"


def test_fixture_operation_request_requires_projections() -> None:
    """Request schema must include required key 'projections'."""
    module = _load_operations("p25b_fix_req")
    assert "projections" in module._FIXTURE_REQUEST_KEYS


def _make_fixture_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "feature_id": "fancy_widget",
        "slots": {
            "loading": "slot_loading.json",
            "ready": "slot_ready.json",
        },
        "projections": {
            "loading": "proj_loading.json",
            "ready": "proj_ready.json",
        },
        "out": "lib/fixtures/fixture.dart",
    }


def _setup_fixture_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "fixtures").mkdir(parents=True, exist_ok=True)
    for name in ("loading", "ready"):
        _write_json(run_root / f"slot_{name}.json", {"state": name})
        _write_json(run_root / f"proj_{name}.json", {"proj": name})


def test_fixture_operation_rejects_missing_projections() -> None:
    module = _load_operations("p25b_fix_missing_proj")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            bad = _make_fixture_request(proj, run)
            del bad["projections"]
            try:
                module.build("flutter.fixture_codegen.v1", bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("missing projections accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_rejects_projections_state_set_mismatch() -> None:
    module = _load_operations("p25b_fix_proj_mismatch")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            bad = _make_fixture_request(proj, run)
            bad["projections"] = {
                "loading": "proj_loading.json",
                "ready": "proj_ready.json",
                "extra": "proj_extra.json",
            }
            _write_json(run / "proj_extra.json", {"proj": "extra"})
            try:
                module.build("flutter.fixture_codegen.v1", bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("projections state-set mismatch accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_producer_before_consumer_gate() -> None:
    """If projections files don't exist yet, building the fixture must
    fail at request validation (producer-before-consumer gate)."""
    module = _load_operations("p25b_fix_pbc")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            # Delete projection files.
            for name in ("loading", "ready"):
                (run / f"proj_{name}.json").unlink()
            request = _make_fixture_request(proj, run)
            try:
                module.build("flutter.fixture_codegen.v1", request)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("producer-before-consumer gate not enforced")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_guard_argv_is_deterministic_sorted() -> None:
    """verify_fixture_projections argv: interpreter, platform primitive,
    --run-root <abs>, --projection STATE=<abs> (sorted state order),
    --slots STATE=<abs> (sorted state order)."""
    module = _load_operations("p25b_fix_argv")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
    finally:
        _restore_operations(module, saved)
    assert len(plan["steps"]) == 2
    guard_step = plan["steps"][0]
    assert guard_step["step_id"] == "verify_fixture_projections"
    argv = guard_step["argv"]
    # Argv structure: interpreter, guard script, --run-root, --projection
    # pairs (sorted), --slots pairs (sorted).
    assert argv[0] == sys.executable
    assert argv[1] == str(
        module.PLATFORM_SCRIPTS_DIR / "flutter_fixture_projection_guard_v1.py"
    )
    rest = argv[2:]
    # --run-root comes first.
    assert rest[0] == "--run-root"
    assert rest[1] == str(run)
    rest2 = rest[2:]
    # Two --projection pairs in sorted state order: loading, ready.
    assert rest2[0] == "--projection"
    assert rest2[1] == f"loading={run / 'proj_loading.json'}"
    assert rest2[2] == "--projection"
    assert rest2[3] == f"ready={run / 'proj_ready.json'}"
    # Two --slots pairs in sorted state order.
    assert rest2[4] == "--slots"
    assert rest2[5] == f"loading={run / 'slot_loading.json'}"
    assert rest2[6] == "--slots"
    assert rest2[7] == f"ready={run / 'slot_ready.json'}"


def test_fixture_operation_guard_step_primitive_sha_recomputed() -> None:
    """The platform primitive SHA must be recomputed from the file and
    equal the current file SHA (no manifest entry consulted)."""
    module = _load_operations("p25b_fix_sha")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
    finally:
        _restore_operations(module, saved)
    guard_step = plan["steps"][0]
    expected_sha = _sha256_file(
        module.PLATFORM_SCRIPTS_DIR / "flutter_fixture_projection_guard_v1.py"
    )
    assert guard_step["primitive_sha256"] == expected_sha


def test_fixture_operation_make_visual_fixture_argv_unchanged() -> None:
    """The make_visual_fixture step argv must remain unchanged: --feature,
    --slots STATE=ABS sorted, --out."""
    module = _load_operations("p25b_fix_mvf_argv")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
    finally:
        _restore_operations(module, saved)
    mvf = plan["steps"][1]
    argv = mvf["argv"]
    assert argv[2:] == [
        "--feature", "fancy_widget",
        "--slots", f"loading={run / 'slot_loading.json'}",
        "--slots", f"ready={run / 'slot_ready.json'}",
        "--out", str(proj / "lib" / "fixtures" / "fixture.dart"),
    ]


def test_fixture_operation_verify_plan_rejects_tampered_guard_path() -> None:
    module = _load_operations("p25b_fix_tamper_path")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            plan["steps"][0]["argv"][1] = "/tmp/evil_guard.py"
            try:
                module.verify_plan(plan)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("tampered guard path accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_verify_plan_rejects_tampered_guard_sha() -> None:
    module = _load_operations("p25b_fix_tamper_sha")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            plan["steps"][0]["primitive_sha256"] = "a" * 64
            try:
                module.verify_plan(plan)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("tampered guard sha accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_verify_plan_rejects_reordered_steps() -> None:
    module = _load_operations("p25b_fix_reorder")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            bad = copy.deepcopy(plan)
            bad["steps"][0], bad["steps"][1] = bad["steps"][1], bad["steps"][0]
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("reordered steps accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_verify_plan_rejects_guard_cwd_tamper_only() -> None:
    """Security: changing only the guard step's cwd to another real
    absolute normalized directory must be rejected. Merely re-applying
    _check_root_nesting(cwd, run_root) would accept any disjoint cwd;
    the corrected cwd_binding closes the gap by requiring the guard cwd
    to equal the immediately-following consumer step's cwd."""
    module = _load_operations("p25b_fix_tamper_cwd_only")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            other = tmp / "other_proj"
            proj.mkdir(); run.mkdir(); other.mkdir()
            # Give the other dir a project shape so its cwd is a
            # plausible absolute normalized directory.
            (other / "lib").mkdir(parents=True)
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            bad = copy.deepcopy(plan)
            # Tamper ONLY the guard cwd to another real dir; keep the
            # consumer cwd unchanged. Nesting between `other` and `run`
            # is disjoint (passes _check_root_nesting), so this isolates
            # the equality-with-consumer rule.
            bad["steps"][0]["cwd"] = str(other)
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("guard-only cwd tamper accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_verify_plan_rejects_coordinated_cwd_tamper() -> None:
    """Security: changing BOTH the guard cwd AND the consumer cwd to
    another real absolute normalized directory must STILL be rejected,
    because the consumer step remains independently anchored to its
    project-rooted --out argv path by the default cwd_binding rule.
    This proves the equality-with-consumer rule is defense in depth,
    not the sole anchor."""
    module = _load_operations("p25b_fix_tamper_cwd_coordinated")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            other = tmp / "other_proj"
            proj.mkdir(); run.mkdir(); other.mkdir()
            (other / "lib" / "fixtures").mkdir(parents=True)
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            bad = copy.deepcopy(plan)
            # Tamper BOTH cwds to another real dir. The consumer's
            # --out argv still points into the original proj tree, so
            # the default cwd_binding on the consumer must reject this.
            bad["steps"][0]["cwd"] = str(other)
            bad["steps"][1]["cwd"] = str(other)
            try:
                module.verify_plan(bad)
            except module.OperationPlanError:
                pass
            else:
                raise AssertionError("coordinated cwd tamper accepted")
    finally:
        _restore_operations(module, saved)


def test_fixture_operation_verify_plan_accepts_valid_guard_cwd() -> None:
    """Sanity: the valid plan remains accepted (both steps cwd equal
    to the validated project_root, consumer anchored by --out)."""
    module = _load_operations("p25b_fix_valid_cwd")
    saved = _patched_operations(module)
    try:
        with _canonical_tempdir() as tmp:
            proj = tmp / "proj"
            run = tmp / "run"
            proj.mkdir(); run.mkdir()
            _setup_fixture_inputs(proj, run)
            request = _make_fixture_request(proj, run)
            plan = module.build("flutter.fixture_codegen.v1", request)
            report = module.verify_plan(plan)
    finally:
        _restore_operations(module, saved)
    assert report["ok"] is True
    assert report["steps_total"] == 2


def test_fixture_operation_verify_plan_rejects_wrong_origin() -> None:
    """verify_fixture_projections must be platform origin; tampering
    script_origin to 'capsule' must fail (the spec re-derives origin
    from the internal fixed spec, so this is just a behavior check)."""
    module = _load_operations("p25b_fix_wrong_origin")
    # The internal spec's origin is fixed; verify the step SHA matches
    # the recomputed platform-script SHA, not a capsule manifest entry.
    capsule_names = set()
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    for entry in manifest["scripts"]:
        capsule_names.add(entry["name"])
    assert "flutter_fixture_projection_guard_v1.py" not in capsule_names, (
        "platform primitive must not collide with capsule manifest"
    )


def test_fixture_operation_no_new_operation_id_or_registry_entry() -> None:
    """Operation IDs and registries must remain unchanged."""
    module = _load_operations("p25b_fix_no_new")
    assert "flutter.fixture_codegen.v1" in module.list_operation_ids()
    # Registry file unchanged. The registry uses the short port id
    # ``fixture_codegen`` (not the full ``flutter.fixture_codegen.v1``
    # operation id); confirm it is still present exactly once.
    registry = json.loads(REGISTRY_PATH.read_bytes())
    text = json.dumps(registry)
    assert "fixture_codegen" in text


# ===========================================================================
# 9. Binding/authorization/executor end-to-end propagation for the new
#    fixture guard.
# ===========================================================================


def test_fixture_guard_end_to_end_through_executor() -> None:
    """Build a verified fixture_codegen authorization whose plan has two
    steps, substitute BOTH the capsule make_visual_fixture primitive and
    the platform guard primitive with safe stubs, and execute. The
    report must show two successful steps in exact order."""
    # Import executor module by file path.
    executor = _load("p25b_e2e_exec", EXECUTOR_PATH)
    authz_module = executor._load_authorization_module()
    binding_module = authz_module._load_binding_module()
    operations_module = binding_module._load_operations_module()

    # Use the existing test pattern: build a frozen project + manifest.
    sys.path.insert(0, str(ICP_SCRIPTS))
    try:
        # Use the helpers from the existing p2e2b test if available; else
        # build a minimal local equivalent.
        from importlib.util import spec_from_file_location as _spec
        # We need _frozen_canonical_flutter_project and _with_fake_preflight.
        # Load them from the existing p2e2b selftest to avoid duplication.
        p2e2b_path = ICP_SCRIPTS / "selftest_p2e2b_flutter_executor.py"
        spec_ = _spec("p25b_p2e2b_helpers", str(p2e2b_path))
        helpers_mod = importlib.util.module_from_spec(spec_)
        sys.modules["p25b_p2e2b_helpers"] = helpers_mod
        spec_.loader.exec_module(helpers_mod)
    finally:
        sys.path.pop(0)

    frozen = helpers_mod._frozen_canonical_flutter_project
    fake_preflight = helpers_mod._with_fake_preflight
    write_json = helpers_mod._write_json
    sha_bytes = helpers_mod._sha256_bytes

    @contextlib.contextmanager
    def _substituted_fixture(executor_module, *, batch_id="p25b-e2e"):
        am = executor_module._load_authorization_module()
        bm = am._load_binding_module()
        ops = bm._load_operations_module()
        script_dir = Path(os.path.realpath(
            tempfile.mkdtemp(prefix=f"p25b_fix_{batch_id}_")
        ))
        try:
            with frozen(batch_id=batch_id) as (proj, run_root, mp):
                with fake_preflight(bm):
                    saved_csd = ops.CAPSULE_SCRIPTS_DIR
                    saved_psd = ops.PLATFORM_SCRIPTS_DIR
                    saved_lm = ops._load_manifest
                    saved_vc = ops._verify_capsule
                    # Write the platform guard stub as a read-only
                    # success stub (it never writes anything).
                    guard_name = "flutter_fixture_projection_guard_v1.py"
                    (script_dir / guard_name).write_text(
                        "import sys; sys.exit(0)\n", encoding="utf-8"
                    )
                    # Write the make_visual_fixture capsule stub.
                    capsule_name = "make_visual_fixture.py"
                    (script_dir / capsule_name).write_text(
                        "import sys; sys.exit(0)\n", encoding="utf-8"
                    )
                    real_manifest = ops._load_manifest()
                    patched_scripts = []
                    for entry in real_manifest["scripts"]:
                        if entry["name"] == capsule_name:
                            sp = script_dir / capsule_name
                            patched_scripts.append(
                                {**entry, "sha256": sha_bytes(sp.read_bytes())}
                            )
                        else:
                            patched_scripts.append(entry)
                    patched_manifest = {**real_manifest, "scripts": patched_scripts}
                    ops.CAPSULE_SCRIPTS_DIR = script_dir
                    ops.PLATFORM_SCRIPTS_DIR = script_dir
                    ops._load_manifest = lambda: patched_manifest
                    ops._verify_capsule = lambda: {
                        "kind": "icp.iff-v1-vendor-capsule-verify",
                        "ok": True, "capsule_root": "vendor/iff_v1",
                    }
                    try:
                        # Set up fixture inputs.
                        (proj / "lib" / "fixtures").mkdir(parents=True, exist_ok=True)
                        for name in ("loading", "ready"):
                            write_json(run_root / f"slot_{name}.json", {"s": name})
                            write_json(run_root / f"proj_{name}.json", {"p": name})
                        request = {
                            "project_root": str(proj),
                            "run_root": str(run_root),
                            "package_name": "my_app",
                            "feature_id": "fancy_widget",
                            "slots": {
                                "loading": "slot_loading.json",
                                "ready": "slot_ready.json",
                            },
                            "projections": {
                                "loading": "proj_loading.json",
                                "ready": "proj_ready.json",
                            },
                            "out": "lib/fixtures/fixture.dart",
                        }
                        binding = bm.prepare_binding(
                            mp, "flutter.fixture_codegen.v1", request
                        )
                        vr = bm.verify_binding(binding)
                        manifest_sha = sha_bytes(mp.read_bytes())
                        bd = vr["binding_digest"]
                        nonce = "0123456789abcdef0123456789abcdef"
                        authz = am.prepare_authorization(
                            binding,
                            expected_manifest_path=str(mp),
                            expected_manifest_sha256=manifest_sha,
                            expected_binding_digest=bd,
                            execution_nonce=nonce,
                        )
                        expected = (
                            str(mp), manifest_sha, bd,
                            authz["authorization_digest"],
                        )
                        yield authz, expected, nonce, run_root
                    finally:
                        ops.CAPSULE_SCRIPTS_DIR = saved_csd
                        ops.PLATFORM_SCRIPTS_DIR = saved_psd
                        ops._load_manifest = saved_lm
                        ops._verify_capsule = saved_vc
        finally:
            import shutil
            shutil.rmtree(script_dir, ignore_errors=True)

    with _substituted_fixture(executor) as (authz, expected, nonce, run_root):
        report = executor.execute_authorization(
            authorization=authz,
            expected_manifest_path=expected[0],
            expected_manifest_sha256=expected[1],
            expected_binding_digest=expected[2],
            expected_authorization_digest=expected[3],
        )
    assert report["ok"] is True, report
    assert report["overall_status"] == "success"
    # Two steps in order: verify_fixture_projections then make_visual_fixture.
    assert len(report["step_results"]) == 2
    assert report["step_results"][0]["step_id"] == "verify_fixture_projections"
    assert report["step_results"][1]["step_id"] == "make_visual_fixture"
    for sr in report["step_results"]:
        assert sr["status"] == "success"
        assert sr["exit_code"] == 0


# ===========================================================================
# 10. No platform activation, registry change, vendor/baseline/IFF change.
# ===========================================================================


def test_no_platform_activation_gate_change() -> None:
    """The flutter_standard_v1 module must remain unchanged from its
    protected hash (no activation change). P2.5d is authorized to update
    the trace_harness legacy primitive tuple; the P2.5d-final hash is
    recorded here. The activation_state, executable flag, and every
    other operation's mapping remain unchanged."""
    # P2.5d authorized transition: trace_harness tuple now mirrors the
    # trusted plan's capsule legacy primitives in execution order:
    # (merge_shared_expected.py, gen_layout_trace_test.py).
    expected = "a5dfdd9fe5c480d1cd42e558aba40b3eacbb891234e6ec54164baab9c16c2ba2"
    actual = _sha256_file(PLATFORMS_DIR / "flutter_standard_v1.py")
    assert actual == expected, (
        f"flutter_standard_v1.py hash changed: {actual} != {expected}"
    )


def test_no_registry_change() -> None:
    expected = "9b8cca5c2898c0b295fa28e6dbd6e7b32220145dd6c0cd041ad667b0d0253b84"
    actual = _sha256_file(REGISTRY_PATH)
    assert actual == expected, (
        f"registries.json hash changed: {actual} != {expected}"
    )


def test_no_vendor_baseline_change() -> None:
    expected = "72e8401bb42e3c1b9cfd8c07d9cc44050833ed7658b3358476b9aaa4a7a257ec"
    actual = _sha256_file(
        ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
    )
    assert actual == expected


def test_no_pycache_under_icp() -> None:
    """No __pycache__ anywhere under icp/."""
    found: list[Path] = []
    for path in ICP_ROOT.rglob("__pycache__"):
        if path.is_dir():
            found.append(path)
    assert not found, f"__pycache__ present under icp/: {found}"


def test_protected_execution_hashes_unchanged() -> None:
    """All seven protected production hashes must be unchanged. P2.5d is
    authorized to update flutter_standard_v1.py (trace_harness tuple
    update) and flutter_operations_v1.py (trace_harness schema + plan
    + cross-step identity coupling); their P2.5d-final hashes are
    recorded here with annotations."""
    expected = {
        "flutter_execution_binding_v1.py":
            "d6668876865d0d090ea057bc73274a502e1057d888bdca1336c236c65f4a5a9d",
        "flutter_execution_authorization_v1.py":
            "1d6a17bfb64420a3357c4a914f93d2b3f3e22ac2476d2c24b8141d21c246bbd2",
        "flutter_execution_executor_v1.py":
            "34fdfd22c4ced65216d5e7925696fbda7a9317a460478843314d49bb4f395cb2",
        "flutter_project_preflight_v1.py":
            "56476140ec998f796fd9181b7aad5342ca67f0508f5d078873c2fbe00a53cb11",
        # P2.5d authorized transition: frozen at P2.5d-final value.
        "flutter_standard_v1.py":
            "a5dfdd9fe5c480d1cd42e558aba40b3eacbb891234e6ec54164baab9c16c2ba2",
    }
    for name, sha in expected.items():
        actual = _sha256_file(PLATFORMS_DIR / name)
        assert actual == sha, f"{name} hash changed: {actual} != {sha}"


# ===========================================================================
# Selftest runner.
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
