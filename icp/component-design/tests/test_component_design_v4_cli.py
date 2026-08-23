from __future__ import annotations

import hashlib
import importlib.util
import json
import fcntl
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


STAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = STAGE_ROOT / "scripts" / "component_design.py"
MOBILE_COMPONENT_PATTERNS = (
    STAGE_ROOT / "references" / "mobile-component-patterns.md"
)
IOLE_SCRIPT = STAGE_ROOT.parents[1] / "iole" / "scripts" / "iole_flow_contract_v2.py"
IOLE_MAPPING = STAGE_ROOT.parents[1] / "iole" / "references" / "role-mapping-v2.json"
from .extract_fixture import URL_A, URL_B, create_verified_extract

COMPONENT_DESIGN_SPEC = importlib.util.spec_from_file_location(
    "icp_component_design_script", SCRIPT
)
if COMPONENT_DESIGN_SPEC is None or COMPONENT_DESIGN_SPEC.loader is None:
    raise RuntimeError("cannot load component-design script for contract tests")
COMPONENT_DESIGN = importlib.util.module_from_spec(COMPONENT_DESIGN_SPEC)
COMPONENT_DESIGN_SPEC.loader.exec_module(COMPONENT_DESIGN)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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


def refresh_iole_digests(bundle: dict) -> dict:
    """Recompute the closure/bundle digest chain after legitimate fixture edits."""

    closure = bundle["source_closure"]
    analysis_sha = canonical_digest(closure["analysis"])
    closure["review"]["analysis_sha256"] = analysis_sha
    closure["analysis_sha256"] = analysis_sha
    closure["review_sha256"] = canonical_digest(closure["review"])
    closure.pop("closure_digest", None)
    closure["closure_digest"] = canonical_digest(closure)
    bundle.pop("bundle_digest", None)
    bundle["bundle_digest"] = canonical_digest(bundle)
    return bundle


def run_command(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def member_row(
    title: str,
    route: str,
    design_url: str,
    ui: str,
    interaction: str,
    api: str,
) -> dict[str, str]:
    return {
        "标题": title,
        "Route": route,
        "设计稿地址": design_url,
        "UI补充描述": ui,
        "交互描述": interaction,
        "接口描述": api,
        "UT": "",
        "IT": "",
        "E2E": "",
        "frontend status": "ready",
        "frontend pr": "",
        "frontend reviews": "",
        "frontend lease_token": "",
        "frontend lease_until": "",
        "frontend last_error": "",
    }


class ComponentDesignV4CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline_temp = tempfile.TemporaryDirectory()
        cls.baseline_root = Path(cls.baseline_temp.name)
        cls.baseline_project = create_verified_extract(cls.baseline_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.baseline_temp.cleanup()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        shutil.copytree(self.baseline_project, self.project)
        self.stage_dir = self.project / ".icp" / "component-design"
        self.bundle_path = self.build_source_bundle()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def build_source_bundle(
        self,
        include_designless_context: bool = False,
        source_contains_todo: bool = False,
        source_contains_whitespace_only_clause: bool = False,
        design_b_scope: str = "modify",
        empty_interaction_for_design_b: bool = False,
        design_a_relation_kind: str = "navigation",
        design_a_interaction_override: str | None = None,
        design_a_api_override: str | None = None,
        design_a_it_override: str | None = None,
        design_a_e2e_override: str | None = None,
        acceptance_order: tuple[str, ...] | None = None,
    ) -> Path:
        design_a_interaction = (
            "Help opens Design B as a modal."
            if design_a_relation_kind == "modal"
            else "Selecting the offer navigates to Design B."
        )
        if design_a_interaction_override is not None:
            design_a_interaction = design_a_interaction_override
        raw_rows = {
            "Design A": member_row(
                "Design A",
                "design-a",
                URL_A,
                "Show the available withdrawal offer.",
                design_a_interaction,
                (
                    "Read the amount from the loan detail response."
                    if design_a_api_override is None
                    else design_a_api_override
                ),
            ),
            "Design B": member_row(
                "Design B",
                "design-b",
                URL_B,
                "Show the selected withdrawal offer.",
                "Confirming submits the selected offer.",
                "Send the selected offer identifier.",
            ),
        }
        if source_contains_todo:
            raw_rows["Design A"]["UI补充描述"] = (
                "Show the customer's TODO items exactly as the business source names them."
            )
        if source_contains_whitespace_only_clause:
            raw_rows["Design A"]["接口描述"] = " "
        if empty_interaction_for_design_b:
            raw_rows["Design B"]["交互描述"] = ""
        if design_a_it_override is not None:
            raw_rows["Design A"]["IT"] = design_a_it_override
        if design_a_e2e_override is not None:
            raw_rows["Design A"]["E2E"] = design_a_e2e_override
        if include_designless_context:
            raw_rows["Design A"]["交互描述"] = (
                "Selecting the offer navigates to Design B. "
                "Help opens Designless Context."
            )
            raw_rows["Designless Context"] = member_row(
                "Designless Context",
                "existing-context",
                "",
                "This existing page is read-only context for the flow.",
                "Returning leaves the current flow unchanged.",
                "",
            )
        spreadsheet_id = "component-design-fixture"
        sheet_name = "Sheet1"
        source_id = "google-sheets:" + canonical_digest(
            {"sheet_name": sheet_name, "spreadsheet_id": spreadsheet_id}
        )
        scopes = {
            "Design A": "modify",
            "Design B": design_b_scope,
        }
        if include_designless_context:
            scopes["Designless Context"] = "context"

        analysis_rows = []
        for title, row in raw_rows.items():
            fields = []
            for column, value in row.items():
                if column in {
                    "标题",
                    "frontend status",
                    "frontend pr",
                    "frontend reviews",
                    "frontend lease_token",
                    "frontend lease_until",
                    "frontend last_error",
                }:
                    continue
                references = []
                targets = ["Design B"] if title == "Design A" else []
                if title == "Design A" and include_designless_context:
                    targets.append("Designless Context")
                for target in targets:
                    start = value.find(target)
                    if start >= 0:
                        references.append(
                            {
                                "reference_id": f"{title}-{column}-{target}",
                                "start": start,
                                "end": start + len(target),
                                "quote": target,
                                "target_title": target,
                                "relation_kind": (
                                    design_a_relation_kind
                                    if target == "Design B"
                                    else "navigation"
                                ),
                            }
                        )
                fields.append(
                    {
                        "column": column,
                        "source_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                        "references": references,
                        "dismissals": [],
                    }
                )
            analysis_rows.append(
                {"title": title, "change_scope": scopes[title], "fields": fields}
            )
        analysis = {
            "kind": "iole.source-analysis-input.v2",
            "schema_version": 2,
            "source_id": source_id,
            "role": "client",
            "root_title": "Design A",
            "rows": analysis_rows,
        }
        catalog_payload = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "row_id_column": "标题",
            "titles": list(raw_rows),
        }
        title_catalog = {
            "kind": "icps.flow-title-catalog.v1",
            "schema_version": 1,
            **catalog_payload,
            "catalog_digest": canonical_digest(catalog_payload),
        }
        field_reviews = [
            {
                "title": row["title"],
                "column": field["column"],
                "source_sha256": field["source_sha256"],
                "all_dependencies_identified": True,
                "reference_targets_correct": True,
                "dismissals_correct": True,
                "evidence": ["Complete source field checked against the title catalog."],
                "issues": [],
            }
            for row in analysis_rows
            for field in row["fields"]
        ]
        closure_review = {
            "kind": "iole.source-closure-review.v1",
            "schema_version": 1,
            "analysis_sha256": canonical_digest(analysis),
            "title_catalog_digest": title_catalog["catalog_digest"],
            "decision": "pass",
            "field_reviews": field_reviews,
            "cross_review": {
                "every_business_field_reviewed": True,
                "no_unresolved_reference": True,
                "no_ambiguous_target": True,
                "evidence": ["Every analyzed source field is represented once."],
                "issues": [],
            },
        }
        raw_path = self.root / "raw-rows.json"
        analysis_path = self.root / "source-analysis.json"
        catalog_path = self.root / "title-catalog.json"
        review_path = self.root / "source-closure-review.json"
        bundle_path = self.project / ".icp" / "source" / "source-bundle.json"
        write_json(raw_path, raw_rows)
        write_json(analysis_path, analysis)
        write_json(catalog_path, title_catalog)
        write_json(review_path, closure_review)
        mapping_path = IOLE_MAPPING
        if acceptance_order is not None:
            mapping = read_json(IOLE_MAPPING)
            sections = {
                section["prefix"]: section
                for section in mapping["job"]["acceptance_sections"]
            }
            mapping["job"]["acceptance_sections"] = [
                sections[prefix] for prefix in acceptance_order
            ]
            mapping_path = self.root / "role-mapping-v2.reordered.json"
            write_json(mapping_path, mapping)
        result = run_command(
            IOLE_SCRIPT,
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
            str(mapping_path),
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(result.stdout, encoding="utf-8")
        return bundle_path

    def begin(self, project_catalog: dict | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            "begin",
            "--project-root",
            str(self.project),
        ]
        if project_catalog is not None:
            catalog_path = self.root / "project-component-catalog.json"
            write_json(catalog_path, project_catalog)
            args.extend(["--project-catalog", str(catalog_path)])
        return run_command(SCRIPT, *args)

    def test_begin_reads_the_single_stage1_frozen_source_without_external_bundle(self) -> None:
        frozen_path = self.project / ".icp" / "source" / "source-bundle.json"
        write_json(frozen_path, read_json(self.bundle_path))

        begun = run_command(
            SCRIPT,
            "begin",
            "--project-root",
            str(self.project),
        )

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        state = read_json(self.stage_dir / "state.json")
        self.assertEqual(
            state["source_bundle_digest"],
            read_json(frozen_path)["bundle_digest"],
        )

    def test_begin_rebuilds_uncommitted_artifacts_when_state_was_not_published(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        expected_state = read_json(self.stage_dir / "state.json")
        (self.stage_dir / "state.json").unlink()

        resumed = self.begin()

        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual(read_json(self.stage_dir / "state.json"), expected_state)
        self.assertEqual(
            read_json(self.stage_dir / "checklist.json")["nodes"][0]["status"],
            "completed",
        )

    def test_begin_requires_the_stage1_frozen_source(self) -> None:
        (self.project / ".icp" / "source" / "source-bundle.json").unlink()

        begun = run_command(
            SCRIPT,
            "begin",
            "--project-root",
            str(self.project),
        )

        self.assertEqual(begun.returncode, 2, begun.stdout + begun.stderr)
        self.assertIn("missing_frozen_source", begun.stderr)

    def test_begin_rejects_a_second_external_source_bundle(self) -> None:
        external = self.root / "second-source-bundle.json"
        write_json(external, read_json(self.bundle_path))

        begun = run_command(
            SCRIPT,
            "begin",
            "--project-root",
            str(self.project),
            "--source-bundle",
            str(external),
        )

        self.assertNotEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        self.assertIn("unrecognized arguments: --source-bundle", begun.stderr)

    def test_component_lock_exposes_a_closed_implementation_contract_without_raw_source(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

        lock = read_json(self.stage_dir / "component-lock.json")
        contract = lock["implementation_contract"]
        forbidden_keys = {
            "source_coverage",
            "source_refs",
            "source_ref",
            "source_text",
            "quote",
            "row_data",
            "source_contract",
        }

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(collect_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value)) if value else set()
            return set()

        self.assertFalse(forbidden_keys & collect_keys(contract))
        self.assertEqual(
            contract["source_identity"]["bundle_digest"],
            read_json(self.bundle_path)["bundle_digest"],
        )
        self.assertTrue(contract["semantic_facts"])
        self.assertIn("documented_integration_obligations", contract)

    def test_it_obligations_follow_the_it_header_not_acceptance_position(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_it_override="IT verifies the selected offer is submitted.",
            design_a_e2e_override="E2E verifies the whole application flow.",
            acceptance_order=("E2E", "UT", "IT"),
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

        context = read_json(self.stage_dir / "business-context.json")
        member = next(
            item for item in context["members"] if item["title"] == "Design A"
        )
        it_clause_id = next(
            clause["clause_id"]
            for clause in member["clauses"]
            if clause["label"] == "IT"
        )
        self.assertEqual(it_clause_id, "acceptance:2")
        page_key = COMPONENT_DESIGN.page_key_for("Design A")
        facts = read_json(
            self.stage_dir / "page-component-facts" / f"{page_key}.json"
        )
        expected_it_fact_ids = {
            fact["fact_id"]
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if any(
                ref["clause_id"] == it_clause_id for ref in fact["source_refs"]
            )
        }
        self.assertTrue(expected_it_fact_ids)

        contract = read_json(self.stage_dir / "component-lock.json")[
            "implementation_contract"
        ]
        actual_it_fact_ids = {
            obligation["fact_id"]
            for obligation in contract["documented_integration_obligations"]
            if obligation["source_kind"] == "it_description"
            and obligation["page_key"] == page_key
        }
        self.assertEqual(actual_it_fact_ids, expected_it_fact_ids)

    def historical_catalog(
        self,
        evidence_class: str = "verified-component-lock",
        component_id: str = "historical-page-shell",
    ) -> dict:
        semantic_contract = {
            "component_id": component_id,
            "name": "Historical page shell",
            "kind": "page",
            "scope": "shared",
            "reuse_mode": "container",
            "responsibility": "Own a page shell and place page-specific content.",
            "owns": ["The root visual boundary and one content slot."],
            "excludes": ["All page-specific behavior and business data."],
            "capabilities": [],
            "slots": [
                {
                    "slot_id": "content",
                    "role": "Place a page-specific business component.",
                    "cardinality": "one",
                }
            ],
            "data_roles": [],
            "action_roles": [],
        }
        if evidence_class == "verified-component-lock":
            provenance_path = self.project / ".icp" / "history" / "component-lock.json"
            write_json(
                provenance_path,
                {
                    "schema": "icp.component-design.lock.v4",
                    "component_definitions": [semantic_contract],
                },
            )
        else:
            provenance_path = self.project / "src" / "HistoricalPageShell.kt"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                "class HistoricalPageShell\n", encoding="utf-8"
            )
        return {
            "schema": "icp.component-design.project-catalog.v1",
            "components": [
                {
                    "component_id": component_id,
                    "evidence_class": evidence_class,
                    "provenance": {
                        "path": str(provenance_path.relative_to(self.project)),
                        "sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
                    },
                    "semantic_contract": semantic_contract,
                }
            ],
        }

    def with_interaction_items(self, facts: dict) -> dict:
        interaction_coverage = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        if not interaction_coverage["source_text"]:
            return facts
        self.add_transition_result_facts(facts)
        facts_by_id = {
            fact["fact_id"]: fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
        }
        items = []
        for segment_index, segment in enumerate(interaction_coverage["segments"], start=1):
            if segment["disposition"] != "fact":
                continue
            segment_item_count = len(items)
            source_ref = {
                "member_title": facts["member_title"],
                "clause_id": interaction_coverage["clause_id"],
                "source_sha256": interaction_coverage["source_sha256"],
                "start": segment["start"],
                "end": segment["end"],
                "quote": segment["quote"],
            }
            for fact_index, fact_id in enumerate(segment["fact_ids"], start=1):
                fact = facts_by_id[fact_id]
                if fact["kind"] not in {
                    "condition",
                    "state",
                    "trigger",
                    "behavior",
                    "result",
                }:
                    continue
                item = {
                    "item_id": (
                        f"{facts['page_key']}-interaction-{segment_index}-{fact_index}"
                    ),
                    "source_ref": source_ref,
                    "condition": None,
                    "state": None,
                    "trigger": None,
                    "behavior": None,
                    "result": None,
                }
                item[fact["kind"]] = {
                    "fact_id": fact_id,
                    "meaning": fact["meaning"],
                }
                items.append(item)
            if len(items) == segment_item_count:
                items.append(
                    {
                        "item_id": (
                            f"{facts['page_key']}-interaction-{segment_index}-null"
                        ),
                        "source_ref": source_ref,
                        "condition": None,
                        "state": None,
                        "trigger": None,
                        "behavior": None,
                        "result": None,
                    }
                )
        facts["interaction_items"] = items
        candidate_by_fact_id = {
            fact["fact_id"]: candidate["candidate_id"]
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
        }
        parts_by_field = {
            field: [item[field] for item in items if item[field] is not None]
            for field in ("condition", "state", "trigger", "behavior", "result")
        }
        graph_parts: dict[str, dict | None] = {}
        graph_bindings: dict[str, list[str]] = {}
        for field, parts in parts_by_field.items():
            graph_parts[field] = (
                None
                if not parts
                else {
                    "fact_ids": [part["fact_id"] for part in parts],
                    "inference_basis": [],
                    **(
                        {"kind": "local", "api_contract_id": None}
                        if field == "behavior"
                        else {}
                    ),
                    **({"outcomes": ["done"]} if field == "result" else {}),
                }
            )
            graph_bindings[f"{field}_candidate_ids"] = list(
                dict.fromkeys(
                    candidate_by_fact_id[part["fact_id"]] for part in parts
                )
            )
        graph_interactions = []
        if any(graph_parts.values()):
            if graph_parts["behavior"] is not None and graph_parts["trigger"] is None:
                graph_parts["trigger"] = {
                    "fact_ids": [],
                    "inference_basis": [f"{facts['page_key']}:implicit-trigger"],
                }
                graph_bindings["trigger_candidate_ids"] = list(
                    graph_bindings["behavior_candidate_ids"]
                )
            if graph_parts["trigger"] is not None and graph_parts["behavior"] is None:
                graph_parts["behavior"] = {
                    "fact_ids": [],
                    "inference_basis": [f"{facts['page_key']}:implicit-behavior"],
                    "kind": "local",
                    "api_contract_id": None,
                }
                graph_bindings["behavior_candidate_ids"] = list(
                    graph_bindings["trigger_candidate_ids"]
                )
            graph_interactions.append(
                {
                    "interaction_id": f"{facts['page_key']}-interaction",
                    **graph_parts,
                    "component_bindings": graph_bindings,
                }
            )
        facts["interaction_graph"] = {
            "schema": "icp.component-design.interaction-graph.v2",
            "interactions": graph_interactions,
            "edges": [],
            "terminal_outcomes": [],
        }
        if facts.get("api_contracts") and graph_interactions:
            behavior_interaction = next(
                (
                    interaction
                    for interaction in graph_interactions
                    if interaction["behavior"] is not None
                ),
                None,
            )
            if behavior_interaction is not None:
                behavior_interaction["behavior"]["kind"] = "api_call"
                behavior_interaction["behavior"]["api_contract_id"] = facts[
                    "api_contracts"
                ][0]["api_contract_id"]
        if facts.get("api_contracts"):
            return self.bind_first_api_contract(facts)
        return self.close_result_outcomes(facts)

    def transition_requirements_of(self, facts: dict) -> list[tuple[str, dict, str]]:
        requirements: list[tuple[str, dict, str]] = []
        for requirement in facts.get("navigation_requirements", []):
            requirements.append(
                (
                    "navigation",
                    requirement,
                    requirement["navigation_requirement_id"],
                )
            )
        for requirement in facts.get("presentation_requirements", []):
            if requirement["relation_kind"] == "modal":
                requirements.append(
                    (
                        "modal",
                        requirement,
                        requirement["presentation_requirement_id"],
                    )
                )
        return requirements

    def add_transition_result_facts(self, facts: dict) -> dict:
        """Give every declared cross-page transition a source-backed result fact."""

        requirements = self.transition_requirements_of(facts)
        if not requirements:
            return facts
        interaction_coverage = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        if not interaction_coverage["source_text"]:
            return facts
        segment = next(
            (
                segment
                for segment in interaction_coverage["segments"]
                if segment["disposition"] == "fact"
            ),
            None,
        )
        if segment is None:
            return facts
        content = facts["candidates"][-1]
        block_refs = (
            [{"design_name": facts["design_names"][0], "block_id": "content"}]
            if facts.get("design_names")
            else []
        )
        for index, (_kind, requirement, _requirement_id) in enumerate(
            requirements, start=1
        ):
            fact_id = f"{facts['page_key']}-result-{index}"
            if any(fact["fact_id"] == fact_id for fact in content["facts"]):
                continue
            content["facts"].append(
                {
                    "fact_id": fact_id,
                    "evidence_class": "business_source",
                    "kind": "result",
                    "meaning": (
                        f"Open {requirement['target_member_title']} from this page."
                    ),
                    "source_refs": [
                        {
                            "member_title": facts["member_title"],
                            "clause_id": interaction_coverage["clause_id"],
                            "source_sha256": interaction_coverage["source_sha256"],
                            "start": segment["start"],
                            "end": segment["end"],
                            "quote": segment["quote"],
                        }
                    ],
                    "block_refs": json.loads(json.dumps(block_refs)),
                }
            )
            segment["fact_ids"].append(fact_id)
        return facts

    def close_transition_edges(self, facts: dict) -> dict:
        """Consume every declared navigation/modal requirement with one edge."""

        requirements = self.transition_requirements_of(facts)
        if not requirements:
            return facts
        self.add_transition_result_facts(facts)
        graph = facts["interaction_graph"]
        consumed = {
            requirement_id
            for edge in graph["edges"]
            if edge["target"]["kind"] in {"navigation", "modal"}
            for requirement_id in edge["target"]["requirement_ids"]
        }
        source = next(
            (
                item
                for item in graph["interactions"]
                if item.get("behavior") is not None
            ),
            None,
        )
        if source is None:
            return facts
        for index, (kind, requirement, requirement_id) in enumerate(
            requirements, start=1
        ):
            if requirement_id in consumed:
                continue
            if source.get("result") is None:
                source["result"] = {
                    "fact_ids": [],
                    "inference_basis": [
                        f"{facts['page_key']}:{source['interaction_id']}:implicit-result"
                    ],
                    "outcomes": (
                        ["success", "failure"]
                        if source["behavior"].get("kind") == "api_call"
                        else []
                    ),
                }
                source["component_bindings"]["result_candidate_ids"] = list(
                    source["component_bindings"].get("behavior_candidate_ids", [])
                )
            covering_fact_id = f"{facts['page_key']}-result-{index}"
            if covering_fact_id not in source["result"]["fact_ids"]:
                source["result"]["fact_ids"] = list(source["result"]["fact_ids"]) + [
                    covering_fact_id
                ]
                owner = next(
                    (
                        candidate["candidate_id"]
                        for candidate in facts["candidates"]
                        for fact in candidate["facts"]
                        if fact["fact_id"] == covering_fact_id
                    ),
                    None,
                )
                if (
                    owner is not None
                    and owner
                    not in source["component_bindings"]["result_candidate_ids"]
                ):
                    source["component_bindings"]["result_candidate_ids"].append(owner)
            outcome = "opened" if index == 1 else f"opened-{index}"
            if outcome not in source["result"]["outcomes"]:
                source["result"]["outcomes"] = list(source["result"]["outcomes"]) + [
                    outcome
                ]
            graph["edges"].append(
                {
                    "from_interaction_id": source["interaction_id"],
                    "outcome": outcome,
                    "target": {
                        "kind": kind,
                        "page_key": requirement["target_page_key"],
                        "design_name": requirement["target_member_title"],
                        "requirement_ids": [requirement_id],
                    },
                }
            )
        return facts

    def close_result_outcomes(self, facts: dict) -> dict:
        """Every behavior gets a result whose declared outcomes resolve once."""

        self.close_transition_edges(facts)
        graph = facts["interaction_graph"]
        resolved: dict[str, set[str]] = {}
        for edge in graph["edges"]:
            resolved.setdefault(edge["from_interaction_id"], set()).add(
                edge["outcome"]
            )
        terminal_keys = {
            (terminal["interaction_id"], terminal["outcome"])
            for terminal in graph["terminal_outcomes"]
        }
        for interaction in graph["interactions"]:
            behavior = interaction.get("behavior")
            if behavior is None:
                continue
            if interaction.get("result") is None:
                api = behavior.get("kind") == "api_call"
                interaction["result"] = {
                    "fact_ids": [],
                    "inference_basis": [
                        f"{facts['page_key']}:{interaction['interaction_id']}:implicit-result"
                    ],
                    "outcomes": ["success", "failure"] if api else ["done"],
                }
                interaction["component_bindings"]["result_candidate_ids"] = list(
                    interaction["component_bindings"].get(
                        "behavior_candidate_ids",
                        interaction["component_bindings"].get(
                            "trigger_candidate_ids", []
                        ),
                    )
                )
            for outcome in interaction["result"]["outcomes"]:
                if outcome in resolved.get(interaction["interaction_id"], set()):
                    continue
                if (interaction["interaction_id"], outcome) in terminal_keys:
                    continue
                graph["terminal_outcomes"].append(
                    {
                        "interaction_id": interaction["interaction_id"],
                        "outcome": outcome,
                        "inference_basis": [
                            f"{facts['page_key']}:{interaction['interaction_id']}:terminal-result"
                        ],
                    }
                )
                terminal_keys.add((interaction["interaction_id"], outcome))
        return facts

    def add_api_continuations(self, facts: dict, interaction: dict) -> None:
        contract_id = interaction["behavior"]["api_contract_id"]
        candidate_ids = list(
            dict.fromkeys(
                interaction["component_bindings"]["behavior_candidate_ids"]
                + interaction["component_bindings"]["trigger_candidate_ids"]
            )
        )
        for outcome, behavior_kind in (("success", "render"), ("failure", "present")):
            continuation_id = f"{interaction['interaction_id']}-{outcome}"
            if any(
                item["interaction_id"] == continuation_id
                for item in facts["interaction_graph"]["interactions"]
            ):
                continue
            facts["interaction_graph"]["interactions"].append(
                {
                    "interaction_id": continuation_id,
                    "condition": None,
                    "state": None,
                    "trigger": {
                        "fact_ids": [],
                        "inference_basis": [f"{contract_id}:{outcome}"],
                    },
                    "behavior": {
                        "fact_ids": [],
                        "inference_basis": [f"{contract_id}:{outcome}"],
                        "kind": behavior_kind,
                        "api_contract_id": None,
                    },
                    "result": {
                        "fact_ids": [],
                        "inference_basis": [f"{contract_id}:{outcome}"],
                        "outcomes": ["done"],
                    },
                    "component_bindings": {
                        "condition_candidate_ids": [],
                        "state_candidate_ids": [],
                        "trigger_candidate_ids": candidate_ids,
                        "behavior_candidate_ids": candidate_ids,
                        "result_candidate_ids": candidate_ids,
                    },
                }
            )
            facts["interaction_graph"]["terminal_outcomes"].append(
                {
                    "interaction_id": continuation_id,
                    "outcome": "done",
                    "inference_basis": [f"{contract_id}:{outcome}:terminal-result"],
                }
            )
            facts["interaction_graph"]["edges"].append(
                {
                    "from_interaction_id": interaction["interaction_id"],
                    "outcome": outcome,
                    "target": {
                        "kind": "interaction",
                        "to_interaction_id": continuation_id,
                    },
                }
            )

    def bind_first_api_contract(self, facts: dict) -> dict:
        if not facts["api_requirements"]:
            return facts
        requirement = facts["api_requirements"][0]
        contract_id = f"{facts['page_key']}-api"
        locator = requirement["locator"] or f"GET /{facts['page_key']}"
        locator_match = re.fullmatch(
            r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+)", locator
        )
        method = locator_match.group(1) if locator_match else "GET"
        path = (
            locator_match.group(2)
            if locator_match and locator_match.group(2).startswith("/")
            else f"/{facts['page_key']}"
        )
        numeric_locator = locator.split("/")
        project_id = (
            int(numeric_locator[0])
            if len(numeric_locator) == 2 and all(part.isdigit() for part in numeric_locator)
            else 101
        )
        endpoint_id = (
            int(numeric_locator[-1])
            if all(part.isdigit() for part in numeric_locator)
            else 201
        )
        raw_contract = {
            "openapi": "3.0.0",
            "paths": {
                path: {
                    method.lower(): {"responses": {"200": {"description": "OK"}}}
                }
            },
        }
        facts["api_contracts"] = [
            {
                "api_contract_id": contract_id,
                "requirement_ids": [requirement["requirement_id"]],
                "locator": locator,
                "apifox": {
                    "project_id": project_id,
                    "endpoint_id": endpoint_id,
                    "acquired_by": "readEntityDetails",
                    "raw_contract": raw_contract,
                    "raw_sha256": canonical_digest(raw_contract),
                },
                "normalized": {
                    "method": method,
                    "path": path,
                    "auth": None,
                    "parameters": [],
                    "request_body": None,
                    "responses": [{"status": "200", "schema": {"type": "object"}}],
                    "errors": [],
                },
            }
        ]
        interaction = next(
            (
                item
                for item in facts["interaction_graph"]["interactions"]
                if item["behavior"] is not None
            ),
            None,
        )
        if interaction is None:
            candidate_id = facts["candidates"][-1]["candidate_id"]
            interaction = {
                "interaction_id": f"{facts['page_key']}-api-call",
                "condition": None,
                "state": None,
                "trigger": {
                    "fact_ids": [],
                    "inference_basis": [requirement["requirement_id"]],
                },
                "behavior": {
                    "fact_ids": [],
                    "inference_basis": [requirement["requirement_id"]],
                    "kind": "api_call",
                    "api_contract_id": contract_id,
                },
                "result": None,
                "component_bindings": {
                    "condition_candidate_ids": [],
                    "state_candidate_ids": [],
                    "trigger_candidate_ids": [candidate_id],
                    "behavior_candidate_ids": [candidate_id],
                    "result_candidate_ids": [],
                },
            }
            facts["interaction_graph"]["interactions"].append(interaction)
        if interaction["trigger"] is None:
            trigger_interaction = next(
                (
                    item
                    for item in facts["interaction_graph"]["interactions"]
                    if item is not interaction and item["trigger"] is not None
                ),
                None,
            )
            if trigger_interaction is None:
                interaction["trigger"] = {
                    "fact_ids": [],
                    "inference_basis": [requirement["requirement_id"]],
                }
                interaction["component_bindings"]["trigger_candidate_ids"] = list(
                    interaction["component_bindings"]["behavior_candidate_ids"]
                )
            else:
                interaction["trigger"] = trigger_interaction["trigger"]
                interaction["component_bindings"]["trigger_candidate_ids"] = (
                    trigger_interaction["component_bindings"][
                        "trigger_candidate_ids"
                    ]
                )
                facts["interaction_graph"]["interactions"].remove(
                    trigger_interaction
                )
        interaction["behavior"]["kind"] = "api_call"
        interaction["behavior"]["api_contract_id"] = contract_id
        stale_result = interaction.get("result")
        if stale_result is not None and not stale_result.get("fact_ids"):
            interaction["result"] = None
            interaction["component_bindings"]["result_candidate_ids"] = []
            facts["interaction_graph"]["terminal_outcomes"] = [
                terminal
                for terminal in facts["interaction_graph"]["terminal_outcomes"]
                if terminal["interaction_id"] != interaction["interaction_id"]
            ]
        if interaction.get("result") is not None:
            for api_outcome in ("success", "failure"):
                if api_outcome not in interaction["result"]["outcomes"]:
                    interaction["result"]["outcomes"] = list(
                        interaction["result"]["outcomes"]
                    ) + [api_outcome]
        self.add_api_continuations(facts, interaction)
        return self.close_result_outcomes(facts)

    def valid_page_facts(self, page: dict[str, str]) -> dict:
        template = read_json(Path(page["input_path"]))
        if not template["design_names"]:
            page_key = template["page_key"]
            facts = []
            coverage = []
            for index, clause in enumerate(template["source_coverage"]):
                text = clause["source_text"]
                if text:
                    fact_id = f"{page_key}-source-fact-{index + 1}"
                    facts.append(
                        {
                            "fact_id": fact_id,
                            "evidence_class": "business_source",
                            "kind": (
                                "behavior"
                                if "interaction" in clause["clause_id"]
                                else "data"
                                if clause["clause_id"] == "page:route"
                                else "responsibility"
                            ),
                            "meaning": (
                                f"Apply this source-only member's page-local meaning from {clause['clause_id']}."
                            ),
                            "source_refs": [
                                {
                                    "member_title": template["member_title"],
                                    "clause_id": clause["clause_id"],
                                    "source_sha256": clause["source_sha256"],
                                    "start": 0,
                                    "end": len(text),
                                    "quote": text,
                                }
                            ],
                            "block_refs": [],
                        }
                    )
                    segments = [
                        {
                            "start": 0,
                            "end": len(text),
                            "quote": text,
                            "disposition": "fact",
                            "fact_ids": [fact_id],
                        }
                    ]
                else:
                    segments = []
                coverage.append({**clause, "segments": segments})
            return self.bind_first_api_contract(self.with_interaction_items({
                **template,
                "source_coverage": coverage,
                "candidates": [
                    {
                        "candidate_id": f"{page_key}-source-component",
                        "name": f"{template['member_title']} source component",
                        "kind": "component",
                        "responsibility": "Own the component semantics declared by this source-only row.",
                        "owns": ["This row's independent business semantics."],
                        "excludes": ["Any visual detail not declared by this row."],
                        "source_block_refs": [],
                        "facts": facts,
                    }
                ],
                "design_compositions": [],
            }))
        design_name = template["design_names"][0]
        page_key = template["page_key"]
        shell_id = f"{page_key}-shell"
        content_id = f"{page_key}-content"
        facts = []
        coverage = []
        semantic_meanings = {
            "design-a": "Use the declared Design A route as this page's route identity.",
            "design-b": "Use the declared Design B route as this page's route identity.",
            "Show the available withdrawal offer.": "Present the available withdrawal offer.",
            "Show the selected withdrawal offer.": "Present the selected withdrawal offer.",
            "Selecting the offer navigates to Design B.": "Selecting an offer navigates to Design B.",
            "Confirming submits the selected offer.": "Confirmation submits the selected offer.",
            "Read the amount from the loan detail response.": "Obtain the displayed amount from the loan detail response.",
            "Send the selected offer identifier.": "Submit the selected offer identifier to the declared API.",
        }
        for index, clause in enumerate(template["source_coverage"]):
            text = clause["source_text"]
            fact_id = f"{page_key}-fact-{index + 1}"
            if not text:
                segments = []
            else:
                segments = [
                    {
                        "start": 0,
                        "end": len(text),
                        "quote": text,
                        "disposition": "fact",
                        "fact_ids": [fact_id],
                    }
                ]
                facts.append(
                    {
                        "fact_id": fact_id,
                        "evidence_class": "business_source",
                        "kind": (
                            "behavior"
                            if "interaction" in clause["clause_id"]
                            else "api_dependency"
                            if clause["clause_id"] == "requirement:2"
                            else "data"
                            if clause["clause_id"] == "page:route"
                            else "responsibility"
                        ),
                        "meaning": semantic_meanings.get(
                            text,
                            f"Apply the page-local meaning declared by {clause['clause_id']}.",
                        ),
                        "source_refs": [
                            {
                                "member_title": template["member_title"],
                                "clause_id": clause["clause_id"],
                                "source_sha256": clause["source_sha256"],
                                "start": 0,
                                "end": len(text),
                                "quote": text,
                            }
                        ],
                        "block_refs": [
                            {"design_name": design_name, "block_id": "content"}
                        ],
                    }
                )
            coverage.append({**clause, "segments": segments})
        return self.bind_first_api_contract(self.with_interaction_items({
            **template,
            "source_coverage": coverage,
            "candidates": [
                {
                    "candidate_id": shell_id,
                    "name": f"{template['member_title']} shell",
                    "kind": "page",
                    "responsibility": "Own the page shell and content placement.",
                    "owns": ["The root page boundary."],
                    "excludes": ["Page-specific business behavior."],
                    "source_block_refs": [
                        {"design_name": design_name, "block_id": "page"}
                    ],
                    "facts": [],
                },
                {
                    "candidate_id": content_id,
                    "name": f"{template['member_title']} content",
                    "kind": "component",
                    "responsibility": "Expose this page's business content and behavior.",
                    "owns": ["The page-specific semantic content."],
                    "excludes": ["The surrounding page shell."],
                    "source_block_refs": [
                        {"design_name": design_name, "block_id": "content"}
                    ],
                    "facts": facts,
                },
            ],
            "design_compositions": [
                {
                    "design_name": design_name,
                    "root_instance_id": f"{page_key}-shell-instance",
                    "instances": [
                        {
                            "instance_id": f"{page_key}-shell-instance",
                            "candidate_id": shell_id,
                            "parent_instance_id": None,
                            "slot": "root",
                            "source_block_ids": ["page"],
                        },
                        {
                            "instance_id": f"{page_key}-content-instance",
                            "candidate_id": content_id,
                            "parent_instance_id": f"{page_key}-shell-instance",
                            "slot": "content",
                            "source_block_ids": ["content"],
                        },
                    ],
                }
            ],
        }))

    def page_facts_v4(self, facts: dict) -> dict:
        facts["schema"] = "icp.component-design.page-facts.v4"
        for candidate in facts["candidates"]:
            for fact in candidate["facts"]:
                fact["evidence_class"] = "business_source"
        return facts

    def add_design_visible_fact(
        self,
        facts: dict,
        *,
        kind: str = "responsibility",
        source_refs: list[dict] | None = None,
        visible_basis: str | None = "The verified root Block visibly owns the page frame.",
    ) -> dict:
        shell = facts["candidates"][0]
        design_name = facts["design_names"][0]
        fact = {
            "fact_id": f"{facts['page_key']}-visible-frame",
            "kind": kind,
            "meaning": "Own a visible page frame.",
            "evidence_class": "design_visible",
            "source_refs": [] if source_refs is None else source_refs,
            "block_refs": [{"design_name": design_name, "block_id": "page"}],
        }
        if visible_basis is not None:
            fact["visible_basis"] = visible_basis
        shell["facts"].append(fact)
        return fact

    def api_contract_entry(self, facts: dict, requirement: dict, contract_id: str) -> dict:
        locator = requirement["locator"] or f"GET /{facts['page_key']}"
        locator_match = re.fullmatch(
            r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+)", locator
        )
        method = locator_match.group(1) if locator_match else "GET"
        path = (
            locator_match.group(2)
            if locator_match and locator_match.group(2).startswith("/")
            else f"/{facts['page_key']}"
        )
        numeric_locator = locator.split("/")
        project_id = (
            int(numeric_locator[0])
            if len(numeric_locator) == 2 and all(part.isdigit() for part in numeric_locator)
            else 101
        )
        endpoint_id = (
            int(numeric_locator[-1])
            if all(part.isdigit() for part in numeric_locator)
            else 201
        )
        raw_contract = {
            "openapi": "3.0.0",
            "paths": {
                path: {
                    method.lower(): {"responses": {"200": {"description": "OK"}}}
                }
            },
        }
        return {
            "api_contract_id": contract_id,
            "requirement_ids": [requirement["requirement_id"]],
            "locator": locator,
            "apifox": {
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "acquired_by": "readEntityDetails",
                "raw_contract": raw_contract,
                "raw_sha256": canonical_digest(raw_contract),
            },
            "normalized": {
                "method": method,
                "path": path,
                "auth": None,
                "parameters": [],
                "request_body": None,
                "responses": [{"status": "200", "schema": {"type": "object"}}],
                "errors": [],
            },
        }

    def bind_two_api_contracts(self, facts: dict) -> dict:
        if len(facts["api_requirements"]) < 2:
            raise AssertionError("fixture needs two same-page API requirements")
        facts = self.bind_first_api_contract(facts)
        requirement = facts["api_requirements"][1]
        second = self.api_contract_entry(
            facts, requirement, f"{facts['page_key']}-api-2"
        )
        facts["api_contracts"].append(second)
        candidate_id = facts["candidates"][-1]["candidate_id"]
        interaction = {
            "interaction_id": f"{facts['page_key']}-api-call-2",
            "condition": None,
            "state": None,
            "trigger": {
                "fact_ids": [],
                "inference_basis": [requirement["requirement_id"]],
            },
            "behavior": {
                "fact_ids": [],
                "inference_basis": [requirement["requirement_id"]],
                "kind": "api_call",
                "api_contract_id": second["api_contract_id"],
            },
            "result": None,
            "component_bindings": {
                "condition_candidate_ids": [],
                "state_candidate_ids": [],
                "trigger_candidate_ids": [candidate_id],
                "behavior_candidate_ids": [candidate_id],
                "result_candidate_ids": [],
            },
        }
        facts["interaction_graph"]["interactions"].append(interaction)
        self.add_api_continuations(facts, interaction)
        return self.close_result_outcomes(facts)

    def record_design_a_with_two_contracts(
        self, mutate
    ) -> tuple[
        subprocess.CompletedProcess[str],
        "ComponentDesignV4CliTest",
        dict,
        list[dict],
    ]:
        nested = ComponentDesignV4CliTest(
            methodName="test_begin_creates_page_fact_work_items_before_group_abstraction"
        )
        nested.setUp()
        try:
            nested.bundle_path = nested.build_source_bundle(
                design_a_interaction_override=(
                    "Selecting the offer navigates to Design B. API: GET /offers"
                )
            )
            begun = nested.begin()
            assert begun.returncode == 0, begun.stdout + begun.stderr
            pages = json.loads(begun.stdout)["pages"]
            design_a = next(
                page for page in pages if page["member_title"] == "Design A"
            )
            facts = nested.bind_two_api_contracts(nested.valid_page_facts(design_a))
            sealed = nested.acquire_page_contracts(design_a, facts)
            assert sealed is None, sealed.stdout + sealed.stderr
            mutate(facts)
            return (
                nested.record_page_draft(design_a, facts, acquire_contracts=False),
                nested,
                design_a,
                pages,
            )
        except BaseException:
            nested.tearDown()
            raise

    def test_page_api_contract_order_is_normalized_to_sealed_artifacts(self) -> None:
        def reverse_declared(facts: dict) -> None:
            facts["api_contracts"].reverse()

        drafted, nested, design_a, pages = self.record_design_a_with_two_contracts(
            reverse_declared
        )
        try:
            self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
            page_key = design_a["page_key"]
            for facts_name in (f"{page_key}.draft.json",):
                frozen = read_json(
                    nested.stage_dir / "page-component-facts" / facts_name
                )
                self.assertEqual(
                    [item["api_contract_id"] for item in frozen["api_contracts"]],
                    [f"{page_key}-api", f"{page_key}-api-2"],
                )
            reviewed = nested.record_page_review(design_a, nested.page_review(design_a))
            self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
            frozen = read_json(
                nested.stage_dir / "page-component-facts" / f"{page_key}.json"
            )
            self.assertEqual(
                [item["api_contract_id"] for item in frozen["api_contracts"]],
                [f"{page_key}-api", f"{page_key}-api-2"],
            )
            for page in pages:
                if page["member_title"] == "Design A":
                    continue
                recorded = nested.record_page(page, nested.valid_page_facts(page))
                self.assertEqual(
                    recorded.returncode, 0, recorded.stdout + recorded.stderr
                )
            recorded = nested.record_abstraction(nested.valid_abstraction_plan())
            self.assertEqual(
                recorded.returncode, 0, recorded.stdout + recorded.stderr
            )
            verified = nested.verify()
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            lock = read_json(nested.stage_dir / "component-lock.json")
            self.assertEqual(
                [
                    contract["api_contract_id"]
                    for contract in lock["api_contracts"]
                    if contract["page_key"] == page_key
                ],
                [f"{page_key}-api", f"{page_key}-api-2"],
            )
        finally:
            nested.tearDown()

    def test_page_api_contract_identity_rejects_duplicate_missing_and_changed(self) -> None:
        def declare_duplicate(facts: dict) -> None:
            first = facts["api_contracts"][0]
            facts["api_contracts"] = [first, json.loads(json.dumps(first))]

        drafted, nested, _design_a, _pages = self.record_design_a_with_two_contracts(
            declare_duplicate
        )
        nested.tearDown()
        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn(
            "page API contracts must exactly equal the separately sealed Apifox artifacts",
            drafted.stderr,
        )
        self.assertIn("duplicates=[", drafted.stderr)

        def declare_missing(facts: dict) -> None:
            facts["api_contracts"].pop()

        drafted, nested, _design_a, _pages = self.record_design_a_with_two_contracts(
            declare_missing
        )
        nested.tearDown()
        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn(
            "page API contracts must exactly equal the separately sealed Apifox artifacts",
            drafted.stderr,
        )
        self.assertIn("missing=[", drafted.stderr)

        def declare_unexpected(facts: dict) -> None:
            clone = json.loads(json.dumps(facts["api_contracts"][0]))
            clone["api_contract_id"] = "unknown-api-contract"
            facts["api_contracts"].append(clone)

        drafted, nested, _design_a, _pages = self.record_design_a_with_two_contracts(
            declare_unexpected
        )
        nested.tearDown()
        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("unexpected=['unknown-api-contract']", drafted.stderr)

        def change_payload(facts: dict) -> None:
            facts["api_contracts"][1]["normalized"]["method"] = "POST"

        drafted, nested, _design_a, _pages = self.record_design_a_with_two_contracts(
            change_payload
        )
        nested.tearDown()
        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("page API contract payload changed", drafted.stderr)

    def record_page(
        self, page: dict[str, str], facts: dict
    ) -> subprocess.CompletedProcess[str]:
        drafted = self.record_page_draft(page, facts)
        if drafted.returncode != 0:
            return drafted
        return self.record_page_review(page, self.page_review(page))

    def record_page_draft(
        self,
        page: dict[str, str],
        facts: dict,
        *,
        acquire_contracts: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if acquire_contracts:
            acquired = self.acquire_page_contracts(page, facts)
            if acquired is not None:
                return acquired
        facts_path = self.root / f"{page['page_key']}.draft-input.json"
        write_json(facts_path, facts)
        return run_command(
            SCRIPT,
            "record-page-facts",
            "--project-root",
            str(self.project),
            "--page-key",
            page["page_key"],
            "--facts",
            str(facts_path),
        )

    def acquire_page_contracts(
        self, page: dict[str, str], facts: dict
    ) -> subprocess.CompletedProcess[str] | None:
        for index, contract in enumerate(facts["api_contracts"]):
            contract_path = (
                self.root / f"{page['page_key']}.api-contract-{index + 1}.json"
            )
            write_json(contract_path, contract)
            acquired = run_command(
                SCRIPT,
                "record-api-contract",
                "--project-root",
                str(self.project),
                "--page-key",
                page["page_key"],
                "--contract",
                str(contract_path),
            )
            if acquired.returncode != 0:
                return acquired
        return None

    def page_review(self, page: dict[str, str], *, decision: str = "pass") -> dict:
        review = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )
        review["decision"] = decision
        for segment in review["segment_reviews"]:
            segment["all_normative_meanings_extracted"] = True
            segment["facts_atomic"] = True
            segment["fact_kinds_correct"] = True
            segment["same_page_scope_correct"] = True
            segment["component_relation_intents_correct"] = True
            segment["evidence"] = [
                "The exact segment was compared with every linked typed fact and same-page Block."
            ]
            segment["issues"] = []
        cross = review["cross_page_review"]
        cross["candidate_boundaries_complete"] = True
        cross["design_visible_facts_limited_to_visible_semantics"] = True
        cross["all_visible_variation_roles_extracted"] = True
        cross["no_cross_page_semantic_leak"] = True
        cross["no_implementation_content"] = True
        cross["interaction_graph_complete"] = True
        cross["interaction_component_bindings_correct"] = True
        cross["api_contracts_correct"] = True
        cross["evidence"] = [
            "All candidates and facts remain page-local semantic data without implementation content."
        ]
        cross["issues"] = []
        if decision == "revise":
            review["segment_reviews"][0]["facts_atomic"] = False
            review["segment_reviews"][0]["issues"] = [
                "The source segment still combines independent semantic facts."
            ]
        return review

    def record_page_review(
        self, page: dict[str, str], review: dict
    ) -> subprocess.CompletedProcess[str]:
        review_path = self.root / f"{page['page_key']}.review.json"
        write_json(review_path, review)
        return run_command(
            SCRIPT,
            "record-page-review",
            "--project-root",
            str(self.project),
            "--page-key",
            page["page_key"],
            "--review",
            str(review_path),
        )

    def seal_all_pages(self) -> list[dict[str, str]]:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in reversed(pages):
            recorded = self.record_page(page, self.valid_page_facts(page))
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        return pages

    def seal_pages_with_design_visible_content(
        self, meanings: list[str]
    ) -> list[dict[str, str]]:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        self.assertEqual(len(pages), len(meanings))
        for page, meaning in zip(pages, meanings, strict=True):
            facts = self.valid_page_facts(page)
            facts["candidates"][1]["facts"].append(
                {
                    "fact_id": f"{page['page_key']}-visible-content",
                    "kind": "responsibility",
                    "meaning": meaning,
                    "evidence_class": "design_visible",
                    "visible_basis": (
                        "The verified content Block visibly owns this content boundary."
                    ),
                    "source_refs": [],
                    "block_refs": [
                        {
                            "design_name": facts["design_names"][0],
                            "block_id": "content",
                        }
                    ],
                }
            )
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        return pages

    def shared_design_visible_plan(self, common_meaning: str) -> dict:
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_ids = {
            item["candidate_id"]
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        }
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-design-visible-content",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "shared-visible-content",
                "rationale": "Every instance independently proves one visible content boundary.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": [
                    "Keep an exactly common visible responsibility local."
                ],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "shared-visible-content",
                "name": "Shared visible content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Own one common visible content boundary.",
                "owns": ["The exact common visible responsibility."],
                "excludes": ["Page-specific behavior, state, and values."],
                "capabilities": [
                    {
                        "capability_id": "visible-content-boundary",
                        "kind": "responsibility",
                        "meaning": common_meaning,
                    }
                ],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        self.reset_candidate_bindings_to_instance_facts(plan, content_ids)
        for instance in plan["component_instances"]:
            if not content_ids.intersection(instance["candidate_ids"]):
                continue
            instance["component_id"] = "shared-visible-content"
            visible_binding = next(
                item
                for item in instance["fact_bindings"]
                if item["fact_id"].endswith("-visible-content")
            )
            visible_binding["target_kind"] = "capability"
            visible_binding["target_id"] = "visible-content-boundary"
        return plan

    def valid_abstraction_plan(self) -> dict:
        template = read_json(self.stage_dir / "abstraction-plan.input.json")
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        shell_candidates = [
            item for item in registry["candidates"] if item["candidate"]["kind"] == "page"
        ]
        content_candidates = [
            item
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        ]
        decisions = [
            {
                "decision_id": "extract-shared-page-shell",
                "kind": "extract-container",
                "candidate_ids": [item["candidate_id"] for item in shell_candidates],
                "target_component_id": "shared-page-shell",
                "rationale": "Both pages use the same shell responsibility and child boundary.",
                "evidence_candidate_ids": [
                    item["candidate_id"] for item in shell_candidates
                ],
                "alternatives_rejected": ["Duplicating the shell would repeat one boundary."],
            }
        ]
        definitions = [
            {
                "component_id": "shared-page-shell",
                "name": "Shared page shell",
                "kind": "page",
                "scope": "shared",
                "reuse_mode": "container",
                "responsibility": "Own a page shell and place page-specific content.",
                "owns": ["The root visual boundary and one content slot."],
                "excludes": ["All page-specific behavior and business data."],
                "capabilities": [],
                "slots": [
                    {
                        "slot_id": "content",
                        "role": "Place a page-specific business component.",
                        "cardinality": "one",
                    }
                ],
                "data_roles": [],
                "action_roles": [],
            }
        ]
        component_for_candidate = {
            item["candidate_id"]: "shared-page-shell" for item in shell_candidates
        }
        semantic_binding_by_fact_id: dict[str, tuple[str, str]] = {}
        for index, item in enumerate(content_candidates, start=1):
            component_id = f"page-content-{index}"
            capabilities = []
            data_roles = []
            action_roles = []
            for fact in item["candidate"]["facts"]:
                if (
                    fact["evidence_class"] != "business_source"
                    or fact["kind"] == "component_relation"
                ):
                    continue
                target_id = f"source-{fact['fact_id']}"
                if fact["kind"] == "data":
                    data_roles.append(
                        {
                            "role_id": target_id,
                            "meaning": fact["meaning"],
                            "required": True,
                        }
                    )
                    semantic_binding_by_fact_id[fact["fact_id"]] = (
                        "data_role",
                        target_id,
                    )
                elif fact["kind"] == "behavior":
                    action_roles.append(
                        {"role_id": target_id, "meaning": fact["meaning"]}
                    )
                    semantic_binding_by_fact_id[fact["fact_id"]] = (
                        "action_role",
                        target_id,
                    )
                else:
                    capabilities.append(
                        {
                            "capability_id": target_id,
                            "kind": fact["kind"],
                            "meaning": fact["meaning"],
                        }
                    )
                    semantic_binding_by_fact_id[fact["fact_id"]] = (
                        "capability",
                        target_id,
                    )
            decisions.append(
                {
                    "decision_id": f"keep-content-{index}-separate",
                    "kind": "keep-separate",
                    "candidate_ids": [item["candidate_id"]],
                    "target_component_id": component_id,
                    "rationale": "The page-specific behavior and data remain independent.",
                    "evidence_candidate_ids": [item["candidate_id"]],
                    "alternatives_rejected": [
                        "Sharing would put one page's behavior into another page."
                    ],
                }
            )
            definitions.append(
                {
                    "component_id": component_id,
                    "name": f"Page content {index}",
                    "kind": "component",
                    "scope": "local",
                    "reuse_mode": "local",
                    "responsibility": "Own one page's business content contract.",
                    "owns": ["This page's semantic facts."],
                    "excludes": ["Other pages' facts."],
                    "capabilities": capabilities,
                    "slots": [],
                    "data_roles": data_roles,
                    "action_roles": action_roles,
                }
            )
            component_for_candidate[item["candidate_id"]] = component_id
        instances = []
        for item in registry["candidates"]:
            candidate = item["candidate"]
            instances.append(
                {
                    "instance_id": f"instance-{item['candidate_id']}",
                    "component_id": component_for_candidate[item["candidate_id"]],
                    "page_key": item["page_key"],
                    "member_title": item["member_title"],
                    "candidate_ids": [item["candidate_id"]],
                    "fact_bindings": [
                        {
                            "fact_id": fact["fact_id"],
                            "target_kind": semantic_binding_by_fact_id.get(
                                fact["fact_id"], ("instance_fact", fact["kind"])
                            )[0],
                            "target_id": semantic_binding_by_fact_id.get(
                                fact["fact_id"], ("instance_fact", fact["kind"])
                            )[1],
                        }
                        for fact in candidate["facts"]
                    ],
                }
            )
        return {
            **template,
            "decisions": decisions,
            "component_definitions": definitions,
            "component_instances": instances,
        }

    def reset_candidate_bindings_to_instance_facts(
        self, plan: dict, candidate_ids: set[str]
    ) -> None:
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        fact_kinds = {
            fact["fact_id"]: fact["kind"]
            for item in registry["candidates"]
            for fact in item["candidate"]["facts"]
        }
        for instance in plan["component_instances"]:
            if not candidate_ids.intersection(instance["candidate_ids"]):
                continue
            for binding in instance["fact_bindings"]:
                binding.update(
                    {
                        "target_kind": "instance_fact",
                        "target_id": fact_kinds[binding["fact_id"]],
                    }
                )

    def add_presentation_usages(self, plan: dict) -> dict:
        """Resolve every frozen modal requirement to final component usage."""

        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        instance_by_candidate = {
            candidate_id: instance
            for instance in plan["component_instances"]
            for candidate_id in instance["candidate_ids"]
        }
        for page in registry["pages"]:
            for requirement in page["presentation_requirements"]:
                source_ref = requirement["source_ref"]
                matching_fact_ids: list[str] = []
                matching_candidates: list[str] = []
                for item in registry["candidates"]:
                    if item["page_key"] != page["page_key"]:
                        continue
                    candidate_matches = [
                        fact["fact_id"]
                        for fact in item["candidate"]["facts"]
                        if any(
                            ref["clause_id"] == source_ref["clause_id"]
                            and ref["source_sha256"] == source_ref["source_sha256"]
                            and ref["start"] <= source_ref["start"]
                            and ref["end"] >= source_ref["end"]
                            for ref in fact["source_refs"]
                        )
                    ]
                    if candidate_matches:
                        matching_candidates.append(item["candidate_id"])
                        matching_fact_ids.extend(candidate_matches)
                source_instance = instance_by_candidate[matching_candidates[0]]
                target_page = next(
                    item
                    for item in registry["pages"]
                    if item["page_key"] == requirement["target_page_key"]
                )
                target_instance = instance_by_candidate[
                    target_page["root_candidate_ids"][0]
                ]
                evidence = {
                    "presentation_requirement_id": requirement[
                        "presentation_requirement_id"
                    ],
                    "source_page_key": page["page_key"],
                    "source_member_title": page["member_title"],
                    "host_instance_id": source_instance["instance_id"],
                    "source_fact_ids": matching_fact_ids,
                    "target_page_key": requirement["target_page_key"],
                    "target_member_title": requirement["target_member_title"],
                    "target_instance_id": target_instance["instance_id"],
                    "target_component_id": target_instance["component_id"],
                    "presentation_mode": requirement["relation_kind"],
                }
                plan["presentation_usages"].append(
                    {
                        "usage_id": "usage-" + canonical_digest(evidence)[:20],
                        **evidence,
                    }
                )
        return plan

    def record_abstraction(self, plan: dict) -> subprocess.CompletedProcess[str]:
        plan_path = self.root / "abstraction-plan.json"
        write_json(plan_path, plan)
        return run_command(
            SCRIPT,
            "record-abstraction",
            "--project-root",
            str(self.project),
            "--plan",
            str(plan_path),
        )

    def source_declared_single_container_plan(self) -> dict:
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        source_entry = next(
            item
            for item in registry["candidates"]
            if item["member_title"] == "Designless Context"
        )
        candidate_id = source_entry["candidate_id"]
        decision = next(
            item for item in plan["decisions"] if candidate_id in item["candidate_ids"]
        )
        previous_component_id = decision["target_component_id"]
        decision.update(
            {
                "decision_id": "extract-source-declared-container",
                "kind": "extract-container",
                "candidate_ids": [candidate_id],
                "target_component_id": "source-declared-container",
                "rationale": "The source-only row explicitly declares this reusable container boundary.",
                "evidence_candidate_ids": [candidate_id],
                "alternatives_rejected": [
                    "Keeping an explicitly shared source contract page-local."
                ],
            }
        )
        definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == previous_component_id
        )
        definition.update(
            {
                "component_id": "source-declared-container",
                "name": "Source declared container",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "container",
                "responsibility": "Provide one reusable outer surface for caller-owned content.",
                "owns": ["The reusable outer boundary and content placement."],
                "excludes": ["Caller-owned business data and behavior."],
                "capabilities": [],
                "slots": [
                    {
                        "slot_id": "content",
                        "role": "Place caller-owned business content.",
                        "cardinality": "one",
                    }
                ],
                "data_roles": [],
                "action_roles": [],
            }
        )
        instance = next(
            item
            for item in plan["component_instances"]
            if candidate_id in item["candidate_ids"]
        )
        self.reset_candidate_bindings_to_instance_facts(plan, {candidate_id})
        instance["component_id"] = "source-declared-container"
        return plan

    def verify(self) -> subprocess.CompletedProcess[str]:
        return run_command(
            SCRIPT,
            "verify",
            "--project-root",
            str(self.project),
        )

    def test_begin_creates_page_fact_work_items_before_group_abstraction(self) -> None:
        result = self.begin()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "collecting_page_facts")
        self.assertEqual(
            [item["member_title"] for item in payload["pages"]],
            ["Design A", "Design B"],
        )
        snapshot = read_json(
            self.stage_dir / "project-component-catalog.snapshot.json"
        )
        self.assertEqual(snapshot["schema"], "icp.component-design.project-catalog.v1")
        self.assertEqual(snapshot["components"], [])
        for page in payload["pages"]:
            template = read_json(Path(page["input_path"]))
            self.assertEqual(template["schema"], "icp.component-design.page-facts.v4")
            self.assertEqual(template["page_key"], page["page_key"])
            self.assertEqual(template["member_title"], page["member_title"])
            self.assertTrue(template["source_coverage"])
            self.assertEqual(template["candidates"], [])
            self.assertEqual(template["design_compositions"], [])
            for clause in template["source_coverage"]:
                self.assertEqual(clause["segments"], [])
        self.assertFalse((self.stage_dir / "business-rules.input.json").exists())

    def test_begin_freezes_a_complete_input_derived_component_stage_checklist(self) -> None:
        result = self.begin()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pages = json.loads(result.stdout)["pages"]

        checklist = read_json(self.stage_dir / "checklist.json")
        node_ids = [item["node_id"] for item in checklist["nodes"]]
        expected = ["stage.begin"]
        for page in pages:
            page_key = page["page_key"]
            page_input = read_json(Path(page["input_path"]))
            if page_input["api_requirements"]:
                expected.append(f"page:{page_key}.api-contracts")
            expected.extend(
                [
                    f"page:{page_key}.facts",
                    f"page:{page_key}.review",
                ]
            )
        expected.extend(["group.abstraction", "stage.verify"])

        self.assertEqual(checklist["stage"], "component-design")
        self.assertEqual(node_ids, expected)
        self.assertEqual(checklist["nodes"][0]["status"], "completed")
        self.assertTrue(
            all(item["status"] == "pending" for item in checklist["nodes"][1:])
        )

    def test_iole_handoff_preserves_declared_columns_and_ignores_unowned_columns(self) -> None:
        raw_path = self.root / "raw-rows.json"
        analysis_path = self.root / "source-analysis.json"
        catalog_path = self.root / "title-catalog.json"
        review_path = self.root / "source-closure-review.json"
        raw_rows = read_json(raw_path)
        raw_rows["Design A"]["未映射业务列"] = "  preserve this complete value\n"
        raw_rows["Design A"]["未映射空列"] = ""
        raw_rows["Design B"]["未映射业务列"] = "second-row-value"
        raw_rows["Design B"]["未映射空列"] = ""
        raw_rows["Design B"]["frontend status"] = ""
        write_json(raw_path, raw_rows)
        analysis = read_json(analysis_path)
        analysis["rows"][1]["change_scope"] = "context"
        write_json(analysis_path, analysis)
        catalog = read_json(catalog_path)
        review = {
            "kind": "iole.source-closure-review.v1",
            "schema_version": 1,
            "analysis_sha256": canonical_digest(analysis),
            "title_catalog_digest": catalog["catalog_digest"],
            "decision": "pass",
            "field_reviews": [
                {
                    "title": row["title"],
                    "column": field["column"],
                    "source_sha256": field["source_sha256"],
                    "all_dependencies_identified": True,
                    "reference_targets_correct": True,
                    "dismissals_correct": True,
                    "evidence": ["Complete source field checked against the title catalog."],
                    "issues": [],
                }
                for row in analysis["rows"]
                for field in row["fields"]
            ],
            "cross_review": {
                "every_business_field_reviewed": True,
                "no_unresolved_reference": True,
                "no_ambiguous_target": True,
                "evidence": ["Every analyzed source field is represented once."],
                "issues": [],
            },
        }
        write_json(review_path, review)

        rebuilt = run_command(
            IOLE_SCRIPT,
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
        )
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stdout + rebuilt.stderr)
        self.bundle_path.write_text(rebuilt.stdout, encoding="utf-8")

        bundle = json.loads(rebuilt.stdout)
        expected_columns = [
            "标题",
            "Route",
            "设计稿地址",
            "UI补充描述",
            "交互描述",
            "接口描述",
            "UT",
            "IT",
            "E2E",
        ]
        self.assertEqual(bundle["row_data_columns"], expected_columns)
        by_title = {member["title"]: member for member in bundle["members"]}
        for title, raw_row in raw_rows.items():
            expected_row_data = {
                column: None if value == "" else value
                for column, value in raw_row.items()
                if column in expected_columns
            }
            self.assertIn("row_data", by_title[title])
            self.assertEqual(list(by_title[title]["row_data"]), expected_columns)
            self.assertEqual(by_title[title]["row_data"], expected_row_data)
            source_contract = by_title[title]["source_contract"]
            self.assertEqual(
                source_contract["route"],
                None if raw_row["Route"] == "" else raw_row["Route"],
            )
            self.assertEqual(
                source_contract["design_ref"],
                None
                if raw_row["设计稿地址"] == ""
                else raw_row["设计稿地址"],
            )
            self.assertEqual(
                source_contract["interaction"],
                None if raw_row["交互描述"] == "" else raw_row["交互描述"],
            )
            self.assertEqual(
                [section["value"] for section in source_contract["requirement_sections"]],
                [
                    None if raw_row[column] == "" else raw_row[column]
                    for column in ("UI补充描述", "交互描述", "接口描述")
                ],
            )
            self.assertEqual(
                [section["value"] for section in source_contract["acceptance_sections"]],
                [
                    None if raw_row[column] == "" else raw_row[column]
                    for column in ("UT", "IT", "E2E")
                ],
            )
            self.assertEqual(
                by_title[title]["queue_status"],
                None
                if raw_row["frontend status"] == ""
                else raw_row["frontend status"],
            )

        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        frozen_bundle = read_json(self.project / ".icp" / "source" / "source-bundle.json")
        frozen_by_title = {
            member["title"]: member for member in frozen_bundle["members"]
        }
        for title, raw_row in raw_rows.items():
            self.assertEqual(
                frozen_by_title[title]["row_data"],
                {
                    column: None if value == "" else value
                    for column, value in raw_row.items()
                    if column in expected_columns
                },
            )

    def begin_on_fresh_project(
        self, bundle: dict
    ) -> tuple[subprocess.CompletedProcess[str], "ComponentDesignV4CliTest"]:
        """Run `begin` against an edited bundle on an untouched copy of the project."""

        nested = ComponentDesignV4CliTest(
            methodName="test_begin_creates_page_fact_work_items_before_group_abstraction"
        )
        nested.setUp()
        write_json(nested.bundle_path, bundle)
        return nested.begin(), nested

    def test_row_data_key_order_is_not_a_source_contract(self) -> None:
        bundle = read_json(self.bundle_path)
        original_rows = {
            member["title"]: dict(member["row_data"]) for member in bundle["members"]
        }
        for member in bundle["members"]:
            member["row_data"] = dict(reversed(list(member["row_data"].items())))
        self.assertNotEqual(
            list(next(m for m in bundle["members"] if m["title"] == "Design A")["row_data"]),
            bundle["row_data_columns"],
        )
        refresh_iole_digests(bundle)

        begun, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
            context = read_json(
                nested.project / ".icp" / "component-design" / "business-context.json"
            )
            for member in context["members"]:
                self.assertEqual(
                    list(member["row_data"]), bundle["row_data_columns"]
                )
                self.assertEqual(member["row_data"], original_rows[member["title"]])
        finally:
            nested.tearDown()

    def test_row_data_rejects_missing_unexpected_and_degraded_values(self) -> None:
        base = read_json(self.bundle_path)

        def design_a(edited: dict) -> dict:
            return next(m for m in edited["members"] if m["title"] == "Design A")

        missing = json.loads(json.dumps(base))
        design_a(missing)["row_data"].pop("UT")
        refresh_iole_digests(missing)
        rejected, _ = self.begin_on_fresh_project(missing)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("row_data must match declared source columns", rejected.stderr)
        self.assertIn("missing=['UT']", rejected.stderr)

        unexpected = json.loads(json.dumps(base))
        design_a(unexpected)["row_data"]["undeclared-column"] = "unexpected"
        refresh_iole_digests(unexpected)
        rejected, _ = self.begin_on_fresh_project(unexpected)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("row_data must match declared source columns", rejected.stderr)
        self.assertIn("unexpected=['undeclared-column']", rejected.stderr)

        empty_string = json.loads(json.dumps(base))
        design_a(empty_string)["row_data"]["UT"] = ""
        refresh_iole_digests(empty_string)
        rejected, _ = self.begin_on_fresh_project(empty_string)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "row_data values must be complete strings or null", rejected.stderr
        )

        lost_null = json.loads(json.dumps(base))
        design_a(lost_null)["row_data"]["UT"] = 5
        refresh_iole_digests(lost_null)
        rejected, _ = self.begin_on_fresh_project(lost_null)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "row_data values must be complete strings or null", rejected.stderr
        )

    def reorder_analysis_fields(self, bundle: dict) -> dict:
        """Reverse each analysis row's field order and keep field reviews consistent."""

        closure = bundle["source_closure"]
        analysis = closure["analysis"]
        review_by_key = {
            (item["title"], item["column"]): item
            for item in closure["review"]["field_reviews"]
        }
        for row in analysis["rows"]:
            row["fields"].reverse()
        closure["review"]["field_reviews"] = [
            review_by_key[(row["title"], field["column"])]
            for row in analysis["rows"]
            for field in row["fields"]
        ]
        return bundle

    def test_analyzed_column_coverage_is_order_independent(self) -> None:
        bundle = self.reorder_analysis_fields(read_json(self.bundle_path))
        first_row = bundle["source_closure"]["analysis"]["rows"][0]
        self.assertNotEqual(
            [field["column"] for field in first_row["fields"]],
            [field["column"] for field in reversed(first_row["fields"])],
        )
        refresh_iole_digests(bundle)

        begun, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
            context = read_json(
                nested.project / ".icp" / "component-design" / "business-context.json"
            )
            frozen_row = next(
                row
                for row in context["source_closure"]["analysis"]["rows"]
                if row["title"] == "Design A"
            )
            self.assertEqual(
                [field["column"] for field in frozen_row["fields"]],
                [field["column"] for field in first_row["fields"]],
            )
        finally:
            nested.tearDown()

    def test_source_contract_values_are_bound_to_their_actual_sheet_columns(self) -> None:
        bundle = read_json(self.bundle_path)
        member = next(item for item in bundle["members"] if item["title"] == "Design A")
        contract = member["source_contract"]
        contract["interaction"] = member["row_data"]["UI补充描述"]
        contract["contract_digest"] = canonical_digest(
            {key: value for key, value in contract.items() if key != "contract_digest"}
        )
        bundle["bundle_digest"] = canonical_digest(
            {key: value for key, value in bundle.items() if key != "bundle_digest"}
        )

        rejected, _nested = self.begin_on_fresh_project(bundle)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("source contract column mismatch", rejected.stderr)

    def test_analyzed_column_rejects_duplicate_missing_and_unexpected_columns(self) -> None:
        base = read_json(self.bundle_path)

        duplicate = self.reorder_analysis_fields(json.loads(json.dumps(base)))
        row = duplicate["source_closure"]["analysis"]["rows"][0]
        row["fields"].append(dict(row["fields"][0]))
        refresh_iole_digests(duplicate)
        rejected, _ = self.begin_on_fresh_project(duplicate)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("IOLE source analysis column mismatch", rejected.stderr)
        self.assertIn(f"duplicates=['{row['fields'][0]['column']}']", rejected.stderr)

        missing = json.loads(json.dumps(base))
        row = missing["source_closure"]["analysis"]["rows"][0]
        dropped = row["fields"].pop()
        reviews = missing["source_closure"]["review"]["field_reviews"]
        reviews.remove(
            next(
                item
                for item in reviews
                if (item["title"], item["column"])
                == (row["title"], dropped["column"])
            )
        )
        refresh_iole_digests(missing)
        rejected, _ = self.begin_on_fresh_project(missing)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "IOLE source analysis does not cover every declared source column",
            rejected.stderr,
        )
        self.assertIn(f"missing=['{dropped['column']}']", rejected.stderr)

        unexpected = json.loads(json.dumps(base))
        row = unexpected["source_closure"]["analysis"]["rows"][0]
        row["fields"].append(
            {
                "column": "undeclared-column",
                "source_sha256": hashlib.sha256(b"").hexdigest(),
                "references": [],
                "dismissals": [],
            }
        )
        refresh_iole_digests(unexpected)
        rejected, _ = self.begin_on_fresh_project(unexpected)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("IOLE source analysis column mismatch", rejected.stderr)
        self.assertIn("undeclared-column", rejected.stderr)

    def test_relation_topology_is_order_independent(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        bundle = read_json(self.bundle_path)
        self.assertEqual(len(bundle["relations"]), 2)
        bundle["relations"].reverse()
        refresh_iole_digests(bundle)

        begun, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
            context = read_json(
                nested.project / ".icp" / "component-design" / "business-context.json"
            )
            self.assertEqual(
                context["relations"],
                [
                    {"from_title": "Design A", "to_title": "Design B"},
                    {"from_title": "Design A", "to_title": "Designless Context"},
                ],
            )
        finally:
            nested.tearDown()

    def test_begin_rejects_a_self_consistent_bundle_that_drops_a_title_mention(self) -> None:
        bundle = read_json(self.bundle_path)
        closure = bundle["source_closure"]
        source_row = next(
            row
            for row in closure["analysis"]["rows"]
            if any(field["references"] for field in row["fields"])
        )
        source_field = next(
            field for field in source_row["fields"] if field["references"]
        )
        removed_reference = source_field["references"].pop(0)
        source_title = source_row["title"]
        target_title = removed_reference["target_title"]
        bundle["relations"] = [
            relation
            for relation in bundle["relations"]
            if (relation["from_title"], relation["to_title"])
            != (source_title, target_title)
        ]
        bundle["members"] = [
            member for member in bundle["members"] if member["title"] != target_title
        ]
        closure["analysis"]["rows"] = [
            row for row in closure["analysis"]["rows"] if row["title"] != target_title
        ]
        closure["review"]["field_reviews"] = [
            review
            for review in closure["review"]["field_reviews"]
            if review["title"] != target_title
        ]
        refresh_iole_digests(bundle)

        rejected, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unresolved title mention", rejected.stderr)
        finally:
            nested.tearDown()

    def test_relation_normalization_does_not_follow_analysis_traversal_order(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        bundle = read_json(self.bundle_path)
        analysis_rows = bundle["source_closure"]["analysis"]["rows"]
        analysis_rows.reverse()
        for row in analysis_rows:
            row["fields"].reverse()
            for field in row["fields"]:
                field["references"].reverse()
        refresh_iole_digests(bundle)

        begun, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
            context = read_json(
                nested.project / ".icp" / "component-design" / "business-context.json"
            )
            self.assertEqual(
                context["relations"],
                sorted(
                    context["relations"],
                    key=lambda item: (item["from_title"], item["to_title"]),
                ),
            )
        finally:
            nested.tearDown()

    def test_relation_topology_rejects_duplicate_missing_and_unexpected_edges(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        base = read_json(self.bundle_path)

        duplicate = json.loads(json.dumps(base))
        duplicate["relations"].append(dict(duplicate["relations"][0]))
        refresh_iole_digests(duplicate)
        rejected, _ = self.begin_on_fresh_project(duplicate)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("duplicate relation", rejected.stderr)

        missing = json.loads(json.dumps(base))
        missing["relations"].pop()
        refresh_iole_digests(missing)
        rejected, _ = self.begin_on_fresh_project(missing)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("IOLE relations do not reach members", rejected.stderr)

        unexpected = json.loads(json.dumps(base))
        unexpected["relations"].append(
            {"from_title": "Design B", "to_title": "Design A"}
        )
        refresh_iole_digests(unexpected)
        rejected, _ = self.begin_on_fresh_project(unexpected)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "IOLE source closure relation projection mismatch", rejected.stderr
        )
        self.assertIn("unexpected=[('Design B', 'Design A')]", rejected.stderr)

    def test_field_review_coverage_is_order_independent(self) -> None:
        bundle = read_json(self.bundle_path)
        reviews = bundle["source_closure"]["review"]["field_reviews"]
        self.assertGreater(len(reviews), 1)
        reviews.reverse()
        refresh_iole_digests(bundle)

        begun, nested = self.begin_on_fresh_project(bundle)
        try:
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        finally:
            nested.tearDown()

    def test_field_review_rejects_duplicate_and_missing_identities(self) -> None:
        base = read_json(self.bundle_path)

        duplicate = json.loads(json.dumps(base))
        reviews = duplicate["source_closure"]["review"]["field_reviews"]
        duplicated = dict(reviews[0])
        dropped = reviews.pop()
        reviews.append(duplicated)
        refresh_iole_digests(duplicate)
        rejected, _ = self.begin_on_fresh_project(duplicate)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "IOLE source field review projection mismatch", rejected.stderr
        )
        self.assertIn("duplicates=[", rejected.stderr)
        self.assertIn(
            f"missing=[('{dropped['title']}', '{dropped['column']}', "
            f"'{dropped['source_sha256']}')]",
            rejected.stderr,
        )

    def record_modal_usage_on(
        self, fx: "ComponentDesignV4CliTest", declared_transform=None
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Seal a modal fixture whose requirement matches two source facts."""

        fx.bundle_path = fx.build_source_bundle(design_a_relation_kind="modal")
        begun = fx.begin()
        assert begun.returncode == 0, begun.stdout + begun.stderr
        pages = json.loads(begun.stdout)["pages"]
        design_a = next(page for page in pages if page["member_title"] == "Design A")
        facts = fx.valid_page_facts(design_a)
        interaction = next(
            clause
            for clause in facts["source_coverage"]
            if clause["clause_id"] == "page:interaction"
        )
        text = interaction["source_text"]
        extra_id = f"{facts['page_key']}-modal-usage-context"
        content = facts["candidates"][1]
        content["facts"].append(
            {
                "fact_id": extra_id,
                "evidence_class": "business_source",
                "kind": "responsibility",
                "meaning": "The modal reference stays inside this page's content semantics.",
                "source_refs": [
                    {
                        "member_title": facts["member_title"],
                        "clause_id": interaction["clause_id"],
                        "source_sha256": interaction["source_sha256"],
                        "start": 0,
                        "end": len(text),
                        "quote": text,
                    }
                ],
                "block_refs": [
                    {"design_name": facts["design_names"][0], "block_id": "content"}
                ],
            }
        )
        interaction["segments"][0]["fact_ids"].append(extra_id)
        recorded = fx.record_page(design_a, facts)
        assert recorded.returncode == 0, recorded.stdout + recorded.stderr
        for page in pages:
            if page["member_title"] == "Design A":
                continue
            recorded = fx.record_page(page, fx.valid_page_facts(page))
            assert recorded.returncode == 0, recorded.stdout + recorded.stderr
        plan = fx.valid_abstraction_plan()
        registry = read_json(fx.stage_dir / "group-candidate-registry.json")
        requirement = next(
            requirement
            for page in registry["pages"]
            if page["member_title"] == "Design A"
            for requirement in page["presentation_requirements"]
        )

        def covers_requirement(source_ref: dict) -> bool:
            return (
                source_ref["clause_id"] == requirement["source_ref"]["clause_id"]
                and source_ref["start"] <= requirement["source_ref"]["start"]
                and source_ref["end"] >= requirement["source_ref"]["end"]
            )

        source_candidate = next(
            item
            for item in registry["candidates"]
            if item["member_title"] == "Design A"
            and any(
                covers_requirement(source_ref)
                for fact in item["candidate"]["facts"]
                for source_ref in fact["source_refs"]
            )
        )
        matching_fact_ids = [
            fact["fact_id"]
            for fact in source_candidate["candidate"]["facts"]
            if any(
                covers_requirement(source_ref)
                for source_ref in fact["source_refs"]
            )
        ]
        assert len(matching_fact_ids) == 3, matching_fact_ids
        source_instance = next(
            item
            for item in plan["component_instances"]
            if source_candidate["candidate_id"] in item["candidate_ids"]
        )
        target_page = next(
            item for item in registry["pages"] if item["member_title"] == "Design B"
        )
        target_instance = next(
            item
            for item in plan["component_instances"]
            if target_page["root_candidate_ids"][0] in item["candidate_ids"]
        )
        usage_evidence = {
            "presentation_requirement_id": requirement["presentation_requirement_id"],
            "source_page_key": COMPONENT_DESIGN.page_key_for("Design A"),
            "source_member_title": "Design A",
            "host_instance_id": source_instance["instance_id"],
            "source_fact_ids": list(matching_fact_ids),
            "target_page_key": requirement["target_page_key"],
            "target_member_title": requirement["target_member_title"],
            "target_instance_id": target_instance["instance_id"],
            "target_component_id": target_instance["component_id"],
            "presentation_mode": "modal",
        }
        declared_usage = dict(usage_evidence)
        if declared_transform is not None:
            declared_usage["source_fact_ids"] = list(
                declared_transform(list(matching_fact_ids))
            )
        plan["presentation_usages"] = [
            {
                "usage_id": "usage-" + canonical_digest(usage_evidence)[:20],
                **declared_usage,
            }
        ]
        return fx.record_abstraction(plan), matching_fact_ids

    def test_presentation_source_fact_coverage_is_order_independent(self) -> None:
        recorded, matching = self.record_modal_usage_on(
            self, declared_transform=lambda ids: list(reversed(ids))
        )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertEqual(len(lock["presentation_usages"]), 1)
        self.assertEqual(
            lock["presentation_usages"][0]["source_fact_ids"], matching
        )

    def test_presentation_source_fact_rejects_duplicate_missing_and_unexpected(self) -> None:
        def run(declared_transform) -> str:
            nested = ComponentDesignV4CliTest(
                methodName="test_begin_creates_page_fact_work_items_before_group_abstraction"
            )
            nested.setUp()
            try:
                recorded, _matching = self.record_modal_usage_on(
                    nested, declared_transform=declared_transform
                )
                return recorded.stderr
            finally:
                nested.tearDown()

        duplicated = run(lambda ids: [ids[0], ids[0]])
        self.assertIn("invalid_contract", duplicated)
        self.assertIn(
            "source_fact_ids must not contain duplicates", duplicated
        )

        missing = run(lambda ids: ids[:1])
        self.assertIn("presentation_usage_invalid", missing)
        self.assertIn("does not bind every exact source fact", missing)
        self.assertIn("missing=[", missing)

        unexpected = run(lambda ids: [*ids, "unexpected-fact"])
        self.assertIn("presentation_usage_invalid", unexpected)
        self.assertIn("unexpected=['unexpected-fact']", unexpected)

    def test_designless_context_with_business_data_gets_a_source_only_work_item(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)

        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        self.assertEqual(
            [item["member_title"] for item in pages],
            ["Design A", "Design B", "Designless Context"],
        )
        source_only = next(
            item for item in pages if item["member_title"] == "Designless Context"
        )
        template = read_json(Path(source_only["input_path"]))
        self.assertEqual(template["design_names"], [])
        self.assertTrue(
            any(
                item["source_text"].strip()
                for item in template["source_coverage"]
                if item["clause_id"].startswith("requirement:")
            )
        )
        design_a = next(item for item in pages if item["member_title"] == "Design A")
        design_a_template = read_json(Path(design_a["input_path"]))
        self.assertIn(
            "Designless Context",
            {
                item["target_member_title"]
                for item in design_a_template["navigation_requirements"]
            },
        )

    def test_modal_reference_becomes_an_exact_page_presentation_requirement(self) -> None:
        self.bundle_path = self.build_source_bundle(design_a_relation_kind="modal")

        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        template = read_json(Path(page["input_path"]))
        interaction = "Help opens Design B as a modal."
        start = interaction.index("Design B")
        evidence = {
            "reference_id": "Design A-交互描述-Design B",
            "relation_kind": "modal",
            "source_column": "交互描述",
            "source_ref": {
                "member_title": "Design A",
                "clause_id": "page:interaction",
                "source_sha256": hashlib.sha256(interaction.encode("utf-8")).hexdigest(),
                "start": start,
                "end": start + len("Design B"),
                "quote": "Design B",
            },
            "target_member_title": "Design B",
            "target_page_key": COMPONENT_DESIGN.page_key_for("Design B"),
        }
        self.assertEqual(
            template["presentation_requirements"],
            [
                {
                    "presentation_requirement_id": (
                        "presentation-" + canonical_digest(evidence)[:20]
                    ),
                    **evidence,
                }
            ],
        )

    def test_abstraction_must_resolve_every_modal_to_final_component_data(self) -> None:
        self.bundle_path = self.build_source_bundle(design_a_relation_kind="modal")
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()

        missing = self.record_abstraction(plan)

        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("presentation_usage_missing", missing.stderr)

        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        requirement = next(
            requirement
            for page in registry["pages"]
            if page["member_title"] == "Design A"
            for requirement in page["presentation_requirements"]
        )
        source_candidate = next(
            item
            for item in registry["candidates"]
            if item["member_title"] == "Design A"
            and any(
                source_ref["clause_id"] == requirement["source_ref"]["clause_id"]
                and source_ref["start"] <= requirement["source_ref"]["start"]
                and source_ref["end"] >= requirement["source_ref"]["end"]
                for fact in item["candidate"]["facts"]
                for source_ref in fact["source_refs"]
            )
        )
        source_fact_ids = [
            fact["fact_id"]
            for fact in source_candidate["candidate"]["facts"]
            if any(
                source_ref["clause_id"] == requirement["source_ref"]["clause_id"]
                and source_ref["start"] <= requirement["source_ref"]["start"]
                and source_ref["end"] >= requirement["source_ref"]["end"]
                for source_ref in fact["source_refs"]
            )
        ]
        source_instance = next(
            item
            for item in plan["component_instances"]
            if source_candidate["candidate_id"] in item["candidate_ids"]
        )
        target_page = next(
            item for item in registry["pages"] if item["member_title"] == "Design B"
        )
        target_root_candidate_id = target_page["root_candidate_ids"][0]
        target_instance = next(
            item
            for item in plan["component_instances"]
            if target_root_candidate_id in item["candidate_ids"]
        )
        usage_evidence = {
            "presentation_requirement_id": requirement["presentation_requirement_id"],
            "source_page_key": requirement["source_ref"]["member_title"]
            and COMPONENT_DESIGN.page_key_for(requirement["source_ref"]["member_title"]),
            "source_member_title": requirement["source_ref"]["member_title"],
            "host_instance_id": source_instance["instance_id"],
            "source_fact_ids": source_fact_ids,
            "target_page_key": requirement["target_page_key"],
            "target_member_title": requirement["target_member_title"],
            "target_instance_id": target_instance["instance_id"],
            "target_component_id": target_instance["component_id"],
            "presentation_mode": "modal",
        }
        plan["presentation_usages"] = [
            {
                "usage_id": "usage-" + canonical_digest(usage_evidence)[:20],
                **usage_evidence,
            }
        ]

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertEqual(lock["presentation_usages"], plan["presentation_usages"])

    def test_lock_source_context_preserves_scope_identity_and_relation_topology(self) -> None:
        self.bundle_path = self.build_source_bundle(
            include_designless_context=True,
            design_b_scope="context",
        )
        self.seal_all_pages()
        self.assertEqual(
            self.record_abstraction(self.valid_abstraction_plan()).returncode, 0
        )

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        context = read_json(self.stage_dir / "business-context.json")
        expected_members = [
            {
                "title": member["title"],
                "page_key": (
                    COMPONENT_DESIGN.page_key_for(member["title"])
                    if COMPONENT_DESIGN.member_requires_semantic_work_item(member)
                    else None
                ),
                "change_scope": member["change_scope"],
                "route": member["route"],
                "design_names": [
                    state["design_name"] for state in member["design_states"]
                ],
                "contract_digest": member["source_contract"]["contract_digest"],
            }
            for member in context["members"]
        ]
        self.assertEqual(
            lock["source_context"],
            {
                "source_kind": context["source_kind"],
                "source_id": context["source_id"],
                "root_title": context["root_title"],
                "members": expected_members,
                "relations": context["relations"],
            },
        )
        scopes = {
            member["title"]: member["change_scope"]
            for member in lock["source_context"]["members"]
        }
        self.assertEqual(scopes["Design A"], "modify")
        self.assertEqual(scopes["Design B"], "context")
        self.assertEqual(scopes["Designless Context"], "context")
        manifest_page_keys = {
            member["page_key"]
            for member in lock["source_context"]["members"]
            if member["page_key"] is not None
        }
        self.assertEqual(manifest_page_keys, {page["page_key"] for page in lock["pages"]})
        self.assertEqual(
            next(
                member["page_key"]
                for member in lock["source_context"]["members"]
                if member["title"] == "Designless Context"
            ),
            COMPONENT_DESIGN.page_key_for("Designless Context"),
        )
        self.assertTrue(
            any(
                instance["member_title"] == "Designless Context"
                for instance in lock["component_instances"]
            )
        )
        block_bindings = read_json(
            self.stage_dir / "block-component-bindings.json"
        )
        self.assertNotIn(
            "Designless Context",
            {item["member_title"] for item in block_bindings["bindings"]},
        )
        self.assertNotIn(
            "Designless Context",
            [member["title"] for member in lock["context_members"]],
        )
        for page in lock["pages"]:
            sealed_page = read_json(
                self.stage_dir / "page-component-facts" / f"{page['page_key']}.json"
            )
            sealed_page.pop("mobile_component_pattern_context")
            self.assertEqual(page, sealed_page)
            self.assertNotIn("change_scope", page)
        for collection in (lock["component_instances"], lock["page_compositions"]):
            self.assertTrue(all("change_scope" not in item for item in collection))
        manifest_text = json.dumps(lock["source_context"], ensure_ascii=False)
        self.assertNotIn("allowed_paths", manifest_text)
        self.assertNotIn("implementation", manifest_text)

    def test_implementation_contract_projects_only_modify_members(self) -> None:
        self.bundle_path = self.build_source_bundle(
            include_designless_context=True,
            design_b_scope="navigate-only",
        )
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        source_members = lock["source_context"]["members"]
        expected_page_keys = [
            member["page_key"]
            for member in source_members
            if member["change_scope"] == "modify"
        ]
        contract = lock["implementation_contract"]

        self.assertEqual(contract["page_keys"], expected_page_keys)
        self.assertEqual(
            [page["page_key"] for page in contract["pages"]],
            expected_page_keys,
        )
        self.assertEqual(
            contract["source_identity"]["members"],
            source_members,
        )
        self.assertEqual(
            {page["page_key"] for page in lock["pages"]},
            {member["page_key"] for member in source_members},
        )

    def test_begin_rejects_a_relation_outside_the_declared_member_graph(self) -> None:
        bundle = read_json(self.bundle_path)
        bundle["relations"].append(
            {"from_title": "Design A", "to_title": "Undeclared Page"}
        )
        bundle["bundle_digest"] = hashlib.sha256(
            COMPONENT_DESIGN.canonical_bytes(
                {key: value for key, value in bundle.items() if key != "bundle_digest"}
            )
        ).hexdigest()
        write_json(self.bundle_path, bundle)

        begun = self.begin()

        self.assertNotEqual(begun.returncode, 0)
        self.assertIn("invalid_iole_input", begun.stderr)

    def test_begin_rejects_a_bundle_without_source_closure_evidence(self) -> None:
        bundle = read_json(self.bundle_path)
        bundle.pop("source_closure")
        bundle["bundle_digest"] = canonical_digest(
            {key: value for key, value in bundle.items() if key != "bundle_digest"}
        )
        write_json(self.bundle_path, bundle)

        begun = self.begin()

        self.assertNotEqual(begun.returncode, 0)
        self.assertIn("source closure", begun.stderr)

    def test_extract_begin_rejects_a_false_source_closure_before_stage_one_work(self) -> None:
        bundle = read_json(self.bundle_path)
        bundle["source_closure"]["review"]["decision"] = "revise"
        refresh_iole_digests(bundle)
        source_path = self.root / "false-closure-bundle.json"
        write_json(source_path, bundle)
        extract_project = self.root / "extract-project"
        extract_project.mkdir()

        begun = run_command(
            STAGE_ROOT.parent / "extract" / "scripts" / "extract.py",
            "begin-run",
            "--project-root",
            str(extract_project),
            "--source-bundle",
            str(source_path),
        )

        self.assertNotEqual(begun.returncode, 0)
        self.assertIn("source closure review did not pass", begun.stderr)
        self.assertFalse((extract_project / ".icp" / "extract" / "run-manifest.json").exists())

    def test_locked_source_context_cannot_be_changed_without_detection(self) -> None:
        self.seal_all_pages()
        self.assertEqual(
            self.record_abstraction(self.valid_abstraction_plan()).returncode, 0
        )
        self.assertEqual(self.verify().returncode, 0)
        lock_path = self.stage_dir / "component-lock.json"
        lock = read_json(lock_path)
        lock["source_context"]["members"][0]["change_scope"] = "context"
        write_json(lock_path, lock)

        repeated = self.verify()

        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("component_design_locked", repeated.stderr)

    def test_record_page_facts_writes_a_reviewable_draft_without_sealing(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]

        recorded = self.record_page_draft(page, self.valid_page_facts(page))

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        payload = json.loads(recorded.stdout)
        self.assertEqual(payload["state"], "collecting_page_facts")
        self.assertEqual(payload["page_status"], "awaiting_page_review")
        self.assertEqual(payload["sealed_pages"], 0)
        self.assertEqual(payload["total_pages"], 2)
        draft = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.draft.json"
        )
        self.assertEqual(draft["member_title"], page["member_title"])
        self.assertTrue(draft["candidates"])
        review_input = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )
        self.assertEqual(review_input["page_key"], page["page_key"])
        self.assertEqual(review_input["decision"], "revise")
        self.assertTrue(review_input["segment_reviews"])
        self.assertFalse(
            (
                self.stage_dir
                / "page-component-facts"
                / f"{page['page_key']}.json"
            ).exists()
        )
        self.assertFalse((self.stage_dir / "group-candidate-registry.json").exists())

    def test_page_review_is_the_only_sealing_path(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]

        for index, page in enumerate(pages, start=1):
            drafted = self.record_page_draft(page, self.valid_page_facts(page))
            self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
            self.assertFalse(
                (
                    self.stage_dir
                    / "page-component-facts"
                    / f"{page['page_key']}.json"
                ).exists()
            )

            reviewed = self.record_page_review(page, self.page_review(page))

            self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
            payload = json.loads(reviewed.stdout)
            self.assertEqual(payload["page_status"], "sealed")
            self.assertEqual(payload["sealed_pages"], index)
            self.assertTrue(
                (
                    self.stage_dir
                    / "page-component-facts"
                    / f"{page['page_key']}.json"
                ).is_file()
            )
            self.assertEqual(
                (self.stage_dir / "group-candidate-registry.json").exists(),
                index == len(pages),
            )

        self.assertEqual(
            json.loads(reviewed.stdout)["state"], "awaiting_group_abstraction"
        )
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        self.assertTrue(
            all(page_entry["page_review_sha256"] for page_entry in registry["pages"])
        )

    def test_stage_writer_lock_serializes_concurrent_page_fact_transactions(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        facts_paths = []
        for page in pages:
            path = self.root / f"{page['page_key']}.concurrent-facts.json"
            facts = self.valid_page_facts(page)
            acquired = self.acquire_page_contracts(page, facts)
            self.assertIsNone(acquired, acquired.stderr if acquired else "")
            write_json(path, facts)
            facts_paths.append(path)

        lock_path = self.stage_dir / ".write.lock"
        lock_path.touch()
        commands = [
            [
                sys.executable,
                str(SCRIPT),
                "record-page-facts",
                "--project-root",
                str(self.project),
                "--page-key",
                page["page_key"],
                "--facts",
                str(path),
                "--lock-timeout-seconds",
                "2",
            ]
            for page, path in zip(pages, facts_paths, strict=True)
        ]
        processes = []
        with lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                processes = [
                    subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    for command in commands
                ]
                time.sleep(0.1)
                self.assertTrue(
                    all(process.poll() is None for process in processes),
                    "every writer must wait before reading the shared state",
                )
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

        results = [process.communicate(timeout=5) for process in processes]
        self.assertTrue(
            all(process.returncode == 0 for process in processes),
            results,
        )
        state = read_json(self.stage_dir / "state.json")
        self.assertTrue(
            all(
                state["pages"][page["page_key"]]["status"]
                == "awaiting_page_review"
                for page in pages
            )
        )

    def test_concurrent_page_reviews_seal_all_pages_and_materialize_one_registry(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        review_paths = []
        for page in pages:
            drafted = self.record_page_draft(page, self.valid_page_facts(page))
            self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
            path = self.root / f"{page['page_key']}.concurrent-review.json"
            write_json(path, self.page_review(page))
            review_paths.append(path)

        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "record-page-review",
                    "--project-root",
                    str(self.project),
                    "--page-key",
                    page["page_key"],
                    "--review",
                    str(path),
                    "--lock-timeout-seconds",
                    "2",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for page, path in zip(pages, review_paths, strict=True)
        ]
        results = [process.communicate(timeout=5) for process in processes]

        self.assertTrue(
            all(process.returncode == 0 for process in processes),
            results,
        )
        state = read_json(self.stage_dir / "state.json")
        self.assertEqual(state["state"], "awaiting_group_abstraction")
        self.assertTrue(
            all(
                state["pages"][page["page_key"]]["status"] == "sealed"
                for page in pages
            )
        )
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        self.assertEqual(len(registry["pages"]), len(pages))
        self.assertEqual(
            state["candidate_registry_sha256"],
            hashlib.sha256(
                (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    def test_stage_writer_lock_times_out_without_mutating_state(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts_path = self.root / "contended-facts.json"
        write_json(facts_path, self.valid_page_facts(page))
        state_path = self.stage_dir / "state.json"
        state_before = state_path.read_bytes()

        lock_path = self.stage_dir / ".write.lock"
        lock_path.touch()
        with lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            result = run_command(
                SCRIPT,
                "record-page-facts",
                "--project-root",
                str(self.project),
                "--page-key",
                page["page_key"],
                "--facts",
                str(facts_path),
                "--lock-timeout-seconds",
                "0.05",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"error": "stage_busy"', result.stderr)
        self.assertEqual(state_path.read_bytes(), state_before)

    def test_a_sealed_page_review_is_hash_bound_before_abstraction(self) -> None:
        self.seal_all_pages()
        page = read_json(self.stage_dir / "group-candidate-registry.json")["pages"][0]
        review_path = (
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.json"
        )
        review = read_json(review_path)
        review["cross_page_review"]["evidence"].append(
            "This unrecorded mutation must invalidate the sealed evidence."
        )
        write_json(review_path, review)

        recorded = self.record_abstraction(self.valid_abstraction_plan())

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("stage_drift", recorded.stderr)

    def test_page_review_rejects_a_false_pass_and_placeholder_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        drafted = self.record_page_draft(page, self.valid_page_facts(page))
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        false_pass = self.page_review(page)
        false_pass["segment_reviews"][0]["facts_atomic"] = False
        rejected = self.record_page_review(page, false_pass)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("false_page_review_pass", rejected.stderr)
        self.assertFalse(
            (
                self.stage_dir
                / "page-component-facts"
                / f"{page['page_key']}.json"
            ).exists()
        )

        placeholder = self.page_review(page)
        placeholder["segment_reviews"][0]["evidence"] = [
            "TODO: rubber-stamp this segment."
        ]
        rejected = self.record_page_review(page, placeholder)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("placeholder_page_review_evidence", rejected.stderr)

    def test_page_review_requires_all_visible_variation_roles_to_be_extracted(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        self.add_design_visible_fact(facts, kind="data")
        drafted = self.record_page_draft(page, facts)
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        review = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )
        self.assertFalse(
            review["cross_page_review"]["all_visible_variation_roles_extracted"]
        )
        review = self.page_review(page)
        review["cross_page_review"]["all_visible_variation_roles_extracted"] = False
        rejected = self.record_page_review(page, review)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("false_page_review_pass", rejected.stderr)

    def test_revised_or_stale_page_review_cannot_seal_the_wrong_draft(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        drafted = self.record_page_draft(page, facts)
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        stale_review = self.page_review(page)

        revised = self.record_page_review(
            page, self.page_review(page, decision="revise")
        )
        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        self.assertEqual(json.loads(revised.stdout)["page_status"], "revision_required")
        self.assertTrue(
            (
                self.stage_dir
                / "page-component-facts"
                / f"{page['page_key']}.review-repair.json"
            ).is_file()
        )

        facts["candidates"][1]["facts"][0]["meaning"] = (
            "Expose the exact page route as page-local data."
        )
        redrafted = self.record_page_draft(page, facts)
        self.assertEqual(redrafted.returncode, 0, redrafted.stdout + redrafted.stderr)

        rejected = self.record_page_review(page, stale_review)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("review_input_mismatch", rejected.stderr)
        sealed = self.record_page_review(page, self.page_review(page))
        self.assertEqual(sealed.returncode, 0, sealed.stdout + sealed.stderr)
        self.assertEqual(json.loads(sealed.stdout)["page_status"], "sealed")

    def test_one_source_span_can_review_multiple_atomic_typed_facts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        interaction_coverage = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        segment = interaction_coverage["segments"][0]
        original_fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["fact_id"] == segment["fact_ids"][0]
        )
        state_fact = {
            **original_fact,
            "fact_id": f"{page['page_key']}-interaction-result-state",
            "kind": "state",
            "meaning": "The destination page becomes the visible state after selection.",
        }
        facts["candidates"][1]["facts"].append(state_fact)
        segment["fact_ids"].append(state_fact["fact_id"])
        self.with_interaction_items(facts)

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        review_input = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )
        interaction_review = next(
            item
            for item in review_input["segment_reviews"]
            if item["clause_id"] == "page:interaction"
        )
        self.assertEqual(
            [item["kind"] for item in interaction_review["linked_facts"]],
            ["behavior", "result", "state"],
        )
        sealed = self.record_page_review(page, self.page_review(page))
        self.assertEqual(sealed.returncode, 0, sealed.stdout + sealed.stderr)

    def test_interaction_item_keeps_four_nullable_fields_and_maps_only_non_null_data(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        interaction_fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["kind"] == "behavior"
            and any(
                source_ref["clause_id"] == "page:interaction"
                for source_ref in fact["source_refs"]
            )
        )
        facts["interaction_items"] = [
            {
                "item_id": f"{page['page_key']}-interaction-behavior-1",
                "source_ref": interaction_fact["source_refs"][0],
                "condition": None,
                "state": None,
                "trigger": None,
                "behavior": {
                    "fact_id": interaction_fact["fact_id"],
                    "meaning": interaction_fact["meaning"],
                },
                "result": None,
            },
            *[
                item
                for item in facts["interaction_items"]
                if item["result"] is not None
            ],
        ]

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        normalized = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.draft.json"
        )
        item = normalized["interaction_items"][0]
        self.assertIsNone(item["condition"])
        self.assertIsNone(item["state"])
        self.assertIsNone(item["trigger"])
        self.assertIsNone(item["result"])
        self.assertEqual(item["behavior"]["fact_id"], interaction_fact["fact_id"])

    def test_page_facts_accepts_a_component_bound_interaction_graph(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        interaction_item = next(
            item for item in facts["interaction_items"] if item["behavior"] is not None
        )
        behavior_fact_id = interaction_item["behavior"]["fact_id"]
        api_contract_id = facts["api_contracts"][0]["api_contract_id"]
        content_candidate_id = next(
            candidate["candidate_id"]
            for candidate in facts["candidates"]
            if any(
                fact["fact_id"] == behavior_fact_id for fact in candidate["facts"]
            )
        )
        facts["interaction_graph"] = {
            "schema": "icp.component-design.interaction-graph.v2",
            "interactions": [
                {
                    "interaction_id": f"{facts['page_key']}-submit",
                    "condition": None,
                    "state": None,
                    "trigger": {
                        "fact_ids": [],
                        "inference_basis": [facts["api_requirements"][0]["requirement_id"]],
                    },
                    "behavior": {
                        "fact_ids": [behavior_fact_id],
                        "inference_basis": [],
                        "kind": "api_call",
                        "api_contract_id": api_contract_id,
                    },
                    "result": None,
                    "component_bindings": {
                        "condition_candidate_ids": [],
                        "state_candidate_ids": [],
                        "trigger_candidate_ids": [content_candidate_id],
                        "behavior_candidate_ids": [content_candidate_id],
                        "result_candidate_ids": [],
                    },
                }
            ],
            "edges": [],
            "terminal_outcomes": [],
        }
        self.add_api_continuations(
            facts, facts["interaction_graph"]["interactions"][0]
        )
        self.close_result_outcomes(facts)

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        normalized = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.draft.json"
        )
        self.assertEqual(
            normalized["interaction_graph"], facts["interaction_graph"]
        )

    def test_non_empty_interaction_description_requires_complete_interaction_graph(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["interaction_graph"] = {
            "schema": "icp.component-design.interaction-graph.v2",
            "interactions": [],
            "edges": [],
            "terminal_outcomes": [],
        }

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("interaction_graph_coverage", drafted.stderr)

    def test_interface_description_is_projected_as_an_api_contract_requirement(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        template = read_json(Path(page["input_path"]))

        self.assertEqual(len(template["api_requirements"]), 1)
        requirement = template["api_requirements"][0]
        self.assertEqual(requirement["source_kind"], "interface_description")
        self.assertEqual(
            requirement["source_ref"]["quote"],
            "Read the amount from the loan detail response.",
        )
        self.assertIsNone(requirement["locator"])
        self.assertEqual(template["api_contracts"], [])

    def test_api_directive_in_interaction_description_is_a_technical_locator(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_interaction_override="点击刷新，API:GET /loans，然后显示 Design B 列表。",
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        template = read_json(Path(page["input_path"]))

        self.assertEqual(len(template["api_requirements"]), 1)
        requirement = template["api_requirements"][0]
        self.assertEqual(requirement["source_kind"], "api_directive")
        self.assertEqual(requirement["locator"], "GET /loans")
        self.assertEqual(requirement["source_ref"]["quote"], "API:GET /loans")

    def test_api_directive_stops_before_quotes_and_following_prose(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_interaction_override=(
                "页面加载，API：/auth/otp-requests“，完成后 "
                "API: /auth/otp-requests请求成功后，校验 API:/auth/sessions“，"
                "上传 API:/feedback/images\"上传，首页 API:/offers”接口，随后显示 Design B。"
            ),
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        template = read_json(Path(page["input_path"]))

        self.assertEqual(
            [item["locator"] for item in template["api_requirements"]],
            [
                "/auth/otp-requests",
                "/auth/otp-requests",
                "/auth/sessions",
                "/feedback/images",
                "/offers",
            ],
        )
        self.assertEqual(
            [item["source_ref"]["quote"] for item in template["api_requirements"]],
            [
                "API：/auth/otp-requests",
                "API: /auth/otp-requests",
                "API:/auth/sessions",
                "API:/feedback/images",
                "API:/offers",
            ],
        )

    def test_empty_interface_sources_create_no_api_requirement_or_contract(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_interaction_override="点击刷新，然后显示 Design B 列表。",
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        template = read_json(Path(page["input_path"]))

        self.assertEqual(template["api_requirements"], [])
        self.assertEqual(template["api_contracts"], [])

    def test_natural_language_after_api_colon_is_not_a_technical_locator(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_interaction_override=(
                "不调用外部 API：请稍后处理，随后显示 Design B 列表。"
            ),
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        template = read_json(Path(page["input_path"]))

        self.assertEqual(template["api_requirements"], [])

    def test_api_directive_must_match_the_frozen_endpoint_shape(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_interaction_override=(
                "点击刷新，API:GET /loans，然后显示 Design B 列表。"
            ),
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        contract = facts["api_contracts"][0]
        contract["locator"] = "POST /audit"
        contract["normalized"]["method"] = "POST"
        contract["normalized"]["path"] = "/audit"

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_locator_mismatch", drafted.stderr)

    def test_page_facts_cannot_author_an_unsealed_apifox_contract(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))

        drafted = self.record_page_draft(
            page, facts, acquire_contracts=False
        )

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_acquisition_missing", drafted.stderr)

    def test_apifox_acquisition_rejects_a_false_raw_hash(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        facts["api_contracts"][0]["apifox"]["raw_sha256"] = "0" * 64

        acquired = self.acquire_page_contracts(page, facts)

        self.assertIsNotNone(acquired)
        self.assertNotEqual(acquired.returncode, 0)
        self.assertIn("invalid_api_acquisition", acquired.stderr)

    def test_every_api_requirement_needs_one_acquired_contract(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        )
        api_interaction["behavior"]["kind"] = "local"
        api_interaction["behavior"]["api_contract_id"] = None
        facts["api_contracts"] = []

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_contract_coverage", drafted.stderr)

    def test_every_acquired_contract_must_drive_an_api_interaction(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        )
        api_interaction["behavior"]["kind"] = "local"
        api_interaction["behavior"]["api_contract_id"] = None

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_interaction_coverage", drafted.stderr)

    def test_api_call_interaction_requires_a_frozen_apifox_contract(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
        )
        api_interaction["behavior"]["kind"] = "api_call"
        api_interaction["behavior"]["api_contract_id"] = "loan-detail"

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_contract_missing", drafted.stderr)

    def test_api_call_interaction_requires_a_trigger_in_the_same_node(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        )
        api_interaction["trigger"] = None
        api_interaction["component_bindings"]["trigger_candidate_ids"] = []

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_interaction_trigger_missing", drafted.stderr)

    def test_api_call_requires_success_and_failure_continuations(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        )
        facts["interaction_graph"]["edges"] = [
            edge
            for edge in facts["interaction_graph"]["edges"]
            if edge["from_interaction_id"] != api_interaction["interaction_id"]
        ]

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("api_interaction_outcome_missing", drafted.stderr)

    def test_api_outcome_may_be_explicitly_terminal_with_a_reason(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        api_interaction = next(
            interaction
            for interaction in facts["interaction_graph"]["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        )
        facts["interaction_graph"]["edges"] = [
            edge
            for edge in facts["interaction_graph"]["edges"]
            if not (
                edge["from_interaction_id"] == api_interaction["interaction_id"]
                and edge["outcome"] == "failure"
            )
        ]
        facts["interaction_graph"]["terminal_outcomes"].append(
            {
                "interaction_id": api_interaction["interaction_id"],
                "outcome": "failure",
                "inference_basis": ["failure is intentionally terminal"],
            }
        )

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

    def test_trigger_only_interaction_is_not_a_causal_unit(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        candidate_id = facts["candidates"][0]["candidate_id"]
        facts["interaction_graph"]["interactions"].append(
            {
                "interaction_id": f"{facts['page_key']}-orphan-trigger",
                "condition": None,
                "state": None,
                "trigger": {
                    "fact_ids": [],
                    "inference_basis": ["orphan test trigger"],
                },
                "behavior": None,
                "result": None,
                "component_bindings": {
                    "condition_candidate_ids": [],
                    "state_candidate_ids": [],
                    "trigger_candidate_ids": [candidate_id],
                    "behavior_candidate_ids": [],
                    "result_candidate_ids": [],
                },
            }
        )

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("interaction_causality_missing", drafted.stderr)

    def test_behavior_only_interaction_is_not_a_causal_unit(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        candidate_id = facts["candidates"][0]["candidate_id"]
        facts["interaction_graph"]["interactions"].append(
            {
                "interaction_id": f"{facts['page_key']}-orphan-behavior",
                "condition": None,
                "state": None,
                "trigger": None,
                "behavior": {
                    "fact_ids": [],
                    "inference_basis": ["orphan test behavior"],
                    "kind": "local",
                    "api_contract_id": None,
                },
                "result": None,
                "component_bindings": {
                    "condition_candidate_ids": [],
                    "state_candidate_ids": [],
                    "trigger_candidate_ids": [],
                    "behavior_candidate_ids": [candidate_id],
                    "result_candidate_ids": [],
                },
            }
        )

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("interaction_causality_missing", drafted.stderr)

    def test_graph_edge_must_start_from_a_behavior_node(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        candidate_id = facts["candidates"][0]["candidate_id"]
        source_id = f"{facts['page_key']}-state-source"
        facts["interaction_graph"]["interactions"].append(
            {
                "interaction_id": source_id,
                "condition": None,
                "state": {
                    "fact_ids": [],
                    "inference_basis": ["state-only source"],
                },
                "trigger": None,
                "behavior": None,
                "result": None,
                "component_bindings": {
                    "condition_candidate_ids": [],
                    "state_candidate_ids": [candidate_id],
                    "trigger_candidate_ids": [],
                    "behavior_candidate_ids": [],
                    "result_candidate_ids": [],
                },
            }
        )
        target_id = facts["interaction_graph"]["interactions"][0]["interaction_id"]
        facts["interaction_graph"]["edges"].append(
            {
                "from_interaction_id": source_id,
                "outcome": "next",
                "target": {"kind": "interaction", "to_interaction_id": target_id},
            }
        )

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("invalid_interaction_edge_causality", drafted.stderr)

    def test_result_is_a_first_class_fact_graph_field_and_locked_outcome(self) -> None:
        self.bundle_path = self.build_source_bundle(design_a_api_override="")
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        page_a = next(item for item in pages if item["member_title"] == "Design A")
        page_b = next(item for item in pages if item["member_title"] == "Design B")
        page_key = page_a["page_key"]
        facts = self.valid_page_facts(page_a)
        result_fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["kind"] == "result"
        )
        navigation = facts["navigation_requirements"][0]
        self.assertEqual(navigation["relation_kind"], "navigation")
        interaction = facts["interaction_graph"]["interactions"][0]
        interaction["behavior"]["kind"] = "navigate"
        navigation_edge = next(
            edge
            for edge in facts["interaction_graph"]["edges"]
            if edge["target"]["kind"] == "navigation"
        )
        self.assertEqual(
            navigation_edge["target"]["requirement_ids"],
            [navigation["navigation_requirement_id"]],
        )

        drafted = self.record_page_draft(page_a, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        normalized = read_json(
            self.stage_dir / "page-component-facts" / f"{page_key}.draft.json"
        )
        normalized_interaction = normalized["interaction_graph"]["interactions"][0]
        self.assertEqual(
            normalized_interaction["result"]["fact_ids"], [result_fact["fact_id"]]
        )
        self.assertEqual(
            normalized_interaction["component_bindings"]["result_candidate_ids"],
            normalized_interaction["component_bindings"]["behavior_candidate_ids"],
        )
        self.assertEqual(
            normalized["interaction_graph"]["edges"],
            facts["interaction_graph"]["edges"],
        )
        self.assertTrue(
            any(
                item["result"] is not None
                and item["result"]["fact_id"] == result_fact["fact_id"]
                for item in normalized["interaction_items"]
            )
        )

        resultless = json.loads(json.dumps(facts))
        resultless["interaction_graph"]["interactions"][0]["result"] = None
        resultless["interaction_graph"]["interactions"][0]["component_bindings"][
            "result_candidate_ids"
        ] = []
        rejected = self.record_page_draft(page_a, resultless)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_result_missing", rejected.stderr)

        orphan_result = json.loads(json.dumps(facts))
        orphan_result["interaction_graph"]["interactions"][0]["behavior"] = None
        orphan_result["interaction_graph"]["interactions"][0]["trigger"] = None
        orphan_result["interaction_graph"]["interactions"][0]["component_bindings"][
            "behavior_candidate_ids"
        ] = []
        orphan_result["interaction_graph"]["interactions"][0]["component_bindings"][
            "trigger_candidate_ids"
        ] = []
        rejected = self.record_page_draft(page_a, orphan_result)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_causality_missing", rejected.stderr)

        recorded = self.record_page(page_a, facts)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_page(page_b, self.valid_page_facts(page_b))
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        locked_page_a = next(
            page for page in lock["pages"] if page["member_title"] == "Design A"
        )
        locked_page_b = next(
            page for page in lock["pages"] if page["member_title"] == "Design B"
        )
        locked_graph = next(
            graph
            for graph in lock["interaction_graphs"]
            if graph["member_title"] == "Design A"
        )
        locked_interaction = locked_graph["interactions"][0]
        self.assertEqual(
            locked_interaction["result"]["fact_ids"], [result_fact["fact_id"]]
        )
        self.assertTrue(
            locked_interaction["component_bindings"]["result_component_instance_ids"]
        )
        self.assertNotIn(
            "result_candidate_ids", locked_interaction["component_bindings"]
        )
        self.assertEqual(locked_graph["edges"], facts["interaction_graph"]["edges"])
        self.assertTrue(
            any(
                item["result"] is not None
                and item["result"]["fact_id"] == result_fact["fact_id"]
                for item in locked_page_a["interaction_items"]
            )
        )
        page_a_fact_ids = {
            fact["fact_id"]
            for candidate in locked_page_a["candidates"]
            for fact in candidate["facts"]
        }
        page_b_fact_ids = {
            fact["fact_id"]
            for candidate in locked_page_b["candidates"]
            for fact in candidate["facts"]
        }
        self.assertEqual(page_a_fact_ids & page_b_fact_ids, set())
        for candidate in locked_page_b["candidates"]:
            for fact in candidate["facts"]:
                self.assertTrue(
                    all(
                        ref["design_name"] == "Design B" for ref in fact["block_refs"]
                    )
                )
        locked_api_graph = next(
            graph
            for graph in lock["interaction_graphs"]
            if graph["member_title"] == "Design B"
        )
        api_interaction = next(
            item
            for item in locked_api_graph["interactions"]
            if item["behavior"] is not None and item["behavior"]["kind"] == "api_call"
        )
        self.assertEqual(
            set(api_interaction["result"]["outcomes"]), {"success", "failure"}
        )
        resolved_outcomes = {
            edge["outcome"]
            for edge in locked_api_graph["edges"]
            if edge["from_interaction_id"] == api_interaction["interaction_id"]
        } | {
            terminal["outcome"]
            for terminal in locked_api_graph["terminal_outcomes"]
            if terminal["interaction_id"] == api_interaction["interaction_id"]
        }
        self.assertTrue({"success", "failure"} <= resolved_outcomes)

    def test_cross_page_modal_result_needs_exact_iole_relation_evidence(self) -> None:
        self.bundle_path = self.build_source_bundle(
            design_a_relation_kind="modal",
            design_a_api_override="",
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        page_a = next(item for item in pages if item["member_title"] == "Design A")
        page_b = next(item for item in pages if item["member_title"] == "Design B")
        facts = self.valid_page_facts(page_a)
        modal = facts["presentation_requirements"][0]
        self.assertEqual(modal["relation_kind"], "modal")
        interaction = facts["interaction_graph"]["interactions"][0]
        interaction["behavior"]["kind"] = "present"
        self.assertEqual(
            [edge["target"]["kind"] for edge in facts["interaction_graph"]["edges"]],
            ["modal"],
        )
        self.assertEqual(
            facts["interaction_graph"]["edges"][0]["target"]["requirement_ids"],
            [modal["presentation_requirement_id"]],
        )

        evidenceless = json.loads(json.dumps(facts))
        evidenceless["interaction_graph"]["edges"][0]["target"]["requirement_ids"] = []
        rejected = self.record_page_draft(page_a, evidenceless)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_edge_target", rejected.stderr)

        unknown_requirement = json.loads(json.dumps(facts))
        unknown_requirement["interaction_graph"]["edges"][0]["target"][
            "requirement_ids"
        ] = ["presentation-unknown000000000000000"]
        rejected = self.record_page_draft(page_a, unknown_requirement)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_edge_target", rejected.stderr)

        unknown_design = json.loads(json.dumps(facts))
        unknown_design["interaction_graph"]["edges"][0]["target"][
            "design_name"
        ] = "Design B 2"
        rejected = self.record_page_draft(page_a, unknown_design)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_edge_target", rejected.stderr)

        unknown_kind = json.loads(json.dumps(facts))
        unknown_kind["interaction_graph"]["edges"][0]["target"]["kind"] = "teleport"
        rejected = self.record_page_draft(page_a, unknown_kind)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_edge_target", rejected.stderr)

        recorded = self.record_page(page_a, facts)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_page(page_b, self.valid_page_facts(page_b))
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_abstraction(
            self.add_presentation_usages(self.valid_abstraction_plan())
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        locked_graph = next(
            graph
            for graph in lock["interaction_graphs"]
            if graph["member_title"] == "Design A"
        )
        self.assertEqual(len(locked_graph["edges"]), 1)
        edge = locked_graph["edges"][0]
        self.assertEqual(edge["target"]["kind"], "modal")
        self.assertEqual(
            edge["target"]["page_key"], COMPONENT_DESIGN.page_key_for("Design B")
        )
        self.assertEqual(
            edge["target"]["requirement_ids"],
            [modal["presentation_requirement_id"]],
        )
        locked_page_a = next(
            page for page in lock["pages"] if page["member_title"] == "Design A"
        )
        locked_page_b = next(
            page for page in lock["pages"] if page["member_title"] == "Design B"
        )
        page_a_fact_ids = {
            fact["fact_id"]
            for candidate in locked_page_a["candidates"]
            for fact in candidate["facts"]
        }
        page_b_fact_ids = {
            fact["fact_id"]
            for candidate in locked_page_b["candidates"]
            for fact in candidate["facts"]
        }
        self.assertEqual(page_a_fact_ids & page_b_fact_ids, set())
        for candidate in locked_page_b["candidates"]:
            for fact in candidate["facts"]:
                self.assertTrue(
                    all(ref["design_name"] == "Design B" for ref in fact["block_refs"])
                )

        # A component/reference relation is never a runtime transition.
        nested = ComponentDesignV4CliTest(
            methodName="test_designless_context_with_business_data_gets_a_source_only_work_item"
        )
        nested.setUp()
        try:
            nested.bundle_path = nested.build_source_bundle(
                design_a_relation_kind="component",
                design_a_api_override="",
            )
            nested_begun = nested.begin()
            self.assertEqual(
                nested_begun.returncode, 0, nested_begun.stdout + nested_begun.stderr
            )
            nested_pages = json.loads(nested_begun.stdout)["pages"]
            nested_page_a = next(
                item
                for item in nested_pages
                if item["member_title"] == "Design A"
            )
            nested_facts = nested.valid_page_facts(nested_page_a)
            component_requirement = nested_facts["presentation_requirements"][0]
            self.assertEqual(component_requirement["relation_kind"], "component")
            nested_interaction = nested_facts["interaction_graph"]["interactions"][0]
            nested_interaction["behavior"]["kind"] = "present"
            nested_interaction["result"]["outcomes"] = ["opened"]
            nested_facts["interaction_graph"]["terminal_outcomes"] = []
            nested_facts["interaction_graph"]["edges"].append(
                {
                    "from_interaction_id": nested_interaction["interaction_id"],
                    "outcome": "opened",
                    "target": {
                        "kind": "modal",
                        "page_key": component_requirement["target_page_key"],
                        "design_name": "Design B",
                        "requirement_ids": [
                            component_requirement["presentation_requirement_id"]
                        ],
                    },
                }
            )

            rejected = nested.record_page_draft(nested_page_a, nested_facts)

            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("invalid_interaction_edge_target", rejected.stderr)
        finally:
            nested.tearDown()

    def test_every_behavior_result_outcome_is_resolved_exactly_once(self) -> None:
        self.bundle_path = self.build_source_bundle(design_a_api_override="")
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        page_a = next(item for item in pages if item["member_title"] == "Design A")
        page_b = next(item for item in pages if item["member_title"] == "Design B")
        facts = self.valid_page_facts(page_a)
        interaction = facts["interaction_graph"]["interactions"][0]
        self.assertEqual(interaction["result"]["outcomes"], ["done", "opened"])
        self.assertEqual(
            [
                (terminal["interaction_id"], terminal["outcome"])
                for terminal in facts["interaction_graph"]["terminal_outcomes"]
            ],
            [(interaction["interaction_id"], "done")],
        )
        self.assertEqual(
            [
                (edge["from_interaction_id"], edge["outcome"])
                for edge in facts["interaction_graph"]["edges"]
            ],
            [(interaction["interaction_id"], "opened")],
        )

        drafted = self.record_page_draft(page_a, json.loads(json.dumps(facts)))

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        terminal_removed = json.loads(json.dumps(facts))
        terminal_removed["interaction_graph"]["terminal_outcomes"] = []
        rejected = self.record_page_draft(page_a, terminal_removed)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_result_outcome_unresolved", rejected.stderr)

        edge_removed = json.loads(json.dumps(facts))
        edge_removed["interaction_graph"]["edges"] = []
        rejected = self.record_page_draft(page_a, edge_removed)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_result_outcome_unresolved", rejected.stderr)

        self_edge = json.loads(json.dumps(facts))
        self_edge["interaction_graph"]["edges"].append(
            {
                "from_interaction_id": interaction["interaction_id"],
                "outcome": "done",
                "target": {
                    "kind": "interaction",
                    "to_interaction_id": interaction["interaction_id"],
                },
            }
        )
        rejected = self.record_page_draft(page_a, self_edge)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_graph", rejected.stderr)

        undeclared = json.loads(json.dumps(facts))
        undeclared["interaction_graph"]["terminal_outcomes"][0]["outcome"] = "finished"
        rejected = self.record_page_draft(page_a, undeclared)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("invalid_interaction_terminal_outcome", rejected.stderr)

        api_facts = self.valid_page_facts(page_b)
        api_interaction = next(
            item
            for item in api_facts["interaction_graph"]["interactions"]
            if item["behavior"] is not None and item["behavior"]["kind"] == "api_call"
        )
        self.assertEqual(
            api_interaction["result"]["outcomes"], ["success", "failure"]
        )
        unresolved_api = json.loads(json.dumps(api_facts))
        unresolved_api["interaction_graph"]["edges"] = [
            edge
            for edge in unresolved_api["interaction_graph"]["edges"]
            if not (
                edge["from_interaction_id"] == api_interaction["interaction_id"]
                and edge["outcome"] == "success"
            )
        ]
        rejected = self.record_page_draft(page_b, unresolved_api)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_interaction_outcome_missing", rejected.stderr)

    def test_transition_requirements_are_consumed_exactly_once_with_covering_result_facts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        page_a = next(item for item in pages if item["member_title"] == "Design A")
        page_b = next(item for item in pages if item["member_title"] == "Design B")
        facts = self.valid_page_facts(page_a)
        navigation = facts["navigation_requirements"][0]
        interaction = facts["interaction_graph"]["interactions"][0]
        navigation_edge = next(
            edge
            for edge in facts["interaction_graph"]["edges"]
            if edge["target"]["kind"] == "navigation"
        )
        self.assertEqual(
            navigation_edge["target"]["requirement_ids"],
            [navigation["navigation_requirement_id"]],
        )

        omitted = json.loads(json.dumps(facts))
        omitted["interaction_graph"]["edges"] = [
            edge
            for edge in omitted["interaction_graph"]["edges"]
            if edge["target"]["kind"] != "navigation"
        ]
        omitted["interaction_graph"]["interactions"][0]["result"]["outcomes"] = [
            outcome
            for outcome in omitted["interaction_graph"]["interactions"][0]["result"][
                "outcomes"
            ]
            if outcome != navigation_edge["outcome"]
        ]
        rejected = self.record_page_draft(page_a, omitted)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_transition_evidence_missing", rejected.stderr)

        duplicated = json.loads(json.dumps(facts))
        duplicated_interaction = duplicated["interaction_graph"]["interactions"][0]
        duplicated_interaction["result"]["outcomes"] = list(
            duplicated_interaction["result"]["outcomes"]
        ) + ["opened-again"]
        duplicated["interaction_graph"]["edges"].append(
            {
                "from_interaction_id": duplicated_interaction["interaction_id"],
                "outcome": "opened-again",
                "target": json.loads(json.dumps(navigation_edge["target"])),
            }
        )
        rejected = self.record_page_draft(page_a, duplicated)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_transition_evidence_duplicate", rejected.stderr)

        wrong_result = json.loads(json.dumps(facts))
        wrong_result["interaction_graph"]["edges"] = [
            edge
            for edge in wrong_result["interaction_graph"]["edges"]
            if edge["target"]["kind"] != "navigation"
        ]
        wrong_result["interaction_graph"]["interactions"][0]["result"]["outcomes"] = [
            outcome
            for outcome in wrong_result["interaction_graph"]["interactions"][0][
                "result"
            ]["outcomes"]
            if outcome != navigation_edge["outcome"]
        ]
        continuation = next(
            item
            for item in wrong_result["interaction_graph"]["interactions"]
            if item["interaction_id"].endswith("-success")
        )
        continuation["result"]["outcomes"] = list(
            continuation["result"]["outcomes"]
        ) + ["opened-elsewhere"]
        wrong_result["interaction_graph"]["edges"].append(
            {
                "from_interaction_id": continuation["interaction_id"],
                "outcome": "opened-elsewhere",
                "target": json.loads(json.dumps(navigation_edge["target"])),
            }
        )
        rejected = self.record_page_draft(page_a, wrong_result)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_transition_evidence_unbound", rejected.stderr)

        recorded = self.record_page(page_a, facts)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_page(page_b, self.valid_page_facts(page_b))
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        locked_graph = next(
            graph
            for graph in lock["interaction_graphs"]
            if graph["member_title"] == "Design A"
        )
        self.assertEqual(
            locked_graph["transition_requirements"],
            facts["navigation_requirements"],
        )
        locked_edge = next(
            edge
            for edge in locked_graph["edges"]
            if edge["target"]["kind"] == "navigation"
        )
        self.assertEqual(
            locked_edge["target"]["requirement_ids"],
            [navigation["navigation_requirement_id"]],
        )
        self.assertIn(
            navigation["source_ref"]["quote"],
            locked_graph["transition_requirements"][0]["source_ref"]["quote"],
        )

    def test_component_lock_projects_api_interactions_to_final_component_instances(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            facts = self.bind_first_api_contract(self.valid_page_facts(page))
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertEqual(lock["schema"], "icp.component-design.lock.v8")
        self.assertEqual(len(lock["api_contracts"]), 2)
        self.assertEqual(len(lock["interaction_graphs"]), 2)
        for contract in lock["api_contracts"]:
            artifact = contract["acquisition_artifact"]
            artifact_path = self.stage_dir / artifact["path"]
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                artifact["sha256"],
            )
        for graph in lock["interaction_graphs"]:
            api_interaction = next(
                item
                for item in graph["interactions"]
                if item["behavior"] is not None
                and item["behavior"]["kind"] == "api_call"
            )
            self.assertTrue(
                api_interaction["component_bindings"][
                    "behavior_component_instance_ids"
                ]
            )
            self.assertNotIn(
                "behavior_candidate_ids", api_interaction["component_bindings"]
            )

    def test_page_review_exposes_interaction_graph_and_api_contract_checks(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.bind_first_api_contract(self.valid_page_facts(page))
        drafted = self.record_page_draft(page, facts)
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        review = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )

        self.assertEqual(review["interaction_graph"], facts["interaction_graph"])
        self.assertEqual(
            review["navigation_requirements"], facts["navigation_requirements"]
        )
        self.assertEqual(review["api_contracts"], facts["api_contracts"])
        self.assertEqual(review["schema"], "icp.component-design.page-review.v3")
        self.assertFalse(review["cross_page_review"]["interaction_graph_complete"])
        self.assertFalse(
            review["cross_page_review"]["interaction_component_bindings_correct"]
        )
        self.assertFalse(review["cross_page_review"]["api_contracts_correct"])

    def test_interaction_item_rejects_a_missing_nullable_field(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        interaction_fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["kind"] == "behavior"
            and any(
                source_ref["clause_id"] == "page:interaction"
                for source_ref in fact["source_refs"]
            )
        )
        facts["interaction_items"] = [
            {
                "item_id": f"{page['page_key']}-interaction-behavior-1",
                "source_ref": interaction_fact["source_refs"][0],
                "condition": None,
                "trigger": None,
                "behavior": {
                    "fact_id": interaction_fact["fact_id"],
                    "meaning": interaction_fact["meaning"],
                },
            }
        ]

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("invalid_interaction_item", drafted.stderr)

    def test_interaction_description_can_split_into_all_five_atomic_item_types(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        interaction_coverage = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        segment = interaction_coverage["segments"][0]
        behavior_fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["fact_id"] == segment["fact_ids"][0]
        )
        for kind, meaning in (
            ("condition", "The declared interaction precondition is satisfied."),
            ("state", "The source component is ready for the interaction."),
            ("trigger", "The user selects the declared source control."),
        ):
            fact = {
                **behavior_fact,
                "fact_id": f"{page['page_key']}-interaction-{kind}",
                "kind": kind,
                "meaning": meaning,
            }
            facts["candidates"][1]["facts"].append(fact)
            segment["fact_ids"].append(fact["fact_id"])
        self.with_interaction_items(facts)

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        normalized = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.draft.json"
        )
        self.assertEqual(
            {
                field
                for item in normalized["interaction_items"]
                for field in ("condition", "state", "trigger", "behavior", "result")
                if item[field] is not None
            },
            {"condition", "state", "trigger", "behavior", "result"},
        )
        self.assertTrue(
            all(
                sum(
                    item[field] is not None
                    for field in ("condition", "state", "trigger", "behavior", "result")
                )
                == 1
                for item in normalized["interaction_items"]
            )
        )

    def test_interaction_item_field_must_match_its_fact_kind(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        behavior_item = next(
            item for item in facts["interaction_items"] if item["behavior"] is not None
        )
        behavior_item["trigger"] = behavior_item["behavior"]
        behavior_item["behavior"] = None

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("interaction_item_coverage", drafted.stderr)

    def test_empty_interaction_description_is_one_explicit_all_null_item(self) -> None:
        self.bundle_path = self.build_source_bundle(
            empty_interaction_for_design_b=True
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design B"
        )
        template = read_json(Path(page["input_path"]))

        self.assertEqual(
            template["interaction_items"],
            [
                {
                    "item_id": f"{page['page_key']}-interaction-null",
                    "source_ref": None,
                    "condition": None,
                    "state": None,
                    "trigger": None,
                    "behavior": None,
                    "result": None,
                }
            ],
        )
        recorded = self.record_page(page, self.valid_page_facts(page))
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_non_empty_interaction_description_cannot_skip_atomic_items(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["interaction_items"] = []

        drafted = self.record_page_draft(page, facts)

        self.assertNotEqual(drafted.returncode, 0)
        self.assertIn("interaction_item_coverage", drafted.stderr)

    def test_non_interaction_meaning_in_interaction_text_uses_an_all_null_item(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Designless Context"
        )
        facts = self.valid_page_facts(page)
        interaction_item = facts["interaction_items"][0]
        fact_id = interaction_item["behavior"]["fact_id"]
        fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["fact_id"] == fact_id
        )
        fact["kind"] = "data"
        interaction_item["behavior"] = None
        self.with_interaction_items(facts)

        drafted = self.record_page_draft(page, facts)

        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)
        normalized = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.draft.json"
        )
        self.assertTrue(
            all(
                normalized["interaction_items"][0][field] is None
                for field in ("condition", "state", "trigger", "behavior", "result")
            )
        )

    def test_page_facts_reject_another_pages_source_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        semantic_fact = facts["candidates"][1]["facts"][0]
        semantic_fact["source_refs"][0]["member_title"] = "Design B"

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_semantic_leak", recorded.stderr)

    def test_every_semantic_fact_requires_design_block_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["candidates"][1]["facts"][0]["block_refs"] = []

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_semantic_fact", recorded.stderr)

    def test_design_visible_fact_without_a_source_span_can_seal(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v4(self.valid_page_facts(page))
        self.add_design_visible_fact(facts)

        recorded = self.record_page(page, facts)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        canonical = read_json(
            self.stage_dir / "page-component-facts" / f"{page['page_key']}.json"
        )
        visible_fact = canonical["candidates"][0]["facts"][0]
        self.assertEqual(visible_fact["evidence_class"], "design_visible")
        self.assertEqual(visible_fact["source_refs"], [])
        self.assertTrue(visible_fact["visible_basis"])

    def test_page_facts_v1_is_rejected_after_the_provenance_schema_bump(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["schema"] = "icp.component-design.page-facts.v1"

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_page_facts", recorded.stderr)

    def test_design_visible_fact_rejects_invisible_kinds(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        for forbidden_kind in ("behavior", "api_dependency"):
            with self.subTest(kind=forbidden_kind):
                facts = self.page_facts_v4(self.valid_page_facts(page))
                self.add_design_visible_fact(facts, kind=forbidden_kind)

                recorded = self.record_page(page, facts)

                self.assertNotEqual(recorded.returncode, 0)
                self.assertIn("invalid_fact_evidence_class", recorded.stderr)

    def test_design_visible_fact_rejects_source_refs_and_missing_basis(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v4(self.valid_page_facts(page))
        source_ref = facts["candidates"][1]["facts"][0]["source_refs"][0]
        self.add_design_visible_fact(facts, source_refs=[source_ref])

        with_source = self.record_page(page, facts)

        self.assertNotEqual(with_source.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", with_source.stderr)

        facts = self.page_facts_v4(self.valid_page_facts(page))
        self.add_design_visible_fact(facts, visible_basis=None)

        without_basis = self.record_page(page, facts)

        self.assertNotEqual(without_basis.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", without_basis.stderr)

        facts = self.page_facts_v4(self.valid_page_facts(page))
        self.add_design_visible_fact(facts, visible_basis=" ")

        with_empty_basis = self.record_page(page, facts)

        self.assertNotEqual(with_empty_basis.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", with_empty_basis.stderr)

    def test_business_source_fact_rejects_visible_basis(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v4(self.valid_page_facts(page))
        facts["candidates"][1]["facts"][0]["visible_basis"] = (
            "Business facts must not masquerade as design-only evidence."
        )

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", recorded.stderr)

    def test_design_visible_fact_cannot_consume_business_source_coverage(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v4(self.valid_page_facts(page))
        target = facts["candidates"][1]["facts"][0]
        target["evidence_class"] = "design_visible"
        target["visible_basis"] = "The cited Block is visible in this design."
        target["source_refs"] = []

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("design_visible_coverage_leak", recorded.stderr)

    def test_design_visible_fact_cannot_cite_another_pages_block(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v4(self.valid_page_facts(page))
        visible = self.add_design_visible_fact(facts)
        visible["block_refs"] = [{"design_name": "Design B", "block_id": "page"}]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_semantic_leak", recorded.stderr)

    def test_fact_block_evidence_must_be_owned_by_its_candidate(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["candidates"][1]["facts"][0]["block_refs"] = [
            {
                "design_name": facts["design_names"][0],
                "block_id": "page",
            }
        ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("semantic_hierarchy_mismatch", recorded.stderr)

    def test_every_fact_source_ref_must_appear_in_the_coverage_ledger(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        target_fact = facts["candidates"][1]["facts"][0]
        other_clause = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] != target_fact["source_refs"][0]["clause_id"]
            and item["source_text"]
        )
        target_fact["source_refs"].append(
            {
                "member_title": facts["member_title"],
                "clause_id": other_clause["clause_id"],
                "source_sha256": other_clause["source_sha256"],
                "start": 0,
                "end": len(other_clause["source_text"]),
                "quote": other_clause["source_text"],
            }
        )

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("semantic_fact_coverage", recorded.stderr)

    def test_page_facts_reject_unresolved_source_segments(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        segment = facts["source_coverage"][0]["segments"][0]
        removed_fact_id = segment["fact_ids"][0]
        facts["candidates"][1]["facts"] = [
            item
            for item in facts["candidates"][1]["facts"]
            if item["fact_id"] != removed_fact_id
        ]
        facts["source_coverage"][0]["segments"] = [
            {
                "start": segment["start"],
                "end": segment["end"],
                "quote": segment["quote"],
                "disposition": "unresolved",
                "rationale": "The model could not determine the semantic owner.",
            }
        ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unresolved_semantic", recorded.stderr)

    def test_nonempty_business_clause_cannot_be_hidden_as_context(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["candidates"][1]["facts"] = []
        for clause in facts["source_coverage"]:
            if not clause["segments"]:
                continue
            segment = clause["segments"][0]
            clause["segments"] = [
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "quote": segment["quote"],
                    "disposition": "context",
                    "rationale": "Treat the entire source as background context.",
                }
            ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("source_coverage", recorded.stderr)

    def test_normative_clause_remainder_cannot_be_demoted_to_context(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        clause = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        original = clause["segments"][0]
        split = original["quote"].index(" ")
        fact_id = original["fact_ids"][0]
        fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["fact_id"] == fact_id
        )
        fact["source_refs"][0]["end"] = split
        fact["source_refs"][0]["quote"] = original["quote"][:split]
        clause["segments"] = [
            {
                "start": 0,
                "end": split,
                "quote": original["quote"][:split],
                "disposition": "fact",
                "fact_ids": [fact_id],
            },
            {
                "start": split,
                "end": original["end"],
                "quote": original["quote"][split:],
                "disposition": "context",
                "rationale": "Treat the remaining interaction as background.",
            },
        ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("source_coverage", recorded.stderr)

    def test_source_punctuation_cannot_be_dropped_as_context(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        clause = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        original = clause["segments"][0]
        split = original["end"] - 1
        self.assertEqual(original["quote"][split:], ".")
        fact_id = original["fact_ids"][0]
        fact = next(
            fact
            for candidate in facts["candidates"]
            for fact in candidate["facts"]
            if fact["fact_id"] == fact_id
        )
        fact["source_refs"][0]["end"] = split
        fact["source_refs"][0]["quote"] = original["quote"][:split]
        clause["segments"] = [
            {
                "start": 0,
                "end": split,
                "quote": original["quote"][:split],
                "disposition": "fact",
                "fact_ids": [fact_id],
            },
            {
                "start": split,
                "end": original["end"],
                "quote": ".",
                "disposition": "context",
                "rationale": "Treat the sentence terminator as non-semantic.",
            },
        ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("source_coverage", recorded.stderr)

    def test_whitespace_only_clause_is_preserved_without_a_fabricated_fact(self) -> None:
        self.bundle_path = self.build_source_bundle(
            source_contains_whitespace_only_clause=True
        )
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        whitespace_clauses = [
            item
            for item in facts["source_coverage"]
            if item["source_text"] and not item["source_text"].strip()
        ]
        whitespace_fact_ids = {
            fact_id
            for clause in whitespace_clauses
            for segment in clause["segments"]
            for fact_id in segment["fact_ids"]
        }
        for candidate in facts["candidates"]:
            candidate["facts"] = [
                fact
                for fact in candidate["facts"]
                if fact["fact_id"] not in whitespace_fact_ids
            ]
        for clause in whitespace_clauses:
            clause["segments"] = [
                {
                    "start": 0,
                    "end": len(clause["source_text"]),
                    "quote": clause["source_text"],
                    "disposition": "context",
                    "rationale": "Preserve source whitespace without inventing behavior.",
                }
            ]

        recorded = self.record_page(page, facts)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_composition_instance_must_use_blocks_owned_by_its_candidate(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        composition = facts["design_compositions"][0]
        composition["instances"][1]["candidate_id"] = composition["instances"][0][
            "candidate_id"
        ]

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("semantic_hierarchy_mismatch", recorded.stderr)

    def test_page_composition_must_follow_the_verified_block_hierarchy(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        composition = facts["design_compositions"][0]
        shell, content = composition["instances"]
        composition["root_instance_id"] = content["instance_id"]
        content["parent_instance_id"] = None
        content["slot"] = "root"
        shell["parent_instance_id"] = content["instance_id"]
        shell["slot"] = "content"

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("semantic_hierarchy_mismatch", recorded.stderr)

    def test_group_registry_is_built_once_after_all_pages_are_sealed(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]

        second = self.record_page(pages[1], self.valid_page_facts(pages[1]))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse((self.stage_dir / "group-candidate-registry.json").exists())
        first = self.record_page(pages[0], self.valid_page_facts(pages[0]))

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(json.loads(first.stdout)["state"], "awaiting_group_abstraction")
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        self.assertEqual(
            registry["schema"], "icp.component-design.group-candidate-registry.v1"
        )
        candidate_ids = [item["candidate_id"] for item in registry["candidates"]]
        self.assertEqual(candidate_ids, sorted(candidate_ids))
        self.assertEqual(len(candidate_ids), 4)
        plan = read_json(self.stage_dir / "abstraction-plan.input.json")
        self.assertEqual(plan["schema"], "icp.component-design.abstraction-plan.v1")
        self.assertEqual(plan["decisions"], [])
        self.assertEqual(plan["component_definitions"], [])
        self.assertEqual(plan["component_instances"], [])
        self.assertEqual(
            plan["candidate_registry_sha256"],
            hashlib.sha256(
                (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    def test_mobile_component_patterns_are_injected_into_page_and_group_inputs(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        page_input = read_json(Path(pages[0]["input_path"]))
        context = page_input["mobile_component_pattern_context"]

        self.assertEqual(
            context["schema"],
            "icp.component-design.mobile-component-pattern-context.v1",
        )
        self.assertEqual(
            context["knowledge_sha256"],
            hashlib.sha256(MOBILE_COMPONENT_PATTERNS.read_bytes()).hexdigest(),
        )
        self.assertIn("pattern:bottom-navigation", context["content"])
        self.assertIn("pattern:bottom-sheet", context["content"])
        self.assertIn("pattern:modal-dialog", context["content"])
        self.assertIn("Android", context["content"])
        self.assertIn("iOS", context["content"])
        self.assertEqual(
            (self.stage_dir / "mobile-component-patterns.md").read_text(
                encoding="utf-8"
            ),
            context["content"],
        )

        self.seal_all_pages()
        review_input = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{pages[0]['page_key']}.review.input.json"
        )
        self.assertEqual(
            review_input["mobile_component_pattern_context"], context
        )
        plan = read_json(self.stage_dir / "abstraction-plan.input.json")
        self.assertEqual(plan["mobile_component_pattern_context"], context)

    def test_stage_one_complete_blocks_are_the_direct_design_input(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

        source_catalog = read_json(self.stage_dir / "source-catalog.json")
        for design in source_catalog["designs"]:
            self.assertIn("semantic_blocks", design["artifact_sha256"])
            self.assertTrue(design["blocks"])
            self.assertTrue(
                all("source_nodes" in block for block in design["blocks"])
            )

    def test_begin_does_not_rerun_stage_one_verification(self) -> None:
        # Stage 1 already froze a complete run-result. Removing an internal review
        # artifact makes a second verify-run impossible, but must not prevent
        # Stage 2 from consuming the sealed Stage-1 output.
        (self.project / ".icp" / "extract" / "Design A" / "semantic-review.json").unlink()

        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

    def test_begin_rejects_ui_supplement_not_used_for_stage_one_grouping(self) -> None:
        self.bundle_path = self.build_source_bundle(source_contains_todo=True)

        begun = self.begin()

        self.assertEqual(begun.returncode, 2)
        self.assertIn("iole_extract_mismatch", begun.stderr)
        self.assertIn("was not used by extract", begun.stderr)

    def test_record_page_facts_rejects_changed_mobile_component_patterns(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.valid_page_facts(page)
        facts["mobile_component_pattern_context"]["content"] += "\nchanged"

        recorded = self.record_page(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("input_drift", recorded.stderr)

    def test_record_abstraction_rejects_changed_mobile_component_patterns(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        plan["mobile_component_pattern_context"]["content"] += "\nchanged"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("input_drift", recorded.stderr)

    def test_record_abstraction_keeps_shared_definition_and_page_facts_separate(self) -> None:
        self.seal_all_pages()

        recorded = self.record_abstraction(self.valid_abstraction_plan())

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        payload = json.loads(recorded.stdout)
        self.assertEqual(payload["state"], "ready_to_lock")
        system = read_json(self.stage_dir / "component-system.json")
        shared = next(
            item
            for item in system["component_definitions"]
            if item["component_id"] == "shared-page-shell"
        )
        self.assertEqual(shared["reuse_mode"], "container")
        self.assertNotIn("source_refs", shared)
        self.assertNotIn("facts", shared)
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        expected_fact_ids = {
            fact["fact_id"]
            for item in registry["candidates"]
            for fact in item["candidate"]["facts"]
        }
        actual_fact_ids = {
            binding["fact_id"]
            for instance in system["component_instances"]
            for binding in instance["fact_bindings"]
        }
        self.assertEqual(actual_fact_ids, expected_fact_ids)
        self.assertTrue((self.stage_dir / "component-cache-events.json").is_file())
        self.assertTrue((self.stage_dir / "replacement-map.json").is_file())

    def test_record_abstraction_resumes_after_artifacts_were_written_before_state(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        state_path = self.stage_dir / "state.json"
        checklist_path = self.stage_dir / "checklist.json"
        state_before = state_path.read_bytes()
        checklist_before = checklist_path.read_bytes()

        first = self.record_abstraction(plan)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        state_path.write_bytes(state_before)
        checklist_path.write_bytes(checklist_before)

        resumed = self.record_abstraction(plan)

        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual(read_json(state_path)["state"], "ready_to_lock")

    def test_committed_stage2_steps_repair_missing_checklist_receipts_without_new_revision(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        first = pages[0]
        facts = self.valid_page_facts(first)
        drafted = self.record_page_draft(first, facts)
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        def remove_receipt(node_id: str) -> None:
            checklist_path = self.stage_dir / "checklist.json"
            checklist = read_json(checklist_path)
            checklist["events"] = [
                event
                for event in checklist["events"]
                if not (
                    event["node_id"] == node_id
                    and event["event"] == "completed"
                )
            ]
            for sequence, event in enumerate(checklist["events"], start=1):
                event["sequence"] = sequence
            target = next(
                item for item in checklist["nodes"] if item["node_id"] == node_id
            )
            target.update(
                {
                    "status": "pending",
                    "evidence_sha256": None,
                    "invalidated_by": None,
                }
            )
            write_json(checklist_path, checklist)

        state_path = self.stage_dir / "state.json"
        facts_revision = read_json(state_path)["pages"][first["page_key"]]["revision"]
        remove_receipt(f"page:{first['page_key']}.facts")
        resumed_draft = self.record_page_draft(first, facts, acquire_contracts=False)
        self.assertEqual(
            resumed_draft.returncode,
            0,
            resumed_draft.stdout + resumed_draft.stderr,
        )
        self.assertEqual(
            read_json(state_path)["pages"][first["page_key"]]["revision"],
            facts_revision,
        )

        review = self.page_review(first)
        reviewed = self.record_page_review(first, review)
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        review_revision = read_json(state_path)["pages"][first["page_key"]]["revision"]
        remove_receipt(f"page:{first['page_key']}.review")
        resumed_review = self.record_page_review(first, review)
        self.assertEqual(
            resumed_review.returncode,
            0,
            resumed_review.stdout + resumed_review.stderr,
        )
        self.assertEqual(
            read_json(state_path)["pages"][first["page_key"]]["revision"],
            review_revision,
        )

        for page in pages[1:]:
            recorded = self.record_page(page, self.valid_page_facts(page))
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = self.valid_abstraction_plan()
        abstracted = self.record_abstraction(plan)
        self.assertEqual(abstracted.returncode, 0, abstracted.stdout + abstracted.stderr)
        state_before_retry = read_json(state_path)
        remove_receipt("group.abstraction")
        resumed_abstraction = self.record_abstraction(plan)
        self.assertEqual(
            resumed_abstraction.returncode,
            0,
            resumed_abstraction.stdout + resumed_abstraction.stderr,
        )
        self.assertEqual(read_json(state_path), state_before_retry)

    def test_component_lock_references_mobile_patterns_once_without_copying_each_page(self) -> None:
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = run_command(
            SCRIPT,
            "verify",
            "--project-root",
            str(self.project),
        )

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        expected_hash = hashlib.sha256(MOBILE_COMPONENT_PATTERNS.read_bytes()).hexdigest()
        self.assertEqual(
            lock["inference_context"],
            {
                "mobile_component_patterns": {
                    "path": "mobile-component-patterns.md",
                    "sha256": expected_hash,
                    "authority": "advisory_only",
                }
            },
        )
        self.assertTrue(
            all(
                "mobile_component_pattern_context" not in page
                for page in lock["pages"]
            )
        )

    def test_record_abstraction_accepts_the_generated_stage_input_path(self) -> None:
        self.seal_all_pages()
        plan_path = self.stage_dir / "abstraction-plan.input.json"
        plan = self.valid_abstraction_plan()
        write_json(plan_path, plan)

        recorded = run_command(
            SCRIPT,
            "record-abstraction",
            "--project-root",
            str(self.project),
            "--plan",
            str(plan_path),
        )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        self.assertEqual(read_json(plan_path), plan)

    def test_source_only_row_can_declare_one_shared_container_without_duplicate_designs(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in reversed(pages):
            facts = self.valid_page_facts(page)
            if page["member_title"] == "Designless Context":
                title_fact = facts["candidates"][0]["facts"][0]
                title_fact["kind"] = "component_relation"
                title_fact["meaning"] = (
                    "Declare this source-only row as a reusable shared container."
                )
                title_fact["relation_intent"] = "shared_candidate"
                title_fact["relation_target"] = {
                    "kind": "self_candidate",
                    "id": facts["candidates"][0]["candidate_id"],
                }
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        recorded = self.record_abstraction(
            self.source_declared_single_container_plan()
        )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        system = read_json(self.stage_dir / "component-system.json")
        definition = next(
            item
            for item in system["component_definitions"]
            if item["component_id"] == "source-declared-container"
        )
        self.assertEqual(definition["scope"], "shared")
        self.assertEqual(definition["reuse_mode"], "container")

    def test_component_relation_without_closed_intent_and_target_is_rejected(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Designless Context"
        )
        facts = self.valid_page_facts(page)
        title_fact = facts["candidates"][0]["facts"][0]
        title_fact["kind"] = "component_relation"
        title_fact["meaning"] = "Declare this row as a component boundary."

        recorded = self.record_page_draft(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_component_relation", recorded.stderr)

    def test_local_component_boundary_does_not_authorize_single_candidate_sharing(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in reversed(pages):
            facts = self.valid_page_facts(page)
            if page["member_title"] == "Designless Context":
                candidate = facts["candidates"][0]
                title_fact = candidate["facts"][0]
                title_fact.update(
                    {
                        "kind": "component_relation",
                        "meaning": "Declare this row as a local component boundary.",
                        "relation_intent": "local_boundary",
                        "relation_target": {
                            "kind": "self_candidate",
                            "id": candidate["candidate_id"],
                        },
                    }
                )
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        recorded = self.record_abstraction(
            self.source_declared_single_container_plan()
        )

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unsupported_abstraction", recorded.stderr)

    def test_shared_usage_relation_target_must_be_a_closed_source_member_edge(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Design A"
        )
        facts = self.valid_page_facts(page)
        relation = facts["candidates"][1]["facts"][0]
        relation.update(
            {
                "kind": "component_relation",
                "meaning": "Use a shared component declared by another source member.",
                "relation_intent": "shared_usage",
                "relation_target": {
                    "kind": "source_member",
                    "id": "Unknown Component Row",
                },
            }
        )

        recorded = self.record_page_draft(page, facts)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_component_relation", recorded.stderr)

    def test_page_review_projects_and_checks_component_relation_intent(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        page = next(
            item
            for item in json.loads(begun.stdout)["pages"]
            if item["member_title"] == "Designless Context"
        )
        facts = self.valid_page_facts(page)
        candidate = facts["candidates"][0]
        title_fact = candidate["facts"][0]
        title_fact.update(
            {
                "kind": "component_relation",
                "meaning": "Declare this source-only row as reusable.",
                "relation_intent": "shared_candidate",
                "relation_target": {
                    "kind": "self_candidate",
                    "id": candidate["candidate_id"],
                },
            }
        )
        drafted = self.record_page_draft(page, facts)
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        review = read_json(
            self.stage_dir
            / "page-component-facts"
            / f"{page['page_key']}.review.input.json"
        )
        segment = next(
            item
            for item in review["segment_reviews"]
            if any(
                fact["fact_id"] == title_fact["fact_id"]
                for fact in item["linked_facts"]
            )
        )
        projected = next(
            fact
            for fact in segment["linked_facts"]
            if fact["fact_id"] == title_fact["fact_id"]
        )
        self.assertEqual(projected["relation_intent"], "shared_candidate")
        self.assertEqual(projected["relation_target"], title_fact["relation_target"])
        self.assertFalse(segment["component_relation_intents_correct"])

    def test_shared_usage_relation_must_bind_to_the_target_shared_component(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        shared_usage_fact_id = None
        for page in reversed(pages):
            facts = self.valid_page_facts(page)
            if page["member_title"] == "Designless Context":
                candidate = facts["candidates"][0]
                candidate["facts"][0].update(
                    {
                        "kind": "component_relation",
                        "meaning": "Declare this source-only row as reusable.",
                        "relation_intent": "shared_candidate",
                        "relation_target": {
                            "kind": "self_candidate",
                            "id": candidate["candidate_id"],
                        },
                    }
                )
            elif page["member_title"] == "Design A":
                interaction_fact = next(
                    fact
                    for candidate in facts["candidates"]
                    for fact in candidate["facts"]
                    if any(
                        ref["clause_id"] == "page:interaction"
                        for ref in fact["source_refs"]
                    )
                )
                relation = {
                    **interaction_fact,
                    "fact_id": f"{page['page_key']}-shared-usage",
                    "kind": "component_relation",
                    "meaning": "Use the shared component from Designless Context.",
                    "relation_intent": "shared_usage",
                    "relation_target": {
                        "kind": "source_member",
                        "id": "Designless Context",
                    },
                }
                facts["candidates"][1]["facts"].append(relation)
                interaction_segment = next(
                    segment
                    for coverage in facts["source_coverage"]
                    if coverage["clause_id"] == "page:interaction"
                    for segment in coverage["segments"]
                    if interaction_fact["fact_id"] in segment.get("fact_ids", [])
                )
                interaction_segment["fact_ids"].append(relation["fact_id"])
                shared_usage_fact_id = relation["fact_id"]
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        self.assertIsNotNone(shared_usage_fact_id)
        plan = self.source_declared_single_container_plan()
        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_component_relation_binding", recorded.stderr)

        usage_instance = next(
            item
            for item in plan["component_instances"]
            if item["member_title"] == "Design A"
        )
        usage_binding = next(
            item
            for item in usage_instance["fact_bindings"]
            if item["fact_id"] == shared_usage_fact_id
        )
        usage_binding.update(
            {
                "target_kind": "component_ref",
                "target_id": "source-declared-container",
            }
        )

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_inbound_shared_usage_authorizes_one_unambiguous_target_candidate(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        shared_usage_fact_id = None
        for page in reversed(json.loads(begun.stdout)["pages"]):
            facts = self.valid_page_facts(page)
            if page["member_title"] == "Design A":
                interaction_fact = next(
                    fact
                    for candidate in facts["candidates"]
                    for fact in candidate["facts"]
                    if any(
                        ref["clause_id"] == "page:interaction"
                        for ref in fact["source_refs"]
                    )
                )
                relation = {
                    **interaction_fact,
                    "fact_id": f"{page['page_key']}-shared-usage",
                    "kind": "component_relation",
                    "meaning": "Use the shared component from Designless Context.",
                    "relation_intent": "shared_usage",
                    "relation_target": {
                        "kind": "source_member",
                        "id": "Designless Context",
                    },
                }
                facts["candidates"][1]["facts"].append(relation)
                interaction_segment = next(
                    segment
                    for coverage in facts["source_coverage"]
                    if coverage["clause_id"] == "page:interaction"
                    for segment in coverage["segments"]
                    if interaction_fact["fact_id"] in segment.get("fact_ids", [])
                )
                interaction_segment["fact_ids"].append(relation["fact_id"])
                shared_usage_fact_id = relation["fact_id"]
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        self.assertIsNotNone(shared_usage_fact_id)
        plan = self.source_declared_single_container_plan()
        usage_instance = next(
            item
            for item in plan["component_instances"]
            if item["member_title"] == "Design A"
        )
        usage_binding = next(
            item
            for item in usage_instance["fact_bindings"]
            if item["fact_id"] == shared_usage_fact_id
        )
        usage_binding.update(
            {
                "target_kind": "component_ref",
                "target_id": "source-declared-container",
            }
        )

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertIn(
            "source-declared-container",
            {
                definition["component_id"]
                for definition in lock["component_definitions"]
                if definition["scope"] == "shared"
            },
        )

    def test_single_candidate_shared_container_needs_source_backed_share_evidence(self) -> None:
        self.bundle_path = self.build_source_bundle(include_designless_context=True)
        self.seal_all_pages()

        recorded = self.record_abstraction(
            self.source_declared_single_container_plan()
        )

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unsupported_abstraction", recorded.stderr)

    def test_final_composition_slots_must_exist_on_parent_component(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        first_facts = self.valid_page_facts(pages[0])
        first_facts["design_compositions"][0]["instances"][1]["slot"] = "missing-slot"
        self.assertEqual(self.record_page(pages[0], first_facts).returncode, 0)
        self.assertEqual(
            self.record_page(pages[1], self.valid_page_facts(pages[1])).returncode,
            0,
        )

        recorded = self.record_abstraction(self.valid_abstraction_plan())

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unknown_component_slot", recorded.stderr)

    def test_final_composition_enforces_one_slot_cardinality(self) -> None:
        synthetic_stage = self.root / "synthetic-component-design"
        write_json(
            synthetic_stage / "page-component-facts" / "page-a.json",
            {
                "design_compositions": [
                    {
                        "design_name": "Design A",
                        "root_instance_id": "parent-instance",
                        "instances": [
                            {
                                "instance_id": "parent-instance",
                                "candidate_id": "parent-candidate",
                                "parent_instance_id": None,
                                "slot": "root",
                                "source_block_ids": ["page"],
                            },
                            {
                                "instance_id": "first-child",
                                "candidate_id": "first-candidate",
                                "parent_instance_id": "parent-instance",
                                "slot": "content",
                                "source_block_ids": ["first"],
                            },
                            {
                                "instance_id": "second-child",
                                "candidate_id": "second-candidate",
                                "parent_instance_id": "parent-instance",
                                "slot": "content",
                                "source_block_ids": ["second"],
                            },
                        ],
                    }
                ]
            },
        )
        plan = {
            "component_definitions": [
                {
                    "component_id": "parent-component",
                    "slots": [
                        {
                            "slot_id": "content",
                            "role": "Place one child.",
                            "cardinality": "one",
                        }
                    ],
                },
                {"component_id": "first-component", "slots": []},
                {"component_id": "second-component", "slots": []},
            ],
            "decisions": [
                {
                    "candidate_ids": ["parent-candidate"],
                    "target_component_id": "parent-component",
                },
                {
                    "candidate_ids": ["first-candidate"],
                    "target_component_id": "first-component",
                },
                {
                    "candidate_ids": ["second-candidate"],
                    "target_component_id": "second-component",
                },
            ],
        }

        with self.assertRaises(COMPONENT_DESIGN.ContractError) as raised:
            COMPONENT_DESIGN.validate_final_composition_slots(
                synthetic_stage,
                {"pages": {"page-a": {}}},
                plan,
                {"components": []},
            )

        self.assertEqual(raised.exception.code, "invalid_slot_cardinality")

    def test_final_container_instance_must_exercise_a_declared_slot(self) -> None:
        synthetic_stage = self.root / "synthetic-empty-container"
        write_json(
            synthetic_stage / "page-component-facts" / "page-a.json",
            {
                "design_compositions": [
                    {
                        "design_name": "Design A",
                        "root_instance_id": "container-instance",
                        "instances": [
                            {
                                "instance_id": "container-instance",
                                "candidate_id": "container-candidate",
                                "parent_instance_id": None,
                                "slot": "root",
                                "source_block_ids": ["page"],
                            }
                        ],
                    }
                ]
            },
        )
        plan = {
            "component_definitions": [
                {
                    "component_id": "empty-container",
                    "reuse_mode": "container",
                    "slots": [
                        {
                            "slot_id": "content",
                            "role": "Place business content.",
                            "cardinality": "one",
                        }
                    ],
                }
            ],
            "decisions": [
                {
                    "candidate_ids": ["container-candidate"],
                    "target_component_id": "empty-container",
                }
            ],
        }

        with self.assertRaises(COMPONENT_DESIGN.ContractError) as raised:
            COMPONENT_DESIGN.validate_final_composition_slots(
                synthetic_stage,
                {"pages": {"page-a": {}}},
                plan,
                {"components": []},
            )

        self.assertEqual(raised.exception.code, "unexercised_component_slot")

    def test_shared_capability_requires_evidence_from_every_page_instance(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_candidates = [
            item
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        ]
        content_ids = {item["candidate_id"] for item in content_candidates}
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-shared-page-content",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "shared-page-content",
                "rationale": "Both candidates appear to expose one content responsibility.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": ["Keep both page components separate."],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "shared-page-content",
                "name": "Shared page content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Own a shared content responsibility.",
                "owns": ["Only capabilities evidenced on every page instance."],
                "excludes": ["Page-specific values and behavior."],
                "capabilities": [
                    {
                        "capability_id": "selection-behavior",
                        "kind": "behavior",
                        "meaning": "Expose the page's primary selection outcome.",
                    }
                ],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        affected_instances = [
            item
            for item in plan["component_instances"]
            if content_ids.intersection(item["candidate_ids"])
        ]
        self.reset_candidate_bindings_to_instance_facts(plan, content_ids)
        for instance in affected_instances:
            instance["component_id"] = "shared-page-content"
        first_behavior_binding = next(
            binding
            for binding in affected_instances[0]["fact_bindings"]
            if binding["target_id"] == "behavior"
        )
        first_behavior_binding["target_kind"] = "capability"
        first_behavior_binding["target_id"] = "selection-behavior"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_semantic_leak", recorded.stderr)

    def test_shared_capability_meaning_must_be_exactly_common_to_every_instance(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_candidates = [
            item
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        ]
        content_ids = {item["candidate_id"] for item in content_candidates}
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-invented-shared-capability",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "invented-shared-content",
                "rationale": "Claim one behavior that the page facts do not share.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": ["Keep the distinct behaviors separate."],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "invented-shared-content",
                "name": "Invented shared content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Own one common behavior.",
                "owns": ["Only behavior proven on every instance."],
                "excludes": ["Page-specific values."],
                "capabilities": [
                    {
                        "capability_id": "delete-account",
                        "kind": "behavior",
                        "meaning": "Delete the account permanently.",
                    }
                ],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        affected_instances = [
            item
            for item in plan["component_instances"]
            if content_ids.intersection(item["candidate_ids"])
        ]
        self.reset_candidate_bindings_to_instance_facts(plan, content_ids)
        for instance in affected_instances:
            instance["component_id"] = "invented-shared-content"
            behavior_binding = next(
                binding
                for binding in instance["fact_bindings"]
                if binding["target_id"] == "behavior"
            )
            behavior_binding["target_kind"] = "capability"
            behavior_binding["target_id"] = "delete-account"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_semantic_leak", recorded.stderr)

    def test_exact_common_fact_meaning_can_form_a_shared_capability(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        common_meaning = "Activate the page primary outcome."
        for page in pages:
            facts = self.valid_page_facts(page)
            behavior_fact = next(
                fact
                for candidate in facts["candidates"]
                for fact in candidate["facts"]
                if fact["kind"] == "behavior"
            )
            behavior_fact["meaning"] = common_meaning
            self.with_interaction_items(facts)
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_ids = {
            item["candidate_id"]
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        }
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-exact-common-capability",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "shared-outcome-content",
                "rationale": "Every instance exposes the same canonical behavior fact.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": ["Keep an exactly common capability local."],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "shared-outcome-content",
                "name": "Shared outcome content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Expose one common page outcome.",
                "owns": ["The exact common outcome capability."],
                "excludes": ["Page-specific data and API facts."],
                "capabilities": [
                    {
                        "capability_id": "primary-outcome",
                        "kind": "behavior",
                        "meaning": common_meaning,
                    }
                ],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        self.reset_candidate_bindings_to_instance_facts(plan, content_ids)
        for instance in plan["component_instances"]:
            if not content_ids.intersection(instance["candidate_ids"]):
                continue
            instance["component_id"] = "shared-outcome-content"
            behavior_binding = next(
                binding
                for binding in instance["fact_bindings"]
                if binding["target_id"] == "behavior"
            )
            behavior_binding["target_kind"] = "capability"
            behavior_binding["target_id"] = "primary-outcome"

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_design_visible_invariant_can_form_a_shared_complete_component(self) -> None:
        common_meaning = "Own one independently verified visible content boundary."
        self.seal_pages_with_design_visible_content([common_meaning, common_meaning])
        plan = self.shared_design_visible_plan(common_meaning)

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_coarse_visible_facts_fail_then_split_facts_can_be_resealed(self) -> None:
        pages = self.seal_pages_with_design_visible_content(
            [
                "Own the visible content boundary with the first page selected state.",
                "Own the visible content boundary with the second page selected state.",
            ]
        )
        coarse_plan = self.shared_design_visible_plan(
            "Own the visible content boundary with the first page selected state."
        )

        coarse_result = self.record_abstraction(coarse_plan)

        self.assertNotEqual(coarse_result.returncode, 0)
        self.assertIn("cross_page_definition_leak", coarse_result.stderr)
        for artifact in (
            "abstraction-decisions.json",
            "component-system.json",
            "component-cache-events.json",
            "replacement-map.json",
        ):
            self.assertFalse((self.stage_dir / artifact).exists())

        common_meaning = "Own one independently verified visible content boundary."
        for index, page in enumerate(pages, start=1):
            facts = self.valid_page_facts(page)
            facts["candidates"][1]["facts"].extend(
                [
                    {
                        "fact_id": f"{page['page_key']}-visible-content",
                        "kind": "responsibility",
                        "meaning": common_meaning,
                        "evidence_class": "design_visible",
                        "visible_basis": (
                            "The verified content Block visibly owns this content boundary."
                        ),
                        "source_refs": [],
                        "block_refs": [
                            {
                                "design_name": facts["design_names"][0],
                                "block_id": "content",
                            }
                        ],
                    },
                    {
                        "fact_id": f"{page['page_key']}-visible-instance-state",
                        "kind": "state",
                        "meaning": f"The rendered design visibly presents state {index}.",
                        "evidence_class": "design_visible",
                        "visible_basis": (
                            "The verified content Block visibly presents this instance state."
                        ),
                        "source_refs": [],
                        "block_refs": [
                            {
                                "design_name": facts["design_names"][0],
                                "block_id": "content",
                            }
                        ],
                    },
                ]
            )
            resealed = self.record_page(page, facts)
            self.assertEqual(
                resealed.returncode, 0, resealed.stdout + resealed.stderr
            )

        split_plan = self.shared_design_visible_plan(common_meaning)
        split_result = self.record_abstraction(split_plan)

        self.assertEqual(split_result.returncode, 0, split_result.stdout + split_result.stderr)

    def test_shared_complete_visible_data_must_bind_declared_data_roles(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        common_responsibility = "Present one repeated visible content boundary."
        common_data = "Supply the visible label for this repeated component."
        for page in pages:
            facts = self.valid_page_facts(page)
            content = facts["candidates"][1]
            content["facts"].extend(
                [
                    {
                        "fact_id": f"{page['page_key']}-visible-content",
                        "kind": "responsibility",
                        "meaning": common_responsibility,
                        "evidence_class": "design_visible",
                        "visible_basis": "The verified content Block visibly proves this repeated component boundary.",
                        "source_refs": [],
                        "block_refs": [
                            {
                                "design_name": facts["design_names"][0],
                                "block_id": "content",
                            }
                        ],
                    },
                    {
                        "fact_id": f"{page['page_key']}-visible-label",
                        "kind": "data",
                        "meaning": common_data,
                        "evidence_class": "design_visible",
                        "visible_basis": "The verified repeated component exposes one visible label value.",
                        "source_refs": [],
                        "block_refs": [
                            {
                                "design_name": facts["design_names"][0],
                                "block_id": "content",
                            }
                        ],
                    },
                ]
            )
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        plan = self.shared_design_visible_plan(common_responsibility)
        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("visible_variation_role_missing", recorded.stderr)

        definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == "shared-visible-content"
        )
        definition["data_roles"].append(
            {"role_id": "visible-label", "meaning": common_data, "required": True}
        )
        for instance in plan["component_instances"]:
            if instance["component_id"] != "shared-visible-content":
                continue
            fact_binding = next(
                item
                for item in instance["fact_bindings"]
                if item["fact_id"].endswith("-visible-label")
            )
            fact_binding.update(
                {"target_kind": "data_role", "target_id": "visible-label"}
            )

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_fact_binding_kind_must_match_the_definition_target_kind(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        local_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"].startswith("page-content-")
        )
        local_definition["capabilities"] = [
            {
                "capability_id": "submit-action",
                "kind": "behavior",
                "meaning": "Expose the page submit action.",
            }
        ]
        local_instance = next(
            item
            for item in plan["component_instances"]
            if item["component_id"] == local_definition["component_id"]
        )
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        data_fact_ids = {
            fact["fact_id"]
            for item in registry["candidates"]
            for fact in item["candidate"]["facts"]
            if fact["kind"] in {"data", "api_dependency"}
        }
        data_binding = next(
            item
            for item in local_instance["fact_bindings"]
            if item["fact_id"] in data_fact_ids
        )
        data_binding["target_kind"] = "capability"
        data_binding["target_id"] = "submit-action"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_fact_binding", recorded.stderr)

    def test_local_component_cannot_hide_source_semantics_as_instance_facts(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        fact_kinds = {
            fact["fact_id"]: fact["kind"]
            for item in registry["candidates"]
            for fact in item["candidate"]["facts"]
        }
        local_component_ids = {
            definition["component_id"]
            for definition in plan["component_definitions"]
            if definition["scope"] == "local"
        }
        instance = next(
            item
            for item in plan["component_instances"]
            if item["component_id"] in local_component_ids
        )
        binding = next(
            item
            for item in instance["fact_bindings"]
            if item["target_kind"] != "instance_fact"
        )
        binding["target_kind"] = "instance_fact"
        binding["target_id"] = fact_kinds[binding["fact_id"]]

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("local_semantic_binding_missing", recorded.stderr)

    def test_shared_definition_cannot_copy_one_pages_source_literal(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_entries = [
            item
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        ]
        content_ids = {item["candidate_id"] for item in content_entries}
        page_a_api_fact = next(
            fact
            for fact in content_entries[0]["candidate"]["facts"]
            if fact["kind"] == "api_dependency"
        )
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-leaking-complete-component",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "leaking-shared-content",
                "rationale": "Treat both API dependencies as one shared capability.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": ["Keep page API semantics on instances."],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "leaking-shared-content",
                "name": "Leaking shared content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Own shared content.",
                "owns": ["One API capability."],
                "excludes": ["Other instance facts."],
                "capabilities": [
                    {
                        "capability_id": "api-binding",
                        "kind": "api_dependency",
                        "meaning": page_a_api_fact["meaning"],
                    }
                ],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        self.reset_candidate_bindings_to_instance_facts(plan, content_ids)
        for instance in plan["component_instances"]:
            if not content_ids.intersection(instance["candidate_ids"]):
                continue
            instance["component_id"] = "leaking-shared-content"
            api_binding = next(
                item
                for item in instance["fact_bindings"]
                if item["target_id"] == "api_dependency"
            )
            api_binding["target_kind"] = "capability"
            api_binding["target_id"] = "api-binding"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_definition_leak", recorded.stderr)

    def test_local_definition_cannot_be_shared_across_pages(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        local_decisions = [
            item for item in plan["decisions"] if item["kind"] == "keep-separate"
        ]
        first_component_id = local_decisions[0]["target_component_id"]
        second_component_id = local_decisions[1]["target_component_id"]
        local_decisions[1]["target_component_id"] = first_component_id
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if item["component_id"] != second_component_id
        ]
        first_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == first_component_id
        )
        targets_by_kind = {
            capability["kind"]: ("capability", capability["capability_id"])
            for capability in first_definition["capabilities"]
        }
        if first_definition["data_roles"]:
            targets_by_kind["data"] = (
                "data_role",
                first_definition["data_roles"][0]["role_id"],
            )
        if first_definition["action_roles"]:
            targets_by_kind["behavior"] = (
                "action_role",
                first_definition["action_roles"][0]["role_id"],
            )
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        fact_kinds = {
            fact["fact_id"]: fact["kind"]
            for item in registry["candidates"]
            for fact in item["candidate"]["facts"]
        }
        for instance in plan["component_instances"]:
            if instance["component_id"] == second_component_id:
                instance["component_id"] = first_component_id
                for binding in instance["fact_bindings"]:
                    target = targets_by_kind.get(fact_kinds[binding["fact_id"]])
                    if target is not None:
                        binding["target_kind"], binding["target_id"] = target

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unsupported_abstraction", recorded.stderr)

    def test_same_page_reuse_cannot_hide_behind_a_local_definition(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            facts = self.valid_page_facts(page)
            if page["member_title"] == "Design A":
                facts["candidates"][0]["kind"] = "component"
            recorded = self.record_page(page, facts)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        page_b_shell_id = next(
            item["candidate_id"]
            for item in registry["candidates"]
            if item["member_title"] == "Design B"
            and item["candidate"]["kind"] == "page"
        )
        shell_decision = next(
            item
            for item in plan["decisions"]
            if page_b_shell_id in item["candidate_ids"]
        )
        shell_decision["kind"] = "keep-local"
        shell_decision["rationale"] = "Keep the only page shell local."
        shell_decision["alternatives_rejected"] = ["Invent a second shell instance."]
        shell_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == shell_decision["target_component_id"]
        )
        shell_definition["scope"] = "local"
        shell_definition["reuse_mode"] = "local"

        page_a_ids = [
            item["candidate_id"]
            for item in registry["candidates"]
            if item["member_title"] == "Design A"
        ]
        page_a_decisions = [
            next(
                decision
                for decision in plan["decisions"]
                if candidate_id in decision["candidate_ids"]
            )
            for candidate_id in page_a_ids
        ]
        first_target = page_a_decisions[0]["target_component_id"]
        second_target = page_a_decisions[1]["target_component_id"]
        page_a_decisions[1]["target_component_id"] = first_target
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if item["component_id"] != second_target
        ]
        merged_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == first_target
        )
        merged_definition["slots"] = [
            {
                "slot_id": "content",
                "role": "Place the nested content candidate.",
                "cardinality": "one",
            }
        ]
        for instance in plan["component_instances"]:
            if instance["component_id"] == second_target:
                instance["component_id"] = first_target

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unsupported_abstraction", recorded.stderr)

    def test_component_definition_kind_must_match_every_candidate_kind(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        local_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"].startswith("page-content-")
        )
        local_definition["kind"] = "section"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_component_instance", recorded.stderr)

    def test_shared_definition_cannot_copy_an_unrelated_candidate_literal(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_fact = next(
            fact
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
            for fact in item["candidate"]["facts"]
            if fact["kind"] == "api_dependency"
        )
        shared_shell = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == "shared-page-shell"
        )
        shared_shell["responsibility"] = content_fact["meaning"]

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("cross_page_definition_leak", recorded.stderr)

    def test_component_definition_cannot_declare_the_reserved_root_slot(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        shared_shell = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == "shared-page-shell"
        )
        shared_shell["slots"].append(
            {
                "slot_id": "root",
                "role": "Illegally reuse the composition root marker.",
                "cardinality": "one",
            }
        )

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("invalid_component_definition", recorded.stderr)

    def test_complete_shared_component_requires_a_cross_instance_invariant(self) -> None:
        self.seal_all_pages()
        plan = self.valid_abstraction_plan()
        registry = read_json(self.stage_dir / "group-candidate-registry.json")
        content_ids = {
            item["candidate_id"]
            for item in registry["candidates"]
            if item["candidate"]["kind"] == "component"
        }
        plan["decisions"] = [
            item
            for item in plan["decisions"]
            if not content_ids.intersection(item["candidate_ids"])
        ]
        plan["decisions"].append(
            {
                "decision_id": "extract-empty-complete-component",
                "kind": "extract-complete",
                "candidate_ids": sorted(content_ids),
                "target_component_id": "empty-shared-content",
                "rationale": "Merge without identifying any shared semantic role.",
                "evidence_candidate_ids": sorted(content_ids),
                "alternatives_rejected": ["Keep page behavior separate."],
            }
        )
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if not item["component_id"].startswith("page-content-")
        ]
        plan["component_definitions"].append(
            {
                "component_id": "empty-shared-content",
                "name": "Empty shared content",
                "kind": "component",
                "scope": "shared",
                "reuse_mode": "complete",
                "responsibility": "Claim a complete shared responsibility.",
                "owns": ["No evidenced invariant."],
                "excludes": ["Page-specific facts."],
                "capabilities": [],
                "slots": [],
                "data_roles": [],
                "action_roles": [],
            }
        )
        for instance in plan["component_instances"]:
            if content_ids.intersection(instance["candidate_ids"]):
                instance["component_id"] = "empty-shared-content"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("unsupported_abstraction", recorded.stderr)

    def test_verify_freezes_component_semantics_without_implementation(self) -> None:
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        payload = json.loads(verified.stdout)
        self.assertEqual(payload["state"], "locked")
        checklist = read_json(self.stage_dir / "checklist.json")
        self.assertTrue(
            all(item["status"] == "completed" for item in checklist["nodes"])
        )
        self.assertEqual(
            read_json(self.stage_dir / "state.json")["checklist_sha256"],
            hashlib.sha256((self.stage_dir / "checklist.json").read_bytes()).hexdigest(),
        )
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertEqual(lock["schema"], "icp.component-design.lock.v8")
        self.assertEqual(lock["stage_boundary"], "component-semantics-only")
        self.assertNotIn("business_rules", lock)
        self.assertNotIn("implementation", lock)
        self.assertEqual(len(lock["pages"]), 2)
        locked_facts = [
            fact
            for page in lock["pages"]
            for candidate in page["candidates"]
            for fact in candidate["facts"]
        ]
        self.assertTrue(locked_facts)
        self.assertTrue(
            all(fact["evidence_class"] == "business_source" for fact in locked_facts)
        )
        self.assertEqual(len(lock["page_compositions"]), 2)
        final_component_ids = {
            instance["component_id"]
            for composition in lock["page_compositions"]
            for instance in composition["instances"]
        }
        self.assertEqual(
            final_component_ids,
            {"shared-page-shell", "page-content-1", "page-content-2"},
        )
        self.assertTrue(
            all(
                entry["status"] == "replaced"
                for entry in lock["cache_view"]["candidate_entries"]
            )
        )
        stage_result = read_json(self.stage_dir / "stage-result.json")
        self.assertEqual(
            stage_result["schema"], "icp.component-design.stage-result.v8"
        )
        self.assertEqual(stage_result["status"], "complete")
        self.assertEqual(
            stage_result["artifacts"]["block_component_bindings"],
            {
                "path": "block-component-bindings.json",
                "sha256": hashlib.sha256(
                    (self.stage_dir / "block-component-bindings.json").read_bytes()
                ).hexdigest(),
            },
        )
        repeated = self.verify()
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["resumed"])

    def test_verify_binds_every_extract_block_to_its_final_component(self) -> None:
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        binding_path = self.stage_dir / "block-component-bindings.json"
        self.assertTrue(binding_path.is_file())
        bindings = read_json(binding_path)
        catalog = read_json(self.stage_dir / "source-catalog.json")
        lock = read_json(self.stage_dir / "component-lock.json")
        expected_blocks = {
            (design["design_name"], block["block_id"]): block
            for design in catalog["designs"]
            for block in design["blocks"]
        }
        actual_blocks = {
            (item["design_name"], item["block"]["block_id"]): item["block"]
            for item in bindings["bindings"]
        }
        self.assertEqual(actual_blocks, expected_blocks)
        self.assertEqual(len(bindings["bindings"]), len(expected_blocks))
        self.assertEqual(bindings["binding_count"], len(expected_blocks))
        self.assertEqual(bindings["source_catalog_sha256"], lock["source_hashes"]["source_catalog_sha256"])
        self.assertEqual(
            lock["block_component_bindings"],
            {
                "path": "block-component-bindings.json",
                "sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
                "design_count": len(catalog["designs"]),
                "binding_count": len(expected_blocks),
            },
        )
        final_components = {
            definition["component_id"] for definition in lock["component_definitions"]
        }
        for item in bindings["bindings"]:
            self.assertIn(item["component_id"], final_components)
            self.assertTrue(item["design_instance_id"])
            self.assertTrue(item["semantic_component_instance_id"])
            self.assertTrue(item["candidate_id"])
        shared_shell_bindings = [
            item
            for item in bindings["bindings"]
            if item["component_id"] == "shared-page-shell"
        ]
        self.assertEqual(len(shared_shell_bindings), 2)
        self.assertEqual(
            {item["design_name"] for item in shared_shell_bindings},
            {"Design A", "Design B"},
        )
        self.assertEqual(
            len({item["design_instance_id"] for item in shared_shell_bindings}), 2
        )

    def test_verify_freezes_complete_component_bound_layout_inputs(self) -> None:
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        bindings = read_json(self.stage_dir / "block-component-bindings.json")
        catalog = read_json(self.stage_dir / "source-catalog.json")
        layout_inputs = bindings["layout_inputs"]
        self.assertEqual(
            {item["design_state_id"] for item in layout_inputs},
            {item["design_name"] for item in catalog["designs"]},
        )
        for layout_input in layout_inputs:
            self.assertEqual(
                set(layout_input),
                {
                    "page_key",
                    "design_state_id",
                    "root_instance_id",
                    "reference",
                    "instances",
                    "blocks_by_id",
                    "source_nodes_by_id",
                    "component_definitions_by_id",
                    "platform_context",
                },
            )
            self.assertEqual(
                layout_input["reference"]["coordinate_contract"],
                {"supported_frame_spaces": ["canvas", "artboard", "parent"]},
            )
            self.assertEqual(
                set(layout_input["source_nodes_by_id"]),
                {
                    node_id
                    for block in layout_input["blocks_by_id"].values()
                    for node_id in block["ordered_source_node_ids"]
                },
            )
            self.assertEqual(
                set(layout_input["component_definitions_by_id"]),
                {item["component_id"] for item in self.valid_abstraction_plan()["component_definitions"]},
            )
            root = next(
                item
                for item in layout_input["instances"]
                if item["instance_id"] == layout_input["root_instance_id"]
            )
            self.assertIsNone(root["parent_instance_id"])
            self.assertEqual(root["slot"], "root")
            siblings: dict[tuple[object, object], list[int]] = {}
            for item in layout_input["instances"]:
                siblings.setdefault(
                    (item["parent_instance_id"], item["slot"]), []
                ).append(item["order"])
            self.assertTrue(
                all(sorted(orders) == list(range(len(orders))) for orders in siblings.values())
            )
            serialized = json.dumps(layout_input, ensure_ascii=False)
            self.assertNotIn("source_bundle", serialized)
            self.assertNotIn("interaction_description", serialized)

    def test_locked_block_component_bindings_cannot_be_changed(self) -> None:
        self.seal_all_pages()
        recorded = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        self.assertEqual(self.verify().returncode, 0)
        binding_path = self.stage_dir / "block-component-bindings.json"
        bindings = read_json(binding_path)
        bindings["bindings"][0]["component_id"] = "different-component"
        write_json(binding_path, bindings)

        repeated = self.verify()

        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("component_design_locked", repeated.stderr)

    def test_exact_business_source_may_legitimately_contain_todo_text(self) -> None:
        self.bundle_path = self.build_source_bundle(source_contains_todo=True)
        source_bundle = read_json(self.bundle_path)
        self.project = create_verified_extract(
            self.root / "todo-extract",
            {
                URL_A: "Show the customer's TODO items exactly as the business source names them.",
                URL_B: "Show the selected withdrawal offer.",
            },
        )
        self.stage_dir = self.project / ".icp" / "component-design"
        self.bundle_path = self.project / ".icp" / "source" / "source-bundle.json"
        write_json(self.bundle_path, source_bundle)
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            recorded = self.record_page(page, self.valid_page_facts(page))
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        abstraction = self.record_abstraction(self.valid_abstraction_plan())
        self.assertEqual(
            abstraction.returncode, 0, abstraction.stdout + abstraction.stderr
        )

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_verified_historical_component_can_be_reused_without_a_score(self) -> None:
        begun = self.begin(self.historical_catalog())
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            recorded = self.record_page(page, self.valid_page_facts(page))
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
        plan = self.valid_abstraction_plan()
        shell_decision = next(
            item for item in plan["decisions"] if item["kind"] == "extract-container"
        )
        shell_decision["kind"] = "reuse-existing"
        shell_decision["target_component_id"] = "historical-page-shell"
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if item["component_id"] != "shared-page-shell"
        ]
        for instance in plan["component_instances"]:
            if instance["component_id"] == "shared-page-shell":
                instance["component_id"] = "historical-page-shell"

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        canonical = read_json(self.stage_dir / "abstraction-decisions.json")
        reused = next(
            item for item in canonical["decisions"] if item["kind"] == "reuse-existing"
        )
        self.assertNotIn("score", reused)
        self.assertNotIn("similarity", reused)
        self.assertEqual(reused["target_component_id"], "historical-page-shell")

    def test_verified_shared_history_can_be_reused_by_one_current_instance(self) -> None:
        begun = self.begin(self.historical_catalog())
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            self.assertEqual(
                self.record_page(page, self.valid_page_facts(page)).returncode, 0
            )
        plan = self.valid_abstraction_plan()
        shell_decision = next(
            item for item in plan["decisions"] if item["kind"] == "extract-container"
        )
        first_shell_candidate, second_shell_candidate = shell_decision["candidate_ids"]
        shell_decision.update(
            {
                "decision_id": "reuse-one-historical-shell",
                "kind": "reuse-existing",
                "candidate_ids": [first_shell_candidate],
                "target_component_id": "historical-page-shell",
                "rationale": "Reuse one already-verified shared shell instance.",
                "evidence_candidate_ids": [first_shell_candidate],
                "alternatives_rejected": ["Duplicate the verified shell locally."],
            }
        )
        plan["decisions"].append(
            {
                "decision_id": "keep-other-shell-local",
                "kind": "keep-separate",
                "candidate_ids": [second_shell_candidate],
                "target_component_id": "other-local-shell",
                "rationale": "This candidate does not use the historical shell.",
                "evidence_candidate_ids": [second_shell_candidate],
                "alternatives_rejected": ["Force an unrelated historical reuse."],
            }
        )
        shared_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == "shared-page-shell"
        )
        shared_definition.update(
            {
                "component_id": "other-local-shell",
                "name": "Other local shell",
                "scope": "local",
                "reuse_mode": "local",
            }
        )
        for instance in plan["component_instances"]:
            if first_shell_candidate in instance["candidate_ids"]:
                instance["component_id"] = "historical-page-shell"
            elif second_shell_candidate in instance["candidate_ids"]:
                instance["component_id"] = "other-local-shell"

        recorded = self.record_abstraction(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_project_catalog_rejects_unverified_provenance_hash(self) -> None:
        catalog = self.historical_catalog()
        catalog["components"][0]["provenance"]["sha256"] = "f" * 64

        begun = self.begin(catalog)

        self.assertNotEqual(begun.returncode, 0)
        self.assertIn("historical_component_evidence", begun.stderr)

    def test_code_derived_history_requires_an_explicit_adapted_definition(self) -> None:
        begun = self.begin(self.historical_catalog("code-derived"))
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            self.assertEqual(
                self.record_page(page, self.valid_page_facts(page)).returncode, 0
            )
        plan = self.valid_abstraction_plan()
        shell_decision = next(
            item for item in plan["decisions"] if item["kind"] == "extract-container"
        )
        shell_decision["kind"] = "reuse-existing"
        shell_decision["target_component_id"] = "historical-page-shell"
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if item["component_id"] != "shared-page-shell"
        ]
        for instance in plan["component_instances"]:
            if instance["component_id"] == "shared-page-shell":
                instance["component_id"] = "historical-page-shell"

        rejected = self.record_abstraction(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("historical_component_evidence", rejected.stderr)

        shell_decision["kind"] = "adapt-existing"
        shell_decision["source_component_id"] = "historical-page-shell"
        shell_decision["target_component_id"] = "adapted-page-shell"
        adapted_definition = self.historical_catalog("code-derived")["components"][0][
            "semantic_contract"
        ]
        adapted_definition["component_id"] = "adapted-page-shell"
        adapted_definition["name"] = "Adapted page shell"
        plan["component_definitions"].append(adapted_definition)
        for instance in plan["component_instances"]:
            if instance["component_id"] == "historical-page-shell":
                instance["component_id"] = "adapted-page-shell"

        accepted = self.record_abstraction(plan)

        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        canonical = read_json(self.stage_dir / "abstraction-decisions.json")
        adapted = next(
            item for item in canonical["decisions"] if item["kind"] == "adapt-existing"
        )
        self.assertEqual(adapted["source_component_id"], "historical-page-shell")
        self.assertEqual(adapted["target_component_id"], "adapted-page-shell")

    def test_adaptation_must_not_overwrite_a_historical_component_id(self) -> None:
        begun = self.begin(self.historical_catalog("code-derived"))
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            self.assertEqual(
                self.record_page(page, self.valid_page_facts(page)).returncode, 0
            )
        plan = self.valid_abstraction_plan()
        shell_decision = next(
            item for item in plan["decisions"] if item["kind"] == "extract-container"
        )
        shell_decision["kind"] = "adapt-existing"
        shell_decision["source_component_id"] = "historical-page-shell"
        shell_decision["target_component_id"] = "historical-page-shell"
        shell_definition = next(
            item
            for item in plan["component_definitions"]
            if item["component_id"] == "shared-page-shell"
        )
        shell_definition["component_id"] = "historical-page-shell"
        for instance in plan["component_instances"]:
            if instance["component_id"] == "shared-page-shell":
                instance["component_id"] = "historical-page-shell"

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("historical_component_collision", recorded.stderr)

    def test_historical_reuse_cannot_create_a_supersession_cycle(self) -> None:
        candidate_id = (
            "page-"
            + hashlib.sha256("Design A".encode("utf-8")).hexdigest()[:16]
            + "-shell"
        )
        catalog = self.historical_catalog(component_id=candidate_id)
        begun = self.begin(catalog)
        self.assertEqual(begun.returncode, 0, begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        for page in pages:
            self.assertEqual(
                self.record_page(page, self.valid_page_facts(page)).returncode, 0
            )
        plan = self.valid_abstraction_plan()
        shell_decision = next(
            item for item in plan["decisions"] if item["kind"] == "extract-container"
        )
        shell_decision["kind"] = "reuse-existing"
        shell_decision["target_component_id"] = candidate_id
        plan["component_definitions"] = [
            item
            for item in plan["component_definitions"]
            if item["component_id"] != "shared-page-shell"
        ]
        for instance in plan["component_instances"]:
            if instance["component_id"] == "shared-page-shell":
                instance["component_id"] = candidate_id

        recorded = self.record_abstraction(plan)

        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn("replacement_cycle", recorded.stderr)


if __name__ == "__main__":
    unittest.main()
