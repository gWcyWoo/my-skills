"""Web (JS) device operations — headless browser via Playwright/Puppeteer."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from device import run


def _find_npm(project: Path) -> str:
    if (project / "yarn.lock").exists():
        return "yarn"
    if (project / "pnpm-lock.yaml").exists():
        return "pnpm"
    return "npm"



_server_proc = None
_port = 3000
_project = None
_route = None


def running_devices():
    if _server_proc and _server_proc.poll() is None:
        return [f"localhost:{_port}"]
    return []


def boot_device(name=None):
    return f"localhost:{_port}"


def find_artifact(project: Path) -> str:
    global _project
    _project = project
    flutter_web = project / "build" / "web"
    if flutter_web.exists():
        return str(flutter_web)
    dist = project / "dist"
    if not dist.exists():
        dist = project / "build"
    if not dist.exists():
        raise FileNotFoundError("no dist/ or build/ directory found")
    return str(dist)


def build(project: Path) -> str:
    global _project
    _project = project
    if (project / "pubspec.yaml").exists():
        run(["flutter", "build", "web"], timeout=600, cwd=str(project))
        return find_artifact(project)
    pm = _find_npm(project)
    run([pm, "install"], timeout=300, cwd=str(project))
    run([pm, "run", "build"], timeout=300, cwd=str(project))
    return find_artifact(project)


def install(device_id, artifact_path):
    pass


def launch(device_id, package_or_url, route=None):
    global _server_proc, _port, _route
    _route = route
    if not _project:
        raise RuntimeError("_project not set — call build() or find_artifact() first")
    project = _project
    if (project / "pubspec.yaml").exists():
        web_dir = project / "build" / "web"
        if not web_dir.exists():
            raise FileNotFoundError("flutter build/web not found — run build first")
        _port = 8080
        _server_proc = subprocess.Popen(
            ["python3", "-m", "http.server", str(_port)],
            cwd=str(web_dir),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        pm = _find_npm(project)
        _server_proc = subprocess.Popen(
            [pm, "run", "dev"],
            cwd=str(project),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    time.sleep(5)


def _base_url():
    path = f"/{_route}" if _route else ""
    return f"http://localhost:{_port}{path}"


def _node_bin():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node not found — needed for headless browser operations")
    return node


def screenshot(device_id, out_path: Path) -> int:
    node = _node_bin()
    script = (
        "const p=require('puppeteer');"
        f"(async()=>{{const b=await p.launch({{headless:'new'}});"
        f"const pg=await b.newPage();await pg.goto('{_base_url()}');"
        f"await pg.screenshot({{path:'{out_path}',fullPage:true}});"
        "await b.close()}})()"
    )
    run([node, "-e", script], timeout=30, cwd=str(_project))
    return out_path.stat().st_size


def dump_view_tree(device_id, out_path: Path):
    node = _node_bin()
    script = (
        "const p=require('puppeteer');"
        "(async()=>{const b=await p.launch({headless:'new'});"
        f"const pg=await b.newPage();await pg.goto('{_base_url()}');"
        f"const h=await pg.content();require('fs').writeFileSync('{out_path}',h);"
        "await b.close()})()"
    )
    run([node, "-e", script], timeout=30, cwd=str(_project))


def count_view_nodes(html_path: Path) -> int:
    content = html_path.read_text(errors="replace")
    return content.count("<div") + content.count("<span") + content.count("<button")


def kill_device(device_id):
    global _server_proc
    if _server_proc:
        _server_proc.terminate()
        _server_proc = None
