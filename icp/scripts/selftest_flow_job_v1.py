#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared_core import visual_evidence_v1 as visual


SCRIPT = Path(__file__).with_name("icp_flow_job_v1.py")
ICP_SKILL = Path(__file__).parents[1] / "SKILL.md"
WORKER_CONTRACT = Path(__file__).parents[1] / "references" / "worker-node-contract-v1.md"
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


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def write_page_evidence(
    node_root: Path,
) -> None:
    reference = (node_root / "design.png").resolve()
    actual = (node_root / "actual.png").resolve()
    diff = (node_root / "diff.png").resolve()
    provenance = (node_root / "actual-provenance.json").resolve()
    reference.write_bytes(PNG)
    changed = bytearray(PNG)
    changed[-13] ^= 1
    actual.write_bytes(bytes(changed))
    diff.write_bytes(PNG)
    provenance.write_text(
        json.dumps(
            {
                "kind": "icp.runtime-provenance.v1",
                "actual_source": "emulator_screenshot",
                "actual_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
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
    manifest_path = node_root / "visual-evidence.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


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
        write_page_evidence(result_path.parent)
        evidence.append("visual-evidence.json")
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
            self.assertIn("remaining visual mismatch must be status=failed", worker_prompt)
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
            "page worker result requires canonical ICP visual evidence",
        )

    def test_accepts_page_only_with_bound_design_runtime_and_visual_evidence(self) -> None:
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

        self.assertEqual(recorded.returncode, 0, recorded.stdout)
        self.assertEqual(json.loads(recorded.stdout)["status"], "node-passed")

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
            "page visual evidence did not pass",
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
