#!/usr/bin/env python3
"""Regression: confirmed API text may differ from the design fixture."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run(script: Path, root: Path, bindings: Path | None, name: str) -> subprocess.CompletedProcess[str]:
    command = [
        "python3", str(script),
        "--trace", str(root / "trace.json"),
        "--expected", str(root / "expected.json"),
        "--out", str(root / f"{name}.json"),
    ]
    if bindings is not None:
        command.extend(["--data-slot-bindings", str(bindings)])
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    script = Path(__file__).with_name("check_render_fidelity.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "expected.json", {
            "nodes": {"plan-title": {"bbox": [10, 10, 120, 24], "impl": "text", "text": "Design plan"}},
        })
        write_json(root / "trace.json", {
            "pageType": "RuntimePage",
            "expectedNodeIds": ["plan-title"],
            "nodes": {"plan-title": {"present": True, "bbox": [10, 10, 120, 24], "text": "API plan B"}},
        })

        baseline = run(script, root, None, "baseline")
        if baseline.returncode == 0:
            raise AssertionError("text mismatch without API provenance must fail")

        unconfirmed = root / "unconfirmed.json"
        write_json(unconfirmed, {"bindings": [{
            "node": "plan-title",
            "binding": {"field": "plan.title"},
            "contentSource": {"kind": "api", "evidence": "GET /plans response.plan.title"},
            "confirmedByModel": False,
        }]})
        if run(script, root, unconfirmed, "unconfirmed").returncode == 0:
            raise AssertionError("unconfirmed API provenance must not exempt text")

        confirmed = root / "confirmed.json"
        write_json(confirmed, {"bindings": [{
            "node": "plan-title",
            "binding": {"field": "plan.title"},
            "contentSource": {"kind": "api", "evidence": "GET /plans response.plan.title"},
            "confirmedByModel": True,
        }]})
        accepted = run(script, root, confirmed, "accepted")
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)
        report = json.loads((root / "accepted.json").read_text(encoding="utf-8"))
        if report.get("dynamicContentExclusions") != ["plan-title"]:
            raise AssertionError(report)

        invalid = root / "invalid.json"
        write_json(invalid, {"bindings": [{
            "node": "plan-title",
            "binding": {"field": "plan.title"},
            "contentSource": {"kind": "api", "evidence": ""},
            "confirmedByModel": True,
        }]})
        if run(script, root, invalid, "invalid").returncode == 0:
            raise AssertionError("confirmed API binding without evidence must fail visibly")

    print("ok render fidelity API dynamic-content contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
