#!/usr/bin/env python3
from __future__ import annotations

from check_asset_resources import validate


def main() -> int:
    good = {
        "icon": {"format": "svg", "resourcePolicy": "pure_vector", "logicalSize": [24, 24]},
        "photo": {
            "format": "webp", "resourcePolicy": "density_bitmap", "logicalSize": [120, 80],
            "pixelSize": [360, 240], "sourceDensity": [3, 3],
        },
    }
    if validate(good, 3):
        raise AssertionError(validate(good, 3))
    low_resolution = {"photo": dict(good["photo"], pixelSize=[120, 80], sourceDensity=[1, 1])}
    failures = validate(low_resolution, 3)
    if not any("low-resolution bitmap" in failure for failure in failures):
        raise AssertionError(failures)
    wrong_vector = {"icon": dict(good["icon"], format="png")}
    failures = validate(wrong_vector, 3)
    if not any("must use SVG" in failure for failure in failures):
        raise AssertionError(failures)
    print("ok asset resource contract selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
