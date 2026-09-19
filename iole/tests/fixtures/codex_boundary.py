#!/usr/bin/env python3
"""Recording Codex-process boundary; IOLE ledger/storage code remains real."""
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

prompt = sys.stdin.read()
job = json.loads(prompt.split("IOLE_JOB_JSON\n", 1)[1].split("\nEND_IOLE_JOB_JSON", 1)[0])
project = Path(job["project"])
mode_file = project / "boundary-mode.json"
mode = json.loads(mode_file.read_text()) if mode_file.exists() else {}
phase, node = job["phase"], job.get("node_id")
result_path = Path(sys.argv[sys.argv.index("-o") + 1])
resume = len(sys.argv) > 2 and sys.argv[2] == "resume"
session = sys.argv[-2] if resume else str(uuid.uuid4())
record = {"phase": phase, "node": node, "session": session, "resume": resume,
          "prompt": prompt, "job": job, "pid": os.getpid(), "argv": sys.argv[1:]}
with (project / "boundary-calls.jsonl").open("a") as f:
    f.write(json.dumps(record) + "\n")


def event(value):
    print(json.dumps(value), flush=True)


def command(script, *args):
    p = subprocess.run([sys.executable, str(Path(job["skills_root"]) / script), *map(str, args)],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return json.loads(p.stdout)


event({"type": "thread.started", "thread_id": session})
event({"type": "turn.started"})
answer = {"node_id": node or "", "outcome": "done", "summary": phase + " verified",
          "evidence": [], "source_synced": False, "lease_until": None}
sheet_path = project / "source.json"
claims_path = project / "boundary-claims.json"
claims = json.loads(claims_path.read_text()) if claims_path.exists() else {}
run = json.loads(Path(job["run"]).read_text())
row_id = run["nodes"][node]["row"]["row_id"] if node else None
storage = run["nodes"][node].get("source_skill", "icpl") if node else "icpl"
storage_script = "icps/scripts/icps_local.py" if storage == "icps" else "icpl/scripts/icpl.py"

if job.get("preflight_required") and not mode.get("missing_preflight"):
    source = json.loads(sheet_path.read_text())
    issues = []
    for nid in job["preflight_nodes"]:
        rid = run["nodes"][nid]["row"]["row_id"]
        cell = next(row for row in source["rows"] if row["row_id"] == rid)["roles"]["frontend"]
        if cell["status"] == "doing":
            if cell["lease_token"] != claims.get(nid):
                issues.append({"node_id": nid, "kind": "foreign_owner", "summary": "Source token is not in this run's claim record"})
            elif datetime.fromisoformat(cell["lease_until"]) <= datetime.now(timezone.utc):
                issues.append({"node_id": nid, "kind": "owned_expired", "summary": "Owned lease expired before dispatch"})
    snapshot = Path(job["preflight_path"]).with_suffix(".source.json")
    snapshot.write_text(json.dumps(source))
    report = {"generation": job["generation"], "run": job["run"], "checked": job["preflight_nodes"],
              "issues": issues, "evidence": [str(snapshot)]}
    if mode.get("stale_preflight"):
        report["generation"] = "old-launch"
    if mode.get("incomplete_preflight"):
        report["checked"] = report["checked"][1:]
    Path(job["preflight_path"]).write_text(json.dumps(report))


def maintain_lease(cell):
    operation = "renew" if datetime.fromisoformat(cell["lease_until"]) > datetime.now(timezone.utc) else "recover"
    result = command(storage_script, operation, "--link", sheet_path, "--role", "frontend",
                     "--row-id", row_id, "--lease-token", claims[node],
                     "--expected-lease-until", cell["lease_until"], "--lease-minutes", "60")
    claims[node] = result["lease_token"]
    claims_path.write_text(json.dumps(claims))
    with (project / "lease-operations.jsonl").open("a") as f:
        f.write(json.dumps({"node": node, "operation": operation, **result}) + "\n")
    if mode.get("lease_ack_lost") and not (project / "lease-ack-lost").exists():
        (project / "lease-ack-lost").touch()
        event({"type": "turn.failed", "error": {"message": "Acknowledgement lost after lease update"}})
        sys.exit(7)
    return result

if mode.get("hold_phase") == phase:
    (project / "boundary-ready.json").write_text(json.dumps({"pid": os.getpid()}))
    while not (project / "boundary-release").exists():
        time.sleep(0.01)

if phase == "prepare":
    if job.get("feedback"):
        command(storage_script, "claim", "--link", sheet_path, "--role", "frontend",
                "--row-ids", row_id, "--status", "ready", "--error", "Confirmed tree-audit repair")
    if node in claims and not job.get("feedback"):
        cell = next(row for row in json.loads(sheet_path.read_text())["rows"]
                    if row["row_id"] == row_id)["roles"]["frontend"]
        if cell["lease_token"] != claims[node] or cell["status"] != "doing":
            answer.update(outcome="node_blocked", summary="Source belongs to another owner")
            result_path.write_text(json.dumps(answer))
            event({"type": "turn.completed", "usage": {}})
            sys.exit(0)
        if mode.get("legacy_expiry_block"):
            answer.update(outcome="blocked", summary="Expired owned lease has no supported recovery operation")
            result_path.write_text(json.dumps(answer))
            event({"type": "turn.completed", "usage": {}})
            sys.exit(0)
        claim = (maintain_lease(cell) if datetime.fromisoformat(cell["lease_until"]) <= datetime.now(timezone.utc)
                 else cell)
    else:
        claim = command(storage_script, "inspect", "--link", sheet_path, "--role", "frontend",
                        "--title", job["title"], "--claim", "doing", "--lease-minutes", "60")
    claims[node] = claim["lease_token"]
    claims_path.write_text(json.dumps(claims))
    answer.update(outcome="ready", source_synced=True, lease_until=claim["lease_until"])
    if mode.get("lease_soon"):
        answer["lease_until"] = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    if mode.get("lease_seconds"):
        answer["lease_until"] = (datetime.now(timezone.utc) + timedelta(seconds=mode["lease_seconds"])).isoformat()
    if mode.get("lease_soon") or mode.get("lease_seconds"):
        sheet = json.loads(sheet_path.read_text())
        next(r for r in sheet["rows"] if r["row_id"] == row_id)["roles"]["frontend"]["lease_until"] = answer["lease_until"]
        sheet_path.write_text(json.dumps(sheet))
    if mode.get("prepare_blocked"):
        answer.update(outcome="blocked", summary="Preparation prerequisite unavailable")
    if node in mode.get("node_blocked", []):
        answer.update(outcome="node_blocked", summary="Page prerequisite unavailable")
    if mode.get("missing_lease"):
        answer["lease_until"] = None
elif phase == "recover":
    cell = next(row for row in json.loads(sheet_path.read_text())["rows"] if row["row_id"] == row_id)["roles"]["frontend"]
    if cell["status"] == "review" and job["recovering_phase"] == "review":
        answer.update(outcome="ready", source_synced=True)
    elif cell["status"] == "doing" and cell["lease_token"] == claims.get(node):
        if mode.get("recovery_unchanged"):
            answer.update(outcome="ready", source_synced=True, lease_until=cell["lease_until"])
        elif mode.get("lease_soon"):
            answer.update(outcome="node_blocked", summary="Lease recovery prerequisite unavailable")
        else:
            lease = (maintain_lease(cell) if mode.get("lease_seconds") or datetime.fromisoformat(cell["lease_until"]) <= datetime.now(timezone.utc)
                     else cell)
            answer.update(outcome="ready", source_synced=True, lease_until=lease["lease_until"])
    else:
        answer.update(outcome="blocked", summary="Recorded source ownership is no longer valid")
elif phase == "implement":
    if mode.get("hold"):
        event({"type": "item.completed", "item": {"type": "agent_message", "text": "Waiting at controlled external boundary"}})
        ready = project / ("grandchild-ready-" + str(os.getpid()))
        child_code = "import signal,time; from pathlib import Path; "
        if mode.get("ignore_term"):
            child_code += "signal.signal(signal.SIGTERM, signal.SIG_IGN); signal.signal(signal.SIGINT, signal.SIG_IGN); "
        child_code += f"Path({str(ready)!r}).touch(); time.sleep(120)"
        child = subprocess.Popen([sys.executable, "-c", child_code], start_new_session=mode.get("detached", False))
        while not ready.exists():
            time.sleep(0.01)
        (project / "boundary-ready.json").write_text(json.dumps({"pid": os.getpid(), "grandchild": child.pid}))
        while not (project / "boundary-release").exists():
            time.sleep(0.01)
        child.terminate()
        child.wait()
    folder = project / ".codex" / "icp" / job["title"]
    folder.mkdir(parents=True, exist_ok=True)
    if not mode.get("missing_evidence"):
        (folder / "layout-blueprint.json").write_text('{"components": [{"name": "fixture"}]}')
        (folder / "api-contract.json").write_text('{"apis": []}')
        (folder / "behavior-result.json").write_text(json.dumps({
            "behavior_total": 1, "behavior_passed": 1, "mock_violations": [],
            "positive": {"total": 1, "passed": 1, "failed": []},
            "negative": {"total": 0, "passed": 0, "failed": []}}))
    answer["evidence"] = [str(folder / "behavior-result.json")]
    if mode.get("blocked"):
        answer.update(outcome="blocked", summary="Required external fixture unavailable")
elif phase == "review":
    if mode.get("revision") and not (project / "revision-requested").exists():
        (project / "revision-requested").touch()
        answer.update(outcome="needs_revision", summary="Repair the demonstrated fixture defect")
    else:
        command("iole/scripts/iole.py", "mark", "--run", job["run"], "--node", node,
                "--status", "done", "--check")
        sheet = json.loads(sheet_path.read_text())
        cell = next(row for row in sheet["rows"] if row["row_id"] == row_id)["roles"]["frontend"]
        if cell["status"] != "review":
            command(storage_script, "claim", "--link", sheet_path, "--role", "frontend",
                    "--row-ids", row_id, "--status", "review", "--lease-token", claims[node])
        if mode.get("writeback_interrupted"):
            event({"type": "turn.failed", "error": {"message": "Connection lost after remote write"}})
            sys.exit(7)
        if node in mode.get("partial_nodes", []) and not job.get("feedback"):
            command("iole/scripts/iole.py", "mark", "--run", job["run"], "--node", node, "--status", "partial", "--error", "Independent acceptance remains")
            answer.update(outcome="partial")
        else:
            command("iole/scripts/iole.py", "mark", "--run", job["run"], "--node", node, "--status", "done")
        answer["source_synced"] = not mode.get("unconfirmed_sync")
elif phase == "finalize":
    answer["source_synced"] = True
    if mode.get("tree_blocked"):
        answer.update(outcome="blocked", summary="Cross-page acceptance missing")
    if mode.get("tree_revision") and not (project / "tree-revision-requested").exists():
        (project / "tree-revision-requested").touch()
        answer.update(outcome="needs_revision", node_id=mode.get("repair_node", "n0"), summary="Repair demonstrated cross-page defect")
    if mode.get("repair_partials"):
        partial = next((n for n, p in run["progress"].items() if p["status"] == "partial"), None)
        if partial:
            answer.update(outcome="needs_revision", node_id=partial, summary="Close independent retained acceptance")

if mode.get("bad_result") and phase == "implement":
    kind = mode["bad_result"]
    if kind == "wrong_node":
        answer["node_id"] = "some-other-node"
    elif kind == "wrong_type":
        answer["source_synced"] = "true"
    elif kind == "missing_field":
        answer.pop("evidence")
    elif kind == "malformed":
        result_path.write_text("not json")
if mode.get("bad_result") != "malformed" or phase != "implement":
    result_path.write_text(json.dumps(answer))
event({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}})
if not (phase == "implement" and mode.get("no_completion")):
    event({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 80,
                                               "output_tokens": 10, "reasoning_output_tokens": 4}})
if phase == "implement" and mode.get("nonzero_exit"):
    sys.exit(9)
