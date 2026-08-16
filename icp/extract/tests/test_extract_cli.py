from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract.py"


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
                    "rationale": "These nodes directly form the page context.",
                },
                {
                    "source_node_ids": [],
                    "source_subtree_roots": ["group:1"],
                    "status": "mapped",
                    "block_id": "offer",
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
                    "rationale": "Artboard defines the page.",
                },
                {
                    "source_node_id": "text:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "rationale": "Title is page content.",
                },
                {
                    "source_node_id": "group:1",
                    "status": "mapped",
                    "block_id": "offer",
                    "geometry_basis": "frame",
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
        self.assertTrue(
            all("source_binding_correct" in item for item in review_template["block_reviews"])
        )
        self.assertIn(
            "non_rendering_classifications_correct", review_template["cross_block_review"]
        )

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
                    "rationale": "The artboard defines the page.",
                },
                {
                    "source_node_id": "metadata:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
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
                    "rationale": "Artboard defines the page.",
                },
                {
                    "source_node_id": "text:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "rationale": "Heading is page content.",
                },
                {
                    "source_node_id": "group:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "rationale": "Offer is part of the task.",
                },
                {
                    "source_node_id": "button:1",
                    "status": "absorbed",
                    "block_id": "page",
                    "geometry_basis": "real_frame",
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
                "semantic_review_passed": True,
            },
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
