#!/usr/bin/env python3
"""Focused regression tests for shared-worker liveness and evidence gates."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True)


def write_fake_worker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

mode = sys.argv[1]
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text(encoding="utf-8"))

if mode == "hang":
    marker = Path(sys.argv[3])
    pid_file = Path(sys.argv[4])
    child_code = r'''\
from pathlib import Path
import signal
import sys
import time

marker = Path(sys.argv[1])
def stop(signum, frame):
    marker.write_text("terminated", encoding="utf-8")
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
while True:
    time.sleep(1)
'''
    child = subprocess.Popen([sys.executable, "-c", child_code, str(marker)])
    pid_file.write_text(str(child.pid), encoding="utf-8")
    print("hung worker started", flush=True)
    while True:
        time.sleep(1)

if mode == "exit0":
    raise SystemExit(0)

if mode in {"valid", "paintless"}:
    subprocess.run(contract["complianceCommand"], check=True)
    compliance = Path(contract["compliance"])
    render_plan = {
        "nodes": {
            "logo": {
                "implementation": "shape",
                "bbox": [0, 0, 74, 74],
                "required": True,
                "renderMode": "absolute_positioned",
                "widgetTraceRequired": True,
                "fills": [] if mode == "paintless" else ["#66DD77"],
            }
        }
    }
    (Path(contract["jobRoot"]) / "component_render_plan.json").write_text(
        json.dumps(render_plan), encoding="utf-8"
    )
    result = {
        "success": True,
        "invocation_id": os.environ["IFF_SHARED_INVOCATION_ID"],
        "prompt_sha256": os.environ["IFF_SHARED_PROMPT_SHA256"],
        "result_path": contract["result"],
        "compliance_path": contract["compliance"],
        "compliance_sha256": hashlib.sha256(compliance.read_bytes()).hexdigest(),
    }
    Path(contract["result"]).write_text(
        json.dumps(result, sort_keys=True) + "\\n", encoding="utf-8"
    )
    raise SystemExit(0)

raise SystemExit(f"unknown mode: {mode}")
""",
        encoding="utf-8",
    )


def make_contract(root: Path, scripts: Path, skill: Path, name: str) -> Path:
    case = root / name
    project = case / "project"
    job = case / "job"
    source = case / "source"
    project.mkdir(parents=True)
    job.mkdir(parents=True)
    source.mkdir(parents=True)
    component = job / "component.json"
    component.write_text(
        json.dumps(
            {
                "signature": f"synthetic:{name}",
                "source_spec_dir": str(source),
                "widget_path": f"lib/shared/{name}_canvas.dart",
                "colors_path": f"lib/shared/{name}_canvas_colors.dart",
                "test_path": f"test/shared/{name}_canvas_test.dart",
                "asset_target": f"assets/shared/{name}",
                "bbox": [0, 0, 320, 120],
                "group_node": f"group:{name}",
                "class_name": "SyntheticSharedCanvas",
                "result_path": str(job / "shared_result.json"),
                "compliance_path": str(job / "worker_compliance.json"),
            }
        ),
        encoding="utf-8",
    )
    prompt = job / "worker_prompt.md"
    generated = run(
        sys.executable,
        str(scripts / "make_worker_prompt.py"),
        "--skill-dir",
        str(skill),
        "--mode",
        "shared",
        "--component-json",
        str(component),
        "--spec-dir",
        str(job),
        "--project-root",
        str(project),
        "--out",
        str(prompt),
    )
    assert generated.returncode == 0, generated.stderr or generated.stdout
    generated_paths = json.loads(generated.stdout)
    assert Path(generated_paths["prompt"]) == prompt
    return Path(generated_paths["invocationContract"])


def supervised(
    supervisor: Path,
    contract: Path,
    worker: Path,
    mode: str,
    *worker_args: str,
    idle: str = "2",
    total: str = "10",
) -> subprocess.CompletedProcess[str]:
    return run(
        sys.executable,
        str(supervisor),
        "run",
        "--contract",
        str(contract),
        "--idle-timeout",
        idle,
        "--total-timeout",
        total,
        "--",
        sys.executable,
        str(worker),
        mode,
        str(contract),
        *worker_args,
    )


def failure_payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode != 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent
    supervisor = scripts / "shared_worker_supervisor.py"

    with tempfile.TemporaryDirectory(prefix="iff-shared-supervisor-") as raw_tmp:
        root = Path(raw_tmp)
        worker = root / "fake_worker.py"
        write_fake_worker(worker)

        hung_contract = make_contract(root, scripts, skill, "hung")
        marker = root / "grandchild_terminated"
        pid_file = root / "grandchild.pid"
        hung = supervised(
            supervisor,
            hung_contract,
            worker,
            "hang",
            str(marker),
            str(pid_file),
            idle="0.5",
            total="5",
        )
        hung_failure = failure_payload(hung)
        assert hung_failure["reason"] == "idle_timeout", hung_failure
        for _ in range(40):
            if marker.exists():
                break
            time.sleep(0.05)
        assert marker.exists(), "hung worker grandchild did not receive process-group termination"
        assert pid_file.exists(), "hung worker did not create its descendant process"

        no_result_contract = make_contract(root, scripts, skill, "no_result")
        no_result = supervised(supervisor, no_result_contract, worker, "exit0")
        assert failure_payload(no_result)["reason"] == "missing_result"

        stale_contract = make_contract(root, scripts, skill, "stale")
        stale_data = json.loads(stale_contract.read_text(encoding="utf-8"))
        stale_path = Path(stale_data["result"])
        stale_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "invocation_id": stale_data["invocationId"],
                    "prompt_sha256": stale_data["promptSha256"],
                }
            ),
            encoding="utf-8",
        )
        os.utime(stale_path, (1, 1))
        stale = supervised(supervisor, stale_contract, worker, "exit0")
        assert failure_payload(stale)["reason"] == "missing_result"
        assert not stale_path.exists(), "stale result was not cleared before launch"

        valid_contract = make_contract(root, scripts, skill, "valid")
        valid = supervised(supervisor, valid_contract, worker, "valid")
        assert valid.returncode == 0, valid.stdout + valid.stderr
        valid_payload = json.loads(valid.stdout.strip().splitlines()[-1])
        assert valid_payload["success"] is True, valid_payload
        valid_data = json.loads(valid_contract.read_text(encoding="utf-8"))
        assert Path(valid_data["result"]).exists()
        assert Path(valid_data["compliance"]).exists()

        paintless_contract = make_contract(root, scripts, skill, "paintless")
        paintless = supervised(supervisor, paintless_contract, worker, "paintless")
        assert paintless.returncode != 0, paintless.stdout
        assert failure_payload(paintless)["code"] == "paintless_render_plan", paintless.stdout

    print(
        "PASS: hung process groups, missing/stale/paintless results, and fresh shared evidence are supervised"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
