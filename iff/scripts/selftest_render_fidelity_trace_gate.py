#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from visual_diff import component_issues


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def run(
    script: Path,
    root: Path,
    trace: Path,
    name: str,
    diff_report: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "python3",
        str(script),
        "--trace",
        str(trace),
        "--expected",
        str(root / "expected.json"),
        "--out",
        str(root / f"{name}_report.json"),
    ]
    if diff_report is not None:
        command.extend(["--diff-report", str(diff_report)])
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
    )


def main() -> int:
    script = Path(__file__).resolve().parent / "check_render_fidelity.py"
    with tempfile.TemporaryDirectory(prefix="iff_fidelity_trace_") as tmp:
        root = Path(tmp)
        write_json(root / "expected.json", {"nodes": {"node-1": {"bbox": [0, 0, 10, 10]}}})

        canonical = root / "canonical.json"
        write_json(
            canonical,
            {"pageType": "RuntimePage", "expectedNodeIds": ["node-1"],
             "nodes": {"node-1": {"present": True, "bbox": [0, 0, 10, 10]}}},
        )
        accepted = run(script, root, canonical, "accepted")
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)

        for name, payload in (
            ("empty", {"pageType": "RuntimePage", "expectedNodeIds": ["node-1"], "nodes": {}}),
            ("legacy", {"pageType": "RuntimePage", "expectedNodeIds": ["node-1"],
                        "widgets": {"node-1": {"present": True}}}),
        ):
            trace = root / f"{name}.json"
            write_json(trace, payload)
            rejected = run(script, root, trace, name)
            assert rejected.returncode != 0, rejected.stdout
            assert "non-empty top-level nodes object" in rejected.stderr, rejected.stderr
            assert not (root / f"{name}_report.json").exists()

        _, _, schema_asset_issues, _ = component_issues(
            {
                "approved-alias": {
                    "state": "approved",
                    "bbox": [0, 0, 10, 10],
                    "widgets": {
                        "icon": {
                            "node": "97:194",
                            "bbox": [0, 0, 10, 10],
                            "widget": "Image.asset",
                        }
                    },
                }
            },
            [(0, 0, 0, 255)] * 100,
            [(255, 255, 255, 255)] * 100,
            10,
            10,
        )
        assert len(schema_asset_issues) == 1, schema_asset_issues
        assert schema_asset_issues[0]["component"] == "approved-alias", schema_asset_issues
        assert schema_asset_issues[0]["state"] == "approved", schema_asset_issues
        assert schema_asset_issues[0]["bbox"] == [0, 0, 10, 10], schema_asset_issues

        write_json(
            root / "expected.json",
            {
                "nodes": {
                    "97:194": {"bbox": [0, 0, 10, 10]},
                    "unique-current-board": {"bbox": [20, 0, 10, 10]},
                }
            },
        )
        scoped_trace = root / "actual_layout_trace.json"
        write_json(
            scoped_trace,
            {
                "pageType": "RuntimePage",
                "expectedNodeIds": ["97:194", "unique-current-board"],
                "nodes": {
                    "97:194": {"present": True, "bbox": [0, 0, 10, 10]},
                    "unique-current-board": {"present": True, "bbox": [20, 0, 10, 10]},
                },
            },
        )
        feature_diff = root / "post_repair_diff_report.json"
        write_json(
            feature_diff,
            {
                "assetIssues": [
                    {"node": "97:194", "board": root.name, "state": "approved", "component": "alias-a", "bbox": [0, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.123},
                    {"node": "97:194", "board": root.name, "state": "approved", "component": "alias-b", "bbox": [0, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.123},
                    {"node": "97:194", "board": root.name, "state": "approved", "component": "alias-c", "bbox": [0, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.123},
                    {"node": "17:158", "board": "other-state", "state": "declined", "component": "other-a", "bbox": [0, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 1.0},
                    {"node": "17:158", "board": "other-state", "state": "declined", "component": "other-b", "bbox": [0, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.2},
                    {"node": "180:2779", "board": root.name, "state": "other-alias", "component": "wrong-region-a", "bbox": [40, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.1038},
                    {"node": "180:2779", "board": root.name, "state": "other-alias", "component": "wrong-region-b", "bbox": [40, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.1038},
                    {"node": "180:2779", "board": root.name, "state": "other-alias", "component": "wrong-region-c", "bbox": [40, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.1038},
                    {"node": "unique-current-board", "board": root.name, "state": "approved", "component": "unique", "bbox": [20, 0, 10, 10], "widget": "Image.asset", "role": "icon", "pixelMismatch": 0.25},
                ]
            },
        )
        scoped = run(script, root, scoped_trace, "scoped", feature_diff)
        assert scoped.returncode != 0, scoped.stdout
        scoped_report = json.loads((root / "scoped_report.json").read_text(encoding="utf-8"))
        asset_failures = [item for item in scoped_report["failures"] if item["category"] == "asset_shape"]
        assert [item["node"] for item in asset_failures] == ["97:194", "unique-current-board"], asset_failures
        assert asset_failures[0]["observed"] == 0.123, asset_failures
        assert asset_failures[0]["aliasCount"] == 3, asset_failures
        assert asset_failures[1]["observed"] == 0.25, asset_failures
        assert all(item["tol"] == 0.10 for item in asset_failures), asset_failures

        write_json(root / "expected.json", {
            "designPixelScale": 2,
            "nodes": {"logical": {
                "bbox": [20, 40, 60, 80], "text": "X", "fontSize": 28, "radius": 16,
            }},
        })
        logical_trace = root / "logical_trace.json"
        write_json(logical_trace, {
            "pageType": "RuntimePage", "expectedNodeIds": ["logical"],
            "nodes": {"logical": {
                "present": True, "bbox": [10, 20, 30, 40], "text": "X",
                "fontSize": 14, "radius": 8,
            }},
        })
        logical = run(script, root, logical_trace, "logical")
        assert logical.returncode == 0, logical.stdout

    print("PASS: render fidelity handles board-scoped assets and 375 logical export scale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
