#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from shared_core import visual_evidence_v1 as visual


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
)


def _files(root: Path) -> tuple[Path, Path, Path, Path]:
    reference = root / "reference.png"
    actual = root / "actual.png"
    diff = root / "diff.png"
    provenance = root / "provenance.json"
    reference.write_bytes(PNG)
    changed = bytearray(PNG)
    changed[-13] ^= 1
    actual.write_bytes(bytes(changed))
    diff.write_bytes(PNG)
    provenance.write_text(
        json.dumps(
            {
                "kind": "icp.runtime-provenance.v1",
                "actual_source": "browser_screenshot",
                "actual_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return reference, actual, diff, provenance


def test_visual_evidence_is_platform_independent_and_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-evidence-") as directory:
        reference, actual, diff, provenance = _files(Path(directory).resolve())
        evidence = visual.build_evidence(
            reference_path=reference,
            actual_path=actual,
            diff_path=diff,
            actual_provenance_path=provenance,
            mismatch_ratio=0.01,
            max_mismatch_ratio=0.02,
        )
        assert evidence["status"] == "pass"
        visual.verify_evidence(evidence)
        evidence["diff"]["mismatch_ratio"] = 0.5
        try:
            visual.verify_evidence(evidence)
        except visual.VisualEvidenceError as exc:
            assert "status" in str(exc)
        else:
            raise AssertionError("tampered visual status must fail")


def test_design_reference_cannot_be_used_as_actual() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-copy-") as directory:
        reference, actual, diff, provenance = _files(Path(directory).resolve())
        actual.write_bytes(reference.read_bytes())
        provenance.write_text(
            json.dumps(
                {
                    "actual_source": "browser_screenshot",
                    "actual_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        try:
            visual.build_evidence(
                reference_path=reference,
                actual_path=actual,
                diff_path=diff,
                actual_provenance_path=provenance,
                mismatch_ratio=0,
                max_mismatch_ratio=0,
            )
        except visual.VisualEvidenceError as exc:
            assert "copied design" in str(exc)
        else:
            raise AssertionError("design image as actual must fail")


def main() -> int:
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    failures = 0
    for name, test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok {name}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
