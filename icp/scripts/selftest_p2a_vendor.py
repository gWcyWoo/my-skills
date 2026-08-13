#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2a iFF v1 vendor capsule.

Covers the maintenance tool (``vendor_iff_v1.py``), the runtime integrity
gate (``verify_vendor_iff_v1.py``), the vendored capsule contents, and the
deterministic manifest (``iff-v1-vendor.json``).

The capsule is the only iFF-derived material the ICP runtime may import or
execute; the live ``iff/`` skill must never be a runtime dependency. These
tests build isolated skill roots in private temp dirs and exercise the
production module APIs + the production CLIs against the real P0 baseline.
Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2a_vendor.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
IFF_ROOT = REPO_ROOT / "iff"
IFF_SCRIPTS = IFF_ROOT / "scripts"
P0_BASELINE = ICP_ROOT / "references" / "baselines" / "iff-v1.json"
PROD_CAPSULE = ICP_ROOT / "vendor" / "iff_v1"
PROD_CAPSULE_SCRIPTS = PROD_CAPSULE / "scripts"
PROD_MANIFEST = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
VENDOR_TOOL = ICP_SCRIPTS / "vendor_iff_v1.py"
VERIFY_TOOL = ICP_SCRIPTS / "verify_vendor_iff_v1.py"


# ---------------------------------------------------------------------------
# Module loaders (file-path based; never imports iff at runtime).
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_VENDOR = _load("vendor_iff_v1", VENDOR_TOOL)
_VERIFY = _load("verify_vendor_iff_v1", VERIFY_TOOL)


# ---------------------------------------------------------------------------
# P0 baseline helpers.
# ---------------------------------------------------------------------------


def _p0_baseline() -> dict:
    raw = P0_BASELINE.read_bytes()
    return json.loads(raw)


def _p0_scripts() -> list[dict]:
    return _p0_baseline()["scripts"]


def _real_iff_hashes() -> dict[str, str]:
    """Map basename -> SHA-256 of every live iff/scripts/*.py."""
    out: dict[str, str] = {}
    for entry in _p0_scripts():
        name = entry["path"].rsplit("/", 1)[-1]
        src = IFF_SCRIPTS / name
        out[name] = hashlib.sha256(src.read_bytes()).hexdigest()
    return out


def _run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2a_"):
    """A temp directory whose path is canonicalized via ``realpath``.

    On macOS, ``tempfile.TemporaryDirectory()`` returns a ``/var/...`` path,
    but ``/var`` is a symlink to ``/private/var``. The implementation correctly
    rejects any symlink in the path chain (including ``/var``), so tests must
    use the canonical ``/private/var/...`` form. This helper yields the
    canonicalized path while still cleaning up via the original temp handle.
    """
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


# ---------------------------------------------------------------------------
# Fixture construction in temp dirs.
# ---------------------------------------------------------------------------


def _build_skill_root_in_tmp(tmp: Path) -> Path:
    """Build a self-contained skill root with baseline + capsule + manifest.

    Uses the maintenance tool's internal refresh() against the real iff source.
    Returns the skill root path.
    """
    skill = tmp / "icp"
    (skill / "references" / "baselines").mkdir(parents=True)
    (skill / "vendor").mkdir(parents=True)
    baseline_dst = skill / "references" / "baselines" / "iff-v1.json"
    baseline_dst.write_bytes(P0_BASELINE.read_bytes())
    capsule_root = skill / "vendor" / "iff_v1"
    manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
    result = _VENDOR.refresh(
        iff_root=IFF_ROOT,
        capsule_root=capsule_root,
        baseline_path=baseline_dst,
        manifest_path=manifest_path,
        capsule_rel="vendor/iff_v1",
    )
    assert result["ok"] is True, f"refresh failed: {result}"
    return skill


def _build_skill_with_short_circuit(tmp: Path) -> Path:
    """Build a skill root whose capsule is missing so verifier fails closed."""
    skill = tmp / "icp"
    (skill / "references" / "baselines").mkdir(parents=True)
    (skill / "references" / "baselines" / "iff-v1.json").write_bytes(P0_BASELINE.read_bytes())
    return skill


# ---------------------------------------------------------------------------
# 1. P0 baseline shape and exact file set.
# ---------------------------------------------------------------------------


def test_p0_baseline_has_165_unique_basenames() -> None:
    scripts = _p0_scripts()
    basenames = [s["path"].rsplit("/", 1)[-1] for s in scripts]
    assert len(scripts) == 165, f"expected 165 P0 scripts, got {len(scripts)}"
    assert len(set(basenames)) == 165, "P0 basenames must be unique"
    assert all(s["path"].startswith("iff/scripts/") for s in scripts)
    # SHA values must be 64-char lowercase hex.
    for s in scripts:
        assert len(s["sha256"]) == 64 and s["sha256"].islower()
        assert isinstance(s["in_required_registry"], bool)


def test_runtime_capsule_exactly_matches_p0_baseline() -> None:
    """The installed capsule has exactly the 165 P0 files with matching SHAs."""
    assert PROD_CAPSULE_SCRIPTS.is_dir(), f"capsule scripts dir missing: {PROD_CAPSULE_SCRIPTS}"
    expected = {s["path"].rsplit("/", 1)[-1]: s["sha256"] for s in _p0_scripts()}
    actual_files = sorted(p.name for p in PROD_CAPSULE_SCRIPTS.iterdir() if p.is_file())
    assert len(actual_files) == 165, (
        f"capsule has {len(actual_files)} files; expected 165; "
        f"extras={sorted(set(actual_files) - set(expected))} "
        f"missing={sorted(set(expected) - set(actual_files))}"
    )
    for name, sha in sorted(expected.items()):
        target = PROD_CAPSULE_SCRIPTS / name
        assert target.is_file(), f"capsule missing: {name}"
        assert not target.is_symlink(), f"capsule file is a symlink: {name}"
        st = target.lstat()
        assert stat.S_ISREG(st.st_mode), f"capsule file not regular: {name}"
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        assert actual == sha, f"capsule SHA mismatch for {name}: expected {sha} got {actual}"


def test_membership_counts_111_54() -> None:
    baseline = _p0_baseline()
    in_required = sum(1 for s in baseline["scripts"] if s["in_required_registry"])
    not_required = sum(1 for s in baseline["scripts"] if not s["in_required_registry"])
    assert in_required == 111, f"expected 111 required, got {in_required}"
    assert not_required == 54, f"expected 54 non-required, got {not_required}"
    manifest = json.loads(PROD_MANIFEST.read_bytes())
    assert manifest["counts"]["scripts_total"] == 165
    assert manifest["counts"]["scripts_in_required"] == 111
    assert manifest["counts"]["scripts_not_in_required"] == 54


# ---------------------------------------------------------------------------
# 2. Manifest determinism.
# ---------------------------------------------------------------------------


def test_manifest_bytes_deterministic_across_temp_roots() -> None:
    manifests = []
    for i in range(2):
        with _canonical_tempdir(prefix="p2a_det_") as tmp:
            skill = _build_skill_root_in_tmp(tmp)
            m = skill / "references" / "baselines" / "iff-v1-vendor.json"
            manifests.append(m.read_bytes())
    assert manifests[0] == manifests[1], (
        "manifest bytes must be deterministic across different temp roots"
    )
    # The production manifest must equal the freshly built one.
    assert PROD_MANIFEST.read_bytes() == manifests[0], (
        "production manifest drifts from a fresh deterministic build"
    )


# ---------------------------------------------------------------------------
# 3. Runtime verifier (verify_vendor_iff_v1) — positive cases.
# ---------------------------------------------------------------------------


def test_runtime_verifier_no_sibling_iff_available() -> None:
    """The verifier must succeed when no iff/ is present anywhere nearby."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        # The temp skill root has NO sibling iff/, and we never reference iff/.
        result = _VERIFY.verify_skill(skill)
        assert result["ok"] is True
        assert result["scripts_total"] == 165
        assert result["scripts_in_required"] == 111
        assert result["scripts_not_in_required"] == 54


def test_runtime_verifier_production_capsule_green() -> None:
    """The actual production capsule must verify in-place."""
    result = _VERIFY.verify_skill(ICP_ROOT)
    assert result["ok"] is True
    assert result["scripts_total"] == 165


def test_runtime_verifier_cli_emits_canonical_json_success() -> None:
    r = _run_cli(VERIFY_TOOL)
    assert r.returncode == 0, f"verifier CLI failed: rc={r.returncode} stderr={r.stderr!r}"
    assert r.stderr == ""
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


# ---------------------------------------------------------------------------
# 4. Runtime verifier — negative cases (fail closed).
# ---------------------------------------------------------------------------


def test_runtime_verifier_missing_file_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        files = sorted(p for p in scripts_dir.iterdir() if p.is_file() and p.name.endswith(".py"))
        victim = files[0]
        victim.unlink()
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "missing" in str(exc).lower() or victim.name in str(exc)
        else:
            raise AssertionError("verifier accepted missing file")


def test_runtime_verifier_extra_file_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        (scripts_dir / "rogue_extra.py").write_text("# rogue\n", encoding="utf-8")
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "rogue_extra.py" in str(exc) or "extra" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted extra file")


def test_runtime_verifier_mutated_file_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        victim = sorted(p for p in scripts_dir.iterdir() if p.is_file())[0]
        original = victim.read_bytes()
        victim.write_bytes(original + b"\n# mutation\n")
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert victim.name in str(exc) or "sha" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted mutated file")


def test_runtime_verifier_symlinked_file_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        # External sentinel file outside the skill root.
        external = Path(tmp) / "external_target.py"
        external.write_text("# external\n", encoding="utf-8")
        victim = sorted(p for p in scripts_dir.iterdir() if p.is_file())[0]
        victim.unlink()
        (scripts_dir / victim.name).symlink_to(external)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "symlink" in str(exc).lower() or victim.name in str(exc)
        else:
            raise AssertionError("verifier accepted symlinked file")
        # External target unchanged.
        assert external.read_bytes() == b"# external\n"


def test_runtime_verifier_non_regular_file_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        victim = sorted(p for p in scripts_dir.iterdir() if p.is_file())[0]
        victim.unlink()
        # FIFO is non-regular.
        os.mkfifo(scripts_dir / victim.name)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            msg = str(exc).lower()
            assert "regular" in msg or victim.name in str(exc) or "fifo" in msg
        else:
            raise AssertionError("verifier accepted non-regular file")


def test_runtime_verifier_unreadable_file_fails() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return  # root bypasses permission bits.
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        victim = sorted(p for p in scripts_dir.iterdir() if p.is_file())[0]
        victim.chmod(0o000)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert victim.name in str(exc) or "read" in str(exc).lower() or "access" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted unreadable file")
        finally:
            victim.chmod(0o644)


# ---------------------------------------------------------------------------
# 5. Capsule-root + intermediate directory symlink escape.
# ---------------------------------------------------------------------------


def test_runtime_verifier_capsule_root_symlink_escape_no_external_writes() -> None:
    """capsule_root is a symlink to an external dir; verifier fails and does not write there."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        # Move real capsule aside; replace with symlink to external sentinel.
        real_capsule = capsule_root.parent / ".real_iff_v1"
        capsule_root.rename(real_capsule)
        external = Path(tmp) / "external_capsule"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        capsule_root.symlink_to(external)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verifier followed capsule_root symlink")
        # External dir untouched.
        assert sentinel.read_bytes() == b"preserved\n"
        assert sorted(p.name for p in external.iterdir()) == ["sentinel.txt"]


def test_runtime_verifier_intermediate_dir_symlink_escape_no_external_writes() -> None:
    """An intermediate directory (vendor/) is a symlink; verifier must fail."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        vendor = skill / "vendor"
        real_vendor = skill / ".real_vendor"
        vendor.rename(real_vendor)
        external = Path(tmp) / "external_vendor"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        vendor.symlink_to(external)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verifier followed intermediate symlink")
        assert sentinel.read_bytes() == b"preserved\n"


# ---------------------------------------------------------------------------
# 6. Manifest shape / duplicate keys / unsafe paths / baseline binding.
# ---------------------------------------------------------------------------


def _rewrite_manifest(skill: Path, mutator) -> None:
    manifest = skill / "references" / "baselines" / "iff-v1-vendor.json"
    obj = json.loads(manifest.read_bytes())
    obj = mutator(obj) or obj
    manifest.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_runtime_verifier_duplicate_json_key_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        manifest = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Inject a duplicate key by hand-writing the JSON.
        obj_text = manifest.read_text()
        # Append a duplicate top-level "kind" key.
        broken = obj_text.replace(
            '"kind": "icp.iff-v1-vendor-capsule",',
            '"kind": "icp.iff-v1-vendor-capsule",\n"kind": "other",',
            1,
        )
        manifest.write_text(broken, encoding="utf-8")
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "duplicate" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted duplicate JSON key")


def test_runtime_verifier_wrong_schema_kind_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        _rewrite_manifest(skill, lambda o: {**o, "kind": "wrong.kind"})
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "kind" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted wrong kind")


def test_runtime_verifier_wrong_schema_version_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        _rewrite_manifest(skill, lambda o: {**o, "schema_version": 999})
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "schema_version" in str(exc).lower() or "schema" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted wrong schema_version")


def test_runtime_verifier_unsafe_capsule_root_path_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        # An absolute capsule_root would be unsafe.
        _rewrite_manifest(skill, lambda o: {**o, "capsule_root": "/etc"})
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "capsule_root" in str(exc).lower() or "relative" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted absolute capsule_root")


def test_runtime_verifier_unsafe_dest_path_with_dotdot_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))

        def _bad(o):
            scripts = list(o["scripts"])
            scripts[0] = {**scripts[0], "dest_path": "scripts/../../../etc/passwd"}
            return {**o, "scripts": scripts}

        _rewrite_manifest(skill, _bad)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "dest_path" in str(exc).lower() or "canonical" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted unsafe dest_path")


def test_runtime_verifier_baseline_binding_mismatch_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))

        def _bad(o):
            return {**o, "baseline": {**o["baseline"], "sha256": "0" * 64}}

        _rewrite_manifest(skill, _bad)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "baseline" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted baseline binding mismatch")


def test_runtime_verifier_counts_mismatch_fails() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))

        def _bad(o):
            return {**o, "counts": {**o["counts"], "scripts_total": 999}}

        _rewrite_manifest(skill, _bad)
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "count" in str(exc).lower() or "scripts_total" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted count mismatch")


# ---------------------------------------------------------------------------
# 7. Maintenance tool: source mismatch / missing file refuse publication.
# ---------------------------------------------------------------------------


def test_vendor_refresh_source_mismatch_refuses() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        # Build a "wrong" source iff with mismatched bytes for one file.
        bad_iff = Path(tmp) / "iff_bad"
        bad_scripts = bad_iff / "scripts"
        bad_scripts.mkdir(parents=True)
        baseline = json.loads(P0_BASELINE.read_bytes())
        for entry in baseline["scripts"]:
            name = entry["path"].rsplit("/", 1)[-1]
            data = (IFF_SCRIPTS / name).read_bytes()
            (bad_scripts / name).write_bytes(data)
        # Corrupt exactly one file (still regular, just wrong SHA).
        victim_name = baseline["scripts"][0]["path"].rsplit("/", 1)[-1]
        (bad_scripts / victim_name).write_bytes(b"# wrong\n")
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Snapshot capsule + manifest BEFORE failed refresh.
        capsule_before = {
            p.name: p.read_bytes()
            for p in capsule_root.glob("scripts/*.py")
            if p.is_file()
        }
        manifest_before = manifest_path.read_bytes()
        try:
            _VENDOR.refresh(
                iff_root=bad_iff,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert victim_name in str(exc) or "mismatch" in str(exc).lower()
        else:
            raise AssertionError("refresh accepted source mismatch")
        # Existing capsule preserved byte-for-byte.
        capsule_after = {
            p.name: p.read_bytes()
            for p in capsule_root.glob("scripts/*.py")
            if p.is_file()
        }
        assert capsule_after == capsule_before, "failed refresh mutated capsule"
        assert manifest_path.read_bytes() == manifest_before, "failed refresh mutated manifest"
        # No staging residue.
        staging = list(capsule_root.parent.glob(".iff_v1_stage.*"))
        assert staging == [], f"staging residue left: {staging}"
        manifest_tmp = list(manifest_path.parent.glob(".iff-v1-vendor.*"))
        assert manifest_tmp == [], f"manifest temp residue left: {manifest_tmp}"


def test_vendor_refresh_missing_source_file_refuses() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        bad_iff = Path(tmp) / "iff_missing"
        bad_scripts = bad_iff / "scripts"
        bad_scripts.mkdir(parents=True)
        baseline = json.loads(P0_BASELINE.read_bytes())
        for entry in baseline["scripts"]:
            name = entry["path"].rsplit("/", 1)[-1]
            data = (IFF_SCRIPTS / name).read_bytes()
            (bad_scripts / name).write_bytes(data)
        # Remove one file from the source.
        victim_name = baseline["scripts"][0]["path"].rsplit("/", 1)[-1]
        (bad_scripts / victim_name).unlink()
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        manifest_before = manifest_path.read_bytes()
        try:
            _VENDOR.refresh(
                iff_root=bad_iff,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert victim_name in str(exc) or "missing" in str(exc).lower()
        else:
            raise AssertionError("refresh accepted missing source file")
        assert manifest_path.read_bytes() == manifest_before


# ---------------------------------------------------------------------------
# 8. Maintenance tool: existing non-identical capsule refuses publication.
# ---------------------------------------------------------------------------


def test_vendor_refresh_refuses_non_identical_existing_capsule() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Mutate one capsule file in place.
        scripts_dir = capsule_root / "scripts"
        victim = sorted(p for p in scripts_dir.iterdir() if p.is_file())[0]
        victim.write_bytes(victim.read_bytes() + b"\n# drift\n")
        before = {
            p.name: p.read_bytes() for p in scripts_dir.iterdir() if p.is_file()
        }
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "differ" in str(exc).lower() or "non-identical" in str(exc).lower() \
                or "drift" in str(exc).lower() or "capsule" in str(exc).lower()
        else:
            raise AssertionError("refresh silently overwrote non-identical capsule")
        # Existing (drifted) capsule preserved.
        after = {
            p.name: p.read_bytes() for p in scripts_dir.iterdir() if p.is_file()
        }
        assert after == before


def test_vendor_refresh_identical_rerun_allowed() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        manifest_before = manifest_path.read_bytes()
        # Re-run against the same good source: must succeed (no-op).
        result = _VENDOR.refresh(
            iff_root=IFF_ROOT,
            capsule_root=capsule_root,
            baseline_path=baseline_path,
            manifest_path=manifest_path,
            capsule_rel="vendor/iff_v1",
        )
        assert result["ok"] is True
        assert manifest_path.read_bytes() == manifest_before
        # No staging residue.
        assert list(capsule_root.parent.glob(".iff_v1_stage.*")) == []


def test_vendor_refresh_no_temp_residue_on_failure() -> None:
    """A failing refresh must leave no .iff_v1_stage.* / .iff-v1-vendor.* temp dirs."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Truncate the baseline so refresh fails inside the staging phase
        # AFTER the temp tree has been created.
        baseline_path.write_bytes(b"{\n")  # malformed JSON baseline
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError:
            pass
        else:
            raise AssertionError("refresh accepted malformed baseline")
        # No temp residue in capsule_root.parent or manifest_path.parent.
        residue = list(capsule_root.parent.glob(".iff_v1_stage.*"))
        residue += list(manifest_path.parent.glob(".iff-v1-vendor.*"))
        assert residue == [], f"temp residue left behind: {residue}"


# ---------------------------------------------------------------------------
# 9. Maintenance tool: race / non-clobber.
# ---------------------------------------------------------------------------


def test_vendor_refresh_non_clobber_manifest_race() -> None:
    """If a manifest appears between refresh's check and publication, it must not be clobbered."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Pre-create a DIFFERENT manifest at the destination. refresh must
        # detect the non-identical manifest and refuse.
        wrong_manifest = json.loads(manifest_path.read_bytes())
        wrong_manifest["counts"]["scripts_total"] = 999
        manifest_path.write_text(
            json.dumps(wrong_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        wrong_bytes = manifest_path.read_bytes()
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "manifest" in str(exc).lower() or "differ" in str(exc).lower()
        else:
            raise AssertionError("refresh clobbered an existing non-identical manifest")
        assert manifest_path.read_bytes() == wrong_bytes


# ---------------------------------------------------------------------------
# 10. CLI malformed input emits one JSON error, no traceback.
# ---------------------------------------------------------------------------


def test_cli_vendor_no_required_args_emits_json_error_no_traceback() -> None:
    r = _run_cli(VENDOR_TOOL)  # no --iff-root / --capsule-root
    assert r.returncode == 2, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "code" in payload and isinstance(payload["code"], str)
    assert "message" in payload and isinstance(payload["message"], str)
    assert "Traceback" not in r.stderr


def test_cli_vendor_unknown_arg_emits_json_error_no_traceback() -> None:
    r = _run_cli(VENDOR_TOOL, "--iff-root", str(IFF_ROOT), "--bogus", "x")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


def test_cli_verifier_unknown_arg_emits_json_error_no_traceback() -> None:
    r = _run_cli(VERIFY_TOOL, "--bogus")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


# ---------------------------------------------------------------------------
# 11. Maintenance tool rejects symlinked source roots / scripts / capsule roots.
# ---------------------------------------------------------------------------


def test_vendor_refresh_rejects_symlinked_iff_root() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        symlink_iff = Path(tmp) / "iff_symlink"
        symlink_iff.symlink_to(IFF_ROOT)
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        try:
            _VENDOR.refresh(
                iff_root=symlink_iff,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("refresh accepted symlinked iff-root")


def test_vendor_refresh_rejects_symlinked_capsule_root() -> None:
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Replace capsule_root with a symlink.
        real = capsule_root.parent / ".real"
        capsule_root.rename(real)
        external = Path(tmp) / "external_capsule"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        capsule_root.symlink_to(external)
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "symlink" in str(exc).lower() or "capsule" in str(exc).lower()
        else:
            raise AssertionError("refresh accepted symlinked capsule-root")
        # External untouched.
        assert sentinel.read_bytes() == b"preserved\n"


# ---------------------------------------------------------------------------
# 12. Source iff/** remains byte-identical.
# ---------------------------------------------------------------------------


def test_source_iff_remains_byte_identical_after_full_workflow() -> None:
    """All real hashes from iff/scripts/*.py must equal the P0 baseline SHAs,
    and a real CLI refresh run must not mutate any iff file."""
    hashes_before = _real_iff_hashes()
    # Sanity: live iff matches the P0 baseline SHAs exactly.
    expected = {s["path"].rsplit("/", 1)[-1]: s["sha256"] for s in _p0_scripts()}
    assert hashes_before == expected, (
        "live iff/scripts/*.py does not match P0 baseline SHAs; "
        "this test cannot prove immutability against a drifted source"
    )
    # Run the real maintenance CLI in --check mode against the production
    # capsule; it must not write to iff.
    r = _run_cli(
        VENDOR_TOOL,
        "--iff-root", str(IFF_ROOT),
        "--capsule-root", str(PROD_CAPSULE),
        "--check",
    )
    assert r.returncode == 0, f"check failed: rc={r.returncode} stderr={r.stderr!r}"
    hashes_after = _real_iff_hashes()
    assert hashes_after == hashes_before, "maintenance CLI mutated iff source"


def test_git_diff_iff_is_empty_after_workflow() -> None:
    """git diff --exit-code -- iff must be empty (no iff mutation)."""
    r = subprocess.run(
        ["git", "diff", "--exit-code", "--", "iff"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (
        f"git diff -- iff is non-empty:\nstdout={r.stdout}\nstderr={r.stderr}"
    )


# ---------------------------------------------------------------------------
# 13. Maintenance tool CLI success path.
# ---------------------------------------------------------------------------


def test_cli_vendor_check_production_capsule_green() -> None:
    r = _run_cli(
        VENDOR_TOOL,
        "--iff-root", str(IFF_ROOT),
        "--capsule-root", str(PROD_CAPSULE),
        "--check",
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


def test_cli_vendor_refresh_production_idempotent() -> None:
    """A real CLI refresh of the production capsule must succeed (identical re-run)."""
    r = _run_cli(
        VENDOR_TOOL,
        "--iff-root", str(IFF_ROOT),
        "--capsule-root", str(PROD_CAPSULE),
        "--refresh",
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["scripts_total"] == 165


# ---------------------------------------------------------------------------
# 14. RED — exact file-set (no __pycache__ exemption).
# ---------------------------------------------------------------------------


def test_runtime_verifier_pycache_directory_is_not_exempt() -> None:
    """An extra ``__pycache__`` directory under capsule scripts must fail closed."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        (scripts_dir / "__pycache__").mkdir()
        (scripts_dir / "__pycache__" / "x.pyc").write_bytes(b"\x00\x00")
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "__pycache__" in str(exc) or "extra" in str(exc).lower() \
                or "unexpected" in str(exc).lower() or "directory" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted __pycache__ directory")


def test_runtime_verifier_pycache_file_is_not_exempt() -> None:
    """An extra ``__pycache__`` regular file under capsule scripts must fail closed."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        scripts_dir = skill / "vendor" / "iff_v1" / "scripts"
        (scripts_dir / "__pycache__").write_bytes(b"\x00\x00")
        try:
            _VERIFY.verify_skill(skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "__pycache__" in str(exc) or "extra" in str(exc).lower()
        else:
            raise AssertionError("verifier accepted __pycache__ file")


def test_vendor_check_pycache_directory_is_not_exempt() -> None:
    """A ``__pycache__`` directory in the capsule must fail the maintenance check."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        (capsule_root / "scripts" / "__pycache__").mkdir()
        (capsule_root / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        try:
            _VENDOR.check(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
            )
        except _VENDOR.VendorError as exc:
            assert "__pycache__" in str(exc) or "extra" in str(exc).lower() \
                or "unexpected" in str(exc).lower() or "directory" in str(exc).lower()
        else:
            raise AssertionError("maintenance check accepted __pycache__ directory")


def test_vendor_refresh_refuses_existing_capsule_with_pycache() -> None:
    """An existing capsule containing __pycache__ must be rejected pre-publication."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        (capsule_root / "scripts" / "__pycache__").mkdir()
        (capsule_root / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "__pycache__" in str(exc) or "extra" in str(exc).lower() \
                or "unexpected" in str(exc).lower() or "directory" in str(exc).lower()
        else:
            raise AssertionError("refresh accepted existing capsule with __pycache__")


# ---------------------------------------------------------------------------
# 15. RED — first publication is failure-preserving (rollback).
# ---------------------------------------------------------------------------


def test_injected_manifest_failure_rolls_back_newly_published_capsule() -> None:
    """If manifest publication fails right after the capsule was freshly
    published, the newly published capsule must be rolled back, the manifest
    must remain absent, and no staging residue may remain."""
    with _canonical_tempdir() as tmp:
        skill_root_parent = Path(tmp)
        skill = skill_root_parent / "icp"
        (skill / "references" / "baselines").mkdir(parents=True)
        (skill / "vendor").mkdir(parents=True)
        baseline_dst = skill / "references" / "baselines" / "iff-v1.json"
        baseline_dst.write_bytes(P0_BASELINE.read_bytes())
        capsule_root = skill / "vendor" / "iff_v1"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        # Assert the precondition: capsule and manifest both absent.
        assert not capsule_root.exists()
        assert not manifest_path.exists()

        original_os_link = _VENDOR.os.link
        state = {"capsule_published": False}

        def _failing_os_link(src, dst, *args, **kwargs):
            # Only fail when we link the final manifest (dst is manifest_path).
            if Path(dst) == manifest_path and state["capsule_published"]:
                raise FileExistsError(
                    f"injected: manifest exists at {dst}"
                )
            return original_os_link(src, dst, *args, **kwargs)

        # Wrap the publish-capsule step so we can prove the failure happens
        # AFTER capsule publication.
        original_replace = _VENDOR.os.replace

        def _tracking_replace(src, dst, *args, **kwargs):
            result = original_replace(src, dst, *args, **kwargs)
            if Path(dst) == capsule_root:
                state["capsule_published"] = True
            return result

        _VENDOR.os.link = _failing_os_link  # type: ignore[assignment]
        _VENDOR.os.replace = _tracking_replace  # type: ignore[assignment]
        try:
            try:
                _VENDOR.refresh(
                    iff_root=IFF_ROOT,
                    capsule_root=capsule_root,
                    baseline_path=baseline_dst,
                    manifest_path=manifest_path,
                    capsule_rel="vendor/iff_v1",
                )
            except _VENDOR.VendorError as exc:
                assert "manifest" in str(exc).lower() \
                    or "publish" in str(exc).lower() \
                    or "inject" in str(exc).lower() \
                    or "rolled" in str(exc).lower()
            else:
                raise AssertionError(
                    "refresh did not raise on manifest publication failure"
                )
            # The proof: the newly-published capsule was rolled back.
            assert state["capsule_published"] is True, (
                "test setup failure: capsule was never published before the "
                "injected failure; the test cannot prove rollback"
            )
            assert not capsule_root.exists(), (
                f"newly published capsule was NOT rolled back: {capsule_root} exists"
            )
            assert not capsule_root.is_symlink(), (
                f"capsule root is a leftover symlink: {capsule_root}"
            )
            assert not manifest_path.exists(), (
                f"manifest was created despite failure: {manifest_path}"
            )
            # No staging residue.
            staging_residue = list(capsule_root.parent.glob(".iff_v1_stage.*"))
            staging_residue += list(manifest_path.parent.glob(".iff-v1-vendor.*"))
            assert staging_residue == [], (
                f"staging residue left after failed publish: {staging_residue}"
            )
            # No external directory under the skill vendor parent leaked.
            leftover_vendor = sorted(
                p.name for p in capsule_root.parent.iterdir() if p.name != "iff_v1"
            )
            leftover_baselines = sorted(
                p.name for p in manifest_path.parent.iterdir()
                if p.name != "iff-v1.json"
            )
            assert leftover_vendor == [], (
                f"vendor dir residue after rollback: {leftover_vendor}"
            )
            assert leftover_baselines == [], (
                f"baselines dir residue after rollback: {leftover_baselines}"
            )
        finally:
            _VENDOR.os.link = original_os_link  # type: ignore[assignment]
            _VENDOR.os.replace = original_replace  # type: ignore[assignment]


def test_manifest_directory_fsync_failure_rolls_back_linked_manifest_and_capsule() -> None:
    """A linked manifest is already published before its parent fsync runs."""
    with _canonical_tempdir() as tmp:
        skill = Path(tmp) / "icp"
        (skill / "references" / "baselines").mkdir(parents=True)
        (skill / "vendor").mkdir(parents=True)
        baseline_dst = skill / "references" / "baselines" / "iff-v1.json"
        baseline_dst.write_bytes(P0_BASELINE.read_bytes())
        capsule_root = skill / "vendor" / "iff_v1"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        original_fsync_dir = _VENDOR._fsync_dir

        def _fail_after_manifest_link(path: Path) -> None:
            if Path(path) == manifest_path.parent and manifest_path.exists():
                raise OSError("injected manifest directory fsync failure")
            original_fsync_dir(path)

        _VENDOR._fsync_dir = _fail_after_manifest_link
        try:
            try:
                _VENDOR.refresh(
                    iff_root=IFF_ROOT,
                    capsule_root=capsule_root,
                    baseline_path=baseline_dst,
                    manifest_path=manifest_path,
                    capsule_rel="vendor/iff_v1",
                )
            except OSError as exc:
                assert "manifest directory fsync failure" in str(exc)
            else:
                raise AssertionError("expected injected manifest directory fsync failure")
        finally:
            _VENDOR._fsync_dir = original_fsync_dir

        assert not capsule_root.exists()
        assert not manifest_path.exists()
        assert not list((skill / "vendor").glob(".iff_v1.stage-*"))
        assert not list(manifest_path.parent.glob(".iff-v1-vendor.json.stage-*"))


def test_injected_manifest_failure_preserves_pre_existing_identical_capsule() -> None:
    """A pre-existing identical capsule must NOT be deleted/rolled back on
    manifest publication failure."""
    with _canonical_tempdir() as tmp:
        skill = _build_skill_root_in_tmp(Path(tmp))
        capsule_root = skill / "vendor" / "iff_v1"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        # Snapshot capsule bytes (this is the pre-existing identical capsule).
        capsule_before = {
            p.name: p.read_bytes()
            for p in (capsule_root / "scripts").iterdir()
            if p.is_file()
        }
        # Remove the manifest so this refresh is a "manifest-only" publish.
        manifest_path.unlink()
        assert not manifest_path.exists()

        original_os_link = _VENDOR.os.link

        def _failing_os_link(src, dst, *args, **kwargs):
            if Path(dst) == manifest_path:
                raise FileExistsError(f"injected: manifest exists at {dst}")
            return original_os_link(src, dst, *args, **kwargs)

        _VENDOR.os.link = _failing_os_link  # type: ignore[assignment]
        try:
            try:
                _VENDOR.refresh(
                    iff_root=IFF_ROOT,
                    capsule_root=capsule_root,
                    baseline_path=baseline_path,
                    manifest_path=manifest_path,
                    capsule_rel="vendor/iff_v1",
                )
            except _VENDOR.VendorError:
                pass
            else:
                raise AssertionError("refresh did not raise on manifest failure")
            # Pre-existing capsule must be preserved byte-for-byte.
            capsule_after = {
                p.name: p.read_bytes()
                for p in (capsule_root / "scripts").iterdir()
                if p.is_file()
            }
            assert capsule_after == capsule_before, (
                "pre-existing identical capsule was rolled back despite being "
                "pre-existing"
            )
            assert not manifest_path.exists()
        finally:
            _VENDOR.os.link = original_os_link  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 16. RED — intermediate symlink escape on capsule root chain.
# ---------------------------------------------------------------------------


def test_vendor_refresh_rejects_intermediate_symlink_in_capsule_chain() -> None:
    """``through`` is a symlink to an external dir; ``through/vendor/iff_v1``
    is the capsule root. refresh() must reject before external creation."""
    with _canonical_tempdir() as tmp:
        tmp = tmp  # already canonicalized by _canonical_tempdir
        skill = _build_skill_root_in_tmp(tmp)
        # External dir the symlink will point at.
        external = tmp / "external_target"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        # Build symlink chain: through -> external
        through = tmp / "through"
        through.symlink_to(external)
        # capsule_root points THROUGH the symlink.
        capsule_root = through / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "symlink" in str(exc).lower(), (
                f"refresh did not name symlink in error: {exc}"
            )
        else:
            raise AssertionError("refresh followed intermediate symlink")
        # External dir must not have a vendor/ created in it.
        assert sentinel.read_bytes() == b"preserved\n"
        assert not (external / "vendor").exists(), (
            "external dir received a vendor/ subtree through symlink"
        )
        assert sorted(p.name for p in external.iterdir()) == ["sentinel.txt"]


def test_vendor_refresh_rejects_intermediate_symlink_in_iff_root_chain() -> None:
    """An iff-root path with any caller-supplied intermediate symlink (not
    only the leaf) must be rejected before source traversal."""
    with _canonical_tempdir() as tmp:
        tmp = tmp  # already canonicalized by _canonical_tempdir
        skill = _build_skill_root_in_tmp(tmp)
        # Build a path whose intermediate component is a symlink, but whose
        # leaf is real. link -> REPO_ROOT, iff_root_arg = link/iff.
        # The leaf 'iff' is real; 'link' is the intermediate symlink.
        link = tmp / "link_to_repo"
        link.symlink_to(REPO_ROOT)
        iff_root_arg = link / "iff"
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        manifest_path = skill / "references" / "baselines" / "iff-v1-vendor.json"
        try:
            _VENDOR.refresh(
                iff_root=iff_root_arg,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "symlink" in str(exc).lower(), (
                f"refresh did not name symlink: {exc}"
            )
        else:
            raise AssertionError("refresh followed intermediate iff-root symlink")


def test_vendor_refresh_rejects_intermediate_symlink_in_manifest_chain() -> None:
    """A manifest path whose chain contains any caller-supplied intermediate
    symlink (not only the direct parent) must be rejected before external
    write."""
    with _canonical_tempdir() as tmp:
        tmp = tmp  # already canonicalized by _canonical_tempdir
        skill = _build_skill_root_in_tmp(tmp)
        # Build a path whose grandparent is a symlink, not just the parent.
        external = tmp / "external_baselines"
        external.mkdir()
        (external / "baselines").mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        link = skill / "references" / "link_to_external"
        link.symlink_to(external)
        # manifest_path goes through the symlink at link, then a real baselines/
        manifest_path = link / "baselines" / "iff-v1-vendor.json"
        capsule_root = skill / "vendor" / "iff_v1"
        baseline_path = skill / "references" / "baselines" / "iff-v1.json"
        try:
            _VENDOR.refresh(
                iff_root=IFF_ROOT,
                capsule_root=capsule_root,
                baseline_path=baseline_path,
                manifest_path=manifest_path,
                capsule_rel="vendor/iff_v1",
            )
        except _VENDOR.VendorError as exc:
            assert "symlink" in str(exc).lower(), (
                f"refresh did not name symlink: {exc}"
            )
        else:
            raise AssertionError("refresh followed intermediate manifest symlink")
        # External untouched.
        assert sentinel.read_bytes() == b"preserved\n"
        assert sorted(p.name for p in (external / "baselines").iterdir()) == []


# ---------------------------------------------------------------------------
# 17. RED — verify_skill must not .resolve() caller-supplied skill root.
# ---------------------------------------------------------------------------


def test_verify_skill_rejects_symlinked_skill_root() -> None:
    """A symlinked skill root must be rejected; verify_skill must not call
    .resolve() and thereby erase symlink identity."""
    with _canonical_tempdir() as tmp:
        tmp = tmp  # already canonicalized by _canonical_tempdir
        real_skill = _build_skill_root_in_tmp(tmp)
        external = tmp / "external_skill_root"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        symlink_skill = tmp / "icp_link"
        symlink_skill.symlink_to(real_skill)
        try:
            _VERIFY.verify_skill(symlink_skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verify_skill followed symlinked skill root")
        # External untouched.
        assert sentinel.read_bytes() == b"preserved\n"


def test_verify_skill_rejects_intermediate_symlink_in_skill_chain() -> None:
    """A skill_root whose path chain contains a symlink must be rejected."""
    with _canonical_tempdir() as tmp:
        tmp = tmp  # already canonicalized by _canonical_tempdir
        real_skill = _build_skill_root_in_tmp(tmp)
        # Build path through a symlinked parent.
        external_parent = tmp / "external_parent"
        external_parent.mkdir()
        sentinel = external_parent / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        link_parent = tmp / "link_parent"
        link_parent.symlink_to(external_parent)
        # Even though the leaf 'icp' is real, traversing link_parent is a
        # caller-supplied intermediate symlink.
        symlink_skill = link_parent / "icp"
        # Create symlinked skill chain: link_parent -> external_parent, then
        # we need a real 'icp' below external_parent. Copy real_skill there.
        # We must NOT need to traverse via symlink; we want a skill chain
        # whose intermediate is a symlink.
        linked_real = external_parent / "icp"
        # Don't actually copy; we just need to prove the verifier rejects the
        # symlink path before any directory traversal.
        try:
            _VERIFY.verify_skill(symlink_skill)
        except _VERIFY.CapsuleIntegrityError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verify_skill followed symlinked skill chain")
        # External untouched.
        assert sentinel.read_bytes() == b"preserved\n"
        assert not linked_real.exists()


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
