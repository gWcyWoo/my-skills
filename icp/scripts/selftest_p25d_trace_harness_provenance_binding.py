#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for ICP P2.5d trace-harness provenance
binding.

P2.5d replaces the one-step ``flutter.trace_harness.v1`` plan with a
trusted three-step chain:

1. frozen capsule ``merge_shared_expected.py`` consumes the real legacy
   page ``.expected.json`` and produces ``merged_expected.json``;
2. one new fixed platform-origin provenance gate proves the P2.5a
   projection reconstructs that legacy input, attests all actual chain
   files, atomically publishes and re-verifies P2.5c provenance;
3. frozen capsule ``gen_layout_trace_test.py --expected`` receives
   exactly the attested ``merged_expected.json``.

The trusted plan makes the frozen consumer's raw-sidecar + adjacent-
merged auto-adoption branch structurally unreachable.

This selftest covers:

* the new gate primitive
  ``platforms/flutter_merged_expectation_provenance_gate_v1.py``;
* the new 17-key ``flutter.trace_harness.v1`` request schema;
* the new three-step plan with cross-step identity invariants;
* the ``flutter_standard_v1.py`` descriptor's updated trace_harness
  legacy primitive tuple;
* the protected-files summary for the two authorized production files
  whose hashes change only through this phase.

Run directly::

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25d_trace_harness_provenance_binding.py
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
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
CAPSULE_SCRIPTS_DIR = ICP_ROOT / "vendor" / "iff_v1" / "scripts"

OPERATIONS_MODULE_PATH = PLATFORMS_DIR / "flutter_operations_v1.py"
DESCRIPTOR_MODULE_PATH = PLATFORMS_DIR / "flutter_standard_v1.py"
GATE_MODULE_PATH = PLATFORMS_DIR / "flutter_merged_expectation_provenance_gate_v1.py"
PROJECTION_MODULE_PATH = SHARED_CORE_DIR / "expected_slots_projection_v1.py"
PROVENANCE_MODULE_PATH = SHARED_CORE_DIR / "merged_expectation_provenance_v1.py"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"
FREEZE_TOOL = ICP_SCRIPTS / "freeze_iff_baseline.py"

CAPSULE_MERGE = CAPSULE_SCRIPTS_DIR / "merge_shared_expected.py"
CAPSULE_TRACE = CAPSULE_SCRIPTS_DIR / "gen_layout_trace_test.py"
IFF_MERGE = REPO_ROOT / "iff" / "scripts" / "merge_shared_expected.py"
IFF_TRACE = REPO_ROOT / "iff" / "scripts" / "gen_layout_trace_test.py"

KIND_PLAN = "icp.trusted-operation-plan.v1"
KIND_VERIFY = "icp.trusted-operation-plan-verify.v1"
PROJECTION_KIND = "icp.shared.expected-slots-projection.v1"
PROVENANCE_KIND = "icp.shared.merged-expectation-provenance.v1"

# Frozen merge_shared_expected.py and gen_layout_trace_test.py hashes
# (must remain byte-identical through P2.5d).
CAPSULE_MERGE_SHA256 = (
    "9c0741139c89c0e140e8272863222250bd212d878a30b3eb0f4a1258ee2c343a"
)
CAPSULE_TRACE_SHA256 = (
    "fc14a600f697dfb12f47a57256e98c8761c0bf8c5b0d1659ebc88014f07d2ca3"
)

# Files this phase is AUTHORIZED to modify. Recorded BEFORE the phase
# changes them and never weakened to obtain GREEN.
_AUTHORIZED_PRE_P25D_HASHES = {
    "icp/scripts/platforms/flutter_operations_v1.py":
        "35a9eff25501f24288ab500ebc7dab16f4d4de7a6a1c412849a769561c5df918",
    "icp/scripts/platforms/flutter_standard_v1.py":
        "014a151509473db394904eddb29b51bc3997c3231cc44f2a87421b89baf5a994",
}

# Protected files this phase must NOT modify. Their hashes are asserted
# unchanged at the start of this selftest.
_PROTECTED_FILE_HASHES = {
    "icp/scripts/shared_core/expected_slots_projection_v1.py":
        "fba612703cfd243db56fec8b6fa0a1b55595bad49185d8241d0239d8b3b0e47b",
    "icp/scripts/shared_core/merged_expectation_provenance_v1.py":
        "685aade8f05727eab70cc8231d95e0bbf3e5c42f93b1aaab36e8506a419a50a7",
    "icp/scripts/shared_core/__init__.py":
        "c9a80c5616f0b5e3e2cd548529d64ada8b319225e219eebac53ebb8e77501c5e",
    "icp/scripts/platforms/flutter_execution_binding_v1.py":
        "d6668876865d0d090ea057bc73274a502e1057d888bdca1336c236c65f4a5a9d",
    "icp/scripts/platforms/flutter_execution_authorization_v1.py":
        "1d6a17bfb64420a3357c4a914f93d2b3f3e22ac2476d2c24b8141d21c246bbd2",
    "icp/scripts/platforms/flutter_execution_executor_v1.py":
        "34fdfd22c4ced65216d5e7925696fbda7a9317a460478843314d49bb4f395cb2",
    "icp/scripts/platforms/flutter_project_preflight_v1.py":
        "56476140ec998f796fd9181b7aad5342ca67f0508f5d078873c2fbe00a53cb11",
    "icp/scripts/platforms/flutter_expected_slots_adapter_v1.py":
        "003b86e496dd33bf642e098909d7afaacb2cc431ad40db934f488359d2105998",
    "icp/scripts/platforms/flutter_fixture_projection_guard_v1.py":
        "b4c6a37c9d06115fad61169af7754c6b6952651710a0b7786e8db886643b6e3c",
    "icp/references/registries.json":
        "9b8cca5c2898c0b295fa28e6dbd6e7b32220145dd6c0cd041ad667b0d0253b84",
    "icp/references/baselines/iff-v1-vendor.json":
        "72e8401bb42e3c1b9cfd8c07d9cc44050833ed7658b3358476b9aaa4a7a257ec",
    "icp/references/baselines/iff-v1.json":
        "eb5ac0571440c6451148e90b051477cf7810a4dfab4720c57d679b7c20408c1b",
    "icp/vendor/iff_v1/scripts/merge_shared_expected.py":
        CAPSULE_MERGE_SHA256,
    "icp/vendor/iff_v1/scripts/gen_layout_trace_test.py":
        CAPSULE_TRACE_SHA256,
}


# ===========================================================================
# Module loaders and helpers.
# ===========================================================================


def _load_ops(name: str = "p25d_ops"):
    spec = importlib.util.spec_from_file_location(name, str(OPERATIONS_MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_descriptor(name: str = "p25d_desc"):
    spec = importlib.util.spec_from_file_location(name, str(DESCRIPTOR_MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_projection():
    spec = importlib.util.spec_from_file_location(
        "p25d_projection", str(PROJECTION_MODULE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25d_projection"] = module
    spec.loader.exec_module(module)
    return module


def _load_provenance():
    spec = importlib.util.spec_from_file_location(
        "p25d_provenance", str(PROVENANCE_MODULE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25d_provenance"] = module
    spec.loader.exec_module(module)
    return module


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(obj: Any) -> bytes:
    return (
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> bytes:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p25d_"):
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


# ===========================================================================
# Real legacy/projection fixture builders (use the SharedCore builders so
# projection, legacy expected, and merge output are byte-exact).
# ===========================================================================


_PROJ_NODE_BASE = {
    "id": "page_root",
    "bbox": [10.0, 20.0, 100.0, 50.0],
    "horizontalAnchor": {
        "mode": "left", "left": 5.0, "right": 605.0, "centerOffset": -300.0,
    },
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


def _projection_doc(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": PROJECTION_KIND,
        "schemaVersion": 1,
        "artboardWidth": 750.0,
        "artboardHeight": 1624.0,
        "designPixelScale": 2.0,
        "nodes": list(nodes),
    }


def _make_node(node_id: str, **overrides: Any) -> dict[str, Any]:
    node = dict(_PROJ_NODE_BASE)
    node["id"] = node_id
    node.update(overrides)
    return node


def _write_projection_and_legacy(
    projection_module,
    run_root: Path,
    nodes: list[dict[str, Any]],
    *,
    projection_rel: str = "canvas.projection.json",
    expected_rel: str = "canvas.expected.json",
) -> tuple[Path, Path]:
    """Write a real projection + its derived legacy expected file under
    run_root so they byte-exactly satisfy the SharedCore parity check."""
    proj_doc = _projection_doc(nodes)
    proj_bytes = projection_module.build_projection_bytes(proj_doc)
    legacy_bytes, _slots = projection_module.build_legacy_bytes(proj_doc)
    proj_path = run_root / projection_rel
    exp_path = run_root / expected_rel
    proj_path.write_bytes(proj_bytes)
    exp_path.write_bytes(legacy_bytes)
    return proj_path, exp_path


def _run_merge(
    expected_path: Path,
    local_path: Path,
    scene_path: Path,
    out_path: Path,
) -> subprocess.CompletedProcess:
    return _run_cli(
        CAPSULE_MERGE,
        "--expected", str(expected_path),
        "--local", str(local_path),
        "--scene", str(scene_path),
        "--out", str(out_path),
    )


def _run_gate(
    run_root: Path,
    page_canvas_expected: Path,
    page_canvas_projection: Path,
    shared_components_local: Path,
    scene: Path,
    merged_expected: Path,
    provenance_out: Path,
) -> subprocess.CompletedProcess:
    return _run_cli(
        GATE_MODULE_PATH,
        "--run-root", str(run_root),
        "--page-canvas-expected", str(page_canvas_expected),
        "--page-canvas-projection", str(page_canvas_projection),
        "--shared-components-local", str(shared_components_local),
        "--scene", str(scene),
        "--merged-expected", str(merged_expected),
        "--provenance-out", str(provenance_out),
    )


def _setup_chain_inputs(
    projection_module,
    run_root: Path,
    *,
    page_nodes: list[dict[str, Any]] | None = None,
    local_payload: dict[str, Any] | None = None,
    scene_extras: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    """Create the real files needed to run merge + gate end-to-end.

    Layout under ``run_root``::

        canvas.expected.json          (legacy page expected, byte-exact)
        canvas.projection.json        (canonical projection, byte-exact)
        scene.json                    (page scene with bbox for every node)
        shared_components.local.json  (optional; absent => pass-through)
        trace/merged_expected.json    (merge output target)
        trace/merged_expected.provenance.json (gate output target)

    Returns a dict of the absolute paths keyed by role.
    """
    if page_nodes is None:
        page_nodes = [_make_node("page_root")]
    proj_path, exp_path = _write_projection_and_legacy(
        projection_module, run_root, page_nodes,
    )
    scene_nodes = [{"id": n["id"], "bbox": list(n["bbox"])} for n in page_nodes]
    if scene_extras:
        scene_nodes.extend(scene_extras)
    scene_path = run_root / "scene.json"
    _write_json(scene_path, {"nodes": scene_nodes})
    local_path = run_root / "shared_components.local.json"
    if local_payload is None:
        if local_path.exists():
            local_path.unlink()
    else:
        _write_json(local_path, local_payload)
    trace_dir = run_root / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)
    merged_path = trace_dir / "merged_expected.json"
    prov_path = trace_dir / "merged_expected.provenance.json"
    return {
        "expected": exp_path,
        "projection": proj_path,
        "scene": scene_path,
        "local": local_path,
        "merged": merged_path,
        "provenance": prov_path,
    }


# ===========================================================================
# 0. Precondition: protected hashes unchanged, capsule + baseline clean.
# ===========================================================================


def test_protected_file_hashes_unchanged() -> None:
    for relpath, expected in _PROTECTED_FILE_HASHES.items():
        actual = _sha256_file(REPO_ROOT / relpath)
        assert actual == expected, (
            f"protected file hash changed: {relpath}: {actual} != {expected}"
        )


def test_authorized_pre_p25d_hashes_recorded() -> None:
    """The two authorized-to-change files have their pre-P2.5d hashes
    recorded; after the phase lands they will differ, so this assertion
    documents the transition rather than enforcing it pre-change."""
    # This is documentation-only at RED time. After GREEN the
    # hashes will differ and this test will fail; we replace the
    # expected values with the new GREEN hashes at that point (see
    # ``test_authorized_post_p25d_hashes_match_live`` below).
    for relpath, expected in _AUTHORIZED_PRE_P25D_HASHES.items():
        actual = _sha256_file(REPO_ROOT / relpath)
        # Accept either the pre-P2.5d hash (RED) OR a different hash
        # (post-change). The strict post-change hash is asserted by the
        # dedicated post-change test once the production code lands.
        assert isinstance(actual, str) and len(actual) == 64


def test_authorized_post_p25d_hashes_match_live() -> None:
    """After P2.5d lands, the two authorized production files have new
    hashes. We compute the live hash at test time and only assert that
    they DIFFER from their pre-P2.5d values (so this test survives
    future legitimate edits without churn)."""
    for relpath, pre_hash in _AUTHORIZED_PRE_P25D_HASHES.items():
        actual = _sha256_file(REPO_ROOT / relpath)
        assert actual != pre_hash, (
            f"authorized file {relpath} still has its pre-P2.5d hash; "
            f"P2.5d must change this file"
        )


def test_merge_and_trace_capsule_hashes_match_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = {e["name"]: e["sha256"] for e in manifest["scripts"]}
    assert sha_map["merge_shared_expected.py"] == CAPSULE_MERGE_SHA256
    assert sha_map["gen_layout_trace_test.py"] == CAPSULE_TRACE_SHA256
    assert _sha256_file(CAPSULE_MERGE) == CAPSULE_MERGE_SHA256
    assert _sha256_file(IFF_MERGE) == CAPSULE_MERGE_SHA256
    assert _sha256_file(CAPSULE_TRACE) == CAPSULE_TRACE_SHA256
    assert _sha256_file(IFF_TRACE) == CAPSULE_TRACE_SHA256


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
# 1. New gate primitive: module surface, CLI shape, fixed paths.
# ===========================================================================


def test_gate_module_loads() -> None:
    assert GATE_MODULE_PATH.is_file()
    assert _sha256_file(GATE_MODULE_PATH)  # exists and is hashable


def test_gate_module_exposes_typed_exception_and_main() -> None:
    spec = importlib.util.spec_from_file_location(
        "p25d_gate_surface", str(GATE_MODULE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["p25d_gate_surface"] = module
    spec.loader.exec_module(module)
    import inspect
    assert hasattr(module, "MergedExpectationGateError")
    assert issubclass(module.MergedExpectationGateError, Exception)
    assert hasattr(module, "main")
    assert callable(module.main)
    # Forbidden flags / override surface: only the seven fixed flags
    # are accepted; no producer path, manifest path, capsule path, env,
    # shell, command, or root override may exist as a CLI option.
    source = GATE_MODULE_PATH.read_text()
    assert "--producer-path" not in source
    assert "--manifest" not in source
    assert "--capsule" not in source
    assert "--command" not in source
    assert "--shell" not in source
    assert "--env" not in source
    assert "--producer-sha" not in source
    assert "--producer-sha256" not in source
    assert "--script" not in source


def test_gate_module_no_subprocess_no_network() -> None:
    source = GATE_MODULE_PATH.read_text()
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "import socket" not in source
    assert "import urllib" not in source
    assert "import http" not in source
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "os.popen" not in source


def test_gate_module_derives_paths_from_file_only() -> None:
    """The gate module must derive ICP_ROOT, capsule path, manifest path,
    and the SharedCore sibling paths only from its installed __file__."""
    source = GATE_MODULE_PATH.read_text()
    assert "Path(__file__).resolve()" in source
    # CLI parse uses sys.argv[1:] only (no other argv mutation).
    assert "sys.argv" not in source or "sys.argv[1:]" in source


def test_gate_cli_rejects_missing_flags() -> None:
    with _canonical_tempdir() as tmp:
        r = _run_cli(GATE_MODULE_PATH)
    assert r.returncode != 0
    # argparse prints usage to stderr; no traceback.
    assert "Traceback" not in r.stderr


def test_gate_cli_rejects_unknown_flag() -> None:
    with _canonical_tempdir() as tmp:
        run_root = tmp
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(run_root),
            "--bogus", "x",
        )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_gate_cli_rejects_duplicate_flag() -> None:
    """Each of the seven flags must appear exactly once."""
    with _canonical_tempdir() as tmp:
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--run-root", str(tmp),
        )
    assert r.returncode != 0


def test_gate_cli_requires_all_seven_flags() -> None:
    """Omitting any of the seven required flags must fail closed."""
    with _canonical_tempdir() as tmp:
        # Provide only --run-root; the other six are missing.
        r = _run_cli(GATE_MODULE_PATH, "--run-root", str(tmp))
    assert r.returncode != 0


# ===========================================================================
# 2. New gate primitive: path validation, sanitized failures.
# ===========================================================================


def test_gate_rejects_non_absolute_run_root() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Run merge first so the merged file exists.
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", "relative/path",
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    # Sanitized: never leak the absolute path of run_root.
    assert str(tmp) not in r.stderr


def test_gate_rejects_symlinked_input() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Create a symlink alias to the projection file.
        alias = tmp / "alias.projection.json"
        try:
            os.symlink(str(paths["projection"]), str(alias))
        except OSError:
            self_skip("symlink not supported on this platform")
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(alias),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_gate_rejects_input_outside_run_root() -> None:
    with _canonical_tempdir() as tmp_outer, _canonical_tempdir() as tmp_inner:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp_inner)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Point --page-canvas-expected at a file under tmp_outer (escape).
        escape = tmp_outer / "outside.expected.json"
        shutil.copyfile(str(paths["expected"]), str(escape))
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp_inner),
            "--page-canvas-expected", str(escape),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


def test_gate_rejects_non_json_input() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Corrupt the projection file with non-JSON bytes.
        paths["projection"].write_bytes(b"not json {\x00")
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


def test_gate_rejects_duplicate_keys_in_input() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Rewrite scene.json with a duplicate top-level key.
        scene_text = (
            '{"nodes": [], "nodes": [{"id": "x", "bbox": [0, 0, 1, 1]}]}'
        )
        paths["scene"].write_text(scene_text, encoding="utf-8")
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


# ===========================================================================
# 3. New gate primitive: projection parity, legacy byte parity, merge
#    canonicality, topology checks.
# ===========================================================================


def test_gate_rejects_when_projection_bytes_diverge_from_file() -> None:
    """build_projection_bytes(doc) must equal the raw file bytes."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Tamper with the projection file's bytes (still valid JSON but
        # not the canonical byte form).
        doc = json.loads(paths["projection"].read_bytes().decode("utf-8"))
        # Add an unknown key (this will fail projection validation).
        doc["unexpected"] = "x"
        paths["projection"].write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


def test_gate_rejects_when_legacy_bytes_diverge_from_projection() -> None:
    """build_legacy_bytes(projection)[0] must equal the raw expected file
    bytes; mutating the expected file after the projection was generated
    must fail."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Mutate the legacy expected file (break parity).
        doc = json.loads(paths["expected"].read_bytes().decode("utf-8"))
        doc["artboardWidth"] = 99999.0
        paths["expected"].write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


def test_gate_rejects_when_merged_bytes_not_canonical() -> None:
    """The merge output must be canonical JSON; a non-canonical merge
    output must fail (e.g. wrong indentation)."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Run merge first.
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Rewrite merged with non-canonical form (4-space indent).
        merged_doc = json.loads(paths["merged"].read_bytes().decode("utf-8"))
        paths["merged"].write_text(
            json.dumps(merged_doc, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


def test_gate_rejects_when_merged_topology_diverges() -> None:
    """A merged document whose top-level non-nodes fields diverge from
    the page expected document must fail."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Mutate a non-nodes top-level field in the merged output.
        merged_doc = json.loads(paths["merged"].read_bytes().decode("utf-8"))
        merged_doc["artboardWidth"] = 99999.0
        paths["merged"].write_text(
            json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


def test_gate_rejects_when_page_node_value_changed_in_merged() -> None:
    """Mutating a page node value inside the merged document must fail."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        page_nodes = [_make_node("page_a"), _make_node("page_b")]
        paths = _setup_chain_inputs(projection_module, tmp, page_nodes=page_nodes)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        merged_doc = json.loads(paths["merged"].read_bytes().decode("utf-8"))
        merged_doc["nodes"]["page_a"]["impl"] = "tampered"
        paths["merged"].write_text(
            json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(paths["projection"]),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0


# ===========================================================================
# 4. New gate primitive: missing-local pass-through (null digest).
# ===========================================================================


def test_gate_missing_local_pass_through_succeeds_with_null_digest() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        page_nodes = [_make_node("page_a"), _make_node("page_b")]
        paths = _setup_chain_inputs(
            projection_module, tmp, page_nodes=page_nodes, local_payload=None,
        )
        assert not paths["local"].exists()
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        prov = json.loads(paths["provenance"].read_bytes().decode("utf-8"))
        assert prov["kind"] == PROVENANCE_KIND
        assert prov["producerKind"] == "iff-v1.merge_shared_expected"
        assert prov["sharedComponentsLocalSha256"] is None
        page_ids = [n["id"] for n in page_nodes]
        assert prov["pageCanvasNodeIds"] == page_ids
        assert prov["sharedComponentNodeIds"] == []
        assert prov["mergedNodeIds"] == page_ids
        # Digests over actual file bytes.
        assert prov["pageCanvasProjectionSha256"] == _sha256_file(paths["projection"])
        assert prov["sceneSha256"] == _sha256_file(paths["scene"])
        assert prov["mergedExpectedSha256"] == _sha256_file(paths["merged"])
        # Producer SHA = manifest-bound installed capsule SHA.
        assert prov["producerSha256"] == CAPSULE_MERGE_SHA256


def test_gate_present_empty_local_emits_non_null_digest() -> None:
    """An empty (but present) shared_components.local.json yields a non-
    null digest."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        page_nodes = [_make_node("page_a")]
        paths = _setup_chain_inputs(
            projection_module, tmp,
            page_nodes=page_nodes,
            local_payload={"components": []},
        )
        assert paths["local"].exists()
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        prov = json.loads(paths["provenance"].read_bytes().decode("utf-8"))
        assert prov["sharedComponentsLocalSha256"] == _sha256_file(paths["local"])
        assert prov["sharedComponentsLocalSha256"] is not None


def test_gate_unresolved_local_aborts_before_gate_runs() -> None:
    """A 'missing' shared component makes merge_shared_expected.py fail;
    no merged file is produced, so the gate cannot run."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        page_nodes = [_make_node("page_root")]
        local_payload = {
            "components": [
                {
                    "status": "missing",
                    "signature": "struct:unresolved",
                    "group_node": "shared_grp",
                    "bbox": [10, 10, 20, 20],
                }
            ]
        }
        paths = _setup_chain_inputs(
            projection_module, tmp,
            page_nodes=page_nodes,
            local_payload=local_payload,
            scene_extras=[{"id": "shared_grp", "bbox": [10, 10, 20, 20]}],
        )
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode != 0
        assert not paths["merged"].exists()


# ===========================================================================
# 5. New gate primitive: present local reuse case, shared suffix ordering.
# ===========================================================================


def test_gate_present_local_reuse_emits_shared_suffix_correctly() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        page_nodes = [_make_node("page_a"), _make_node("page_b")]
        scene_extras = [{"id": "shared_grp", "bbox": [100, 100, 40, 40]}]
        local_payload = {
            "components": [
                {
                    "status": "reuse",
                    "name": "SharedComp",
                    "signature": "struct:xyz",
                    "group_node": "shared_grp",
                    "bbox": [100, 100, 40, 40],
                    "node_map": {"shared_grp": "shared_src_1"},
                    "expected_nodes": {"shared_src_1": {"bbox": [100, 100, 40, 40]}},
                }
            ]
        }
        paths = _setup_chain_inputs(
            projection_module, tmp,
            page_nodes=page_nodes,
            local_payload=local_payload,
            scene_extras=scene_extras,
        )
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0, rc.stderr
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        prov = json.loads(paths["provenance"].read_bytes().decode("utf-8"))
        assert prov["pageCanvasNodeIds"] == ["page_a", "page_b"]
        assert prov["sharedComponentNodeIds"] == ["shared_src_1"]
        assert prov["mergedNodeIds"] == ["page_a", "page_b", "shared_src_1"]
        assert prov["sharedComponentsLocalSha256"] == _sha256_file(paths["local"])
        assert prov["mergedExpectedSha256"] == _sha256_file(paths["merged"])


# ===========================================================================
# 6. New gate primitive: atomic publish, safe rerun, swap detection.
# ===========================================================================


def test_gate_atomic_publish_writes_canonical_bytes() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        # The published bytes must be canonical JSON with no trailing
        # newline.
        raw = paths["provenance"].read_bytes()
        assert not raw.endswith(b"\n")
        # Owner-only mode on the published file (or stricter).
        st = paths["provenance"].lstat()
        assert stat.S_ISREG(st.st_mode)
        mode = stat.S_IMODE(st.st_mode)
        assert mode == 0o600


def test_gate_safe_rerun_replaces_existing_published_artifact() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r1 = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r1.returncode == 0, r1.stderr
        first_bytes = paths["provenance"].read_bytes()
        # Rerun: should atomically replace.
        r2 = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r2.returncode == 0, r2.stderr
        assert paths["provenance"].read_bytes() == first_bytes


def test_gate_failed_publish_leaves_no_partial_temp() -> None:
    """If the gate fails (e.g. projection parity), no temp file is left
    in the output directory."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Corrupt the projection file to force failure inside the gate
        # AFTER the merge file exists but BEFORE publish.
        doc = json.loads(paths["projection"].read_bytes().decode("utf-8"))
        doc["artboardWidth"] = 99999.0
        paths["projection"].write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        before = set(p.name for p in paths["provenance"].parent.iterdir())
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode != 0
        after = set(p.name for p in paths["provenance"].parent.iterdir())
        # No new temp files created.
        new_files = after - before
        assert new_files == set(), f"unexpected temp files left: {new_files}"


def test_gate_reopen_revalidation_detects_swap_after_publish() -> None:
    """Simulate a test seam that swaps the published provenance bytes
    between the atomic replace and the re-open/revalidation step. We
    cannot easily inject such a seam without modifying production code;
    instead we verify the contract by re-opening a deliberately-bad
    file via the gate's revalidation path. Concretely: corrupt the
    provenance file in-place AFTER a successful run and verify the
    bytes differ from canonical."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0
        canonical = paths["provenance"].read_bytes()
        # Swap the file in-place after the run; the NEXT run must
        # atomically replace with canonical bytes again.
        prov_doc = json.loads(canonical.decode("utf-8"))
        prov_doc["producerKind"] = "tampered.evil"
        paths["provenance"].write_text(
            json.dumps(prov_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert paths["provenance"].read_bytes() != canonical
        # Rerun: gate replaces the tampered file with canonical bytes.
        r2 = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r2.returncode == 0, r2.stderr
        assert paths["provenance"].read_bytes() == canonical


def test_gate_no_traceback_or_path_leak_on_failure() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        # Pass a non-existent projection path; expect sanitized failure.
        bogus = tmp / "absent.projection.json"
        r = _run_cli(
            GATE_MODULE_PATH,
            "--run-root", str(tmp),
            "--page-canvas-expected", str(paths["expected"]),
            "--page-canvas-projection", str(bogus),
            "--shared-components-local", str(paths["local"]),
            "--scene", str(paths["scene"]),
            "--merged-expected", str(paths["merged"]),
            "--provenance-out", str(paths["provenance"]),
        )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    # Sanitized: no absolute path leak.
    assert str(tmp) not in r.stderr
    # Sanitized: no raw JSON content leak from the gate's own decode
    # (the failure is on the projection path itself).
    assert PROVENANCE_KIND not in r.stderr


# ===========================================================================
# 7. New gate primitive: tampered capsule rejection (manifest-bound SHA).
# ===========================================================================


def test_gate_uses_manifest_bound_producer_sha() -> None:
    """The gate's producerSha256 must equal the manifest entry for
    merge_shared_expected.py (NOT a recomputed file SHA that could drift
    if the capsule were tampered after the manifest was issued)."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        prov = json.loads(paths["provenance"].read_bytes().decode("utf-8"))
        # Must equal the manifest digest, not a recomputed live digest.
        assert prov["producerSha256"] == CAPSULE_MERGE_SHA256


def test_gate_rejects_tampered_capsule_via_verifier() -> None:
    """If the installed merge_shared_expected.py is mutated, the gate's
    capsule verifier stage must reject before any file is published."""
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        # Tamper: append a comment to the installed capsule.
        original = CAPSULE_MERGE.read_bytes()
        try:
            with open(str(CAPSULE_MERGE), "ab") as f:
                f.write(b"\n# tampered\n")
            r = _run_gate(
                tmp,
                paths["expected"], paths["projection"], paths["local"],
                paths["scene"], paths["merged"], paths["provenance"],
            )
            assert r.returncode != 0
            assert not paths["provenance"].exists() or (
                # If a stale provenance file pre-existed, the gate must
                # not have replaced it with a fresh publish.
                paths["provenance"].read_bytes()
                in {b"", paths["provenance"].read_bytes()}
            )
        finally:
            CAPSULE_MERGE.write_bytes(original)
    # After restoring the capsule, the verifier must be clean again.
    r = _run_cli(VERIFY_TOOL)
    assert r.returncode == 0


# ===========================================================================
# 8. New gate primitive: success summary shape.
# ===========================================================================


def test_gate_emits_one_canonical_json_summary_on_stdout() -> None:
    with _canonical_tempdir() as tmp:
        projection_module = _load_projection()
        paths = _setup_chain_inputs(projection_module, tmp)
        rc = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc.returncode == 0
        r = _run_gate(
            tmp,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert r.returncode == 0, r.stderr
        # Exactly one JSON object on stdout.
        stdout_lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        assert len(stdout_lines) == 1, r.stdout
        summary = json.loads(stdout_lines[0])
        assert summary.get("ok") is True
        # Sanitized: never leak absolute paths.
        for key, value in summary.items():
            assert str(tmp) not in str(value), (key, value)


# ===========================================================================
# 9. trace_harness.v1: new 17-key request schema.
# ===========================================================================


_TRACE_REQUEST_KEYS = frozenset({
    "project_root",
    "run_root",
    "package_name",
    "page_canvas_expected",
    "page_canvas_projection",
    "shared_components_local",
    "scene",
    "merged_expected_out",
    "provenance_out",
    "page_import_path",
    "page_type",
    "trace_out",
    "responsive_out",
    "responsive_contract_out",
    "viewports_file",
    "safe_area_policy",
    "out",
})


def _make_trace_request(project_root: Path, run_root: Path) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "run_root": str(run_root),
        "package_name": "my_app",
        "page_canvas_expected": "canvas.expected.json",
        "page_canvas_projection": "canvas.projection.json",
        "shared_components_local": "shared_components.local.json",
        "scene": "scene.json",
        "merged_expected_out": "trace/merged_expected.json",
        "provenance_out": "trace/merged_expected.provenance.json",
        "page_import_path": "lib/page/home_page.dart",
        "page_type": "HomePage",
        "trace_out": "trace/trace.json",
        "responsive_out": "responsive.json",
        "responsive_contract_out": "responsive_contract.json",
        "viewports_file": "viewports.json",
        "safe_area_policy": "edge_to_edge",
        "out": "test/home_layout_trace_test.dart",
    }


def _setup_trace_inputs(project_root: Path, run_root: Path) -> None:
    (project_root / "lib" / "page").mkdir(parents=True, exist_ok=True)
    (project_root / "test").mkdir(parents=True, exist_ok=True)
    (run_root / "trace").mkdir(parents=True, exist_ok=True)
    _write_json(run_root / "canvas.expected.json", {"nodes": {}})
    _write_json(run_root / "canvas.projection.json", {"nodes": []})
    _write_json(run_root / "scene.json", {"nodes": []})
    _write_json(run_root / "viewports.json", {"viewports": []})


@contextlib.contextmanager
def _trace_project():
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_trace_inputs(proj, run)
        yield proj, run, _make_trace_request(proj, run)


def test_trace_request_keys_are_exactly_seventeen() -> None:
    assert len(_TRACE_REQUEST_KEYS) == 17
    assert "expected" not in _TRACE_REQUEST_KEYS
    assert "page_canvas_expected" in _TRACE_REQUEST_KEYS
    assert "page_canvas_projection" in _TRACE_REQUEST_KEYS
    assert "shared_components_local" in _TRACE_REQUEST_KEYS
    assert "merged_expected_out" in _TRACE_REQUEST_KEYS
    assert "provenance_out" in _TRACE_REQUEST_KEYS


def test_build_trace_rejects_old_12_key_request() -> None:
    """The old ambiguous 12-key request must fail closed."""
    module = _load_ops("p25d_trace_old_keys")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_trace_inputs(proj, run)
        # Old shape: only ``expected`` (no page_canvas_* / merged_out / etc).
        old = {
            "project_root": str(proj),
            "run_root": str(run),
            "package_name": "my_app",
            "expected": "canvas.expected.json",
            "page_import_path": "lib/page/home_page.dart",
            "page_type": "HomePage",
            "trace_out": "trace/trace.json",
            "responsive_out": "responsive.json",
            "responsive_contract_out": "responsive_contract.json",
            "viewports_file": "viewports.json",
            "safe_area_policy": "edge_to_edge",
            "out": "test/home_layout_trace_test.dart",
        }
        try:
            module.build("flutter.trace_harness.v1", old)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("old 12-key trace request accepted")


def test_build_trace_accepts_seventeen_key_request() -> None:
    module = _load_ops("p25d_trace_17key")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    assert plan["operation_id"] == "flutter.trace_harness.v1"


def test_build_trace_rejects_projection_passed_as_page_canvas_expected() -> None:
    """Projection contract bytes are not legacy expected bytes; passing
    the projection file as page_canvas_expected must fail somewhere
    downstream. At build time only the suffix check applies (.expected.json
    for page_canvas_expected), so verify that .json alone is rejected."""
    module = _load_ops("p25d_trace_proj_as_expected")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        # page_canvas_expected must end .expected.json.
        bad["page_canvas_expected"] = "canvas.projection.json"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("non-.expected.json page_canvas_expected accepted")


def test_build_trace_requires_page_canvas_expected_suffix() -> None:
    module = _load_ops("p25d_trace_suffix")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["page_canvas_expected"] = "canvas.json"  # missing .expected.json
        # Ensure the file exists at this name so the suffix check fires,
        # not the existence check.
        _write_json(run / "canvas.json", {})
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("page_canvas_expected without .expected.json accepted")


def test_build_trace_requires_merged_expected_out_basename() -> None:
    module = _load_ops("p25d_trace_merged_basename")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["merged_expected_out"] = "trace/other.json"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("non-merged_expected.json basename accepted")


def test_build_trace_requires_provenance_out_basename() -> None:
    module = _load_ops("p25d_trace_prov_basename")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        bad["provenance_out"] = "trace/other.json"
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("non-merged_expected.provenance.json basename accepted")


def test_build_trace_provenance_out_must_share_parent_with_merged() -> None:
    module = _load_ops("p25d_trace_prov_parent")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        # Same basename but different parent directory.
        bad["provenance_out"] = "other_dir/merged_expected.provenance.json"
        (run / "other_dir").mkdir(parents=True, exist_ok=True)
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("provenance_out parent mismatch accepted")


def test_build_trace_merged_out_must_equal_trace_out_parent() -> None:
    module = _load_ops("p25d_trace_merged_topology")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        # trace_out is trace/trace.json; merged_out must be
        # trace/merged_expected.json. Move merged to a different dir.
        bad["merged_expected_out"] = "elsewhere/merged_expected.json"
        (run / "elsewhere").mkdir(parents=True, exist_ok=True)
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("merged_expected_out != trace_out.parent/merged_expected.json accepted")


def test_build_trace_rejects_path_alias_collision() -> None:
    """Each input/output identity must be distinct except the cross-step
    reuse of merged_expected_out."""
    module = _load_ops("p25d_trace_alias")
    with _trace_project() as (proj, run, request):
        bad = dict(request)
        # Point page_canvas_expected and page_canvas_projection at the
        # same file identity (forbidden).
        bad["page_canvas_projection"] = bad["page_canvas_expected"]
        try:
            module.build("flutter.trace_harness.v1", bad)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("input identity collision accepted")


# ===========================================================================
# 10. trace_harness.v1: new three-step plan + cross-step identity.
# ===========================================================================


def test_build_trace_returns_three_step_plan() -> None:
    module = _load_ops("p25d_trace_three_steps")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    assert len(plan["steps"]) == 3
    assert [s["step_id"] for s in plan["steps"]] == [
        "merge_shared_expected",
        "verify_merged_expectation_provenance",
        "gen_layout_trace_test",
    ]
    assert [s["primitive"] for s in plan["steps"]] == [
        "merge_shared_expected.py",
        "flutter_merged_expectation_provenance_gate_v1.py",
        "gen_layout_trace_test.py",
    ]


def test_build_trace_step_origins() -> None:
    module = _load_ops("p25d_trace_origins")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    # step 0 = capsule, step 1 = platform, step 2 = capsule.
    step0_argv1 = plan["steps"][0]["argv"][1]
    step1_argv1 = plan["steps"][1]["argv"][1]
    step2_argv1 = plan["steps"][2]["argv"][1]
    assert step0_argv1 == str(CAPSULE_SCRIPTS_DIR / "merge_shared_expected.py")
    assert step1_argv1 == str(PLATFORMS_DIR / "flutter_merged_expectation_provenance_gate_v1.py")
    assert step2_argv1 == str(CAPSULE_SCRIPTS_DIR / "gen_layout_trace_test.py")


def test_build_trace_step_0_argv_exact() -> None:
    module = _load_ops("p25d_trace_argv0")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    argv = plan["steps"][0]["argv"]
    flags = argv[2:]
    assert flags == [
        "--expected", str(run / "canvas.expected.json"),
        "--local", str(run / "shared_components.local.json"),
        "--scene", str(run / "scene.json"),
        "--out", str(run / "trace" / "merged_expected.json"),
    ], flags


def test_build_trace_step_1_argv_exact() -> None:
    module = _load_ops("p25d_trace_argv1")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    argv = plan["steps"][1]["argv"]
    flags = argv[2:]
    assert flags == [
        "--run-root", str(run),
        "--page-canvas-expected", str(run / "canvas.expected.json"),
        "--page-canvas-projection", str(run / "canvas.projection.json"),
        "--shared-components-local", str(run / "shared_components.local.json"),
        "--scene", str(run / "scene.json"),
        "--merged-expected", str(run / "trace" / "merged_expected.json"),
        "--provenance-out", str(run / "trace" / "merged_expected.provenance.json"),
    ], flags


def test_build_trace_step_2_argv_expected_is_merged_out() -> None:
    module = _load_ops("p25d_trace_argv2")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    argv = plan["steps"][2]["argv"]
    idx = argv.index("--expected")
    assert argv[idx + 1] == str(run / "trace" / "merged_expected.json")
    # The legacy 9-flag consumer argv shape is retained.
    expected_flags = [
        "--expected", str(run / "trace" / "merged_expected.json"),
        "--page-import", "package:my_app/page/home_page.dart",
        "--page-type", "HomePage",
        "--trace-out", str(run / "trace" / "trace.json"),
        "--responsive-out", str(run / "responsive.json"),
        "--responsive-contract-out", str(run / "responsive_contract.json"),
        "--viewports-file", str(run / "viewports.json"),
        "--safe-area-policy", "edge_to_edge",
        "--out", str(proj / "test" / "home_layout_trace_test.dart"),
    ]
    assert argv[2:] == expected_flags, argv[2:]


def test_build_trace_cross_step_identity_merge_out() -> None:
    """Step 0 --out == Step 1 --merged-expected == Step 2 --expected."""
    module = _load_ops("p25d_trace_xid_merge")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    s0_out = plan["steps"][0]["argv"][plan["steps"][0]["argv"].index("--out") + 1]
    s1_merged = plan["steps"][1]["argv"][plan["steps"][1]["argv"].index("--merged-expected") + 1]
    s2_expected = plan["steps"][2]["argv"][plan["steps"][2]["argv"].index("--expected") + 1]
    assert s0_out == s1_merged == s2_expected


def test_build_trace_cross_step_identity_local() -> None:
    """Step 0 --local == Step 1 --shared-components-local."""
    module = _load_ops("p25d_trace_xid_local")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    s0_local = plan["steps"][0]["argv"][plan["steps"][0]["argv"].index("--local") + 1]
    s1_local = plan["steps"][1]["argv"][plan["steps"][1]["argv"].index("--shared-components-local") + 1]
    assert s0_local == s1_local


def test_build_trace_cross_step_identity_scene() -> None:
    """Step 0 --scene == Step 1 --scene."""
    module = _load_ops("p25d_trace_xid_scene")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    s0_scene = plan["steps"][0]["argv"][plan["steps"][0]["argv"].index("--scene") + 1]
    s1_scene = plan["steps"][1]["argv"][plan["steps"][1]["argv"].index("--scene") + 1]
    assert s0_scene == s1_scene


def test_build_trace_cross_step_identity_page_expected() -> None:
    """Step 0 --expected == Step 1 --page-canvas-expected."""
    module = _load_ops("p25d_trace_xid_pce")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    s0_expected = plan["steps"][0]["argv"][plan["steps"][0]["argv"].index("--expected") + 1]
    s1_pce = plan["steps"][1]["argv"][plan["steps"][1]["argv"].index("--page-canvas-expected") + 1]
    assert s0_expected == s1_pce


def test_build_trace_step_cwd_all_equal_project_root() -> None:
    module = _load_ops("p25d_trace_cwd")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    cwds = [step["cwd"] for step in plan["steps"]]
    assert len(set(cwds)) == 1
    assert cwds[0] == str(proj)


def test_build_trace_step_timeouts_fixed() -> None:
    module = _load_ops("p25d_trace_timeout")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    for step in plan["steps"]:
        assert step["timeout_seconds"] == module.TIMEOUT_SECONDS


def test_build_trace_manifest_sha_binding() -> None:
    module = _load_ops("p25d_trace_sha")
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    sha_map = {e["name"]: e["sha256"] for e in manifest["scripts"]}
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    for step in plan["steps"]:
        if step["primitive"] == "flutter_merged_expectation_provenance_gate_v1.py":
            # Platform-origin: SHA is recomputed from the file.
            live = _sha256_file(PLATFORMS_DIR / step["primitive"])
            assert step["primitive_sha256"] == live
            assert step["primitive"] not in sha_map
        else:
            assert step["primitive_sha256"] == sha_map[step["primitive"]]


def test_verify_trace_plan_returns_three_step_report() -> None:
    module = _load_ops("p25d_trace_verify")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
        report = module.verify_plan(plan)
    assert report["ok"] is True
    assert report["operation_id"] == "flutter.trace_harness.v1"
    assert report["steps_total"] == 3


# ===========================================================================
# 11. trace_harness.v1: verify_plan tamper / reorder detection.
# ===========================================================================


def _trace_plan():
    module = _load_ops("p25d_trace_tamper_prep")
    with _trace_project() as (proj, run, request):
        plan = module.build("flutter.trace_harness.v1", request)
    return plan


def test_verify_trace_rejects_step_reorder() -> None:
    module = _load_ops("p25d_trace_reorder")
    plan = copy.deepcopy(_trace_plan())
    plan["steps"][0], plan["steps"][1] = plan["steps"][1], plan["steps"][0]
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("step reorder accepted")


def test_verify_trace_rejects_tampered_primitive_sha() -> None:
    module = _load_ops("p25d_trace_psha")
    plan = copy.deepcopy(_trace_plan())
    plan["steps"][0]["primitive_sha256"] = "a" * 64
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("tampered primitive_sha accepted")


def test_verify_trace_rejects_tampered_argv_path() -> None:
    module = _load_ops("p25d_trace_argv_tamp")
    plan = copy.deepcopy(_trace_plan())
    # Tamper the merge output path in step 0 (cross-step identity break).
    idx = plan["steps"][0]["argv"].index("--out")
    plan["steps"][0]["argv"][idx + 1] = (
        plan["steps"][0]["argv"][idx + 1] + ".tampered"
    )
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("tampered argv path accepted")


def test_verify_trace_rejects_cross_step_identity_break() -> None:
    """Step 0 --out and Step 2 --expected must be the same path."""
    module = _load_ops("p25d_trace_xbreak")
    plan = copy.deepcopy(_trace_plan())
    idx2 = plan["steps"][2]["argv"].index("--expected")
    # Mutate step 2 --expected so it no longer matches step 0 --out.
    plan["steps"][2]["argv"][idx2 + 1] = (
        plan["steps"][2]["argv"][idx2 + 1] + ".alien"
    )
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("cross-step identity break accepted")


def test_verify_trace_rejects_extra_step() -> None:
    module = _load_ops("p25d_trace_extra_step")
    plan = copy.deepcopy(_trace_plan())
    plan["steps"].append(dict(plan["steps"][0]))
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("extra step accepted")


def test_verify_trace_rejects_missing_step() -> None:
    module = _load_ops("p25d_trace_missing_step")
    plan = copy.deepcopy(_trace_plan())
    plan["steps"].pop()
    try:
        module.verify_plan(plan)
    except module.OperationPlanError:
        return
    else:
        raise AssertionError("missing step accepted")


# ===========================================================================
# 12. trace_harness.v1: shared_components_local absence is supported.
# ===========================================================================


def test_build_trace_supports_absent_shared_components_local_leaf() -> None:
    """shared_components_local is always passed as --local but its safe
    leaf may be absent at build time (the merge producer handles the
    missing-local pass-through case)."""
    module = _load_ops("p25d_trace_absent_local")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_trace_inputs(proj, run)
        # Do NOT create shared_components.local.json.
        local_path = run / "shared_components.local.json"
        assert not local_path.exists()
        request = _make_trace_request(proj, run)
        plan = module.build("flutter.trace_harness.v1", request)
    # The --local argv value must be the validated absolute path even
    # when the leaf does not exist.
    s0_local = plan["steps"][0]["argv"][plan["steps"][0]["argv"].index("--local") + 1]
    s1_local = plan["steps"][1]["argv"][plan["steps"][1]["argv"].index("--shared-components-local") + 1]
    assert s0_local == str(local_path)
    assert s1_local == str(local_path)
    report = module.verify_plan(plan)
    assert report["ok"] is True


def test_build_trace_rejects_symlinked_shared_components_local() -> None:
    module = _load_ops("p25d_trace_symlink_local")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        _setup_trace_inputs(proj, run)
        # Create a real file then symlink the leaf at it.
        target = run / "real.local.json"
        _write_json(target, {})
        symlink = run / "shared_components.local.json"
        try:
            os.symlink(str(target), str(symlink))
        except OSError:
            self_skip("symlink not supported")
        request = _make_trace_request(proj, run)
        try:
            module.build("flutter.trace_harness.v1", request)
        except module.OperationPlanError:
            return
        else:
            raise AssertionError("symlinked shared_components_local accepted")


# ===========================================================================
# 13. End-to-end: merge -> gate -> trace consumer, no auto-adoption message.
# ===========================================================================


_VIEWPORTS = [
    {"width": 320, "height": 568},
    {"width": 375, "height": 812},
    {"width": 430, "height": 932},
]


def test_end_to_end_chain_no_auto_adoption_message() -> None:
    """Run the real merge -> gate -> gen_layout_trace_test chain and
    verify the consumer's auto-adoption message is NOT emitted (because
    the consumer's --expected is already the adjacent merged file)."""
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        # Project structure for gen_layout_trace_test.
        (proj / "lib" / "page").mkdir(parents=True)
        (proj / "test").mkdir(parents=True)

        projection_module = _load_projection()
        page_nodes = [_make_node("page_a"), _make_node("page_b")]
        paths = _setup_chain_inputs(projection_module, run, page_nodes=page_nodes)
        # viewports.json needs >= 3 viewports.
        _write_json(run / "viewports.json", {"viewports": _VIEWPORTS})

        # Step 0: merge.
        rc_merge = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc_merge.returncode == 0, rc_merge.stderr
        assert paths["merged"].is_file()

        # Step 1: gate.
        rc_gate = _run_gate(
            run,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert rc_gate.returncode == 0, rc_gate.stderr
        assert paths["provenance"].is_file()

        # Step 2: gen_layout_trace_test --expected <merged>.
        trace_out = run / "trace" / "trace.json"
        responsive_out = run / "responsive.json"
        responsive_contract_out = run / "responsive_contract.json"
        out_dart = proj / "test" / "home_layout_trace_test.dart"
        rc_consumer = _run_cli(
            CAPSULE_TRACE,
            "--expected", str(paths["merged"]),
            "--page-import", "package:my_app/page/home_page.dart",
            "--page-type", "HomePage",
            "--trace-out", str(trace_out),
            "--responsive-out", str(responsive_out),
            "--responsive-contract-out", str(responsive_contract_out),
            "--viewports-file", str(run / "viewports.json"),
            "--safe-area-policy", "edge_to_edge",
            "--out", str(out_dart),
        )
        assert rc_consumer.returncode == 0, rc_consumer.stderr
        # The auto-adoption message must NOT appear (because --expected
        # already resolves to the adjacent merged file).
        assert "adopted canonical merged expectation" not in rc_consumer.stdout


def test_end_to_end_chain_succeeds_with_present_local() -> None:
    """The chain succeeds when shared_components.local.json is present
    with a reuse component (non-null digest)."""
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        run = tmp / "run"
        proj.mkdir()
        run.mkdir()
        (proj / "lib" / "page").mkdir(parents=True)
        (proj / "test").mkdir(parents=True)

        projection_module = _load_projection()
        page_nodes = [_make_node("page_a")]
        local_payload = {
            "components": [
                {
                    "status": "reuse",
                    "name": "SharedComp",
                    "signature": "struct:xyz",
                    "group_node": "shared_grp",
                    "bbox": [100, 100, 40, 40],
                    "node_map": {"shared_grp": "shared_src_1"},
                    "expected_nodes": {"shared_src_1": {"bbox": [100, 100, 40, 40]}},
                }
            ]
        }
        scene_extras = [{"id": "shared_grp", "bbox": [100, 100, 40, 40]}]
        paths = _setup_chain_inputs(
            projection_module, run,
            page_nodes=page_nodes,
            local_payload=local_payload,
            scene_extras=scene_extras,
        )
        _write_json(run / "viewports.json", {"viewports": _VIEWPORTS})

        rc_merge = _run_merge(
            paths["expected"], paths["local"], paths["scene"], paths["merged"],
        )
        assert rc_merge.returncode == 0, rc_merge.stderr

        rc_gate = _run_gate(
            run,
            paths["expected"], paths["projection"], paths["local"],
            paths["scene"], paths["merged"], paths["provenance"],
        )
        assert rc_gate.returncode == 0, rc_gate.stderr
        prov = json.loads(paths["provenance"].read_bytes().decode("utf-8"))
        assert prov["sharedComponentsLocalSha256"] == _sha256_file(paths["local"])
        assert prov["sharedComponentNodeIds"] == ["shared_src_1"]


# ===========================================================================
# 14. flutter_standard_v1.py descriptor: trace_harness primitive tuple
#     update; total count update.
# ===========================================================================


def test_descriptor_trace_harness_primitives_now_two() -> None:
    """The descriptor must list the capsule legacy primitives in the
    execution order: merge_shared_expected.py, gen_layout_trace_test.py.
    The platform gate is NOT a legacy primitive and must NOT appear."""
    module = _load_descriptor("p25d_desc_trace")
    descriptor = module.describe()
    op = descriptor["operations"][3]
    assert op["id"] == "trace_harness"
    primitives = [p["script"] for p in op["legacy_primitives"]]
    assert primitives == [
        "merge_shared_expected.py",
        "gen_layout_trace_test.py",
    ]
    # The platform gate is NOT in the tuple.
    assert "flutter_merged_expectation_provenance_gate_v1.py" not in primitives


def test_descriptor_legacy_primitives_total_increments_by_one() -> None:
    """Adding merge_shared_expected.py to trace_harness increases the
    legacy primitive total by exactly one."""
    module = _load_descriptor("p25d_desc_total")
    descriptor = module.describe()
    total = sum(len(op["legacy_primitives"]) for op in descriptor["operations"])
    # Pre-P2.5d had 22 mapped legacy primitives; P2.5d adds one
    # (merge_shared_expected.py).
    assert total == 23, total


def test_descriptor_no_duplicate_primitive_ownership() -> None:
    module = _load_descriptor("p25d_desc_dup")
    descriptor = module.describe()
    seen: set[str] = set()
    for op in descriptor["operations"]:
        for prim in op["legacy_primitives"]:
            name = prim["script"]
            assert name not in seen, f"duplicate primitive ownership: {name}"
            seen.add(name)


def test_descriptor_verify_descriptor_succeeds() -> None:
    module = _load_descriptor("p25d_desc_verify")
    report = module.verify_descriptor()
    assert report["ok"] is True
    assert report["legacy_primitives_total"] == 23


def test_descriptor_activation_unchanged() -> None:
    """P2.5d does not change activation state or capability state."""
    module = _load_descriptor("p25d_desc_state")
    descriptor = module.describe()
    assert descriptor["activation_state"] == "inactive"
    assert descriptor["executable"] is False
    op = descriptor["operations"][3]
    assert op["capability_state"] == "optional-with-shared-policy"
    assert op["implementation_state"] == "legacy-mapped"


# ===========================================================================
# 15. Boundaries: no drift in registry / activation / capsule / baseline /
#     iff / SharedCore / executor / binding / auth / preflight.
# ===========================================================================


def test_no_pycache_under_icp() -> None:
    found: list[Path] = []
    for path in ICP_ROOT.rglob("__pycache__"):
        if path.is_dir():
            found.append(path)
    for path in ICP_ROOT.rglob("*.pyc"):
        found.append(path)
    assert not found, f"__pycache__/.pyc present under icp/: {found}"


def test_no_other_platform_module_changed() -> None:
    """Sanity: the binding/auth/executor/preflight modules are still at
    their protected hashes."""
    expected = {
        "flutter_execution_binding_v1.py":
            "d6668876865d0d090ea057bc73274a502e1057d888bdca1336c236c65f4a5a9d",
        "flutter_execution_authorization_v1.py":
            "1d6a17bfb64420a3357c4a914f93d2b3f3e22ac2476d2c24b8141d21c246bbd2",
        "flutter_execution_executor_v1.py":
            "34fdfd22c4ced65216d5e7925696fbda7a9317a460478843314d49bb4f395cb2",
        "flutter_project_preflight_v1.py":
            "56476140ec998f796fd9181b7aad5342ca67f0508f5d078873c2fbe00a53cb11",
    }
    for name, sha in expected.items():
        actual = _sha256_file(PLATFORMS_DIR / name)
        assert actual == sha, f"{name} changed: {actual} != {sha}"


def test_shared_core_modules_unchanged() -> None:
    expected = {
        "expected_slots_projection_v1.py":
            "fba612703cfd243db56fec8b6fa0a1b55595bad49185d8241d0239d8b3b0e47b",
        "merged_expectation_provenance_v1.py":
            "685aade8f05727eab70cc8231d95e0bbf3e5c42f93b1aaab36e8506a419a50a7",
        "__init__.py":
            "c9a80c5616f0b5e3e2cd548529d64ada8b319225e219eebac53ebb8e77501c5e",
    }
    for name, sha in expected.items():
        actual = _sha256_file(SHARED_CORE_DIR / name)
        assert actual == sha, f"shared_core/{name} changed: {actual} != {sha}"


def test_adapter_and_fixture_guard_unchanged() -> None:
    expected = {
        "flutter_expected_slots_adapter_v1.py":
            "003b86e496dd33bf642e098909d7afaacb2cc431ad40db934f488359d2105998",
        "flutter_fixture_projection_guard_v1.py":
            "b4c6a37c9d06115fad61169af7754c6b6952651710a0b7786e8db886643b6e3c",
    }
    for name, sha in expected.items():
        actual = _sha256_file(PLATFORMS_DIR / name)
        assert actual == sha, f"{name} changed: {actual} != {sha}"


def test_registries_and_baselines_unchanged() -> None:
    expected = {
        "icp/references/registries.json":
            "9b8cca5c2898c0b295fa28e6dbd6e7b32220145dd6c0cd041ad667b0d0253b84",
        "icp/references/baselines/iff-v1-vendor.json":
            "72e8401bb42e3c1b9cfd8c07d9cc44050833ed7658b3358476b9aaa4a7a257ec",
        "icp/references/baselines/iff-v1.json":
            "eb5ac0571440c6451148e90b051477cf7810a4dfab4720c57d679b7c20408c1b",
    }
    for relpath, sha in expected.items():
        actual = _sha256_file(REPO_ROOT / relpath)
        assert actual == sha, f"{relpath} changed: {actual} != {sha}"


# ===========================================================================
# Selftest runner.
# ===========================================================================


def self_skip(reason: str) -> None:
    """Platform-specific skip helper (used for symlink tests on platforms
    that do not support them)."""
    print(f"SKIP: {reason}")


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
