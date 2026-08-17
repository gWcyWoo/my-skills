from __future__ import annotations

import hashlib
import importlib.util
import json
import fcntl
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
    ) -> Path:
        raw_rows = {
            "Design A": member_row(
                "Design A",
                "design-a",
                URL_A,
                "Show the available withdrawal offer.",
                "Selecting the offer navigates to Design B.",
                "Read the amount from the loan detail response.",
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
                                "relation_kind": "navigation",
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
        bundle_path = self.root / "source-bundle.json"
        write_json(raw_path, raw_rows)
        write_json(analysis_path, analysis)
        write_json(catalog_path, title_catalog)
        write_json(review_path, closure_review)
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
            str(IOLE_MAPPING),
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        bundle_path.write_text(result.stdout, encoding="utf-8")
        return bundle_path

    def begin(self, project_catalog: dict | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            "begin",
            "--project-root",
            str(self.project),
            "--source-bundle",
            str(self.bundle_path),
        ]
        if project_catalog is not None:
            catalog_path = self.root / "project-component-catalog.json"
            write_json(catalog_path, project_catalog)
            args.extend(["--project-catalog", str(catalog_path)])
        return run_command(SCRIPT, *args)

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
                if fact["kind"] not in {"condition", "state", "trigger", "behavior"}:
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
                    }
                )
        facts["interaction_items"] = items
        return facts

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
            return self.with_interaction_items({
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
            })
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
        return self.with_interaction_items({
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
        })

    def page_facts_v2(self, facts: dict) -> dict:
        facts["schema"] = "icp.component-design.page-facts.v2"
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

    def record_page(
        self, page: dict[str, str], facts: dict
    ) -> subprocess.CompletedProcess[str]:
        drafted = self.record_page_draft(page, facts)
        if drafted.returncode != 0:
            return drafted
        return self.record_page_review(page, self.page_review(page))

    def record_page_draft(
        self, page: dict[str, str], facts: dict
    ) -> subprocess.CompletedProcess[str]:
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
            self.assertEqual(template["schema"], "icp.component-design.page-facts.v2")
            self.assertEqual(template["page_key"], page["page_key"])
            self.assertEqual(template["member_title"], page["member_title"])
            self.assertTrue(template["source_coverage"])
            self.assertEqual(template["candidates"], [])
            self.assertEqual(template["design_compositions"], [])
            for clause in template["source_coverage"]:
                self.assertEqual(clause["segments"], [])
        self.assertFalse((self.stage_dir / "business-rules.input.json").exists())

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
        frozen_bundle = read_json(self.stage_dir / "iole-source-bundle.json")
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
            write_json(path, self.valid_page_facts(page))
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
            ["behavior", "state"],
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
            }
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
        self.assertEqual(item["behavior"]["fact_id"], interaction_fact["fact_id"])

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

    def test_interaction_description_can_split_into_all_four_atomic_item_types(self) -> None:
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
                for field in ("condition", "state", "trigger", "behavior")
                if item[field] is not None
            },
            {"condition", "state", "trigger", "behavior"},
        )
        self.assertTrue(
            all(
                sum(
                    item[field] is not None
                    for field in ("condition", "state", "trigger", "behavior")
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
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
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
                for field in ("condition", "state", "trigger", "behavior")
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
        facts = self.page_facts_v2(self.valid_page_facts(page))
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
                facts = self.page_facts_v2(self.valid_page_facts(page))
                self.add_design_visible_fact(facts, kind=forbidden_kind)

                recorded = self.record_page(page, facts)

                self.assertNotEqual(recorded.returncode, 0)
                self.assertIn("invalid_fact_evidence_class", recorded.stderr)

    def test_design_visible_fact_rejects_source_refs_and_missing_basis(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v2(self.valid_page_facts(page))
        source_ref = facts["candidates"][1]["facts"][0]["source_refs"][0]
        self.add_design_visible_fact(facts, source_refs=[source_ref])

        with_source = self.record_page(page, facts)

        self.assertNotEqual(with_source.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", with_source.stderr)

        facts = self.page_facts_v2(self.valid_page_facts(page))
        self.add_design_visible_fact(facts, visible_basis=None)

        without_basis = self.record_page(page, facts)

        self.assertNotEqual(without_basis.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", without_basis.stderr)

        facts = self.page_facts_v2(self.valid_page_facts(page))
        self.add_design_visible_fact(facts, visible_basis=" ")

        with_empty_basis = self.record_page(page, facts)

        self.assertNotEqual(with_empty_basis.returncode, 0)
        self.assertIn("invalid_fact_evidence_class", with_empty_basis.stderr)

    def test_business_source_fact_rejects_visible_basis(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stderr)
        page = json.loads(begun.stdout)["pages"][0]
        facts = self.page_facts_v2(self.valid_page_facts(page))
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
        facts = self.page_facts_v2(self.valid_page_facts(page))
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
        facts = self.page_facts_v2(self.valid_page_facts(page))
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

    def test_single_candidate_shared_container_needs_source_only_component_declaration(self) -> None:
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
        lock = read_json(self.stage_dir / "component-lock.json")
        self.assertEqual(lock["schema"], "icp.component-design.lock.v6")
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
            stage_result["schema"], "icp.component-design.stage-result.v6"
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
