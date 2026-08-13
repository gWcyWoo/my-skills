from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "visual_diff.py"


def write_solid_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    raw = b"".join(
        b"\x00" + bytes(channel for pixel in pixels[y * width : (y + 1) * width] for channel in pixel)
        for y in range(height)
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class VisualDiffTest(unittest.TestCase):
    def test_significant_difference_outside_expected_widgets_is_unexpected_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            width = height = 20
            reference_pixels = [(255, 255, 255, 255)] * (width * height)
            actual_pixels = list(reference_pixels)
            for y in range(10, 20):
                for x in range(10, 20):
                    actual_pixels[y * width + x] = (0, 0, 0, 255)
            reference = root / "reference.png"
            actual = root / "actual.png"
            write_solid_png(reference, width, height, reference_pixels)
            write_solid_png(actual, width, height, actual_pixels)
            layout = root / "layout.json"
            layout.write_text(
                json.dumps(
                    {
                        "known": {
                            "widgets": {
                                "label": {"node": "label", "widget": "text", "bbox": [0, 0, 5, 5]}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--reference",
                    str(reference),
                    "--actual",
                    str(actual),
                    "--layout",
                    str(layout),
                    "--out",
                    str(report),
                    "--heatmap",
                    str(root / "heatmap.png"),
                    "--ssim-threshold",
                    "0",
                    "--pixel-threshold",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            issues = json.loads(report.read_text(encoding="utf-8"))["unexpectedIssues"]
            self.assertEqual(100, issues[0]["pixelCount"])


if __name__ == "__main__":
    unittest.main()
