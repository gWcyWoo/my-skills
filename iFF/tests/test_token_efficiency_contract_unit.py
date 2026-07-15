from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_implementation_map import build_implementation_map
from model_context_contract import (
    expected_workers,
    persist_model_input,
    render_contract,
    validate_packet,
)
from run_fetch_pipeline import parse_design_urls
from visual_diff import write_png_rgba


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TokenEfficiencyContractUnitTest(unittest.TestCase):
    def test_worker_roster_is_derived_from_unique_manifest_boards(self) -> None:
        manifest = {
            "featureId": "home",
            "states": {
                "default": {"board": "default"},
                "approved": {"board": "approved"},
            },
        }

        self.assertEqual(
            [
                {"id": "board--approved", "role": "board", "board": "approved"},
                {"id": "board--default", "role": "board", "board": "default"},
                {"id": "assembly", "role": "assembly", "board": None},
            ],
            expected_workers(manifest),
        )

        for invalid in (
            {"featureId": "home", "states": {"default": {}}},
            {
                "featureId": "home",
                "states": {
                    "default": {"board": "same"},
                    "approved": {"board": "same"},
                },
            },
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    expected_workers(invalid)

    def test_contract_render_is_deterministic_and_binds_every_input_fingerprint(self) -> None:
        contract_input = {
            "version": "IFF_WORKER_CONTRACT v3",
            "worker": {"id": "board--default", "role": "board", "board": "default"},
            "paths": {"spec": "/spec/home/default", "project": "/project"},
            "fingerprints": {
                "row": "row-v1",
                "rules": "rules-v1",
                "renderer": "renderer-v1",
                "preflight": "preflight-v1",
            },
        }

        first = render_contract(contract_input)
        self.assertEqual(first, render_contract(contract_input))
        for key in contract_input["fingerprints"]:
            changed = json.loads(json.dumps(contract_input))
            changed["fingerprints"][key] += "-changed"
            with self.subTest(fingerprint=key):
                self.assertNotEqual(first, render_contract(changed))

    def test_packet_validation_rejects_empty_stale_unknown_and_wrong_scope_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "spec" / "artifact_digest.json"
            source.parent.mkdir(parents=True)
            source.write_text("current", encoding="utf-8")
            expected = {
                "kind": "visual",
                "scope": {"feature": "home", "board": "default"},
                "requiredSources": ["artifactDigest"],
                "allowedActions": ["fill_plan_judgment", "none"],
            }
            packet = {
                "version": 2,
                "kind": "visual",
                "scope": expected["scope"],
                "sources": {
                    "artifactDigest": {
                        "path": str(source),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                },
                "action": {
                    "kind": "fill_plan_judgment",
                    "target": "components.header.family",
                    "allowedDecisions": ["reuse", "independent"],
                    "allowedWritePaths": [
                        "artifactDigest:components.header.family"
                    ],
                    "requiredWritePathsByDecision": {
                        "reuse": ["artifactDigest:components.header.family"],
                        "independent": ["artifactDigest:components.header.family"],
                    },
                },
            }

            self.assertEqual([], validate_packet(packet, expected, project))
            mutations = {
                "empty sources": lambda value: value.update(sources={}),
                "stale source": lambda value: value["sources"]["artifactDigest"].update(
                    sha256="0" * 64
                ),
                "unknown action": lambda value: value["action"].update(kind="invent"),
                "empty action": lambda value: value.update(action={}),
                "wrong scope": lambda value: value["scope"].update(board="approved"),
                "write source not declared": lambda value: value["action"].update(
                    allowedWritePaths=["invented:value"],
                    requiredWritePathsByDecision={
                        "reuse": ["invented:value"],
                        "independent": ["invented:value"],
                    },
                ),
            }
            for name, mutate in mutations.items():
                invalid = json.loads(json.dumps(packet))
                mutate(invalid)
                with self.subTest(name=name):
                    self.assertTrue(validate_packet(invalid, expected, project))

    def test_model_input_ledger_retains_every_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / ".iff" / "model_context.jsonl"
            first = persist_model_input(
                b"first", kind="visual", owner="board--default", ledger=ledger
            )
            second = persist_model_input(
                b"second", kind="visual", owner="board--default", ledger=ledger
            )

            entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([first, second], entries)
            self.assertEqual(11, sum(entry["bytes"] for entry in entries))
            for entry in entries:
                archive = ledger.parent / "model_context_blobs" / f"{entry['sha256']}.bin"
                self.assertTrue(archive.is_file())
                self.assertEqual(entry["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_design_urls_are_split_in_source_order(self) -> None:
        self.assertEqual(
            ["https://design/1", "https://design/2", "https://design/3"],
            parse_design_urls(
                " https://design/1；https://design/2\n\nhttps://design/3; "
            ),
        )

    def test_implementation_map_covers_only_required_visible_nodes(self) -> None:
        render_plan = {
            "nodes": {
                "title": {
                    "required": True,
                    "implementation": "text",
                    "bbox": [10, 20, 100, 30],
                },
                "icon": {
                    "implementation": "asset",
                    "bbox": [120, 20, 20, 20],
                },
                "guide": {
                    "required": False,
                    "implementation": "layout_guide",
                    "bbox": [0, 0, 1, 1],
                },
            }
        }
        expected = {
            "nodes": {
                "title": {"widget": "IffText"},
                "icon": {"widget": "IffAsset"},
            }
        }

        result = build_implementation_map(render_plan, expected)

        self.assertEqual(["icon", "title"], [item["node"] for item in result["nodes"]])
        self.assertTrue(
            all(item["renderMode"] == "absolute_positioned" for item in result["nodes"])
        )
        self.assertTrue(all(len(item["bbox"]) == 4 for item in result["nodes"]))

    def test_visual_packet_advances_to_the_first_unresolved_declared_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            write_json(board / "artifact_digest.json", {"scene": {"nodeCount": 2}})
            write_json(
                board / "implementation_plan.json",
                {
                    "components": {
                        "header": {"family": "shared-header"},
                        "footer": {"family": "__MODEL__"},
                    },
                    "modelFields": [
                        {"path": "components.header.family"},
                        {"path": "components.footer.family"},
                    ],
                },
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "make_visual_model_packet.py"),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            action = json.loads(out.read_text(encoding="utf-8"))["action"]
            self.assertEqual(
                {"path": "components.footer.family"}, action["modelField"]
            )

    def test_visual_packet_rejects_an_undeclared_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp)
            write_json(board / "artifact_digest.json", {"scene": {"nodeCount": 2}})
            write_json(
                board / "implementation_plan.json",
                {"decision": "__MODEL__", "modelFields": []},
            )
            out = board / "visual_model_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "make_visual_model_packet.py"),
                    "--spec-dir",
                    str(board),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not declared in modelFields", result.stdout + result.stderr)

    def test_guard_valid_png_passes_but_malformed_png_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, malformed in (("valid", False), ("malformed", True)):
                with self.subTest(name=name):
                    board = root / name
                    board.mkdir()
                    if malformed:
                        (board / "reference.png").write_bytes(b"reference")
                        (board / "actual.png").write_bytes(b"actual")
                    else:
                        write_png_rgba(
                            board / "reference.png", 1, 1, [(255, 255, 255, 255)]
                        )
                        write_png_rgba(
                            board / "actual.png", 1, 1, [(0, 0, 0, 255)]
                        )
                    write_json(
                        board / "render_fidelity_report.json",
                        {"ok": True, "assetShapeChecked": True},
                    )
                    write_json(
                        board / "diff_report.json",
                        {
                            "shapeIssues": [],
                            "unexpectedIssues": [],
                            "assetIssues": [],
                            "textIssues": [],
                            "viewportIssues": [],
                        },
                    )
                    write_json(
                        board / "visual_manifest.json",
                        {
                            "actual_source": "simulator_screenshot",
                            "device_id": "simulator-1",
                            "capture_command": "simctl screenshot",
                            "timestamp": "2026-01-01T00:00:00Z",
                            "project_root": str(root),
                            "app_hashes": {},
                            "runtime_input_hashes": {},
                            "launch_command": [
                                "flutter",
                                "run",
                                "-d",
                                "simulator-1",
                            ],
                            "viewport": {"width": 1, "height": 1, "density": 1},
                        },
                    )
                    out = board / "visual_gate_report.json"
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPTS_DIR / "make_visual_gate_report.py"),
                            "--spec-dir",
                            str(board),
                            "--out",
                            str(out),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if malformed:
                        self.assertNotEqual(0, result.returncode)
                    else:
                        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
