#!/usr/bin/env python3
"""Static visual-correctness check for fc-generated Flutter widgets.

Reads:
  --raw-json <path>    Lanhu Figma JSON (sibling of spec.md, produced by `fd`).
  --code-dir <path>    Directory containing the generated .dart widget files.
  --font-scale <n>     Optional divisor for raw design font sizes when code
                       uses iOS pt / Flutter logical pixels.
Compares declared Color/Text/AssetImage/fontSize/fontWeight literals in the
.dart files against the design layers extracted from raw.json. Outputs a
single line of JSON to stdout.

stdout schema (one line):
  {
    "expected":         <int>,
    "matched":          <int>,
    "mismatches":       [{"layer_id","kind","expected","actual","file","line"}],
    "unmatched_design": [{"layer_id","type","content"|"asset"|"color"}],
    "unmatched_code":   [{"file","line","kind","value"}]
  }

Exit codes:
  0 — matched == expected, no mismatches, no unmatched_design.
  1 — verification failed (mismatches or unmatched_design non-empty).
  2 — input error (raw.json unreadable, no .dart files, etc.).

Notes:
  - "spec values verbatim" (fc P1) means literal Color(0x...), Text("..."),
    AssetImage("..."), fontSize: <num>, fontWeight: FontWeight.w<n> are the
    only forms recognized. Theme/colorScheme references are intentionally
    not matched.
  - bbox / runtime layout are out of scope (Tier 1 only).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ---------- raw.json reading ----------

def walk_layers(node):
    yield node
    for sub in node.get("layers") or []:
        yield from walk_layers(sub)


def color_dict_to_argb(c):
    """Convert a Figma color dict to 0xAARRGGBB int. None if unparseable."""
    if not isinstance(c, dict):
        return None
    v = c.get("value")
    if isinstance(v, str) and v.startswith("#"):
        h = v.lstrip("#")
        if len(h) == 6:
            return int("FF" + h.upper(), 16)
        if len(h) == 8:
            # Figma serializes as #RRGGBBAA; Dart uses 0xAARRGGBB.
            return int((h[6:8] + h[0:6]).upper(), 16)
    r, g, b = c.get("r"), c.get("g"), c.get("b")
    a = c.get("a", 1)
    if r is None or g is None or b is None:
        return None
    R, G, B, A = round(r * 255), round(g * 255), round(b * 255), round(a * 255)
    return (A << 24) | (R << 16) | (G << 8) | B


def asset_basename(layer):
    """Derive the local slice basename for a hasExportImage layer.
    Mirrors fd's slice_filename behavior at the level of basename only.
    """
    img = layer.get("image") or {}
    src = img.get("imageUrl") or img.get("svgUrl") or ""
    if not src:
        return None
    base = src.split("/")[-1].split("?")[0]
    return base or None


def load_artboard(raw):
    """Locate the artboard layer tree.

    The on-disk raw.json (per fd's fetch.py) wraps the Figma payload as
    {design_name, ..., figma_json: {meta, assets, artboard: {...}}}.
    Some intermediate forms strip the wrapper; tolerate both.
    """
    fj = raw.get("figma_json")
    if isinstance(fj, dict) and isinstance(fj.get("artboard"), dict):
        return fj["artboard"]
    if isinstance(raw.get("artboard"), dict):
        return raw["artboard"]
    return {}


def normalize_num(value):
    return int(value) if isinstance(value, float) and value.is_integer() else value


def extract_design_layers(raw, font_scale=1.0):
    """Return list of normalized design records: text / fill / asset."""
    artboard = load_artboard(raw)
    out = []
    for layer in walk_layers(artboard):
        if not layer.get("visible", True):
            continue
        ltype = layer.get("type", "")
        base = {"id": layer.get("id"), "name": layer.get("name", ""),
                "type": ltype}

        if ltype == "textLayer":
            text = layer.get("text") or {}
            ts = text.get("style") or {}
            font = ts.get("font") or {}
            content = ts.get("content") or text.get("value") or ""
            color = color_dict_to_argb(ts.get("color"))
            size = font.get("size")
            font_size = None
            if isinstance(size, (int, float)):
                font_size = normalize_num(size / font_scale)
            weight = font.get("fontWeight")
            rec = dict(base)
            rec.update({
                "kind": "text",
                "content": content,
                "color": color,
                "font_size": font_size,
                "font_weight": int(weight) if isinstance(weight, (int, float)) else None,
            })
            out.append(rec)

        elif ltype == "shapeLayer":
            style = layer.get("style") or {}
            for fill in (style.get("fills") or []):
                if not fill.get("visible", True):
                    continue
                color = color_dict_to_argb(fill.get("color"))
                if color is None:
                    continue
                rec = dict(base)
                rec.update({"kind": "fill", "color": color})
                out.append(rec)
                break  # primary fill only

        if layer.get("hasExportImage") or layer.get("hasExportDDSImage"):
            base_name = asset_basename(layer)
            if base_name:
                rec = dict(base)
                rec.update({"kind": "asset", "asset": base_name})
                out.append(rec)

    return out


# ---------- .dart parsing ----------

_RE_COLOR_HEX = re.compile(r"Color\(\s*0x([0-9A-Fa-f]{8})\s*\)")
_RE_COLOR_ARGB = re.compile(
    r"Color\.fromARGB\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)
_RE_TEXT = re.compile(r"""Text\(\s*(['"])(.*?)\1""", re.DOTALL)
_RE_ASSET = re.compile(
    r"""(?:AssetImage|Image\.asset)\(\s*(['"])([^'"]+?)\1"""
)
_RE_FONT_SIZE = re.compile(r"fontSize\s*:\s*([0-9]+(?:\.[0-9]+)?)")
_RE_FONT_WEIGHT = re.compile(
    r"fontWeight\s*:\s*FontWeight\.(w\d{3}|bold|normal)"
)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def decode_dart_string(s):
    """Decode common Dart escape sequences inside a non-raw string literal.
    Handles \\n \\t \\r \\\\ \\' \\" \\$ — enough for design-text comparison.
    Unicode escapes (\\u…) are passed through verbatim (rare in spec text).
    """
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            nxt = s[i + 1]
            mapped = {"n": "\n", "t": "\t", "r": "\r",
                      "\\": "\\", "'": "'", '"': '"', "$": "$"}.get(nxt)
            if mapped is not None:
                out.append(mapped)
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def parse_dart_file(path):
    src = Path(path).read_text(encoding="utf-8")
    out = []
    for m in _RE_COLOR_HEX.finditer(src):
        out.append({"kind": "color", "value": int(m.group(1), 16),
                    "line": line_of(src, m.start()), "pos": m.start()})
    for m in _RE_COLOR_ARGB.finditer(src):
        a, r, g, b = (int(x) for x in m.groups())
        out.append({"kind": "color",
                    "value": (a << 24) | (r << 16) | (g << 8) | b,
                    "line": line_of(src, m.start()), "pos": m.start()})
    for m in _RE_TEXT.finditer(src):
        out.append({"kind": "text", "value": decode_dart_string(m.group(2)),
                    "line": line_of(src, m.start()), "pos": m.start()})
    for m in _RE_ASSET.finditer(src):
        out.append({"kind": "asset", "value": m.group(2),
                    "line": line_of(src, m.start()), "pos": m.start()})
    for m in _RE_FONT_SIZE.finditer(src):
        v = float(m.group(1))
        out.append({"kind": "font_size",
                    "value": int(v) if v.is_integer() else v,
                    "line": line_of(src, m.start()), "pos": m.start()})
    for m in _RE_FONT_WEIGHT.finditer(src):
        tok = m.group(1)
        if tok == "bold":
            w = 700
        elif tok == "normal":
            w = 400
        else:
            w = int(tok[1:])
        out.append({"kind": "font_weight", "value": w,
                    "line": line_of(src, m.start()), "pos": m.start()})
    return out


# ---------- matching ----------

def find_first(items, pred, consumed):
    for it in sorted(items, key=lambda x: (x["file"], x["pos"])):
        if (it["file"], it["pos"]) in consumed:
            continue
        if pred(it):
            return it
    return None


def fmt_color(v):
    return f"0x{v:08X}" if isinstance(v, int) else str(v)


def match(design_layers, code_items):
    by = {"text": [], "asset": [], "color": [], "font_size": [], "font_weight": []}
    for it in code_items:
        by[it["kind"]].append(it)

    mismatches = []
    unmatched_design = []
    matched = 0
    consumed = set()

    for d in design_layers:
        if d["kind"] == "text":
            hit = find_first(by["text"], lambda c, d=d: c["value"] == d["content"], consumed)
            if not hit:
                unmatched_design.append({"layer_id": d["id"], "type": "text",
                                         "content": d["content"]})
                continue
            consumed.add((hit["file"], hit["pos"]))
            matched += 1
            # Side-fields: scan ±25 lines in the same file for a TextStyle.
            for kind, expected in (("font_size", d.get("font_size")),
                                   ("font_weight", d.get("font_weight")),
                                   ("color", d.get("color"))):
                if expected is None:
                    continue
                near = next(
                    (c for c in sorted(by[kind], key=lambda x: (x["file"], x["pos"]))
                     if c["file"] == hit["file"]
                     and abs(c["line"] - hit["line"]) <= 25
                     and (c["file"], c["pos"]) not in consumed),
                    None,
                )
                if near is None:
                    mismatches.append({
                        "layer_id": d["id"], "kind": kind,
                        "expected": fmt_color(expected) if kind == "color" else expected,
                        "actual": None,
                        "file": hit["file"], "line": hit["line"],
                    })
                else:
                    consumed.add((near["file"], near["pos"]))
                    if near["value"] != expected:
                        mismatches.append({
                            "layer_id": d["id"], "kind": kind,
                            "expected": fmt_color(expected) if kind == "color" else expected,
                            "actual": fmt_color(near["value"]) if kind == "color" else near["value"],
                            "file": near["file"], "line": near["line"],
                        })

        elif d["kind"] == "asset":
            base = d["asset"]
            hit = find_first(
                by["asset"],
                lambda c, base=base: c["value"].endswith(base) or c["value"].endswith("/" + base),
                consumed,
            )
            if not hit:
                unmatched_design.append({"layer_id": d["id"], "type": "asset",
                                         "asset": d["asset"]})
                continue
            consumed.add((hit["file"], hit["pos"]))
            matched += 1

        elif d["kind"] == "fill":
            hit = find_first(by["color"], lambda c, d=d: c["value"] == d["color"], consumed)
            if not hit:
                unmatched_design.append({"layer_id": d["id"], "type": "fill",
                                         "color": fmt_color(d["color"])})
                continue
            consumed.add((hit["file"], hit["pos"]))
            matched += 1

    unmatched_code = []
    for c in code_items:
        if (c["file"], c["pos"]) in consumed:
            continue
        if c["kind"] not in ("text", "asset", "color"):
            continue
        unmatched_code.append({
            "file": c["file"], "line": c["line"], "kind": c["kind"],
            "value": fmt_color(c["value"]) if c["kind"] == "color" else c["value"],
        })

    return {
        "expected": len(design_layers),
        "matched": matched,
        "mismatches": mismatches,
        "unmatched_design": unmatched_design,
        "unmatched_code": unmatched_code,
    }


# ---------- driver ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-json", required=True)
    ap.add_argument("--code-dir", required=True)
    ap.add_argument("--font-scale", type=float, default=1.0,
                    help="Divide raw design font sizes by this scale before matching code literals")
    args = ap.parse_args()
    if args.font_scale <= 0:
        print(json.dumps({"error": "--font-scale must be > 0"}), flush=True)
        sys.exit(2)

    raw_path = Path(args.raw_json)
    code_dir = Path(args.code_dir)
    if not raw_path.is_file():
        print(json.dumps({"error": f"raw.json not found: {raw_path}"}), flush=True)
        sys.exit(2)
    if not code_dir.is_dir():
        print(json.dumps({"error": f"code dir not found: {code_dir}"}), flush=True)
        sys.exit(2)

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"raw.json parse error: {e}"}), flush=True)
        sys.exit(2)

    design = extract_design_layers(raw, args.font_scale)

    files = sorted(
        str(p) for p in code_dir.rglob("*.dart")
        if "/test/" not in str(p).replace(os.sep, "/")
    )
    if not files:
        print(json.dumps({"error": f"no .dart files under {code_dir}"}), flush=True)
        sys.exit(2)

    code_items = []
    for fp in files:
        rel = os.path.relpath(fp)
        for it in parse_dart_file(fp):
            it["file"] = rel
            code_items.append(it)

    result = match(design, code_items)
    print(json.dumps(result, ensure_ascii=False), flush=True)

    ok = (result["matched"] == result["expected"]
          and not result["mismatches"]
          and not result["unmatched_design"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
