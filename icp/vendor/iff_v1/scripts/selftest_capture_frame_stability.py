#!/usr/bin/env python3
"""Regression: transient or persistently corrupted screenshot frames are never accepted."""

from __future__ import annotations

import tempfile
from pathlib import Path

from capture_runtime_screenshot import (
    frame_mismatch_ratio,
    select_stable_candidate,
    unexpected_dark_ratio,
)
from visual_diff import write_png_rgba


def main() -> int:
    width = height = 20
    white = [(255, 255, 255, 255)] * (width * height)
    good_a = list(white)
    good_b = list(white)
    good_b[10 * width + 10] = (248, 248, 248, 255)
    bad = list(white)
    for y in range(2, 18):
        for x in range(1, 19):
            bad[y * width + x] = (0, 0, 0, 255)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reference = root / "reference.png"
        bad_path = root / "bad.png"
        good_a_path = root / "good_a.png"
        good_b_path = root / "good_b.png"
        write_png_rgba(reference, width, height, white)
        write_png_rgba(bad_path, width, height, bad)
        write_png_rgba(good_a_path, width, height, good_a)
        write_png_rgba(good_b_path, width, height, good_b)

        if frame_mismatch_ratio(bad_path, good_a_path) < 0.5:
            raise AssertionError("large transient corruption was not detected")
        if unexpected_dark_ratio(reference, bad_path) < 0.5:
            raise AssertionError("reference-aware black-block corruption was not detected")
        if unexpected_dark_ratio(reference, good_b_path) > 0.01:
            raise AssertionError("normal antialias variation was classified as corruption")

        selected = select_stable_candidate(
            [bad_path, good_a_path, good_b_path],
            reference_path=reference,
            stable_samples=2,
            mismatch_threshold=0.02,
            unexpected_dark_threshold=0.10,
        )
        if selected != good_b_path:
            raise AssertionError(selected)
        if select_stable_candidate(
            [bad_path, bad_path],
            reference_path=reference,
            stable_samples=2,
            mismatch_threshold=0.02,
            unexpected_dark_threshold=0.10,
        ) is not None:
            raise AssertionError("two stable corrupted frames must still be rejected")

    print("ok capture frame stability selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
