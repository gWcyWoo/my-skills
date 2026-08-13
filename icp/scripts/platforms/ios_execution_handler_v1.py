"""iOS-family controlled Xcode/simulator effects for Swift and Objective-C."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class IOSExecutionHandlerError(RuntimeError):
    pass


_SAFE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_BUNDLE_ID = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish(path: Path, data: bytes, *, replace_digest: str | None = None) -> str:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise IOSExecutionHandlerError("output target is unsafe")
    if path.exists():
        current = _sha(path)
        if path.read_bytes() == data:
            return current
        if current != replace_digest:
            raise IOSExecutionHandlerError("output compare-and-swap mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _sha(path)


def _publish_json(path: Path, value: dict[str, Any]) -> str:
    return _publish(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _paired(step: dict[str, Any], platform_id: str, *, source_check: bool) -> dict[str, str]:
    if tuple(step["inputs"]) != tuple(step["outputs"]):
        raise IOSExecutionHandlerError("publication artifact ids must match")
    result: dict[str, str] = {}
    for artifact_id, output_value in step["outputs"].items():
        output = Path(output_value)
        if source_check:
            allowed = {".swift"} if platform_id == "ios-swift" else {".h", ".m", ".mm"}
            if output.suffix not in allowed:
                raise IOSExecutionHandlerError("source output extension is invalid")
        result[artifact_id] = _publish(
            output, Path(step["inputs"][artifact_id]).read_bytes()
        )
    return result


def _tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise IOSExecutionHandlerError(f"{name} is unavailable")
    return value


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "CI": "1",
        "NSUnbufferedIO": "YES",
    }
    if extra_env:
        environment.update(extra_env)
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=environment,
    )
    report = {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }
    if result.returncode != 0:
        raise IOSExecutionHandlerError(f"xcode command failed with exit code {result.returncode}")
    return report


def _json_input(step: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    value = step["inputs"].get(artifact_id)
    if not value:
        raise IOSExecutionHandlerError(f"missing {artifact_id} input")
    try:
        document = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IOSExecutionHandlerError(f"{artifact_id} input is invalid") from exc
    if not isinstance(document, dict):
        raise IOSExecutionHandlerError(f"{artifact_id} input must be an object")
    return document


def _output(step: dict[str, Any], artifact_id: str) -> Path:
    value = step["outputs"].get(artifact_id)
    if not value:
        raise IOSExecutionHandlerError(f"missing {artifact_id} output")
    return Path(value)


def _runtime(step: dict[str, Any], *, capture: bool) -> dict[str, Any]:
    value = _json_input(step, "runtime")
    expected = (
        "project",
        "scheme",
        "simulator_udid",
        "app_product",
        "bundle_id",
    ) if capture else ("project", "scheme", "simulator_udid")
    if tuple(value) != expected:
        raise IOSExecutionHandlerError("iOS runtime config shape is invalid")
    for field in ("project", "scheme", "simulator_udid"):
        if not isinstance(value[field], str) or not _SAFE_NAME.fullmatch(value[field]):
            raise IOSExecutionHandlerError(f"iOS runtime {field} is invalid")
    if not value["project"].endswith(".xcodeproj"):
        raise IOSExecutionHandlerError("iOS project must end with .xcodeproj")
    if capture:
        if not isinstance(value["app_product"], str) or not _SAFE_NAME.fullmatch(value["app_product"]):
            raise IOSExecutionHandlerError("iOS app product is invalid")
        if not isinstance(value["bundle_id"], str) or not _BUNDLE_ID.fullmatch(value["bundle_id"]):
            raise IOSExecutionHandlerError("iOS bundle id is invalid")
    return value


def _xcode_args(runtime: dict[str, Any], action: str, run_root: Path) -> list[str]:
    arguments = [
        _tool("xcodebuild"),
        "-project",
        runtime["project"],
        "-scheme",
        runtime["scheme"],
        "-derivedDataPath",
        str(run_root / "DerivedData"),
    ]
    if action == "test":
        arguments.extend(
            ["-destination", f"platform=iOS Simulator,id={runtime['simulator_udid']}", "test"]
        )
    else:
        arguments.extend(["-sdk", "iphonesimulator", "-configuration", "Debug", "build"])
    return arguments


def _test(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, capture=False)
    report = _run(
        _xcode_args(runtime, "test", Path(context["run_root"])),
        cwd=Path(context["project_root"]),
    )
    return {"receipt": _publish_json(_output(step, "receipt"), report)}


def _gates(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, capture=False)
    run_root = Path(context["run_root"])
    project_root = Path(context["project_root"])
    build = _run(_xcode_args(runtime, "build", run_root), cwd=project_root)
    tests = _run(_xcode_args(runtime, "test", run_root), cwd=project_root)
    return {"receipt": _publish_json(_output(step, "receipt"), {"build": build, "tests": tests})}


def _trace(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, capture=False)
    trace = _output(step, "trace")
    _run(
        _xcode_args(runtime, "test", Path(context["run_root"])),
        cwd=Path(context["project_root"]),
        extra_env={"ICP_TRACE_OUTPUT": str(trace)},
    )
    if trace.is_symlink() or not trace.is_file():
        raise IOSExecutionHandlerError("XCTest did not publish the native trace")
    return {"trace": _sha(trace)}


def _capture(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, capture=True)
    run_root = Path(context["run_root"])
    project_root = Path(context["project_root"])
    _run(_xcode_args(runtime, "build", run_root), cwd=project_root)
    app = run_root / "DerivedData" / "Build" / "Products" / "Debug-iphonesimulator" / f"{runtime['app_product']}.app"
    if app.is_symlink() or not app.is_dir():
        raise IOSExecutionHandlerError("built simulator app is missing")
    xcrun = _tool("xcrun")
    udid = runtime["simulator_udid"]
    _run([xcrun, "simctl", "bootstatus", udid, "-b"], cwd=project_root)
    _run([xcrun, "simctl", "install", udid, str(app)], cwd=project_root)
    _run([xcrun, "simctl", "launch", udid, runtime["bundle_id"]], cwd=project_root)
    actual = _output(step, "actual")
    _run([xcrun, "simctl", "io", udid, "screenshot", str(actual)], cwd=project_root)
    if actual.is_symlink() or not actual.is_file() or not actual.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise IOSExecutionHandlerError("simulator screenshot is invalid")
    provenance = {
        "kind": "icp.runtime-capture-provenance.v1",
        "actual_source": "simulator_screenshot",
        "actual_sha256": _sha(actual),
        "simulator_udid_digest": hashlib.sha256(udid.encode()).hexdigest(),
        "bundle_id_digest": hashlib.sha256(runtime["bundle_id"].encode()).hexdigest(),
    }
    return {
        "actual": provenance["actual_sha256"],
        "provenance": _publish_json(_output(step, "provenance"), provenance),
    }


def _fan_in(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    plan = _json_input(step, "mutation_plan")
    if tuple(plan) != ("path", "expected_sha256", "content"):
        raise IOSExecutionHandlerError("fan-in mutation shape is invalid")
    relative = Path(plan["path"])
    if relative.is_absolute() or ".." in relative.parts or not isinstance(plan["content"], str):
        raise IOSExecutionHandlerError("fan-in mutation is invalid")
    target = Path(context["project_root"]) / relative
    current = _sha(target) if target.is_file() and not target.is_symlink() else None
    if plan["expected_sha256"] != current:
        raise IOSExecutionHandlerError("fan-in compare-and-swap mismatch")
    after = _publish(target, plan["content"].encode(), replace_digest=current)
    receipt = {"target": str(relative), "before_sha256": current, "after_sha256": after}
    return {"receipt": _publish_json(_output(step, "receipt"), receipt)}


def execute(
    platform_id: str,
    operation_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if platform_id not in {"ios-swift", "ios-objc"} or not operation_id.startswith(platform_id + "."):
        raise IOSExecutionHandlerError("iOS operation scope is invalid")
    port = operation_id[len(platform_id) + 1 : -3]
    if port in {"visible_codegen", "fixture_codegen"}:
        return _paired(step, platform_id, source_check=port == "visible_codegen")
    if port == "packaging":
        return _paired(step, platform_id, source_check=False)
    if port == "trace_harness":
        return _trace(step, context)
    if port == "test_runner":
        return _test(step, context)
    if port == "runtime_capture":
        return _capture(step, context)
    if port == "project_gates":
        return _gates(step, context)
    if port == "fan_in":
        return _fan_in(step, context)
    raise IOSExecutionHandlerError("iOS operation port is unsupported")


__all__ = ["IOSExecutionHandlerError", "execute"]
