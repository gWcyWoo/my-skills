#!/usr/bin/env python3
import math

from generate_canvas import unrotated_size_from_aabb


def main() -> int:
    aabb_width = 743.1619262695312
    aabb_height = 656.1918334960938
    rotation = 80.72179947167388
    local = unrotated_size_from_aabb(aabb_width, aabb_height, rotation)
    assert local is not None
    local_width, local_height = local
    radians = math.radians(rotation)
    rebuilt_width = abs(local_width * math.cos(radians)) + abs(local_height * math.sin(radians))
    rebuilt_height = abs(local_width * math.sin(radians)) + abs(local_height * math.cos(radians))
    assert abs(rebuilt_width - aabb_width) < 0.01
    assert abs(rebuilt_height - aabb_height) < 0.01
    assert local_width < aabb_width and local_height > aabb_height
    assert unrotated_size_from_aabb(100, 100, 45) is None
    print("OK: rotated local size rebuilds the render-plan AABB without double rotation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
