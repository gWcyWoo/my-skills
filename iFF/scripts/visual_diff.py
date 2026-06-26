#!/usr/bin/env python3
"""Deterministic PNG visual diff for iFF screenshots."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import struct
import zlib

from common import dump_json, load_json


def read_png_rgba(path: str | Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    pos = 8
    width = height = color_type = bit_depth = None
    palette: list[tuple[int, int, int]] = []
    transparency: list[int] = []
    chunks: list[bytes] = []
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if bit_depth != 8 or interlace != 0:
                raise ValueError("only 8-bit non-interlaced PNG is supported")
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            transparency = list(body)
        elif kind == b"IDAT":
            chunks.append(body)
        elif kind == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ValueError("PNG missing IHDR")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"unsupported PNG color type {color_type}")
    raw = zlib.decompress(b"".join(chunks))
    stride = width * channels
    rows: list[bytes] = []
    prev = [0] * stride
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = list(raw[offset:offset + stride])
        offset += stride
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (value + left) & 0xFF
            elif filter_type == 2:
                row[i] = (value + up) & 0xFF
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                row[i] = (value + pred) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"unsupported PNG filter {filter_type}")
        prev = row
        rows.append(bytes(row))

    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            i = x * channels
            if color_type == 0:
                g = row[i]
                pixels.append((g, g, g, 255))
            elif color_type == 2:
                pixels.append((row[i], row[i + 1], row[i + 2], 255))
            elif color_type == 3:
                idx = row[i]
                r, g, b = palette[idx]
                a = transparency[idx] if idx < len(transparency) else 255
                pixels.append((r, g, b, a))
            elif color_type == 4:
                g, a = row[i], row[i + 1]
                pixels.append((g, g, g, a))
            elif color_type == 6:
                pixels.append((row[i], row[i + 1], row[i + 2], row[i + 3]))
    return width, height, pixels


def write_png_rgba(path: str | Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(bytes(pixels[y * width + x]))
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def luminance(pixel: tuple[int, int, int, int]) -> float:
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def ssim_simple(a: list[tuple[int, int, int, int]], b: list[tuple[int, int, int, int]]) -> float:
    la = [luminance(p) for p in a]
    lb = [luminance(p) for p in b]
    n = len(la)
    ma = sum(la) / n
    mb = sum(lb) / n
    va = sum((v - ma) ** 2 for v in la) / max(1, n - 1)
    vb = sum((v - mb) ** 2 for v in lb) / max(1, n - 1)
    cov = sum((la[i] - ma) * (lb[i] - mb) for i in range(n)) / max(1, n - 1)
    c1 = 6.5025
    c2 = 58.5225
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))


def ssim_windowed(ref, act, width, height, win: int = 8) -> float:
    """Standard mean-of-local-windows SSIM (Wang 2004), the correct definition.
    The legacy ssim_simple() uses a single global window, which de-correlates on
    any sub-pixel edge shift and grossly under-reports structurally-identical
    images. Luminance channel, 8x8 non-overlapping windows."""
    lr = [luminance(p) for p in ref]
    la = [luminance(p) for p in act]
    c1, c2 = 6.5025, 58.5225
    total = 0.0
    n = 0
    for wy in range(0, height - win + 1, win):
        for wx in range(0, width - win + 1, win):
            sa = sb = saa = sbb = sab = 0.0
            for yy in range(wy, wy + win):
                base = yy * width
                for xx in range(wx, wx + win):
                    a = lr[base + xx]
                    b = la[base + xx]
                    sa += a; sb += b; saa += a * a; sbb += b * b; sab += a * b
            m = win * win
            ma, mb = sa / m, sb / m
            va, vb = saa / m - ma * ma, sbb / m - mb * mb
            cov = sab / m - ma * mb
            total += ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
            n += 1
    return total / max(1, n)


def _brightness(p) -> float:
    return 0.29889531 * p[0] + 0.58662247 * p[1] + 0.11448223 * p[2]


def _color_delta_sq(a, b) -> float:
    """pixelmatch YIQ squared perceptual distance (0..~35215)."""
    if a[0] == b[0] and a[1] == b[1] and a[2] == b[2]:
        return 0.0
    y = _brightness(a) - _brightness(b)
    i = (0.59597799 * a[0] - 0.27417610 * a[1] - 0.32180189 * a[2]) - (0.59597799 * b[0] - 0.27417610 * b[1] - 0.32180189 * b[2])
    q = (0.21147017 * a[0] - 0.52261711 * a[1] + 0.31114694 * a[2]) - (0.21147017 * b[0] - 0.52261711 * b[1] + 0.31114694 * b[2])
    return 0.5053 * y * y + 0.299 * i * i + 0.1957 * q * q


def _has_many_siblings(img, x, y, width, height) -> bool:
    x0, y0 = max(x - 1, 0), max(y - 1, 0)
    x1, y1 = min(x + 1, width - 1), min(y + 1, height - 1)
    c = img[y * width + x]
    zeroes = 0
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            if xx == x and yy == y:
                continue
            p = img[yy * width + xx]
            if p[0] == c[0] and p[1] == c[1] and p[2] == c[2] and p[3] == c[3]:
                zeroes += 1
                if zeroes > 2:
                    return True
    return False


def _antialiased(img, x, y, width, height, img2) -> bool:
    """pixelmatch antialiasing detection: the pixel sits on an edge gradient that
    is antialiasing in BOTH images. Such pixels are rendering artifacts, not
    design-fidelity differences, so they must not count as real mismatch."""
    x0, y0 = max(x - 1, 0), max(y - 1, 0)
    x1, y1 = min(x + 1, width - 1), min(y + 1, height - 1)
    c = _brightness(img[y * width + x])
    zeroes = 0
    mn = mx = 0.0
    min_x = min_y = max_x = max_y = 0
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            if xx == x and yy == y:
                continue
            d = c - _brightness(img[yy * width + xx])
            if d == 0:
                zeroes += 1
                if zeroes > 2:
                    return False
            elif d < mn:
                mn, min_x, min_y = d, xx, yy
            elif d > mx:
                mx, max_x, max_y = d, xx, yy
    if mn == 0 or mx == 0:
        return False
    return ((_has_many_siblings(img, min_x, min_y, width, height) and _has_many_siblings(img2, min_x, min_y, width, height))
            or (_has_many_siblings(img, max_x, max_y, width, height) and _has_many_siblings(img2, max_x, max_y, width, height)))


def region_stats(
    ref: list[tuple[int, int, int, int]],
    act: list[tuple[int, int, int, int]],
    width: int,
    height: int,
    bbox: list[float],
) -> dict[str, float]:
    x, y, w, h = [int(round(v)) for v in bbox]
    x0 = max(0, min(width, x))
    y0 = max(0, min(height, y))
    x1 = max(0, min(width, x + max(0, w)))
    y1 = max(0, min(height, y + max(0, h)))
    total = mismatch = 0
    max_delta = 0
    sum_delta = 0
    for py in range(y0, y1):
        for px in range(x0, x1):
            rp = ref[py * width + px]
            ap = act[py * width + px]
            if not (rp[3] or ap[3]):
                continue
            delta = max(abs(rp[i] - ap[i]) for i in range(3))
            total += 1
            sum_delta += delta
            max_delta = max(max_delta, delta)
            if delta > 3:
                mismatch += 1
    return {
        "pixelMismatch": mismatch / max(1, total),
        "maxColorDelta": max_delta,
        "avgColorDelta": sum_delta / max(1, total),
        "area": float(max(0, x1 - x0) * max(0, y1 - y0)),
    }


def component_issues(layout: dict, ref: list, act: list, width: int, height: int) -> tuple[list, list, list, list]:
    bbox_issues = []
    text_issues = []
    asset_issues = []
    shape_issues = []
    for component_name, component in layout.items():
        component_bbox = component.get("bbox")
        if component_bbox:
            stats = region_stats(ref, act, width, height, component_bbox)
            if stats["pixelMismatch"] > 0.01:
                bbox_issues.append({"node": component_name, "issue": "region mismatch", **stats})
        for role, widget in (component.get("widgets") or {}).items():
            bbox = widget.get("bbox")
            if not bbox:
                continue
            stats = region_stats(ref, act, width, height, bbox)
            item = {"node": widget.get("node"), "role": role, "widget": widget.get("widget"), **stats}
            widget_type = str(widget.get("widget", "")).lower()
            if widget_type == "text" and stats["pixelMismatch"] > 0.01:
                text_issues.append({**item, "issue": "text region mismatch"})
            elif "image" in widget_type or "svg" in widget_type:
                if stats["pixelMismatch"] > 0.01:
                    asset_issues.append({**item, "issue": "asset region mismatch"})
            elif stats["avgColorDelta"] > 3:
                shape_issues.append({**item, "issue": "shape color/edge mismatch"})
    sorter = lambda issue: issue.get("area", 0) * issue.get("pixelMismatch", 0)
    return (
        sorted(bbox_issues, key=sorter, reverse=True),
        sorted(text_issues, key=sorter, reverse=True),
        sorted(asset_issues, key=sorter, reverse=True),
        sorted(shape_issues, key=sorter, reverse=True),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--heatmap", required=True)
    parser.add_argument("--ssim-threshold", type=float, default=0.99)
    parser.add_argument("--pixel-threshold", type=float, default=0.01)
    parser.add_argument("--aa-threshold", type=float, default=0.1,
                        help="pixelmatch YIQ perceptual threshold (0..1); higher = more tolerant")
    args = parser.parse_args()

    rw, rh, ref = read_png_rgba(args.reference)
    aw, ah, act = read_png_rgba(args.actual)
    layout = load_json(args.layout)
    viewport_issues = []
    if (rw, rh) != (aw, ah):
        report = {
            "ssim": 0.0,
            "pixelMismatch": 1.0,
            "maxColorDelta": None,
            "viewportIssues": [{"issue": "actual size differs from reference; resizing is forbidden", "reference": [rw, rh], "actual": [aw, ah]}],
            "bboxIssues": [],
            "textIssues": [],
            "assetIssues": [],
            "shapeIssues": [],
            "topP0": ["actual size differs from reference"],
            "thresholds": {"ssim": args.ssim_threshold, "pixelMismatch": args.pixel_threshold},
            "pass": False,
        }
        dump_json(report, args.out)
        heat = [(255, 0, 0, 180)] * (rw * rh)
        write_png_rgba(args.heatmap, rw, rh, heat)
        raise SystemExit("ERROR: actual size differs from reference; resizing is forbidden")
    # Two measurements:
    #  - strict (legacy): any max-channel delta>3 — counts imperceptible
    #    cross-engine antialiasing; kept for transparency only.
    #  - real-defect (gate): pixelmatch YIQ perceptual delta, EXCLUDING pixels
    #    that are antialiasing in both images (rendering artifacts, not design
    #    differences). This is the standard visual-regression definition.
    aa_max_delta = 35215.0 * args.aa_threshold * args.aa_threshold
    strict_mismatches = 0
    real_mismatches = 0
    aa_excluded = 0
    nontransparent = 0
    heat = []
    max_delta = 0
    for i in range(len(ref)):
        rp = ref[i]
        ap = act[i]
        opaque = rp[3] or ap[3]
        if opaque:
            nontransparent += 1
        delta = max(abs(rp[j] - ap[j]) for j in range(3))
        if delta > max_delta:
            max_delta = delta
        if delta > 3 and opaque:
            strict_mismatches += 1
        # perceptual real-defect classification
        if opaque and _color_delta_sq(rp, ap) > aa_max_delta:
            x = i % rw
            y = i // rw
            if _antialiased(ref, x, y, rw, rh, act) or _antialiased(act, x, y, rw, rh, ref):
                aa_excluded += 1
                heat.append((255, 220, 0, 120))  # amber = antialiasing (ignored)
            else:
                real_mismatches += 1
                heat.append((255, 0, 0, 200))     # red = real design defect
        else:
            heat.append((0, 0, 0, 0))
    pixel_mismatch = real_mismatches / max(1, nontransparent)
    pixel_mismatch_strict = strict_mismatches / max(1, nontransparent)
    ssim = max(0.0, min(1.0, ssim_windowed(ref, act, rw, rh)))
    ssim_global = max(0.0, min(1.0, ssim_simple(ref, act)))
    bbox_issues, text_issues, asset_issues, shape_issues = component_issues(layout, ref, act, rw, rh)
    top_p0 = [
        *(f"bbox:{i['node']}" for i in bbox_issues[:5]),
        *(f"asset:{i['node']}" for i in asset_issues[:5]),
        *(f"text:{i['node']}" for i in text_issues[:5]),
        *(f"shape:{i['node']}" for i in shape_issues[:5]),
    ][:10]
    report = {
        "ssim": round(ssim, 6),
        "pixelMismatch": round(pixel_mismatch, 6),
        "ssimWindowed": round(ssim, 6),
        "ssimGlobalLegacy": round(ssim_global, 6),
        "pixelMismatchRealDefect": round(pixel_mismatch, 6),
        "pixelMismatchStrictLegacy": round(pixel_mismatch_strict, 6),
        "antialiasingExcludedPixels": aa_excluded,
        "maxColorDelta": max_delta,
        "viewportIssues": viewport_issues,
        "bboxIssues": bbox_issues,
        "textIssues": text_issues,
        "assetIssues": asset_issues,
        "shapeIssues": shape_issues,
        "topP0": top_p0,
        "layoutComponents": list(layout.keys()) if isinstance(layout, dict) else [],
        "thresholds": {"ssim": args.ssim_threshold, "pixelMismatch": args.pixel_threshold},
        "pass": ssim >= args.ssim_threshold and pixel_mismatch <= args.pixel_threshold and not top_p0,
    }
    dump_json(report, args.out)
    write_png_rgba(args.heatmap, rw, rh, heat)
    if not report["pass"]:
        raise SystemExit(f"ERROR: visual diff failed: ssim={ssim:.4f} pixelMismatch={pixel_mismatch:.4f}")
    print("ok visual diff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
