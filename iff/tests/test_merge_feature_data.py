from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge_feature_data.py"
CHECK_BINDINGS = Path(__file__).resolve().parents[1] / "scripts" / "check_data_bindings.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MergeFeatureDataTest(unittest.TestCase):
    def make_board(
        self, root: Path, board: str, contract: Path, design_text: str
    ) -> None:
        manifest = root / board / "component_manifest.json"
        bindings = root / board / "data_slot_bindings.json"
        write_json(
            manifest,
            {
                "components": [
                    {
                        "name": "amount-card",
                        "dynamicSlots": [
                            {"node": "amount-node", "text": design_text}
                        ],
                    }
                ]
            },
        )
        write_json(
            bindings,
            {
                "inputs": {
                    "component_manifest.json": sha256(manifest),
                    "api_contract.json": sha256(contract),
                },
                "bindings": [
                    {
                        "component": "amount-card",
                        "node": "amount-node",
                        "designText": design_text,
                        "binding": {
                            "field": {
                                "endpoint": "/loan",
                                "method": "GET",
                                "status": "200",
                                "jsonPath": "$.amount",
                                "type": "number",
                                "format": None,
                                "required": True,
                                "nullable": False,
                                "enum": None,
                            },
                            "transform": "formatNaira",
                            "confidence": "high",
                        },
                    }
                ],
            },
        )

    def test_merges_two_state_boards_with_state_qualified_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            contract = spec / "api_contract.json"
            feature = root / "feature.json"
            out_manifest = spec / "component_manifest.json"
            out_bindings = spec / "data_slot_bindings.json"
            write_json(contract, {"endpoints": {}})
            self.make_board(spec, "default-board", contract, "₦10")
            self.make_board(spec, "approved-board", contract, "₦20")
            write_json(
                feature,
                {
                    "featureId": "loan",
                    "states": {
                        "default": {"board": "default-board"},
                        "approved": {"board": "approved-board"},
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--feature-manifest",
                    str(feature),
                    "--api-contract",
                    str(contract),
                    "--out-manifest",
                    str(out_manifest),
                    "--out-bindings",
                    str(out_bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
            bindings = json.loads(out_bindings.read_text(encoding="utf-8"))
            self.assertEqual(
                ["approved", "default"],
                [component["state"] for component in manifest["components"]],
            )
            self.assertEqual(
                ["approved", "default"],
                [entry["state"] for entry in bindings["bindings"]],
            )
            self.assertEqual(
                sha256(out_manifest),
                bindings["inputs"]["component_manifest.json"],
            )
            self.assertEqual(
                {"path": str(feature.resolve()), "sha256": sha256(feature)},
                bindings["inputs"]["feature_manifest.json"],
            )

            board_manifest = spec / "approved-board/component_manifest.json"
            board_payload = json.loads(board_manifest.read_text(encoding="utf-8"))
            board_payload["components"][0]["dynamicSlots"][0]["text"] = "₦30"
            write_json(board_manifest, board_payload)
            stale = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_BINDINGS),
                    "--manifest",
                    str(out_manifest),
                    "--api-contract",
                    str(contract),
                    "--bindings",
                    str(out_bindings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("stale merged board", stale.stdout + stale.stderr)

    def test_stale_board_binding_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            contract = spec / "api_contract.json"
            feature = root / "feature.json"
            write_json(contract, {"endpoints": {}})
            self.make_board(spec, "default-board", contract, "₦10")
            binding_path = spec / "default-board/data_slot_bindings.json"
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            binding["inputs"]["component_manifest.json"] = "old"
            write_json(binding_path, binding)
            write_json(
                feature,
                {
                    "featureId": "loan",
                    "states": {"default": {"board": "default-board"}},
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--feature-manifest",
                    str(feature),
                    "--api-contract",
                    str(contract),
                    "--out-manifest",
                    str(spec / "component_manifest.json"),
                    "--out-bindings",
                    str(spec / "data_slot_bindings.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("stale board binding", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
