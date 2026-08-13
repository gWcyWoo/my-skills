#!/usr/bin/env python3
"""Platform-independent validation for reference/actual/diff visual evidence."""
from __future__ import annotations

import hashlib
import json
import stat
import struct
from pathlib import Path
from typing import Any


class VisualEvidenceError(ValueError):
    pass


KIND = "icp.visual-evidence.v1"
ACTUAL_SOURCES = ("browser_screenshot", "simulator_screenshot", "emulator_screenshot")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(path_value: Path | str, role: str) -> tuple[Path, int, int, str]:
    path = Path(path_value)
    if not path.is_absolute():
        raise VisualEvidenceError(f"{role} path must be absolute")
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise VisualEvidenceError(f"{role} must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise VisualEvidenceError(f"{role} must be PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if width <= 0 or height <= 0:
        raise VisualEvidenceError(f"{role} PNG dimensions are invalid")
    return path, width, height, hashlib.sha256(raw).hexdigest()


def _strict_json(path: Path | str) -> dict:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise VisualEvidenceError(f"duplicate provenance key: {key}")
            result[key] = value
        return result

    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise VisualEvidenceError("actual provenance must be an object")
    return value


def build_evidence(
    *,
    reference_path: Path | str,
    actual_path: Path | str,
    diff_path: Path | str,
    actual_provenance_path: Path | str,
    mismatch_ratio: float,
    max_mismatch_ratio: float,
) -> dict:
    reference, ref_width, ref_height, reference_digest = _png(reference_path, "reference")
    actual, actual_width, actual_height, actual_digest = _png(actual_path, "actual")
    diff, diff_width, diff_height, diff_digest = _png(diff_path, "diff")
    if (ref_width, ref_height) != (actual_width, actual_height) or (
        ref_width,
        ref_height,
    ) != (diff_width, diff_height):
        raise VisualEvidenceError("reference, actual, and diff dimensions must match")
    if reference_digest == actual_digest:
        raise VisualEvidenceError("actual screenshot must not be a copied design reference")
    if isinstance(mismatch_ratio, bool) or not isinstance(mismatch_ratio, (int, float)):
        raise VisualEvidenceError("mismatch_ratio must be numeric")
    if isinstance(max_mismatch_ratio, bool) or not isinstance(max_mismatch_ratio, (int, float)):
        raise VisualEvidenceError("max_mismatch_ratio must be numeric")
    if not 0 <= mismatch_ratio <= 1 or not 0 <= max_mismatch_ratio <= 1:
        raise VisualEvidenceError("visual mismatch ratios must be in [0,1]")
    provenance_path = Path(actual_provenance_path)
    provenance = _strict_json(provenance_path)
    actual_source = provenance.get("actual_source")
    if actual_source not in ACTUAL_SOURCES:
        raise VisualEvidenceError("actual_source is not a real runtime screenshot type")
    if provenance.get("actual_sha256") != actual_digest:
        raise VisualEvidenceError("actual provenance digest mismatch")
    evidence = {
        "kind": KIND,
        "schema_version": 1,
        "reference": {
            "path": str(reference),
            "sha256": reference_digest,
            "width": ref_width,
            "height": ref_height,
        },
        "actual": {
            "path": str(actual),
            "sha256": actual_digest,
            "actual_source": actual_source,
            "provenance_path": str(provenance_path),
            "provenance_sha256": _sha(provenance_path),
        },
        "diff": {
            "path": str(diff),
            "sha256": diff_digest,
            "mismatch_ratio": float(mismatch_ratio),
            "max_mismatch_ratio": float(max_mismatch_ratio),
        },
        "status": "pass" if mismatch_ratio <= max_mismatch_ratio else "fail",
    }
    verify_evidence(evidence)
    return evidence


def verify_evidence(evidence: dict) -> None:
    order = ("kind", "schema_version", "reference", "actual", "diff", "status")
    if not isinstance(evidence, dict) or tuple(evidence) != order:
        raise VisualEvidenceError("visual evidence shape is invalid")
    if evidence["kind"] != KIND or evidence["schema_version"] != 1:
        raise VisualEvidenceError("visual evidence identity is invalid")
    if tuple(evidence["reference"]) != ("path", "sha256", "width", "height"):
        raise VisualEvidenceError("reference evidence shape is invalid")
    if tuple(evidence["actual"]) != (
        "path",
        "sha256",
        "actual_source",
        "provenance_path",
        "provenance_sha256",
    ):
        raise VisualEvidenceError("actual evidence shape is invalid")
    if tuple(evidence["diff"]) != (
        "path",
        "sha256",
        "mismatch_ratio",
        "max_mismatch_ratio",
    ):
        raise VisualEvidenceError("diff evidence shape is invalid")
    for field in ("mismatch_ratio", "max_mismatch_ratio"):
        value = evidence["diff"][field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise VisualEvidenceError(f"diff {field} is invalid")
    reference, width, height, reference_digest = _png(evidence["reference"]["path"], "reference")
    actual, actual_width, actual_height, actual_digest = _png(evidence["actual"]["path"], "actual")
    diff, diff_width, diff_height, diff_digest = _png(evidence["diff"]["path"], "diff")
    if evidence["reference"] != {
        "path": str(reference),
        "sha256": reference_digest,
        "width": width,
        "height": height,
    }:
        raise VisualEvidenceError("reference evidence drift")
    provenance_path = Path(evidence["actual"]["provenance_path"])
    provenance = _strict_json(provenance_path)
    if evidence["actual"] != {
        "path": str(actual),
        "sha256": actual_digest,
        "actual_source": provenance.get("actual_source"),
        "provenance_path": str(provenance_path),
        "provenance_sha256": _sha(provenance_path),
    }:
        raise VisualEvidenceError("actual evidence drift")
    if evidence["diff"]["path"] != str(diff) or evidence["diff"]["sha256"] != diff_digest:
        raise VisualEvidenceError("diff evidence drift")
    if (width, height) != (actual_width, actual_height) or (width, height) != (diff_width, diff_height):
        raise VisualEvidenceError("visual evidence dimensions drift")
    if reference_digest == actual_digest or provenance.get("actual_sha256") != actual_digest:
        raise VisualEvidenceError("actual runtime provenance is invalid")
    if provenance.get("actual_source") not in ACTUAL_SOURCES:
        raise VisualEvidenceError("actual_source is invalid")
    expected_status = (
        "pass"
        if evidence["diff"]["mismatch_ratio"] <= evidence["diff"]["max_mismatch_ratio"]
        else "fail"
    )
    if evidence["status"] != expected_status:
        raise VisualEvidenceError("visual evidence status drift")


__all__ = ["ACTUAL_SOURCES", "VisualEvidenceError", "build_evidence", "verify_evidence"]
