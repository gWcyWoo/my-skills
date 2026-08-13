#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from common import dump_json, load_json


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "component"


def _pascal(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Component"


def _widget_dir(project_root: Path) -> Path:
    for candidate in (
        Path("lib/src/common_widgets"),
        Path("lib/shared/widgets"),
        Path("lib/common_widgets"),
        Path("lib/widgets"),
    ):
        if (project_root / candidate).is_dir():
            return candidate
    return Path("lib/shared/widgets")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    batch_path = Path(args.batch).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    batch = load_json(batch_path)
    components = batch.get("components") or []
    if not isinstance(components, list):
        raise SystemExit("ERROR: batch components must be a list")

    widget_dir = _widget_dir(project_root)
    jobs = []
    blockers = []
    for component in components:
        if component.get("status") != "missing":
            continue
        signature = str(component.get("signature") or "").strip()
        rows = component.get("rows") or []
        best_source = str(component.get("best_asset_source") or "").strip()
        if not signature or not rows or not best_source:
            raise SystemExit("ERROR: missing component needs signature, rows, and best_asset_source")
        source_row = next((row for row in rows if str(row.get("spec_dir")) == best_source), rows[0])
        group_node = str(source_row.get("group_node") or "").strip()
        bbox = source_row.get("bbox")
        if not group_node or not isinstance(bbox, list) or len(bbox) != 4:
            raise SystemExit(f"ERROR: invalid source row for shared component {signature}")

        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10]
        stem = f"iff_shared_{_slug(str(component.get('kind') or 'component'))}_{digest}"
        job_dir = out_dir / stem
        job_dir.mkdir(parents=True, exist_ok=True)
        class_name = f"IffShared{_pascal(str(component.get('kind') or 'component'))}{digest.upper()}"
        widget_path = widget_dir / f"{stem}.dart"
        colors_path = widget_dir / f"{stem}_colors.dart"
        asset_target = Path("assets/iff_shared") / stem
        job = {
            "schemaVersion": 1,
            "signature": signature,
            "kind": component.get("kind"),
            "source_spec_dir": best_source,
            "group_node": group_node,
            "group_name": source_row.get("group_name"),
            "bbox": bbox,
            "canonical_nodes": source_row.get("canonical_nodes") or [],
            "rows": rows,
            "pooled_assets": component.get("pooled_assets") or {},
            "assets_incomplete": bool(component.get("assets_incomplete")),
            "assets_missing_positions": component.get("assets_missing_positions") or [],
            "paint_missing_positions": component.get("paint_missing_positions") or [],
            "batch_path": str(batch_path),
            "project_root": str(project_root),
            "job_dir": str(job_dir),
            "class_name": class_name,
            "widget_path": str(widget_path),
            "colors_path": str(colors_path),
            "asset_target": str(asset_target),
            "test_path": str(Path("test/shared/widgets") / f"{stem}_test.dart"),
            "result_path": str(job_dir / "shared_result.json"),
            "compliance_path": str(job_dir / "worker_compliance.json"),
        }
        job_path = job_dir / "component.json"
        dump_json(job, job_path)
        jobs.append({"signature": signature, "job": str(job_path), "job_dir": str(job_dir)})

    index = {
        "schemaVersion": 1,
        "batch": str(batch_path),
        "jobs": jobs,
        "blockers": blockers,
    }
    dump_json(index, out_dir / "jobs.json")
    print(
        json.dumps(
            {
                "count": len(jobs),
                "jobs": [job["job"] for job in jobs],
                "blockedCount": len(blockers),
                "blockers": blockers,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
