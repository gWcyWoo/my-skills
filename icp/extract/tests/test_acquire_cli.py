from __future__ import annotations

import base64
import gzip
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ICP_ROOT = Path(__file__).resolve().parents[2]
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_rgba_png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"".join(b"\x00" + (b"\x00\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(pixels))
        + png_chunk(b"IEND", b"")
    )


PNG_2X2 = make_rgba_png(2, 2)


class AcquireCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        isolated_skills = self.root / "isolated-skills"
        isolated_skills.mkdir()
        shutil.copytree(ICP_ROOT, isolated_skills / "icp")
        self.script = isolated_skills / "icp" / "extract" / "scripts" / "acquire.py"
        self.extract_script = isolated_skills / "icp" / "extract" / "scripts" / "extract.py"
        self.assertFalse((isolated_skills / "fd").exists())
        self.assertFalse((isolated_skills / "iff").exists())
        self.fixture_dir = self.root / "http-fixture"
        self.fixture_dir.mkdir()
        self.api_base = "https://fixture.invalid"
        self.url = (
            "https://lanhuapp.com/web/#/item/project/detailDetach?"
            "pid=project-1&image_id=image-1&fromEditor=true"
        )
        figma = {
            "artboard": {
                "id": "root:1",
                "type": "artboard",
                "name": "Checkout",
                "frame": {"x": 0, "y": 0, "width": 1, "height": 1},
                "layers": [
                    {
                        "id": "asset:1",
                        "type": "shapeLayer",
                        "name": "Logo",
                        "frame": {"x": 0, "y": 0, "width": 1, "height": 1},
                        "hasExportImage": True,
                        "image": {
                            "imageUrl": f"{self.api_base}/FigmaSlicePNGlogo.png",
                            "svgUrl": f"{self.api_base}/FigmaSliceSVGlogo.svg",
                        },
                    }
                ],
            }
        }
        (self.fixture_dir / "figma.json.gz").write_bytes(
            gzip.compress(json.dumps(figma).encode("utf-8"))
        )
        (self.fixture_dir / "cover.png").write_bytes(PNG_1X1)
        (self.fixture_dir / "logo.png").write_bytes(PNG_1X1)
        (self.fixture_dir / "logo.svg").write_bytes(
            b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        )
        self.write_fixture_manifest(svg_status=200)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_fixture_manifest(self, svg_status: int) -> None:
        manifest = {
            "schema": "icp.extract.http-fixture.v1",
            "responses": {
                "/api/project/image": {
                    "json": {
                        "code": "00000",
                        "result": {
                            "id": "design-1",
                            "name": "Checkout",
                            "url": f"{self.api_base}/cover.png",
                            "versions": [
                                {
                                    "id": "version-1",
                                    "json_url": f"{self.api_base}/figma.json",
                                    "url": f"{self.api_base}/cover.png",
                                }
                            ],
                        },
                    }
                },
                "/figma.json": {
                    "file": "figma.json.gz",
                    "content_encoding": "gzip",
                },
                "/cover.png": {"file": "cover.png"},
                "/FigmaSlicePNGlogo.png": {"file": "logo.png"},
                "/FigmaSliceSVGlogo.svg": {
                    "file": "logo.svg",
                    "status": svg_status,
                },
            },
        }
        (self.fixture_dir / "responses.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def run_acquire(self, output_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--url",
                self.url,
                "--output-dir",
                str(output_dir),
                "--cookie",
                "fixture-cookie",
                "--api-base",
                self.api_base,
                "--http-fixture",
                str(self.fixture_dir / "responses.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def run_prepare(
        self, project: Path, acquisition_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.extract_script),
                "prepare",
                "--project-root",
                str(project),
                "--acquisition-dir",
                str(acquisition_dir),
                "--design-url",
                self.url,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_acquire_is_self_contained_and_freezes_complete_design_materials(self) -> None:
        output_dir = self.root / "acquired"
        result = self.run_acquire(output_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["design_name"], "Checkout")
        self.assertEqual(summary["expected_asset_count"], 2)
        self.assertEqual(summary["downloaded_asset_count"], 2)

        acquisition = json.loads((output_dir / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual(acquisition["schema"], "icp.extract.lanhu-acquisition.v1")
        self.assertEqual(acquisition["identity"]["image_id"], "image-1")
        self.assertEqual(acquisition["identity"]["project_id"], "project-1")
        self.assertEqual(acquisition["identity"]["design_id"], "design-1")
        self.assertEqual(acquisition["identity"]["version_id"], "version-1")
        self.assertEqual(acquisition["reference"]["size"], {"width": 1, "height": 1})
        self.assertEqual(acquisition["artboard_size"], {"width": 1, "height": 1})
        self.assertEqual(acquisition["assets"]["expected_count"], 2)
        self.assertEqual(acquisition["assets"]["downloaded_count"], 2)
        self.assertEqual(acquisition["assets"]["hashed_count"], 2)
        self.assertTrue(acquisition["assets"]["complete"])
        self.assertEqual(len(acquisition["assets"]["files"]), 2)
        self.assertEqual((output_dir / "reference.png").read_bytes(), PNG_1X1)
        source = json.loads((output_dir / "design.json").read_text(encoding="utf-8"))
        self.assertEqual(source["lanhu_url"], self.url)
        self.assertEqual(source["design_id"], "design-1")

    def test_acquire_fails_atomically_when_any_expected_slice_fails(self) -> None:
        self.write_fixture_manifest(svg_status=503)
        output_dir = self.root / "partial-must-not-exist"
        result = self.run_acquire(output_dir)
        self.assertEqual(result.returncode, 2)
        self.assertIn("asset_download_failed", result.stderr)
        self.assertFalse(output_dir.exists())

    def test_acquire_accepts_an_exact_uniform_reference_export_scale(self) -> None:
        (self.fixture_dir / "cover.png").write_bytes(PNG_2X2)
        output_dir = self.root / "scaled-acquired"
        result = self.run_acquire(output_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        acquisition = json.loads((output_dir / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual(acquisition["reference"]["size"], {"width": 2, "height": 2})
        self.assertEqual(acquisition["reference"]["logical_scale"], "2")

    def test_acquire_rejects_a_truncated_reference_png(self) -> None:
        (self.fixture_dir / "cover.png").write_bytes(PNG_1X1[:24])
        output_dir = self.root / "truncated-reference"
        result = self.run_acquire(output_dir)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid_reference", result.stderr)
        self.assertFalse(output_dir.exists())

    def test_acquire_rejects_an_export_flag_without_any_asset_url(self) -> None:
        figma_path = self.fixture_dir / "figma.json.gz"
        figma = json.loads(gzip.decompress(figma_path.read_bytes()))
        figma["artboard"]["layers"][0]["image"] = {}
        figma_path.write_bytes(gzip.compress(json.dumps(figma).encode("utf-8")))
        output_dir = self.root / "missing-export-url"
        result = self.run_acquire(output_dir)
        self.assertEqual(result.returncode, 2)
        self.assertIn("asset_metadata_missing", result.stderr)
        self.assertFalse(output_dir.exists())

    def test_prepare_accepts_only_an_untampered_acquisition_contract(self) -> None:
        output_dir = self.root / "acquired"
        acquired = self.run_acquire(output_dir)
        self.assertEqual(acquired.returncode, 0, acquired.stderr)

        project = self.root / "project"
        project.mkdir()
        prepared = self.run_prepare(project, output_dir)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        stage = project / ".icp" / "extract" / "Checkout"
        manifest = json.loads((stage / "source-manifest.json").read_text(encoding="utf-8"))
        acquisition = json.loads((output_dir / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["acquisition_sha256"],
            __import__("hashlib").sha256(
                (output_dir / "acquisition.json").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(manifest["acquisition_identity"], acquisition["identity"])
        self.assertEqual(len(manifest["assets"]), 2)

        tampered_project = self.root / "tampered-project"
        tampered_project.mkdir()
        first_asset = next((output_dir / "assets").iterdir())
        first_asset.write_bytes(b"tampered")
        rejected = self.run_prepare(tampered_project, output_dir)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("acquisition_drift", rejected.stderr)
        self.assertFalse((tampered_project / ".icp").exists())

    def test_prepare_persists_verified_source_node_to_local_asset_relations(self) -> None:
        output_dir = self.root / "acquired"
        acquired = self.run_acquire(output_dir)
        self.assertEqual(acquired.returncode, 0, acquired.stderr)

        project = self.root / "project"
        project.mkdir()
        prepared = self.run_prepare(project, output_dir)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

        stage = project / ".icp" / "extract" / "Checkout"
        manifest = json.loads((stage / "source-manifest.json").read_text(encoding="utf-8"))
        asset_index_path = stage / "asset-index.json"
        asset_index = json.loads(asset_index_path.read_text(encoding="utf-8"))
        png_url = f"{self.api_base}/FigmaSlicePNGlogo.png"
        svg_url = f"{self.api_base}/FigmaSliceSVGlogo.svg"
        svg_raw = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        self.assertEqual(
            asset_index,
            {
                "schema": "icp.extract.asset-index.v1",
                "source_sha256": manifest["source_sha256"],
                "source_facts_sha256": manifest["source_facts_sha256"],
                "assets": [
                    {
                        "asset_id": f"sha256:{hashlib.sha256(png_url.encode()).hexdigest()}",
                        "remote_url": png_url,
                        "local_path": "source/assets/logo.png",
                        "format": "png",
                        "sha256": hashlib.sha256(PNG_1X1).hexdigest(),
                        "size": len(PNG_1X1),
                        "source_references": [
                            {
                                "source_node_id": "asset:1",
                                "source_field": "image.imageUrl",
                            }
                        ],
                    },
                    {
                        "asset_id": f"sha256:{hashlib.sha256(svg_url.encode()).hexdigest()}",
                        "remote_url": svg_url,
                        "local_path": "source/assets/logo.svg",
                        "format": "svg",
                        "sha256": hashlib.sha256(svg_raw).hexdigest(),
                        "size": len(svg_raw),
                        "source_references": [
                            {
                                "source_node_id": "asset:1",
                                "source_field": "image.svgUrl",
                            }
                        ],
                    },
                ],
            },
        )
        self.assertEqual(manifest["asset_index_file"], "asset-index.json")
        self.assertEqual(
            manifest["asset_index_sha256"],
            hashlib.sha256(asset_index_path.read_bytes()).hexdigest(),
        )

        asset_index["assets"][0]["source_references"][0]["source_node_id"] = "missing:1"
        asset_index_path.write_text(json.dumps(asset_index), encoding="utf-8")
        rejected = self.run_prepare(project, output_dir)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("source_drift", rejected.stderr)

    def test_prepare_persists_verified_design_to_reference_coordinate_mapping(self) -> None:
        (self.fixture_dir / "cover.png").write_bytes(PNG_2X2)
        output_dir = self.root / "scaled-acquired"
        acquired = self.run_acquire(output_dir)
        self.assertEqual(acquired.returncode, 0, acquired.stderr)

        project = self.root / "project"
        project.mkdir()
        prepared = self.run_prepare(project, output_dir)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

        stage = project / ".icp" / "extract" / "Checkout"
        manifest_path = stage / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["reference"],
            {
                "path": "source/reference.png",
                "sha256": hashlib.sha256(PNG_2X2).hexdigest(),
                "pixel_size": {"width": 2, "height": 2},
                "logical_artboard_size": {"width": 1, "height": 1},
                "logical_scale": "2",
            },
        )
        self.assertNotIn("reference_file", manifest)
        self.assertNotIn("reference_sha256", manifest)

        manifest["reference"]["logical_scale"] = "3"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rejected = self.run_prepare(project, output_dir)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("input_drift", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
