from __future__ import annotations

import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
import builtins
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract.py"
sys.path.insert(0, str(SCRIPT.parent))
from icp.extract.scripts import extract as EXTRACT


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


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_design() -> dict[str, object]:
    return {
        "design_name": "Checkout",
        "design_id": "design-1",
        "version_id": "version-1",
        "lanhu_url": "https://lanhu.example/design-1",
        "figma_json": {
            "artboard": {
                "id": "root:1",
                "type": "artboard",
                "name": "Checkout",
                "frame": {"x": 0, "y": 0, "width": 750, "height": 1624},
                "layers": [
                    {
                        "id": "text:1",
                        "type": "textLayer",
                        "name": "Title",
                        "frame": {"x": 32, "y": 80, "width": 240, "height": 48},
                        "text": "Emergency loan",
                    },
                    {
                        "id": "group:1",
                        "type": "groupLayer",
                        "name": "Offer card",
                        "frame": {"x": 24, "y": 160, "width": 702, "height": 320},
                        "layers": [
                            {
                                "id": "button:1",
                                "type": "shapeLayer",
                                "name": "Apply",
                                "frame": {
                                    "x": 48,
                                    "y": 384,
                                    "width": 654,
                                    "height": 72,
                                },
                                "realFrame": {
                                    "x": 48,
                                    "y": 384,
                                    "width": 654,
                                    "height": 72,
                                },
                                "rotation": 180,
                                "fills": [{"color": "#5B5CE2"}],
                            }
                        ],
                    },
                ],
            }
        },
    }


class ExtractCliTest(unittest.TestCase):
    def test_topology_projection_collects_reversed_and_sibling_edges_in_one_scan(self) -> None:
        semantic_draft = {
            "blocks": [
                {"block_id": "page", "parent_block_id": None},
                {"block_id": "offer", "parent_block_id": "page"},
                {"block_id": "secondary", "parent_block_id": "page"},
            ]
        }
        facts = {
            "nodes": {
                "root": {"id": "root", "parent_id": None, "child_ids": ["group"]},
                "group": {
                    "id": "group",
                    "parent_id": "root",
                    "child_ids": ["button", "badge"],
                },
                "button": {"id": "button", "parent_id": "group", "child_ids": []},
                "badge": {"id": "badge", "parent_id": "group", "child_ids": []},
            }
        }
        assignments = {
            "root": {"status": "mapped", "block_id": "page"},
            "group": {"status": "mapped", "block_id": "offer"},
            "button": {"status": "absorbed", "block_id": "page"},
            "badge": {"status": "mapped", "block_id": "secondary"},
        }

        projection = EXTRACT.build_source_block_topology_projection(
            semantic_draft,
            facts,
            ["root", "group", "button", "badge"],
            assignments,
        )

        self.assertFalse(projection["ok"])
        self.assertEqual(
            [item["code"] for item in projection["issues"]],
            [
                "source_edge_reverses_block_hierarchy",
                "source_edge_crosses_sibling_blocks",
            ],
        )
        self.assertEqual(
            [item["source_child_id"] for item in projection["issues"]],
            ["button", "badge"],
        )

    def test_topology_projection_collapses_non_rendering_source_containers(self) -> None:
        semantic_draft = {
            "blocks": [
                {"block_id": "page", "parent_block_id": None},
                {"block_id": "action", "parent_block_id": "page"},
            ]
        }
        facts = {
            "nodes": {
                "root": {"id": "root", "parent_id": None, "child_ids": ["wrapper"]},
                "wrapper": {
                    "id": "wrapper",
                    "parent_id": "root",
                    "child_ids": ["button"],
                },
                "button": {"id": "button", "parent_id": "wrapper", "child_ids": []},
            }
        }
        assignments = {
            "root": {"status": "mapped", "block_id": "page"},
            "wrapper": {"status": "non_rendering", "block_id": None},
            "button": {"status": "mapped", "block_id": "action"},
        }

        projection = EXTRACT.build_source_block_topology_projection(
            semantic_draft, facts, ["root", "wrapper", "button"], assignments
        )

        self.assertTrue(projection["ok"])
        self.assertEqual(
            projection["edges"],
            [
                {
                    "source_parent_id": "root",
                    "source_child_id": "button",
                    "collapsed_source_ids": ["wrapper"],
                    "parent_block_id": "page",
                    "child_block_id": "action",
                    "source_sibling_index": 0,
                    "relation": "descendant_block",
                }
            ],
        )

    def test_missing_pillow_is_reported_as_a_structured_extract_dependency_error(self) -> None:
        original_import = builtins.__import__

        def without_pillow(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("missing Pillow")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_pillow):
            with self.assertRaisesRegex(
                EXTRACT.ContractError, "Pillow is required"
            ):
                EXTRACT.require_pillow_image()

    def test_reference_crop_path_preserves_the_missing_pillow_error(self) -> None:
        facts = {
            "source_sha256": "a" * 64,
            "node_order": ["icon", "shape"],
            "nodes": {
                "icon": {
                    "payload": {
                        "type": "symbolInstance",
                        "componentName": "Icon",
                        "frame": {"left": 0, "top": 0, "width": 2, "height": 2},
                    },
                    "child_ids": ["shape"],
                },
                "shape": {"payload": {"type": "shapeLayer"}, "child_ids": []},
            },
        }
        missing = EXTRACT.ContractError("missing_dependency", "Pillow is required")

        with patch.object(EXTRACT, "require_pillow_image", side_effect=missing):
            with self.assertRaises(EXTRACT.ContractError) as raised:
                EXTRACT.build_reference_crop_assets(
                    facts,
                    b"reference",
                    {"logical_scale": "1", "sha256": "b" * 64},
                )

        self.assertEqual(raised.exception.code, "missing_dependency")

    def test_reference_crop_does_not_require_pillow_without_a_crop_candidate(self) -> None:
        facts = {
            "source_sha256": "a" * 64,
            "node_order": ["root"],
            "nodes": {
                "root": {
                    "payload": {"type": "artboard"},
                    "child_ids": [],
                }
            },
        }

        with patch.object(
            EXTRACT,
            "require_pillow_image",
            side_effect=AssertionError("Pillow must not be loaded"),
        ):
            assets, files = EXTRACT.build_reference_crop_assets(
                facts,
                b"not-needed",
                {"logical_scale": "1", "sha256": "b" * 64},
            )

        self.assertEqual((assets, files), ([], []))

    def test_reference_crop_verification_preserves_the_missing_pillow_error(self) -> None:
        missing = EXTRACT.ContractError("missing_dependency", "Pillow is required")

        with patch.object(EXTRACT, "require_pillow_image", side_effect=missing):
            with self.assertRaises(EXTRACT.ContractError) as raised:
                EXTRACT.reference_crop_pixel_sha(b"crop")

        self.assertEqual(raised.exception.code, "missing_dependency")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.root / "raw.json"
        self.reference = self.root / "reference.png"
        self.design_name = "Checkout"
        self.extract_dir = self.project / ".icp" / "extract" / self.design_name
        write_json(self.source, sample_design())
        self.reference.write_bytes(make_rgba_png(750, 1624))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def prepare_workspace(self) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--allow-loose-input",
            "--design-url",
            "https://lanhu.example/design-1",
        )

    def run_stage_cli(
        self, command: str, *args: str, design_name: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            command,
            "--project-root",
            str(self.project),
            "--design-name",
            design_name or self.design_name,
            *args,
        )

    def prepare_single_block_reverse_review(self) -> dict:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "loan_checkout",
                    "role_basis": "interpreted",
                    "role_evidence": ["The current draft treats the source as one checkout task."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Light page with one offer surface.",
                        "border": "The source contains a rounded offer boundary.",
                        "spacing": "The content follows a vertical task flow.",
                    },
                    "content_summary": "Heading, offer, and action.",
                    "composition": "The current draft collapses every source node into one page Block.",
                    "relations": [],
                }
            ],
        }
        draft_path = self.root / "reverse-audit-draft.json"
        write_json(draft_path, draft)
        drafted = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        state = read_json(self.extract_dir / "state.json")
        assignments = []
        for node_id, basis in (
            ("root:1", "frame"),
            ("text:1", "frame"),
            ("group:1", "frame"),
            ("button:1", "real_frame"),
        ):
            assignments.append(
                {
                    "source_node_id": node_id,
                    "status": "mapped" if node_id == "root:1" else "absorbed",
                    "block_id": "page",
                    "geometry_basis": basis,
                    "content_role": (
                        "static_copy" if node_id == "text:1" else "static_visual"
                    ),
                    "rationale": "The current draft assigns this exact node to the page Block.",
                }
            )
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": assignments,
        }
        bindings_path = self.root / "reverse-audit-bindings.json"
        write_json(bindings_path, bindings)
        bound = self.run_stage_cli(
            "record-bindings", "--bindings", str(bindings_path)
        )
        self.assertEqual(bound.returncode, 0, bound.stdout + bound.stderr)
        return read_json(self.extract_dir / "semantic-review.input.json")

    def fill_passing_semantic_review(self, review: dict) -> None:
        review["decision"] = "pass"
        for item in review["block_reviews"]:
            item["role_correct"] = True
            item["hierarchy_correct"] = True
            item["appearance_interpretation_correct"] = True
            item["content_grouping_correct"] = True
            item["source_binding_correct"] = True
            item["evidence"] = [
                "The rendered reference and current Block boundary were compared directly."
            ]
            item["issues"] = []
        for item in review["source_node_reviews"]:
            item["semantic_assignment_correct"] = True
            item["content_role_correct"] = True
            item["independent_grouping_correct"] = True
            item["parent_child_relation_correct"] = True
            item["evidence"] = [
                "The exact JSON node, current Block, parent source node, and child source nodes were checked together."
            ]
            item["issues"] = []
        for item in review["source_group_reviews"]:
            item["semantic_relation"] = (
                "matches_block"
                if len(item["subtree_block_ids"]) == 1
                else "contains_blocks"
            )
            item["visual_semantics_correct"] = True
            item["json_grouping_reconciled"] = True
            item["visual_evidence"] = [
                "The rendered group boundary was inspected before consulting source JSON."
            ]
            item["json_evidence"] = [
                "The complete source group, parent, children, and subtree Block projection were checked."
            ]
            item["rationale"] = [
                "The visual Block hypothesis and JSON grouping evidence are explicitly reconciled."
            ]
            item["issues"] = []
        cross = review["cross_block_review"]
        cross["relations_correct"] = True
        cross["reading_order_correct"] = True
        cross["no_semantic_omissions"] = True
        cross["non_rendering_classifications_correct"] = True
        cross["evidence"] = [
            "The complete source-node order and Block graph were checked for omissions."
        ]
        cross["issues"] = []

    def test_bindings_freeze_a_reviewed_content_role_for_every_source_node(self) -> None:
        review = self.prepare_single_block_reverse_review()

        roles = {
            item["source_node"]["id"]: item["assignment"]["content_role"]
            for item in review["reverse_binding_evidence"]["nodes"]
        }
        self.assertEqual(
            roles,
            {
                "root:1": "static_visual",
                "text:1": "static_copy",
                "group:1": "static_visual",
                "button:1": "static_visual",
            },
        )
        self.assertTrue(
            all(
                item["content_role_correct"] is False
                for item in review["source_node_reviews"]
            )
        )

        self.fill_passing_semantic_review(review)
        review_path = self.root / "content-role-review.json"
        write_json(review_path, review)
        recorded = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        stage_result = read_json(self.extract_dir / "stage-result.json")
        self.assertTrue(stage_result["content_roles_reviewed"])

    def test_reverse_review_requires_visual_json_reconciliation_for_every_source_group(self) -> None:
        review = self.prepare_single_block_reverse_review()

        self.assertEqual(
            [item["source_node_id"] for item in review["source_group_reviews"]],
            ["root:1", "group:1"],
        )
        self.assertEqual(
            review["source_group_reviews"][0]["subtree_block_ids"], ["page"]
        )
        self.assertEqual(
            review["source_group_reviews"][1]["subtree_block_ids"], ["page"]
        )
        self.assertTrue(
            all(
                item["semantic_relation"] == "unreviewed"
                and item["visual_semantics_correct"] is False
                and item["json_grouping_reconciled"] is False
                for item in review["source_group_reviews"]
            )
        )

        self.fill_passing_semantic_review(review)
        target = review["source_group_reviews"][1]
        target["visual_semantics_correct"] = False
        target["json_grouping_reconciled"] = False
        target["issues"] = [
            "The JSON Offer card group is independent evidence that the one-Block visual hypothesis must be revised."
        ]
        review["decision"] = "revise"
        review_path = self.root / "source-group-reconciliation-review.json"
        write_json(review_path, review)

        revised = self.run_stage_cli("record-review", "--review", str(review_path))

        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        repair = read_json(self.extract_dir / "semantic-repair.json")
        self.assertEqual(
            repair["source_group_issues"]["group:1"], target["issues"]
        )
        self.assertEqual(
            repair["source_group_repair_packets"]["group:1"][
                "source_and_current_block"
            ]["source_node"]["payload"]["name"],
            "Offer card",
        )

    def test_prepare_creates_lossless_extract_workspace_and_fails_on_drift(self) -> None:
        result = self.prepare_workspace()
        self.assertEqual(result.returncode, 0, result.stderr)

        extract_dir = self.extract_dir
        self.assertEqual(
            sorted(path.name for path in (self.project / ".icp").iterdir()),
            ["extract"],
        )
        self.assertEqual(
            sorted(path.name for path in (self.project / ".icp" / "extract").iterdir()),
            ["Checkout"],
        )
        self.assertEqual(
            (extract_dir / "source" / "design.json").read_bytes(),
            self.source.read_bytes(),
        )
        self.assertEqual(
            (extract_dir / "source" / "reference.png").read_bytes(),
            self.reference.read_bytes(),
        )

        manifest = read_json(extract_dir / "source-manifest.json")
        self.assertEqual(manifest["schema"], "icp.extract.source-manifest.v1")
        self.assertEqual(manifest["design_id"], "design-1")
        self.assertEqual(manifest["version_id"], "version-1")
        self.assertEqual(manifest["root_node_id"], "root:1")
        self.assertEqual(manifest["source_node_count"], 4)
        self.assertEqual(
            manifest["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest()
        )
        self.assertEqual(
            manifest["reference"]["sha256"],
            hashlib.sha256(self.reference.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["reference"]["pixel_size"], {"width": 750, "height": 1624})
        self.assertEqual(
            manifest["reference"]["logical_artboard_size"],
            {"width": 750, "height": 1624},
        )
        self.assertEqual(manifest["reference"]["logical_scale"], "1")

        facts = read_json(extract_dir / "source-facts.json")
        self.assertEqual(facts["schema"], "icp.extract.source-facts.v1")
        self.assertEqual(facts["node_order"], ["root:1", "text:1", "group:1", "button:1"])
        self.assertEqual(facts["nodes"]["button:1"]["parent_id"], "group:1")
        self.assertEqual(facts["nodes"]["group:1"]["child_ids"], ["button:1"])
        self.assertEqual(
            facts["nodes"]["button:1"]["payload"]["fills"],
            [{"color": "#5B5CE2"}],
        )
        self.assertNotIn("layers", facts["nodes"]["group:1"]["payload"])
        self.assertEqual(read_json(extract_dir / "state.json")["state"], "awaiting_semantic_draft")

        resumed = self.prepare_workspace()
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertTrue(json.loads(resumed.stdout)["resumed"])

        changed = sample_design()
        changed["version_id"] = "version-2"
        write_json(self.source, changed)
        drifted = self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--allow-loose-input",
            "--design-url",
            "https://lanhu.example/design-1",
        )
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("input_drift", drifted.stderr)

    def test_prepare_freezes_optional_assets_with_exact_hashes(self) -> None:
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "offer.svg").write_text("<svg>offer</svg>", encoding="utf-8")
        (assets / "apply.png").write_bytes(b"apply-image")
        source = sample_design()
        button = source["figma_json"]["artboard"]["layers"][1]["layers"][0]
        button["hasExportImage"] = True
        button["image"] = {
            "imageUrl": "https://assets.invalid/FigmaSlicePNGapply.png",
            "svgUrl": "https://assets.invalid/FigmaSliceSVGoffer.svg",
        }
        write_json(self.source, source)
        result = self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--assets-dir",
            str(assets),
            "--allow-loose-input",
            "--design-url",
            "https://lanhu.example/design-1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        extract_dir = self.extract_dir
        manifest = read_json(extract_dir / "source-manifest.json")
        self.assertEqual(
            manifest["assets"],
            [
                {
                    "path": "apply.png",
                    "sha256": hashlib.sha256(b"apply-image").hexdigest(),
                    "size": len(b"apply-image"),
                },
                {
                    "path": "offer.svg",
                    "sha256": hashlib.sha256(b"<svg>offer</svg>").hexdigest(),
                    "size": len(b"<svg>offer</svg>"),
                },
            ],
        )
        self.assertEqual(
            (extract_dir / "source" / "assets" / "apply.png").read_bytes(),
            b"apply-image",
        )

        (assets / "offer.svg").write_text("<svg>changed</svg>", encoding="utf-8")
        drifted = self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--assets-dir",
            str(assets),
            "--allow-loose-input",
            "--design-url",
            "https://lanhu.example/design-1",
        )
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("input_drift", drifted.stderr)

    def test_prepare_derives_exact_reference_crop_for_unexported_icon_component(self) -> None:
        source = {
            "design_name": "登录-验证码",
            "design_id": "design-otp",
            "version_id": "version-otp",
            "lanhu_url": "https://lanhu.example/design-1",
            "figma_json": {
                "artboard": {
                    "id": "root:otp",
                    "type": "artboard",
                    "name": "登录-验证码",
                    "frame": {"left": 0, "top": 0, "width": 390, "height": 852},
                    "layers": [
                        {
                            "id": "2272:1184",
                            "type": "symbolInstence",
                            "name": "Repayment-Login",
                            "componentName": "Repayment-Login",
                            "realFrame": {
                                "left": 286.25,
                                "top": 744.25,
                                "width": 47.5,
                                "height": 47.5,
                            },
                            "hasExportImage": False,
                            "hasExportDDSImage": False,
                            "layers": [
                                {
                                    "id": "I2272:1184;2272:1165",
                                    "type": "artboard",
                                    "name": "Frame",
                                    "frame": {
                                        "left": 298,
                                        "top": 756,
                                        "width": 24,
                                        "height": 24,
                                    },
                                    "layers": [
                                        {
                                            "id": "I2272:1184;2272:1166",
                                            "type": "shapeLayer",
                                            "name": "Vector",
                                            "frame": {
                                                "left": 298.00030517578125,
                                                "top": 759.510498046875,
                                                "width": 24,
                                                "height": 16.97864532470703,
                                            },
                                            "hasExportImage": False,
                                            "hasExportDDSImage": False,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
        write_json(self.source, source)
        reference = Image.new("RGBA", (780, 1704), (245, 250, 247, 255))
        draw = ImageDraw.Draw(reference)
        draw.rounded_rectangle((572, 1488, 667, 1583), radius=24, fill=(243, 247, 245, 255))
        draw.rounded_rectangle((596, 1512, 643, 1559), radius=5, fill=(43, 109, 69, 255))
        draw.rectangle((596, 1524, 643, 1529), fill=(255, 255, 255, 255))
        draw.polygon(((610, 1543), (600, 1535), (610, 1527)), fill=(255, 255, 255, 255))
        reference.save(self.reference, format="PNG")

        result = self.prepare_workspace()

        self.assertEqual(result.returncode, 0, result.stderr)
        stage = self.project / ".icp" / "extract" / "登录-验证码"
        manifest = read_json(stage / "source-manifest.json")
        self.assertEqual(len(manifest["derived_assets"]), 1)
        asset = read_json(stage / "asset-index.json")["assets"][0]
        self.assertEqual(asset["origin"], "reference_crop")
        self.assertEqual(asset["source_references"], [
            {"source_node_id": "2272:1184", "source_field": "reference.crop"}
        ])
        self.assertEqual(asset["reference_crop"], {
            "reference_sha256": manifest["reference"]["sha256"],
            "logical_rect": {"left": 286.25, "top": 744.25, "width": 47.5, "height": 47.5},
            "pixel_rect": {"left": 572, "top": 1488, "width": 96, "height": 96},
            "logical_scale": "2",
            "rounding": "outward",
        })
        crop_path = stage / asset["local_path"]
        with Image.open(crop_path) as crop:
            self.assertEqual(crop.size, (96, 96))
            self.assertEqual(crop.convert("RGBA").getpixel((48, 38)), (255, 255, 255, 255))

        resumed = self.prepare_workspace()
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

        original_builder = EXTRACT.build_reference_crop_assets

        def differently_encoded(*args, **kwargs):
            assets, files = original_builder(*args, **kwargs)
            rewritten_assets = json.loads(json.dumps(assets))
            rewritten_files = []
            for local_path, raw in files:
                image = Image.open(io.BytesIO(raw)).convert("RGBA")
                encoded = io.BytesIO()
                image.save(encoded, format="PNG", compress_level=0)
                alternative = encoded.getvalue()
                record = next(
                    item for item in rewritten_assets if item["local_path"] == local_path
                )
                record["sha256"] = hashlib.sha256(alternative).hexdigest()
                record["size"] = len(alternative)
                rewritten_files.append((local_path, alternative))
            return rewritten_assets, rewritten_files

        with patch.object(
            EXTRACT,
            "build_reference_crop_assets",
            side_effect=differently_encoded,
        ):
            EXTRACT.verify_frozen_sources(
                stage.resolve(), read_json(stage / "state.json")
            )

        crop_path.write_bytes(b"tampered")
        rejected = self.prepare_workspace()
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("source_drift", rejected.stderr)

    def test_reference_crop_candidate_outside_the_reference_fails_visibly(self) -> None:
        facts = {
            "source_sha256": "a" * 64,
            "node_order": ["icon", "shape"],
            "nodes": {
                "icon": {
                    "payload": {
                        "type": "symbolInstance",
                        "componentName": "Icon",
                        "frame": {"left": 9, "top": 9, "width": 2, "height": 2},
                    },
                    "child_ids": ["shape"],
                },
                "shape": {
                    "payload": {"type": "shapeLayer"},
                    "child_ids": [],
                },
            },
        }
        reference = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        buffer = io.BytesIO()
        reference.save(buffer, format="PNG")
        raw = buffer.getvalue()

        with self.assertRaisesRegex(
            EXTRACT.ContractError, "outside the frozen reference"
        ):
            EXTRACT.build_reference_crop_assets(
                facts,
                raw,
                {"logical_scale": "1", "sha256": hashlib.sha256(raw).hexdigest()},
            )

    def test_reference_crop_accepts_the_fraction_scale_frozen_by_lanhu(self) -> None:
        self.assertEqual(
            EXTRACT._scaled_pixel_rect(
                {"left": 1, "top": 2, "width": 3, "height": 4}, "3/2"
            ),
            {"left": 1, "top": 3, "width": 5, "height": 6},
        )

    def test_prepare_rejects_a_design_url_that_does_not_match_the_source(self) -> None:
        result = self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--allow-loose-input",
            "--design-url",
            "https://lanhu.example/different-design",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("design_url_mismatch", result.stderr)
        self.assertFalse((self.project / ".icp").exists())

    def test_prepare_rejects_loose_inputs_without_the_hidden_test_flag(self) -> None:
        result = self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(self.source),
            "--reference-image",
            str(self.reference),
            "--design-url",
            "https://lanhu.example/design-1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsafe_loose_input", result.stderr)
        self.assertFalse((self.project / ".icp").exists())

    def test_record_draft_accepts_semantics_but_rejects_source_facts(self) -> None:
        prepared = self.prepare_workspace()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        extract_dir = self.extract_dir
        manifest_sha = read_json(extract_dir / "state.json")["source_manifest_sha256"]
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": manifest_sha,
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The full rendered artboard is one page."],
                    "parent_block_id": None,
                    "child_block_ids": ["offer"],
                    "appearance": {
                        "background": "Light page surface.",
                        "border": "No page-level border is visible.",
                        "spacing": "Content follows a vertical rhythm.",
                    },
                    "content_summary": "Loan checkout content.",
                    "composition": "A title precedes one primary offer card.",
                    "relations": [],
                },
                {
                    "block_id": "offer",
                    "name": "Primary offer",
                    "role": "primary_offer",
                    "role_basis": "interpreted",
                    "role_evidence": ["It groups the offer and its primary action."],
                    "parent_block_id": "page",
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Contrasting card surface.",
                        "border": "Rounded visual boundary.",
                        "spacing": "Internal content and action are separated.",
                    },
                    "content_summary": "Offer details and apply action.",
                    "composition": "The action is subordinate to the offer.",
                    "relations": [
                        {
                            "type": "follows",
                            "target_block_id": "page",
                            "evidence": "The offer sits below the page heading.",
                        }
                    ],
                },
            ],
        }
        draft_path = self.root / "semantic-draft.json"
        write_json(draft_path, draft)

        recorded = self.run_stage_cli(
            "record-draft",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(read_json(extract_dir / "semantic-draft.json"), draft)
        state = read_json(extract_dir / "state.json")
        self.assertEqual(state["state"], "awaiting_bindings")
        self.assertEqual(state["revision"], 1)
        self.assertTrue((extract_dir / "revisions" / "semantic-draft.0001.json").is_file())
        binding_template = read_json(extract_dir / "bindings.input.json")
        self.assertEqual(
            [item["source_node_id"] for item in binding_template["assignments"]],
            ["root:1", "text:1", "group:1", "button:1"],
        )
        self.assertTrue(
            all(item["status"] == "unresolved" for item in binding_template["assignments"])
        )
        self.assertTrue(
            all(
                item["content_role"] == "unresolved"
                for item in binding_template["assignments"]
            )
        )
        self.assertEqual(binding_template["semantic_draft_sha256"], state["semantic_draft_sha256"])

        forbidden = json.loads(json.dumps(draft))
        forbidden["blocks"][1]["appearance"]["spacing_px"] = 24
        write_json(draft_path, forbidden)
        rejected = self.run_stage_cli(
            "record-draft",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("source_fact_in_semantic_draft", rejected.stderr)

    def test_record_draft_recovers_when_a_crash_left_only_the_canonical_draft(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The artboard is the page."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {"background": "Light surface.", "border": "No outer border.", "spacing": "Single flow."},
                    "content_summary": "Page content.",
                    "composition": "One semantic root.",
                    "relations": [],
                }
            ],
        }
        (self.extract_dir / "semantic-draft.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        draft_path = self.root / "crash-window-draft.json"
        write_json(draft_path, draft)
        resumed = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(read_json(self.extract_dir / "state.json")["state"], "awaiting_bindings")
        self.assertTrue((self.extract_dir / "bindings.input.json").is_file())

        state = read_json(self.extract_dir / "state.json")
        unresolved = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [],
        }
        unresolved_path = self.root / "crash-window-unresolved.json"
        write_json(unresolved_path, unresolved)
        repaired = self.run_stage_cli(
            "record-bindings", "--bindings", str(unresolved_path)
        )
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(read_json(self.extract_dir / "state.json")["state"], "repair_required")

        revised_draft = json.loads(json.dumps(draft))
        revised_draft["blocks"][0]["name"] = "Revised page"
        revised_raw = (
            json.dumps(revised_draft, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        (self.extract_dir / "semantic-draft.json").write_bytes(revised_raw)
        revised_path = self.root / "repair-cycle-crash-draft.json"
        write_json(revised_path, revised_draft)
        recovered = self.run_stage_cli("record-draft", "--draft", str(revised_path))
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        recovered_state = read_json(self.extract_dir / "state.json")
        self.assertEqual(recovered_state["state"], "awaiting_bindings")
        self.assertEqual(
            recovered_state["semantic_draft_sha256"], hashlib.sha256(revised_raw).hexdigest()
        )

    def test_expand_bindings_requires_an_exact_explicit_source_partition(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The artboard is the page."],
                    "parent_block_id": None,
                    "child_block_ids": ["offer"],
                    "appearance": {"background": "Light surface.", "border": "No outer border.", "spacing": "Vertical flow."},
                    "content_summary": "Page content.",
                    "composition": "Page contains one offer.",
                    "relations": [],
                },
                {
                    "block_id": "offer",
                    "name": "Offer",
                    "role": "offer",
                    "role_basis": "interpreted",
                    "role_evidence": ["The group contains the offer action."],
                    "parent_block_id": "page",
                    "child_block_ids": [],
                    "appearance": {"background": "Card surface.", "border": "Card boundary.", "spacing": "Grouped content."},
                    "content_summary": "Offer content.",
                    "composition": "One grouped offer.",
                    "relations": [],
                },
            ],
        }
        draft_path = self.root / "partition-draft.json"
        write_json(draft_path, draft)
        recorded = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        state = read_json(self.extract_dir / "state.json")
        plan = {
            "schema": "icp.extract.binding-plan.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "rules": [
                {
                    "source_node_ids": ["root:1", "text:1"],
                    "source_subtree_roots": [],
                    "status": "absorbed",
                    "block_id": "page",
                    "content_role": "static_visual",
                    "rationale": "These nodes directly form the page context.",
                },
                {
                    "source_node_ids": [],
                    "source_subtree_roots": ["group:1"],
                    "status": "mapped",
                    "block_id": "offer",
                    "content_role": "static_visual",
                    "rationale": "The complete group subtree forms the offer.",
                },
            ],
        }
        plan_path = self.root / "binding-plan.json"
        write_json(plan_path, plan)
        expanded = self.run_stage_cli("expand-bindings", "--plan", str(plan_path))
        self.assertEqual(expanded.returncode, 0, expanded.stderr)
        bindings = read_json(self.extract_dir / "bindings.input.json")
        self.assertEqual(
            [item["source_node_id"] for item in bindings["assignments"]],
            ["root:1", "text:1", "group:1", "button:1"],
        )
        self.assertEqual(bindings["assignments"][-1]["geometry_basis"], "real_frame")

        plan["rules"][0]["source_node_ids"].append("group:1")
        write_json(plan_path, plan)
        overlap = self.run_stage_cli("expand-bindings", "--plan", str(plan_path))
        self.assertEqual(overlap.returncode, 2)
        self.assertIn("binding_plan_overlap", overlap.stderr)

    def test_expand_bindings_routes_explicit_unresolved_subtree_to_repair(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The artboard is the page."],
                    "parent_block_id": None,
                    "child_block_ids": ["offer"],
                    "appearance": {
                        "background": "Light surface.",
                        "border": "No outer border.",
                        "spacing": "Vertical flow.",
                    },
                    "content_summary": "Page content.",
                    "composition": "Page contains one offer.",
                    "relations": [],
                },
                {
                    "block_id": "offer",
                    "name": "Offer",
                    "role": "offer",
                    "role_basis": "interpreted",
                    "role_evidence": ["The group contains the offer action."],
                    "parent_block_id": "page",
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Card surface.",
                        "border": "Card boundary.",
                        "spacing": "Grouped content.",
                    },
                    "content_summary": "Offer content.",
                    "composition": "One grouped offer.",
                    "relations": [],
                },
            ],
        }
        draft_path = self.root / "unresolved-plan-draft.json"
        write_json(draft_path, draft)
        recorded = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        state = read_json(self.extract_dir / "state.json")
        rationale = "The cropped reference does not show this source subtree."
        plan = {
            "schema": "icp.extract.binding-plan.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "rules": [
                {
                    "source_node_ids": ["root:1", "text:1"],
                    "source_subtree_roots": [],
                    "status": "absorbed",
                    "block_id": "page",
                    "content_role": "static_visual",
                    "rationale": "These nodes form the visible page context.",
                },
                {
                    "source_node_ids": ["group:1"],
                    "source_subtree_roots": [],
                    "status": "mapped",
                    "block_id": "offer",
                    "content_role": "static_visual",
                    "rationale": "The visible group forms the offer.",
                },
                {
                    "source_node_ids": [],
                    "source_subtree_roots": ["button:1"],
                    "status": "unresolved",
                    "block_id": None,
                    "content_role": "unresolved",
                    "rationale": rationale,
                },
            ],
        }
        plan_path = self.root / "unresolved-binding-plan.json"
        write_json(plan_path, plan)

        expanded = self.run_stage_cli("expand-bindings", "--plan", str(plan_path))
        self.assertEqual(expanded.returncode, 0, expanded.stderr)
        bindings = read_json(self.extract_dir / "bindings.input.json")
        unresolved = bindings["assignments"][-1]
        self.assertEqual(
            unresolved,
            {
                "source_node_id": "button:1",
                "status": "unresolved",
                "block_id": None,
                "geometry_basis": "not_applicable",
                "content_role": "unresolved",
                "rationale": rationale,
            },
        )

        recorded_bindings = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(self.extract_dir / "bindings.input.json"),
        )
        self.assertEqual(recorded_bindings.returncode, 0, recorded_bindings.stderr)
        coverage = read_json(self.extract_dir / "coverage.json")
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["partitions"]["unresolved"], ["button:1"])
        self.assertEqual(list(coverage["repair_packets"]), ["button:1"])
        packet = read_json(self.extract_dir / coverage["repair_packets"]["button:1"])
        self.assertEqual(packet["reason"], rationale)
        self.assertEqual(packet["source_node"]["id"], "button:1")
        self.assertEqual(packet["current_binding"], unresolved)
        self.assertEqual(
            read_json(self.extract_dir / "state.json")["state"], "repair_required"
        )
        self.assertFalse((self.extract_dir / "semantic-review.input.json").exists())

    def test_bindings_generate_repair_packets_then_reach_exact_coverage(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        extract_dir = self.extract_dir
        manifest_sha = read_json(extract_dir / "state.json")["source_manifest_sha256"]
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": manifest_sha,
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The rendered artboard is one page."],
                    "parent_block_id": None,
                    "child_block_ids": ["offer"],
                    "appearance": {
                        "background": "Light page surface.",
                        "border": "No page-level border.",
                        "spacing": "Vertical content rhythm.",
                    },
                    "content_summary": "Checkout content.",
                    "composition": "Heading followed by an offer.",
                    "relations": [],
                },
                {
                    "block_id": "offer",
                    "name": "Primary offer",
                    "role": "primary_offer",
                    "role_basis": "interpreted",
                    "role_evidence": ["The card groups details and one action."],
                    "parent_block_id": "page",
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Contrasting card surface.",
                        "border": "Rounded boundary.",
                        "spacing": "Separated content and action.",
                    },
                    "content_summary": "Offer details and action.",
                    "composition": "Action belongs to the offer.",
                    "relations": [],
                },
            ],
        }
        draft_path = self.root / "draft-for-bindings.json"
        write_json(draft_path, draft)
        recorded_draft = self.run_stage_cli(
            "record-draft",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(recorded_draft.returncode, 0, recorded_draft.stderr)
        draft_sha = read_json(extract_dir / "state.json")["semantic_draft_sha256"]

        partial = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": manifest_sha,
            "semantic_draft_sha256": draft_sha,
            "assignments": [
                {
                    "source_node_id": "root:1",
                    "status": "mapped",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "Artboard defines the page.",
                },
                {
                    "source_node_id": "text:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_copy",
                    "rationale": "Title is page content.",
                },
                {
                    "source_node_id": "group:1",
                    "status": "mapped",
                    "block_id": "offer",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "Group represents the offer.",
                },
            ],
        }
        bindings_path = self.root / "bindings.json"
        write_json(bindings_path, partial)
        crash_leftover = extract_dir / "repair-packets" / "revision-0002"
        crash_leftover.mkdir(parents=True)
        (crash_leftover / "interrupted.tmp").write_text("stale", encoding="utf-8")
        partial_result = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(partial_result.returncode, 0, partial_result.stderr)
        coverage = read_json(extract_dir / "coverage.json")
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["partitions"]["unresolved"], ["button:1"])
        self.assertEqual(coverage["duplicate_bindings"], [])
        self.assertEqual(coverage["synthetic_source_ids"], [])
        state = read_json(extract_dir / "state.json")
        self.assertEqual(state["state"], "repair_required")
        packet_path = extract_dir / coverage["repair_packets"]["button:1"]
        packet = read_json(packet_path)
        self.assertEqual(packet["source_node"]["id"], "button:1")
        self.assertEqual(packet["parent_node"]["id"], "group:1")
        self.assertEqual(packet["reference"]["crop_bounds"], sample_design()["figma_json"]["artboard"]["layers"][1]["layers"][0]["realFrame"])
        self.assertEqual(packet["candidate_block_ids"], ["offer"])

        duplicate = json.loads(json.dumps(partial))
        duplicate["assignments"].append(duplicate["assignments"][0])
        write_json(bindings_path, duplicate)
        rejected = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("duplicate_source_binding", rejected.stderr)
        self.assertEqual(read_json(extract_dir / "state.json")["revision"], 2)

        phantom_complete = json.loads(json.dumps(partial))
        phantom_complete["assignments"][2]["block_id"] = "page"
        phantom_complete["assignments"].append(
            {
                "source_node_id": "button:1",
                "status": "absorbed",
                "block_id": "page",
                "geometry_basis": "real_frame",
                "content_role": "static_visual",
                "rationale": "Incorrectly collapses the action into the page.",
            }
        )
        write_json(bindings_path, phantom_complete)
        phantom = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(phantom.returncode, 2)
        self.assertIn("unbound_semantic_leaf", phantom.stderr)

        complete = json.loads(json.dumps(partial))
        complete["assignments"].append(
            {
                "source_node_id": "button:1",
                "status": "absorbed",
                "block_id": "offer",
                "geometry_basis": "real_frame",
                "content_role": "static_visual",
                "rationale": "Rotated action is part of the offer.",
            }
        )
        write_json(bindings_path, complete)
        completed = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        coverage = read_json(extract_dir / "coverage.json")
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["partitions"]["mapped"], ["root:1", "group:1"])
        self.assertEqual(coverage["partitions"]["absorbed"], ["text:1", "button:1"])
        self.assertEqual(coverage["partitions"]["non_rendering"], [])
        self.assertEqual(coverage["partitions"]["unresolved"], [])
        self.assertEqual(
            read_json(extract_dir / "state.json")["state"], "awaiting_semantic_review"
        )
        review_template = read_json(extract_dir / "semantic-review.input.json")
        self.assertEqual(
            [item["block_id"] for item in review_template["block_reviews"]],
            ["page", "offer"],
        )
        self.assertEqual(review_template["decision"], "revise")
        self.assertEqual(
            review_template["coverage_sha256"],
            read_json(extract_dir / "state.json")["coverage_sha256"],
        )
        self.assertEqual(
            review_template["binding_evidence"]["blocks"],
            [
                {
                    "block_id": "page",
                    "mapped_source_node_ids": ["root:1"],
                    "absorbed_source_node_ids": ["text:1"],
                },
                {
                    "block_id": "offer",
                    "mapped_source_node_ids": ["group:1"],
                    "absorbed_source_node_ids": ["button:1"],
                },
            ],
        )
        self.assertEqual(review_template["binding_evidence"]["non_rendering"], [])
        reverse_evidence = review_template["reverse_binding_evidence"]
        self.assertEqual(
            [item["source_node"]["id"] for item in reverse_evidence["nodes"]],
            ["root:1", "text:1", "group:1", "button:1"],
        )
        self.assertEqual(
            [item["source_node_id"] for item in review_template["source_node_reviews"]],
            ["root:1", "text:1", "group:1", "button:1"],
        )
        offer_node = next(
            item
            for item in reverse_evidence["nodes"]
            if item["source_node"]["id"] == "group:1"
        )
        self.assertEqual(offer_node["assignment"]["block_id"], "offer")
        self.assertEqual(offer_node["assigned_block"]["block_id"], "offer")
        self.assertEqual(offer_node["parent_source_node"]["id"], "root:1")
        self.assertTrue(
            all("source_binding_correct" in item for item in review_template["block_reviews"])
        )
        self.assertIn(
            "non_rendering_classifications_correct", review_template["cross_block_review"]
        )

    def test_bindings_return_every_source_edge_that_reverses_the_block_hierarchy(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The rendered artboard is one page."],
                    "parent_block_id": None,
                    "child_block_ids": ["offer"],
                    "appearance": {
                        "background": "Light page surface.",
                        "border": "No page-level border.",
                        "spacing": "Vertical content rhythm.",
                    },
                    "content_summary": "Checkout content.",
                    "composition": "Heading followed by an offer.",
                    "relations": [],
                },
                {
                    "block_id": "offer",
                    "name": "Primary offer",
                    "role": "primary_offer",
                    "role_basis": "interpreted",
                    "role_evidence": ["The card groups details and one action."],
                    "parent_block_id": "page",
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Contrasting card surface.",
                        "border": "Rounded boundary.",
                        "spacing": "Separated content and action.",
                    },
                    "content_summary": "Offer details and action.",
                    "composition": "Action belongs to the offer.",
                    "relations": [],
                },
            ],
        }
        draft_path = self.root / "reversed-topology-draft.json"
        write_json(draft_path, draft)
        drafted = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(drafted.returncode, 0, drafted.stderr)

        state = read_json(self.extract_dir / "state.json")
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [
                {
                    "source_node_id": "root:1",
                    "status": "mapped",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "The artboard defines the page.",
                },
                {
                    "source_node_id": "text:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_copy",
                    "rationale": "The title belongs to the page.",
                },
                {
                    "source_node_id": "group:1",
                    "status": "mapped",
                    "block_id": "offer",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "The source group defines the offer.",
                },
                {
                    "source_node_id": "button:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "real_frame",
                    "content_role": "static_visual",
                    "rationale": "This intentionally reverses the source hierarchy.",
                },
            ],
        }
        bindings_path = self.root / "reversed-topology-bindings.json"
        write_json(bindings_path, bindings)

        recorded = self.run_stage_cli(
            "record-bindings", "--bindings", str(bindings_path)
        )

        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        coverage = read_json(self.extract_dir / "coverage.json")
        self.assertFalse(coverage["complete"])
        self.assertEqual(
            coverage["topology_projection"]["issues"],
            [
                {
                    "code": "source_edge_reverses_block_hierarchy",
                    "source_parent_id": "group:1",
                    "source_child_id": "button:1",
                    "parent_block_id": "offer",
                    "child_block_id": "page",
                    "source_parent_path": ["root:1", "group:1"],
                    "source_child_path": ["root:1", "group:1", "button:1"],
                    "source_sibling_index": 0,
                    "expected": "child Block must equal or descend from parent Block",
                }
            ],
        )
        topology_packet = coverage["topology_repair_packets"]["button:1"]
        self.assertEqual(topology_packet["source_parent"]["id"], "group:1")
        self.assertEqual(topology_packet["source_child"]["id"], "button:1")
        self.assertEqual(topology_packet["parent_block"]["block_id"], "offer")
        self.assertEqual(topology_packet["child_block"]["block_id"], "page")
        self.assertEqual(
            topology_packet["allowed_repairs"],
            [
                "bind_to_existing_block",
                "split_semantic_block",
                "merge_semantic_blocks",
                "create_semantic_block",
                "fix_parent_child_relation",
                "classify_non_rendering",
            ],
        )
        self.assertEqual(
            read_json(self.extract_dir / "state.json")["state"], "repair_required"
        )
        self.assertFalse((self.extract_dir / "semantic-review.input.json").exists())

    def test_bindings_reject_a_geometry_basis_whose_source_field_is_missing(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The rendered artboard is one page."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Light page surface.",
                        "border": "No outer border.",
                        "spacing": "Content follows a vertical rhythm.",
                    },
                    "content_summary": "Checkout content.",
                    "composition": "One page-level composition.",
                    "relations": [],
                }
            ],
        }
        draft_path = self.root / "geometry-draft.json"
        write_json(draft_path, draft)
        recorded = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        state = read_json(self.extract_dir / "state.json")
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [
                {
                    "source_node_id": node_id,
                    "status": "mapped" if node_id == "root:1" else "absorbed",
                    "block_id": "page",
                    "geometry_basis": "real_frame" if node_id == "text:1" else (
                        "real_frame" if node_id == "button:1" else "frame"
                    ),
                    "content_role": (
                        "static_copy" if node_id == "text:1" else "static_visual"
                    ),
                    "rationale": "Every source node contributes to the page.",
                }
                for node_id in ("root:1", "text:1", "group:1", "button:1")
            ],
        }
        bindings_path = self.root / "missing-geometry-bindings.json"
        write_json(bindings_path, bindings)
        rejected = self.run_stage_cli(
            "record-bindings", "--bindings", str(bindings_path)
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("invalid_geometry_basis", rejected.stderr)

    def test_bindings_reject_a_named_basis_on_a_geometryless_source_node(self) -> None:
        source = sample_design()
        source["figma_json"]["artboard"]["layers"] = [
            {
                "id": "metadata:1",
                "type": "metadataLayer",
                "name": "Geometryless metadata",
            }
        ]
        write_json(self.source, source)
        self.assertEqual(self.prepare_workspace().returncode, 0)

        state = read_json(self.extract_dir / "state.json")
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The rendered artboard is one page."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Light page surface.",
                        "border": "No outer border.",
                        "spacing": "No rendered child spacing is present.",
                    },
                    "content_summary": "Checkout page.",
                    "composition": "One page-level composition.",
                    "relations": [],
                }
            ],
        }
        draft_path = self.root / "geometryless-draft.json"
        write_json(draft_path, draft)
        recorded = self.run_stage_cli("record-draft", "--draft", str(draft_path))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        state = read_json(self.extract_dir / "state.json")
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [
                {
                    "source_node_id": "root:1",
                    "status": "mapped",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "The artboard defines the page.",
                },
                {
                    "source_node_id": "metadata:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "The metadata contributes to the page.",
                },
            ],
        }
        bindings_path = self.root / "geometryless-bindings.json"
        write_json(bindings_path, bindings)
        rejected = self.run_stage_cli(
            "record-bindings", "--bindings", str(bindings_path)
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("invalid_geometry_basis", rejected.stderr)

    def test_reverse_json_audit_rejects_a_present_node_bound_to_the_wrong_block(self) -> None:
        review = self.prepare_single_block_reverse_review()
        self.fill_passing_semantic_review(review)
        target = next(
            item
            for item in review["source_node_reviews"]
            if item["source_node_id"] == "group:1"
        )
        target["semantic_assignment_correct"] = False
        target["issues"] = [
            "The Offer card JSON group is present but incorrectly absorbed into the page instead of owning an offer Block."
        ]
        review_path = self.root / "wrong-block-review.json"
        write_json(review_path, review)

        false_pass = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertNotEqual(false_pass.returncode, 0)
        self.assertIn("false_semantic_pass", false_pass.stderr)
        review["decision"] = "revise"
        write_json(review_path, review)
        revised = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )
        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        self.assertEqual(read_json(self.extract_dir / "state.json")["state"], "repair_required")
        repair = read_json(self.extract_dir / "semantic-repair.json")
        packet = repair["reverse_repair_packets"]["group:1"]
        self.assertEqual(
            packet["source_and_current_block"]["source_node"]["payload"]["name"],
            "Offer card",
        )
        self.assertEqual(
            packet["source_and_current_block"]["assigned_block"]["block_id"],
            "page",
        )

    def test_reverse_json_audit_returns_an_independent_subtree_swallowed_by_parent(self) -> None:
        review = self.prepare_single_block_reverse_review()
        self.fill_passing_semantic_review(review)
        target = next(
            item
            for item in review["source_node_reviews"]
            if item["source_node_id"] == "group:1"
        )
        target["independent_grouping_correct"] = False
        target["issues"] = [
            "The rounded Offer card subtree is an independent visual-semantic group but the draft has no corresponding child Block."
        ]
        review["decision"] = "revise"
        review_path = self.root / "swallowed-subtree-review.json"
        write_json(review_path, review)

        revised = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        repair = read_json(self.extract_dir / "semantic-repair.json")
        packet = repair["reverse_repair_packets"]["group:1"]
        self.assertEqual(
            [item["id"] for item in packet["source_and_current_block"]["child_source_nodes"]],
            ["button:1"],
        )
        self.assertIn("create_semantic_block", packet["allowed_repairs"])

    def test_reverse_json_audit_returns_a_wrong_source_parent_child_relation(self) -> None:
        review = self.prepare_single_block_reverse_review()
        self.fill_passing_semantic_review(review)
        target = next(
            item
            for item in review["source_node_reviews"]
            if item["source_node_id"] == "button:1"
        )
        target["parent_child_relation_correct"] = False
        target["issues"] = [
            "The Apply node belongs under the Offer card source parent, but the semantic draft erased that containment relation."
        ]
        review["decision"] = "revise"
        review_path = self.root / "wrong-parent-review.json"
        write_json(review_path, review)

        revised = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        packet = read_json(self.extract_dir / "semantic-repair.json")[
            "reverse_repair_packets"
        ]["button:1"]
        self.assertEqual(
            packet["source_and_current_block"]["parent_source_node"]["id"],
            "group:1",
        )
        self.assertIn("fix_parent_child_relation", packet["allowed_repairs"])

    def test_reverse_json_audit_requires_every_source_node_in_exact_order(self) -> None:
        review = self.prepare_single_block_reverse_review()
        self.fill_passing_semantic_review(review)
        review["source_node_reviews"] = review["source_node_reviews"][:-1]
        review_path = self.root / "missing-node-review.json"
        write_json(review_path, review)

        rejected = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("every JSON source node", rejected.stderr)

    def test_reverse_json_audit_collects_all_node_failures_before_repair(self) -> None:
        review = self.prepare_single_block_reverse_review()
        self.fill_passing_semantic_review(review)
        group = next(
            item
            for item in review["source_node_reviews"]
            if item["source_node_id"] == "group:1"
        )
        group["semantic_assignment_correct"] = False
        group["issues"] = [
            "The Offer card needs its own semantic Block instead of the page assignment."
        ]
        button = next(
            item
            for item in review["source_node_reviews"]
            if item["source_node_id"] == "button:1"
        )
        button["parent_child_relation_correct"] = False
        button["issues"] = [
            "The Apply action must remain semantically contained by the Offer card."
        ]
        review["decision"] = "revise"
        review_path = self.root / "complete-round-review.json"
        write_json(review_path, review)

        revised = self.run_stage_cli(
            "record-review", "--review", str(review_path)
        )

        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        repair = read_json(self.extract_dir / "semantic-repair.json")
        self.assertEqual(
            set(repair["reverse_repair_packets"]), {"group:1", "button:1"}
        )
        self.assertEqual(
            set(repair["source_node_issues"]), {"group:1", "button:1"}
        )

    def test_semantic_review_is_the_final_binary_gate_and_detects_source_drift(self) -> None:
        self.assertEqual(self.prepare_workspace().returncode, 0)
        extract_dir = self.extract_dir
        manifest_sha = read_json(extract_dir / "state.json")["source_manifest_sha256"]
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": manifest_sha,
            "blocks": [
                {
                    "block_id": "page",
                    "name": "Checkout page",
                    "role": "loan_checkout",
                    "role_basis": "interpreted",
                    "role_evidence": ["The heading, offer, and action form one checkout task."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Light page with a contrasting offer surface.",
                        "border": "The offer has a visible rounded boundary.",
                        "spacing": "The content follows a vertical task flow.",
                    },
                    "content_summary": "Heading, offer, and primary action.",
                    "composition": "One dominant offer leads to one action.",
                    "relations": [],
                }
            ],
        }
        draft_path = self.root / "final-draft.json"
        write_json(draft_path, draft)
        result = self.run_stage_cli(
            "record-draft",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_json(extract_dir / "state.json")
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": manifest_sha,
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [
                {
                    "source_node_id": "root:1",
                    "status": "mapped",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "Artboard defines the page.",
                },
                {
                    "source_node_id": "text:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_copy",
                    "rationale": "Heading is page content.",
                },
                {
                    "source_node_id": "group:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "Offer is part of the task.",
                },
                {
                    "source_node_id": "button:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "real_frame",
                    "content_role": "static_visual",
                    "rationale": "Action is part of the offer.",
                },
            ],
        }
        bindings_path = self.root / "final-bindings.json"
        write_json(bindings_path, bindings)
        result = self.run_stage_cli(
            "record-bindings",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_json(extract_dir / "state.json")
        review = read_json(extract_dir / "semantic-review.input.json")
        review["decision"] = "pass"
        for item in review["block_reviews"]:
            item["role_correct"] = True
            item["hierarchy_correct"] = True
            item["appearance_interpretation_correct"] = True
            item["content_grouping_correct"] = True
            item["source_binding_correct"] = True
            item["issues"] = []
        for item in review["source_node_reviews"]:
            item["semantic_assignment_correct"] = True
            item["content_role_correct"] = True
            item["independent_grouping_correct"] = True
            item["parent_child_relation_correct"] = True
            item["evidence"] = [
                "The exact JSON source node, assigned Block, and source parent-child relation agree."
            ]
            item["issues"] = []
        cross = review["cross_block_review"]
        cross["relations_correct"] = True
        cross["reading_order_correct"] = True
        cross["no_semantic_omissions"] = True
        cross["non_rendering_classifications_correct"] = True
        cross["issues"] = []
        review_path = self.root / "semantic-review.json"
        write_json(review_path, review)

        placeholder = self.run_stage_cli(
            "record-review",
            "--review",
            str(review_path),
        )
        self.assertEqual(placeholder.returncode, 2)
        self.assertIn("placeholder_review_evidence", placeholder.stderr)

        review["block_reviews"][0]["evidence"] = [
            "The source-bound facts and rendered reference agree."
        ]
        cross["evidence"] = [
            "All source nodes are covered and the task flow is coherent."
        ]
        for item in review["source_group_reviews"]:
            item["semantic_relation"] = "matches_block"
            item["visual_semantics_correct"] = True
            item["json_grouping_reconciled"] = True
            item["visual_evidence"] = [
                "The rendered group boundary was inspected before reading JSON grouping."
            ]
            item["json_evidence"] = [
                "The complete JSON group hierarchy maps to the current page Block."
            ]
            item["rationale"] = [
                "The visual hypothesis and JSON grouping evidence agree in this fixture."
            ]
            item["issues"] = []
        write_json(review_path, review)

        frozen_source = extract_dir / "source" / "design.json"
        original_source = frozen_source.read_bytes()
        frozen_source.write_bytes(original_source + b"\n")
        drifted = self.run_stage_cli(
            "record-review",
            "--review",
            str(review_path),
        )
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("source_drift", drifted.stderr)
        self.assertFalse((extract_dir / "stage-result.json").exists())
        frozen_source.write_bytes(original_source)

        passed = self.run_stage_cli(
            "record-review",
            "--review",
            str(review_path),
        )
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(read_json(extract_dir / "state.json")["state"], "complete")
        stage_result = read_json(extract_dir / "stage-result.json")
        self.assertEqual(stage_result["status"], "complete")
        self.assertEqual(
            stage_result["exact_coverage_equation"],
            "all_source_nodes = mapped ⊎ absorbed ⊎ non_rendering; unresolved = ∅",
        )
        self.assertEqual(
            stage_result["gates"],
            {
                "source_facts_lossless": True,
                "source_asset_relations_resolvable": True,
                "reference_coordinate_mapping_exact": True,
                "exact_coverage": True,
                "no_duplicate_bindings": True,
                "no_synthetic_source_ids": True,
                "semantic_blocks_reconstruct_complete_design_json": True,
                "source_parent_child_projection_exact": True,
                "reverse_json_semantic_audit": True,
                "visual_json_group_reconciliation": True,
                "semantic_review_passed": True,
            },
        )
        semantic_blocks = read_json(extract_dir / "semantic-blocks.json")
        self.assertTrue(semantic_blocks["source_topology_projection"]["ok"])
        self.assertEqual(
            [
                (item["source_parent_id"], item["source_child_id"], item["relation"])
                for item in semantic_blocks["source_topology_projection"]["edges"]
            ],
            [
                ("root:1", "text:1", "same_block"),
                ("root:1", "group:1", "same_block"),
                ("group:1", "button:1", "same_block"),
            ],
        )
        manifest = read_json(extract_dir / "source-manifest.json")
        self.assertEqual(
            stage_result["artifacts"]["asset_index"],
            {
                "path": "asset-index.json",
                "sha256": manifest["asset_index_sha256"],
            },
        )
        self.assertEqual(
            stage_result["artifacts"]["reference"],
            manifest["reference"],
        )
        verified = self.run_stage_cli("verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["complete"])

        result_path = extract_dir / "stage-result.json"
        original_result = result_path.read_bytes()
        tampered_result = json.loads(original_result)
        tampered_result["status"] = "incomplete"
        write_json(result_path, tampered_result)
        rejected = self.run_stage_cli("verify")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stage_drift", rejected.stderr)
        result_path.write_bytes(original_result)


if __name__ == "__main__":
    unittest.main()
