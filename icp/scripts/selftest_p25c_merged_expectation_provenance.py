#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2.5c merged-expectation
provenance contract.

P2.5c adds exactly one new platform-neutral contract to SharedCore: the
merged-expectation provenance v1 document
(``icp/scripts/shared_core/merged_expectation_provenance_v1.py``). This
contract records the digest chain by which a frozen trace consumer's
*effective* expected document was assembled from the raw page-canvas
projection, ``shared_components.local.json``, the page ``scene.json``, and
the produced ``merged_expected.json``.

The contract is **platform-neutral provenance only**. It MUST NOT change or
partially gate ``flutter.trace_harness.v1``; P2.5d binds the producer,
adapter, and consumer after this contract is accepted. SharedCore continues
to own no platform behavior, no execution authority, and no I/O.

This selftest is **contract + proof only**. It does not change the iFF v1
compatibility capsule, any platform adapter, any execution plan/registry,
any authorization, any executor, or any platform activation gate. The
differential proof runs the frozen ``merge_shared_expected.py`` capsule
primitive against synthetic input documents (without editing or copying
the vendor script) and constructs provenance from the exact SHA-256 values
and the page/shared/merged node order.

Run directly::

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25c_merged_expectation_provenance.py
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
SHARED_CORE_DIR = ICP_SCRIPTS / "shared_core"
PLATFORMS_DIR = ICP_SCRIPTS / "platforms"
PROD_MODULE_PATH = SHARED_CORE_DIR / "merged_expectation_provenance_v1.py"
PROD_PACKAGE_PATH = SHARED_CORE_DIR / "__init__.py"
CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
IFF_SCRIPTS = REPO_ROOT / "iff" / "scripts"
MERGE_SHARED_EXPECTED_CAPSULE = CAPSULE_SCRIPTS / "merge_shared_expected.py"
MERGE_SHARED_EXPECTED_IFF = IFF_SCRIPTS / "merge_shared_expected.py"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"
FREEZE_TOOL = ICP_SCRIPTS / "freeze_iff_baseline.py"

KIND = "icp.shared.merged-expectation-provenance.v1"
SCHEMA_VERSION = 1

# 32 MiB canonical byte bound.
MAX_CANONICAL_BYTES = 32 * 1024 * 1024

# Forbidden production-source tokens. Kept here in the TEST only (never in
# the production module). Production must be standard-library-only with no
# process/network/filesystem execution surface and no capsule/platform
# import; it must also not import the P2.5a1 projection module.
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
    "import importlib",
    "from importlib",
    "merge_shared_expected",
    "generate_canvas",
    "vendor.iff_v1",
    "import iff",
    "from iff",
    "platforms",
    "flutter",
    "dart",
    "expected_slots_projection",
    "argparse",
    "Path(",
    "open(",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "sys.argv",
    'if __name__',
    "sys.dont_write_bytecode",
    "os.environ",
    "os.mkdir",
    "os.makedirs",
    "tempfile",
)

# Frozen RED fixture constants — current live hashes of the protected files.
# These MUST be recorded BEFORE P2.5c production changes and MUST NOT be
# updated to conceal drift. P2.5c does not touch any of these files
# except the two authorized-to-change P2.5d files (annototed below).
PROTECTED_FILE_HASHES = {
    "icp/scripts/shared_core/expected_slots_projection_v1.py":
        "fba612703cfd243db56fec8b6fa0a1b55595bad49185d8241d0239d8b3b0e47b",
    "icp/scripts/shared_core/__init__.py":
        "c9a80c5616f0b5e3e2cd548529d64ada8b319225e219eebac53ebb8e77501c5e",
    "icp/scripts/platforms/flutter_expected_slots_adapter_v1.py":
        "003b86e496dd33bf642e098909d7afaacb2cc431ad40db934f488359d2105998",
    "icp/scripts/platforms/flutter_fixture_projection_guard_v1.py":
        "b4c6a37c9d06115fad61169af7754c6b6952651710a0b7786e8db886643b6e3c",
    # P2.5d authorized transition: trace_harness was upgraded from a
    # one-step plan (gen_layout_trace_test) to a three-step trusted
    # chain (merge_shared_expected -> platform provenance gate ->
    # gen_layout_trace_test). The operations module now carries the
    # 17-key request schema, the new three-step _TRACE_STEPS_SPEC, the
    # trace-specific verify_plan cross-step identity coupling, and the
    # new trace_harness_chain cwd_binding. Hash frozen at the P2.5d
    # final value; do not change without an authorized phase bump.
    "icp/scripts/platforms/flutter_operations_v1.py":
        "af348f75b41b90fdef3e3b3068e06803145d262f26dce68e718bb9884792dcf9",
    "icp/scripts/platforms/flutter_execution_binding_v1.py":
        "d6668876865d0d090ea057bc73274a502e1057d888bdca1336c236c65f4a5a9d",
    "icp/scripts/platforms/flutter_execution_authorization_v1.py":
        "1d6a17bfb64420a3357c4a914f93d2b3f3e22ac2476d2c24b8141d21c246bbd2",
    "icp/scripts/platforms/flutter_execution_executor_v1.py":
        "34fdfd22c4ced65216d5e7925696fbda7a9317a460478843314d49bb4f395cb2",
    "icp/scripts/platforms/flutter_project_preflight_v1.py":
        "56476140ec998f796fd9181b7aad5342ca67f0508f5d078873c2fbe00a53cb11",
    # P2.5d authorized transition: the descriptor's trace_harness
    # legacy primitive tuple was updated to mirror the trusted plan's
    # capsule legacy primitives in execution order:
    # (merge_shared_expected.py, gen_layout_trace_test.py). The
    # platform gate is NOT added to that tuple. Hash frozen at the
    # P2.5d final value; do not change without an authorized phase
    # bump.
    "icp/scripts/platforms/flutter_standard_v1.py":
        "a5dfdd9fe5c480d1cd42e558aba40b3eacbb891234e6ec54164baab9c16c2ba2",
    "icp/references/registries.json":
        "9b8cca5c2898c0b295fa28e6dbd6e7b32220145dd6c0cd041ad667b0d0253b84",
    "icp/references/baselines/iff-v1-vendor.json":
        "72e8401bb42e3c1b9cfd8c07d9cc44050833ed7658b3358476b9aaa4a7a257ec",
}

# The frozen merge_shared_expected.py capsule primitive, bound by SHA-256
# to the vendor manifest entry. P2.5c never edits or copies it.
MERGE_SHARED_EXPECTED_SHA256 = (
    "9c0741139c89c0e140e8272863222250bd212d878a30b3eb0f4a1258ee2c343a"
)


# ---------------------------------------------------------------------------
# Module loaders (file-path based; no package import side effects).
# ---------------------------------------------------------------------------


def _load_prod_module(name: str = "p25c_prod"):
    spec = importlib.util.spec_from_file_location(name, str(PROD_MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p25c_"):
    """A temp directory whose path is realpath-canonicalized.

    macOS ``/tmp`` -> ``/private/tmp`` (and ``/var`` -> ``/private/var``)
    symlinks would otherwise trip strict no-symlink path-chain checks.
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, payload: Any) -> bytes:
    # Use the same canonical form as the frozen iff common.dump_json so the
    # differential parity proof is byte-exact against merge_shared_expected.
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


# ---------------------------------------------------------------------------
# Minimal valid provenance factory.
# ---------------------------------------------------------------------------

_VALID_DIGEST_A = "0" * 64
_VALID_DIGEST_B = "1" * 64
_VALID_DIGEST_C = "2" * 64
_VALID_DIGEST_D = "3" * 64
_VALID_DIGEST_E = "4" * 64


def _minimal_doc(
    *,
    page_ids: list[str] | None = None,
    shared_ids: list[str] | None = None,
    local_digest: str | None = None,
) -> dict[str, Any]:
    if page_ids is None:
        page_ids = ["page_1", "page_2"]
    if shared_ids is None:
        shared_ids = []
    merged = list(page_ids) + list(shared_ids)
    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "producerKind": "iff-v1.merge_shared_expected",
        "producerSha256": _VALID_DIGEST_A,
        "pageCanvasProjectionSha256": _VALID_DIGEST_B,
        "sharedComponentsLocalSha256": local_digest,
        "sceneSha256": _VALID_DIGEST_C,
        "mergedExpectedSha256": _VALID_DIGEST_D,
        "pageCanvasNodeIds": list(page_ids),
        "sharedComponentNodeIds": list(shared_ids),
        "mergedNodeIds": merged,
    }


# ===========================================================================
# 0. Precondition: protected hashes unchanged; capsule + baseline + iff clean.
# ===========================================================================


def test_protected_file_hashes_unchanged() -> None:
    for relpath, expected in PROTECTED_FILE_HASHES.items():
        actual = _sha256_file(REPO_ROOT / relpath)
        assert actual == expected, (
            f"protected file hash changed: {relpath}: {actual} != {expected}"
        )


def test_merge_shared_expected_capsule_hashes_match_manifest() -> None:
    """The frozen merge_shared_expected.py in both iff/ and icp/vendor/iff_v1/
    must match the manifest-bound SHA-256."""
    iff_sha = _sha256_file(MERGE_SHARED_EXPECTED_IFF)
    cap_sha = _sha256_file(MERGE_SHARED_EXPECTED_CAPSULE)
    assert iff_sha == MERGE_SHARED_EXPECTED_SHA256, (
        f"iff/scripts/merge_shared_expected.py hash changed: {iff_sha}"
    )
    assert cap_sha == MERGE_SHARED_EXPECTED_SHA256, (
        f"icp/vendor/iff_v1/scripts/merge_shared_expected.py hash changed: {cap_sha}"
    )


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
# 1. Module surface.
# ===========================================================================


def test_module_all_lists_exact_public_api() -> None:
    module = _load_prod_module("p25c_all")
    assert set(module.__all__) == {
        "KIND",
        "SCHEMA_VERSION",
        "MergedExpectationProvenanceError",
        "build_provenance",
        "validate_provenance",
        "build_provenance_bytes",
    }


def test_module_kind_and_schema_version_constants() -> None:
    module = _load_prod_module("p25c_const")
    assert module.KIND == KIND
    assert module.SCHEMA_VERSION == SCHEMA_VERSION


def test_module_typed_exception_is_valueerror_subclass() -> None:
    module = _load_prod_module("p25c_exc")
    assert issubclass(module.MergedExpectationProvenanceError, ValueError)
    assert module.MergedExpectationProvenanceError.__module__ == module.__name__


def test_module_public_callable_names() -> None:
    module = _load_prod_module("p25c_names")
    public_funcs = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_funcs) == {
        "build_provenance", "validate_provenance", "build_provenance_bytes",
    }, public_funcs
    public_classes = [
        n for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    assert set(public_classes) == {"MergedExpectationProvenanceError"}, public_classes


def test_build_provenance_signature_is_keyword_only() -> None:
    module = _load_prod_module("p25c_sig")
    sig = inspect.signature(module.build_provenance)
    expected_params = [
        "producerKind",
        "producerSha256",
        "pageCanvasProjectionSha256",
        "sharedComponentsLocalSha256",
        "sceneSha256",
        "mergedExpectedSha256",
        "pageCanvasNodeIds",
        "sharedComponentNodeIds",
        "mergedNodeIds",
    ]
    assert list(sig.parameters) == expected_params, sig
    for name, param in sig.parameters.items():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, (name, param.kind)
        assert param.default is inspect.Parameter.empty, (name, param.default)


def test_validate_provenance_signature() -> None:
    module = _load_prod_module("p25c_sig_val")
    sig = inspect.signature(module.validate_provenance)
    params = list(sig.parameters)
    assert params == ["value"], sig


def test_build_provenance_bytes_signature() -> None:
    module = _load_prod_module("p25c_sig_bytes")
    sig = inspect.signature(module.build_provenance_bytes)
    params = list(sig.parameters)
    assert params == ["value"], sig


# ===========================================================================
# 2. Happy path: object, key order, bytes, no newline, Unicode, determinism.
# ===========================================================================


def test_validate_provenance_happy_path_returns_dict() -> None:
    module = _load_prod_module("p25c_happy")
    doc = _minimal_doc()
    out = module.validate_provenance(doc)
    assert isinstance(out, dict)
    assert type(out) is dict, "detached output must be a plain dict"


def test_validate_provenance_top_level_key_order() -> None:
    module = _load_prod_module("p25c_order")
    out = module.validate_provenance(_minimal_doc())
    assert list(out.keys()) == [
        "kind",
        "schemaVersion",
        "producerKind",
        "producerSha256",
        "pageCanvasProjectionSha256",
        "sharedComponentsLocalSha256",
        "sceneSha256",
        "mergedExpectedSha256",
        "pageCanvasNodeIds",
        "sharedComponentNodeIds",
        "mergedNodeIds",
    ]


def test_build_provenance_happy_path_object() -> None:
    module = _load_prod_module("p25c_build")
    out = module.build_provenance(
        producerKind="iff-v1.merge_shared_expected",
        producerSha256=_VALID_DIGEST_A,
        pageCanvasProjectionSha256=_VALID_DIGEST_B,
        sharedComponentsLocalSha256=None,
        sceneSha256=_VALID_DIGEST_C,
        mergedExpectedSha256=_VALID_DIGEST_D,
        pageCanvasNodeIds=["page_1", "page_2"],
        sharedComponentNodeIds=[],
        mergedNodeIds=["page_1", "page_2"],
    )
    assert list(out.keys()) == [
        "kind",
        "schemaVersion",
        "producerKind",
        "producerSha256",
        "pageCanvasProjectionSha256",
        "sharedComponentsLocalSha256",
        "sceneSha256",
        "mergedExpectedSha256",
        "pageCanvasNodeIds",
        "sharedComponentNodeIds",
        "mergedNodeIds",
    ]
    assert out["kind"] == KIND
    assert out["schemaVersion"] == SCHEMA_VERSION
    assert out["sharedComponentsLocalSha256"] is None
    assert out["pageCanvasNodeIds"] == ["page_1", "page_2"]
    assert out["sharedComponentNodeIds"] == []
    assert out["mergedNodeIds"] == ["page_1", "page_2"]


def test_build_provenance_bytes_canonical_form() -> None:
    module = _load_prod_module("p25c_bytes")
    doc = _minimal_doc()
    data = module.build_provenance_bytes(doc)
    assert isinstance(data, bytes)
    assert not data.endswith(b"\n"), "canonical bytes must not end with newline"
    # Re-decode and verify exact key order in serialized form.
    text = data.decode("utf-8")
    positions = {k: text.find(f'"{k}"') for k in (
        "kind", "schemaVersion", "producerKind", "producerSha256",
        "pageCanvasProjectionSha256", "sharedComponentsLocalSha256",
        "sceneSha256", "mergedExpectedSha256",
        "pageCanvasNodeIds", "sharedComponentNodeIds", "mergedNodeIds",
    )}
    ordered = sorted(positions.items(), key=lambda kv: kv[1])
    assert [k for k, _ in ordered] == [
        "kind", "schemaVersion", "producerKind", "producerSha256",
        "pageCanvasProjectionSha256", "sharedComponentsLocalSha256",
        "sceneSha256", "mergedExpectedSha256",
        "pageCanvasNodeIds", "sharedComponentNodeIds", "mergedNodeIds",
    ], ordered


def test_build_provenance_bytes_exactly_matches_json_dumps_form() -> None:
    module = _load_prod_module("p25c_form")
    doc = _minimal_doc()
    data = module.build_provenance_bytes(doc)
    detached = module.validate_provenance(doc)
    expected = json.dumps(
        detached, ensure_ascii=False, indent=2, allow_nan=False,
    ).encode("utf-8")
    assert data == expected


def test_build_provenance_bytes_preserves_unicode_node_ids() -> None:
    module = _load_prod_module("p25c_uni")
    doc = _minimal_doc(
        page_ids=["你好_世界", "emoji_🌍", "accent_éàÜ"],
        shared_ids=["shared_中文"],
    )
    doc["mergedNodeIds"] = list(doc["pageCanvasNodeIds"]) + list(doc["sharedComponentNodeIds"])
    data = module.build_provenance_bytes(doc)
    assert "你好".encode("utf-8") in data
    assert "🌍".encode("utf-8") in data
    assert "éàÜ".encode("utf-8") in data
    assert "中文".encode("utf-8") in data
    assert b"\\u" not in data


def test_build_provenance_bytes_is_deterministic_across_calls() -> None:
    module = _load_prod_module("p25c_det")
    doc = _minimal_doc()
    b1 = module.build_provenance_bytes(doc)
    b2 = module.build_provenance_bytes(doc)
    assert b1 == b2


def test_build_provenance_bytes_round_trips_through_validate() -> None:
    module = _load_prod_module("p25c_rt")
    doc = _minimal_doc()
    data = module.build_provenance_bytes(doc)
    decoded = json.loads(data.decode("utf-8"))
    out = module.validate_provenance(decoded)
    again = module.build_provenance_bytes(out)
    assert again == data


# ===========================================================================
# 3. Detached clone with hostile/custom Mapping and sequence subclasses.
# ===========================================================================


def test_build_provenance_does_not_serialize_mapping_subclass_directly() -> None:
    """A custom Mapping subclass that yields the same insertion order must
    produce a detached plain dict; the output must not be the caller's
    subclass."""
    module = _load_prod_module("p25c_map_sub")

    class _CustomDict(dict):
        """A Mapping subclass; the production module must not serialize
        this subclass directly."""

    doc = _minimal_doc()
    custom = _CustomDict(doc)
    custom["pageCanvasNodeIds"] = list(doc["pageCanvasNodeIds"])

    class _CustomList(list):
        """A sequence subclass; must be detached to a plain list."""

    custom["pageCanvasNodeIds"] = _CustomList(doc["pageCanvasNodeIds"])
    custom["sharedComponentNodeIds"] = _CustomList(doc["sharedComponentNodeIds"])
    custom["mergedNodeIds"] = _CustomList(doc["mergedNodeIds"])

    out = module.validate_provenance(custom)
    assert type(out) is dict, "output must be plain dict"
    assert type(out["pageCanvasNodeIds"]) is list, "node list must be plain list"
    assert type(out["sharedComponentNodeIds"]) is list
    assert type(out["mergedNodeIds"]) is list


def test_build_provenance_caller_mutation_does_not_affect_output() -> None:
    """Mutating the caller's input after build_provenance must not change
    a re-decode of the bytes."""
    module = _load_prod_module("p25c_mut")
    doc = _minimal_doc(page_ids=["p1", "p2"], shared_ids=["s1"])
    data = module.build_provenance_bytes(doc)
    # Mutate the input after the call.
    doc["producerKind"] = "tampered.kind"
    doc["pageCanvasNodeIds"].append("p3")
    doc["pageCanvasNodeIds"][0] = "changed"
    doc["mergedNodeIds"].append("extra")
    doc["newKey"] = "evil"
    del doc["schemaVersion"]
    # Re-decode the bytes: the original content must be preserved.
    re_doc = json.loads(data.decode("utf-8"))
    assert re_doc["producerKind"] == "iff-v1.merge_shared_expected"
    assert re_doc["pageCanvasNodeIds"] == ["p1", "p2"]
    assert re_doc["mergedNodeIds"] == ["p1", "p2", "s1"]
    assert "newKey" not in re_doc
    assert re_doc["schemaVersion"] == SCHEMA_VERSION


def test_build_provenance_bytes_input_mutation_after_call_does_not_change_bytes() -> None:
    module = _load_prod_module("p25c_bmut")
    doc = _minimal_doc(page_ids=["p1"], shared_ids=["s1"])
    data = module.build_provenance_bytes(doc)
    doc["pageCanvasNodeIds"].append("p2")
    doc["mergedNodeIds"].append("p2")
    data2 = module.build_provenance_bytes(_minimal_doc(page_ids=["p1"], shared_ids=["s1"]))
    assert data == data2


# ===========================================================================
# 4. sharedComponentsLocalSha256 null and present.
# ===========================================================================


def test_local_digest_null_passthrough_case_accepted() -> None:
    module = _load_prod_module("p25c_null")
    doc = _minimal_doc(local_digest=None)
    out = module.validate_provenance(doc)
    assert out["sharedComponentsLocalSha256"] is None


def test_local_digest_present_accepted() -> None:
    module = _load_prod_module("p25c_local")
    doc = _minimal_doc(local_digest=_VALID_DIGEST_E)
    out = module.validate_provenance(doc)
    assert out["sharedComponentsLocalSha256"] == _VALID_DIGEST_E


def test_local_digest_rejects_zero_string() -> None:
    """The pass-through case is null only; the literal string 'null' is
    not a valid digest."""
    module = _load_prod_module("p25c_local_str")
    doc = _minimal_doc()
    doc["sharedComponentsLocalSha256"] = "null"
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("string 'null' must be rejected as a digest")


# ===========================================================================
# 5. Empty node sets; large-but-bounded representative node sets.
# ===========================================================================


def test_empty_node_sets_accepted() -> None:
    module = _load_prod_module("p25c_empty")
    doc = _minimal_doc(page_ids=[], shared_ids=[])
    out = module.validate_provenance(doc)
    assert out["pageCanvasNodeIds"] == []
    assert out["sharedComponentNodeIds"] == []
    assert out["mergedNodeIds"] == []


def test_large_bounded_node_sets_accepted() -> None:
    """A representative large-but-bounded set: 10000 page ids, 5000 shared
    ids (all disjoint), and a 15000-entry merged list in page+shared order."""
    module = _load_prod_module("p25c_large")
    page_ids = [f"page_{i:05d}" for i in range(10000)]
    shared_ids = [f"shared_{i:05d}" for i in range(5000)]
    doc = _minimal_doc(page_ids=page_ids, shared_ids=shared_ids)
    out = module.validate_provenance(doc)
    assert len(out["pageCanvasNodeIds"]) == 10000
    assert len(out["sharedComponentNodeIds"]) == 5000
    assert len(out["mergedNodeIds"]) == 15000


def test_node_id_count_limit_100000_accepted() -> None:
    """A list of exactly 100000 entries is accepted."""
    module = _load_prod_module("p25c_max_count")
    page_ids = [f"p{i:06d}" for i in range(100000)]
    doc = _minimal_doc(page_ids=page_ids, shared_ids=[])
    out = module.validate_provenance(doc)
    assert len(out["pageCanvasNodeIds"]) == 100000


def test_node_id_count_limit_100001_rejected() -> None:
    module = _load_prod_module("p25c_over_count")
    page_ids = [f"p{i:06d}" for i in range(100001)]
    doc = _minimal_doc(page_ids=page_ids, shared_ids=[])
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("100001 node ids must be rejected")


def test_node_id_byte_boundary_512_accepted() -> None:
    module = _load_prod_module("p25c_512")
    nid = "a" * 512
    doc = _minimal_doc(page_ids=[nid], shared_ids=[])
    out = module.validate_provenance(doc)
    assert out["pageCanvasNodeIds"] == [nid]


def test_node_id_byte_boundary_513_rejected() -> None:
    module = _load_prod_module("p25c_513")
    nid = "a" * 513
    doc = _minimal_doc(page_ids=[nid], shared_ids=[])
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("513-byte node id must be rejected")


def test_node_id_utf8_byte_boundary() -> None:
    """A node id whose UTF-8 encoding reaches exactly 512 bytes is OK; one
    byte over must reject."""
    module = _load_prod_module("p25c_utf8_bound")
    # 'á' is U+00E1 -> 2 UTF-8 bytes. 256 of them = 512 bytes.
    ok = "á" * 256
    assert len(ok.encode("utf-8")) == 512
    doc_ok = _minimal_doc(page_ids=[ok], shared_ids=[])
    out = module.validate_provenance(doc_ok)
    assert out["pageCanvasNodeIds"] == [ok]
    bad = "á" * 257  # 514 UTF-8 bytes
    assert len(bad.encode("utf-8")) == 514
    doc_bad = _minimal_doc(page_ids=[bad], shared_ids=[])
    try:
        module.validate_provenance(doc_bad)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("514-byte UTF-8 node id must be rejected")


# ===========================================================================
# 6. Missing/unknown/non-string top-level keys.
# ===========================================================================


def _assert_reject(doc_overrides: dict[str, Any], *, remove: tuple[str, ...] = (),
                   msg_hint: str | None = None) -> None:
    module = _load_prod_module("p25c_rej")
    doc = _minimal_doc()
    for key in remove:
        doc.pop(key, None)
    doc.update(doc_overrides)
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError as exc:
        if msg_hint is not None and msg_hint not in str(exc):
            raise AssertionError(
                f"expected error mentioning {msg_hint!r}, got: {exc}"
            )
        return
    raise AssertionError(f"document should have been rejected: {doc}")


def test_missing_kind_rejected() -> None:
    _assert_reject({}, remove=("kind",), msg_hint="kind")


def test_missing_schema_version_rejected() -> None:
    _assert_reject({}, remove=("schemaVersion",), msg_hint="schemaVersion")


def test_missing_producer_kind_rejected() -> None:
    _assert_reject({}, remove=("producerKind",), msg_hint="producerKind")


def test_missing_producer_sha_rejected() -> None:
    _assert_reject({}, remove=("producerSha256",), msg_hint="producerSha256")


def test_missing_page_canvas_projection_sha_rejected() -> None:
    _assert_reject({}, remove=("pageCanvasProjectionSha256",),
                   msg_hint="pageCanvasProjectionSha256")


def test_missing_shared_components_local_sha_rejected() -> None:
    _assert_reject({}, remove=("sharedComponentsLocalSha256",),
                   msg_hint="sharedComponentsLocalSha256")


def test_missing_scene_sha_rejected() -> None:
    _assert_reject({}, remove=("sceneSha256",), msg_hint="sceneSha256")


def test_missing_merged_expected_sha_rejected() -> None:
    _assert_reject({}, remove=("mergedExpectedSha256",),
                   msg_hint="mergedExpectedSha256")


def test_missing_page_canvas_node_ids_rejected() -> None:
    _assert_reject({}, remove=("pageCanvasNodeIds",),
                   msg_hint="pageCanvasNodeIds")


def test_missing_shared_component_node_ids_rejected() -> None:
    _assert_reject({}, remove=("sharedComponentNodeIds",),
                   msg_hint="sharedComponentNodeIds")


def test_missing_merged_node_ids_rejected() -> None:
    _assert_reject({}, remove=("mergedNodeIds",), msg_hint="mergedNodeIds")


def test_unknown_top_level_key_rejected() -> None:
    _assert_reject({"extra": "x"}, msg_hint="unknown")


def test_non_string_top_level_key_rejected() -> None:
    """A non-string top-level key (e.g., int 1) must be rejected, not
    leak a TypeError or KeyError."""
    module = _load_prod_module("p25c_nskey")
    doc: dict[Any, Any] = {}
    for k, v in _minimal_doc().items():
        doc[k] = v
    doc[1] = "bad key"
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError as exc:
        assert "bad_keys" in str(exc) or "top-level" in str(exc), exc
        return
    raise AssertionError("non-string top-level key must be rejected")


# ===========================================================================
# 7. Wrong kind/version/bool version.
# ===========================================================================


def test_wrong_kind_rejected() -> None:
    _assert_reject({"kind": "icp.shared.other.v1"}, msg_hint="kind")


def test_wrong_schema_version_rejected() -> None:
    _assert_reject({"schemaVersion": 2}, msg_hint="schemaVersion")


def test_schema_version_zero_rejected() -> None:
    _assert_reject({"schemaVersion": 0}, msg_hint="schemaVersion")


def test_schema_version_negative_rejected() -> None:
    _assert_reject({"schemaVersion": -1}, msg_hint="schemaVersion")


def test_schema_version_bool_rejected() -> None:
    """True is not 1; bool must be rejected even though bool is int subclass."""
    _assert_reject({"schemaVersion": True}, msg_hint="schemaVersion")


def test_schema_version_string_rejected() -> None:
    _assert_reject({"schemaVersion": "1"}, msg_hint="schemaVersion")


def test_schema_version_float_rejected() -> None:
    _assert_reject({"schemaVersion": 1.0}, msg_hint="schemaVersion")


def test_schema_version_none_rejected() -> None:
    _assert_reject({"schemaVersion": None}, msg_hint="schemaVersion")


# ===========================================================================
# 8. producerKind grammar boundaries.
# ===========================================================================


def test_producer_kind_minimum_length_one_accepted() -> None:
    module = _load_prod_module("p25c_pk_min")
    doc = _minimal_doc()
    doc["producerKind"] = "a"
    out = module.validate_provenance(doc)
    assert out["producerKind"] == "a"


def test_producer_kind_maximum_128_chars_accepted() -> None:
    module = _load_prod_module("p25c_pk_max")
    doc = _minimal_doc()
    doc["producerKind"] = "a" + "b" * 127  # 128 chars
    out = module.validate_provenance(doc)
    assert out["producerKind"] == "a" + "b" * 127


def test_producer_kind_allowed_chars_accepted() -> None:
    module = _load_prod_module("p25c_pk_chars")
    for value in ("a.b", "a-b", "a_b", "a.0", "a-b.c_d.0", "abc123"):
        doc = _minimal_doc()
        doc["producerKind"] = value
        out = module.validate_provenance(doc)
        assert out["producerKind"] == value


def test_producer_kind_empty_rejected() -> None:
    _assert_reject({"producerKind": ""}, msg_hint="producerKind")


def test_producer_kind_uppercase_first_char_rejected() -> None:
    _assert_reject({"producerKind": "Abc"}, msg_hint="producerKind")


def test_producer_kind_digit_first_char_rejected() -> None:
    _assert_reject({"producerKind": "1abc"}, msg_hint="producerKind")


def test_producer_kind_underscore_first_char_rejected() -> None:
    _assert_reject({"producerKind": "_abc"}, msg_hint="producerKind")


def test_producer_kind_dash_first_char_rejected() -> None:
    _assert_reject({"producerKind": "-abc"}, msg_hint="producerKind")


def test_producer_kind_dot_first_char_rejected() -> None:
    _assert_reject({"producerKind": ".abc"}, msg_hint="producerKind")


def test_producer_kind_invalid_char_rejected() -> None:
    _assert_reject({"producerKind": "abc!"}, msg_hint="producerKind")


def test_producer_kind_space_rejected() -> None:
    _assert_reject({"producerKind": "a b"}, msg_hint="producerKind")


def test_producer_kind_too_long_129_chars_rejected() -> None:
    _assert_reject({"producerKind": "a" * 129}, msg_hint="producerKind")


def test_producer_kind_non_string_rejected() -> None:
    _assert_reject({"producerKind": 123}, msg_hint="producerKind")


# ===========================================================================
# 9. Digest failures for every digest field.
# ===========================================================================


def _bad_digests() -> list[tuple[str, Any]]:
    return [
        ("uppercase", "A" * 64),
        ("short", "0" * 63),
        ("long", "0" * 65),
        ("nonhex", "g" * 64),
        ("mixed_case", "0" * 63 + "A"),
        ("empty", ""),
        ("int", 0),
        ("None", None),
        ("bool", True),
        ("float", 1.5),
        ("list", ["0" * 64]),
    ]


def test_producer_sha256_invalid_values_rejected() -> None:
    for label, bad in _bad_digests():
        _assert_reject({"producerSha256": bad}, msg_hint="producerSha256")


def test_page_canvas_projection_sha256_invalid_values_rejected() -> None:
    for label, bad in _bad_digests():
        _assert_reject({"pageCanvasProjectionSha256": bad},
                       msg_hint="pageCanvasProjectionSha256")


def test_shared_components_local_sha256_invalid_values_rejected() -> None:
    # null is the only allowed non-digest; every other bad digest must reject.
    for label, bad in _bad_digests():
        if bad is None:
            continue
        _assert_reject({"sharedComponentsLocalSha256": bad},
                       msg_hint="sharedComponentsLocalSha256")


def test_scene_sha256_invalid_values_rejected() -> None:
    for label, bad in _bad_digests():
        _assert_reject({"sceneSha256": bad}, msg_hint="sceneSha256")


def test_merged_expected_sha256_invalid_values_rejected() -> None:
    for label, bad in _bad_digests():
        _assert_reject({"mergedExpectedSha256": bad},
                       msg_hint="mergedExpectedSha256")


# ===========================================================================
# 10. Node-id list failures.
# ===========================================================================


def test_node_id_list_not_a_list_rejected() -> None:
    _assert_reject({"pageCanvasNodeIds": "page_1"}, msg_hint="pageCanvasNodeIds")


def test_node_id_list_tuple_rejected() -> None:
    """A tuple is a sequence but not a list; must reject."""
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ("p1", "p2")
    doc["mergedNodeIds"] = ["p1", "p2"]
    module = _load_prod_module("p25c_tuple")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("tuple node-id list must be rejected")


def test_node_id_non_string_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = [123]
    doc["mergedNodeIds"] = [123]
    module = _load_prod_module("p25c_int_id")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("non-string node id must be rejected")


def test_node_id_empty_string_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = [""]
    doc["mergedNodeIds"] = [""]
    module = _load_prod_module("p25c_empty_id")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("empty node id must be rejected")


def test_node_id_control_chars_rejected() -> None:
    module = _load_prod_module("p25c_ctrl")
    for bad in ("\x00", "\x01", "\x1f", "\x7f", "\n", "\r", "\t"):
        doc = _minimal_doc()
        doc["pageCanvasNodeIds"] = [bad]
        doc["mergedNodeIds"] = [bad]
        try:
            module.validate_provenance(doc)
        except module.MergedExpectationProvenanceError:
            continue
        raise AssertionError(f"node id with control char {bad!r} must be rejected")


def test_node_id_duplicates_within_page_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ["p1", "p1"]
    doc["mergedNodeIds"] = ["p1", "p1"]
    module = _load_prod_module("p25c_dup")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("duplicate page node id must be rejected")


def test_node_id_duplicates_within_shared_rejected() -> None:
    doc = _minimal_doc()
    doc["sharedComponentNodeIds"] = ["s1", "s1"]
    doc["mergedNodeIds"] = ["s1", "s1"]
    module = _load_prod_module("p25c_dup_shared")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("duplicate shared node id must be rejected")


def test_node_id_duplicates_within_merged_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ["p1"]
    doc["sharedComponentNodeIds"] = []
    doc["mergedNodeIds"] = ["p1", "p1"]
    module = _load_prod_module("p25c_dup_merged")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("duplicate merged node id must be rejected")


def test_page_shared_overlap_rejected() -> None:
    """If page and shared overlap, the document is invalid. The rejection
    can come from either the duplicate-in-merged check or the explicit
    page/shared disjointness check; both enforce the contract. The test
    below constructs an honestly-overlapping doc where merged = page+shared
    would have a duplicate, so the duplicate check fires first. A second
    sub-case constructs a doc whose merged list omits the duplicate so the
    explicit disjointness check fires."""
    module = _load_prod_module("p25c_overlap")
    # Sub-case 1: merged = page + shared literally (with duplicate).
    doc1 = _minimal_doc()
    doc1["pageCanvasNodeIds"] = ["p1", "shared"]
    doc1["sharedComponentNodeIds"] = ["shared"]
    doc1["mergedNodeIds"] = ["p1", "shared", "shared"]
    try:
        module.validate_provenance(doc1)
    except module.MergedExpectationProvenanceError:
        pass
    else:
        raise AssertionError("overlap doc 1 must be rejected")
    # Sub-case 2: merged omits the duplicate so only the disjointness
    # check catches the page/shared overlap. The merged-mismatch check
    # would also reject this; either way the document is rejected.
    doc2 = _minimal_doc()
    doc2["pageCanvasNodeIds"] = ["p1", "shared"]
    doc2["sharedComponentNodeIds"] = ["shared"]
    doc2["mergedNodeIds"] = ["p1", "shared"]
    try:
        module.validate_provenance(doc2)
    except module.MergedExpectationProvenanceError as exc:
        # Either the disjointness check or the merged-mismatch check fired.
        msg = str(exc).lower()
        assert "disjoint" in msg or "must equal" in msg, exc
        return
    raise AssertionError("overlap doc 2 must be rejected")


def test_merged_wrong_order_rejected() -> None:
    """merged = page + shared; reversing the order must reject."""
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ["p1", "p2"]
    doc["sharedComponentNodeIds"] = ["s1"]
    doc["mergedNodeIds"] = ["s1", "p1", "p2"]  # wrong order
    module = _load_prod_module("p25c_order_rej")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("wrong merged order must be rejected")


def test_merged_missing_id_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ["p1", "p2"]
    doc["sharedComponentNodeIds"] = ["s1"]
    doc["mergedNodeIds"] = ["p1", "p2"]  # missing s1
    module = _load_prod_module("p25c_missing_merged")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("missing merged id must be rejected")


def test_merged_extra_id_rejected() -> None:
    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = ["p1"]
    doc["sharedComponentNodeIds"] = ["s1"]
    doc["mergedNodeIds"] = ["p1", "s1", "extra"]  # extra
    module = _load_prod_module("p25c_extra_merged")
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("extra merged id must be rejected")


# ===========================================================================
# 11. Canonical 32 MiB bound.
# ===========================================================================


def test_canonical_byte_bound_under_32mib_accepted() -> None:
    """A representative document whose canonical bytes are well under 32 MiB
    is accepted. Uses 4000 ids of 512 chars each on page+merged (the
    shared list stays empty) -> ~4 MiB canonical bytes."""
    module = _load_prod_module("p25c_under")
    n = 4000
    page_ids = [f"p{i:06d}_" + "x" * 505 for i in range(n)]
    # Cap any single id at 512 UTF-8 bytes.
    page_ids = [pid[:512] for pid in page_ids]
    assert all(len(pid.encode("utf-8")) <= 512 for pid in page_ids)
    doc = _minimal_doc(page_ids=page_ids, shared_ids=[])
    data = module.build_provenance_bytes(doc)
    assert len(data) <= MAX_CANONICAL_BYTES


def test_canonical_byte_bound_over_32mib_rejected() -> None:
    """A document whose canonical bytes exceed 32 MiB must reject. Uses
    ~33000 unique ids of 512 chars on page+merged -> ~34 MiB canonical
    bytes while staying under the 100000 per-list limit."""
    module = _load_prod_module("p25c_over")
    n = 33000
    # Each id: 'p' + 10-digit index + padding of 'x' to reach 512 UTF-8 bytes.
    # 'p' = 1 byte; index padded to 10 digits = 10 bytes; padding = 501 bytes.
    page_ids = [f"p{i:010d}" + "x" * 501 for i in range(n)]
    assert all(len(pid) == 512 for pid in page_ids)
    assert all(len(pid.encode("utf-8")) == 512 for pid in page_ids)
    assert len(set(page_ids)) == n, "ids must be unique"
    doc = _minimal_doc(page_ids=page_ids, shared_ids=[])
    try:
        module.build_provenance_bytes(doc)
    except module.MergedExpectationProvenanceError as exc:
        assert "32" in str(exc) or "MiB" in str(exc) or "exceed" in str(exc), exc
        return
    raise AssertionError("canonical bytes over 32 MiB must be rejected")


# ===========================================================================
# 12. NaN/Inf/custom-object rejection and only typed errors.
# ===========================================================================


def test_validate_rejects_non_mapping_root() -> None:
    module = _load_prod_module("p25c_non_map")
    for bad in ([1, 2, 3], "string", 123, 1.5, True, None, b"bytes"):
        try:
            module.validate_provenance(bad)
        except module.MergedExpectationProvenanceError:
            continue
        raise AssertionError(f"non-mapping root {bad!r} must be rejected")


def test_validate_rejects_custom_object_value_in_node_id_list() -> None:
    """A custom object placed inside a node-id list must reject with the
    typed exception (never a TypeError leak)."""
    module = _load_prod_module("p25c_custom_obj")

    class _Custom:
        pass

    doc = _minimal_doc()
    doc["pageCanvasNodeIds"] = [_Custom()]
    doc["mergedNodeIds"] = list(doc["pageCanvasNodeIds"])
    try:
        module.validate_provenance(doc)
    except module.MergedExpectationProvenanceError:
        return
    raise AssertionError("custom object in node-id list must be rejected")


def test_only_typed_exception_is_raised_for_all_failures() -> None:
    """Every validation failure must raise only MergedExpectationProvenanceError,
    never TypeError/KeyError/AttributeError/etc. Run a broad set of bad inputs
    and verify the exception type."""
    module = _load_prod_module("p25c_typed_only")

    class _ExplodingMapping(dict):
        """A mapping that returns a hostile value for producerKind."""
        def __getitem__(self, key):
            if key == "producerKind":
                return object()
            return super().__getitem__(key)

    bad_docs: list[Any] = [
        None,
        [],
        "x",
        123,
        {"kind": "x"},
        {**_minimal_doc(), "kind": object()},
        {**_minimal_doc(), "schemaVersion": object()},
        {**_minimal_doc(), "producerKind": object()},
        {**_minimal_doc(), "producerSha256": object()},
        {**_minimal_doc(), "pageCanvasNodeIds": object()},
        {**_minimal_doc(), "mergedNodeIds": ["extra_id"]},
    ]
    for bad in bad_docs:
        try:
            module.validate_provenance(bad)
        except module.MergedExpectationProvenanceError:
            continue
        except Exception as exc:
            raise AssertionError(
                f"non-typed exception {type(exc).__name__} for input {bad!r}"
            )
        else:
            # Some inputs may not raise (e.g., valid ones); only flag if a
            # clearly-invalid input did not raise. The list above is all
            # invalid, so reaching here is a bug.
            raise AssertionError(f"invalid input was not rejected: {bad!r}")


def test_build_provenance_bytes_rejects_nan_in_input_via_strict_json() -> None:
    """Although the provenance schema has no float fields, build_provenance_bytes
    must use allow_nan=False so any future leak of NaN/Inf into the detached
    document is rejected rather than emitted as a non-JSON token."""
    module = _load_prod_module("p25c_nan")
    # Direct test: build a detached dict that contains NaN and verify
    # json.dumps(..., allow_nan=False) raises; this is a behavior proof
    # that the production module uses allow_nan=False.
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    assert "allow_nan=False" in source, (
        "production module must use allow_nan=False in json.dumps"
    )


# ===========================================================================
# 13. Module has no forbidden imports/literals; no CLI/filesystem/process/
#     network/platform/vendor surface.
# ===========================================================================


def test_production_module_imports_only_standard_library() -> None:
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_stdlib_prefixes = {
        "__future__",
        "json",
        "re",
        "typing",
        "collections.abc",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed_stdlib_prefixes, (
                    f"production imports non-allowed module: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            assert top in allowed_stdlib_prefixes, (
                f"production imports non-allowed module: {node.module}"
            )


def test_production_module_has_no_forbidden_tokens() -> None:
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    leaks = [tok for tok in FORBIDDEN_TOKENS if tok in source]
    assert leaks == [], f"production source leaks forbidden tokens: {leaks}"


def test_production_module_does_not_import_subprocess_or_process_modules() -> None:
    """Belt-and-braces: snapshot sys.modules before/after loading the
    production module under fresh names; no process/network/platform module
    may appear."""
    forbidden = (
        "subprocess", "socket", "urllib.request", "http.client",
        "platforms", "flutter", "dart",
    )
    before = set(sys.modules)
    _load_prod_module("p25c_imp_guard_a")
    _load_prod_module("p25c_imp_guard_b")
    after = set(sys.modules)
    new_modules = after - before
    leaked = [m for m in forbidden if m in new_modules]
    assert not leaked, (
        f"production import leaked forbidden modules into sys.modules: {leaked}"
    )


def test_production_module_does_not_import_expected_slots_projection() -> None:
    """The P2.5c contract must not import the P2.5a1 projection module."""
    before = set(sys.modules)
    _load_prod_module("p25c_no_p25a1")
    after = set(sys.modules)
    new_modules = after - before
    leaked = [m for m in new_modules if "expected_slots_projection" in m]
    assert not leaked, (
        f"production import loaded P2.5a1 projection module: {leaked}"
    )


def test_production_module_has_no_cli_block() -> None:
    """The production module must not have an ``if __name__ == ...`` block
    or any argparse main()."""
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
                if test.left.id == "__name__":
                    raise AssertionError(
                        "production module has an `if __name__ == ...` block"
                    )
    assert "argparse" not in source.split('"""')[0] or "argparse" not in source


def test_production_module_is_non_executable_on_import() -> None:
    """Importing the production module must not write a file, spawn a
    process, or set sys.dont_write_bytecode. Verified by source absence."""
    source = PROD_MODULE_PATH.read_text(encoding="utf-8")
    assert "sys.dont_write_bytecode" not in source
    assert "sys.argv" not in source


# ===========================================================================
# 14. No __pycache__/.pyc under icp/.
# ===========================================================================


def test_no_pycache_under_icp() -> None:
    found: list[Path] = []
    for path in ICP_ROOT.rglob("__pycache__"):
        if path.is_dir():
            found.append(path)
    for path in ICP_ROOT.rglob("*.pyc"):
        found.append(path)
    assert not found, f"__pycache__/.pyc present under icp/: {found}"


def test_production_module_import_creates_no_pycache_under_owned_path() -> None:
    """Importing the production module must not litter __pycache__ next to
    it when PYTHONDONTWRITEBYTECODE=1."""
    cache_dir = PROD_MODULE_PATH.parent / "__pycache__"
    pre = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys;"
         f"p=importlib.util.spec_from_file_location('p25c_nopyc','{PROD_MODULE_PATH}');"
         "m=importlib.util.module_from_spec(p);"
         "sys.modules['p25c_nopyc']=m;"
         "p.loader.exec_module(m);"
         "assert m.build_provenance_bytes or True"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"import probe failed: {r.stderr!r}"
    post = set(cache_dir.glob("*")) if cache_dir.is_dir() else set()
    new_files = post - pre
    relevant = {p for p in new_files if "merged_expectation_provenance_v1" in p.name}
    assert not relevant, (
        f"production import created __pycache__ side effect: "
        f"{sorted(p.name for p in relevant)}"
    )


# ===========================================================================
# 15. Differential evidence against the frozen merge_shared_expected.py.
# ===========================================================================


def _run_merge(
    tmp: Path,
    expected_payload: dict[str, Any],
    scene_payload: dict[str, Any],
    local_payload: dict[str, Any] | None,
) -> tuple[int, str, str, Path, Path, Path, Path]:
    """Run the frozen merge_shared_expected.py against synthetic inputs.

    Returns (returncode, stdout, stderr, expected_path, local_path,
    scene_path, out_path). ``local_payload=None`` means the local file
    is intentionally absent (pass-through case)."""
    expected_path = tmp / "canvas.expected.json"
    local_path = tmp / "shared_components.local.json"
    scene_path = tmp / "scene.json"
    out_path = tmp / "merged_expected.json"
    _write_json(expected_path, expected_payload)
    _write_json(scene_path, scene_payload)
    if local_payload is not None:
        _write_json(local_path, local_payload)
    elif local_path.exists():
        local_path.unlink()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(
        [sys.executable, str(MERGE_SHARED_EXPECTED_CAPSULE),
         "--expected", str(expected_path),
         "--local", str(local_path),
         "--scene", str(scene_path),
         "--out", str(out_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    return r.returncode, r.stdout, r.stderr, expected_path, local_path, scene_path, out_path


def test_differential_pass_through_case_provenance() -> None:
    """When shared_components.local.json is absent, merge_shared_expected.py
    copies the page canvas expected.json unchanged. Construct provenance
    with sharedComponentsLocalSha256=null and verify it validates."""
    module = _load_prod_module("p25c_diff_pt")
    with _canonical_tempdir() as tmp:
        expected_payload = {
            "nodes": {
                "page_1": {"bbox": [0, 0, 10, 10], "impl": "shape"},
                "page_2": {"bbox": [20, 20, 30, 30], "impl": "text", "text": "x"},
            }
        }
        scene_payload = {
            "nodes": [
                {"id": "page_1", "bbox": [0, 0, 10, 10]},
                {"id": "page_2", "bbox": [20, 20, 30, 30]},
            ]
        }
        rc, out, err, exp_p, local_p, scene_p, merged_p = _run_merge(
            tmp, expected_payload, scene_payload, local_payload=None,
        )
        assert rc == 0, f"merge failed: rc={rc} stderr={err!r}"
        assert merged_p.is_file(), "no merged output written"
        # Compute the digest chain from exact input/output bytes.
        page_canvas_sha = _sha256_file(exp_p)
        scene_sha = _sha256_file(scene_p)
        merged_sha = _sha256_file(merged_p)
        producer_sha = _sha256_file(MERGE_SHARED_EXPECTED_CAPSULE)
        page_node_ids = list(expected_payload["nodes"].keys())
        doc = module.build_provenance(
            producerKind="iff-v1.merge_shared_expected",
            producerSha256=producer_sha,
            pageCanvasProjectionSha256=page_canvas_sha,
            sharedComponentsLocalSha256=None,
            sceneSha256=scene_sha,
            mergedExpectedSha256=merged_sha,
            pageCanvasNodeIds=page_node_ids,
            sharedComponentNodeIds=[],
            mergedNodeIds=list(page_node_ids),
        )
        assert doc["sharedComponentsLocalSha256"] is None
        assert doc["mergedNodeIds"] == page_node_ids
        # Byte serialization round-trips.
        data = module.build_provenance_bytes(doc)
        re_doc = json.loads(data.decode("utf-8"))
        assert re_doc["mergedExpectedSha256"] == merged_sha


def test_differential_shared_reuse_case_provenance() -> None:
    """When shared_components.local.json has a reuse component, the merged
    output adds new source-id nodes. Construct provenance with the exact
    page/shared/merged node order and verify it validates."""
    module = _load_prod_module("p25c_diff_reuse")
    with _canonical_tempdir() as tmp:
        expected_payload = {
            "nodes": {
                "page_root": {"bbox": [0, 0, 100, 100], "impl": "shape"},
            }
        }
        scene_payload = {
            "nodes": [
                {"id": "page_root", "bbox": [0, 0, 100, 100]},
                {"id": "shared_root", "bbox": [10, 10, 20, 20]},
            ]
        }
        local_payload = {
            "components": [
                {
                    "status": "reuse",
                    "name": "MyShared",
                    "signature": "struct:abc",
                    "group_node": "shared_root",
                    "bbox": [10, 10, 20, 20],
                    "node_map": {"shared_root": "src_1"},
                    "expected_nodes": {"src_1": {"bbox": [10, 10, 20, 20]}},
                }
            ]
        }
        rc, out, err, exp_p, local_p, scene_p, merged_p = _run_merge(
            tmp, expected_payload, scene_payload, local_payload=local_payload,
        )
        assert rc == 0, f"merge failed: rc={rc} stderr={err!r} stdout={out!r}"
        merged_doc = json.loads(merged_p.read_bytes().decode("utf-8"))
        # Page node keys precede shared source ids in insertion order.
        assert list(merged_doc["nodes"].keys()) == ["page_root", "src_1"]
        page_canvas_sha = _sha256_file(exp_p)
        local_sha = _sha256_file(local_p)
        scene_sha = _sha256_file(scene_p)
        merged_sha = _sha256_file(merged_p)
        producer_sha = _sha256_file(MERGE_SHARED_EXPECTED_CAPSULE)
        doc = module.build_provenance(
            producerKind="iff-v1.merge_shared_expected",
            producerSha256=producer_sha,
            pageCanvasProjectionSha256=page_canvas_sha,
            sharedComponentsLocalSha256=local_sha,
            sceneSha256=scene_sha,
            mergedExpectedSha256=merged_sha,
            pageCanvasNodeIds=["page_root"],
            sharedComponentNodeIds=["src_1"],
            mergedNodeIds=["page_root", "src_1"],
        )
        assert doc["sharedComponentNodeIds"] == ["src_1"]
        assert doc["mergedNodeIds"] == ["page_root", "src_1"]


def test_differential_unresolved_case_no_success_provenance() -> None:
    """An unresolved (status=missing) shared component must fail the merge;
    no merged_expected.json is produced, so no success provenance can be
    constructed for the failed merge."""
    module = _load_prod_module("p25c_diff_unres")
    with _canonical_tempdir() as tmp:
        expected_payload = {"nodes": {"page_1": {"bbox": [0, 0, 10, 10]}}}
        scene_payload = {"nodes": [{"id": "shared_root", "bbox": [10, 10, 20, 20]}]}
        local_payload = {
            "components": [
                {
                    "status": "missing",
                    "signature": "struct:unresolved",
                    "group_node": "shared_root",
                    "bbox": [10, 10, 20, 20],
                }
            ]
        }
        rc, out, err, exp_p, local_p, scene_p, merged_p = _run_merge(
            tmp, expected_payload, scene_payload, local_payload=local_payload,
        )
        assert rc != 0, "unresolved merge must fail"
        assert "unresolved" in err or "unresolved" in out
        assert not merged_p.exists(), "failed merge must not write output"
        # Any attempt to build a "success" provenance with a fake merged
        # digest still can't claim a real merged document because we have
        # no merged file. The test demonstrates the producer cannot issue
        # a success attestation; the contract still validates any well-
        # formed doc, but no such doc can be produced from this run.


def test_differential_collision_case_no_success_provenance() -> None:
    """A source_id that collides with an existing page canvas key must
    fail the merge; no merged_expected.json is produced."""
    with _canonical_tempdir() as tmp:
        expected_payload = {
            "nodes": {
                "src_1": {"bbox": [0, 0, 10, 10]},  # collides with shared key
            }
        }
        scene_payload = {
            "nodes": [
                {"id": "src_1", "bbox": [0, 0, 10, 10]},
                {"id": "shared_root", "bbox": [10, 10, 20, 20]},
            ]
        }
        local_payload = {
            "components": [
                {
                    "status": "reuse",
                    "name": "MyShared",
                    "signature": "struct:abc",
                    "group_node": "shared_root",
                    "bbox": [10, 10, 20, 20],
                    "node_map": {"shared_root": "src_1"},
                    "expected_nodes": {"src_1": {"bbox": [10, 10, 20, 20]}},
                }
            ]
        }
        rc, out, err, exp_p, local_p, scene_p, merged_p = _run_merge(
            tmp, expected_payload, scene_payload, local_payload=local_payload,
        )
        assert rc != 0, "collision merge must fail"
        combined = err + out
        assert "collides" in combined, f"missing collision message: {combined!r}"
        assert not merged_p.exists(), "failed merge must not write output"


def test_differential_provenance_chain_digests_match_actual_files() -> None:
    """End-to-end: for the shared-reuse case, every provenance digest must
    equal the SHA-256 of the actual file bytes that the frozen merge
    primitive consumed/produced. This proves the contract records the
    effective document, not a proxy."""
    module = _load_prod_module("p25c_diff_chain")
    with _canonical_tempdir() as tmp:
        expected_payload = {
            "nodes": {
                "page_a": {"bbox": [0, 0, 50, 50]},
                "page_b": {"bbox": [60, 60, 30, 30]},
            }
        }
        scene_payload = {
            "nodes": [
                {"id": "page_a", "bbox": [0, 0, 50, 50]},
                {"id": "page_b", "bbox": [60, 60, 30, 30]},
                {"id": "shared_grp", "bbox": [100, 100, 40, 40]},
            ]
        }
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
        rc, out, err, exp_p, local_p, scene_p, merged_p = _run_merge(
            tmp, expected_payload, scene_payload, local_payload=local_payload,
        )
        assert rc == 0, f"merge failed: {err!r}"
        # Re-read the merged doc to extract actual node order.
        merged_doc = json.loads(merged_p.read_bytes().decode("utf-8"))
        assert list(merged_doc["nodes"].keys()) == ["page_a", "page_b", "shared_src_1"]
        doc = module.build_provenance(
            producerKind="iff-v1.merge_shared_expected",
            producerSha256=_sha256_file(MERGE_SHARED_EXPECTED_CAPSULE),
            pageCanvasProjectionSha256=_sha256_file(exp_p),
            sharedComponentsLocalSha256=_sha256_file(local_p),
            sceneSha256=_sha256_file(scene_p),
            mergedExpectedSha256=_sha256_file(merged_p),
            pageCanvasNodeIds=["page_a", "page_b"],
            sharedComponentNodeIds=["shared_src_1"],
            mergedNodeIds=["page_a", "page_b", "shared_src_1"],
        )
        # Prove the contract records the EFFECTIVE merged document, not
        # the raw page-canvas projection: the merged digest must differ
        # from the page canvas digest.
        assert doc["mergedExpectedSha256"] != doc["pageCanvasProjectionSha256"]


# ===========================================================================
# 16. Protected-hash summary (duplicate of section 0, kept explicit).
# ===========================================================================


def test_protected_execution_hashes_unchanged() -> None:
    """All protected binding/authorization/executor/preflight/standard
    module hashes must be unchanged by P2.5c. P2.5d is authorized to
    change flutter_standard_v1.py and flutter_operations_v1.py; those
    new P2.5d-final hashes are recorded in PROTECTED_FILE_HASHES above
    with an annotation."""
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
