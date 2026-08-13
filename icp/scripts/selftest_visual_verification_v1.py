#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from shared_core import visual_evidence_v1 as evidence
from shared_core import visual_verification_v1 as verification


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
)


def _run(root: Path, name: str, mutation_index: int) -> Path:
    reference = root / "reference.png"
    if not reference.exists():
        reference.write_bytes(PNG)
    actual = root / f"actual-{name}.png"
    diff = root / f"diff-{name}.png"
    provenance = root / f"provenance-{name}.json"
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
                "capture_id": f"capture-{name}",
                "state_reset_id": f"reset-{name}",
            }
        ),
        encoding="utf-8",
    )
    manifest = evidence.build_evidence(
        reference_path=reference,
        actual_path=actual,
        diff_path=diff,
        actual_provenance_path=provenance,
        mismatch_ratio=0.01,
        max_mismatch_ratio=0.02,
    )
    path = root / f"visual-evidence-{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path.resolve()


def _calibration() -> dict[str, object]:
    return {
        "reference_width": 1,
        "reference_height": 1,
        "runtime_width": 1,
        "runtime_height": 1,
        "density": 1.0,
        "font_scale": 1.0,
        "locale": "ru-KZ",
        "theme": "light",
        "system_bars": "excluded",
        "animations_disabled": True,
    }


def _state(run_1: Path, run_2: Path) -> dict[str, object]:
    return {
        "name": "customer-service-modal",
        "contract": "Opening customer service shows the approved bottom modal.",
        "final_runs": [str(run_1), str(run_2)],
        "anchors": [
            {
                "name": "modal_top",
                "expected": 560.0,
                "actual": 561.0,
                "tolerance": 2.0,
            }
        ],
        "regions": [
            {
                "name": "modal_card",
                "mismatch_ratio": 0.01,
                "max_mismatch_ratio": 0.02,
            }
        ],
    }


def test_requires_two_distinct_clean_runs_with_anchors_and_regions() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-verification-") as directory:
        root = Path(directory).resolve()
        run_1 = _run(root, "one", -13)
        run_2 = _run(root, "two", -14)
        document = verification.build_verification(
            calibration=_calibration(),
            states=[_state(run_1, run_2)],
            repair_history=[
                {
                    "iteration": 1,
                    "state": "customer-service-modal",
                    "classification": "layout",
                    "target": "modal_top",
                    "before_score": 0.12,
                    "after_score": 0.08,
                }
            ],
        )

        assert document["status"] == "pass"
        assert len(document["states"][0]["final_runs"]) == 2
        assert document["states"][0]["anchors"][0]["status"] == "pass"
        assert document["states"][0]["regions"][0]["status"] == "pass"
        verification.verify_verification(document)


def test_accepts_identical_pixels_from_distinct_capture_and_reset_events() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-stable-") as directory:
        root = Path(directory).resolve()
        run_1 = _run(root, "one", -13)
        run_2 = _run(root, "two", -13)
        document = verification.build_verification(
            calibration=_calibration(),
            states=[_state(run_1, run_2)],
            repair_history=[],
        )

        assert document["status"] == "pass"
        verification.verify_verification(document)


def test_rejects_reused_runtime_capture_as_second_clean_run() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-repeat-") as directory:
        root = Path(directory).resolve()
        run_1 = _run(root, "one", -13)
        try:
            verification.build_verification(
                calibration=_calibration(),
                states=[_state(run_1, run_1)],
                repair_history=[],
            )
        except verification.VisualVerificationError as exc:
            assert "distinct runtime captures" in str(exc)
        else:
            raise AssertionError("a repeated capture must not count as two clean runs")


def test_rejects_anchor_failure_even_when_global_pixel_ratio_passes() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-anchor-") as directory:
        root = Path(directory).resolve()
        state = _state(_run(root, "one", -13), _run(root, "two", -14))
        state["anchors"][0]["actual"] = 570.0
        try:
            verification.build_verification(
                calibration=_calibration(),
                states=[state],
                repair_history=[],
            )
        except verification.VisualVerificationError as exc:
            assert "anchor" in str(exc)
        else:
            raise AssertionError("global pixels must not hide a failed geometry anchor")


def test_rejects_two_consecutive_no_progress_repairs_for_same_target() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-stalled-") as directory:
        root = Path(directory).resolve()
        state = _state(_run(root, "one", -13), _run(root, "two", -14))
        history = [
            {
                "iteration": 1,
                "state": "customer-service-modal",
                "classification": "layout",
                "target": "modal_top",
                "before_score": 0.12,
                "after_score": 0.12,
            },
            {
                "iteration": 2,
                "state": "customer-service-modal",
                "classification": "layout",
                "target": "modal_top",
                "before_score": 0.12,
                "after_score": 0.13,
            },
        ]
        try:
            verification.build_verification(
                calibration=_calibration(),
                states=[state],
                repair_history=history,
            )
        except verification.VisualVerificationError as exc:
            assert "two consecutive no-progress" in str(exc)
        else:
            raise AssertionError("a stalled target must take the controlled failure path")


def test_rejects_non_normalized_repair_scores() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-visual-score-") as directory:
        root = Path(directory).resolve()
        history = [
            {
                "iteration": 1,
                "state": "customer-service-modal",
                "classification": "layout",
                "target": "modal_top",
                "before_score": 12.0,
                "after_score": 8.0,
            }
        ]
        try:
            verification.build_verification(
                calibration=_calibration(),
                states=[_state(_run(root, "one", -13), _run(root, "two", -14))],
                repair_history=history,
            )
        except verification.VisualVerificationError as exc:
            assert "[0,1]" in str(exc)
        else:
            raise AssertionError("repair scores must use one normalized metric")


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
