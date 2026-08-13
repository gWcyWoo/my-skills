#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2e1 shared frozen
selection-manifest verifier (``verify_selection_manifest_v1.verify``).

The verifier is a read-only re-attestor: it loads the frozen
``selection-manifest.json`` from disk, re-derives the canonical payload
through the real ``freeze_selection_manifest.build_manifest_payload``
source of truth, requires byte-identical canonical bytes against the
file bytes, and requires the supplied path to equal the recomputed
``<run_root>/selection-manifest.json`` with canonical no-symlink roots.

Tests are run in temporary canonical project/run roots produced through
the real freezer. No production file (capsule, descriptor, manifest,
registry, ``iff/**``, existing project files) is mutated.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e1_selection_manifest.py
"""

from __future__ import annotations

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
MODULE_PATH = ICP_SCRIPTS / "verify_selection_manifest_v1.py"
FREEZE_PATH = ICP_SCRIPTS / "freeze_selection_manifest.py"
COMMON_PATH = ICP_SCRIPTS / "icp_common.py"
PREFLIGHT_PATH = ICP_SCRIPTS / "preflight_selection.py"
REGISTRY_PATH = ICP_ROOT / "references" / "registries.json"
SKILL_MD_PATH = ICP_ROOT / "SKILL.md"

KIND_VERIFY = "icp.selection-manifest-verify.v1"
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Module loader.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path = MODULE_PATH):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_freeze(name: str = "p2e1_freeze_helper"):
    return _load(name, FREEZE_PATH)


def _load_common(name: str = "p2e1_common_helper"):
    return _load(name, COMMON_PATH)


def _canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2e1_sel_"):
    """Yield a temp dir whose path is realpath-canonicalized so the macOS
    ``/tmp`` -> ``/private/tmp`` symlink never trips the strict-resolve
    containment check."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# Fixtures: real manifest built via the freezer source of truth.
# ---------------------------------------------------------------------------


def _good_cands() -> list[dict[str, Any]]:
    return [
        {"row_index": 1, "title": "Alpha", "status": "",
         "design_url": "https://figma.com/file/a"},
        {"row_index": 2, "title": "Beta", "status": "",
         "design_url": "https://lanhuapp.com/url/b"},
    ]


def _resolved(project_root: Path) -> dict[str, Any]:
    return {
        "task_source": "csv",
        "task_ref": "tasks.csv",
        "design_source": "lanhu-figma",
        "platform": "flutter",
        "profile": "flutter-standard",
        "project_root": str(project_root),
    }


@contextlib.contextmanager
def _frozen_manifest(batch_id: str = "p2e1-batch-1"):
    """Build a real manifest through the freezer under a canonical project
    root. Yields ``(project_root, manifest_path, freeze_ack)``."""
    freeze = _load_freeze()
    common = _load_common()
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id=batch_id,
            registries=common.load_registries(),
        )
        yield proj, Path(ack["manifest_path"]), ack


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _tamper_and_rewrite(manifest_path: Path, mutator) -> bytes:
    """Read the manifest, apply ``mutator(doc)`` (in place), rewrite the
    file with the mutated canonical bytes. Returns the new bytes.

    Used to construct explicit tamper cases that the verifier must
    reject (the bytes no longer match the canonical recomputation).
    """
    doc = _read_manifest(manifest_path)
    mutator(doc)
    new_bytes = _canonical_json(doc)
    manifest_path.write_bytes(new_bytes)
    return new_bytes


# ---------------------------------------------------------------------------
# 1. Module surface and public API.
# ---------------------------------------------------------------------------


def test_module_loads() -> None:
    module = _load("p2e1_sel_loads")
    assert module.KIND_VERIFY == KIND_VERIFY
    assert module.SCHEMA_VERSION == SCHEMA_VERSION


def test_module_exposes_typed_exception() -> None:
    module = _load("p2e1_sel_exc")
    assert hasattr(module, "SelectionManifestVerifyError")
    assert issubclass(module.SelectionManifestVerifyError, Exception)


def test_module_has_no_cli_main() -> None:
    module = _load("p2e1_sel_nocli")
    assert not hasattr(module, "main")
    source = MODULE_PATH.read_text()
    assert '__name__ == "__main__"' not in source


def test_public_api_exposes_only_verify_and_exception() -> None:
    module = _load("p2e1_sel_pubapi")
    assert callable(module.verify)
    allowed_funcs = {"verify"}
    public_funcs = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isfunction(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra = sorted(set(public_funcs) - allowed_funcs)
    assert extra == [], f"unexpected public functions: {extra}"
    # Allowed public classes: only the local typed exception.
    allowed_classes = {"SelectionManifestVerifyError"}
    public_classes = [
        n
        for n in dir(module)
        if not n.startswith("_")
        and inspect.isclass(getattr(module, n))
        and getattr(module, n).__module__ == module.__name__
    ]
    extra_c = sorted(set(public_classes) - allowed_classes)
    assert extra_c == [], f"unexpected public classes: {extra_c}"


def test_module_does_not_import_subprocess() -> None:
    """The verifier must not import or call ``subprocess`` / shell.
    Uses AST so docstring mentions do not produce false positives."""
    import ast
    tree = ast.parse(MODULE_PATH.read_text(), filename=str(MODULE_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess", "module imports subprocess"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "subprocess", "module imports from subprocess"
        elif isinstance(node, ast.Attribute):
            # ``subprocess.run`` / ``subprocess.Popen`` etc. require the
            # attribute base name to be ``subprocess``.
            if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                raise AssertionError("module references subprocess attribute")


# ---------------------------------------------------------------------------
# 2. Valid deterministic verification and exact report shape.
# ---------------------------------------------------------------------------


def test_valid_manifest_verifies_and_report_shape_exact() -> None:
    module = _load("p2e1_sel_valid")
    common = _load_common()
    with _frozen_manifest() as (proj, manifest_path, ack):
        report = module.verify(manifest_path)
        # Exact top-level key set.
        expected_keys = {
            "kind", "schema_version", "batch_id", "platform_id", "profile_id",
            "project_root", "state_root", "run_root", "manifest_path",
            "manifest_sha256", "registry_digest", "selected_profile_digest",
            "rules_digest", "actual_batch_size",
        }
        assert set(report.keys()) == expected_keys, set(report.keys()) ^ expected_keys
        # Literal values.
        assert report["kind"] == KIND_VERIFY
        assert report["schema_version"] == SCHEMA_VERSION
        assert report["batch_id"] == "p2e1-batch-1"
        assert report["platform_id"] == "flutter"
        assert report["profile_id"] == "flutter-standard"
        assert report["project_root"] == str(proj)
        assert report["state_root"] == str(proj / ".iff")
        assert report["run_root"] == str(proj / ".iff" / "icp_runs" / "p2e1-batch-1")
        assert report["manifest_path"] == str(manifest_path)
        assert report["actual_batch_size"] == 2
        # manifest_sha256: 64 lower hex over exact file bytes.
        assert _is_sha256_hex(report["manifest_sha256"])
        expected_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        assert report["manifest_sha256"] == expected_sha
        # Digest labels are the manifest's labeled form (sha256:hex).
        doc = _read_manifest(manifest_path)
        assert report["registry_digest"] == doc["registry_digest"]
        assert report["selected_profile_digest"] == doc["selected_profile_digest"]
        assert report["rules_digest"] == doc["rules_digest"]
        # rules_digest must match the current SKILL.md digest.
        skill_md_sha = hashlib.sha256(SKILL_MD_PATH.read_bytes()).hexdigest()
        assert report["rules_digest"] == f"sha256:{skill_md_sha}"
        # Cross-check against the common registry.
        registries = common.load_registries()
        reg_digest = hashlib.sha256(_canonical_json(registries)).hexdigest()
        assert report["registry_digest"] == f"sha256:{reg_digest}"


def test_valid_manifest_deterministic_across_calls() -> None:
    module = _load("p2e1_sel_det")
    with _frozen_manifest() as (proj, manifest_path, ack):
        r1 = module.verify(manifest_path)
        r2 = module.verify(manifest_path)
    assert r1 == r2


def test_verify_is_cwd_independent() -> None:
    module = _load("p2e1_sel_cwd")
    with _frozen_manifest() as (proj, manifest_path, ack):
        with _canonical_tempdir() as other:
            cwd_orig = os.getcwd()
            try:
                os.chdir(str(other))
                report_a = module.verify(manifest_path)
                os.chdir(str(proj))
                report_b = module.verify(manifest_path)
            finally:
                os.chdir(cwd_orig)
    assert report_a == report_b
    assert report_a["manifest_path"] == str(manifest_path)


# ---------------------------------------------------------------------------
# 3. Path attacks.
# ---------------------------------------------------------------------------


def test_rejects_relative_path() -> None:
    module = _load("p2e1_sel_relpath")
    with _frozen_manifest() as (proj, manifest_path, ack):
        cwd_orig = os.getcwd()
        try:
            os.chdir(str(manifest_path.parent))
            rel = Path(manifest_path.name)
            try:
                module.verify(rel)
            except module.SelectionManifestVerifyError:
                pass
            else:
                raise AssertionError("relative path accepted")
        finally:
            os.chdir(cwd_orig)


def test_rejects_noncanonical_path() -> None:
    module = _load("p2e1_sel_noncanon")
    with _frozen_manifest() as (proj, manifest_path, ack):
        # Inject a redundant ./ into the path via raw string (Path()
        # collapses ``.`` so we must use the string form to preserve
        # the non-canonical component through os.fspath).
        noncanonical_str = str(manifest_path.parent) + "/./" + manifest_path.name
        try:
            module.verify(noncanonical_str)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("noncanonical path accepted")


def test_rejects_missing_path() -> None:
    module = _load("p2e1_sel_missing")
    with _frozen_manifest() as (proj, manifest_path, ack):
        missing = manifest_path.parent / "does-not-exist.json"
        try:
            module.verify(missing)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("missing path accepted")


def test_rejects_directory_path() -> None:
    module = _load("p2e1_sel_dir")
    with _frozen_manifest() as (proj, manifest_path, ack):
        try:
            module.verify(manifest_path.parent)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("directory path accepted")


def test_rejects_symlink_leaf() -> None:
    module = _load("p2e1_sel_symlinkleaf")
    with _frozen_manifest() as (proj, manifest_path, ack):
        with _canonical_tempdir() as other:
            link = other / "link-to-manifest.json"
            os.symlink(manifest_path, link)
            try:
                module.verify(link)
            except module.SelectionManifestVerifyError:
                pass
            else:
                raise AssertionError("symlink leaf accepted")


def test_rejects_symlink_ancestor() -> None:
    module = _load("p2e1_sel_symlinkanc")
    with _canonical_tempdir() as base:
        # real proj + a symlink alias to base
        proj = base / "proj"
        proj.mkdir()
        freeze = _load_freeze()
        common = _load_common()
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id="symlinkanc-1",
            registries=common.load_registries(),
        )
        manifest_path = Path(ack["manifest_path"])
        # Build a path that traverses a symlinked ancestor.
        alias_root = base / "alias_root"
        alias_root.symlink_to(base, target_is_directory=True)
        # manifest_path is at base/proj/.iff/icp_runs/<batch>/selection-manifest.json
        rel = manifest_path.relative_to(base)
        aliased = alias_root / rel
        try:
            module.verify(aliased)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("symlink ancestor accepted")


def test_rejects_wrong_filename() -> None:
    module = _load("p2e1_sel_wrongname")
    with _frozen_manifest() as (proj, manifest_path, ack):
        # Copy manifest bytes to a sibling file with a different name.
        wrong = manifest_path.parent / "not-the-manifest.json"
        wrong.write_bytes(manifest_path.read_bytes())
        try:
            module.verify(wrong)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("wrong filename accepted")


def test_rejects_path_outside_recomputed_run_root() -> None:
    module = _load("p2e1_sel_outside")
    with _frozen_manifest() as (proj, manifest_path, ack):
        # Place an identical manifest in an unrelated directory.
        with _canonical_tempdir() as elsewhere:
            other = elsewhere / "selection-manifest.json"
            other.write_bytes(manifest_path.read_bytes())
            try:
                module.verify(other)
            except module.SelectionManifestVerifyError:
                pass
            else:
                raise AssertionError("path outside run root accepted")


# ---------------------------------------------------------------------------
# 4. JSON / encoding attacks.
# ---------------------------------------------------------------------------


def test_rejects_oversized_file() -> None:
    module = _load("p2e1_sel_oversize")
    with _frozen_manifest() as (proj, manifest_path, ack):
        # Pad the file beyond 8 MiB by appending junk.
        original = manifest_path.read_bytes()
        manifest_path.write_bytes(original + (b" " * (8 * 1024 * 1024 + 1)))
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("oversized file accepted")


def test_rejects_non_utf8_bytes() -> None:
    module = _load("p2e1_sel_nonutf8")
    with _frozen_manifest() as (proj, manifest_path, ack):
        manifest_path.write_bytes(b'{"kind": "\xff\xfe"}\n')
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-UTF-8 accepted")


def test_rejects_malformed_json() -> None:
    module = _load("p2e1_sel_malformed")
    with _frozen_manifest() as (proj, manifest_path, ack):
        manifest_path.write_bytes(b"{not json")
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("malformed JSON accepted")


def test_rejects_non_object_root() -> None:
    module = _load("p2e1_sel_nonobj")
    with _frozen_manifest() as (proj, manifest_path, ack):
        manifest_path.write_bytes(b"[1, 2, 3]\n")
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-object root accepted")


def test_rejects_duplicate_keys() -> None:
    module = _load("p2e1_sel_dupkeys")
    with _frozen_manifest() as (proj, manifest_path, ack):
        doc = _read_manifest(manifest_path)
        # Construct bytes with a duplicate ``schema_version`` key.
        text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
        # Append a duplicate key just before the closing brace.
        idx = text.rfind("\n}")
        tampered = text[:idx] + ',\n  "schema_version": 999\n' + text[idx:] + "\n"
        manifest_path.write_bytes(tampered.encode("utf-8"))
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("duplicate keys accepted")


def test_rejects_noncanonical_json_format() -> None:
    module = _load("p2e1_sel_noncanon_json")
    with _frozen_manifest() as (proj, manifest_path, ack):
        doc = _read_manifest(manifest_path)
        # Same logical content, but indented with 4 spaces (non-canonical).
        noncanon = (json.dumps(doc, ensure_ascii=False, indent=4, sort_keys=True) + "\n").encode("utf-8")
        manifest_path.write_bytes(noncanon)
        try:
            module.verify(manifest_path)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-canonical JSON accepted")


# ---------------------------------------------------------------------------
# 5. Top-level shape attacks.
# ---------------------------------------------------------------------------


_TOP_LEVEL_KEYS = [
    "kind", "schema_version", "batch_id", "resolved",
    "registry_digest", "selected_profile_digest", "rules_digest",
    "runtime_script_digests", "capabilities", "actual_batch_size",
    "candidates", "state_root", "run_root",
]


def test_rejects_missing_each_top_level_key() -> None:
    module = _load("p2e1_sel_missing_keys")
    for key in _TOP_LEVEL_KEYS:
        with _frozen_manifest(batch_id=f"miss-{key}") as (proj, mp, ack):
            def _drop(doc, k=key):
                del doc[k]
            _tamper_and_rewrite(mp, _drop)
            try:
                module.verify(mp)
            except module.SelectionManifestVerifyError:
                pass
            else:
                raise AssertionError(f"missing top-level {key} accepted")


def test_rejects_extra_top_level_key() -> None:
    module = _load("p2e1_sel_extra_key")

    def _add(doc):
        doc["extra_field"] = "boom"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _add)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("extra top-level key accepted")


def test_rejects_wrong_kind() -> None:
    module = _load("p2e1_sel_wkind")

    def _m(doc):
        doc["kind"] = "something.else"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("wrong kind accepted")


def test_rejects_wrong_schema_version() -> None:
    module = _load("p2e1_sel_wsv")

    def _m(doc):
        doc["schema_version"] = 2
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("wrong schema_version accepted")


def test_rejects_bool_as_int_schema_version() -> None:
    module = _load("p2e1_sel_boolsv")

    def _m(doc):
        doc["schema_version"] = True
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("bool schema_version accepted")


def test_rejects_wrong_actual_batch_size() -> None:
    module = _load("p2e1_sel_wabs")

    def _m(doc):
        doc["actual_batch_size"] = 99
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("wrong actual_batch_size accepted")


# ---------------------------------------------------------------------------
# 6. resolved-block attacks.
# ---------------------------------------------------------------------------


_RESOLVED_KEYS = [
    "task_source", "task_ref", "design_source", "platform", "profile",
    "project_root",
]


def test_rejects_resolved_missing_each_key() -> None:
    module = _load("p2e1_sel_res_missing")
    for key in _RESOLVED_KEYS:
        with _frozen_manifest(batch_id=f"rmiss-{key}") as (proj, mp, ack):
            def _drop(doc, k=key):
                del doc["resolved"][k]
            _tamper_and_rewrite(mp, _drop)
            try:
                module.verify(mp)
            except module.SelectionManifestVerifyError:
                pass
            else:
                raise AssertionError(f"missing resolved {key} accepted")


def test_rejects_resolved_extra_key() -> None:
    module = _load("p2e1_sel_res_extra")

    def _m(doc):
        doc["resolved"]["extra"] = "boom"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("extra resolved key accepted")


def test_rejects_resolved_non_flutter_platform() -> None:
    module = _load("p2e1_sel_res_plat")

    def _m(doc):
        doc["resolved"]["platform"] = "vue"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-flutter platform accepted")


def test_rejects_resolved_wrong_profile() -> None:
    """The verifier requires ``resolved.profile`` to equal the current
    selected ``default_profile`` for the resolved platform. A genuine
    profile mismatch (``vue-vite`` for a ``flutter`` manifest) is
    rejected by the registry cross-check before the recompute."""
    module = _load("p2e1_sel_res_prof")

    def _m(doc):
        doc["resolved"]["profile"] = "vue-vite"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("wrong profile accepted")


def test_rejects_resolved_non_string_profile() -> None:
    """A non-string profile value is rejected by the resolved-shape
    scalar-type check."""
    module = _load("p2e1_sel_res_prof_ns")

    def _m(doc):
        doc["resolved"]["profile"] = 123
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-string profile accepted")


def test_rejects_resolved_unknown_platform() -> None:
    """A platform not present in the current registry is rejected."""
    module = _load("p2e1_sel_res_prof_unkplat")

    def _m(doc):
        doc["resolved"]["platform"] = "nonexistent-platform"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("unknown platform accepted")


def test_rejects_resolved_non_string_project_root() -> None:
    module = _load("p2e1_sel_res_nr")

    def _m(doc):
        doc["resolved"]["project_root"] = 123
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-string project_root accepted")


def test_rejects_batch_id_with_trailing_newline() -> None:
    """The verifier must independently enforce the exact no-whitespace
    ``batch_id`` grammar ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`` as a
    whole-string contract. Python's ``re.match(r'...$')`` accepts a
    value ending in a single newline (``$`` may match before the final
    newline); ``fullmatch`` does not.

    The producer now rejects a trailing-newline ``batch_id`` at the
    input boundary, so a manifest carrying one can only reach the
    verifier through direct canonical tampering. Build a valid manifest
    through the real producer, then tamper its ``batch_id`` to a
    trailing-newline value and rewrite the canonical bytes. The
    verifier must reject it independently (its own ``_BATCH_ID_RE.fullmatch``
    check), regardless of the producer's enforcement.
    """
    module = _load("p2e1_sel_batch_newline")

    def _m(doc):
        doc["batch_id"] = "p2e1-batch-nl\n"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("trailing-newline batch_id accepted")


def test_rejects_batch_id_with_trailing_space() -> None:
    """A ``batch_id`` ending in a space is whitespace-contaminated and
    must be rejected by the verifier's independent grammar enforcement.

    The producer rejects a trailing-space ``batch_id`` at the input
    boundary, so this case can only reach the verifier through direct
    canonical tampering — exactly the attack the independent enforcement
    exists to catch. Build a valid manifest, then tamper its
    ``batch_id`` to a trailing-space value and rewrite the canonical
    bytes.
    """
    module = _load("p2e1_sel_batch_space")

    def _m(doc):
        doc["batch_id"] = "p2e1-batch-sp "
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("trailing-space batch_id accepted")


# ---------------------------------------------------------------------------
# 7. Candidate evidence attacks.
# ---------------------------------------------------------------------------


def test_rejects_candidate_missing_key() -> None:
    module = _load("p2e1_sel_cand_missing")

    def _m(doc):
        del doc["candidates"][0]["design_url"]
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("missing candidate key accepted")


def test_rejects_candidate_extra_key() -> None:
    module = _load("p2e1_sel_cand_extra")

    def _m(doc):
        doc["candidates"][0]["extra"] = "boom"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("extra candidate key accepted")


def test_rejects_candidate_wrong_type_row_index() -> None:
    module = _load("p2e1_sel_cand_ri")

    def _m(doc):
        doc["candidates"][0]["row_index"] = "1"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("string row_index accepted")


def test_rejects_candidate_bool_row_index() -> None:
    module = _load("p2e1_sel_cand_rib")

    def _m(doc):
        doc["candidates"][0]["row_index"] = True
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("bool row_index accepted")


def test_rejects_candidate_non_positive_row_index() -> None:
    module = _load("p2e1_sel_cand_rip")

    def _m(doc):
        doc["candidates"][0]["row_index"] = 0
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-positive row_index accepted")


def test_rejects_candidate_duplicate_row_index() -> None:
    module = _load("p2e1_sel_cand_dupri")

    def _m(doc):
        doc["candidates"][1]["row_index"] = 1
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("duplicate row_index accepted")


def test_rejects_candidate_empty_title() -> None:
    module = _load("p2e1_sel_cand_et")

    def _m(doc):
        doc["candidates"][0]["title"] = ""
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("empty title accepted")


def test_rejects_candidate_duplicate_title() -> None:
    module = _load("p2e1_sel_cand_dupt")

    def _m(doc):
        doc["candidates"][1]["title"] = "Alpha"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("duplicate title accepted")


def test_rejects_candidate_non_empty_status() -> None:
    module = _load("p2e1_sel_cand_status")

    def _m(doc):
        doc["candidates"][0]["status"] = "doing"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("non-empty status accepted")


def test_rejects_candidate_empty_design_url() -> None:
    module = _load("p2e1_sel_cand_edu")

    def _m(doc):
        doc["candidates"][0]["design_url"] = ""
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("empty design_url accepted")


def test_rejects_candidate_malformed_design_url() -> None:
    module = _load("p2e1_sel_cand_mdu")

    def _m(doc):
        doc["candidates"][0]["design_url"] = "ftp://example.com/x"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("malformed design_url accepted")


def test_rejects_candidate_count_mismatch() -> None:
    module = _load("p2e1_sel_cand_count")

    def _m(doc):
        # Duplicate a candidate so len(candidates) no longer matches
        # actual_batch_size (which stays at 2). The structural validator
        # must catch this before the canonical-bytes comparison.
        doc["candidates"].append(copy.deepcopy(doc["candidates"][0]))
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("candidate count mismatch accepted")


# ---------------------------------------------------------------------------
# 8. Digest / capability / root tampering.
# ---------------------------------------------------------------------------


def test_rejects_registry_digest_tamper() -> None:
    module = _load("p2e1_sel_tamper_reg")

    def _m(doc):
        doc["registry_digest"] = "sha256:" + "0" * 64
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("registry_digest tamper accepted")


def test_rejects_selected_profile_digest_tamper() -> None:
    module = _load("p2e1_sel_tamper_profile")

    def _m(doc):
        doc["selected_profile_digest"] = "sha256:" + "0" * 64
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("selected_profile_digest tamper accepted")


def test_rejects_rules_digest_tamper() -> None:
    module = _load("p2e1_sel_tamper_rules")

    def _m(doc):
        doc["rules_digest"] = "sha256:" + "0" * 64
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("rules_digest tamper accepted")


def test_rejects_runtime_script_digest_tamper() -> None:
    module = _load("p2e1_sel_tamper_runtime")

    def _m(doc):
        # Tamper one runtime script digest.
        first_key = next(iter(doc["runtime_script_digests"]))
        doc["runtime_script_digests"][first_key] = "sha256:" + "0" * 64
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("runtime script digest tamper accepted")


def test_rejects_capability_tamper() -> None:
    module = _load("p2e1_sel_tamper_cap")

    def _m(doc):
        doc["capabilities"]["visible_codegen"] = "unsupported"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("capability tamper accepted")


def test_rejects_state_root_tamper() -> None:
    module = _load("p2e1_sel_tamper_state")

    def _m(doc):
        doc["state_root"] = doc["state_root"] + "/tampered"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("state_root tamper accepted")


def test_rejects_run_root_tamper() -> None:
    module = _load("p2e1_sel_tamper_run")

    def _m(doc):
        doc["run_root"] = doc["run_root"] + "/tampered"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("run_root tamper accepted")


def test_rejects_candidate_title_tamper() -> None:
    """A structural title tamper that breaks the duplicate-title
    invariant is rejected by the candidate validator before the
    canonical-bytes comparison runs."""
    module = _load("p2e1_sel_tamper_title")

    def _m(doc):
        # Tamper the second candidate's title to duplicate the first.
        doc["candidates"][1]["title"] = doc["candidates"][0]["title"]
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("duplicate title tamper accepted")


def test_rejects_project_root_tamper_in_resolved() -> None:
    module = _load("p2e1_sel_tamper_proj")

    def _m(doc):
        doc["resolved"]["project_root"] = doc["resolved"]["project_root"] + "/x"
    with _frozen_manifest() as (proj, mp, ack):
        _tamper_and_rewrite(mp, _m)
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("resolved project_root tamper accepted")


# ---------------------------------------------------------------------------
# 9. Generic failure redaction.
# ---------------------------------------------------------------------------


def test_generic_failure_message_is_type_only() -> None:
    """For generic exceptions (not SelectionManifestVerifyError raised
    explicitly by the verifier), the surfaced message must NOT contain
    arbitrary exception text, secrets, or tracebacks. The verifier's
    own typed failures carry stable messages, but generic ones expose
    type only."""
    module = _load("p2e1_sel_generic")
    # Force a generic exception inside the strict-JSON path. We write a
    # file whose bytes decode as UTF-8 but contain an exotic JSON value
    # that the verifier's strict decoder rejects with a JSONDecodeError
    # wrapped to a typed error.
    with _frozen_manifest() as (proj, mp, ack):
        mp.write_bytes(b"\xc3\x28")  # invalid UTF-8 continuation
        try:
            module.verify(mp)
        except module.SelectionManifestVerifyError:
            pass
        else:
            raise AssertionError("invalid UTF-8 not rejected")


# ---------------------------------------------------------------------------
# 10. Read-only / no writes.
# ---------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[Path, bytes]:
    snap: dict[Path, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.is_symlink():
            snap[p] = b"<symlink>"
        else:
            snap[p] = p.read_bytes()
    return snap


def test_verify_does_not_mutate_project_tree() -> None:
    module = _load("p2e1_sel_nowrite")
    with _frozen_manifest() as (proj, mp, ack):
        before = _snapshot(proj)
        module.verify(mp)
        after = _snapshot(proj)
    assert set(before.keys()) == set(after.keys())
    for p, data in before.items():
        assert after[p] == data, f"project mutated: {p}"


def test_verify_does_not_mutate_registry() -> None:
    module = _load("p2e1_sel_nowrite_reg")
    before = REGISTRY_PATH.read_bytes()
    with _frozen_manifest() as (proj, mp, ack):
        module.verify(mp)
    after = REGISTRY_PATH.read_bytes()
    assert before == after, "registries.json was mutated"


def test_verify_does_not_mutate_skill_md() -> None:
    module = _load("p2e1_sel_nowrite_skill")
    before = SKILL_MD_PATH.read_bytes()
    with _frozen_manifest() as (proj, mp, ack):
        module.verify(mp)
    after = SKILL_MD_PATH.read_bytes()
    assert before == after, "SKILL.md was mutated"


def test_verify_leaves_task_csv_bytes_unchanged() -> None:
    """The manifest freezes path/evidence; a claim legitimately changes
    the external CSV after freeze. The verifier does not require CSV
    bytes to remain unchanged, but it must not modify them itself."""
    module = _load("p2e1_sel_csv_unchanged")
    with _canonical_tempdir() as tmp:
        proj = tmp / "proj"
        proj.mkdir()
        csv_path = proj / "tasks.csv"
        original_csv = (
            b"id,title,design_url,ui_notes,interaction,api,status\n"
            b"1,Alpha,https://figma.com/file/a,un-A,ie-A,ap-A,\n"
            b"2,Beta,https://lanhuapp.com/url/b,un-B,ie-B,ap-B,\n"
        )
        csv_path.write_bytes(original_csv)
        freeze = _load_freeze()
        common = _load_common()
        ack = freeze.freeze_selection_manifest(
            resolved_config=_resolved(proj),
            candidates=_good_cands(),
            batch_id="csv-unchanged-1",
            registries=common.load_registries(),
        )
        module.verify(ack["manifest_path"])
        assert csv_path.read_bytes() == original_csv


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
