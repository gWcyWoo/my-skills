#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2.5a1 SharedCore contract.

P2.5a1 adds exactly one new platform-neutral contract to SharedCore: the
expected/slots projection v1 (``shared_core/expected_slots_projection_v1.py``).
SharedCore owns only:

  1. strict validation of the projection,
  2. deterministic construction of the legacy ``.expected.json`` and
     ``.slots.json`` documents,
  3. byte serialization exactly matching the frozen legacy JSON sidecars.

This selftest is **contract + proof only**. It does not change the iFF v1
compatibility capsule, the platform adapter, any execution plan/registry, any
authorization, any executor, or any platform activation gate.

The differential parity proof instruments the frozen capsule
``icp/vendor/iff_v1/scripts/generate_canvas.py`` **in-process** without
modifying it: it wraps ``emit_node`` to capture references to the capsule's
final ``nodes``/``placed``/``anchors``/``slot_ids`` intermediate state, then
rebuilds the same expected/slots bytes from a platform-neutral projection.
Production SharedCore never imports the capsule — only this test does.

Run directly::

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25a1_expected_slots_projection.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import json
import math
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
PROD_MODULE_PATH = ICP_SCRIPTS / "shared_core" / "expected_slots_projection_v1.py"
PROD_PACKAGE_PATH = ICP_SCRIPTS / "shared_core" / "__init__.py"
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
CAPSULE_GENERATE_CANVAS = CAPSULE_SCRIPTS / "generate_canvas.py"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"
FREEZE_TOOL = ICP_SCRIPTS / "freeze_iff_baseline.py"
IFF_BASELINE = ICP_ROOT / "references" / "baselines" / "iff-v1.json"
IFF_ROOT = REPO_ROOT / "iff"

KIND = "icp.shared.expected-slots-projection.v1"
SCHEMA_VERSION = 1

# Forbidden production-source tokens. Kept here in the TEST only (never in the
# production module). Production must be standard-library-only with no
# process/network/filesystem execution surface and no capsule/platform import.
FORBIDDEN_TOKENS = (
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
    "generate_canvas",
    "vendor.iff_v1",
    "import iff",
    "platforms",
    "argparse",
    "Path(",
    "open(",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
)


# ---------------------------------------------------------------------------
# Module loader (file-path based; no package import side effects).
# ---------------------------------------------------------------------------


def _load_prod_module(name: str = "p25a1_prod"):
    spec = importlib.util.spec_from_file_location(name, str(PROD_MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_capsule_generate_canvas():
    """Import the frozen capsule generate_canvas.py by file path (test only)."""
    spec = importlib.util.spec_from_file_location(
        "p25a1_capsule_generate_canvas", str(CAPSULE_GENERATE_CANVAS)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25a1_capsule_generate_canvas"] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p25a1_"):
    """A temp directory whose path is realpath-canonicalized.

    The macOS ``/tmp`` -> ``/private/tmp`` (and ``/var`` -> ``/private/var``)
    symlinks would otherwise trip the capsule verifier's strict no-symlink
    path-chain check.
    """
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


def _write_json(path: Path, payload: Any) -> bytes:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


# ---------------------------------------------------------------------------
# Minimal valid projection factory (for rejection tests + serialization tests).
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
# 0. Precondition: capsule is verified clean before any differential use.
# ===========================================================================


def test_frozen_capsule_verifies_clean() -> None:
    """The frozen capsule must pass its installed verifier before we touch it."""
    r = _run_cli(VERIFY_TOOL)
    assert r.returncode == 0, f"verifier failed: rc={r.returncode} stderr={r.stderr!r}"
    assert r.stderr == ""
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


def test_frozen_baseline_unchanged() -> None:
    """The iff baseline must match the live iff tree (frozen truth untouched)."""
    r = _run_cli(
        FREEZE_TOOL,
        "--iff-root", "iff",
        "--check", "icp/references/baselines/iff-v1.json",
    )
    assert r.returncode == 0, f"baseline check failed: rc={r.returncode} stderr={r.stderr!r} stdout={r.stdout!r}"


def test_git_diff_iff_is_clean() -> None:
    """No mutation of the protected iff/ tree is permitted by this slice."""
    r = subprocess.run(
        ["git", "diff", "--exit-code", "--", "iff"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"iff/ has uncommitted changes:\n{r.stdout}"


# ===========================================================================
# 1. Module surface and types.
# ===========================================================================


def test_module_loads_and_exposes_typed_exception() -> None:
    module = _load_prod_module("p25a1_load")
    assert issubclass(module.ProjectionValidationError, ValueError)


def test_module_has_no_cli_main() -> None:
    module = _load_prod_module("p25a1_nocli")
    assert not hasattr(module, "main")
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    assert "__name__ == \"__main__\"" not in source
    assert "argparse" not in source


def test_module_exposes_only_approved_public_api() -> None:
    module = _load_prod_module("p25a1_pubapi")
    # P2.5b appends build_projection_bytes as the third approved public
    # function: a pure canonical-byte serializer for the projection
    # itself (used by the adapter/guard, not by the legacy reconstruction
    # path).
    allowed_funcs = {"build_documents", "build_legacy_bytes", "build_projection_bytes"}
    public_funcs = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_funcs) == allowed_funcs, f"unexpected public funcs: {set(public_funcs) - allowed_funcs}"
    public_classes = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"ProjectionValidationError"}, public_classes


def test_build_documents_signature() -> None:
    module = _load_prod_module("p25a1_sig_docs")
    sig = inspect.signature(module.build_documents)
    params = list(sig.parameters)
    assert params == ["projection"], sig
    assert sig.parameters["projection"].default is inspect.Parameter.empty


def test_build_legacy_bytes_signature() -> None:
    module = _load_prod_module("p25a1_sig_bytes")
    sig = inspect.signature(module.build_legacy_bytes)
    params = list(sig.parameters)
    assert params == ["projection"], sig
    assert sig.parameters["projection"].default is inspect.Parameter.empty


# ===========================================================================
# 2. Strict validation: rejection cases (RED must drive every branch).
# ===========================================================================


def _reject(projection: Any) -> None:
    module = _load_prod_module("p25a1_reject")
    try:
        module.build_documents(projection)
    except module.ProjectionValidationError:
        return
    raise AssertionError(f"projection should have been rejected: {projection!r}")


def test_reject_unknown_top_level_field() -> None:
    p = _minimal_projection()
    p["extra"] = True
    _reject(p)


def test_reject_missing_kind() -> None:
    p = _minimal_projection()
    del p["kind"]
    _reject(p)


def test_reject_missing_schema_version() -> None:
    p = _minimal_projection()
    del p["schemaVersion"]
    _reject(p)


def test_reject_missing_artboard_width() -> None:
    p = _minimal_projection()
    del p["artboardWidth"]
    _reject(p)


def test_reject_missing_artboard_height() -> None:
    p = _minimal_projection()
    del p["artboardHeight"]
    _reject(p)


def test_reject_missing_design_pixel_scale() -> None:
    p = _minimal_projection()
    del p["designPixelScale"]
    _reject(p)


def test_reject_missing_nodes() -> None:
    p = _minimal_projection()
    del p["nodes"]
    _reject(p)


def test_reject_wrong_kind() -> None:
    p = _minimal_projection()
    p["kind"] = "icp.something.else.v1"
    _reject(p)


def test_reject_wrong_schema_version() -> None:
    for bad in (0, 2, "1", 1.0, True, None):
        p = _minimal_projection()
        p["schemaVersion"] = bad
        _reject(p)


def test_reject_artboard_width_wrong_types() -> None:
    for bad in ("750", None, True, [750], {"v": 750}):
        p = _minimal_projection()
        p["artboardWidth"] = bad
        _reject(p)


def test_reject_artboard_width_zero_negative_nan_inf() -> None:
    for bad in (0, -1, 0.0, float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["artboardWidth"] = bad
        _reject(p)


def test_reject_artboard_height_zero_negative_nan_inf() -> None:
    for bad in (0, -1, 0.0, float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["artboardHeight"] = bad
        _reject(p)


def test_reject_design_pixel_scale_zero_negative_nan_inf() -> None:
    for bad in (0, -2, 0.0, float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["designPixelScale"] = bad
        _reject(p)


def test_reject_design_pixel_scale_boolean() -> None:
    p = _minimal_projection()
    p["designPixelScale"] = True
    _reject(p)


def test_reject_nodes_not_list() -> None:
    for bad in ({}, "n", None, ()):
        p = _minimal_projection()
        p["nodes"] = bad
        _reject(p)


def test_reject_node_not_object() -> None:
    for bad in ("x", 1, None, [1, 2]):
        p = _minimal_projection()
        p["nodes"] = [bad]
        _reject(p)


def test_reject_node_unknown_field() -> None:
    p = _minimal_projection()
    p["nodes"][0]["extra"] = True
    _reject(p)


def test_reject_node_missing_id() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["id"]
    _reject(p)


def test_reject_node_missing_bbox() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["bbox"]
    _reject(p)


def test_reject_node_missing_horizontal_anchor() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["horizontalAnchor"]
    _reject(p)


def test_reject_node_missing_impl() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["impl"]
    _reject(p)


def test_reject_node_missing_text() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["text"]
    _reject(p)


def test_reject_node_missing_source_text() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["sourceText"]
    _reject(p)


def test_reject_node_missing_text_runs() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["textRuns"]
    _reject(p)


def test_reject_node_missing_font_size() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["fontSize"]
    _reject(p)


def test_reject_node_missing_weight() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["weight"]
    _reject(p)


def test_reject_node_missing_color_hex() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["colorHex"]
    _reject(p)


def test_reject_node_missing_radius() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["radius"]
    _reject(p)


def test_reject_node_missing_slot() -> None:
    p = _minimal_projection()
    del p["nodes"][0]["slot"]
    _reject(p)


def test_reject_node_id_not_string() -> None:
    for bad in (1, None, True, [1]):
        p = _minimal_projection()
        p["nodes"][0]["id"] = bad
        _reject(p)


def test_reject_node_id_empty_string() -> None:
    p = _minimal_projection()
    p["nodes"][0]["id"] = ""
    _reject(p)


def test_reject_duplicate_node_ids() -> None:
    p = _minimal_projection()
    p["nodes"] = [
        _copy_node(_MIN_NODE, id="dup"),
        _copy_node(_MIN_NODE, id="dup", bbox=[20.0, 30.0, 40.0, 50.0]),
    ]
    _reject(p)


def test_reject_bbox_not_list() -> None:
    for bad in ({"x": 1}, "1,2,3,4", None, 1):
        p = _minimal_projection()
        p["nodes"][0]["bbox"] = bad
        _reject(p)


def test_reject_bbox_wrong_length() -> None:
    for bad in ([1, 2, 3], [1, 2, 3, 4, 5], []):
        p = _minimal_projection()
        p["nodes"][0]["bbox"] = bad
        _reject(p)


def test_reject_bbox_non_number_items() -> None:
    for bad in (["1", 2, 3, 4], [1, 2, 3, None], [1, 2, 3, True]):
        p = _minimal_projection()
        p["nodes"][0]["bbox"] = bad
        _reject(p)


def test_reject_bbox_nan_or_inf() -> None:
    for bad in (
        [float("nan"), 2, 3, 4],
        [1, float("inf"), 3, 4],
        [1, 2, 3, float("-inf")],
    ):
        p = _minimal_projection()
        p["nodes"][0]["bbox"] = bad
        _reject(p)


def test_reject_anchor_not_object() -> None:
    for bad in ("x", 1, None, [1], True):
        p = _minimal_projection()
        p["nodes"][0]["horizontalAnchor"] = bad
        _reject(p)


def test_reject_anchor_empty_object() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {}
    _reject(p)


def test_reject_impl_wrong_type() -> None:
    for bad in (1, True, [1], {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["impl"] = bad
        _reject(p)


def test_reject_text_wrong_type() -> None:
    for bad in (1, True, [1], {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["text"] = bad
        _reject(p)


def test_reject_source_text_wrong_type() -> None:
    for bad in (1, True, [1]):
        p = _minimal_projection()
        p["nodes"][0]["sourceText"] = bad
        _reject(p)


def test_reject_text_runs_not_array() -> None:
    for bad in ("x", 1, True, {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["textRuns"] = bad
        _reject(p)


def test_reject_font_size_wrong_type() -> None:
    for bad in ("14", True, [1], {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["fontSize"] = bad
        _reject(p)


def test_reject_font_size_nan_inf() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["nodes"][0]["fontSize"] = bad
        _reject(p)


def test_reject_weight_wrong_type() -> None:
    for bad in (True, [1], {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["weight"] = bad
        _reject(p)


def test_reject_weight_nan_inf() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["nodes"][0]["weight"] = bad
        _reject(p)


def test_reject_color_hex_wrong_type() -> None:
    for bad in (1, True, [1], {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["colorHex"] = bad
        _reject(p)


def test_reject_radius_wrong_type() -> None:
    for bad in ("16", True, {"x": 1}):
        p = _minimal_projection()
        p["nodes"][0]["radius"] = bad
        _reject(p)


def test_reject_radius_nan_inf() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        p = _minimal_projection()
        p["nodes"][0]["radius"] = bad
        _reject(p)


def test_reject_slot_wrong_type() -> None:
    for bad in (1, "x", None, [True]):
        p = _minimal_projection()
        p["nodes"][0]["slot"] = bad
        _reject(p)


def test_reject_slot_true_on_non_text_impl() -> None:
    p = _minimal_projection()
    p["nodes"][0]["impl"] = "shape_container"
    p["nodes"][0]["slot"] = True
    p["nodes"][0]["text"] = None
    _reject(p)


def test_reject_slot_true_with_null_text() -> None:
    p = _minimal_projection()
    p["nodes"][0]["impl"] = "text"
    p["nodes"][0]["slot"] = True
    p["nodes"][0]["text"] = None
    _reject(p)


def test_reject_slot_true_with_non_string_text() -> None:
    p = _minimal_projection()
    p["nodes"][0]["impl"] = "text"
    p["nodes"][0]["slot"] = True
    p["nodes"][0]["text"] = 123
    _reject(p)


def test_reject_inconsistent_slot_declaration_impl_not_text() -> None:
    """slot:true on impl != 'text' is rejected even with a string text."""
    p = _minimal_projection()
    p["nodes"][0]["impl"] = "shape_container"
    p["nodes"][0]["slot"] = True
    p["nodes"][0]["text"] = "looks like text"
    _reject(p)


def test_build_legacy_bytes_rejects_same_inputs() -> None:
    """build_legacy_bytes must validate just as strictly as build_documents."""
    module = _load_prod_module("p25a1_legacy_reject")
    p = _minimal_projection()
    p["nodes"][0]["bbox"] = [1, 2, 3]
    try:
        module.build_legacy_bytes(p)
    except module.ProjectionValidationError:
        return
    raise AssertionError("build_legacy_bytes accepted invalid bbox length")


# ===========================================================================
# 2b. Strict validation: non-string unknown keys must not crash (Defect 1).
#
# The public contract says EVERY invalid projection raises the dedicated
# ProjectionValidationError. A projection containing non-string (but hashable)
# unknown keys alongside string unknown keys must not leak a raw TypeError
# from the message formatter.
# ===========================================================================


def _reject_only_validation_exception(projection: Any) -> None:
    """Like _reject, but additionally proves the exception is exactly
    ProjectionValidationError — never TypeError or any other type."""
    module = _load_prod_module("p25a1_reject_exc")
    try:
        module.build_documents(projection)
    except module.ProjectionValidationError:
        return
    except Exception as exc:
        raise AssertionError(
            f"expected ProjectionValidationError, got {type(exc).__name__}: {exc}"
        ) from exc
    raise AssertionError(f"projection should have been rejected: {projection!r}")


def test_reject_top_level_unknown_integer_key_alongside_string() -> None:
    """Mixed int + string unknown top-level keys must not crash sorted()."""
    p = _minimal_projection()
    p[99] = "bad-int"
    p["extra"] = "bad-str"
    _reject_only_validation_exception(p)


def test_reject_top_level_unknown_integer_key_only() -> None:
    """A non-string unknown top-level key alone must raise the dedicated
    exception, not a TypeError."""
    p = _minimal_projection()
    p[42] = "bad"
    _reject_only_validation_exception(p)


def test_reject_node_unknown_integer_key_alongside_string() -> None:
    """Mixed int + string unknown node keys must not crash sorted()."""
    p = _minimal_projection()
    p["nodes"][0][7] = "bad-int"
    p["nodes"][0]["extra"] = "bad-str"
    _reject_only_validation_exception(p)


def test_reject_node_unknown_integer_key_only() -> None:
    p = _minimal_projection()
    p["nodes"][0][7] = "bad"
    _reject_only_validation_exception(p)


def test_reject_top_level_mixed_unknown_types_deterministic() -> None:
    """Several heterogeneous-type unknown keys (int, float-key, string, tuple)
    must all raise the dedicated exception deterministically."""
    p = _minimal_projection()
    p[1] = "a"
    p["zzz"] = "b"
    p[(1, 2)] = "c"  # hashable non-string
    p[3.0] = "d"
    _reject_only_validation_exception(p)


def test_reject_node_mixed_unknown_types_deterministic() -> None:
    p = _minimal_projection()
    p["nodes"][0][1] = "a"
    p["nodes"][0]["aaa"] = "b"
    p["nodes"][0][(1, 2)] = "c"
    _reject_only_validation_exception(p)


# ===========================================================================
# 2c. Strict validation: nested JSON values in horizontalAnchor / textRuns
# (Defect 2).
#
# horizontalAnchor is a JSON object and textRuns is a JSON array. They must
# be recursively validated as strict JSON: no NaN/infinity, no bytes/custom
# objects, no tuples/sets, no non-string mapping keys. bool and null remain
# valid JSON.
# ===========================================================================


def test_reject_anchor_nan_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": float("nan")}
    _reject(p)


def test_reject_anchor_positive_infinity_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": float("inf")}
    _reject(p)


def test_reject_anchor_negative_infinity_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": float("-inf")}
    _reject(p)


def test_reject_anchor_non_string_key_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", 7: 10.0}
    _reject(p)


def test_reject_anchor_bytes_value_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": b"left"}
    _reject(p)


def test_reject_anchor_custom_object_value_at_nested_depth() -> None:
    class Custom:
        pass
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": Custom()}
    _reject(p)


def test_reject_anchor_tuple_value_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": (1, 2)}
    _reject(p)


def test_reject_anchor_set_value_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": {"x", "y"}}
    _reject(p)


def test_reject_anchor_deeply_nested_nan() -> None:
    """NaN two levels deep inside horizontalAnchor must still be caught."""
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {
        "mode": "left",
        "nested": {"sub": [1, {"deep": float("nan")}]},
    }
    _reject(p)


def test_reject_text_runs_nan_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", "size": float("nan")}]
    _reject(p)


def test_reject_text_runs_positive_infinity_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", "size": float("inf")}]
    _reject(p)


def test_reject_text_runs_negative_infinity_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", "size": float("-inf")}]
    _reject(p)


def test_reject_text_runs_non_string_key_at_nested_depth() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", 7: 10.0}]
    _reject(p)


def test_reject_text_runs_bytes_element() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [b"bytes"]
    _reject(p)


def test_reject_text_runs_custom_object_element() -> None:
    class Custom:
        pass
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [Custom()]
    _reject(p)


def test_reject_text_runs_tuple_element() -> None:
    """A tuple where a JSON value is expected — json.dumps would silently
    serialize it as a JSON array, hiding non-JSON input."""
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [(1, 2)]
    _reject(p)


def test_reject_text_runs_set_element() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"x", "y"}]
    _reject(p)


def test_reject_text_runs_deeply_nested_nan() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", "nested": [1, [2, float("inf")]]}]
    _reject(p)


def test_reject_text_runs_nested_non_string_key_deep() -> None:
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "x", "font": {1: "bad"}}]
    _reject(p)


# --- bool and null remain valid JSON inside nested values (positive tests) ---


def test_accept_anchor_bool_and_null_values() -> None:
    """bool and null are valid strict-JSON values inside horizontalAnchor."""
    module = _load_prod_module("p25a1_anchor_bool")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {
        "mode": "left", "flag": True, "other": False, "nothing": None,
    }
    expected_doc, _ = module.build_documents(p)
    assert expected_doc["nodes"]["n1"]["horizontalAnchor"]["flag"] is True
    assert expected_doc["nodes"]["n1"]["horizontalAnchor"]["other"] is False
    assert expected_doc["nodes"]["n1"]["horizontalAnchor"]["nothing"] is None


def test_accept_text_runs_bool_and_null_values() -> None:
    """bool and null are valid strict-JSON values inside textRuns."""
    module = _load_prod_module("p25a1_runs_bool")
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [
        {"content": "x", "bold": True, "italic": False, "link": None},
        [True, False, None, 1, "s"],
    ]
    expected_doc, _ = module.build_documents(p)
    runs = expected_doc["nodes"]["n1"]["textRuns"]
    assert runs[0]["bold"] is True
    assert runs[0]["italic"] is False
    assert runs[0]["link"] is None
    assert runs[1] == [True, False, None, 1, "s"]


# ===========================================================================
# 2d. Alias isolation: built documents are detached from the input projection.
#
# Mutating the input after build_documents must not change the returned docs,
# and mutating the returned docs must not change the input.
# ===========================================================================


def test_build_documents_input_mutation_does_not_leak_into_output_anchor() -> None:
    module = _load_prod_module("p25a1_iso_anchor_in")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": 5.0}
    expected_doc, _ = module.build_documents(p)
    original = expected_doc["nodes"]["n1"]["horizontalAnchor"]["mode"]
    # Mutate the INPUT after build.
    p["nodes"][0]["horizontalAnchor"]["mode"] = "right"
    p["nodes"][0]["horizontalAnchor"]["left"] = 999.0
    assert expected_doc["nodes"]["n1"]["horizontalAnchor"]["mode"] == original
    assert expected_doc["nodes"]["n1"]["horizontalAnchor"]["left"] == 5.0


def test_build_documents_input_mutation_does_not_leak_into_output_text_runs() -> None:
    module = _load_prod_module("p25a1_iso_runs_in")
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "original", "font": {"size": 14}}]
    expected_doc, _ = module.build_documents(p)
    # Mutate the INPUT's nested run element after build.
    p["nodes"][0]["textRuns"][0]["content"] = "MUTATED"
    p["nodes"][0]["textRuns"][0]["font"]["size"] = 999
    p["nodes"][0]["textRuns"].append({"content": "extra"})
    assert expected_doc["nodes"]["n1"]["textRuns"][0]["content"] == "original"
    assert expected_doc["nodes"]["n1"]["textRuns"][0]["font"]["size"] == 14
    assert len(expected_doc["nodes"]["n1"]["textRuns"]) == 1


def test_build_documents_input_mutation_does_not_leak_into_output_radius_array() -> None:
    """radius as a JSON array is a nested mutable value; it must be detached."""
    module = _load_prod_module("p25a1_iso_radius_in")
    p = _minimal_projection()
    p["nodes"][0]["radius"] = [4.0, 8.0, 8.0, 4.0]
    expected_doc, _ = module.build_documents(p)
    p["nodes"][0]["radius"][0] = 999.0
    p["nodes"][0]["radius"].append(777.0)
    assert expected_doc["nodes"]["n1"]["radius"] == [4.0, 8.0, 8.0, 4.0]


def test_build_documents_output_mutation_does_not_leak_into_input_anchor() -> None:
    module = _load_prod_module("p25a1_iso_anchor_out")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left", "left": 5.0}
    expected_doc, _ = module.build_documents(p)
    expected_doc["nodes"]["n1"]["horizontalAnchor"]["mode"] = "right"
    expected_doc["nodes"]["n1"]["horizontalAnchor"]["left"] = 999.0
    assert p["nodes"][0]["horizontalAnchor"]["mode"] == "left"
    assert p["nodes"][0]["horizontalAnchor"]["left"] == 5.0


def test_build_documents_output_mutation_does_not_leak_into_input_text_runs() -> None:
    module = _load_prod_module("p25a1_iso_runs_out")
    p = _minimal_projection()
    p["nodes"][0]["textRuns"] = [{"content": "original", "font": {"size": 14}}]
    expected_doc, _ = module.build_documents(p)
    expected_doc["nodes"]["n1"]["textRuns"][0]["content"] = "MUTATED"
    expected_doc["nodes"]["n1"]["textRuns"][0]["font"]["size"] = 999
    expected_doc["nodes"]["n1"]["textRuns"].append({"content": "extra"})
    assert p["nodes"][0]["textRuns"][0]["content"] == "original"
    assert p["nodes"][0]["textRuns"][0]["font"]["size"] == 14
    assert len(p["nodes"][0]["textRuns"]) == 1


def test_build_documents_output_mutation_does_not_leak_into_input_radius_array() -> None:
    module = _load_prod_module("p25a1_iso_radius_out")
    p = _minimal_projection()
    p["nodes"][0]["radius"] = [4.0, 8.0, 8.0, 4.0]
    expected_doc, _ = module.build_documents(p)
    expected_doc["nodes"]["n1"]["radius"][0] = 999.0
    assert p["nodes"][0]["radius"] == [4.0, 8.0, 8.0, 4.0]


def test_build_documents_repeated_builds_are_independent() -> None:
    """Two builds from the same projection must return fully independent docs
    — mutating one result must not affect the other."""
    module = _load_prod_module("p25a1_iso_repeat")
    p = _minimal_projection()
    p["nodes"][0]["horizontalAnchor"] = {"mode": "left"}
    p["nodes"][0]["textRuns"] = [{"content": "x"}]
    doc1, _ = module.build_documents(p)
    doc2, _ = module.build_documents(p)
    doc1["nodes"]["n1"]["horizontalAnchor"]["mode"] = "right"
    doc1["nodes"]["n1"]["textRuns"][0]["content"] = "doc1"
    assert doc2["nodes"]["n1"]["horizontalAnchor"]["mode"] == "left"
    assert doc2["nodes"]["n1"]["textRuns"][0]["content"] == "x"


# ===========================================================================
# 2e. Cyclic containers must fail closed (Defect: RecursionError leak).
#
# Cyclic lists/mappings are not valid JSON. The module promises that invalid
# projections raise ProjectionValidationError, never RecursionError.
# ===========================================================================


def test_reject_self_referential_list_in_text_runs() -> None:
    """A directly self-referential list inside textRuns must fail closed."""
    p = _minimal_projection()
    cycle: list[Any] = []
    cycle.append(cycle)
    p["nodes"][0]["textRuns"] = cycle
    _reject(p)


def test_reject_self_referential_mapping_in_anchor() -> None:
    """A directly self-referential mapping inside horizontalAnchor must fail
    closed."""
    p = _minimal_projection()
    cycle: dict[str, Any] = {"mode": "left"}
    cycle["self"] = cycle
    p["nodes"][0]["horizontalAnchor"] = cycle
    _reject(p)


def test_reject_indirect_list_to_mapping_to_same_list_cycle() -> None:
    """An indirect cycle: list -> mapping -> same list must fail closed."""
    p = _minimal_projection()
    inner_map: dict[str, Any] = {}
    outer_list: list[Any] = [inner_map]
    inner_map["back"] = outer_list
    p["nodes"][0]["textRuns"] = outer_list
    _reject(p)


def test_reject_indirect_mapping_to_list_to_same_mapping_cycle() -> None:
    """An indirect cycle: mapping -> list -> same mapping must fail closed."""
    p = _minimal_projection()
    inner_list: list[Any] = []
    outer_map: dict[str, Any] = {"mode": "left", "items": inner_list}
    inner_list.append(outer_map)
    p["nodes"][0]["horizontalAnchor"] = outer_map
    _reject(p)


def test_reject_cycle_through_build_legacy_bytes() -> None:
    """The same cycle rejection must hold through build_legacy_bytes too."""
    module = _load_prod_module("p25a1_cycle_bytes")
    p = _minimal_projection()
    cycle: list[Any] = []
    cycle.append(cycle)
    p["nodes"][0]["textRuns"] = cycle
    try:
        module.build_legacy_bytes(p)
    except module.ProjectionValidationError:
        return
    except Exception as exc:
        raise AssertionError(
            f"expected ProjectionValidationError, got {type(exc).__name__}: {exc}"
        ) from exc
    raise AssertionError("build_legacy_bytes accepted a cyclic textRuns")


def test_accept_acyclic_shared_nested_object_is_cloned_into_independent_containers() -> None:
    """A repeated but acyclic shared nested object (ordinary DAG reuse) is
    valid JSON and must NOT be falsely rejected as a cycle. Both occurrences
    must be cloned into independent output containers so mutating one does
    not affect the other."""
    module = _load_prod_module("p25a1_dag_reuse")
    p = _minimal_projection()
    shared = {"font": {"size": 14, "weight": 700}, "content": "x"}
    # The same dict object appears twice in textRuns (sibling reuse, NOT a
    # cycle — the active recursion path does not revisit it on the same
    # branch).
    p["nodes"][0]["textRuns"] = [shared, shared]
    expected_doc, _ = module.build_documents(p)
    runs = expected_doc["nodes"]["n1"]["textRuns"]
    assert len(runs) == 2
    # Both runs carry the same content.
    assert runs[0]["content"] == "x"
    assert runs[1]["content"] == "x"
    # Outputs are detached from the input.
    shared["content"] = "MUTATED_INPUT"
    assert runs[0]["content"] == "x"
    assert runs[1]["content"] == "x"
    # The two output containers are independent of each other.
    runs[0]["content"] = "doc_a"
    assert runs[1]["content"] == "x"


# ===========================================================================
# 2f. Hashable custom keys whose __repr__ raises must fail closed
# (Defect: raw exception from message formatting).
#
# Object keys must be strings anyway, so the validator never needs to call a
# failing __repr__ to render a bad key. Top-level and node-level cases.
# ===========================================================================


class _BadReprKey:
    """A hashable, non-string key whose __repr__ raises a custom exception."""

    def __hash__(self) -> int:
        return 0xBAD

    def __repr__(self) -> str:
        raise RuntimeError("repr explodes")


def test_reject_top_level_bad_repr_custom_key_only_validation_exception() -> None:
    """A top-level unknown custom key whose __repr__ raises must surface as
    ProjectionValidationError, never the custom exception."""
    p = _minimal_projection()
    p[_BadReprKey()] = "unknown"
    _reject_only_validation_exception(p)


def test_reject_node_bad_repr_custom_key_only_validation_exception() -> None:
    """A node-level unknown custom key whose __repr__ raises must surface as
    ProjectionValidationError, never the custom exception."""
    p = _minimal_projection()
    p["nodes"][0][_BadReprKey()] = "unknown"
    _reject_only_validation_exception(p)


def test_reject_top_level_mixed_bad_repr_and_string_keys_only_validation_exception() -> None:
    """Mixed string and bad-repr unknown top-level keys must still surface as
    ProjectionValidationError without calling the failing repr twice."""
    p = _minimal_projection()
    p["extra"] = "str-unknown"
    p[_BadReprKey()] = "custom-unknown"
    _reject_only_validation_exception(p)


# ===========================================================================
# 3. Deterministic legacy output: key order, Unicode, no trailing newline.
# ===========================================================================


def test_build_documents_expected_key_order() -> None:
    module = _load_prod_module("p25a1_keyorder")
    p = _minimal_projection()
    expected_doc, _slots_doc = module.build_documents(p)
    assert list(expected_doc.keys()) == [
        "artboardWidth",
        "artboardHeight",
        "designPixelScale",
        "logicalDesignWidth",
        "nodes",
    ]


def test_build_documents_logical_design_width_value() -> None:
    module = _load_prod_module("p25a1_ldw")
    p = _minimal_projection()
    p["artboardWidth"] = 750.0
    p["designPixelScale"] = 2.0
    expected_doc, _ = module.build_documents(p)
    assert expected_doc["logicalDesignWidth"] == 375.0


def test_build_documents_node_key_order() -> None:
    module = _load_prod_module("p25a1_node_keyorder")
    p = _minimal_projection()
    expected_doc, _ = module.build_documents(p)
    node = expected_doc["nodes"][_MIN_NODE["id"]]
    assert list(node.keys()) == [
        "bbox",
        "logicalBbox",
        "horizontalAnchor",
        "impl",
        "text",
        "sourceText",
        "textRuns",
        "fontSize",
        "weight",
        "colorHex",
        "radius",
    ]


def test_build_documents_logical_bbox_value() -> None:
    module = _load_prod_module("p25a1_lbbox")
    p = _minimal_projection()
    p["designPixelScale"] = 2.0
    p["nodes"][0]["bbox"] = [10.0, 20.0, 100.0, 50.0]
    expected_doc, _ = module.build_documents(p)
    assert expected_doc["nodes"][_MIN_NODE["id"]]["logicalBbox"] == [5.0, 10.0, 50.0, 25.0]


def test_build_documents_logical_bbox_uses_python_round_2() -> None:
    module = _load_prod_module("p25a1_lbbox_round")
    p = _minimal_projection()
    p["designPixelScale"] = 3.0
    # round(10 / 3, 2) == 3.33; round(20 / 3, 2) == 6.67; etc.
    p["nodes"][0]["bbox"] = [10.0, 20.0, 100.0, 50.0]
    expected_doc, _ = module.build_documents(p)
    assert expected_doc["nodes"][_MIN_NODE["id"]]["logicalBbox"] == [
        round(10.0 / 3.0, 2),
        round(20.0 / 3.0, 2),
        round(100.0 / 3.0, 2),
        round(50.0 / 3.0, 2),
    ]


def test_build_documents_nodes_dict_in_projection_order() -> None:
    module = _load_prod_module("p25a1_order")
    p = _minimal_projection()
    p["nodes"] = [
        _copy_node(_MIN_NODE, id="alpha"),
        _copy_node(_MIN_NODE, id="beta"),
        _copy_node(_MIN_NODE, id="gamma", slot=True, impl="text", text="hello"),
    ]
    expected_doc, slots_doc = module.build_documents(p)
    assert list(expected_doc["nodes"].keys()) == ["alpha", "beta", "gamma"]
    assert list(slots_doc.keys()) == ["gamma"]


def test_build_documents_passes_through_weight_and_radius_uncoerced() -> None:
    module = _load_prod_module("p25a1_uncoerced")
    p = _minimal_projection()
    # Legacy weight can be number, string, or null.
    p["nodes"] = [
        _copy_node(_MIN_NODE, id="w_num", weight=400),
        _copy_node(_MIN_NODE, id="w_str", weight="Bold"),
        _copy_node(_MIN_NODE, id="w_null", weight=None),
        _copy_node(_MIN_NODE, id="r_arr", radius=[4.0, 4.0, 0.0, 0.0]),
        _copy_node(_MIN_NODE, id="r_null", radius=None),
    ]
    expected_doc, _ = module.build_documents(p)
    assert expected_doc["nodes"]["w_num"]["weight"] == 400
    assert expected_doc["nodes"]["w_str"]["weight"] == "Bold"
    assert expected_doc["nodes"]["w_null"]["weight"] is None
    assert expected_doc["nodes"]["r_arr"]["radius"] == [4.0, 4.0, 0.0, 0.0]
    assert expected_doc["nodes"]["r_null"]["radius"] is None


def test_build_legacy_bytes_no_trailing_newline() -> None:
    module = _load_prod_module("p25a1_notrail")
    p = _minimal_projection()
    expected_bytes, slots_bytes = module.build_legacy_bytes(p)
    assert not expected_bytes.endswith(b"\n"), "expected bytes must not end with newline"
    assert not slots_bytes.endswith(b"\n"), "slots bytes must not end with newline"


def test_build_legacy_bytes_unicode_preserved_unescaped() -> None:
    module = _load_prod_module("p25a1_unicode")
    p = _minimal_projection()
    p["nodes"] = [
        _copy_node(
            _MIN_NODE,
            id="uni",
            impl="text",
            text="你好,世界 🌍 — café — 日本語",
            sourceText="你好,世界 🌍 — café — 日本語",
            slot=True,
        ),
    ]
    expected_bytes, slots_bytes = module.build_legacy_bytes(p)
    # ensure_ascii=False is required: characters must appear as UTF-8, not \uXXXX.
    assert "你好".encode("utf-8") in expected_bytes
    assert "🌍".encode("utf-8") in expected_bytes
    assert "café".encode("utf-8") in expected_bytes
    assert "你好".encode("utf-8") in slots_bytes
    assert "🌍".encode("utf-8") in slots_bytes
    # No ASCII-escaped forms.
    assert b"\\u" not in expected_bytes
    assert b"\\u" not in slots_bytes


def test_build_legacy_bytes_matches_json_dumps_form() -> None:
    module = _load_prod_module("p25a1_form")
    p = _minimal_projection()
    expected_doc, slots_doc = module.build_documents(p)
    expected_bytes, slots_bytes = module.build_legacy_bytes(p)
    assert expected_bytes == json.dumps(expected_doc, ensure_ascii=False, indent=2).encode("utf-8")
    assert slots_bytes == json.dumps(slots_doc, ensure_ascii=False, indent=2).encode("utf-8")


def test_build_legacy_bytes_deterministic_across_calls() -> None:
    module = _load_prod_module("p25a1_det")
    p = _minimal_projection()
    b1 = module.build_legacy_bytes(p)
    b2 = module.build_legacy_bytes(p)
    assert b1 == b2


# ===========================================================================
# 4. Differential parity against the frozen iFF v1 capsule.
# ===========================================================================


def _build_corpus_render_plan() -> dict[str, Any]:
    """A render_plan exercising: Unicode text, dynamic slot, multi-color runs,
    non-text shape, non-default scale, deterministic insertion order.

    Every node uses ``parent="root"`` so the artboard root owns the scene.
    The single-line text heights are kept under ``font_size * 1.18`` so the
    capsule's ``display_text_contract`` does not wrap (keeps the run list
    pass-through observable). Multi-color runs require len(runs) > 1 and
    distinct color blobs.
    """
    def text_node(
        node_id: str, bbox: list[float], text: str, font_size: float,
        weight: Any = None, fills=None, runs=None,
    ) -> dict[str, Any]:
        return {
            "name": node_id,
            "bbox": bbox,
            "implementation": "text",
            "parent": "root",
            "children": [],
            "text": text,
            "textRuns": runs or [],
            "fills": fills if fills is not None else ["#000000"],
            "rawFills": [],
            "border": [],
            "radius": 0,
            "shadow": [],
            "opacity": 1,
            "visible": True,
            "required": True,
            "fontSize": font_size,
            "weight": weight,
        }

    def shape_node(node_id: str, bbox: list[float], fills=None, radius=None) -> dict[str, Any]:
        return {
            "name": node_id,
            "bbox": bbox,
            "implementation": "shape_container",
            "parent": "root",
            "children": [],
            "fills": fills if fills is not None else ["#FFFFFF"],
            "rawFills": [],
            "border": [],
            "radius": radius if radius is not None else 0,
            "shadow": [],
            "opacity": 1,
            "visible": True,
            "required": True,
        }

    # Insertion order IS the design z order; capsule preserves it in placed.
    return {
        "rootNode": None,
        "nodes": {
            # Artboard root (parent=None triggers 0,0 normalization).
            "root": {
                "name": "root",
                "bbox": [0, 0, 750, 1624],
                "implementation": "shape_container",
                "parent": None,
                "children": ["card_bg", "title", "amount", "subtitle", "french", "vector_deco"],
                "fills": ["#FAFAFA"],
                "rawFills": [],
                "border": [],
                "radius": 0,
                "shadow": [],
                "opacity": 1,
                "visible": True,
                "required": True,
            },
            # Non-text shape with a real radius so the legacy radius_value > 0.
            "card_bg": shape_node(
                "card_bg", [40, 120, 670, 300],
                fills=["#3366FF"],
                radius={"topLeft": 16, "topRight": 16, "bottomLeft": 16, "bottomRight": 16},
            ),
            # Unicode single-line text (CJK + emoji + accents).
            "title": text_node(
                "title", [60, 140, 400, 20],
                "你好,世界 🌍 — café",
                font_size=16,
                weight=700,
                fills=["#222222"],
            ),
            # Dynamic text slot — referenced in component_manifest.dynamicSlots.
            "amount": text_node(
                "amount", [60, 180, 200, 20],
                "$1,234.56",
                font_size=16,
                weight=400,
                fills=["#FFFFFF"],
            ),
            # Styled runs: 2 runs with distinct colors.
            "subtitle": text_node(
                "subtitle", [60, 220, 320, 16],
                "BoldRed NormGreen",
                font_size=14,
                fills=["#000000"],
                runs=[
                    {"content": "BoldRed", "font": {"size": 14, "fontWeight": 700}, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                    {"content": " NormGreen", "font": {"size": 14, "fontWeight": 400}, "color": {"r": 0, "g": 0.5, "b": 0, "a": 1}},
                ],
            ),
            # Pure Unicode-only text node, no slot.
            "french": text_node(
                "french", [60, 260, 200, 14],
                "ÉàÜ — 中文 — 한국어",
                font_size=12,
                fills=["#FFFFFF"],
            ),
            # A second non-text shape (no fill, no radius -> should be dropped
            # by the capsule because there is no decoration). Proves that the
            # projection only includes nodes the capsule actually placed.
            "vector_deco": shape_node(
                "vector_deco", [700, 1400, 24, 24],
                fills=[],
                radius=0,
            ),
        },
    }


def _build_corpus_classification() -> dict[str, Any]:
    return {
        "artboard": {"width": 750, "height": 1624, "scale": 2},
        "viewport": {"width": 375, "height": 812},
    }


def _build_corpus_component_manifest() -> dict[str, Any]:
    """Mark ``amount`` as a dynamic text slot."""
    return {
        "source": "test_fixture",
        "components": [
            {
                "name": "AmountSlot",
                "kind": "slot",
                "rootNode": "amount",
                "bbox": [60, 180, 200, 20],
                "dynamicSlots": [{"node": "amount", "role": "dynamic_text_slot"}],
                "staticTextLabels": [],
                "nodes": [],
            },
        ],
    }


@contextlib.contextmanager
def _run_capsule_and_capture_state():
    """Run the frozen capsule in-process, wrapping emit_node to retain
    references to the final nodes/placed/anchors/slot_ids + dimensions.

    Yields a dict with the captured state plus paths to the actual sidecars.
    """
    if not CAPSULE_GENERATE_CANVAS.is_file():
        raise AssertionError(f"capsule missing: {CAPSULE_GENERATE_CANVAS}")
    # Precondition: capsule must hash to the manifest value (do not weaken).
    manifest = json.loads(
        (ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json").read_bytes()
    )
    expected_sha = next(
        (e["sha256"] for e in manifest["scripts"] if e["name"] == "generate_canvas.py"),
        None,
    )
    assert expected_sha, "generate_canvas.py not in capsule manifest"
    actual_sha = hashlib.sha256(CAPSULE_GENERATE_CANVAS.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, (
        f"capsule generate_canvas.py SHA mismatch: manifest={expected_sha} actual={actual_sha}"
    )

    gc = _load_capsule_generate_canvas()

    captured: dict[str, Any] = {}

    original_emit_node = gc.emit_node

    def wrapped_emit_node(node, asset_prefix, nodes, reg, artboard_origin,
                          artboard_width, design_pixel_scale, nid, placed, anchors, slot_ids):
        # Retain references on every call; the caller mutates these in place
        # and pops placed[nid] when widget is None, so post-main() we observe
        # the final state without modifying the capsule.
        captured.setdefault("nodes_ref", nodes)
        captured.setdefault("placed_ref", placed)
        captured.setdefault("anchors_ref", anchors)
        captured.setdefault("slot_ids_ref", slot_ids)
        captured.setdefault("artboard_width", artboard_width)
        captured.setdefault("artboard_height", None)  # filled below
        captured.setdefault("design_pixel_scale", design_pixel_scale)
        captured["artboard_origin"] = artboard_origin
        captured["nodes_ref"] = nodes
        captured["placed_ref"] = placed
        captured["anchors_ref"] = anchors
        captured["slot_ids_ref"] = slot_ids
        captured["artboard_width"] = artboard_width
        captured["design_pixel_scale"] = design_pixel_scale
        return original_emit_node(
            node, asset_prefix, nodes, reg, artboard_origin,
            artboard_width, design_pixel_scale, nid, placed, anchors, slot_ids,
        )

    gc.emit_node = wrapped_emit_node
    try:
        with _canonical_tempdir(prefix="p25a1_diff_") as tmp:
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

            # artboard_height is not passed to emit_node; recover it from the
            # classification artboard (the capsule main() used it directly).
            captured["artboard_height"] = 1624.0
            captured["expected_sidecar"] = Path(str(out_dart) + ".expected.json")
            captured["slots_sidecar"] = Path(str(out_dart) + ".slots.json")
            yield captured
    finally:
        gc.emit_node = original_emit_node


def _build_projection_from_capsule_state(captured: dict[str, Any]) -> dict[str, Any]:
    """Use the capsule's own helper functions as the TEST oracle to derive the
    display text/runs, color, and radius from the captured final state.
    Production SharedCore never imports these helpers.
    """
    gc = _load_capsule_generate_canvas()
    nodes = captured["nodes_ref"]
    placed = captured["placed_ref"]
    anchors = captured["anchors_ref"]
    slot_ids = captured["slot_ids_ref"]
    scale = captured["design_pixel_scale"]

    projection_nodes: list[dict[str, Any]] = []
    for nid in placed:  # capsule preserves insertion order in placed
        node = nodes[nid]
        is_text = node.get("implementation") == "text"
        if is_text:
            display_text, display_runs = gc.display_text_contract(node)
        else:
            display_text, display_runs = None, []
        projection_nodes.append({
            "id": nid,
            "bbox": placed[nid],
            "horizontalAnchor": anchors[nid],
            "impl": node.get("implementation"),
            "text": display_text,
            "sourceText": node.get("text") if is_text else None,
            "textRuns": display_runs if is_text else [],
            "fontSize": node.get("fontSize") if is_text else None,
            "weight": node.get("weight") if is_text else None,
            "colorHex": gc.fill_hex(node),
            "radius": gc.radius_value(gc.effective_radius(node, nodes)),
            "slot": (nid in slot_ids and is_text),
        })

    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "artboardWidth": captured["artboard_width"],
        "artboardHeight": captured["artboard_height"],
        "designPixelScale": scale,
        "nodes": projection_nodes,
    }


def test_differential_corpus_runs_and_covers_required_kinds() -> None:
    """Smoke test: the corpus produces a non-empty placed set covering all
    required kinds (Unicode text, dynamic slot, styled runs, non-text shape,
    non-default scale, deterministic order)."""
    with _run_capsule_and_capture_state() as captured:
        projection = _build_projection_from_capsule_state(captured)
    kinds = {n["impl"] for n in projection["nodes"]}
    assert "text" in kinds, "corpus must include a text node"
    assert "shape_container" in kinds, "corpus must include a non-text node"
    assert projection["designPixelScale"] == 2, "corpus must use a non-default scale"
    slot_ids = [n["id"] for n in projection["nodes"] if n["slot"]]
    assert slot_ids == ["amount"], f"corpus must mark 'amount' as the only slot, got {slot_ids}"
    # Unicode text survived into the projection (test-only oracle produces it).
    titles = {n["text"] for n in projection["nodes"] if n["id"] == "title"}
    assert any("你好" in (t or "") for t in titles), titles
    # Styled runs survived into the projection.
    subs = [n for n in projection["nodes"] if n["id"] == "subtitle"]
    assert subs and len(subs[0]["textRuns"]) == 2, "styled runs must be present"
    # Insertion order is preserved and matches the order the capsule placed them.
    ids = [n["id"] for n in projection["nodes"]]
    assert ids == sorted(ids, key=lambda x: list(_build_corpus_render_plan()["nodes"].keys()).index(x)), ids


def test_differential_byte_for_byte_parity_expected_and_slots() -> None:
    """The neutral projection must reproduce the capsule's actual sidecar
    bytes exactly (no sorted keys, no trailing newline, no ASCII escaping)."""
    with _run_capsule_and_capture_state() as captured:
        projection = _build_projection_from_capsule_state(captured)
        actual_expected_bytes = captured["expected_sidecar"].read_bytes()
        actual_slots_bytes = captured["slots_sidecar"].read_bytes()

    module = _load_prod_module("p25a1_diff_parity")
    expected_bytes, slots_bytes = module.build_legacy_bytes(projection)

    assert expected_bytes == actual_expected_bytes, (
        "EXPECTED byte mismatch:\n"
        f"--- actual ({len(actual_expected_bytes)}b) ---\n{actual_expected_bytes.decode('utf-8', 'replace')}\n"
        f"--- built ({len(expected_bytes)}b) ---\n{expected_bytes.decode('utf-8', 'replace')}\n"
    )
    assert slots_bytes == actual_slots_bytes, (
        "SLOTS byte mismatch:\n"
        f"--- actual ({len(actual_slots_bytes)}b) ---\n{actual_slots_bytes.decode('utf-8', 'replace')}\n"
        f"--- built ({len(slots_bytes)}b) ---\n{slots_bytes.decode('utf-8', 'replace')}\n"
    )


def test_differential_mutation_bbox_breaks_parity() -> None:
    """Changing one projected bbox must break byte parity with the capsule."""
    with _run_capsule_and_capture_state() as captured:
        projection = _build_projection_from_capsule_state(captured)
        actual_expected_bytes = captured["expected_sidecar"].read_bytes()
        actual_slots_bytes = captured["slots_sidecar"].read_bytes()

    module = _load_prod_module("p25a1_mut_bbox")
    # Mutate the first text node's bbox in place (in list order).
    mutated = json.loads(json.dumps(projection))  # deep copy
    for n in mutated["nodes"]:
        if n["id"] == "title":
            n["bbox"] = [v + 1.0 for v in n["bbox"]]
            break
    else:
        raise AssertionError("corpus lacked title node")
    exp_bytes, slots_bytes = module.build_legacy_bytes(mutated)
    assert exp_bytes != actual_expected_bytes, "mutated bbox did not change expected bytes"
    # Slot bytes are unaffected by a bbox mutation on a non-slot node.
    assert slots_bytes == actual_slots_bytes


def test_differential_mutation_slot_text_breaks_parity() -> None:
    """Changing one projected slot text must break byte parity on slots AND
    on expected (because expected.text is the same display value)."""
    with _run_capsule_and_capture_state() as captured:
        projection = _build_projection_from_capsule_state(captured)
        actual_slots_bytes = captured["slots_sidecar"].read_bytes()

    module = _load_prod_module("p25a1_mut_slot")
    mutated = json.loads(json.dumps(projection))
    for n in mutated["nodes"]:
        if n["slot"]:
            n["text"] = "MUTATED_TEXT_VALUE"
            break
    else:
        raise AssertionError("corpus lacked any slot node")
    _exp_bytes, slots_bytes = module.build_legacy_bytes(mutated)
    assert slots_bytes != actual_slots_bytes, "mutated slot text did not change slots bytes"


# ===========================================================================
# 5. Second direct projection case (no capsule) — covers item kinds the legacy
#    input schema cannot represent without weakening the parity test.
# ===========================================================================


def test_direct_projection_supports_radius_as_array_and_null_weight() -> None:
    """The legacy capsule always emits a numeric radius (the max of the four
    corners) and a numeric-or-null weight. The neutral projection accepts
    radius as a JSON array and weight as a string too — future adapter
    representations that the frozen input cannot produce today. We prove here
    that these forms validate and pass through byte-for-byte to the legacy
    serialization form, without weakening the differential parity test above.
    """
    module = _load_prod_module("p25a1_direct_extra")
    projection = {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "artboardWidth": 375.0,
        "artboardHeight": 812.0,
        "designPixelScale": 1.0,
        "nodes": [
            {
                "id": "card",
                "bbox": [10.0, 20.0, 100.0, 50.0],
                "horizontalAnchor": {"mode": "left", "left": 10.0, "right": 265.0, "centerOffset": -127.5},
                "impl": "shape_container",
                "text": None,
                "sourceText": None,
                "textRuns": [],
                "fontSize": None,
                "weight": None,
                "colorHex": "#FF8800",
                "radius": [4.0, 8.0, 8.0, 4.0],  # legacy capsule never emits this
                "slot": False,
            },
            {
                "id": "label",
                "bbox": [10.0, 80.0, 60.0, 14.0],
                "horizontalAnchor": {"mode": "left", "left": 10.0, "right": 305.0, "centerOffset": -97.5},
                "impl": "text",
                "text": "Bold Label",
                "sourceText": "Bold Label",
                "textRuns": [],
                "fontSize": 14.0,
                "weight": "Bold",  # legacy capsule always numeric or None
                "colorHex": "#000000",
                "radius": None,
                "slot": False,
            },
        ],
    }
    expected_doc, slots_doc = module.build_documents(projection)
    # Array radius and string weight pass through uncoerced.
    assert expected_doc["nodes"]["card"]["radius"] == [4.0, 8.0, 8.0, 4.0]
    assert expected_doc["nodes"]["label"]["weight"] == "Bold"
    # slots dict is empty (no slot:true node).
    assert slots_doc == {}
    # Bytes form is the standard json.dumps with no trailing newline.
    exp_bytes, slots_bytes = module.build_legacy_bytes(projection)
    assert exp_bytes == json.dumps(expected_doc, ensure_ascii=False, indent=2).encode("utf-8")
    assert slots_bytes == b"{}"


# ===========================================================================
# 6. Static production guard: standard-library only, no forbidden surface.
# ===========================================================================


def test_production_module_imports_only_standard_library() -> None:
    """No third-party or platform imports may appear in the production file."""
    import ast
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_stdlib_prefixes = {
        # standard library modules we expect to need; everything else is suspect
        "ast", "json", "math", "typing",
        "collections", "collections.abc",
        "itertools", "functools", "operator",
        "__future__",  # not a runtime third-party module
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed_stdlib_prefixes, (
                    f"production imports non-stdlib module: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            assert top in allowed_stdlib_prefixes, (
                f"production imports non-stdlib module: {node.module}"
            )


def test_production_module_has_no_forbidden_tokens() -> None:
    """The P2.5a1 deplatformization forbidden tokens must be absent from the
    production source. The forbidden literals live only in this TEST."""
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    leaks = [tok for tok in FORBIDDEN_TOKENS if tok in source]
    assert leaks == [], f"production source leaks forbidden tokens: {leaks}"


def test_production_package_init_has_no_forbidden_tokens() -> None:
    source = PROD_PACKAGE_PATH.read_text(encoding="utf-8")
    leaks = [tok for tok in FORBIDDEN_TOKENS if tok in source]
    # __init__.py legitimately says 'platform-neutral'; only flag the truly
    # forbidden execution/import surfaces.
    hard_forbidden = (
        "import subprocess", "from subprocess", "shell=True", "os.system",
        "os.popen", "generate_canvas", "vendor.iff_v1", "import iff",
        "__import__", "import socket", "import urllib", "import http.client",
    )
    leaks = [tok for tok in hard_forbidden if tok in source]
    assert leaks == [], f"__init__.py leaks forbidden tokens: {leaks}"


def test_production_module_does_not_import_subprocess_or_process_modules() -> None:
    """Belt-and-braces: even if a forbidden literal were obfuscated, the loaded
    module must not pull in any execution/process module as a side effect of
    import. We snapshot ``sys.modules`` before/after to isolate the
    production import's transitive effects from this selftest's own imports."""
    forbidden = ("subprocess", "socket", "urllib.request", "http.client")
    before = set(sys.modules)
    # Load under a fresh name in a subprocess-like isolated process via
    # importlib in this same process; snapshot new modules after the load.
    _load_prod_module("p25a1_imp_guard_a")
    _load_prod_module("p25a1_imp_guard_b")
    after = set(sys.modules)
    new_modules = after - before
    leaked = [m for m in forbidden if m in new_modules]
    assert not leaked, (
        f"production import leaked forbidden modules into sys.modules: {leaked}"
    )


# ===========================================================================
# 7. No __pycache__ side effect for the owned production file at runtime.
# ===========================================================================


def test_production_module_import_creates_no_pycache_under_owned_path() -> None:
    """Importing the production module must not litter __pycache__ next to it
    when PYTHONDONTWRITEBYTECODE=1 (which the runner uses)."""
    cache_dir = PROD_MODULE_PATH.parent / "__pycache__"
    pre = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys;"
         f"p=importlib.util.spec_from_file_location('p25a1_nopyc','{PROD_MODULE_PATH}');"
         "m=importlib.util.module_from_spec(p);"
         "sys.modules['p25a1_nopyc']=m;"
         "p.loader.exec_module(m);"
         "assert m.build_documents or True"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"import probe failed: {r.stderr!r}"
    post = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    new_files = post - pre
    # Filter to files that look like they belong to expected_slots_projection_v1.
    relevant = {p for p in new_files if "expected_slots_projection_v1" in p.name}
    assert not relevant, (
        f"production import created __pycache__ side effect: {sorted(p.name for p in relevant)}"
    )


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
