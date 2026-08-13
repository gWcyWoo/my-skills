#!/usr/bin/env python3
"""Batch-level board index: every fetched design board's feature, name, and the
full set of its normalized visible text strings.

This is the deterministic anchor store for interaction grounding: when an
interaction rule says 点击"立即还款"打开确认弹窗, WHICH board shows that text is
a text lookup here — never a model guess over screenshots.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import dump_json, load_json


def norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specs-dir", required=True, help="lanhu/specs (all features/boards scanned)")
    parser.add_argument("--out", required=True, help="e.g. .iff/board_index.json")
    args = parser.parse_args()

    specs = Path(args.specs_dir).expanduser().resolve()
    boards = []
    for scene_path in sorted(specs.glob("*/*/scene.json")):
        board_dir = scene_path.parent
        scene = load_json(scene_path)
        scene_nodes = scene.get("nodes") or []
        texts = sorted({norm(n.get("text")) for n in scene_nodes if n.get("text")})
        nodes = [
            {
                "id": str(node.get("id")),
                "key": f"iff:{node.get('id')}",
                "text": norm(node.get("text")) or None,
            }
            for node in scene_nodes
            if node.get("id")
        ]
        groups_doc = {}
        try:
            groups_doc = load_json(board_dir / "groups.json")
        except FileNotFoundError:
            pass
        boards.append({
            "feature": board_dir.parent.name,
            "board": board_dir.name,
            "spec_dir": str(board_dir),
            "artboard": scene.get("artboard"),
            "texts": texts,
            "nodes": nodes,
            "groupKinds": sorted({g.get("kind") for g in (groups_doc.get("groups") or []) if g.get("kind")}),
        })
    if not boards:
        raise SystemExit(f"ERROR: no boards with scene.json under {specs}")
    dump_json({"specsDir": str(specs), "boards": boards}, args.out)
    print(f"ok board index: {len(boards)} boards, "
          f"{sum(len(b['texts']) for b in boards)} text anchors -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
