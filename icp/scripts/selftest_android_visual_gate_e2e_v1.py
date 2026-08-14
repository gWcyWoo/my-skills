#!/usr/bin/env python3
"""Real-emulator acceptance for source-bound Android visual verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPTS = Path(__file__).resolve().parent
PLATFORMS = SCRIPTS / "platforms"
VENDORED = SCRIPTS.parent / "vendor" / "iff_v1" / "scripts"
FIXTURE = SCRIPTS.parent / "tests" / "fixtures" / "android_visual_gate"
SERIAL = "emulator-5554"
APPLICATION_ID = "dev.icp.visualgate"
STATE_ID = "visual-gate-default"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PLATFORMS))
sys.path.insert(0, str(VENDORED))

import android_execution_handler_v1 as android_handler  # noqa: E402
import visual_diff  # noqa: E402
from shared_core import visual_evidence_v1, visual_verification_v1  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_logged(argv: list[str], *, cwd: Path = FIXTURE) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(argv), flush=True)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    print(f"exit code: {result.returncode}", flush=True)
    return result


def _checked(argv: list[str], *, cwd: Path = FIXTURE) -> str:
    result = _run_logged(argv, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(argv)}")
    return result.stdout


def _handler(
    operation: str,
    runtime_path: Path,
    outputs: dict[str, Path],
) -> dict[str, Any]:
    print(
        "$ android_execution_handler_v1.execute "
        + operation
        + " "
        + str(runtime_path)
        + " "
        + " ".join(f"{key}={path}" for key, path in outputs.items()),
        flush=True,
    )
    try:
        result = android_handler.execute(
            "android-java",
            f"android-java.{operation}.v1",
            {
                "inputs": {"runtime": str(runtime_path)},
                "outputs": {key: str(path) for key, path in outputs.items()},
            },
            {"project_root": str(FIXTURE)},
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        print("exit code: 2", flush=True)
        raise
    print(json.dumps(result, sort_keys=True), flush=True)
    print("exit code: 0", flush=True)
    return result


def _runtime(path: Path, activity: str) -> Path:
    _write_json(
        path,
        {
            "module": "app",
            "variant": "Debug",
            "device_serial": SERIAL,
            "application_id": APPLICATION_ID,
            "activity": f"dev.icp.visualgate.{activity}",
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
        },
    )
    return path


def _override(raw: str, label: str) -> str | None:
    match = re.search(rf"Override {label}: ([^\n]+)", raw)
    return match.group(1).strip() if match else None


def _restore_display(size: str | None, density: str | None) -> None:
    _run_logged(
        ["adb", "-s", SERIAL, "shell", "wm", "size", size if size else "reset"],
        cwd=FIXTURE,
    )
    _run_logged(
        ["adb", "-s", SERIAL, "shell", "wm", "density", density if density else "reset"],
        cwd=FIXTURE,
    )


def _measurement(
    root: Path,
    *,
    label: str,
    activity: str,
    reference: Path,
    contract: Path,
    density_output: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    runtime = _runtime(root / f"runtime-{label}.json", activity)
    captures: list[Path] = []
    provenances: list[Path] = []
    for index in (1, 2):
        actual = root / f"{label}-actual-{index}.png"
        provenance = root / f"{label}-provenance-{index}.json"
        _handler(
            "runtime_capture",
            runtime,
            {"actual": actual, "provenance": provenance},
        )
        captures.append(actual)
        provenances.append(provenance)
    for index, provenance in enumerate(provenances, start=1):
        value = json.loads(provenance.read_text(encoding="utf-8"))
        print(
            f"HANDLER_PROVENANCE run={index} capture_id={value['capture_id']} "
            f"state_reset_id={value['state_reset_id']}",
            flush=True,
        )

    trace = root / f"{label}-hierarchy.xml"
    _handler("trace_harness", runtime, {"trace": trace})

    anchor_report = root / f"{label}-anchor-measurements.json"
    _checked(
        [
            sys.executable,
            str(PLATFORMS / "android_trace_measure_v1.py"),
            "--hierarchy",
            str(trace),
            "--contract",
            str(contract),
            "--state-id",
            STATE_ID,
            "--density-output",
            str(density_output),
            "--out",
            str(anchor_report),
        ],
        cwd=SCRIPTS.parent.parent,
    )
    region_report = root / f"{label}-region-measurements.json"
    _checked(
        [
            sys.executable,
            str(PLATFORMS / "android_region_diff_v1.py"),
            "--reference",
            str(reference),
            "--actual",
            str(captures[0]),
            "--contract",
            str(contract),
            "--state-id",
            STATE_ID,
            "--out",
            str(region_report),
        ],
        cwd=SCRIPTS.parent.parent,
    )
    return (
        json.loads(anchor_report.read_text(encoding="utf-8")),
        json.loads(region_report.read_text(encoding="utf-8")),
        [
            _evidence(
                root,
                label=f"{label}-{index}",
                reference=reference,
                actual=actual,
                provenance=provenance,
                region_report=region_report,
            )
            for index, (actual, provenance) in enumerate(zip(captures, provenances), start=1)
        ],
    )


def _evidence(
    root: Path,
    *,
    label: str,
    reference: Path,
    actual: Path,
    provenance: Path,
    region_report: Path,
) -> Path:
    report = json.loads(region_report.read_text(encoding="utf-8"))
    mismatch = next(
        float(item["mismatch_ratio"])
        for item in report["measurements"]
        if item["name"] == "asset_icon"
    )
    manifest = visual_evidence_v1.build_evidence(
        reference_path=reference,
        actual_path=actual,
        diff_path=actual,
        actual_provenance_path=provenance,
        mismatch_ratio=mismatch,
        max_mismatch_ratio=1.0,
    )
    path = root / f"{label}-visual-evidence.json"
    _write_json(path, manifest)
    return path


def _verification(
    *,
    label: str,
    contract: Path,
    anchor_report: dict[str, Any],
    region_report: dict[str, Any],
    evidence_paths: list[Path],
    density_scale: float,
    width: int,
    height: int,
) -> dict[str, object]:
    anchor_path = Path(anchor_report["hierarchy_path"]).with_name(
        f"{label}-anchor-measurements.json"
    )
    region_path = Path(region_report["actual_path"]).with_name(
        f"{label}-region-measurements.json"
    )
    anchor = next(item for item in anchor_report["measurements"] if item["name"] == "action_top")
    region = next(item for item in region_report["measurements"] if item["name"] == "asset_icon")
    print(f"$ visual_verification_v1.build_verification state={label}", flush=True)
    return visual_verification_v1.build_verification(
        calibration={
            "reference_width": width,
            "reference_height": height,
            "runtime_width": width,
            "runtime_height": height,
            "density": density_scale,
            "font_scale": 1.0,
            "locale": "en-US",
            "theme": "light",
            "system_bars": "fullscreen-with-navigation",
            "animations_disabled": True,
        },
        states=[
            {
                "name": label,
                "contract": str(contract),
                "final_runs": [str(path) for path in evidence_paths],
                "anchors": [
                    {
                        "name": "action_top",
                        "expected": 100.0,
                        "actual": float(anchor["actual_dp"]),
                        "tolerance": 1.0,
                        "measurement_path": str(anchor_path),
                        "measurement_sha256": _sha(anchor_path),
                    }
                ],
                "regions": [
                    {
                        "name": "asset_icon",
                        "mismatch_ratio": float(region["mismatch_ratio"]),
                        "max_mismatch_ratio": 0.05,
                        "diff_report_path": str(region_path),
                        "diff_report_sha256": _sha(region_path),
                    }
                ],
            }
        ],
        repair_history=[],
    )


def _run_phase(
    root: Path,
    *,
    label: str,
    activity: str,
    reference: Path,
    contract: Path,
    density_output: Path,
    density_scale: float,
    width: int,
    height: int,
) -> bool:
    anchor_report, region_report, evidence = _measurement(
        root,
        label=label,
        activity=activity,
        reference=reference,
        contract=contract,
        density_output=density_output,
    )
    actual = next(item for item in anchor_report["measurements"] if item["name"] == "action_top")
    region = next(item for item in region_report["measurements"] if item["name"] == "asset_icon")
    print(
        f"MEASURED anchor=action_top actual_dp={actual['actual_dp']:.6f} "
        f"expected_dp=100 tolerance_dp=1",
        flush=True,
    )
    print(
        f"MEASURED region=asset_icon mismatch_ratio={region['mismatch_ratio']:.6f} "
        f"maximum=0.05",
        flush=True,
    )
    try:
        document = _verification(
            label=label,
            contract=contract,
            anchor_report=anchor_report,
            region_report=region_report,
            evidence_paths=evidence,
            density_scale=density_scale,
            width=width,
            height=height,
        )
    except visual_verification_v1.VisualVerificationError as exc:
        print(f"VisualVerificationError: {exc}", file=sys.stderr, flush=True)
        print("exit code: 2", flush=True)
        if label != "defect":
            raise
        expected = "anchors=['action_top'] regions=['asset_icon']"
        if expected not in str(exc):
            raise AssertionError(f"failure did not name both defects: {exc}")
        return False
    print(json.dumps({"status": document["status"], "state": label}), flush=True)
    print("exit code: 0", flush=True)
    if label == "defect":
        raise AssertionError("defect phase unexpectedly passed")
    visual_verification_v1.verify_verification(document)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("defect", "fixed", "both"), default="both")
    arguments = parser.parse_args()
    size_before = _checked(["adb", "-s", SERIAL, "shell", "wm", "size"])
    density_before = _checked(["adb", "-s", SERIAL, "shell", "wm", "density"])
    size_override = _override(size_before, "size")
    density_override = _override(density_before, "density")
    try:
        _checked(["adb", "-s", SERIAL, "shell", "wm", "size", "reset"])
        _checked(["adb", "-s", SERIAL, "shell", "wm", "density", "reset"])
        physical_density = _checked(["adb", "-s", SERIAL, "shell", "wm", "density"])
        density_match = re.search(r"Physical density: ([1-9]\d*)", physical_density)
        if density_match is None:
            raise RuntimeError("real physical density is unavailable")
        dpi = int(density_match.group(1))
        scale = dpi / 160.0

        with tempfile.TemporaryDirectory(prefix="icp-android-visual-gate-") as temporary:
            root = Path(temporary)
            density_output = root / "wm-density.txt"
            density_output.write_text(physical_density, encoding="utf-8")
            reference_runtime = _runtime(root / "runtime-reference.json", "FixedActivity")
            reference_raw = root / "reference-runtime.png"
            _handler(
                "runtime_capture",
                reference_runtime,
                {
                    "actual": reference_raw,
                    "provenance": root / "reference-provenance.json",
                },
            )
            width, height, pixels = visual_diff.read_png_rgba(reference_raw)
            reference = root / "frozen-design-reference.png"
            visual_diff.write_png_rgba(reference, width, height, pixels)
            if _sha(reference) == _sha(reference_raw):
                raise AssertionError("frozen reference encoding did not detach from runtime capture")

            contract = root / "implementation-contract.json"
            _write_json(
                contract,
                {
                    "design_contracts": [
                        {
                            "design_id": "android-visual-gate-fixture",
                            "states": [
                                {
                                    "state_id": STATE_ID,
                                    "anchors": [
                                        {
                                            "name": "action_top",
                                            "node_id": "action",
                                            "attribute": "top",
                                            "expected": 100.0,
                                            "tolerance": 1.0,
                                        }
                                    ],
                                    "regions": [
                                        {
                                            "name": "asset_icon",
                                            "bbox": [
                                                round(20 * scale),
                                                round(200 * scale),
                                                round(48 * scale),
                                                round(48 * scale),
                                            ],
                                            "max_mismatch_ratio": 0.05,
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            )

            defect_passed = None
            if arguments.mode in {"defect", "both"}:
                defect_passed = _run_phase(
                    root,
                    label="defect",
                    activity="DefectActivity",
                    reference=reference,
                    contract=contract,
                    density_output=density_output,
                    density_scale=scale,
                    width=width,
                    height=height,
                )
            if arguments.mode == "defect":
                return 0 if defect_passed else 2

            fixed_passed = _run_phase(
                root,
                label="fixed",
                activity="FixedActivity",
                reference=reference,
                contract=contract,
                density_output=density_output,
                density_scale=scale,
                width=width,
                height=height,
            )
            if arguments.mode == "both" and defect_passed is not False:
                raise AssertionError("combined acceptance did not observe the defect failure")
            if not fixed_passed:
                raise AssertionError("fixed acceptance did not pass")
            summary = (
                "defect rejected; fixed state accepted"
                if arguments.mode == "both"
                else "fixed state accepted"
            )
            print(f"ok real Android visual gate: {summary}", flush=True)
            return 0
    finally:
        _restore_display(size_override, density_override)
        for generated in (FIXTURE / ".gradle", FIXTURE / "build", FIXTURE / "app" / "build"):
            if generated.exists() and generated.is_dir() and not generated.is_symlink():
                shutil.rmtree(generated)


if __name__ == "__main__":
    raise SystemExit(main())
