#!/usr/bin/env python3
"""Generic raw.json layer query helper for fc step-5 ambiguity resolution.

Reads `raw.json` (as produced by `fd`), filters layers by id / type /
name substring, and emits a compact JSON list of normalized layer
records to stdout. Replaces ad-hoc `jq` / inline-Python on raw.json.

Usage:
  inspect_layers.py --raw-json <path> [--ids ID,ID,...]
                                       [--type textLayer|shapeLayer|groupLayer|artboard]
                                       [--name-contains SUBSTR]

Output (one line of compact JSON to stdout):
  [{
    "id":          "<layer id>",
    "type":        "textLayer|shapeLayer|groupLayer|artboard",
    "name":        "<layer name>",
    "path":        "ancestor>...>self",
    "parent_id":   "<id of immediate parent, null at root>",
    "frame":       {"x": ..., "y": ..., "w": ..., "h": ...},
    "visible":     true|false,
    "text_content":"..."                # textLayer only; raw newlines preserved
    "font":        {"size", "weight", "family"},  # textLayer
    "text_color":  "0xAARRGGBB",        # textLayer
    "fill_color":  "0xAARRGGBB",        # shapeLayer (primary visible fill)
    "asset":       "assets/<basename>"  # if hasExportImage / hasExportDDSImage
  }]

If no filter is supplied, every layer in the artboard tree is emitted —
useful for debugging schema, but step 5 should always pass a filter.

Exit codes:
  0 — success.
  2 — input error (raw.json missing / unreadable / malformed schema).
"""

import argparse
import json
import sys
from pathlib import Path


# ---------- color normalization (mirror check_static.py) ----------

def color_to_argb_hex(c):
    """Convert a Figma color dict to a '0xAARRGGBB' string. None if unparseable."""
    if not isinstance(c, dict):
        return None
    v = c.get("value")
    if isinstance(v, str) and v.startswith("#"):
        h = v.lstrip("#").upper()
        if len(h) == 6:
            return f"0xFF{h}"
        if len(h) == 8:
            return f"0x{h[6:8]}{h[0:6]}"
    r, g, b = c.get("r"), c.get("g"), c.get("b")
    a = c.get("a", 1)
    if r is None or g is None or b is None:
        return None
    R, G, B, A = round(r * 255), round(g * 255), round(b * 255), round(a * 255)
    return f"0x{A:02X}{R:02X}{G:02X}{B:02X}"


def asset_basename(layer):
    img = layer.get("image") or {}
    src = img.get("imageUrl") or img.get("svgUrl") or ""
    if not src:
        return None
    base = src.split("/")[-1].split("?")[0]
    return f"assets/{base}" if base else None


# ---------- traversal ----------

def load_artboard(raw_path):
    """Locate the artboard tree across the wrapper schemas.

    Real on-disk shape (per fd's fetch.py):
        {design_name, design_id, version_id, lanhu_url,
         figma_json: {meta, assets, artboard: {...}}}
    Fallback: a stripped form where `artboard` is at the top level.
    """
    with open(raw_path, encoding="utf-8") as f:
        wrapper = json.load(f)
    fj = wrapper.get("figma_json")
    if isinstance(fj, dict) and isinstance(fj.get("artboard"), dict):
        return fj["artboard"]
    if isinstance(wrapper.get("artboard"), dict):
        return wrapper["artboard"]
    raise ValueError("raw.json missing figma_json.artboard")


def walk(node, parent_id=None, parent_path=""):
    if not isinstance(node, dict):
        return
    name = node.get("name", "")
    path = f"{parent_path}>{name}" if parent_path else name
    yield node, parent_id, path
    for sub in node.get("layers") or []:
        yield from walk(sub, node.get("id"), path)


# ---------- normalization ----------

def normalize(layer, parent_id, path):
    f = layer.get("frame") or {}
    rec = {
        "id":        layer.get("id"),
        "type":      layer.get("type", ""),
        "name":      layer.get("name", ""),
        "path":      path,
        "parent_id": parent_id,
        "frame":     {
            "x": f.get("left"),
            "y": f.get("top"),
            "w": f.get("width"),
            "h": f.get("height"),
        } if f else None,
        "visible":   layer.get("visible", True),
    }

    if rec["type"] == "textLayer":
        text = layer.get("text") or {}
        ts = text.get("style") or {}
        font = ts.get("font") or {}
        rec["text_content"] = ts.get("content") or text.get("value") or ""
        rec["font"] = {
            "size":   font.get("size"),
            "weight": font.get("fontWeight"),
            "family": font.get("postScriptName") or font.get("name"),
        }
        rec["text_color"] = color_to_argb_hex(ts.get("color"))

    if rec["type"] == "shapeLayer":
        style = layer.get("style") or {}
        for fill in (style.get("fills") or []):
            if not fill.get("visible", True):
                continue
            c = color_to_argb_hex(fill.get("color"))
            if c:
                rec["fill_color"] = c
                break

    if layer.get("hasExportImage") or layer.get("hasExportDDSImage"):
        a = asset_basename(layer)
        if a:
            rec["asset"] = a

    return rec


# ---------- driver ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-json", required=True)
    ap.add_argument("--ids",
                    help="comma-separated layer ids (e.g. 20:377,20:379)")
    ap.add_argument("--type",
                    help="layer type filter (textLayer|shapeLayer|groupLayer|artboard)")
    ap.add_argument("--name-contains",
                    help="case-sensitive substring match on layer name")
    args = ap.parse_args()

    try:
        artboard = load_artboard(args.raw_json)
    except FileNotFoundError:
        print(json.dumps({"error": f"raw.json not found: {args.raw_json}"}),
              flush=True)
        sys.exit(2)
    except (ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"raw.json parse error: {e}"}), flush=True)
        sys.exit(2)

    ids = {s.strip() for s in args.ids.split(",")} if args.ids else None
    out = []
    for node, parent_id, path in walk(artboard):
        if ids is not None and node.get("id") not in ids:
            continue
        if args.type and node.get("type") != args.type:
            continue
        if args.name_contains and args.name_contains not in node.get("name", ""):
            continue
        out.append(normalize(node, parent_id, path))

    print(json.dumps(out, ensure_ascii=False), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
