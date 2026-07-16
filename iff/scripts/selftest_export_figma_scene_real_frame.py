#!/usr/bin/env python3
from export_figma_scene import bbox_of


def main() -> int:
    rotated = {
        "rotation": 80.72179947167388,
        "frame": {"left": 419.1309, "top": 336.9297, "width": 743.1619, "height": 656.1918},
        "realFrame": {"left": 419.1309, "top": -396.8587, "width": 753.6098, "height": 895.5217},
    }
    assert bbox_of(rotated) == [419.1309, -396.8587, 753.6098, 895.5217]
    unrotated = dict(rotated)
    unrotated["rotation"] = 0
    assert bbox_of(unrotated) == [419.1309, 336.9297, 743.1619, 656.1918]
    print("OK: rotated Lanhu nodes prefer realFrame while unrotated nodes retain frame")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
