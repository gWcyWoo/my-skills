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
    mismatches = 0
    nontransparent = 0
    heat = []
    max_delta = 0
    for rp, ap in zip(ref, act):
        if rp[3] or ap[3]:
            nontransparent += 1
        delta = max(abs(rp[i] - ap[i]) for i in range(3))
        max_delta = max(max_delta, delta)
        if delta > 3 and (rp[3] or ap[3]):
            mismatches += 1
            heat.append((255, 0, 0, 180))
        else:
            heat.append((0, 0, 0, 0))
    pixel_mismatch = mismatches / max(1, nontransparent)
    ssim = max(0.0, min(1.0, ssim_simple(ref, act)))
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
