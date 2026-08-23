from __future__ import annotations

import json
import base64
import fcntl
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract.py"
IOLE_SCRIPT = SCRIPT.parents[3] / "iole" / "scripts" / "iole_flow_contract_v2.py"
IOLE_MAPPING = SCRIPT.parents[3] / "iole" / "references" / "role-mapping-v2.json"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
URL_A = (
    "https://lanhuapp.com/web/#/item/project/detailDetach?"
    "pid=project-1&image_id=image-a&fromEditor=true"
)
URL_B = (
    "https://lanhuapp.com/web/#/item/project/detailDetach?"
    "pid=project-1&image_id=image-b&fromEditor=true"
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_for(name: str, design_id: str, version_id: str, url: str, node_id: str) -> dict:
    image_id = "image-a" if url == URL_A else "image-b"
    return {
        "design_name": name,
        "design_id": design_id,
        "version_id": version_id,
        "lanhu_url": url,
        "source_identity": {
            "project_id": "project-1",
            "image_id": image_id,
            "team_id": "",
        },
        "figma_json": {
            "artboard": {
                "id": node_id,
                "type": "artboard",
                "name": name,
                "frame": {"x": 0, "y": 0, "width": 1, "height": 1},
                "layers": [],
            }
        },
    }


class BatchCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.reference = self.root / "reference.png"
        self.reference.write_bytes(PNG_1X1)
        self.urls_file = self.root / "urls.json"
        write_json(
            self.urls_file,
            {"schema": "icp.extract.run-input.v1", "design_urls": [URL_A, URL_B]},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def begin(self) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "begin-run",
            "--project-root",
            str(self.project),
            "--urls-file",
            str(self.urls_file),
        )

    def prepare_design(self, source: dict) -> subprocess.CompletedProcess[str]:
        source_path = self.root / f"{source['design_id']}.json"
        write_json(source_path, source)
        return self.run_cli(
            "prepare",
            "--project-root",
            str(self.project),
            "--source-json",
            str(source_path),
            "--reference-image",
            str(self.reference),
            "--allow-loose-input",
            "--design-url",
            source["lanhu_url"],
        )

    def complete_design(self, name: str, url: str, node_id: str) -> None:
        stage_dir = self.project / ".icp" / "extract" / name
        state = read_json(stage_dir / "state.json")
        draft_path = stage_dir / "semantic-draft.input.json"
        draft = {
            "schema": "icp.extract.semantic-draft.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "blocks": [
                {
                    "block_id": "page",
                    "name": f"{name} page",
                    "role": "page",
                    "role_basis": "entailed",
                    "role_evidence": ["The rendered artboard is the page."],
                    "parent_block_id": None,
                    "child_block_ids": [],
                    "appearance": {
                        "background": "Single page surface.",
                        "border": "No outer border.",
                        "spacing": "No child spacing is present.",
                    },
                    "content_summary": "One empty fixture page.",
                    "composition": "Single semantic root.",
                    "relations": [],
                }
            ],
        }
        write_json(draft_path, draft)
        result = self.run_cli(
            "record-draft",
            "--project-root",
            str(self.project),
            "--design-name",
            name,
            "--draft",
            str(draft_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_json(stage_dir / "state.json")
        bindings_path = stage_dir / "bindings.input.json"
        bindings = {
            "schema": "icp.extract.bindings.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "assignments": [
                {
                    "source_node_id": node_id,
                    "status": "mapped",
                    "block_id": "page",
                    "geometry_basis": "frame",
                    "content_role": "static_visual",
                    "rationale": "The artboard directly represents the page.",
                }
            ],
        }
        write_json(bindings_path, bindings)
        result = self.run_cli(
            "record-bindings",
            "--project-root",
            str(self.project),
            "--design-name",
            name,
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_json(stage_dir / "state.json")
        review_path = stage_dir / "semantic-review.input.json"
        review = read_json(review_path)
        review["decision"] = "pass"
        for item in review["block_reviews"]:
            item["role_correct"] = True
            item["hierarchy_correct"] = True
            item["appearance_interpretation_correct"] = True
            item["content_grouping_correct"] = True
            item["source_binding_correct"] = True
            item["evidence"] = ["Rendered reference and the bound artboard agree."]
            item["issues"] = []
        for item in review["source_node_reviews"]:
            item["semantic_assignment_correct"] = True
            item["content_role_correct"] = True
            item["independent_grouping_correct"] = True
            item["parent_child_relation_correct"] = True
            item["evidence"] = [
                "The exact JSON artboard node and its assigned page Block agree."
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
            item["visual_evidence"] = ["The rendered group boundary was inspected first."]
            item["json_evidence"] = [
                "The source group hierarchy and subtree Block projection agree."
            ]
            item["rationale"] = [
                "Visual semantics and JSON grouping evidence are explicitly reconciled."
            ]
            item["issues"] = []
        cross = review["cross_block_review"]
        cross["relations_correct"] = True
        cross["reading_order_correct"] = True
        cross["no_semantic_omissions"] = True
        cross["non_rendering_classifications_correct"] = True
        cross["evidence"] = ["The fixture has one source node and one semantic block."]
        cross["issues"] = []
        write_json(review_path, review)
        result = self.run_cli(
            "record-review",
            "--project-root",
            str(self.project),
            "--design-name",
            name,
            "--review",
            str(review_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli(
            "verify",
            "--project-root",
            str(self.project),
            "--design-name",
            name,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def remove_checklist_receipt(self, node_id: str) -> None:
        checklist_path = self.project / ".icp" / "extract" / "checklist.json"
        checklist = read_json(checklist_path)
        checklist["events"] = [
            event
            for event in checklist["events"]
            if not (event["node_id"] == node_id and event["event"] == "completed")
        ]
        for sequence, event in enumerate(checklist["events"], start=1):
            event["sequence"] = sequence
        target = next(item for item in checklist["nodes"] if item["node_id"] == node_id)
        target["status"] = "pending"
        target["evidence_sha256"] = None
        target["invalidated_by"] = None
        write_json(checklist_path, checklist)

    def test_committed_stage_state_repairs_missing_checklist_receipts_without_new_revision(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        source = source_for("Design A", "design-a", "version-a", URL_A, "root:a")
        prepared = self.prepare_design(source)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        stage_dir = self.project / ".icp" / "extract" / "Design A"

        state = read_json(stage_dir / "state.json")
        draft_path = stage_dir / "semantic-draft.input.json"
        write_json(
            draft_path,
            {
                "schema": "icp.extract.semantic-draft.v1",
                "source_manifest_sha256": state["source_manifest_sha256"],
                "blocks": [
                    {
                        "block_id": "page",
                        "name": "Design A page",
                        "role": "page",
                        "role_basis": "entailed",
                        "role_evidence": ["The rendered artboard is the page."],
                        "parent_block_id": None,
                        "child_block_ids": [],
                        "appearance": {
                            "background": "Single page surface.",
                            "border": "No outer border.",
                            "spacing": "No child spacing is present.",
                        },
                        "content_summary": "One empty fixture page.",
                        "composition": "Single semantic root.",
                        "relations": [],
                    }
                ],
            },
        )
        recorded = self.run_cli(
            "record-draft",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        draft_revision = read_json(stage_dir / "state.json")["revision"]
        self.remove_checklist_receipt("design:image-a.semantic-draft")
        resumed = self.run_cli(
            "record-draft",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(read_json(stage_dir / "state.json")["revision"], draft_revision)
        self.assertEqual(
            next(
                item
                for item in read_json(self.project / ".icp" / "extract" / "checklist.json")["nodes"]
                if item["node_id"] == "design:image-a.semantic-draft"
            )["status"],
            "completed",
        )

        state = read_json(stage_dir / "state.json")
        unresolved_path = stage_dir / "bindings.unresolved.input.json"
        write_json(
            unresolved_path,
            {
                "schema": "icp.extract.bindings.v1",
                "source_manifest_sha256": state["source_manifest_sha256"],
                "semantic_draft_sha256": state["semantic_draft_sha256"],
                "assignments": [],
            },
        )
        unresolved = self.run_cli(
            "record-bindings",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--bindings",
            str(unresolved_path),
        )
        self.assertEqual(unresolved.returncode, 0, unresolved.stderr)
        self.assertFalse(json.loads(unresolved.stdout)["complete"])
        self.assertEqual(
            next(
                item
                for item in read_json(self.project / ".icp" / "extract" / "checklist.json")["nodes"]
                if item["node_id"] == "design:image-a.bindings"
            )["status"],
            "pending",
        )
        revised_draft = read_json(draft_path)
        revised_draft["blocks"][0]["name"] = "Revised Design A page"
        write_json(draft_path, revised_draft)
        repaired = self.run_cli(
            "record-draft",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--draft",
            str(draft_path),
        )
        self.assertEqual(repaired.returncode, 0, repaired.stderr)

        state = read_json(stage_dir / "state.json")
        bindings_path = stage_dir / "bindings.input.json"
        write_json(
            bindings_path,
            {
                "schema": "icp.extract.bindings.v1",
                "source_manifest_sha256": state["source_manifest_sha256"],
                "semantic_draft_sha256": state["semantic_draft_sha256"],
                "assignments": [
                    {
                        "source_node_id": "root:a",
                        "status": "mapped",
                        "block_id": "page",
                        "geometry_basis": "frame",
                        "content_role": "static_visual",
                        "rationale": "The artboard directly represents the page.",
                    }
                ],
            },
        )
        recorded = self.run_cli(
            "record-bindings",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        bindings_revision = read_json(stage_dir / "state.json")["revision"]
        self.remove_checklist_receipt("design:image-a.bindings")
        resumed = self.run_cli(
            "record-bindings",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--bindings",
            str(bindings_path),
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(read_json(stage_dir / "state.json")["revision"], bindings_revision)

        review_path = stage_dir / "semantic-review.input.json"
        review = read_json(review_path)
        review["decision"] = "pass"
        for item in review["block_reviews"]:
            item.update(
                {
                    "role_correct": True,
                    "hierarchy_correct": True,
                    "appearance_interpretation_correct": True,
                    "content_grouping_correct": True,
                    "source_binding_correct": True,
                    "evidence": ["Rendered reference and bound source agree."],
                    "issues": [],
                }
            )
        for item in review["source_node_reviews"]:
            item.update(
                {
                    "semantic_assignment_correct": True,
                    "content_role_correct": True,
                    "independent_grouping_correct": True,
                    "parent_child_relation_correct": True,
                    "evidence": ["The exact source node and assigned Block agree."],
                    "issues": [],
                }
            )
        for item in review["source_group_reviews"]:
            item.update(
                {
                    "semantic_relation": "matches_block",
                    "visual_semantics_correct": True,
                    "json_grouping_reconciled": True,
                    "visual_evidence": ["The rendered group boundary was inspected."],
                    "json_evidence": ["The source hierarchy and Block projection agree."],
                    "rationale": ["Visual and JSON evidence agree."],
                    "issues": [],
                }
            )
        review["cross_block_review"].update(
            {
                "relations_correct": True,
                "reading_order_correct": True,
                "no_semantic_omissions": True,
                "non_rendering_classifications_correct": True,
                "evidence": ["The fixture has one source node and one Block."],
                "issues": [],
            }
        )
        write_json(review_path, review)
        recorded = self.run_cli(
            "record-review",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--review",
            str(review_path),
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        review_revision = read_json(stage_dir / "state.json")["revision"]
        self.remove_checklist_receipt("design:image-a.semantic-review")
        resumed = self.run_cli(
            "record-review",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
            "--review",
            str(review_path),
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(read_json(stage_dir / "state.json")["revision"], review_revision)

    def test_batch_requires_every_expected_design_to_verify(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        extract_root = self.project / ".icp" / "extract"
        manifest = read_json(extract_root / "run-manifest.json")
        self.assertEqual(manifest["design_count"], 2)
        self.assertEqual([item["design_url"] for item in manifest["designs"]], [URL_A, URL_B])

        source_a = source_for("Design A", "design-a", "version-a", URL_A, "root:a")
        source_b = source_for("Design B", "design-b", "version-b", URL_B, "root:b")
        self.assertEqual(self.prepare_design(source_a).returncode, 0)
        self.assertEqual(self.prepare_design(source_b).returncode, 0)
        self.assertTrue((extract_root / "Design A" / "source-manifest.json").is_file())
        self.assertTrue((extract_root / "Design B" / "source-manifest.json").is_file())

        self.complete_design("Design A", URL_A, "root:a")
        incomplete = self.run_cli(
            "verify-run", "--project-root", str(self.project)
        )
        self.assertEqual(incomplete.returncode, 2)
        self.assertIn("batch_incomplete", incomplete.stderr)

        self.complete_design("Design B", URL_B, "root:b")
        complete = self.run_cli(
            "verify-run", "--project-root", str(self.project)
        )
        self.assertEqual(complete.returncode, 0, complete.stderr)
        summary = json.loads(complete.stdout)
        self.assertEqual(summary["verified_design_count"], 2)
        run_result = read_json(extract_root / "run-result.json")
        self.assertEqual(run_result["status"], "complete")
        self.assertEqual(len(run_result["designs"]), 2)
        checklist = read_json(extract_root / "checklist.json")
        self.assertTrue(
            all(item["status"] == "completed" for item in checklist["nodes"])
        )

        index_path = extract_root / "index.json"
        index = read_json(index_path)
        index["designs"][0]["design_name"] = index["designs"][1]["design_name"]
        index["designs"][0]["design_dir"] = index["designs"][1]["design_dir"]
        index["designs"][0]["stage_result_sha256"] = index["designs"][1][
            "stage_result_sha256"
        ]
        write_json(index_path, index)
        cross_wired = self.run_cli("verify-run", "--project-root", str(self.project))
        self.assertEqual(cross_wired.returncode, 2)
        self.assertIn("batch_stage_mismatch", cross_wired.stderr)

    def test_begin_run_freezes_the_complete_stage_checklist_and_reports_the_first_missing_node(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)

        checklist = read_json(
            self.project / ".icp" / "extract" / "checklist.json"
        )
        self.assertEqual(checklist["stage"], "extract")
        self.assertEqual(
            [item["node_id"] for item in checklist["nodes"]],
            [
                "run.freeze",
                "design:image-a.prepare",
                "design:image-a.semantic-draft",
                "design:image-a.bindings",
                "design:image-a.semantic-review",
                "design:image-a.verify",
                "design:image-b.prepare",
                "design:image-b.semantic-draft",
                "design:image-b.bindings",
                "design:image-b.semantic-review",
                "design:image-b.verify",
                "run.verify",
            ],
        )
        self.assertEqual(checklist["nodes"][0]["status"], "completed")
        self.assertTrue(
            all(item["status"] == "pending" for item in checklist["nodes"][1:])
        )

        incomplete = self.run_cli(
            "verify-run", "--project-root", str(self.project)
        )
        self.assertEqual(incomplete.returncode, 2)
        self.assertIn("checklist_incomplete", incomplete.stderr)
        self.assertIn("resume_from_node=design:image-a.prepare", incomplete.stderr)

    def test_stage_writer_lock_times_out_without_publishing_run_state(self) -> None:
        extract_root = self.project / ".icp" / "extract"
        lock_fd = os.open(self.project, os.O_RDONLY)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            result = self.run_cli(
                "begin-run",
                "--project-root",
                str(self.project),
                "--urls-file",
                str(self.urls_file),
                "--lock-timeout-seconds",
                "0.05",
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        self.assertEqual(result.returncode, 2)
        self.assertIn('"error": "stage_busy"', result.stderr)
        self.assertFalse((extract_root / "run-manifest.json").exists())

    def test_ui_context_is_injected_and_complete_blocks_reconstruct_source_facts(self) -> None:
        ui_supplement = "Keep the account summary and primary action in separate visual groups."
        write_json(
            self.urls_file,
            {
                "schema": "icp.extract.run-input.v2",
                "designs": [
                    {"design_url": URL_A, "ui_supplement": ui_supplement},
                    {"design_url": URL_B, "ui_supplement": None},
                ],
            },
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)

        source_a = source_for("Design A", "design-a", "version-a", URL_A, "root:a")
        self.assertEqual(self.prepare_design(source_a).returncode, 0)
        stage_dir = self.project / ".icp" / "extract" / "Design A"
        authoring = read_json(stage_dir / "semantic-authoring.input.json")
        self.assertEqual(authoring["ui_supplement"], ui_supplement)
        self.assertEqual(
            authoring["source_manifest_sha256"],
            read_json(stage_dir / "state.json")["source_manifest_sha256"],
        )
        source_b = source_for("Design B", "design-b", "version-b", URL_B, "root:b")
        self.assertEqual(self.prepare_design(source_b).returncode, 0)
        self.assertIsNone(
            read_json(
                self.project
                / ".icp"
                / "extract"
                / "Design B"
                / "semantic-authoring.input.json"
            )["ui_supplement"]
        )

        self.complete_design("Design A", URL_A, "root:a")
        review = read_json(stage_dir / "semantic-review.json")
        self.assertEqual(review["semantic_context"]["ui_supplement"], ui_supplement)

        semantic_blocks = read_json(stage_dir / "semantic-blocks.json")
        source_facts = read_json(stage_dir / "source-facts.json")
        reconstructed_nodes = {}
        for block in semantic_blocks["blocks"]:
            for source_node in block["source_nodes"]:
                reconstructed_nodes[source_node["source_node_id"]] = source_node[
                    "source_fact"
                ]
        for source_node in semantic_blocks["non_rendering_source_nodes"]:
            reconstructed_nodes[source_node["source_node_id"]] = source_node[
                "source_fact"
            ]
        self.assertEqual(semantic_blocks["node_order"], source_facts["node_order"])
        self.assertEqual(reconstructed_nodes, source_facts["nodes"])
        self.assertEqual(
            semantic_blocks["source_facts_sha256"],
            hashlib.sha256((stage_dir / "source-facts.json").read_bytes()).hexdigest(),
        )
        def rebuild_node(node_id: str) -> dict:
            record = reconstructed_nodes[node_id]
            node = dict(record["payload"])
            if record["layers_kind"] == "array":
                node["layers"] = [
                    rebuild_node(child_id) for child_id in record["child_ids"]
                ]
            elif record["layers_kind"] == "null":
                node["layers"] = None
            return node

        reconstructed_design = json.loads(
            json.dumps(semantic_blocks["source_document_without_artboard"])
        )
        reconstructed_design["figma_json"]["artboard"] = rebuild_node(
            semantic_blocks["root_node_id"]
        )
        self.assertEqual(reconstructed_design, source_a)
        stage_result = read_json(stage_dir / "stage-result.json")
        self.assertEqual(
            stage_result["artifacts"]["semantic_blocks"]["path"],
            "semantic-blocks.json",
        )

        semantic_blocks["blocks"][0]["source_nodes"][0]["source_fact"]["payload"][
            "name"
        ] = "tampered"
        write_json(stage_dir / "semantic-blocks.json", semantic_blocks)
        rejected = self.run_cli(
            "verify",
            "--project-root",
            str(self.project),
            "--design-name",
            "Design A",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stage_drift", rejected.stderr)

    def test_iole_bundle_is_frozen_once_before_extract_and_binds_every_design(self) -> None:
        ui_supplement = "Use the account summary only to assist visual grouping."
        raw_row = {
            "标题": "Login flow",
            "Route": "login",
            "设计稿地址": URL_A + "\n" + URL_B,
            "UI补充描述": ui_supplement,
            "交互描述": "",
            "UT": "",
            "IT": "",
            "E2E": "",
            "接口描述": "",
            "frontend status": "ready",
            "frontend pr": "",
            "frontend reviews": "",
            "frontend lease_token": "",
            "frontend lease_until": "",
            "frontend last_error": "",
        }
        spreadsheet_id = "extract-integration-fixture"
        sheet_name = "Sheet1"
        source_id = "google-sheets:" + canonical_digest(
            {"sheet_name": sheet_name, "spreadsheet_id": spreadsheet_id}
        )
        operational_columns = {
            "标题",
            "frontend status",
            "frontend pr",
            "frontend reviews",
            "frontend lease_token",
            "frontend lease_until",
            "frontend last_error",
        }
        fields = [
            {
                "column": column,
                "source_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "references": [],
                "dismissals": [],
            }
            for column, value in raw_row.items()
            if column not in operational_columns
        ]
        analysis = {
            "kind": "iole.source-analysis-input.v2",
            "schema_version": 2,
            "source_id": source_id,
            "role": "client",
            "root_title": "Login flow",
            "rows": [
                {"title": "Login flow", "change_scope": "modify", "fields": fields}
            ],
        }
        catalog_payload = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "row_id_column": "标题",
            "titles": ["Login flow"],
        }
        catalog = {
            "kind": "icps.flow-title-catalog.v1",
            "schema_version": 1,
            **catalog_payload,
            "catalog_digest": canonical_digest(catalog_payload),
        }
        review = {
            "kind": "iole.source-closure-review.v1",
            "schema_version": 1,
            "analysis_sha256": canonical_digest(analysis),
            "title_catalog_digest": catalog["catalog_digest"],
            "decision": "pass",
            "field_reviews": [
                {
                    "title": "Login flow",
                    "column": field["column"],
                    "source_sha256": field["source_sha256"],
                    "all_dependencies_identified": True,
                    "reference_targets_correct": True,
                    "dismissals_correct": True,
                    "evidence": ["Compared the complete field with the title catalog."],
                    "issues": [],
                }
                for field in fields
            ],
            "cross_review": {
                "every_business_field_reviewed": True,
                "no_unresolved_reference": True,
                "no_ambiguous_target": True,
                "evidence": ["Every source field was reviewed exactly once."],
                "issues": [],
            },
        }
        raw_path = self.root / "raw-rows.json"
        analysis_path = self.root / "source-analysis.json"
        catalog_path = self.root / "title-catalog.json"
        review_path = self.root / "source-closure-review.json"
        write_json(raw_path, {"Login flow": raw_row})
        write_json(analysis_path, analysis)
        write_json(catalog_path, catalog)
        write_json(review_path, review)
        compiled = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "build-source-bundle",
                "--raw-rows",
                str(raw_path),
                "--title-catalog",
                str(catalog_path),
                "--analysis",
                str(analysis_path),
                "--closure-review",
                str(review_path),
                "--mapping",
                str(IOLE_MAPPING),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        bundle = json.loads(compiled.stdout)
        self.assertEqual(
            bundle["row_data_columns"],
            [
                "标题",
                "Route",
                "设计稿地址",
                "UI补充描述",
                "交互描述",
                "UT",
                "IT",
                "E2E",
                "接口描述",
            ],
        )
        source_bundle = self.root / "source-bundle.json"
        source_bundle.write_text(
            json.dumps(bundle, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        begun = self.run_cli(
            "begin-run",
            "--project-root",
            str(self.project),
            "--source-bundle",
            str(source_bundle),
        )

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        frozen_path = self.project / ".icp" / "source" / "source-bundle.json"
        self.assertEqual(read_json(frozen_path), bundle)
        manifest = read_json(self.project / ".icp" / "extract" / "run-manifest.json")
        self.assertEqual(manifest["source_bundle"]["bundle_digest"], bundle["bundle_digest"])
        self.assertEqual(
            manifest["source_bundle"]["sha256"],
            hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [
                (item["design_url"], item["member_title"], item["contract_digest"], item["ui_supplement"])
                for item in manifest["designs"]
            ],
            [
                (
                    URL_A,
                    "Login flow",
                    bundle["members"][0]["source_contract"]["contract_digest"],
                    ui_supplement,
                ),
                (
                    URL_B,
                    "Login flow",
                    bundle["members"][0]["source_contract"]["contract_digest"],
                    ui_supplement,
                ),
            ],
        )

    def test_batch_rejects_different_designs_with_the_same_safe_name(self) -> None:
        self.assertEqual(self.begin().returncode, 0)
        source_a = source_for("Same name", "design-a", "version-a", URL_A, "root:a")
        source_b = source_for("Same name", "design-b", "version-b", URL_B, "root:b")
        self.assertEqual(self.prepare_design(source_a).returncode, 0)
        collision = self.prepare_design(source_b)
        self.assertEqual(collision.returncode, 2)
        self.assertIn("design_name_collision", collision.stderr)
        first = self.project / ".icp" / "extract" / "Same name" / "source-manifest.json"
        self.assertEqual(read_json(first)["design_id"], "design-a")


if __name__ == "__main__":
    unittest.main()
