#!/usr/bin/env python3
"""Build one deterministic, fingerprinted visual gate report for a board."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

from visual_diff import read_png_rgba


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_app_hashes(project_root: Path) -> dict[str, str]:
    lib_root = project_root / "lib"
    return {
        str(path.relative_to(lib_root)): sha256(path)
        for path in sorted(lib_root.rglob("*.dart"))
    }


def current_runtime_input_hashes(project_root: Path) -> dict[str, str]:
    paths = [
        path
        for name in ("pubspec.yaml", "pubspec.lock")
        if (path := project_root / name).is_file()
    ]
    assets_root = project_root / "assets"
    if assets_root.is_dir():
        paths.extend(path for path in assets_root.rglob("*") if path.is_file())
    return {
        str(path.relative_to(project_root)): sha256(path)
        for path in sorted(paths)
    }


def classify_hard_failures(
    spec_dir: Path,
    diff: dict,
    fidelity: dict,
    manifest: dict,
    asset_tol: float = 0.10,
    text_tol: float = 0.30,
) -> list[dict]:
    failures = [
        {
            "category": "shape",
            "node": issue.get("node"),
            "reason": issue.get("diagnostic") or "reference shape region differs",
        }
        for issue in diff.get("shapeIssues") or []
    ]
    failures.extend(
        {
            "category": "unexpected_region",
            "node": None,
            "reason": issue.get("issue") or "actual page contains visuals outside expected coverage",
        }
        for issue in diff.get("unexpectedIssues") or []
    )
    failures.extend(
        {
            "category": "asset",
            "node": issue.get("node"),
            "reason": (
                f"asset region mismatch {float(issue.get('pixelMismatch') or 0):.3f} "
                f"> {asset_tol}"
            ),
        }
        for issue in diff.get("assetIssues") or []
        if float(issue.get("pixelMismatch") or 0) > asset_tol
    )
    failures.extend(
        {
            "category": "text",
            "node": issue.get("node"),
            "reason": (
                f"text region mismatch {float(issue.get('pixelMismatch') or 0):.3f} "
                f"> {text_tol}"
            ),
        }
        for issue in diff.get("textIssues") or []
        if float(issue.get("pixelMismatch") or 0) > text_tol
    )
    failures.extend(
        {
            "category": "viewport",
            "node": None,
            "reason": issue.get("issue") or "runtime viewport differs from reference",
        }
        for issue in diff.get("viewportIssues") or []
    )
    if fidelity.get("assetShapeChecked") is not True:
        failures.append(
            {
                "category": "asset_shape",
                "node": None,
                "reason": "render fidelity must run with --diff-report",
            }
        )
    if fidelity.get("ok") is not True:
        failures.append(
            {
                "category": "render_fidelity",
                "node": None,
                "reason": fidelity.get("byCategory") or "runtime trace fidelity failed",
            }
        )
    required_manifest_fields = (
        "actual_source",
        "device_id",
        "capture_command",
        "timestamp",
        "project_root",
    )
    missing_manifest_fields = [
        field for field in required_manifest_fields if not manifest.get(field)
    ]
    if not isinstance(manifest.get("app_hashes"), dict):
        missing_manifest_fields.append("app_hashes")
    if not isinstance(manifest.get("runtime_input_hashes"), dict):
        missing_manifest_fields.append("runtime_input_hashes")
    if not isinstance(manifest.get("launch_command"), list) or not manifest.get("launch_command"):
        missing_manifest_fields.append("launch_command")
    if not isinstance(manifest.get("viewport"), dict) or not manifest.get("viewport"):
        missing_manifest_fields.append("viewport")
    if missing_manifest_fields:
        failures.append(
            {
                "category": "evidence",
                "node": None,
                "reason": "visual manifest missing fields: "
                + ", ".join(missing_manifest_fields),
            }
        )
    if manifest.get("actual_source") != "simulator_screenshot":
        failures.append(
            {
                "category": "evidence",
                "node": None,
                "reason": "actual.png must come from simulator_screenshot",
            }
        )
    if sha256(spec_dir / "reference.png") == sha256(spec_dir / "actual.png"):
        failures.append(
            {
                "category": "evidence",
                "node": None,
                "reason": "actual screenshot is byte-identical to reference",
            }
        )
    decoded: dict[str, tuple[int, int]] = {}
    for name in ("reference.png", "actual.png"):
        try:
            width, height, _ = read_png_rgba(spec_dir / name)
            decoded[name] = (width, height)
        except (OSError, ValueError, struct.error, zlib.error) as error:
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": f"{name} is not a valid PNG: {error}",
                }
            )
    viewport = manifest.get("viewport")
    if isinstance(viewport, dict) and "actual.png" in decoded:
        expected_size = (viewport.get("width"), viewport.get("height"))
        if decoded["actual.png"] != expected_size:
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": (
                        "actual.png dimensions differ from manifest viewport: "
                        f"actual={decoded['actual.png']} expected={expected_size}"
                    ),
                }
            )
    launch_command = manifest.get("launch_command")
    if isinstance(launch_command, list) and launch_command:
        device_id = str(manifest.get("device_id") or "")
        launch_device = None
        if "-d" in launch_command:
            device_index = launch_command.index("-d") + 1
            if device_index < len(launch_command):
                launch_device = str(launch_command[device_index])
        if launch_device != device_id:
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": "launch device does not match captured device_id",
                }
            )
        route = manifest.get("route")
        if route and f"--route={route}" not in launch_command:
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": "launch route does not match captured route",
                }
            )
    project_root_value = manifest.get("project_root")
    captured_app_hashes = manifest.get("app_hashes")
    if project_root_value and isinstance(captured_app_hashes, dict):
        project_root = Path(str(project_root_value)).expanduser().resolve()
        if current_app_hashes(project_root) != captured_app_hashes:
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": "app source changed after runtime screenshot capture",
                }
            )
        captured_runtime_inputs = manifest.get("runtime_input_hashes")
        if (
            isinstance(captured_runtime_inputs, dict)
            and current_runtime_input_hashes(project_root) != captured_runtime_inputs
        ):
            failures.append(
                {
                    "category": "evidence",
                    "node": None,
                    "reason": "runtime inputs changed after runtime screenshot capture",
                }
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--component-registry")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--asset-tol", type=float, default=0.10)
    parser.add_argument("--text-tol", type=float, default=0.30)
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir).expanduser().resolve()
    diff = json.loads((spec_dir / "diff_report.json").read_text(encoding="utf-8"))
    fidelity = json.loads(
        (spec_dir / "render_fidelity_report.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (spec_dir / "visual_manifest.json").read_text(encoding="utf-8")
    )
    hard_failures = classify_hard_failures(
        spec_dir, diff, fidelity, manifest, args.asset_tol, args.text_tol
    )
    component_inputs: dict[str, dict[str, str]] = {}
    shared_families = manifest.get("shared_components") or []
    if shared_families and not args.component_registry:
        hard_failures.append(
            {
                "category": "component_registry",
                "node": None,
                "reason": "shared components declared without --component-registry",
            }
        )
    elif shared_families:
        registry = json.loads(Path(args.component_registry).read_text(encoding="utf-8"))
        project_root = Path(args.project_root).expanduser().resolve()
        entries = list((registry.get("components") or {}).values())
        for family in shared_families:
            matches = [entry for entry in entries if entry.get("family_id") == family]
            if len(matches) != 1:
                hard_failures.append(
                    {
                        "category": "component_registry",
                        "node": None,
                        "reason": f"shared component family must resolve exactly once: {family}",
                    }
                )
                continue
            entry = matches[0]
            widget = project_root / str(entry.get("widget_path") or "")
            contract = Path(str(entry.get("contract_path") or ""))
            if not contract.is_absolute():
                contract = project_root / contract
            widget_hash = sha256(widget) if widget.is_file() else None
            contract_hash = sha256(contract) if contract.is_file() else None
            if (
                widget_hash != entry.get("widget_source_sha256")
                or contract_hash != entry.get("contract_sha256")
            ):
                hard_failures.append(
                    {
                        "category": "component_registry",
                        "node": None,
                        "reason": f"shared component files changed: {family}",
                    }
                )
                continue
            component_inputs[str(family)] = {
                "widget": widget_hash,
                "contract": contract_hash,
            }
    input_names = [
        "reference.png",
        "actual.png",
        "render_fidelity_report.json",
        "diff_report.json",
        "visual_manifest.json",
    ]
    inputs = {name: sha256(spec_dir / name) for name in input_names}
    report = {
        "version": 1,
        "ok": not hard_failures,
        "inputs": inputs,
        "hardFailures": hard_failures,
        "componentInputs": component_inputs,
        "diagnostics": {"ssim": diff.get("ssim")},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if hard_failures:
        print(f"FAIL visual gate report: {len(hard_failures)} hard failure(s)")
        return 1
    print(f"ok visual gate report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
