"""Android-family controlled Gradle/ADB effects for Kotlin and Java."""

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


class AndroidExecutionHandlerError(RuntimeError):
    pass


_SAFE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_APPLICATION_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish(path: Path, data: bytes, *, replace_digest: str | None = None) -> str:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise AndroidExecutionHandlerError("output target is unsafe")
    if path.exists():
        current = _sha(path)
        if path.read_bytes() == data:
            return current
        if current != replace_digest:
            raise AndroidExecutionHandlerError("output compare-and-swap mismatch")
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
        raise AndroidExecutionHandlerError("publication artifact ids must match")
    result: dict[str, str] = {}
    for artifact_id, output_value in step["outputs"].items():
        output = Path(output_value)
        if source_check:
            expected = ".kt" if platform_id == "android-kotlin" else ".java"
            if output.suffix != expected:
                raise AndroidExecutionHandlerError("source output extension is invalid")
        result[artifact_id] = _publish(output, Path(step["inputs"][artifact_id]).read_bytes())
    return result


def _json_input(step: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    path_value = step["inputs"].get(artifact_id)
    if not path_value:
        raise AndroidExecutionHandlerError(f"missing {artifact_id} input")
    try:
        value = json.loads(Path(path_value).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AndroidExecutionHandlerError(f"{artifact_id} input is invalid") from exc
    if not isinstance(value, dict):
        raise AndroidExecutionHandlerError(f"{artifact_id} input must be an object")
    return value


def _output(step: dict[str, Any], artifact_id: str) -> Path:
    value = step["outputs"].get(artifact_id)
    if not value:
        raise AndroidExecutionHandlerError(f"missing {artifact_id} output")
    return Path(value)


def _runtime(step: dict[str, Any], *, device: bool) -> dict[str, Any]:
    value = _json_input(step, "runtime")
    expected = (
        "module",
        "variant",
        "device_serial",
        "application_id",
        "activity",
        "apk_path",
    ) if device else ("module", "variant")
    if tuple(value) != expected:
        raise AndroidExecutionHandlerError("Android runtime config shape is invalid")
    if not isinstance(value["module"], str) or not _SAFE_NAME.fullmatch(value["module"]):
        raise AndroidExecutionHandlerError("Android module is invalid")
    if not isinstance(value["variant"], str) or not _SAFE_NAME.fullmatch(value["variant"]):
        raise AndroidExecutionHandlerError("Android variant is invalid")
    if device:
        if not isinstance(value["device_serial"], str) or not _SAFE_NAME.fullmatch(value["device_serial"]):
            raise AndroidExecutionHandlerError("Android device serial is invalid")
        if not isinstance(value["application_id"], str) or not _APPLICATION_ID.fullmatch(value["application_id"]):
            raise AndroidExecutionHandlerError("Android application id is invalid")
        if not isinstance(value["activity"], str) or not _APPLICATION_ID.fullmatch(value["activity"]):
            raise AndroidExecutionHandlerError("Android activity is invalid")
        apk = Path(value["apk_path"])
        if apk.is_absolute() or ".." in apk.parts or apk.suffix != ".apk":
            raise AndroidExecutionHandlerError("Android APK path is invalid")
    return value


def _gradlew(project_root: Path) -> str:
    path = project_root / "gradlew"
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise AndroidExecutionHandlerError("Gradle wrapper is unavailable")
    return str(path)


def _adb() -> str:
    value = shutil.which("adb")
    if not value:
        raise AndroidExecutionHandlerError("adb is unavailable")
    return value


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    serial: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "CI": "1",
        "GRADLE_OPTS": "-Dorg.gradle.daemon=false",
    }
    if serial:
        environment["ANDROID_SERIAL"] = serial
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
        raise AndroidExecutionHandlerError(
            f"Android command failed with exit code {result.returncode}"
        )
    return report, result.stdout


def _task(runtime: dict[str, Any], suffix: str) -> str:
    return f":{runtime['module']}:{suffix}{runtime['variant']}"


def _test(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, device=False)
    project_root = Path(context["project_root"])
    report, _ = _run(
        [_gradlew(project_root), _task(runtime, "test"), "--no-daemon", "--stacktrace"],
        cwd=project_root,
    )
    return {"receipt": _publish_json(_output(step, "receipt"), report)}


def _gates(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, device=False)
    project_root = Path(context["project_root"])
    build, _ = _run(
        [_gradlew(project_root), _task(runtime, "assemble"), "--no-daemon", "--stacktrace"],
        cwd=project_root,
    )
    tests, _ = _run(
        [_gradlew(project_root), _task(runtime, "test"), "--no-daemon", "--stacktrace"],
        cwd=project_root,
    )
    return {"receipt": _publish_json(_output(step, "receipt"), {"build": build, "tests": tests})}


def _prepare_device(runtime: dict[str, Any], context: dict[str, Any]) -> tuple[str, Path]:
    project_root = Path(context["project_root"])
    serial = runtime["device_serial"]
    _run(
        [_gradlew(project_root), _task(runtime, "assemble"), "--no-daemon", "--stacktrace"],
        cwd=project_root,
        serial=serial,
    )
    apk = project_root / runtime["apk_path"]
    if apk.is_symlink() or not apk.is_file():
        raise AndroidExecutionHandlerError("built APK is missing")
    adb = _adb()
    _run([adb, "-s", serial, "install", "-r", str(apk)], cwd=project_root, serial=serial)
    _run(
        [adb, "-s", serial, "shell", "am", "force-stop", runtime["application_id"]],
        cwd=project_root,
        serial=serial,
    )
    _run(
        [adb, "-s", serial, "shell", "am", "start", "-n", f"{runtime['application_id']}/{runtime['activity']}"],
        cwd=project_root,
        serial=serial,
    )
    return adb, apk


def _trace(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, device=True)
    project_root = Path(context["project_root"])
    adb, _ = _prepare_device(runtime, context)
    serial = runtime["device_serial"]
    _run(
        [adb, "-s", serial, "shell", "uiautomator", "dump", "/sdcard/icp-window.xml"],
        cwd=project_root,
        serial=serial,
    )
    _report, data = _run(
        [adb, "-s", serial, "exec-out", "cat", "/sdcard/icp-window.xml"],
        cwd=project_root,
        serial=serial,
    )
    if b"<hierarchy" not in data:
        raise AndroidExecutionHandlerError("Android UIAutomator trace is invalid")
    return {"trace": _publish(_output(step, "trace"), data)}


def _capture(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime(step, device=True)
    project_root = Path(context["project_root"])
    adb, apk = _prepare_device(runtime, context)
    serial = runtime["device_serial"]
    _report, data = _run(
        [adb, "-s", serial, "exec-out", "screencap", "-p"],
        cwd=project_root,
        serial=serial,
    )
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AndroidExecutionHandlerError("Android screenshot is invalid")
    actual = _output(step, "actual")
    actual_digest = _publish(actual, data)
    provenance = {
        "kind": "icp.runtime-capture-provenance.v1",
        "actual_source": "emulator_screenshot",
        "actual_sha256": actual_digest,
        "device_serial_digest": hashlib.sha256(serial.encode()).hexdigest(),
        "application_id_digest": hashlib.sha256(runtime["application_id"].encode()).hexdigest(),
        "apk_sha256": _sha(apk),
    }
    return {
        "actual": actual_digest,
        "provenance": _publish_json(_output(step, "provenance"), provenance),
    }


def _fan_in(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    plan = _json_input(step, "mutation_plan")
    if tuple(plan) != ("path", "expected_sha256", "content"):
        raise AndroidExecutionHandlerError("fan-in mutation shape is invalid")
    relative = Path(plan["path"])
    if relative.is_absolute() or ".." in relative.parts or not isinstance(plan["content"], str):
        raise AndroidExecutionHandlerError("fan-in mutation is invalid")
    target = Path(context["project_root"]) / relative
    current = _sha(target) if target.is_file() and not target.is_symlink() else None
    if plan["expected_sha256"] != current:
        raise AndroidExecutionHandlerError("fan-in compare-and-swap mismatch")
    after = _publish(target, plan["content"].encode(), replace_digest=current)
    receipt = {"target": str(relative), "before_sha256": current, "after_sha256": after}
    return {"receipt": _publish_json(_output(step, "receipt"), receipt)}


def execute(
    platform_id: str,
    operation_id: str,
    step: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if platform_id not in {"android-kotlin", "android-java"} or not operation_id.startswith(platform_id + "."):
        raise AndroidExecutionHandlerError("Android operation scope is invalid")
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
    raise AndroidExecutionHandlerError("Android operation port is unsupported")


__all__ = ["AndroidExecutionHandlerError", "execute"]
