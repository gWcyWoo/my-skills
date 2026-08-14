#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from shared_core import visual_evidence_v1 as visual
from shared_core import visual_verification_v1 as visual_verification


SCRIPT = Path(__file__).with_name("icp_flow_job_v1.py")
ICP_SKILL = Path(__file__).parents[1] / "SKILL.md"
WORKER_CONTRACT = Path(__file__).parents[1] / "references" / "worker-node-contract-v1.md"
WORKER_CONTRACT_V2 = Path(__file__).parents[1] / "references" / "worker-node-contract-v2.md"
LEGACY_WORKER_CONTRACT_SHA256 = "211a6c71412a55133510cb0de14f733fe560c0638656282f4c5cfd3459ac4553"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
)


def make_project(root: Path) -> tuple[Path, str]:
    project_root = root / "project"
    project_root.mkdir()
    (project_root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=project_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ICP Flow Selftest",
            "-c",
            "user.email=icp-flow@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=project_root,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return project_root.resolve(), revision


def flow_job(project_root: Path, revision: str) -> dict[str, object]:
    return {
        "kind": "icp.external-flow-job.v3",
        "schema_version": 3,
        "job_id": "iole:client:flow-abc:review-0:aaaaaaaaaaaa",
        "flow_id": "iole-flow-abc",
        "project_root": str(project_root),
        "base_revision": revision,
        "platform": "android-kotlin",
        "profile": "android-kotlin-standard",
        "role": "client",
        "root_page_id": "PAGE-001",
        "member_digests": {
            "PAGE-001": "a" * 64,
            "PAGE-002": "b" * 64,
        },
        "members": [
            {
                "page_id": "PAGE-001",
                "title": "申请首页",
                "route": "ApplicationScreen",
                "requirement": "实现入口并导航到职业信息页。",
                "acceptance_criteria": [],
                "design_source": "lanhu-figma",
                "design_ref": "https://design.example/PAGE-001",
                "mode": "implement",
                "review": None,
            },
            {
                "page_id": "PAGE-002",
                "title": "职业信息页",
                "route": "OccupationScreen",
                "requirement": "实现职业信息表单。",
                "acceptance_criteria": [],
                "design_source": "lanhu-figma",
                "design_ref": "https://design.example/PAGE-002",
                "mode": "implement",
                "review": None,
            },
        ],
        "component_decisions": [
            {
                "component_id": "shared-form-card",
                "name": "FormCard",
                "decision": "extend",
                "code_path": "app/src/main/java/ui/components/FormCard.kt",
                "allowed_paths": [
                    "app/src/main/java/ui/components/FormCard.kt",
                    "app/src/test/java/ui/components/",
                ],
                "consumers": ["PAGE-001", "PAGE-002"],
                "evidence": "Closest existing semantic component.",
            }
        ],
        "component_analysis": {
            "inventory_source": "project-scan",
            "searched_paths": ["app/src/main"],
            "summary": "Inspected existing shared and feature-local components.",
        },
        "interaction_edges": [
            {
                "from": "PAGE-001",
                "to": "PAGE-002",
                "target_title": "职业信息页",
            }
        ],
        "execution_dag": [
            {
                "node_id": "component:shared-form-card",
                "type": "shared-component",
                "depends_on": [],
                "allowed_paths": [
                    "app/src/main/java/ui/components/FormCard.kt",
                    "app/src/test/java/ui/components/",
                ],
                "page_ids": ["PAGE-001", "PAGE-002"],
            },
            {
                "node_id": "page:PAGE-002",
                "type": "page",
                "depends_on": ["component:shared-form-card"],
                "allowed_paths": [
                    "app/src/main/java/features/application/OccupationScreen.kt",
                    "app/src/test/java/features/application/OccupationScreenTest.kt",
                ],
                "page_ids": ["PAGE-002"],
            },
            {
                "node_id": "page:PAGE-001",
                "type": "page",
                "depends_on": [
                    "component:shared-form-card",
                    "page:PAGE-002",
                ],
                "allowed_paths": [
                    "app/src/main/java/features/application/ApplicationScreen.kt",
                    "app/src/test/java/features/application/ApplicationScreenTest.kt",
                ],
                "page_ids": ["PAGE-001"],
            },
        ],
        "execution_order": [
            "component:shared-form-card",
            "page:PAGE-002",
            "page:PAGE-001",
        ],
    }


def lossless_flow_job(project_root: Path, revision: str) -> dict[str, object]:
    job = flow_job(project_root, revision)
    job["kind"] = "icp.external-flow-job.v4"
    job["schema_version"] = 4
    members = job["members"]
    assert isinstance(members, list)
    digests: dict[str, str] = {}
    for member in members:
        assert isinstance(member, dict)
        original_requirement = str(member["requirement"])
        interaction = (
            "点击继续 →「职业信息页」" if member["page_id"] == "PAGE-001" else ""
        )
        contract: dict[str, object] = {
            "kind": "iole.sheet-member-contract.v1",
            "schema_version": 1,
            "title": member["title"],
            "route": member["route"],
            "design_ref": member["design_ref"],
            "interaction": interaction,
            "requirement_sections": [
                {"label": "UI补充描述", "value": original_requirement}
            ],
            "acceptance_sections": [],
        }
        contract["contract_digest"] = hashlib.sha256(
            json.dumps(
                contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        member["requirement"] = f"UI补充描述: {original_requirement}"
        member["interaction"] = interaction
        member["source_contract"] = contract
        digests[str(member["page_id"])] = hashlib.sha256(
            json.dumps(
                member,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    job["member_digests"] = digests
    return job


def contract_compiled_flow_job(project_root: Path, revision: str) -> dict[str, object]:
    job = lossless_flow_job(project_root, revision)
    job["kind"] = "icp.external-flow-job.v5"
    job["schema_version"] = 5
    members = job["members"]
    assert isinstance(members, list) and isinstance(members[0], dict)
    member = members[0]
    source_contract = member["source_contract"]
    assert isinstance(source_contract, dict)
    source_contract["interaction"] = "Tap continue\nOpen the detail page"
    source_contract["requirement_sections"] = [
        {"label": "UI notes", "value": "Keep the supplied icon\n  Preserve spacing"},
        {"label": "API", "value": ""},
    ]
    source_contract["acceptance_sections"] = [
        {"prefix": "UT", "value": "formatting remains stable"},
        {"prefix": "IT", "value": "continue opens detail\nback returns"},
        {"prefix": "E2E", "value": "complete the reachable flow"},
    ]
    source_contract["contract_digest"] = hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in source_contract.items()
                if key != "contract_digest"
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    member["interaction"] = source_contract["interaction"]
    member["requirement"] = (
        "UI notes: Keep the supplied icon\n  Preserve spacing"
    )
    member["acceptance_criteria"] = [
        "UT: formatting remains stable",
        "IT: continue opens detail\nback returns",
        "E2E: complete the reachable flow",
    ]
    member_digests = job["member_digests"]
    assert isinstance(member_digests, dict)
    member_digests[str(member["page_id"])] = hashlib.sha256(
        json.dumps(
            member,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return job


def implementation_contract_for(
    compiler_input: dict[str, object], state_root: Path
) -> dict[str, object]:
    source_clauses = compiler_input["source_clauses"]
    execution_dag = compiler_input["execution_dag"]
    assert isinstance(source_clauses, list) and isinstance(execution_dag, list)
    owner_by_page: dict[str, str] = {}
    for node in execution_dag:
        assert isinstance(node, dict)
        if node["type"] == "page":
            for page_id in node["page_ids"]:
                owner_by_page[str(page_id)] = str(node["node_id"])
    evidence_root = state_root / "compiler-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    page_ids = list(dict.fromkeys(str(clause["page_id"]) for clause in source_clauses))
    design_contracts: list[dict[str, object]] = []
    state_by_page: dict[str, str] = {}
    for page_id in page_ids:
        reference = evidence_root / f"{page_id}.png"
        reference.write_bytes(PNG)
        state_id = f"state:{page_id}:default"
        state_by_page[page_id] = state_id
        design_contracts.append(
            {
                "design_id": f"design:{page_id}",
                "page_id": page_id,
                "reference_artifacts": [
                    {
                        "artifact_id": f"reference:{page_id}",
                        "path": str(reference.resolve()),
                        "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                    }
                ],
                "states": [
                    {
                        "state_id": state_id,
                        "name": "default",
                        "setup": "Open the page from a clean state.",
                        "reference_artifact_id": f"reference:{page_id}",
                        "viewport": {
                            "width": 1,
                            "height": 1,
                            "density": 1.0,
                            "font_scale": 1.0,
                            "locale": "zh-CN",
                            "theme": "light",
                            "system_bars": "excluded",
                            "animations_disabled": True,
                        },
                        "anchors": [
                            {
                                "name": "root_top",
                                "node_id": "root",
                                "attribute": "top",
                                "expected": 0.0,
                                "tolerance": 0.0,
                            }
                        ],
                        "regions": [
                            {
                                "name": "full_page",
                                "bbox": [0.0, 0.0, 1.0, 1.0],
                                "max_mismatch_ratio": 0.02,
                            }
                        ],
                        "typography": [],
                        "colors": [],
                        "assets": [],
                    }
                ],
            }
        )
    observable_clauses: list[dict[str, object]] = []
    acceptance_cases: list[dict[str, object]] = []
    tdd_slices: list[dict[str, object]] = []
    for index, source_clause in enumerate(source_clauses, start=1):
        assert isinstance(source_clause, dict)
        source_kind = str(source_clause["source_kind"])
        page_id = str(source_clause["page_id"])
        required = list(source_clause["required_evidence"])
        if source_kind == "design":
            clause_type = "visual"
            required = list(dict.fromkeys([*required, "visual"]))
            design_state_ids = [state_by_page[page_id]]
        elif source_kind == "interface":
            clause_type = "interface"
            design_state_ids = []
        else:
            clause_type = "behavior"
            required = list(dict.fromkeys([*required, "integration"]))
            design_state_ids = []
        clause_body = {
            "page_id": page_id,
            "owner_node_id": owner_by_page[page_id],
            "clause_type": clause_type,
            "source_clause_ids": [source_clause["clause_id"]],
            "preconditions": ["The owning page is reachable."],
            "action": f"Exercise source clause {index}.",
            "expected_observables": [str(source_clause["exact_text"])],
            "forbidden_effects": [],
            "required_evidence": required,
            "design_state_ids": design_state_ids,
        }
        clause_id = "observable:" + hashlib.sha256(
            json.dumps(
                clause_body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        observable_clauses.append({"clause_id": clause_id, **clause_body})
        integration_case_ids: list[str] = []
        for evidence_kind in required:
            if evidence_kind not in {"unit", "integration", "e2e"}:
                continue
            case_id = f"case:{index}:{evidence_kind}"
            acceptance_cases.append(
                {
                    "case_id": case_id,
                    "clause_ids": [clause_id],
                    "level": evidence_kind,
                    "preconditions": ["The owning page is reachable."],
                    "action": clause_body["action"],
                    "expected_observables": clause_body["expected_observables"],
                }
            )
            if evidence_kind == "integration":
                integration_case_ids.append(case_id)
        if integration_case_ids:
            tdd_slices.append(
                {
                    "slice_id": f"slice:{index}",
                    "owner_node_id": owner_by_page[page_id],
                    "clause_ids": [clause_id],
                    "integration_case_ids": integration_case_ids,
                    "red_contract": "Fail for missing or wrong observable behavior.",
                    "green_scope": "Implement only this observable behavior.",
                }
            )
    return {
        "kind": "icp.implementation-contract.v1",
        "schema_version": 1,
        "job_id": compiler_input["job_id"],
        "job_digest": compiler_input["job_digest"],
        "compiler_input_digest": hashlib.sha256(
            json.dumps(
                compiler_input,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "source_clauses_digest": compiler_input["source_clauses_digest"],
        "context_source_clauses": [],
        "public_interfaces": [
            {
                "interface_id": f"interface:{node['node_id']}",
                "owner_node_id": node["node_id"],
                "public_target": f"PublicTarget({node['node_id']})",
                "inputs": [],
                "outputs": [],
            }
            for node in execution_dag
        ],
        "ownership": [
            {
                "node_id": node["node_id"],
                "allowed_paths": node["allowed_paths"],
            }
            for node in execution_dag
        ],
        "design_contracts": design_contracts,
        "observable_clauses": observable_clauses,
        "acceptance_cases": acceptance_cases,
        "tdd_slices": tdd_slices,
        "untested_boundaries": [],
    }


def prepare_v5_contract(
    root: Path, project_root: Path, revision: str
) -> tuple[Path, dict[str, object], dict[str, object]]:
    job_path = root / "v5-job.json"
    job_path.write_text(
        json.dumps(contract_compiled_flow_job(project_root, revision)),
        encoding="utf-8",
    )
    prepared = run("prepare", "--job", str(job_path))
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    compiler_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
    compiler_input = json.loads(
        Path(compiler_decision["compiler_input"]).read_text(encoding="utf-8")
    )
    contract = implementation_contract_for(
        compiler_input, Path(compiler_decision["compiler_input"]).parent
    )
    contract_path = root / "candidate-implementation-contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    recorded = run(
        "record-contract",
        "--job",
        str(job_path),
        "--contract",
        str(contract_path),
    )
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    return job_path, contract, json.loads(recorded.stdout)


def write_v5_node_result(
    project_root: Path,
    decision: dict[str, object],
    contract: dict[str, object],
    *,
    omit_clause_id: str | None = None,
    wrong_visual_reference: bool = False,
    failed_test_report: bool = False,
) -> Path:
    result_path = Path(str(decision["worker_result"]))
    node_root = result_path.parent
    node_job = json.loads((node_root / "node-job.json").read_text(encoding="utf-8"))
    node = node_job["node"]
    binding = node_job["implementation_contract"]
    changed_relative = node["allowed_paths"][0]
    if changed_relative.endswith("/"):
        changed_relative += "Generated.kt"
    changed_path = project_root / changed_relative
    changed_path.parent.mkdir(parents=True, exist_ok=True)
    changed_path.write_text(f"// {node['node_id']}\n", encoding="utf-8")
    test_log = node_root / "node-tests.txt"
    test_log.write_text("passed\n", encoding="utf-8")
    evidence = ["node-tests.txt", "acceptance-evidence.json"]
    runtime_provenance_path = node_root / "runtime-provenance.json"
    runtime_actual_path = node_root / "runtime-actual.png"
    runtime_actual_path.write_bytes(b"runtime-capture")
    runtime_provenance_path.write_text(
        json.dumps(
            {
                "kind": "icp.runtime-provenance.v1",
                "actual_source": "emulator_screenshot",
                "actual_path": str(runtime_actual_path.resolve()),
                "actual_sha256": hashlib.sha256(
                    runtime_actual_path.read_bytes()
                ).hexdigest(),
                "capture_id": f"runtime:{node['node_id']}",
                "state_reset_id": f"reset:{node['node_id']}",
            }
        ),
        encoding="utf-8",
    )
    if node["type"] == "page":
        if wrong_visual_reference:
            (node_root / "design.png").write_bytes(PNG + b"wrong-reference")
        write_page_verification(node_root)
        evidence.append("visual-verification.json")
    owned_clause_ids = binding["owned_clause_ids"]
    clauses = {
        clause["clause_id"]: clause for clause in contract["observable_clauses"]
    }
    cases = contract["acceptance_cases"]
    junit_path = node_root / "junit.xml"
    suite = ET.Element(
        "testsuite", tests="0", failures="0", errors="0", skipped="0"
    )
    test_ids: set[str] = set()
    for case in cases:
        if case["level"] not in {"unit", "integration", "e2e"}:
            continue
        if not any(clause_id in owned_clause_ids for clause_id in case["clause_ids"]):
            continue
        test_id = f"test::{case['case_id']}"
        testcase = ET.SubElement(suite, "testcase", classname="fixture", name=test_id)
        if failed_test_report and not test_ids:
            ET.SubElement(testcase, "failure", message="expected observable missing")
        test_ids.add(test_id)
    suite.set("tests", str(len(test_ids)))
    ET.ElementTree(suite).write(junit_path, encoding="unicode")
    evidence.append("junit.xml")
    evidence_bindings: list[dict[str, object]] = []
    design_by_page = {
        design["page_id"]: design for design in contract["design_contracts"]
    }
    for clause_id in owned_clause_ids:
        if clause_id == omit_clause_id:
            continue
        clause = clauses[clause_id]
        for evidence_kind in clause["required_evidence"]:
            case_bindings: list[dict[str, str]] = []
            state_bindings: list[dict[str, str]] = []
            if evidence_kind == "contract":
                artifact_path = Path(binding["path"])
            elif evidence_kind == "design":
                artifact_path = Path(
                    design_by_page[clause["page_id"]]["reference_artifacts"][0][
                        "path"
                    ]
                )
            elif evidence_kind == "visual":
                artifact_path = node_root / "visual-verification.json"
                state_bindings = [
                    {
                        "design_state_id": state_id,
                        "visual_state_name": next(
                            state["name"]
                            for state in design_by_page[clause["page_id"]]["states"]
                            if state["state_id"] == state_id
                        ),
                    }
                    for state_id in clause["design_state_ids"]
                ]
            elif evidence_kind == "runtime":
                artifact_path = runtime_provenance_path
                if "runtime-provenance.json" not in evidence:
                    evidence.append("runtime-provenance.json")
            else:
                artifact_path = junit_path
                case_bindings = [
                    {
                        "acceptance_case_id": case["case_id"],
                        "test_id": f"test::{case['case_id']}",
                    }
                    for case in cases
                    if case["level"] == evidence_kind
                    and clause_id in case["clause_ids"]
                ]
            evidence_bindings.append(
                {
                    "clause_id": clause_id,
                    "evidence_kind": evidence_kind,
                    "artifact_path": str(artifact_path.resolve()),
                    "artifact_sha256": hashlib.sha256(
                        artifact_path.read_bytes()
                    ).hexdigest(),
                    "case_bindings": case_bindings,
                    "state_bindings": state_bindings,
                }
            )
    acceptance_path = node_root / "acceptance-evidence.json"
    acceptance_path.write_text(
        json.dumps(
            {
                "kind": "icp.acceptance-evidence.v1",
                "schema_version": 1,
                "node_id": node["node_id"],
                "implementation_contract_sha256": binding["sha256"],
                "bindings": evidence_bindings,
            }
        ),
        encoding="utf-8",
    )
    result_path.write_text(
        json.dumps(
            {
                "kind": "icp.worker-node-result.v2",
                "schema_version": 2,
                "node_id": node["node_id"],
                "status": "passed",
                "changed_files": [changed_relative],
                "verification": {
                    "focused_tests": "passed",
                    "scope": "passed",
                    "self_check": "passed",
                },
                "evidence": evidence,
                "loaded_contracts": {
                    "icp_skill_sha256": hashlib.sha256(ICP_SKILL.read_bytes()).hexdigest(),
                    "worker_contract_sha256": hashlib.sha256(
                        WORKER_CONTRACT_V2.read_bytes()
                    ).hexdigest(),
                },
                "implementation_contract": binding,
                "acceptance_evidence": "acceptance-evidence.json",
                "error_code": None,
            }
        ),
        encoding="utf-8",
    )
    return result_path


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


class LosslessFlowContractTests(unittest.TestCase):
    def test_v5_rejects_native_design_contract_without_measurable_node_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input_path = Path(decision["compiler_input"])
            contract = implementation_contract_for(
                json.loads(compiler_input_path.read_text(encoding="utf-8")),
                compiler_input_path.parent,
            )
            for design in contract["design_contracts"]:
                for state in design["states"]:
                    for anchor in state["anchors"]:
                        anchor.pop("node_id")
                        anchor.pop("attribute")
                    for region in state["regions"]:
                        region.pop("bbox")
            contract_path = root / "unmeasurable-native-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertIn("native design anchor measurement identity is missing", recorded.stdout)

    def test_v5_rejects_native_design_contract_without_region_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input_path = Path(decision["compiler_input"])
            contract = implementation_contract_for(
                json.loads(compiler_input_path.read_text(encoding="utf-8")),
                compiler_input_path.parent,
            )
            for design in contract["design_contracts"]:
                for state in design["states"]:
                    for region in state["regions"]:
                        region.pop("bbox")
            contract_path = root / "native-contract-without-region-bbox.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertIn("native design region bbox is missing", recorded.stdout)

    def test_v5_record_contract_accepts_the_published_target_path_with_pretty_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input_path = Path(decision["compiler_input"])
            compiler_input = json.loads(compiler_input_path.read_text(encoding="utf-8"))
            contract = implementation_contract_for(
                compiler_input, compiler_input_path.parent
            )
            contract.pop("context_source_clauses")
            published_target = Path(decision["implementation_contract"])
            published_target.write_text(
                json.dumps(contract, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(published_target),
            )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_v5_allows_a_requirement_clause_to_compile_as_visual_with_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input_path = Path(decision["compiler_input"])
            compiler_input = json.loads(compiler_input_path.read_text(encoding="utf-8"))
            contract = implementation_contract_for(
                compiler_input, compiler_input_path.parent
            )
            source_by_id = {
                clause["clause_id"]: clause
                for clause in compiler_input["source_clauses"]
            }
            observable = next(
                clause
                for clause in contract["observable_clauses"]
                if any(
                    source_by_id[source_id]["source_kind"] == "requirement"
                    for source_id in clause["source_clause_ids"]
                )
            )
            observable["clause_type"] = "visual"
            observable["required_evidence"] = list(
                dict.fromkeys([*observable["required_evidence"], "visual"])
            )
            page_design = next(
                design
                for design in contract["design_contracts"]
                if design["page_id"] == observable["page_id"]
            )
            observable["design_state_ids"] = [
                state["state_id"] for state in page_design["states"]
            ]
            contract_path = root / "visual-requirement-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_v5_accepts_a_provenance_bound_task_context_behavior_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input_path = Path(decision["compiler_input"])
            compiler_input = json.loads(compiler_input_path.read_text(encoding="utf-8"))
            state_root = compiler_input_path.parent
            contract = implementation_contract_for(compiler_input, state_root)
            provenance = state_root / "project-contract-retry.txt"
            provenance.write_text(
                "Existing public contract: retry invokes the status gateway once.\n",
                encoding="utf-8",
            )
            exact_text = "Retry invokes the existing status gateway exactly once."
            context_clause_id = "context:project-retry"
            contract["context_source_clauses"] = [
                {
                    "clause_id": context_clause_id,
                    "page_id": "PAGE-002",
                    "source_path": "/task-context/project-contract/retry",
                    "source_kind": "behavior",
                    "exact_text": exact_text,
                    "source_digest": hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
                    "required_evidence": ["integration"],
                    "origin": "project-contract",
                    "provenance_path": str(provenance.resolve()),
                    "provenance_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
                }
            ]
            owner = next(
                str(node["node_id"])
                for node in compiler_input["execution_dag"]
                if node["type"] == "page" and "PAGE-002" in node["page_ids"]
            )
            observable_id = "observable:project-retry"
            case_id = "case:project-retry:integration"
            contract["observable_clauses"].append(
                {
                    "clause_id": observable_id,
                    "page_id": "PAGE-002",
                    "owner_node_id": owner,
                    "clause_type": "behavior",
                    "source_clause_ids": [context_clause_id],
                    "preconditions": ["The status request previously failed."],
                    "action": "Invoke retry through the existing public interface.",
                    "expected_observables": [exact_text],
                    "forbidden_effects": ["Do not invent a language selector."],
                    "required_evidence": ["integration"],
                    "design_state_ids": [],
                }
            )
            contract["acceptance_cases"].append(
                {
                    "case_id": case_id,
                    "clause_ids": [observable_id],
                    "level": "integration",
                    "preconditions": ["The status request previously failed."],
                    "action": "Invoke retry.",
                    "expected_observables": [exact_text],
                }
            )
            contract["tdd_slices"].append(
                {
                    "slice_id": "slice:project-retry",
                    "owner_node_id": owner,
                    "clause_ids": [observable_id],
                    "integration_case_ids": [case_id],
                    "red_contract": "The existing retry contract is missing or wrong.",
                    "green_scope": "Preserve only the provenance-bound retry behavior.",
                }
            )
            contract_path = root / "context-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            provenance.write_text("changed after freeze\n", encoding="utf-8")
            dispatched = run("next-node", "--job", str(job_path))

        self.assertEqual(dispatched.returncode, 2)
        self.assertEqual(
            json.loads(dispatched.stdout)["reason"],
            "implementation contract context provenance digest mismatch",
        )

    def test_v5_recomputes_the_node_binding_instead_of_trusting_a_tampered_node_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, _ = prepare_v5_contract(root, project_root, revision)
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            self.assertEqual(
                run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(component_result),
                ).returncode,
                0,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            node_job_path = Path(page_decision["worker_prompt"]).with_name(
                "node-job.json"
            )
            node_job = json.loads(node_job_path.read_text(encoding="utf-8"))
            node_job["implementation_contract"]["owned_clause_ids"] = []
            node_job["implementation_contract"]["owned_acceptance_case_ids"] = []
            node_job["implementation_contract"]["owned_tdd_slice_ids"] = []
            node_job_path.write_text(json.dumps(node_job), encoding="utf-8")
            page_result = write_v5_node_result(project_root, page_decision, contract)

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 2)
        self.assertEqual(
            json.loads(page_recorded.stdout)["reason"],
            "v5 worker node job implementation contract drift",
        )

    def test_v5_accepts_real_runtime_provenance_only_when_the_contract_requires_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            compiler_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            compiler_input = json.loads(
                Path(compiler_decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(compiler_decision["compiler_input"]).parent
            )
            runtime_clause = next(
                clause
                for clause in contract["observable_clauses"]
                if clause["page_id"] == "PAGE-002"
                and clause["clause_type"] == "behavior"
            )
            runtime_clause["required_evidence"].append("runtime")
            contract_path = root / "runtime-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            recorded_contract = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )
            self.assertEqual(
                recorded_contract.returncode,
                0,
                recorded_contract.stdout + recorded_contract.stderr,
            )
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            self.assertEqual(
                run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(component_result),
                ).returncode,
                0,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            page_result = write_v5_node_result(project_root, page_decision, contract)

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 0, page_recorded.stdout + page_recorded.stderr)

    def test_v5_rejects_a_declared_design_state_without_an_observable_visual_clause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            design = contract["design_contracts"][0]
            extra_state = dict(design["states"][0])
            extra_state["state_id"] = "state:PAGE-001:alternate"
            extra_state["name"] = "alternate"
            design["states"].append(extra_state)
            contract_path = root / "uncovered-design-state-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract design state coverage mismatch",
        )

    def test_v5_finalizes_only_with_exact_recomputed_clause_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, prepared_contract = prepare_v5_contract(
                root, project_root, revision
            )
            changed_files: list[str] = []
            for _ in range(3):
                decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
                result_path = write_v5_node_result(project_root, decision, contract)
                result = json.loads(result_path.read_text(encoding="utf-8"))
                changed_files.extend(result["changed_files"])
                recorded = run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(result_path),
                )
                self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            self.assertEqual(
                json.loads(run("next-node", "--job", str(job_path)).stdout)["status"],
                "ready-for-finalize",
            )
            state_root = Path(prepared_contract["implementation_contract"]).parent
            artifacts = {
                "node_tests": ("flow-tests.txt", b"passed\n"),
                "runtime_capture": ("actual.png", b"emulator-capture"),
                "visual": ("visual.json", b"{}\n"),
                "e2e": ("e2e.txt", b"passed\n"),
            }
            for path_name, payload in artifacts.values():
                (state_root / path_name).write_bytes(payload)
            job_document = json.loads(job_path.read_text(encoding="utf-8"))
            job_digest = hashlib.sha256(
                json.dumps(
                    job_document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            manifest_path = state_root / "evidence-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-evidence-manifest.v1",
                        "schema_version": 1,
                        "job_id": job_document["job_id"],
                        "job_digest": job_digest,
                        "artifacts": {
                            name: {
                                "status": "passed",
                                "path": path_name,
                                "sha256": hashlib.sha256(payload).hexdigest(),
                                **(
                                    {"actual_source": "emulator_screenshot"}
                                    if name == "runtime_capture"
                                    else {}
                                ),
                            }
                            for name, (path_name, payload) in artifacts.items()
                        },
                    }
                ),
                encoding="utf-8",
            )
            handoff_path = state_root / "handoff-v2.json"
            handoff_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-input.v2",
                        "schema_version": 2,
                        "status": "ready-for-pr",
                        "changed_files": changed_files,
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str(manifest_path),
                        "implementation_contract_sha256": prepared_contract[
                            "implementation_contract_digest"
                        ],
                    }
                ),
                encoding="utf-8",
            )

            finalized = run(
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(state_root / "result.json"),
            )

        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        result = json.loads(finalized.stdout)
        self.assertEqual(result["kind"], "icp.flow-handoff-result.v2")
        self.assertEqual(result["coverage"]["status"], "passed")
        required = [clause["clause_id"] for clause in contract["observable_clauses"]]
        self.assertEqual(result["coverage"]["required_clause_ids"], required)
        self.assertEqual(result["coverage"]["covered_clause_ids"], required)
        self.assertEqual(
            result["implementation_contract_sha256"],
            prepared_contract["implementation_contract_digest"],
        )

    def test_v5_finalizer_rejects_a_legacy_handoff_without_coverage_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, prepared_contract = prepare_v5_contract(
                root, project_root, revision
            )
            changed_files: list[str] = []
            for _ in range(3):
                decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
                result_path = write_v5_node_result(project_root, decision, contract)
                result = json.loads(result_path.read_text(encoding="utf-8"))
                changed_files.extend(result["changed_files"])
                recorded = run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(result_path),
                )
                self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            final_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            self.assertEqual(final_decision["status"], "ready-for-finalize")
            state_root = Path(prepared_contract["implementation_contract"]).parent
            artifacts = {
                "node_tests": ("flow-tests.txt", b"passed\n"),
                "runtime_capture": ("actual.png", b"emulator-capture"),
                "visual": ("visual.json", b"{}\n"),
                "e2e": ("e2e.txt", b"passed\n"),
            }
            for path_name, payload in artifacts.values():
                (state_root / path_name).write_bytes(payload)
            manifest_path = state_root / "evidence-manifest.json"
            job_document = json.loads(job_path.read_text(encoding="utf-8"))
            job_digest = hashlib.sha256(
                json.dumps(
                    job_document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-evidence-manifest.v1",
                        "schema_version": 1,
                        "job_id": job_document["job_id"],
                        "job_digest": job_digest,
                        "artifacts": {
                            name: {
                                "status": "passed",
                                "path": path_name,
                                "sha256": hashlib.sha256(payload).hexdigest(),
                                **(
                                    {"actual_source": "emulator_screenshot"}
                                    if name == "runtime_capture"
                                    else {}
                                ),
                            }
                            for name, (path_name, payload) in artifacts.items()
                        },
                    }
                ),
                encoding="utf-8",
            )
            handoff_path = state_root / "legacy-handoff.json"
            handoff_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-input.v1",
                        "schema_version": 1,
                        "status": "ready-for-pr",
                        "changed_files": changed_files,
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str(manifest_path),
                    }
                ),
                encoding="utf-8",
            )

            finalized = run(
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(state_root / "result.json"),
            )

        self.assertEqual(finalized.returncode, 2)
        self.assertEqual(
            json.loads(finalized.stdout)["reason"],
            "v5 finalization requires a coverage-bound handoff",
        )

    def test_v5_rejects_a_clause_bound_to_a_failed_junit_testcase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, _ = prepare_v5_contract(root, project_root, revision)
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            self.assertEqual(
                run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(component_result),
                ).returncode,
                0,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            page_result = write_v5_node_result(
                project_root,
                page_decision,
                contract,
                failed_test_report=True,
            )

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 2)
        self.assertEqual(
            json.loads(page_recorded.stdout)["reason"],
            "worker test evidence did not pass",
        )

    def test_v5_rejects_visual_proof_with_geometry_different_from_the_frozen_design(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            compiler_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            compiler_input = json.loads(
                Path(compiler_decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(compiler_decision["compiler_input"]).parent
            )
            page_design = next(
                design
                for design in contract["design_contracts"]
                if design["page_id"] == "PAGE-002"
            )
            page_design["states"][0]["anchors"][0]["expected"] = 10.0
            contract_path = root / "candidate-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            self.assertEqual(
                run(
                    "record-contract",
                    "--job",
                    str(job_path),
                    "--contract",
                    str(contract_path),
                ).returncode,
                0,
            )
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            self.assertEqual(
                run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(component_result),
                ).returncode,
                0,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            page_result = write_v5_node_result(project_root, page_decision, contract)

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 2)
        self.assertEqual(
            json.loads(page_recorded.stdout)["reason"],
            "worker visual geometry does not match frozen design",
        )

    def test_v5_rejects_visual_proof_compared_against_the_wrong_design_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, _ = prepare_v5_contract(root, project_root, revision)
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            self.assertEqual(
                run(
                    "record-node",
                    "--job",
                    str(job_path),
                    "--result",
                    str(component_result),
                ).returncode,
                0,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            page_result = write_v5_node_result(
                project_root,
                page_decision,
                contract,
                wrong_visual_reference=True,
            )

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 2)
        self.assertEqual(
            json.loads(page_recorded.stdout)["reason"],
            "worker visual reference does not match frozen design",
        )

    def test_v5_rejects_a_green_page_result_that_omits_one_owned_clause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, contract, _ = prepare_v5_contract(root, project_root, revision)
            component_decision = json.loads(
                run("next-node", "--job", str(job_path)).stdout
            )
            component_result = write_v5_node_result(
                project_root, component_decision, contract
            )
            component_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(component_result),
            )
            self.assertEqual(
                component_recorded.returncode,
                0,
                component_recorded.stdout + component_recorded.stderr,
            )
            page_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            node_job = json.loads(
                Path(page_decision["worker_prompt"])
                .with_name("node-job.json")
                .read_text(encoding="utf-8")
            )
            omitted_clause_id = node_job["implementation_contract"][
                "owned_clause_ids"
            ][0]
            page_result = write_v5_node_result(
                project_root,
                page_decision,
                contract,
                omit_clause_id=omitted_clause_id,
            )

            page_recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(page_result),
            )

        self.assertEqual(page_recorded.returncode, 2)
        self.assertEqual(
            json.loads(page_recorded.stdout)["reason"],
            "worker acceptance evidence coverage mismatch",
        )

    def test_v5_rejects_a_legacy_worker_result_without_frozen_contract_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path, _, _ = prepare_v5_contract(root, project_root, revision)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            node_root = Path(decision["worker_result"]).parent
            node_job = json.loads(
                (node_root / "node-job.json").read_text(encoding="utf-8")
            )
            node = node_job["node"]
            changed_relative = node["allowed_paths"][0]
            changed_path = project_root / changed_relative
            changed_path.parent.mkdir(parents=True, exist_ok=True)
            changed_path.write_text("// implementation\n", encoding="utf-8")
            (node_root / "node-tests.txt").write_text("passed\n", encoding="utf-8")
            result_path = Path(decision["worker_result"])
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.worker-node-result.v1",
                        "schema_version": 1,
                        "node_id": node["node_id"],
                        "status": "passed",
                        "changed_files": [changed_relative],
                        "verification": {
                            "focused_tests": "passed",
                            "scope": "passed",
                            "self_check": "passed",
                        },
                        "evidence": ["node-tests.txt"],
                        "loaded_contracts": {
                            "icp_skill_sha256": hashlib.sha256(
                                ICP_SKILL.read_bytes()
                            ).hexdigest(),
                            "worker_contract_sha256": hashlib.sha256(
                                WORKER_CONTRACT.read_bytes()
                            ).hexdigest(),
                        },
                        "error_code": None,
                    }
                ),
                encoding="utf-8",
            )

            recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(result_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "v5 worker result requires frozen contract evidence",
        )

    def test_v5_rejects_an_implementation_contract_bound_to_a_different_compiler_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            contract["compiler_input_digest"] = "0" * 64
            contract_path = root / "foreign-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract identity mismatch",
        )

    def test_v5_rejects_an_implementation_contract_that_expands_path_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            contract["ownership"][0]["allowed_paths"].append("app/src/main/")
            contract_path = root / "expanded-ownership-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract ownership mismatch",
        )

    def test_v5_rejects_an_integration_case_without_one_strict_tdd_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            contract["tdd_slices"].pop()
            contract_path = root / "missing-tdd-slice-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract TDD coverage mismatch",
        )

    def test_v5_rejects_a_required_integration_clause_without_an_acceptance_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            integration_case = next(
                case
                for case in contract["acceptance_cases"]
                if case["level"] == "integration"
            )
            contract["acceptance_cases"].remove(integration_case)
            for tdd_slice in contract["tdd_slices"]:
                if integration_case["case_id"] in tdd_slice["integration_case_ids"]:
                    tdd_slice["integration_case_ids"].remove(integration_case["case_id"])
            contract_path = root / "missing-integration-case-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract acceptance coverage mismatch",
        )

    def test_v5_rejects_a_behavior_clause_whose_integration_evidence_was_weakened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            behavior = next(
                clause
                for clause in contract["observable_clauses"]
                if clause["clause_type"] == "behavior"
            )
            behavior["required_evidence"] = ["unit"]
            contract_path = root / "weakened-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            (
                "observable clause required evidence is incomplete: "
                f"clause_id={behavior['clause_id']}; "
                "minimum=integration; actual=unit"
            ),
        )

    def test_v5_rejects_a_design_state_without_exact_reachability_and_visual_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            state = contract["design_contracts"][0]["states"][0]
            state["setup"] = ""
            state["anchors"] = []
            state["regions"] = []
            contract_path = root / "unmeasured-design-state-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract design state is incomplete",
        )

    def test_v5_rejects_an_implemented_page_without_an_enumerated_design_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            contract["design_contracts"][0]["states"] = []
            contract_path = root / "missing-design-state-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "every implemented page requires a design state contract",
        )

    def test_v5_rejects_a_design_reference_that_drifted_after_contract_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            design = contract["design_contracts"][0]
            reference = Path(design["reference_artifacts"][0]["path"])
            reference.write_bytes(reference.read_bytes() + b"drift")
            contract_path = root / "drifted-design-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract design artifact digest mismatch",
        )

    def test_v5_freezes_a_complete_contract_before_dispatch_and_binds_it_to_the_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            contract_path = root / "implementation-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )
            dispatched = run("next-node", "--job", str(job_path))

            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            record_result = json.loads(recorded.stdout)
            frozen_path = Path(record_result["implementation_contract"])
            self.assertEqual(
                json.loads(frozen_path.read_text(encoding="utf-8")), contract
            )
            self.assertEqual(dispatched.returncode, 0, dispatched.stdout + dispatched.stderr)
            node_decision = json.loads(dispatched.stdout)
            node_job = json.loads(
                Path(node_decision["worker_prompt"])
                .with_name("node-job.json")
                .read_text(encoding="utf-8")
            )
            worker_prompt = Path(node_decision["worker_prompt"]).read_text(
                encoding="utf-8"
            )

        self.assertEqual(node_decision["status"], "ready")
        self.assertEqual(node_job["kind"], "icp.worker-node-job.v2")
        binding = node_job["implementation_contract"]
        self.assertEqual(binding["path"], str(frozen_path))
        self.assertEqual(
            binding["sha256"], record_result["implementation_contract_digest"]
        )
        self.assertEqual(binding["source_clauses_digest"], compiler_input["source_clauses_digest"])
        self.assertEqual(binding["owned_clause_ids"], [])
        self.assertIn("implementation contract", worker_prompt)

    def test_v5_rejects_an_implementation_contract_that_omits_one_source_clause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(contract_compiled_flow_job(project_root, revision)),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(decision["compiler_input"]).read_text(encoding="utf-8")
            )
            contract = implementation_contract_for(
                compiler_input, Path(decision["compiler_input"]).parent
            )
            omitted = contract["observable_clauses"].pop()
            assert isinstance(omitted, dict)
            omitted_id = omitted["clause_id"]
            contract["acceptance_cases"] = [
                case
                for case in contract["acceptance_cases"]
                if omitted_id not in case["clause_ids"]
            ]
            contract["tdd_slices"] = [
                item
                for item in contract["tdd_slices"]
                if omitted_id not in item["clause_ids"]
            ]
            contract_path = root / "incomplete-contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            recorded = run(
                "record-contract",
                "--job",
                str(job_path),
                "--contract",
                str(contract_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "implementation contract source coverage mismatch",
        )

    def test_v5_compiler_input_projects_every_exact_source_line_with_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "v5-job.json"
            job_path.write_text(
                json.dumps(
                    contract_compiled_flow_job(project_root, revision),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            first = json.loads(run("next-node", "--job", str(job_path)).stdout)
            second = json.loads(run("next-node", "--job", str(job_path)).stdout)
            compiler_input = json.loads(
                Path(first["compiler_input"]).read_text(encoding="utf-8")
            )

        self.assertEqual(first, second)
        source_clauses = compiler_input["source_clauses"]
        exact_text = [clause["exact_text"] for clause in source_clauses]
        self.assertEqual(
            exact_text,
            [
                "申请首页",
                "ApplicationScreen",
                "https://design.example/PAGE-001",
                "Tap continue",
                "Open the detail page",
                "Keep the supplied icon",
                "  Preserve spacing",
                "formatting remains stable",
                "continue opens detail",
                "back returns",
                "complete the reachable flow",
                "职业信息页",
                "OccupationScreen",
                "https://design.example/PAGE-002",
                "实现职业信息表单。",
            ],
        )
        self.assertEqual(
            [clause["required_evidence"] for clause in source_clauses[7:11]],
            [["unit"], ["integration"], ["integration"], ["e2e"]],
        )
        self.assertTrue(all(clause["source_digest"] for clause in source_clauses))
        self.assertEqual(
            len({clause["clause_id"] for clause in source_clauses}),
            len(source_clauses),
        )
        self.assertEqual(
            compiler_input["source_clauses_digest"],
            hashlib.sha256(
                json.dumps(
                    source_clauses,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_rejects_a_recomputed_summary_that_replaces_exact_sheet_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root, revision = make_project(Path(temporary_directory))
            job = lossless_flow_job(project_root, revision)
            members = job["members"]
            assert isinstance(members, list) and isinstance(members[0], dict)
            members[0]["requirement"] = "按 Sheet 给定文案实现。"
            member_digests = job["member_digests"]
            assert isinstance(member_digests, dict)
            member_digests[str(members[0]["page_id"])] = hashlib.sha256(
                json.dumps(
                    members[0],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            job_path = Path(temporary_directory) / "lossy-job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

            completed = run("prepare", "--job", str(job_path.resolve()))

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "flow member requirement is not lossless",
        )

    def test_lossless_worker_prompt_makes_source_contract_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root, revision = make_project(Path(temporary_directory))
            job_path = Path(temporary_directory) / "lossless-job.json"
            job_path.write_text(
                json.dumps(
                    lossless_flow_job(project_root, revision), ensure_ascii=False
                ),
                encoding="utf-8",
            )
            prepared = run("prepare", "--job", str(job_path.resolve()))
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            decision = run("next-node", "--job", str(job_path.resolve()))
            self.assertEqual(decision.returncode, 0, decision.stdout + decision.stderr)
            prompt_path = Path(json.loads(decision.stdout)["worker_prompt"])
            prompt = prompt_path.read_text(encoding="utf-8")

        self.assertIn(
            "Treat each member.source_contract as the exact authoritative Sheet contract",
            prompt,
        )
        self.assertIn("Never summarize, rewrite, or replace its values", prompt)


def write_page_evidence(
    node_root: Path,
    *,
    manifest_name: str = "visual-evidence.json",
    actual_name: str = "actual.png",
    diff_name: str = "diff.png",
    provenance_name: str = "actual-provenance.json",
    mutation_index: int = -13,
) -> Path:
    reference = (node_root / "design.png").resolve()
    actual = (node_root / actual_name).resolve()
    diff = (node_root / diff_name).resolve()
    provenance = (node_root / provenance_name).resolve()
    if not reference.exists():
        reference.write_bytes(PNG)
    changed = bytearray(PNG)
    changed[mutation_index] ^= 1
    actual.write_bytes(bytes(changed))
    diff.write_bytes(PNG)
    provenance.write_text(
        json.dumps(
            {
                "kind": "icp.runtime-provenance.v1",
                "actual_source": "emulator_screenshot",
                "actual_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
                "capture_id": f"capture-{actual_name}",
                "state_reset_id": f"reset-{actual_name}",
            }
        ),
        encoding="utf-8",
    )
    manifest = visual.build_evidence(
        reference_path=reference,
        actual_path=actual,
        diff_path=diff,
        actual_provenance_path=provenance,
        mismatch_ratio=0.01,
        max_mismatch_ratio=0.02,
    )
    manifest_path = node_root / manifest_name
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path.resolve()


def write_page_verification(node_root: Path) -> None:
    first = write_page_evidence(node_root)
    second = write_page_evidence(
        node_root,
        manifest_name="visual-evidence-repeat.json",
        actual_name="actual-repeat.png",
        diff_name="diff-repeat.png",
        provenance_name="actual-repeat-provenance.json",
        mutation_index=-14,
    )
    anchor_report = {
        "kind": "icp.android-anchor-measurements.v1",
        "schema_version": 1,
        "state_id": "state-default",
        "measurements": [{"name": "root_top", "actual_dp": 0.0}],
        "errors": [],
        "status": "pass",
    }
    anchor_report["report_sha256"] = hashlib.sha256(
        json.dumps(
            anchor_report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    anchor_report_path = (node_root / "anchor-measurements.json").resolve()
    anchor_report_path.write_text(json.dumps(anchor_report), encoding="utf-8")
    region_report = {
        "kind": "icp.android-region-measurements.v1",
        "schema_version": 1,
        "state_id": "state-default",
        "measurements": [{"name": "full_page", "mismatch_ratio": 0.01}],
        "errors": [],
        "status": "pass",
    }
    region_report["report_sha256"] = hashlib.sha256(
        json.dumps(
            region_report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    region_report_path = (node_root / "region-measurements.json").resolve()
    region_report_path.write_text(json.dumps(region_report), encoding="utf-8")
    document = visual_verification.build_verification(
        calibration={
            "reference_width": 1,
            "reference_height": 1,
            "runtime_width": 1,
            "runtime_height": 1,
            "density": 1.0,
            "font_scale": 1.0,
            "locale": "zh-CN",
            "theme": "light",
            "system_bars": "excluded",
            "animations_disabled": True,
        },
        states=[
            {
                "name": "default",
                "contract": "The approved default page state is visible.",
                "final_runs": [str(first), str(second)],
                "anchors": [
                    {
                        "name": "root_top",
                        "expected": 0.0,
                        "actual": 0.0,
                        "tolerance": 0.0,
                        "measurement_path": str(anchor_report_path),
                        "measurement_sha256": hashlib.sha256(
                            anchor_report_path.read_bytes()
                        ).hexdigest(),
                    }
                ],
                "regions": [
                    {
                        "name": "full_page",
                        "mismatch_ratio": 0.01,
                        "max_mismatch_ratio": 0.02,
                        "diff_report_path": str(region_report_path),
                        "diff_report_sha256": hashlib.sha256(
                            region_report_path.read_bytes()
                        ).hexdigest(),
                    }
                ],
            }
        ],
        repair_history=[],
    )
    (node_root / "visual-verification.json").write_text(
        json.dumps(document), encoding="utf-8"
    )


def pass_next_node(job_path: Path, project_root: Path) -> tuple[str, str]:
    decision = json.loads(run("next-node", "--job", str(job_path)).stdout)
    node_job = json.loads(
        (Path(decision["worker_prompt"]).parent / "node-job.json").read_text(
            encoding="utf-8"
        )
    )
    node = node_job["node"]
    changed_relative = node["allowed_paths"][0]
    if changed_relative.endswith("/"):
        changed_relative += "Generated.kt"
    changed_file = project_root / changed_relative
    changed_file.parent.mkdir(parents=True, exist_ok=True)
    changed_file.write_text(f"// {node['node_id']}\n", encoding="utf-8")
    result_path = Path(decision["worker_result"])
    (result_path.parent / "node-tests.txt").write_text("passed\n", encoding="utf-8")
    verification = {
        "focused_tests": "passed",
        "scope": "passed",
        "self_check": "passed",
    }
    evidence = ["node-tests.txt"]
    if node["type"] == "page":
        write_page_verification(result_path.parent)
        evidence.append("visual-verification.json")
    result_path.write_text(
        json.dumps(
            {
                "kind": "icp.worker-node-result.v1",
                "schema_version": 1,
                "node_id": node["node_id"],
                "status": "passed",
                "changed_files": [changed_relative],
                "verification": verification,
                "evidence": evidence,
                "loaded_contracts": {
                    "icp_skill_sha256": hashlib.sha256(
                        ICP_SKILL.read_bytes()
                    ).hexdigest(),
                    "worker_contract_sha256": hashlib.sha256(
                        WORKER_CONTRACT.read_bytes()
                    ).hexdigest(),
                },
                "error_code": None,
            }
        ),
        encoding="utf-8",
    )
    recorded = run(
        "record-node",
        "--job",
        str(job_path),
        "--result",
        str(result_path),
    )
    assert recorded.returncode == 0, recorded.stderr
    return str(node["node_id"]), changed_relative


class FlowJobTests(unittest.TestCase):
    def test_rejects_overlapping_path_ownership_between_worker_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            document = flow_job(project_root, revision)
            dag = document["execution_dag"]
            assert isinstance(dag, list)
            dag[1]["allowed_paths"] = [
                "app/src/main/java/ui/components/FormCard.kt"
            ]
            job_path = root / "overlap-job.json"
            job_path.write_text(json.dumps(document), encoding="utf-8")

            prepared = run("prepare", "--job", str(job_path))

        self.assertEqual(prepared.returncode, 2)
        self.assertEqual(
            json.loads(prepared.stdout)["reason"],
            "execution node path ownership overlaps",
        )

    def test_persists_one_active_node_and_resumes_it_before_dispatching_another(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )

            prepared = run("prepare", "--job", str(job_path))
            first = run("next-node", "--job", str(job_path))
            resumed = run("next-node", "--job", str(job_path))

            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertEqual(json.loads(prepared.stdout)["status"], "ready")
            self.assertEqual(first.returncode, 0, first.stderr)
            first_result = json.loads(first.stdout)
            self.assertEqual(first_result["status"], "ready")
            self.assertEqual(first_result["node_id"], "component:shared-form-card")
            self.assertTrue(Path(first_result["worker_prompt"]).is_file())
            worker_prompt = Path(first_result["worker_prompt"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("Invoke and follow $icp", worker_prompt)
            self.assertIn("worker-node-contract-v1.md", worker_prompt)
            self.assertIn("intermediate visual mismatch is not terminal", worker_prompt)
            self.assertIn("two independent clean final captures", worker_prompt)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resumed_result = json.loads(resumed.stdout)
            self.assertEqual(resumed_result["status"], "resume-required")
            self.assertEqual(resumed_result["node_id"], "component:shared-form-card")
            self.assertEqual(resumed_result["worker_prompt"], first_result["worker_prompt"])

    def test_accepts_one_compliant_node_result_before_dispatching_the_leaf_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            first = json.loads(run("next-node", "--job", str(job_path)).stdout)
            changed_file = (
                project_root / "app/src/main/java/ui/components/FormCard.kt"
            )
            changed_file.parent.mkdir(parents=True)
            changed_file.write_text("class FormCard\n", encoding="utf-8")
            result_path = Path(first["worker_result"])
            evidence_path = result_path.parent / "node-tests.txt"
            evidence_path.write_text("passed\n", encoding="utf-8")
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.worker-node-result.v1",
                        "schema_version": 1,
                        "node_id": "component:shared-form-card",
                        "status": "passed",
                        "changed_files": [
                            "app/src/main/java/ui/components/FormCard.kt"
                        ],
                        "verification": {
                            "focused_tests": "passed",
                            "scope": "passed",
                            "self_check": "passed",
                        },
                        "evidence": ["node-tests.txt"],
                        "loaded_contracts": {
                            "icp_skill_sha256": hashlib.sha256(
                                ICP_SKILL.read_bytes()
                            ).hexdigest(),
                            "worker_contract_sha256": LEGACY_WORKER_CONTRACT_SHA256,
                        },
                        "error_code": None,
                    }
                ),
                encoding="utf-8",
            )

            recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(result_path),
            )
            following = run("next-node", "--job", str(job_path))

        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(json.loads(recorded.stdout)["status"], "node-passed")
        self.assertEqual(following.returncode, 0, following.stderr)
        self.assertEqual(json.loads(following.stdout)["node_id"], "page:PAGE-002")

    def test_rejects_behavior_only_page_result_without_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            pass_next_node(job_path, project_root)
            page = json.loads(run("next-node", "--job", str(job_path)).stdout)
            node_job = json.loads(
                (Path(page["worker_prompt"]).parent / "node-job.json").read_text(
                    encoding="utf-8"
                )
            )
            node = node_job["node"]
            changed_relative = node["allowed_paths"][0]
            changed_file = project_root / changed_relative
            changed_file.parent.mkdir(parents=True, exist_ok=True)
            changed_file.write_text("// behavior-only page\n", encoding="utf-8")
            result_path = Path(page["worker_result"])
            (result_path.parent / "node-tests.txt").write_text(
                "behavior tests passed\n", encoding="utf-8"
            )
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.worker-node-result.v1",
                        "schema_version": 1,
                        "node_id": node["node_id"],
                        "status": "passed",
                        "changed_files": [changed_relative],
                        "verification": {
                            "focused_tests": "passed",
                            "scope": "passed",
                            "self_check": "passed",
                        },
                        "evidence": ["node-tests.txt"],
                        "loaded_contracts": {
                            "icp_skill_sha256": hashlib.sha256(
                                ICP_SKILL.read_bytes()
                            ).hexdigest(),
                            "worker_contract_sha256": hashlib.sha256(
                                WORKER_CONTRACT.read_bytes()
                            ).hexdigest(),
                        },
                        "error_code": None,
                    }
                ),
                encoding="utf-8",
            )

            recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(result_path),
            )

        self.assertEqual(recorded.returncode, 2)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "page worker result requires high-assurance visual verification",
        )

    def test_rejects_page_with_only_one_visual_evidence_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            pass_next_node(job_path, project_root)
            page = json.loads(run("next-node", "--job", str(job_path)).stdout)
            node_root = Path(page["worker_prompt"]).parent
            node_job = json.loads((node_root / "node-job.json").read_text(encoding="utf-8"))
            node = node_job["node"]
            changed_relative = node["allowed_paths"][0]
            changed_file = project_root / changed_relative
            changed_file.parent.mkdir(parents=True, exist_ok=True)
            changed_file.write_text("// visually verified page\n", encoding="utf-8")
            (node_root / "node-tests.txt").write_text("passed\n", encoding="utf-8")
            write_page_evidence(node_root)
            result_path = Path(page["worker_result"])
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.worker-node-result.v1",
                        "schema_version": 1,
                        "node_id": node["node_id"],
                        "status": "passed",
                        "changed_files": [changed_relative],
                        "verification": {
                            "focused_tests": "passed",
                            "scope": "passed",
                            "self_check": "passed",
                        },
                        "evidence": ["node-tests.txt", "visual-evidence.json"],
                        "loaded_contracts": {
                            "icp_skill_sha256": hashlib.sha256(
                                ICP_SKILL.read_bytes()
                            ).hexdigest(),
                            "worker_contract_sha256": hashlib.sha256(
                                WORKER_CONTRACT.read_bytes()
                            ).hexdigest(),
                        },
                        "error_code": None,
                    }
                ),
                encoding="utf-8",
            )

            recorded = run(
                "record-node",
                "--job",
                str(job_path),
                "--result",
                str(result_path),
            )

        self.assertEqual(recorded.returncode, 2, recorded.stdout)
        self.assertEqual(
            json.loads(recorded.stdout)["reason"],
            "page worker result requires high-assurance visual verification",
        )

    def test_accepts_page_with_two_independent_clean_visual_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(run("prepare", "--job", str(job_path)).returncode, 0)
            pass_next_node(job_path, project_root)

            node_id, _ = pass_next_node(job_path, project_root)
            next_decision = json.loads(run("next-node", "--job", str(job_path)).stdout)

        self.assertEqual(node_id, "page:PAGE-002")
        self.assertEqual(next_decision["status"], "ready")
        self.assertEqual(next_decision["node_id"], "page:PAGE-001")

    def test_finalize_revalidates_persisted_page_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            prepared = json.loads(run("prepare", "--job", str(job_path)).stdout)
            changed_files = [
                pass_next_node(job_path, project_root)[1] for _ in range(3)
            ]
            state_root = Path(prepared["state_root"])
            page_node_root = (
                state_root
                / "nodes"
                / hashlib.sha256(b"page:PAGE-002").hexdigest()
            )
            page_result = json.loads(
                (page_node_root / "worker-result.json").read_text(encoding="utf-8")
            )
            visual_relative = "visual-evidence.json"
            visual_path = page_node_root / visual_relative
            visual_document = json.loads(visual_path.read_text(encoding="utf-8"))
            visual_document["diff"]["mismatch_ratio"] = 1.0
            visual_path.write_text(json.dumps(visual_document), encoding="utf-8")
            handoff_path = state_root / "handoff.json"
            handoff_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-input.v1",
                        "schema_version": 1,
                        "status": "ready-for-pr",
                        "changed_files": changed_files,
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str(state_root / "unused.json"),
                    }
                ),
                encoding="utf-8",
            )

            finalized = run(
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(state_root / "result.json"),
            )

        self.assertEqual(finalized.returncode, 2)
        self.assertEqual(
            json.loads(finalized.stdout)["reason"],
            "page visual verification did not pass",
        )

    def test_finalizes_only_after_all_nodes_and_flow_evidence_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root, revision = make_project(root)
            job_path = root / "flow-job.json"
            job_path.write_text(
                json.dumps(flow_job(project_root, revision), ensure_ascii=False),
                encoding="utf-8",
            )
            prepared_process = run("prepare", "--job", str(job_path))
            self.assertEqual(prepared_process.returncode, 0, prepared_process.stderr)
            prepared = json.loads(prepared_process.stdout)
            changed_files = [
                pass_next_node(job_path, project_root)[1] for _ in range(3)
            ]
            final_decision = run("next-node", "--job", str(job_path))
            self.assertEqual(final_decision.returncode, 0, final_decision.stderr)
            self.assertEqual(
                json.loads(final_decision.stdout)["status"], "ready-for-finalize"
            )

            state_root = Path(prepared["state_root"])
            artifacts = {
                "node_tests": ("flow-tests.txt", b"passed\n"),
                "runtime_capture": ("actual.png", b"emulator-capture"),
                "visual": ("visual.json", b"{}\n"),
                "e2e": ("e2e.txt", b"passed\n"),
            }
            for path_name, payload in artifacts.values():
                (state_root / path_name).write_bytes(payload)
            manifest_path = state_root / "evidence-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-evidence-manifest.v1",
                        "schema_version": 1,
                        "job_id": "iole:client:flow-abc:review-0:aaaaaaaaaaaa",
                        "job_digest": prepared["job_digest"],
                        "artifacts": {
                            name: {
                                "status": "passed",
                                "path": path_name,
                                "sha256": hashlib.sha256(payload).hexdigest(),
                                **(
                                    {"actual_source": "emulator_screenshot"}
                                    if name == "runtime_capture"
                                    else {}
                                ),
                            }
                            for name, (path_name, payload) in artifacts.items()
                        },
                    }
                ),
                encoding="utf-8",
            )
            handoff_path = state_root / "handoff.json"
            handoff_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-input.v1",
                        "schema_version": 1,
                        "status": "ready-for-pr",
                        "changed_files": changed_files,
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str(manifest_path),
                    }
                ),
                encoding="utf-8",
            )
            result_path = state_root / "result.json"

            finalized = run(
                "finalize",
                "--job",
                str(job_path),
                "--handoff",
                str(handoff_path),
                "--result",
                str(result_path),
            )

        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        result = json.loads(finalized.stdout)
        self.assertEqual(result["status"], "ready-for-pr")
        self.assertEqual(result["changed_files"], changed_files)
        self.assertEqual(
            result["member_digests"], {"PAGE-001": "a" * 64, "PAGE-002": "b" * 64}
        )


if __name__ == "__main__":
    unittest.main()
