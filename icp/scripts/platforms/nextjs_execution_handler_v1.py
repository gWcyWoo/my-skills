"""Next.js-owned controlled effects for the nine-port ICP package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class NextExecutionHandlerError(RuntimeError):
    pass


_CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish(path: Path, data: bytes) -> str:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise NextExecutionHandlerError("output target is unsafe")
    if path.exists():
        if path.read_bytes() == data:
            return _sha(path)
        raise NextExecutionHandlerError("output target already exists with different bytes")
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
    data = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return _publish(path, data)


def _paired_publication(step: dict[str, Any]) -> dict[str, str]:
    inputs = step["inputs"]
    outputs = step["outputs"]
    if tuple(inputs) != tuple(outputs):
        raise NextExecutionHandlerError("publication inputs and outputs must have identical ids")
    return {
        artifact_id: _publish(Path(outputs[artifact_id]), Path(inputs[artifact_id]).read_bytes())
        for artifact_id in outputs
    }


def _command(argv: list[str], *, cwd: Path, timeout: int = 300) -> dict[str, Any]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CI": "1",
            "NO_COLOR": "1",
        },
    )
    report = {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }
    if result.returncode != 0:
        raise NextExecutionHandlerError(
            f"controlled command failed with exit code {result.returncode}"
        )
    return report


def _npm() -> str:
    value = shutil.which("npm")
    if not value:
        raise NextExecutionHandlerError("npm is unavailable")
    return value


def _json_input(step: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    path_value = step["inputs"].get(artifact_id)
    if not path_value:
        raise NextExecutionHandlerError(f"missing {artifact_id} input")
    try:
        value = json.loads(Path(path_value).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NextExecutionHandlerError(f"{artifact_id} input is invalid") from exc
    if not isinstance(value, dict):
        raise NextExecutionHandlerError(f"{artifact_id} input must be an object")
    return value


def _json_output(step: dict[str, Any], artifact_id: str) -> Path:
    value = step["outputs"].get(artifact_id)
    if not value:
        raise NextExecutionHandlerError(f"missing {artifact_id} output")
    return Path(value)


def _runtime_config(step: dict[str, Any]) -> dict[str, Any]:
    value = _json_input(step, "runtime")
    if tuple(value) != ("route", "viewport_width", "viewport_height"):
        raise NextExecutionHandlerError("runtime config shape is invalid")
    route = value["route"]
    width = value["viewport_width"]
    height = value["viewport_height"]
    if not isinstance(route, str) or not route.startswith("/") or "\n" in route:
        raise NextExecutionHandlerError("runtime route is invalid")
    if type(width) is not int or type(height) is not int or not (240 <= width <= 4096 and 240 <= height <= 4096):
        raise NextExecutionHandlerError("runtime viewport is invalid")
    return value


def _chrome() -> Path:
    for candidate in _CHROME_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise NextExecutionHandlerError("Chrome is unavailable")


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise NextExecutionHandlerError("Next.js server exited before readiness")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise NextExecutionHandlerError("Next.js server readiness timed out")


def _with_server(project_root: Path, route: str, callback):
    port = _port()
    process = subprocess.Popen(
        [_npm(), "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "CI": "1"},
    )
    url = f"http://127.0.0.1:{port}{route}"
    try:
        _wait(url, process)
        return callback(url)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _trace(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime_config(step)
    output = _json_output(step, "trace")

    def capture(url: str) -> str:
        result = subprocess.run(
            [
                str(_chrome()),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--dump-dom",
                f"--window-size={runtime['viewport_width']},{runtime['viewport_height']}",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            raise NextExecutionHandlerError("Chrome DOM trace failed")
        return _publish_json(
            output,
            {
                "kind": "icp.nextjs-dom-trace.v1",
                "actual_source": "browser_dom",
                "url": url,
                "viewport": {
                    "width": runtime["viewport_width"],
                    "height": runtime["viewport_height"],
                },
                "dom_sha256": hashlib.sha256(result.stdout).hexdigest(),
            },
        )

    return {"trace": _with_server(Path(context["project_root"]), runtime["route"], capture)}


def _capture(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    runtime = _runtime_config(step)
    actual = Path(step["outputs"].get("actual", ""))
    provenance = _json_output(step, "provenance")
    if not actual.is_absolute():
        raise NextExecutionHandlerError("missing actual screenshot output")

    def capture(url: str) -> dict[str, str]:
        result = subprocess.run(
            [
                str(_chrome()),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--screenshot={actual}",
                f"--window-size={runtime['viewport_width']},{runtime['viewport_height']}",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
        if result.returncode != 0 or not actual.is_file():
            raise NextExecutionHandlerError("Chrome screenshot failed")
        actual_digest = _sha(actual)
        provenance_digest = _publish_json(
            provenance,
            {
                "kind": "icp.runtime-capture-provenance.v1",
                "actual_source": "browser_screenshot",
                "actual_sha256": actual_digest,
                "url": url,
                "viewport": {
                    "width": runtime["viewport_width"],
                    "height": runtime["viewport_height"],
                },
                "browser_sha256": _sha(_chrome()),
            },
        )
        return {"actual": actual_digest, "provenance": provenance_digest}

    return _with_server(Path(context["project_root"]), runtime["route"], capture)


def _test(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    report = _command([_npm(), "run", "test", "--", "--run"], cwd=Path(context["project_root"]))
    return {"receipt": _publish_json(_json_output(step, "receipt"), report)}


def _gates(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    project_root = Path(context["project_root"])
    tests = _command([_npm(), "run", "test", "--", "--run"], cwd=project_root)
    build = _command([_npm(), "run", "build"], cwd=project_root)
    return {"receipt": _publish_json(_json_output(step, "receipt"), {"tests": tests, "build": build})}


def _fan_in(step: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    plan = _json_input(step, "mutation_plan")
    if tuple(plan) != ("path", "expected_sha256", "content"):
        raise NextExecutionHandlerError("mutation plan shape is invalid")
    relative = Path(plan["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise NextExecutionHandlerError("mutation target is invalid")
    target = Path(context["project_root"]) / relative
    expected = plan["expected_sha256"]
    current = _sha(target) if target.is_file() and not target.is_symlink() else None
    if expected != current:
        raise NextExecutionHandlerError("fan-in compare-and-swap mismatch")
    if not isinstance(plan["content"], str):
        raise NextExecutionHandlerError("fan-in content is invalid")
    digest = _publish(target, plan["content"].encode("utf-8")) if current is None else None
    if current is not None:
        data = plan["content"].encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        digest = _sha(target)
    receipt = {"target": str(relative), "before_sha256": current, "after_sha256": digest}
    return {"receipt": _publish_json(_json_output(step, "receipt"), receipt)}


def execute(operation_id: str, step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    port = operation_id.split(".")[1]
    if port in {"visible_codegen", "fixture_codegen", "packaging"}:
        return _paired_publication(step)
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
    raise NextExecutionHandlerError("operation port is unsupported")


__all__ = ["NextExecutionHandlerError", "execute"]
