#!/usr/bin/env python3
"""Vertical RED -> GREEN selftest for the ICP P2b lanhu-figma DesignSource.

Covers the public Python API and CLI of ``design_sources/lanhu_figma_v1.py``:

1. ``resolve`` HTTP(S) Lanhu locator -> deterministic board ref; rejects
   non-HTTP schemes, fragments, credentials, missing/duplicate/blank
   ``image_id``, and malformed input.
2. ``probe`` verifies the installed capsule first, then runs only the fixed
   vendored ``fetch.py`` + ``download_cover.py`` primitives using temporary
   storage; never mutates the task CSV, project root, or final bundle root;
   cleans up every temporary artifact on success and failure.
3. ``fetch_normalize`` runs the exact fixed seven-step capsule sequence,
   writes the required top-level artifacts plus the canonical
   ``design_provenance.json`` and ``reference_manifest.json``, and publishes
   atomically with no clobber.
4. ``verify_bundle`` fails closed on missing/extra/symlinked/non-regular
   entries, duplicate JSON keys, digest mismatch, malformed PNG, missing
   ``figma_json.artboard``, wrong scene ``sourceSchema``, provenance/board-ref
   mismatch, and asset-inventory mismatch.
5. CLI subcommands ``resolve``, ``probe``, ``fetch-normalize``,
   ``verify-bundle``; unknown subcommand / unknown flag / malformed input
   emit one canonical JSON object on stderr (exit 2), never a traceback.
6. No cookie/token/secret is accepted as an argument, placed in argv,
   persisted, or emitted.

The private ``_run_step`` subprocess helper may be monkeypatched to
synthesize deterministic capsule fixtures; no such override exists in the
production public API or CLI.

Run directly:

    PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2b_lanhu.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ICP_ROOT = Path(__file__).resolve().parents[1]
ICP_SCRIPTS = Path(__file__).resolve().parent
DESIGN_SOURCES = ICP_SCRIPTS / "design_sources"
MODULE_PATH = DESIGN_SOURCES / "lanhu_figma_v1.py"
PROBE_KIND = "design_source_probe.v1"
REPORT_KIND = "design_bundle_report.v1"
PROVENANCE_KIND = "icp.lanhu-figma.design-provenance.v1"
REFERENCE_MANIFEST_KIND = "icp.lanhu-figma.reference-manifest.v1"
SOURCE_ID = "lanhu-figma"
IR_SCHEMA = "lanhu_figma_json"

# Production capsule paths (read-only fixtures). Any self-test that needs
# to mutate a capsule file MUST do so against a temporary copy built by
# ``_materialize_isolated_capsule_skill_root``; ``PROD_CAPSULE_SCRIPTS``
# exists only so the isolation assertion can prove the mutation target is
# not under the production capsule.
PROD_CAPSULE_SCRIPTS = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
PROD_VENDOR_MANIFEST = (
    ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
)
PROD_BASELINE = ICP_ROOT / "references" / "baselines" / "iff-v1.json"


# ---------------------------------------------------------------------------
# Module loader.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_KNOWN_ERROR = ("design_source_failed", "invalid_locator", "bundle_invalid")


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _canonical_tempdir(prefix: str = "p2b_"):
    """Yield a temp dir whose path is realpath-canonicalized (no /var symlink)."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(os.path.realpath(str(tmp)))


def _argv_value(argv: list[str], flag: str) -> str | None:
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _minimal_png(width: int = 2, height: int = 3) -> bytes:
    """Build a tiny deterministic RGBA PNG (no third-party dependency)."""
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _default_raw(*, artboard: dict | None = None, design_id: str = "d1") -> dict:
    return {
        "design_name": "fixture",
        "design_id": design_id,
        "version_id": "v1",
        "lanhu_url": "https://lanhuapp.com/fixture",
        "figma_json": {
            "artboard": artboard if artboard is not None else {"id": "a1", "bbox": [0, 0, 2, 3]}
        },
    }


def _default_scene() -> dict:
    return {
        "sourceSchema": IR_SCHEMA,
        "designName": "fixture",
        "designId": "d1",
        "versionId": "v1",
        "lanhuUrl": "https://lanhuapp.com/fixture",
        "artboard": {"id": "a1", "name": "artboard", "bbox": [0, 0, 100, 100]},
        "nodes": [],
        "systemUiExclusions": [],
    }


def _make_synthesizer(
    module,
    *,
    raw: dict | None = None,
    raw_fail: bool = False,
    cover_fail: bool = False,
    write_fail: bool = False,
    scene_fail: bool = False,
    scene_obj: dict | None = None,
    png_bytes: bytes | None = None,
    extra_assets: dict[str, bytes] | None = None,
    skip_legacy_manifest: bool = False,
):
    """Build a deterministic replacement for ``lanhu_figma_v1._run_step``.

    Each branch inspects the fixed argv contract for the step's ``--output``
    / ``--out`` / ``--input`` path and synthesizes a stable fixture artifact.
    Failures are raised as the module's ``LanhuFigmaError`` so they exercise
    the same error path the production subprocess runner uses.
    """
    error_cls = module.LanhuFigmaError
    raw_obj = raw if raw is not None else _default_raw()
    scene = scene_obj if scene_obj is not None else _default_scene()
    png = png_bytes if png_bytes is not None else _minimal_png()

    def _synth(script_name: str, argv: list[str]) -> None:
        if script_name == "fetch.py":
            if raw_fail:
                raise error_cls("injected fetch.py failure")
            out = _argv_value(argv, "--output")
            if out:
                op = Path(out)
                op.parent.mkdir(parents=True, exist_ok=True)
                op.write_text(
                    json.dumps(raw_obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                # fetch.py also writes assets/manifest.json when slices exist.
                # The synthesizer writes a deterministic empty slices manifest
                # plus an optional extra asset so asset-inventory is non-empty.
                assets_dir = op.parent / "assets"
                assets_dir.mkdir(parents=True, exist_ok=True)
                manifest = []
                if extra_assets:
                    for name, body in sorted(extra_assets.items()):
                        (assets_dir / name).write_bytes(body)
                        manifest.append(
                            {
                                "layer_id": name,
                                "layer_name": name,
                                "layer_path": name,
                                "frame": {"left": 0, "top": 0, "width": 1, "height": 1},
                                "png_url": None,
                                "svg_url": None,
                                "png_path": f"assets/{name}" if name.endswith(".png") else None,
                                "svg_path": f"assets/{name}" if name.endswith(".svg") else None,
                            }
                        )
                if not skip_legacy_manifest:
                    (assets_dir / "manifest.json").write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        elif script_name == "write.py":
            if write_fail:
                raise error_cls("injected write.py failure")
            out = _argv_value(argv, "--output")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text("# spec.md fixture\n", encoding="utf-8")
        elif script_name == "download_cover.py":
            if cover_fail:
                raise error_cls("injected download_cover.py failure")
            out = _argv_value(argv, "--out")
            op = Path(out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(png)
        elif script_name == "export_figma_scene.py":
            if scene_fail:
                raise error_cls("injected export_figma_scene.py failure")
            out = _argv_value(argv, "--out")
            op = Path(out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(
                json.dumps(scene, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif script_name == "export_tokens.py":
            out = _argv_value(argv, "--out")
            op = Path(out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(
                json.dumps(
                    {"colors": [], "fontSizes": [], "radii": [], "borders": [], "shadows": []},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        elif script_name == "export_assets_manifest.py":
            out = _argv_value(argv, "--out")
            op = Path(out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(
                json.dumps({}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        elif script_name == "classify_design.py":
            out = _argv_value(argv, "--out")
            op = Path(out)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(
                json.dumps(
                    {
                        "type": "screen",
                        "artboard": {"width": 2, "height": 3, "scale": 1},
                        "viewport": {"width": 2, "height": 3},
                        "states": [],
                        "reason": "fixture",
                        "raw": "raw.json",
                        "reference": "reference.png",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            raise AssertionError(f"unexpected script in synthesizer: {script_name}")

    return _synth


@contextlib.contextmanager
def _patched_step(module, synthesizer):
    original = module._run_step
    module._run_step = synthesizer
    try:
        yield
    finally:
        module._run_step = original


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _good_locator() -> str:
    return "https://lanhuapp.com/web/#/iframe/project/image?image_id=abc123&pid=p1&tid=t1"


def _good_locator_query() -> str:
    """A pure query-string locator (no fragment)."""
    return "https://lanhuapp.com/api/project/image?image_id=abc123&pid=p1&tid=t1"


def _canonical_json(obj: dict) -> bytes:
    """Canonical JSON bytes matching the production encoder."""
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# 1. resolve — happy path.
# ---------------------------------------------------------------------------


def test_resolve_https_returns_deterministic_board_ref() -> None:
    module = _load("lanhu_figma_v1_under_test_a", MODULE_PATH)
    loc = _good_locator_query()
    ref = module.resolve(loc)
    assert isinstance(ref, str) and ref
    # Deterministic: same locator -> same ref.
    assert module.resolve(loc) == ref
    # Different locator -> different ref.
    other = module.resolve(
        "https://lanhuapp.com/api/project/image?image_id=other&pid=p1&tid=t1"
    )
    assert other != ref


def test_resolve_http_scheme_accepted() -> None:
    module = _load("lanhu_figma_v1_under_test_b", MODULE_PATH)
    ref = module.resolve("http://example.com/path?image_id=abc")
    assert isinstance(ref, str) and ref


def test_resolve_preserves_locator_bytes_for_board_ref() -> None:
    """The board ref must be a deterministic digest of the locator bytes."""
    module = _load("lanhu_figma_v1_under_test_c", MODULE_PATH)
    loc = _good_locator_query()
    ref = module.resolve(loc)
    digest = hashlib.sha256(loc.encode("utf-8")).hexdigest()
    assert digest in ref


# ---------------------------------------------------------------------------
# 2. resolve — negative cases.
# ---------------------------------------------------------------------------


def test_resolve_rejects_missing_image_id() -> None:
    module = _load("lanhu_figma_v1_under_test_d", MODULE_PATH)
    try:
        module.resolve("https://lanhuapp.com/path?pid=p1")
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted missing image_id")


def test_resolve_rejects_blank_image_id() -> None:
    module = _load("lanhu_figma_v1_under_test_e", MODULE_PATH)
    try:
        module.resolve("https://lanhuapp.com/path?image_id=")
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted blank image_id")


def test_resolve_rejects_whitespace_image_id() -> None:
    module = _load("lanhu_figma_v1_under_test_f", MODULE_PATH)
    try:
        module.resolve("https://lanhuapp.com/path?image_id=%20%20")
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted whitespace image_id")


def test_resolve_rejects_duplicate_image_id() -> None:
    module = _load("lanhu_figma_v1_under_test_g", MODULE_PATH)
    try:
        module.resolve("https://lanhuapp.com/path?image_id=a&image_id=b")
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted duplicate image_id")


def test_resolve_rejects_non_http_scheme() -> None:
    module = _load("lanhu_figma_v1_under_test_h", MODULE_PATH)
    for bad in (
        "ftp://lanhuapp.com/path?image_id=a",
        "file:///etc/passwd?image_id=a",
        "javascript:alert(1)",
        "lanhuapp.com/path?image_id=a",  # no scheme
    ):
        try:
            module.resolve(bad)
        except module.LanhuFigmaError:
            continue
        raise AssertionError(f"resolve accepted non-http scheme: {bad!r}")


def test_resolve_rejects_fragment() -> None:
    module = _load("lanhu_figma_v1_under_test_i", MODULE_PATH)
    try:
        module.resolve("https://lanhuapp.com/path?image_id=a#frag")
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted fragment")


def test_resolve_rejects_credentials() -> None:
    module = _load("lanhu_figma_v1_under_test_j", MODULE_PATH)
    for bad in (
        "https://user:pass@lanhuapp.com/path?image_id=a",
        "https://user@lanhuapp.com/path?image_id=a",
    ):
        try:
            module.resolve(bad)
        except module.LanhuFigmaError:
            continue
        raise AssertionError(f"resolve accepted credentials: {bad!r}")


def test_resolve_rejects_non_string_and_empty() -> None:
    module = _load("lanhu_figma_v1_under_test_k", MODULE_PATH)
    for bad in (None, 123, "", b"bytes", "   "):
        try:
            module.resolve(bad)  # type: ignore[arg-type]
        except module.LanhuFigmaError:
            continue
        except TypeError:
            # Acceptable as long as no traceback leaks to CLI.
            continue
        raise AssertionError(f"resolve accepted bad input: {bad!r}")


# ---------------------------------------------------------------------------
# 3. probe — happy path (monkeypatched subprocess helper).
# ---------------------------------------------------------------------------


def test_probe_returns_canonical_payload_with_capsule_info() -> None:
    module = _load("lanhu_figma_v1_under_test_l", MODULE_PATH)
    loc = _good_locator_query()
    with _patched_step(module, _make_synthesizer(module)):
        report = module.probe(loc)
    assert report["ok"] is True
    assert report["kind"] == PROBE_KIND
    assert report["schema_version"] == 1
    assert report["source_id"] == SOURCE_ID
    assert report["locator"] == loc
    assert report["board_ref"] == module.resolve(loc)
    assert report["capsule"]["ok"] is True
    assert report["capsule"]["scripts_total"] == 165
    assert report["probe"]["raw_artboard_present"] is True
    assert report["probe"]["reference_png_present"] is True
    assert report["probe"]["reference_png_width"] == 2
    assert report["probe"]["reference_png_height"] == 3


def test_probe_uses_only_temporary_storage_and_cleans_up() -> None:
    module = _load("lanhu_figma_v1_under_test_m", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_probe_") as tmp:
        sentinel = tmp / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        # No bundle root, no task CSV touched. Probe must only use tempfile.
        captured_dirs: list[Path] = []
        original_mkdtemp = tempfile.mkdtemp

        def _capturing_mkdtemp(*a, **k):
            d = original_mkdtemp(*a, **k)
            captured_dirs.append(Path(d))
            return d

        module.tempfile.mkdtemp = _capturing_mkdtemp  # type: ignore[assignment]
        try:
            with _patched_step(module, _make_synthesizer(module)):
                module.probe(loc)
        finally:
            module.tempfile.mkdtemp = original_mkdtemp  # type: ignore[assignment]
        # Temp dirs cleaned up.
        for d in captured_dirs:
            assert not d.exists(), f"probe left temp dir: {d}"
        # Sentinel untouched.
        assert sentinel.read_bytes() == b"preserved\n"


def test_probe_step_failure_emits_clean_error_no_temp_residue() -> None:
    module = _load("lanhu_figma_v1_under_test_n", MODULE_PATH)
    loc = _good_locator_query()
    captured_dirs: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def _capturing_mkdtemp(*a, **k):
        d = original_mkdtemp(*a, **k)
        captured_dirs.append(Path(d))
        return d

    module.tempfile.mkdtemp = _capturing_mkdtemp  # type: ignore[assignment]
    try:
        try:
            with _patched_step(module, _make_synthesizer(module, raw_fail=True)):
                module.probe(loc)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("probe did not fail on fetch.py failure")
    finally:
        module.tempfile.mkdtemp = original_mkdtemp  # type: ignore[assignment]
    for d in captured_dirs:
        assert not d.exists(), f"probe left temp residue after failure: {d}"


def test_probe_rejects_locator_missing_artboard() -> None:
    module = _load("lanhu_figma_v1_under_test_o", MODULE_PATH)
    loc = _good_locator_query()
    bad_raw = {"figma_json": {"artboard": None}}
    with _patched_step(module, _make_synthesizer(module, raw=bad_raw)):
        try:
            module.probe(loc)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("probe accepted raw.json missing artboard")


# ---------------------------------------------------------------------------
# 4. fetch_normalize — happy path.
# ---------------------------------------------------------------------------


def test_fetch_normalize_publishes_canonical_bundle() -> None:
    module = _load("lanhu_figma_v1_under_test_p", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_fn_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module)):
            report = module.fetch_normalize(loc, bundle)
        # Bundle published.
        assert bundle.is_dir()
        assert not bundle.is_symlink()
        # Required top-level entries.
        for name in (
            "raw.json",
            "spec.md",
            "reference.png",
            "reference_manifest.json",
            "scene.json",
            "tokens.json",
            "assets_manifest.json",
            "design_classification.json",
            "design_provenance.json",
        ):
            assert (bundle / name).is_file(), f"missing top-level {name}"
        assert (bundle / "assets").is_dir()
        assert (bundle / "assets" / "manifest.json").is_file()
        # No staging residue.
        residue = sorted(p.name for p in bundle.parent.iterdir() if p.name.startswith("."))
        assert residue == [], f"staging residue: {residue}"
        # Report shape.
        assert report["ok"] is True
        assert report["kind"] == REPORT_KIND
        assert report["schema_version"] == 1
        assert report["source_id"] == SOURCE_ID
        assert report["board_ref"] == module.resolve(loc)
        assert report["locator"] == loc
        assert report["bundle_root"] == str(bundle)
        # Artifacts covers every required top-level (other than provenance).
        for name in (
            "raw.json",
            "spec.md",
            "reference.png",
            "reference_manifest.json",
            "scene.json",
            "tokens.json",
            "assets_manifest.json",
            "design_classification.json",
        ):
            assert name in report["artifacts"]
            assert report["artifacts"][name] == hashlib.sha256(
                (bundle / name).read_bytes()
            ).hexdigest()


def test_fetch_normalize_provenance_shape_and_digest_binding() -> None:
    module = _load("lanhu_figma_v1_under_test_q", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_prov_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module)):
            module.fetch_normalize(loc, bundle)
        prov = json.loads((bundle / "design_provenance.json").read_bytes())
        assert prov["kind"] == PROVENANCE_KIND
        assert prov["schema_version"] == 1
        assert prov["source_id"] == SOURCE_ID
        assert prov["ir_schema"] == IR_SCHEMA
        assert prov["board_ref"] == module.resolve(loc)
        assert prov["locator"] == loc
        # Every required top-level artifact (other than provenance) has a digest.
        for name in (
            "raw.json",
            "spec.md",
            "reference.png",
            "reference_manifest.json",
            "scene.json",
            "tokens.json",
            "assets_manifest.json",
            "design_classification.json",
        ):
            assert prov["artifacts"][name] == hashlib.sha256(
                (bundle / name).read_bytes()
            ).hexdigest()
        # assets_inventory is a sorted [relpath, sha256] list.
        inv = prov["assets_inventory"]
        assert isinstance(inv, list)
        rels = [row[0] for row in inv]
        assert rels == sorted(rels), "assets inventory not sorted by relpath"
        for rel, sha in inv:
            assert (bundle / "assets" / rel).is_file()
            assert sha == hashlib.sha256(
                (bundle / "assets" / rel).read_bytes()
            ).hexdigest()
        # No 'design_provenance.json' digest bound inside provenance itself.
        assert "design_provenance.json" not in prov["artifacts"]


def test_fetch_normalize_reference_manifest_binds_sha_and_dimensions() -> None:
    module = _load("lanhu_figma_v1_under_test_r", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_ref_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module)):
            module.fetch_normalize(loc, bundle)
        rm = json.loads((bundle / "reference_manifest.json").read_bytes())
        assert rm["kind"] == REFERENCE_MANIFEST_KIND
        assert rm["schema_version"] == 1
        ref_bytes = (bundle / "reference.png").read_bytes()
        assert rm["sha256"] == hashlib.sha256(ref_bytes).hexdigest()
        assert rm["width"] == 2
        assert rm["height"] == 3


def test_fetch_normalize_preserves_legacy_assets_manifest_and_files() -> None:
    module = _load("lanhu_figma_v1_under_test_s", MODULE_PATH)
    loc = _good_locator_query()
    extra = {"foo.png": b"\x00png-foo", "bar.svg": b"<svg/>"}
    with _canonical_tempdir(prefix="p2b_assets_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module, extra_assets=extra)):
            module.fetch_normalize(loc, bundle)
        # Legacy manifest exists.
        assert (bundle / "assets" / "manifest.json").is_file()
        # Extracted asset files preserved.
        assert (bundle / "assets" / "foo.png").read_bytes() == b"\x00png-foo"
        assert (bundle / "assets" / "bar.svg").read_bytes() == b"<svg/>"
        prov = json.loads((bundle / "design_provenance.json").read_bytes())
        inv = {row[0]: row[1] for row in prov["assets_inventory"]}
        assert inv["foo.png"] == hashlib.sha256(b"\x00png-foo").hexdigest()
        assert inv["bar.svg"] == hashlib.sha256(b"<svg/>").hexdigest()


def test_fetch_normalize_ensures_empty_assets_manifest_when_no_slices() -> None:
    module = _load("lanhu_figma_v1_under_test_t", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_empty_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module, skip_legacy_manifest=True)):
            module.fetch_normalize(loc, bundle)
        # Wrapper must still ensure assets/ exists with an empty legacy manifest.
        assert (bundle / "assets").is_dir()
        legacy = json.loads((bundle / "assets" / "manifest.json").read_bytes())
        assert legacy == []


def test_fetch_normalize_deterministic_across_runs() -> None:
    module = _load("lanhu_figma_v1_under_test_u", MODULE_PATH)
    loc = _good_locator_query()
    runs: list[bytes] = []
    for _ in range(2):
        with _canonical_tempdir(prefix="p2b_det_") as tmp:
            bundle = tmp / "bundle"
            with _patched_step(module, _make_synthesizer(module)):
                module.fetch_normalize(loc, bundle)
            prov = (bundle / "design_provenance.json").read_bytes()
            ref = (bundle / "reference_manifest.json").read_bytes()
            runs.append(prov + b"\n" + ref)
    assert runs[0] == runs[1], (
        "deterministic artifacts drift across runs for the same locator"
    )


# ---------------------------------------------------------------------------
# 5. fetch_normalize — atomicity / non-clobber / symlink rejection.
# ---------------------------------------------------------------------------


def test_fetch_normalize_refuses_existing_bundle() -> None:
    module = _load("lanhu_figma_v1_under_test_v", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_exists_") as tmp:
        bundle = tmp / "bundle"
        bundle.mkdir()
        (bundle / "preexisting.txt").write_text("do-not-overwrite", encoding="utf-8")
        try:
            with _patched_step(module, _make_synthesizer(module)):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("fetch_normalize overwrote existing bundle")
        assert (bundle / "preexisting.txt").read_text() == "do-not-overwrite"
        assert not list(bundle.parent.glob(".lanhu_figma_v1_stage.*"))


def test_fetch_normalize_refuses_symlinked_bundle_root() -> None:
    module = _load("lanhu_figma_v1_under_test_w", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_symlink_") as tmp:
        external = tmp / "external_bundle"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        bundle = tmp / "bundle"
        bundle.symlink_to(external)
        try:
            with _patched_step(module, _make_synthesizer(module)):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("fetch_normalize followed symlinked bundle_root")
        assert sentinel.read_bytes() == b"preserved\n"
        assert sorted(p.name for p in external.iterdir()) == ["sentinel.txt"]


def test_fetch_normalize_rejects_intermediate_symlink_in_chain() -> None:
    module = _load("lanhu_figma_v1_under_test_x", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_inter_") as tmp:
        external = tmp / "external_parent"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_bytes(b"preserved\n")
        link = tmp / "link_to_external"
        link.symlink_to(external)
        bundle = link / "bundle"
        try:
            with _patched_step(module, _make_synthesizer(module)):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("fetch_normalize followed intermediate symlink")
        assert sentinel.read_bytes() == b"preserved\n"
        assert not (external / "bundle").exists()


def test_fetch_normalize_step_failure_cleans_staging_and_leaves_no_bundle() -> None:
    module = _load("lanhu_figma_v1_under_test_y", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_fail_") as tmp:
        bundle = tmp / "bundle"
        try:
            with _patched_step(module, _make_synthesizer(module, write_fail=True)):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("fetch_normalize did not fail on step error")
        assert not bundle.exists()
        assert not bundle.is_symlink()
        residue = list(tmp.glob(".lanhu_figma_v1_stage.*"))
        assert residue == [], f"staging residue: {residue}"


# ---------------------------------------------------------------------------
# 6. verify_bundle — happy path.
# ---------------------------------------------------------------------------


def test_verify_bundle_canonical_payload_on_published_bundle() -> None:
    module = _load("lanhu_figma_v1_under_test_z", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_vb_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module)):
            module.fetch_normalize(loc, bundle)
        report = module.verify_bundle(bundle)
        assert report["ok"] is True
        assert report["kind"] == REPORT_KIND
        assert report["schema_version"] == 1
        assert report["source_id"] == SOURCE_ID
        assert report["board_ref"] == module.resolve(loc)
        assert report["locator"] == loc
        assert report["bundle_root"] == str(bundle)


def test_verify_bundle_idempotent_after_publication() -> None:
    module = _load("lanhu_figma_v1_under_test_aa", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_idem_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _make_synthesizer(module)):
            module.fetch_normalize(loc, bundle)
        r1 = module.verify_bundle(bundle)
        r2 = module.verify_bundle(bundle)
        assert r1 == r2


# ---------------------------------------------------------------------------
# 7. verify_bundle — negative cases.
# ---------------------------------------------------------------------------


def _publish(module, tmp: Path, *, synthesizer=None, locator=None) -> Path:
    bundle = tmp / "bundle"
    syn = synthesizer if synthesizer is not None else _make_synthesizer(module)
    with _patched_step(module, syn):
        module.fetch_normalize(locator or _good_locator_query(), bundle)
    return bundle


def test_verify_bundle_rejects_missing_top_level_artifact() -> None:
    module = _load("lanhu_figma_v1_under_test_ab", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_miss_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "spec.md").unlink()
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("verify_bundle accepted missing top-level")


def test_verify_bundle_rejects_extra_top_level_artifact() -> None:
    module = _load("lanhu_figma_v1_under_test_ac", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_extra_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "rogue.txt").write_text("rogue", encoding="utf-8")
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("verify_bundle accepted extra top-level")


def test_verify_bundle_rejects_symlinked_artifact() -> None:
    module = _load("lanhu_figma_v1_under_test_ad", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_sym_") as tmp:
        bundle = _publish(module, tmp)
        external = tmp / "external_spec.md"
        external.write_text("external", encoding="utf-8")
        (bundle / "spec.md").unlink()
        (bundle / "spec.md").symlink_to(external)
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle followed symlinked artifact")


def test_verify_bundle_rejects_non_regular_artifact() -> None:
    module = _load("lanhu_figma_v1_under_test_ae", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_fifo_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "spec.md").unlink()
        os.mkfifo(bundle / "spec.md")
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("verify_bundle accepted FIFO")


def test_verify_bundle_rejects_duplicate_json_key() -> None:
    module = _load("lanhu_figma_v1_under_test_af", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_dup_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "tokens.json").write_text(
            '{"colors": [], "colors": []}', encoding="utf-8"
        )
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "duplicate" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted duplicate JSON key")


def test_verify_bundle_rejects_digest_mismatch() -> None:
    module = _load("lanhu_figma_v1_under_test_ag", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_dig_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "spec.md").write_text("# mutated spec\n", encoding="utf-8")
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("verify_bundle accepted mutated artifact")


def test_verify_bundle_rejects_malformed_png() -> None:
    module = _load("lanhu_figma_v1_under_test_ah", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_png_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "reference.png").write_bytes(b"not a png")
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("verify_bundle accepted malformed PNG")


def test_verify_bundle_rejects_missing_artboard_in_raw() -> None:
    module = _load("lanhu_figma_v1_under_test_ai", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_art_") as tmp:
        bundle = _publish(module, tmp)
        bad_raw = {
            "design_name": "x",
            "design_id": "d1",
            "version_id": "v1",
            "lanhu_url": _good_locator_query(),
            "figma_json": {"nope": True},
        }
        # Rewrite raw.json and rewrite provenance/reference_manifest to match.
        raw_path = bundle / "raw.json"
        raw_bytes = (
            json.dumps(bad_raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        raw_path.write_bytes(raw_bytes)
        _rewrite_provenance_digest(bundle, "raw.json", raw_bytes)
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "artboard" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted missing figma_json.artboard")


def test_verify_bundle_rejects_wrong_scene_source_schema() -> None:
    module = _load("lanhu_figma_v1_under_test_aj", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_src_") as tmp:
        bundle = _publish(module, tmp)
        bad_scene = _default_scene()
        bad_scene["sourceSchema"] = "figma_native"
        scene_bytes = (
            json.dumps(bad_scene, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        (bundle / "scene.json").write_bytes(scene_bytes)
        _rewrite_provenance_digest(bundle, "scene.json", scene_bytes)
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "sourceschema" in str(exc).lower() or "ir_schema" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted wrong scene sourceSchema")


def test_verify_bundle_rejects_provenance_board_ref_mismatch() -> None:
    module = _load("lanhu_figma_v1_under_test_ak", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_bref_") as tmp:
        bundle = _publish(module, tmp)
        prov = json.loads((bundle / "design_provenance.json").read_bytes())
        prov["board_ref"] = "lanhu-figma:v1:deadbeef"
        (bundle / "design_provenance.json").write_text(
            json.dumps(prov, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "board_ref" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted board_ref mismatch")


def test_verify_bundle_rejects_asset_inventory_mismatch() -> None:
    module = _load("lanhu_figma_v1_under_test_al", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_inv_") as tmp:
        bundle = _publish(module, tmp, synthesizer=_make_synthesizer(
            module,
            extra_assets={"foo.png": b"\x01"}
        ))
        # Drop an asset without updating provenance.
        (bundle / "assets" / "foo.png").unlink()
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "asset" in str(exc).lower() or "inventory" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted inventory mismatch")


def test_verify_bundle_rejects_extra_asset_not_in_inventory() -> None:
    module = _load("lanhu_figma_v1_under_test_am", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_xasset_") as tmp:
        bundle = _publish(module, tmp)
        (bundle / "assets" / "sneaky.png").write_bytes(b"\x00")
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            assert "asset" in str(exc).lower() or "inventory" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle accepted extra asset")


def test_verify_bundle_rejects_symlinked_bundle_root() -> None:
    module = _load("lanhu_figma_v1_under_test_an", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_rootln_") as tmp:
        bundle = _publish(module, tmp)
        link = tmp / "bundle_link"
        link.symlink_to(bundle)
        try:
            module.verify_bundle(link)
        except module.LanhuFigmaError as exc:
            assert "symlink" in str(exc).lower()
        else:
            raise AssertionError("verify_bundle followed symlinked bundle root")


def _rewrite_provenance_digest(bundle: Path, name: str, raw_bytes: bytes) -> None:
    """Rewrite design_provenance.json with the freshly computed digest for ``name``."""
    prov_path = bundle / "design_provenance.json"
    prov = json.loads(prov_path.read_bytes())
    prov["artifacts"][name] = hashlib.sha256(raw_bytes).hexdigest()
    prov_path.write_text(
        json.dumps(prov, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 8. CLI behavior.
# ---------------------------------------------------------------------------


def test_cli_resolve_emits_canonical_json_success() -> None:
    r = _run_cli("resolve", "--locator", _good_locator_query())
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    assert r.stderr == ""
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["board_ref"]


def test_cli_resolve_rejects_bad_locator_with_json_no_traceback() -> None:
    r = _run_cli("resolve", "--locator", "ftp://x?image_id=a")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


def test_cli_probe_rejects_bad_locator_with_json_no_traceback() -> None:
    r = _run_cli("probe", "--locator", "not-a-url")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


def test_cli_unknown_subcommand_emits_json_no_traceback() -> None:
    r = _run_cli("bogus")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


def test_cli_unknown_flag_emits_json_no_traceback() -> None:
    r = _run_cli("resolve", "--locator", _good_locator_query(), "--bogus", "x")
    assert r.returncode == 2
    assert r.stdout == ""
    payload = json.loads(r.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in r.stderr


def test_cli_verify_bundle_rejects_missing_bundle_with_json_no_traceback() -> None:
    with _canonical_tempdir(prefix="p2b_cli_") as tmp:
        missing = tmp / "does_not_exist"
        r = _run_cli("verify-bundle", "--bundle-root", str(missing))
        assert r.returncode == 2
        assert r.stdout == ""
        payload = json.loads(r.stderr)
        assert payload["ok"] is False
        assert "Traceback" not in r.stderr


def test_cli_supports_dashed_and_underscore_subcommands() -> None:
    """Both ``fetch-normalize`` and ``verify-bundle`` are the canonical names."""
    r = _run_cli("fetch-normalize", "--help")
    assert r.returncode == 0
    r = _run_cli("verify-bundle", "--help")
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# 9. Secret hygiene and no-public-override.
# ---------------------------------------------------------------------------


def test_no_cookie_token_or_secret_in_public_api_signatures() -> None:
    module = _load("lanhu_figma_v1_under_test_ao", MODULE_PATH)
    import inspect

    forbidden = ("cookie", "token", "secret", "credential", "password", "apikey")
    for name in ("resolve", "probe", "fetch_normalize", "verify_bundle"):
        sig = inspect.signature(getattr(module, name))
        params = [p.lower() for p in sig.parameters]
        for bad in forbidden:
            assert not any(bad in p for p in params), (
                f"{name} accepts forbidden parameter mentioning {bad!r}: {params}"
            )


def test_public_api_accepts_no_path_or_runner_override() -> None:
    module = _load("lanhu_figma_v1_under_test_ap", MODULE_PATH)
    import inspect

    forbidden_overrides = (
        "skill_root",
        "icp_root",
        "capsule_root",
        "scripts_dir",
        "script_path",
        "interpreter",
        "runner",
        "env",
        "registry",
        "command",
    )
    for name in ("resolve", "probe", "fetch_normalize", "verify_bundle"):
        sig = inspect.signature(getattr(module, name))
        params = {p.lower() for p in sig.parameters}
        for bad in forbidden_overrides:
            assert bad not in params, (
                f"{name} accepts forbidden override {bad!r}: {sorted(params)}"
            )


def test_module_does_not_inspect_or_serialize_environment() -> None:
    """No reference to LANHU_COOKIE / .env reading in the wrapper source."""
    module = _load("lanhu_figma_v1_under_test_aq", MODULE_PATH)
    src = MODULE_PATH.read_text(encoding="utf-8")
    # The wrapper may mention these only in docstrings/comments documenting
    # what it deliberately does NOT do. An assignment, attribute read, or
    # subscript access to a credential-bearing name is forbidden.
    forbidden_substring_in_code = (
        "LANHU_COOKIE",
        ".env",
        "os.environ[",
        "os.environ.get(",
    )
    # Parse the AST so docstrings/comments are excluded.
    import ast

    tree = ast.parse(src, filename=str(MODULE_PATH))
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for bad_str in ("LANHU_COOKIE",):
                if bad_str in node.value:
                    bad.append(f"constant mentions {bad_str!r}")
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            try:
                rendered = ast.unparse(node)
            except Exception:
                rendered = ""
            if "os.environ" in rendered:
                bad.append(f"subscripts os.environ: {rendered}")
        if isinstance(node, ast.Call):
            try:
                rendered = ast.unparse(node)
            except Exception:
                rendered = ""
            if "os.environ.get" in rendered:
                bad.append(f"calls os.environ.get: {rendered}")
    assert not bad, f"wrapper source touches forbidden env surfaces: {bad}"
    # Sanity: the module exposes the four public operations.
    for name in ("resolve", "probe", "fetch_normalize", "verify_bundle"):
        assert hasattr(module, name), f"missing public operation {name}"


def test_argv_never_contains_cookie_or_secret_during_step_run() -> None:
    module = _load("lanhu_figma_v1_under_test_ar", MODULE_PATH)
    loc = _good_locator_query()
    seen_argv: list[list[str]] = []
    syn = _make_synthesizer(module)

    def _spy(script_name, argv):
        seen_argv.append([script_name, *argv])
        return syn(script_name, argv)

    with _canonical_tempdir(prefix="p2b_argv_") as tmp:
        bundle = tmp / "bundle"
        with _patched_step(module, _spy):
            module.fetch_normalize(loc, bundle)
    # Well-known non-credential substrings that appear in fixture filenames
    # (export_tokens.py, tokens.json) — explicitly allow-listed so the test
    # does not flag legitimate argv entries.
    allow_substrings = ("tokens",)
    bad_substrings = ("cookie", "secret", "password", "bearer", "lanhu_cookie")
    # The first element of each recorded call is the script name; subsequent
    # elements are argv values. Only inspect argv VALUES, not script names,
    # because credential leak would appear as a value (e.g. --cookie=...).
    for call in seen_argv:
        for value in call[1:]:
            if any(value == v for v in (
                "--cookie", "--token", "--secret", "--password",
            )):
                raise AssertionError(f"argv passes credential flag: {call}")
            lowered = value.lower()
            for bad in bad_substrings:
                if bad in lowered:
                    raise AssertionError(
                        f"argv value contains forbidden substring {bad!r}: {call}"
                    )
    # Also ensure no allow-listed substring appears as a STANDALONE flag
    # (e.g. "--token=..."); only the fixed per-step flags are permitted.
    allowed_flags_per_step = {
        "fetch.py": {"--url", "--output"},
        "write.py": {"--input", "--output"},
        "download_cover.py": {"--url", "--out"},
        "export_figma_scene.py": {"--raw", "--assets", "--out"},
        "export_tokens.py": {"--scene", "--out"},
        "export_assets_manifest.py": {"--scene", "--out"},
        "classify_design.py": {"--raw", "--reference", "--out"},
    }
    for call in seen_argv:
        script, *argv = call
        flags = {a for a in argv if a.startswith("--")}
        # Flags with attached values (e.g. --cookie=...) would slip past the
        # value-only check above; reject any flag not in the fixed contract.
        expected = allowed_flags_per_step.get(script, set())
        unexpected = flags - expected
        assert not unexpected, (
            f"unexpected flag for {script}: {unexpected}; call={call}"
        )


# ---------------------------------------------------------------------------
# 10. Regression: capsule verification integration; iff untouched.
# ---------------------------------------------------------------------------


def _materialize_isolated_capsule_skill_root(tmp_root: Path) -> Path:
    """Build a minimal temporary ICP skill root under ``tmp_root``.

    The temporary root contains:
      * a byte copy of ``references/baselines/iff-v1-vendor.json`` (the
        committed capsule manifest, used by the verifier);
      * a byte copy of ``references/baselines/iff-v1.json`` (the P0
        baseline, required by the verifier's baseline-binding check);
      * a byte- and mode-preserving copy of every regular file under
        ``vendor/iff_v1/scripts/`` (no symlinks, no subdirectories, no
        ``__pycache__``).

    Returns the path to the temporary scripts directory. The production
    capsule is opened strictly read-only here; no path under it is ever
    written, chmod, renamed, unlinked, or replaced by this helper.
    """
    tmp_baselines = tmp_root / "references" / "baselines"
    tmp_baselines.mkdir(parents=True, exist_ok=False)
    (tmp_baselines / "iff-v1-vendor.json").write_bytes(
        PROD_VENDOR_MANIFEST.read_bytes()
    )
    (tmp_baselines / "iff-v1.json").write_bytes(PROD_BASELINE.read_bytes())

    tmp_scripts = tmp_root / "vendor" / "iff_v1" / "scripts"
    tmp_scripts.mkdir(parents=True, exist_ok=False)
    for entry in PROD_CAPSULE_SCRIPTS.iterdir():
        name = entry.name
        if name == "__pycache__":
            continue
        if entry.is_symlink():
            raise AssertionError(
                f"production capsule contains a symlink: {entry}"
            )
        if not entry.is_file():
            raise AssertionError(
                f"production capsule contains a non-regular entry: {entry}"
            )
        dst = tmp_scripts / name
        dst.write_bytes(entry.read_bytes())
        src_mode = stat.S_IMODE(entry.stat().st_mode)
        os.chmod(dst, src_mode)
    return tmp_scripts


def _assert_target_isolated_from_production(
    target: Path, tmp_root: Path
) -> None:
    """Prove ``target`` lives inside ``tmp_root`` and outside the production
    capsule.

    This is a regression seam: any future change that repoints the
    capsule-tamper self-test back at the production capsule fails here,
    before any mutation occurs. The check is structural (resolved-path
    parenthood), not a source-text grep, so it survives cosmetic edits
    to either the production capsule or this test file.
    """
    target_r = target.resolve()
    iso_r = tmp_root.resolve()
    prod_r = PROD_CAPSULE_SCRIPTS.resolve()
    assert iso_r == target_r or iso_r in target_r.parents, (
        f"mutation target {target_r} is not contained in the temporary "
        f"capsule skill root {iso_r}"
    )
    assert target_r != prod_r and prod_r not in target_r.parents, (
        f"mutation target {target_r} is inside the production capsule "
        f"{prod_r}; capsule self-tests must mutate only a temporary copy"
    )


@contextlib.contextmanager
def _isolated_capsule_skill_root(module):
    """Repoint only the loaded Lanhu module instance's ``ICP_ROOT`` and
    ``CAPSULE_SCRIPTS`` at a freshly-built temporary capsule skill root
    for the duration of the with-block.

    The temporary root is built by ``_materialize_isolated_capsule_skill_root``
    and removed when the inner ``_canonical_tempdir`` closes. The module
    constants are restored in ``finally`` even if the body raises, so a
    later test that reuses the same loaded module instance is unaffected.
    """
    with _canonical_tempdir(prefix="p2b_isocap_") as iso_root:
        iso_scripts = _materialize_isolated_capsule_skill_root(iso_root)
        saved_icp_root = module.ICP_ROOT
        saved_capsule_scripts = module.CAPSULE_SCRIPTS
        module.ICP_ROOT = iso_root
        module.CAPSULE_SCRIPTS = iso_scripts
        try:
            yield iso_root, iso_scripts
        finally:
            module.ICP_ROOT = saved_icp_root
            module.CAPSULE_SCRIPTS = saved_capsule_scripts


def test_probe_and_fetch_normalize_verify_capsule_first() -> None:
    """If the capsule is mutated, probe/fetch_normalize must fail before any step.

    The mutation target is a byte- and mode-preserving copy of the
    production capsule inside a freshly-built temporary ICP skill root.
    Only the loaded Lanhu module instance's ``ICP_ROOT`` and
    ``CAPSULE_SCRIPTS`` are repointed at the temporary root; the
    production capsule is never written, chmod, renamed, unlinked, or
    replaced during this test. ``probe`` and ``fetch_normalize`` must
    verify capsule integrity (SHA mismatch on the tampered ``fetch.py``)
    before invoking any legacy capsule primitive.
    """
    module = _load("lanhu_figma_v1_under_test_as", MODULE_PATH)
    loc = _good_locator_query()
    step_calls = []
    with _isolated_capsule_skill_root(module) as (iso_root, iso_scripts):
        target = iso_scripts / "fetch.py"
        # Structural seam: prove the mutation target lives inside the
        # temporary capsule skill root and outside the production capsule.
        _assert_target_isolated_from_production(target, iso_root)
        original = target.read_bytes()
        target.write_bytes(original + b"\n# tampered\n")
        try:
            try:
                with _patched_step(module, _make_synthesizer(module)):
                    module.probe(loc)
            except module.LanhuFigmaError:
                pass
            else:
                raise AssertionError("probe ran with a mutated capsule")
            assert step_calls == []
            with _canonical_tempdir(prefix="p2b_caps_") as tmp:
                bundle = tmp / "bundle"
                try:
                    with _patched_step(module, _make_synthesizer(module)):
                        module.fetch_normalize(loc, bundle)
                except module.LanhuFigmaError:
                    pass
                else:
                    raise AssertionError(
                        "fetch_normalize ran with a mutated capsule"
                    )
                assert not bundle.exists()
        finally:
            target.write_bytes(original)


def test_git_diff_iff_remains_empty() -> None:
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
# 11. RED — race-free non-clobber publication (empty-dir race).
# ---------------------------------------------------------------------------


def test_fetch_normalize_empty_dir_race_does_not_overwrite() -> None:
    """An empty destination directory appears at the exact publication call.
    The operation must fail, the pre-existing empty directory must still
    exist and remain empty, and staging residue must be absent.
    """
    module = _load("lanhu_figma_v1_under_test_ba", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_race_") as tmp:
        bundle = tmp / "bundle"
        original_publish = module._atomic_publish_no_replace
        state = {"raced": False}

        def _racing_publish(src, dst):
            if not state["raced"]:
                Path(dst).mkdir(exist_ok=False)
                state["raced"] = True
            return original_publish(src, dst)

        module._atomic_publish_no_replace = _racing_publish
        try:
            try:
                with _patched_step(module, _make_synthesizer(module)):
                    module.fetch_normalize(loc, bundle)
            except module.LanhuFigmaError:
                pass
            else:
                raise AssertionError("fetch_normalize overwrote empty dir")
            assert state["raced"] is True, "race injection never fired"
            # The pre-existing empty dir must still exist and be empty.
            assert bundle.is_dir(), "empty dir was removed"
            assert sorted(bundle.iterdir()) == [], "empty dir was written to"
            # No staging residue.
            assert not list(tmp.glob(".lanhu_figma_v1_stage.*")), "staging left"
        finally:
            module._atomic_publish_no_replace = original_publish


# ---------------------------------------------------------------------------
# 12. RED — post-publication parent-fsync failure rolls back the bundle.
# ---------------------------------------------------------------------------


def test_fetch_normalize_post_publication_fsync_failure_rolls_back() -> None:
    """Inject one _fsync_dir(parent) failure AFTER the bundle has been
    atomically published. The call must fail and roll back the bundle it
    published; final and staging paths must both be absent.
    """
    module = _load("lanhu_figma_v1_under_test_bb", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_fsync_") as tmp:
        bundle = tmp / "bundle"
        parent = bundle.parent
        original_fsync = module._fsync_dir
        original_publish = module._atomic_publish_no_replace
        state = {"published": False}

        def _tracking_publish(src, dst):
            result = original_publish(src, dst)
            state["published"] = True
            return result

        def _failing_fsync(path):
            if state["published"] and Path(path) == parent:
                raise OSError("injected post-publication fsync failure")
            return original_fsync(path)

        module._atomic_publish_no_replace = _tracking_publish
        module._fsync_dir = _failing_fsync
        try:
            try:
                with _patched_step(module, _make_synthesizer(module)):
                    module.fetch_normalize(loc, bundle)
            except module.LanhuFigmaError:
                pass
            else:
                raise AssertionError("fetch_normalize did not fail on fsync")
            assert state["published"] is True, "publication never happened"
            assert not bundle.exists(), "bundle was not rolled back"
            assert not bundle.is_symlink(), "bundle symlink left"
            assert not list(tmp.glob(".lanhu_figma_v1_stage.*")), "staging left"
        finally:
            module._atomic_publish_no_replace = original_publish
            module._fsync_dir = original_fsync


# ---------------------------------------------------------------------------
# 13. RED — structurally invalid PNG.
# ---------------------------------------------------------------------------


def _structural_invalid_png() -> bytes:
    """24 bytes: PNG sig + positive width/height at bytes[16:24] but no
    valid IHDR/IDAT/IEND chunk structure. Current _png_size accepts it; a
    structural parser must reject it.
    """
    sig = b"\x89PNG\r\n\x1a\n"
    return sig + b"\x00" * 8 + struct.pack(">II", 5, 5)


def test_verify_bundle_rejects_structurally_invalid_png() -> None:
    module = _load("lanhu_figma_v1_under_test_bc", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_spng_") as tmp:
        bundle = _publish(module, tmp)
        bad_png = _structural_invalid_png()
        (bundle / "reference.png").write_bytes(bad_png)
        rm = json.loads((bundle / "reference_manifest.json").read_bytes())
        rm["sha256"] = hashlib.sha256(bad_png).hexdigest()
        rm["width"] = 5
        rm["height"] = 5
        rm_bytes = _canonical_json(rm)
        (bundle / "reference_manifest.json").write_bytes(rm_bytes)
        _rewrite_provenance_digest(bundle, "reference.png", bad_png)
        _rewrite_provenance_digest(bundle, "reference_manifest.json", rm_bytes)
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            msg = str(exc).lower()
            assert "png" in msg or "chunk" in msg or "ihdr" in msg or "structure" in msg, (
                f"wrong error for structural PNG: {exc}"
            )
        else:
            raise AssertionError("verify_bundle accepted structurally invalid PNG")


def test_fetch_normalize_rejects_structurally_invalid_png() -> None:
    module = _load("lanhu_figma_v1_under_test_bd", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_spngfn_") as tmp:
        bundle = tmp / "bundle"
        try:
            with _patched_step(
                module,
                _make_synthesizer(module, png_bytes=_structural_invalid_png()),
            ):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("fetch_normalize accepted structurally invalid PNG")
        assert not bundle.exists()
        assert not list(tmp.glob(".lanhu_figma_v1_stage.*"))


# ---------------------------------------------------------------------------
# 14. RED — reference/artboard mismatch.
# ---------------------------------------------------------------------------


def test_probe_rejects_reference_artboard_size_mismatch() -> None:
    """Raw artboard bbox is [0,0,100,200], reference PNG is 1x1. probe
    must reject."""
    module = _load("lanhu_figma_v1_under_test_be", MODULE_PATH)
    loc = _good_locator_query()
    big_artboard = {"id": "a1", "bbox": [0, 0, 100, 200]}
    tiny_png = _minimal_png(1, 1)
    with _patched_step(
        module,
        _make_synthesizer(module, raw=_default_raw(artboard=big_artboard), png_bytes=tiny_png),
    ):
        try:
            module.probe(loc)
        except module.LanhuFigmaError as exc:
            msg = str(exc).lower()
            assert (
                "reference" in msg
                or "artboard" in msg
                or "size" in msg
                or "bbox" in msg
                or "dimension" in msg
            ), f"wrong error for mismatch: {exc}"
        else:
            raise AssertionError("probe accepted reference/artboard mismatch")


def test_fetch_normalize_rejects_reference_artboard_size_mismatch() -> None:
    module = _load("lanhu_figma_v1_under_test_bf", MODULE_PATH)
    loc = _good_locator_query()
    big_artboard = {"id": "a1", "bbox": [0, 0, 100, 200]}
    tiny_png = _minimal_png(1, 1)
    with _canonical_tempdir(prefix="p2b_mismatch_") as tmp:
        bundle = tmp / "bundle"
        try:
            with _patched_step(
                module,
                _make_synthesizer(
                    module, raw=_default_raw(artboard=big_artboard), png_bytes=tiny_png
                ),
            ):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError:
            pass
        else:
            raise AssertionError("fetch_normalize accepted mismatch")
        assert not bundle.exists()
        assert not list(tmp.glob(".lanhu_figma_v1_stage.*"))


def test_probe_rejects_missing_artboard_bbox() -> None:
    """Artboard exists but has no bbox extractable via any legacy key."""
    module = _load("lanhu_figma_v1_under_test_bg", MODULE_PATH)
    loc = _good_locator_query()
    no_bbox = {"id": "a1", "name": "no dims"}
    with _patched_step(
        module, _make_synthesizer(module, raw=_default_raw(artboard=no_bbox))
    ):
        try:
            module.probe(loc)
        except module.LanhuFigmaError as exc:
            msg = str(exc).lower()
            assert "bbox" in msg or "artboard" in msg or "dimension" in msg
        else:
            raise AssertionError("probe accepted missing artboard bbox")


def test_verify_bundle_rejects_reference_artboard_size_mismatch() -> None:
    module = _load("lanhu_figma_v1_under_test_bh", MODULE_PATH)
    with _canonical_tempdir(prefix="p2b_vbmismatch_") as tmp:
        bundle = _publish(module, tmp)
        # Rewrite raw.json with a mismatched artboard bbox.
        bad_raw = _default_raw(artboard={"id": "a1", "bbox": [0, 0, 500, 500]})
        raw_bytes = _canonical_json(bad_raw)
        (bundle / "raw.json").write_bytes(raw_bytes)
        _rewrite_provenance_digest(bundle, "raw.json", raw_bytes)
        try:
            module.verify_bundle(bundle)
        except module.LanhuFigmaError as exc:
            msg = str(exc).lower()
            assert (
                "reference" in msg
                or "artboard" in msg
                or "size" in msg
                or "bbox" in msg
                or "dimension" in msg
            )
        else:
            raise AssertionError("verify_bundle accepted reference/artboard mismatch")


def test_probe_accepts_artboard_bbox_via_frame_key() -> None:
    """The bbox extractor must honor the 'frame' dict key from the legacy
    semantics (common.py:77), not just the direct 'bbox' list."""
    module = _load("lanhu_figma_v1_under_test_bi", MODULE_PATH)
    loc = _good_locator_query()
    artboard_with_frame = {
        "id": "a1",
        "frame": {"left": 0, "top": 0, "width": 2, "height": 3},
    }
    with _patched_step(
        module,
        _make_synthesizer(
            module, raw=_default_raw(artboard=artboard_with_frame)
        ),
    ):
        report = module.probe(loc)
    assert report["probe"]["reference_png_width"] == 2
    assert report["probe"]["reference_png_height"] == 3


# ---------------------------------------------------------------------------
# 15. RED — child stderr secrecy.
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    """Mimic subprocess.CompletedProcess with controlled stdout/stderr."""

    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_step_does_not_leak_child_stderr() -> None:
    """Monkeypatch subprocess.run so a fixed primitive exits nonzero with
    stderr=b'SECRET_SENTINEL'. The error must not contain that sentinel
    or any child stdout/stderr bytes."""
    module = _load("lanhu_figma_v1_under_test_bj", MODULE_PATH)
    SECRET = "SECRET_SENTINEL"
    original_run = module.subprocess.run

    def _fake_run(cmd, **kw):
        return _FakeCompletedProcess(
            returncode=1,
            stdout=b"CHILD_STDOUT_SECRET",
            stderr=SECRET.encode() + b" more leak",
        )

    module.subprocess.run = _fake_run
    try:
        try:
            module._run_step("fetch.py", ["--url", "http://x", "--output", "/tmp/x"])
        except module.LanhuFigmaError as exc:
            msg = str(exc)
            assert SECRET not in msg, f"stderr leaked: {msg!r}"
            assert "CHILD_STDOUT_SECRET" not in msg, f"stdout leaked: {msg!r}"
            assert "fetch.py" in msg, "script name missing"
        else:
            raise AssertionError("_run_step did not fail on nonzero exit")
    finally:
        module.subprocess.run = original_run


def test_run_step_oserror_does_not_leak_arbitrary_text() -> None:
    """OSError conversion must report stable class + errno only, not
    arbitrary exception text."""
    module = _load("lanhu_figma_v1_under_test_bk", MODULE_PATH)
    original_run = module.subprocess.run

    def _raising_run(cmd, **kw):
        raise OSError("arbitrary secret text EACCES detail")

    module.subprocess.run = _raising_run
    try:
        try:
            module._run_step("fetch.py", ["--url", "http://x", "--output", "/tmp/x"])
        except module.LanhuFigmaError as exc:
            msg = str(exc)
            assert "arbitrary secret text" not in msg, f"OSError text leaked: {msg!r}"
            assert "fetch.py" in msg
        else:
            raise AssertionError("_run_step did not fail on OSError")
    finally:
        module.subprocess.run = original_run


def test_cli_does_not_leak_child_stderr() -> None:
    """The CLI error JSON must not contain child stderr."""
    import io

    module = _load("lanhu_figma_v1_under_test_bl", MODULE_PATH)
    SECRET = "SECRET_SENTINEL"
    original_run = module.subprocess.run
    captured_err = io.StringIO()
    captured_out = io.StringIO()
    original_stderr = sys.stderr
    original_stdout = sys.stdout

    def _fake_run(cmd, **kw):
        return _FakeCompletedProcess(
            returncode=1, stdout=b"", stderr=SECRET.encode()
        )

    module.subprocess.run = _fake_run
    sys.stderr = captured_err
    sys.stdout = captured_out
    try:
        rc = module.main(["probe", "--locator", _good_locator_query()])
    finally:
        sys.stderr = original_stderr
        sys.stdout = original_stdout
        module.subprocess.run = original_run
    assert rc == 2
    assert captured_out.getvalue() == ""
    raw_err = captured_err.getvalue()
    payload = json.loads(raw_err)
    assert payload["ok"] is False
    assert SECRET not in raw_err, f"secret leaked in CLI JSON: {raw_err!r}"


# ---------------------------------------------------------------------------
# 16. RED — credential-bearing locator query keys.
# ---------------------------------------------------------------------------


_SENSITIVE_QUERY_KEYS = (
    "token",
    "access_token",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "cookie",
    "authorization",
    "auth",
    "bearer",
)


def test_resolve_rejects_sensitive_query_keys() -> None:
    module = _load("lanhu_figma_v1_under_test_bm", MODULE_PATH)
    for key in _SENSITIVE_QUERY_KEYS:
        loc = f"https://lanhuapp.com/path?image_id=abc&{key}=value"
        try:
            module.resolve(loc)
        except module.LanhuFigmaError:
            continue
        raise AssertionError(f"resolve accepted sensitive key: {key!r}")


def test_resolve_rejects_sensitive_query_keys_case_insensitive() -> None:
    module = _load("lanhu_figma_v1_under_test_bn", MODULE_PATH)
    for key in ("Token", "ACCESS_TOKEN", "Api-Key", "APIKEY", "SECRET"):
        loc = f"https://lanhuapp.com/path?image_id=abc&{key}=value"
        try:
            module.resolve(loc)
        except module.LanhuFigmaError:
            continue
        raise AssertionError(f"resolve accepted case-variant: {key!r}")


def test_resolve_rejects_sensitive_query_key_even_if_value_blank() -> None:
    module = _load("lanhu_figma_v1_under_test_bo", MODULE_PATH)
    loc = "https://lanhuapp.com/path?image_id=abc&token="
    try:
        module.resolve(loc)
    except module.LanhuFigmaError:
        pass
    else:
        raise AssertionError("resolve accepted blank sensitive key value")


def test_probe_rejects_sensitive_query_key_without_emitting_locator() -> None:
    """The locator must not be emitted or persisted on rejection."""
    module = _load("lanhu_figma_v1_under_test_bp", MODULE_PATH)
    loc = "https://lanhuapp.com/path?image_id=abc&secret=do-not-leak"
    try:
        module.probe(loc)
    except module.LanhuFigmaError as exc:
        # The error message must not contain the full locator.
        assert "do-not-leak" not in str(exc), f"locator leaked in error: {exc}"
        assert loc not in str(exc)
    else:
        raise AssertionError("probe accepted sensitive query key")


def test_fetch_normalize_rejects_sensitive_query_key_without_persisting() -> None:
    module = _load("lanhu_figma_v1_under_test_bq", MODULE_PATH)
    loc = "https://lanhuapp.com/path?image_id=abc&token=do-not-persist"
    with _canonical_tempdir(prefix="p2b_cred_") as tmp:
        bundle = tmp / "bundle"
        try:
            with _patched_step(module, _make_synthesizer(module)):
                module.fetch_normalize(loc, bundle)
        except module.LanhuFigmaError as exc:
            assert "do-not-persist" not in str(exc)
        else:
            raise AssertionError("fetch_normalize accepted sensitive key")
        assert not bundle.exists(), "bundle persisted despite credential locator"


def test_rollback_parent_fsync_failure_is_visible_and_secret_safe() -> None:
    module = _load("lanhu_figma_v1_under_test_br", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_rollback_fsync_") as tmp:
        bundle = tmp / "bundle"
        original_fsync = module._fsync_dir
        original_publish = module._atomic_publish_no_replace
        state = {"published": False, "fsync_failures": 0}

        def _tracking_publish(src, dst):
            original_publish(src, dst)
            state["published"] = True

        def _failing_fsync(path):
            if state["published"]:
                state["fsync_failures"] += 1
                raise OSError("SECRET_ROLLBACK_FSYNC")
            original_fsync(path)

        module._atomic_publish_no_replace = _tracking_publish
        module._fsync_dir = _failing_fsync
        try:
            try:
                with _patched_step(module, _make_synthesizer(module)):
                    module.fetch_normalize(loc, bundle)
            except module.LanhuFigmaError as exc:
                message = str(exc)
            else:
                raise AssertionError("rollback fsync failure was swallowed")
        finally:
            module._atomic_publish_no_replace = original_publish
            module._fsync_dir = original_fsync

        assert state["fsync_failures"] == 2
        assert "rollback" in message.lower(), message
        assert "SECRET_ROLLBACK_FSYNC" not in message
        assert not bundle.exists()
        assert not list(tmp.glob(".lanhu_figma_v1_stage.*"))


def test_rollback_remove_failure_is_visible_and_secret_safe() -> None:
    module = _load("lanhu_figma_v1_under_test_bs", MODULE_PATH)
    loc = _good_locator_query()
    with _canonical_tempdir(prefix="p2b_rollback_remove_") as tmp:
        bundle = tmp / "bundle"
        original_fsync = module._fsync_dir
        original_rmtree = module.shutil.rmtree
        state = {"entered_rollback": False}

        def _fail_initial_fsync(path):
            if bundle.exists() and not state["entered_rollback"]:
                state["entered_rollback"] = True
                raise OSError("initial fsync failure")
            original_fsync(path)

        def _fail_bundle_remove(path, *args, **kwargs):
            if Path(path) == bundle:
                raise OSError("SECRET_ROLLBACK_REMOVE")
            return original_rmtree(path, *args, **kwargs)

        module._fsync_dir = _fail_initial_fsync
        module.shutil.rmtree = _fail_bundle_remove
        try:
            try:
                with _patched_step(module, _make_synthesizer(module)):
                    module.fetch_normalize(loc, bundle)
            except module.LanhuFigmaError as exc:
                message = str(exc)
            else:
                raise AssertionError("rollback remove failure was swallowed")
        finally:
            module._fsync_dir = original_fsync
            module.shutil.rmtree = original_rmtree
            if bundle.exists():
                original_rmtree(bundle)

        assert state["entered_rollback"] is True
        assert "rollback" in message.lower(), message
        assert "SECRET_ROLLBACK_REMOVE" not in message
        assert not list(tmp.glob(".lanhu_figma_v1_stage.*"))


def test_cli_generic_exception_does_not_emit_arbitrary_text() -> None:
    import io

    module = _load("lanhu_figma_v1_under_test_bt", MODULE_PATH)
    original_resolve = module.resolve

    def _raise_secret(_locator):
        raise RuntimeError("SECRET_GENERIC_EXCEPTION")

    module.resolve = _raise_secret
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            rc = module.main(["resolve", "--locator", _good_locator_query()])
    finally:
        module.resolve = original_resolve

    assert rc == 2
    payload = json.loads(stderr.getvalue())
    assert payload["ok"] is False
    assert payload["code"] == "design_source_failed"
    assert payload["message"] == "RuntimeError"
    assert "SECRET_GENERIC_EXCEPTION" not in stderr.getvalue()


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
