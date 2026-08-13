"""Fixed-action Vue executor with one-time durable nonce receipts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from platforms import vue_execution_authorization_v1 as _authorization


KIND_REPORT = "icp.vue-execution-report.v1"
SCHEMA_VERSION = 1
_RECEIPT_DIR = ".icp-vue-execution-receipts-v1"


class VueExecutionExecutorError(RuntimeError):
    """Raised when an authorization cannot execute exactly once."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VueExecutionExecutorError("receipt data is invalid") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _receipt_root(run_root: Path) -> Path:
    path = run_root / _RECEIPT_DIR
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise VueExecutionExecutorError("receipt directory is unavailable") from exc
    if resolved != path or not stat.S_ISDIR(metadata.st_mode):
        raise VueExecutionExecutorError("receipt directory is invalid")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise VueExecutionExecutorError("receipt directory permissions are too broad")
    return path


def _create_receipt(path: Path, value: dict[str, Any]) -> str:
    data = _canonical_bytes(value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise VueExecutionExecutorError("authorization nonce is already consumed") from exc
    except OSError as exc:
        raise VueExecutionExecutorError("receipt creation failed") from exc
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    return hashlib.sha256(data).hexdigest()


def _strict_json_file(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        data = path.read_bytes()
    except OSError as exc:
        raise VueExecutionExecutorError("bound input is unavailable") from exc
    if resolved != path or not stat.S_ISREG(metadata.st_mode) or len(data) > 16 * 1024 * 1024:
        raise VueExecutionExecutorError("bound input is invalid")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VueExecutionExecutorError("bound input is invalid") from exc
    if not isinstance(value, dict):
        raise VueExecutionExecutorError("bound input is invalid")
    return value


def _publish_pair(outputs: dict[str, str], feature_id: str) -> dict[str, str]:
    sfc_path = Path(outputs["sfc"])
    css_path = Path(outputs["css"])
    if sfc_path.exists() or sfc_path.is_symlink() or css_path.exists() or css_path.is_symlink():
        raise VueExecutionExecutorError("bound output already exists")
    if sfc_path.parent.resolve(strict=True) != sfc_path.parent:
        raise VueExecutionExecutorError("bound output parent is invalid")
    if css_path.parent.resolve(strict=True) != css_path.parent:
        raise VueExecutionExecutorError("bound output parent is invalid")
    sfc = (
        f'<template><main data-icp-feature="{feature_id}"></main></template>\n'
        "<script setup>\n"
        f"const featureId = {json.dumps(feature_id)}\n"
        "</script>\n"
        f'<style src="./{css_path.name}"></style>\n'
    ).encode("utf-8")
    css = f'[data-icp-feature="{feature_id}"] {{ display: block; }}\n'.encode("utf-8")
    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for destination, data in ((sfc_path, sfc), (css_path, css)):
            fd, temp_name = tempfile.mkstemp(prefix=".icp-vue-stage.", dir=destination.parent)
            temp_path = Path(temp_name)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temp_path, destination))
        for temp_path, destination in staged:
            os.link(temp_path, destination)
            published.append(destination)
        directory_fd = os.open(sfc_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        for destination in reversed(published):
            try:
                destination.unlink()
            except OSError:
                pass
        raise VueExecutionExecutorError("bound output publication failed") from exc
    finally:
        for temp_path, _ in staged:
            try:
                temp_path.unlink()
            except OSError:
                pass
    return {"sfc_sha256": hashlib.sha256(sfc).hexdigest(), "css_sha256": hashlib.sha256(css).hexdigest()}


def _publish_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise VueExecutionExecutorError(f"output already exists: {path}") from exc
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(fd, 0o600)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return hashlib.sha256(data).hexdigest()


def _publish_json(path_value: str, value: dict[str, Any]) -> str:
    return _publish_bytes(Path(path_value), _canonical_bytes(value))


def _render_fixture(step: dict[str, Any], feature_id: str) -> dict[str, str]:
    contract = _strict_json_file(step["inputs"]["visual_contract"])
    contract_digest = _digest(contract)
    source = (
        "export const icpFixture = Object.freeze({\n"
        f"  featureId: {json.dumps(feature_id)},\n"
        f"  visualContractDigest: {json.dumps(contract_digest)},\n"
        "});\n"
    ).encode("utf-8")
    return {"fixture_sha256": _publish_bytes(Path(step["outputs"]["fixture"]), source)}


def _run_command(argv: list[str], *, cwd: Path, timeout: int = 180) -> dict[str, Any]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "CI"}
    }
    env["CI"] = "1"
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            shell=False,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VueExecutionExecutorError(f"fixed command timed out: {Path(argv[0]).name}") from exc
    return {
        "argv_id": " ".join(Path(part).name if index == 0 else part for index, part in enumerate(argv[:3])),
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
    }


def _run_test_action(step: dict[str, Any], project_root: Path) -> dict[str, str]:
    phase = step["inputs"]["phase"]
    script = {"red": "test:unit", "green": "test:unit", "verify": "test:e2e"}.get(phase)
    if script is None:
        raise VueExecutionExecutorError("unsupported Vue test phase")
    npm = shutil.which("npm")
    if npm is None:
        raise VueExecutionExecutorError("npm is unavailable")
    result = _run_command([npm, "run", script], cwd=project_root)
    evidence = {
        "kind": "icp.vue-test-evidence.v1",
        "schema_version": 1,
        "phase": phase,
        "script": script,
        "result": result,
    }
    digest = _publish_json(step["outputs"]["evidence"], evidence)
    if result["returncode"] != 0:
        raise VueExecutionExecutorError(f"Vue test phase failed: {phase}")
    return {"evidence_sha256": digest}


def _prepare_packaging(step: dict[str, Any]) -> dict[str, str]:
    manifest = _strict_json_file(step["inputs"]["assets_manifest"])
    receipt = {
        "kind": "icp.vue-packaging-receipt.v1",
        "schema_version": 1,
        "assets_manifest_digest": _digest(manifest),
        "status": "prepared",
    }
    return {"receipt_sha256": _publish_json(step["outputs"]["receipt"], receipt)}


def _run_project_gates(step: dict[str, Any], project_root: Path) -> dict[str, str]:
    npm = shutil.which("npm")
    if npm is None:
        raise VueExecutionExecutorError("npm is unavailable")
    results = [
        {"gate": script, "result": _run_command([npm, "run", script], cwd=project_root)}
        for script in ("build", "test:unit", "test:e2e")
    ]
    report = {
        "kind": "icp.vue-project-gates-report.v1",
        "schema_version": 1,
        "status": "pass" if all(item["result"]["returncode"] == 0 for item in results) else "fail",
        "gates": results,
    }
    digest = _publish_json(step["outputs"]["report"], report)
    if report["status"] != "pass":
        raise VueExecutionExecutorError("Vue project gates failed")
    return {"report_sha256": digest}


def _safe_project_target(project_root: Path, relative: str) -> Path:
    candidate = project_root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise VueExecutionExecutorError("fan-in mutation path escapes project root")
    resolved_parent = candidate.parent.resolve(strict=True)
    if project_root.resolve(strict=True) not in (resolved_parent, *resolved_parent.parents):
        raise VueExecutionExecutorError("fan-in mutation path escapes project root")
    if candidate.exists() and candidate.is_symlink():
        raise VueExecutionExecutorError("fan-in mutation target is a symlink")
    return candidate


def _apply_fan_in(step: dict[str, Any], project_root: Path) -> dict[str, str]:
    manifest = _strict_json_file(step["inputs"]["mutation_manifest"])
    if set(manifest) != {"kind", "schema_version", "mutations"}:
        raise VueExecutionExecutorError("fan-in mutation manifest shape is invalid")
    if manifest["kind"] != "icp.vue-mutation-manifest.v1" or manifest["schema_version"] != 1:
        raise VueExecutionExecutorError("fan-in mutation manifest identity is invalid")
    mutations = manifest["mutations"]
    if not isinstance(mutations, list) or not mutations or len(mutations) > 16:
        raise VueExecutionExecutorError("fan-in mutation count is invalid")
    prepared: list[tuple[Path, bytes, bytes | None, int]] = []
    seen: set[Path] = set()
    for mutation in mutations:
        if not isinstance(mutation, dict) or tuple(mutation) != ("path", "expected_sha256", "content"):
            raise VueExecutionExecutorError("fan-in mutation shape is invalid")
        target = _safe_project_target(project_root, mutation["path"])
        if target in seen:
            raise VueExecutionExecutorError("fan-in mutation target is duplicated")
        seen.add(target)
        before = target.read_bytes() if target.exists() else None
        expected = mutation["expected_sha256"]
        observed = hashlib.sha256(before).hexdigest() if before is not None else None
        if expected != observed:
            raise VueExecutionExecutorError("fan-in mutation compare-and-swap failed")
        if not isinstance(mutation["content"], str):
            raise VueExecutionExecutorError("fan-in mutation content must be text")
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        prepared.append((target, mutation["content"].encode("utf-8"), before, mode))
    changed: list[tuple[Path, bytes | None, int]] = []
    try:
        for target, content, before, mode in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, target)
            changed.append((target, before, mode))
    except Exception:
        for target, before, mode in reversed(changed):
            if before is None:
                target.unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.rollback.", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(before)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, mode)
                os.replace(temporary, target)
        raise
    receipt = {
        "kind": "icp.vue-fan-in-receipt.v1",
        "schema_version": 1,
        "mutation_manifest_digest": _digest(manifest),
        "outputs": [
            {"path": str(target.relative_to(project_root)), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
            for target, _, _, _ in prepared
        ],
    }
    return {"receipt_sha256": _publish_json(step["outputs"]["receipt"], receipt)}


def _choose_port() -> int:
    for port in range(4173, 4210):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise VueExecutionExecutorError("no local Vite test port is available")


def _browser_probe(
    *,
    project_root: Path,
    run_root: Path,
    route: str,
    viewport: dict[str, Any],
    mode: str,
    output: Path | None,
) -> dict[str, Any]:
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        raise VueExecutionExecutorError("Node.js/npm is unavailable")
    width = viewport.get("width")
    height = viewport.get("height")
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise VueExecutionExecutorError("viewport width is invalid")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise VueExecutionExecutorError("viewport height is invalid")
    port = _choose_port()
    url = f"http://127.0.0.1:{port}{route}"
    script = run_root / f".icp-browser-probe-{os.getpid()}-{time.time_ns()}.cjs"
    script_source = """
const { chromium } = require('playwright');
(async () => {
  const [mode, url, output, width, height] = process.argv.slice(2);
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const page = await browser.newPage({viewport: {width: Number(width), height: Number(height)}});
  await page.goto(url, {waitUntil: 'networkidle'});
  let payload;
  if (mode === 'screenshot') {
    await page.screenshot({path: output, fullPage: false});
    payload = {browser_name: 'chrome', browser_version: browser.version(), url};
  } else {
    const elements = await page.locator('body *').evaluateAll(nodes => nodes.slice(0, 512).map(node => {
      const r = node.getBoundingClientRect();
      return {tag: node.tagName.toLowerCase(), text: (node.textContent || '').trim().slice(0, 256), x: r.x, y: r.y, width: r.width, height: r.height};
    }));
    payload = {browser_name: 'chrome', browser_version: browser.version(), url, elements};
  }
  await browser.close();
  process.stdout.write(JSON.stringify(payload));
})().catch(error => { process.stderr.write(String(error)); process.exit(1); });
""".lstrip()
    _publish_bytes(script, script_source.encode("utf-8"))
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}
    }
    env["NODE_PATH"] = str(project_root / "node_modules")
    server = subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=project_root,
        env=env,
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            if server.poll() is not None:
                raise VueExecutionExecutorError("Vite dev server exited before browser capture")
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status < 500:
                        break
            except Exception:
                pass
            if time.monotonic() >= deadline:
                raise VueExecutionExecutorError("Vite dev server did not become ready")
            time.sleep(0.2)
        completed = subprocess.run(
            [node, str(script), mode, url, str(output or ""), str(width), str(height)],
            cwd=project_root,
            env=env,
            shell=False,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise VueExecutionExecutorError("real Chrome capture failed")
        payload = json.loads(completed.stdout.decode("utf-8"))
        if not isinstance(payload, dict):
            raise VueExecutionExecutorError("browser probe result is invalid")
        return payload
    finally:
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            server.wait(timeout=5)
        script.unlink(missing_ok=True)


def _capture_dom_trace(step: dict[str, Any], project_root: Path, run_root: Path) -> dict[str, str]:
    payload = _browser_probe(
        project_root=project_root,
        run_root=run_root,
        route=step["inputs"]["route"],
        viewport={"width": 390, "height": 844},
        mode="trace",
        output=None,
    )
    trace = {"kind": "icp.vue-dom-trace.v1", "schema_version": 1, **payload}
    return {"trace_sha256": _publish_json(step["outputs"]["trace"], trace)}


def _capture_screenshot(step: dict[str, Any], project_root: Path, run_root: Path) -> dict[str, str]:
    actual_path = Path(step["outputs"]["actual"])
    if actual_path.exists():
        raise VueExecutionExecutorError("actual screenshot output already exists")
    actual_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _browser_probe(
        project_root=project_root,
        run_root=run_root,
        route=step["inputs"]["route"],
        viewport=step["inputs"]["viewport"],
        mode="screenshot",
        output=actual_path,
    )
    metadata = actual_path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise VueExecutionExecutorError("actual screenshot is not a regular file")
    with actual_path.open("rb") as stream:
        signature = stream.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        raise VueExecutionExecutorError("actual screenshot is not PNG")
    provenance = {
        "kind": "icp.vue-runtime-capture-provenance.v1",
        "schema_version": 1,
        "actual_source": "browser_screenshot",
        "actual_sha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
        "route": step["inputs"]["route"],
        "viewport": step["inputs"]["viewport"],
        "browser_name": payload["browser_name"],
        "browser_version": payload["browser_version"],
    }
    provenance_digest = _publish_json(step["outputs"]["provenance"], provenance)
    return {"actual_sha256": provenance["actual_sha256"], "provenance_sha256": provenance_digest}


def execute_authorization(
    authorization: dict[str, Any],
    *,
    expected_manifest_path: str,
    expected_manifest_sha256: str,
    expected_binding_digest: str,
    expected_authorization_digest: str,
) -> dict[str, Any]:
    verified = _authorization.verify_authorization(
        authorization,
        expected_manifest_path=expected_manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_binding_digest=expected_binding_digest,
        expected_authorization_digest=expected_authorization_digest,
    )
    binding = authorization["binding"]
    run_root = Path(binding["selection_verification"]["run_root"])
    if Path(expected_manifest_path).parent != run_root:
        raise VueExecutionExecutorError("manifest and run root differ")
    receipt_root = _receipt_root(run_root)
    nonce = authorization["execution_nonce"]
    claim = {
        "kind": "icp.vue-execution-claim.v1",
        "schema_version": 1,
        "execution_nonce": nonce,
        "authorization_digest": verified["authorization_digest"],
        "binding_digest": verified["binding_digest"],
    }
    claim_digest = _create_receipt(receipt_root / f"{nonce}.claim.json", claim)
    try:
        step = binding["plan"]["steps"][0]
        action = step["action"]
        project_root = Path(binding["request"]["project_root"])
        run_root = Path(binding["request"]["run_root"])
        if action == "render_vue_feature":
            _strict_json_file(step["inputs"]["design_bundle"])
            _strict_json_file(step["inputs"]["requirement_contract"])
            artifacts = _publish_pair(step["outputs"], binding["request"]["feature_id"])
        elif action == "render_vue_fixture":
            artifacts = _render_fixture(step, binding["request"]["feature_id"])
        elif action == "capture_dom_trace":
            artifacts = _capture_dom_trace(step, project_root, run_root)
        elif action == "prepare_vue_packaging":
            artifacts = _prepare_packaging(step)
        elif action == "run_vue_tests":
            artifacts = _run_test_action(step, project_root)
        elif action == "capture_browser_screenshot":
            artifacts = _capture_screenshot(step, project_root, run_root)
        elif action == "run_vue_project_gates":
            artifacts = _run_project_gates(step, project_root)
        elif action == "apply_vue_fan_in":
            artifacts = _apply_fan_in(step, project_root)
        else:
            raise VueExecutionExecutorError("bound action is not implemented")
        status = "success"
    except Exception as exc:
        result = {
            "kind": "icp.vue-execution-result.v1",
            "schema_version": 1,
            "status": "failure",
            "claim_digest": claim_digest,
            "authorization_digest": verified["authorization_digest"],
            "error_type": type(exc).__name__,
        }
        _create_receipt(receipt_root / f"{nonce}.result.json", result)
        if isinstance(exc, VueExecutionExecutorError):
            raise
        raise VueExecutionExecutorError("bound action failed") from exc
    result = {
        "kind": "icp.vue-execution-result.v1",
        "schema_version": 1,
        "status": status,
        "claim_digest": claim_digest,
        "authorization_digest": verified["authorization_digest"],
        "artifact_digests": artifacts,
    }
    result_digest = _create_receipt(receipt_root / f"{nonce}.result.json", result)
    return {
        "kind": KIND_REPORT,
        "schema_version": SCHEMA_VERSION,
        "platform_id": "vue",
        "profile_id": "vue-vite",
        "operation_id": binding["operation_id"],
        "status": "success",
        "execution_nonce": nonce,
        "authorization_digest": verified["authorization_digest"],
        "claim_digest": claim_digest,
        "result_digest": result_digest,
        "artifact_digests": artifacts,
    }
