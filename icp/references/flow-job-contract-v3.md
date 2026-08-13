# ICP external flow-job contract v3

`icp.external-flow-job.v3` binds one IOLE flow, member digests, project worktree and
base revision, platform/profile, component analysis/decisions, interaction edges,
worker DAG, and deterministic execution order. It contains no Sheet column names,
statuses, lease secrets, PR URL, Git command, or runtime override.

Prepare with:

```bash
python3 icp_flow_job_v1.py prepare --job /absolute/flow-job.json
```

State lives under `<project_root>/.icp/flow-jobs/<sha256(job_id)>/`. Identical input
resumes. The same job ID with changed canonical input is `input-drift`. Verify the
worktree HEAD equals `base_revision` before publishing state.

Drive nodes serially:

```bash
python3 icp_flow_job_v1.py next-node --job /absolute/flow-job.json
python3 icp_flow_job_v1.py record-node \
  --job /absolute/flow-job.json \
  --result /canonical/node/worker-result.json
```

For `ready`, spawn exactly one child agent with the returned `worker_prompt`. For
`resume-required`, resume that node and do not dispatch another. Accept its result
only when it loaded the current ICP Skill and worker contract, changed only its
owned paths, and never touched Sheet or Git/PR ownership. Shared/integration nodes
must produce focused-test/self-check evidence. Every page node must additionally
bind the exact design reference, a real platform runtime capture, and a passed
visual comparison covering layout, typography, color, spacing, assets, and states
through `icp.visual-verification.v1`: exact calibration, state contracts, anchors,
regional metrics, repair history, and two independent passed
`icp.visual-evidence.v1` runs per state. A first mismatch is not terminal; the page
worker owns measured root-cause repair until pass, a real external/contract
blocker, or two consecutive no-progress targeted repairs for the same mismatch.
Behavior-only page results and prose disclaimers about missing visual access are
invalid. A terminal failed node blocks the flow; later nodes do not run.

After every node passes, the main ICP agent runs trusted full-flow tests, real
browser/simulator/emulator capture, visual comparison, and E2E. Publish four
distinct non-empty artifacts in `icp.flow-evidence-manifest.v1`, each with matching
SHA-256. Runtime capture must declare `browser_screenshot`,
`simulator_screenshot`, or `emulator_screenshot` for the selected platform.

Finalize with the exact union of worker-declared changed files:

```bash
python3 icp_flow_job_v1.py finalize \
  --job /absolute/flow-job.json \
  --handoff /absolute/flow-state/handoff.json \
  --result /absolute/flow-state/result.json
```

Successful finalization emits `icp.flow-handoff-result.v1` with `ready-for-pr`,
flow/member identity, changed files, and sealed evidence. It contains no PR or Sheet
state. IOLE alone verifies, commits, pushes, creates/reuses one PR, and atomically
writes every member to `review`.
