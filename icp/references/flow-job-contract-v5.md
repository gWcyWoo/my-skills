# ICP external flow-job contract v5

`icp.external-flow-job.v5` is active for new IOLE client flows. It retains the
exact v4 `source_contract`, member digests, implementation DAG, and path ownership,
then adds an implementation-contract compilation gate.

1. `prepare --job JOB` validates and persists the exact job.
2. `next-node --job JOB` returns `contract-compilation-required` plus canonical
   compiler-input, compiler-prompt, and implementation-contract paths. It emits no
   worker prompt.
3. The main ICP session follows `implementation-contract-v1.md`, fetches and
   analyzes exact design evidence, and writes the candidate contract.
4. `record-contract --job JOB --contract CONTRACT` validates and freezes it.
5. `next-node` serially emits `icp.worker-node-job.v2`; each job contains the
   frozen contract path/SHA and only that node's clause, acceptance-case, TDD-slice,
   and design-state IDs.
6. `record-node` accepts only coverage-bound `icp.worker-node-result.v2` for v5.
7. After all nodes pass, full-flow verification uses
   `icp.flow-handoff-input.v2`, including the frozen contract SHA. `finalize`
   revalidates all node evidence and emits `icp.flow-handoff-result.v2` with
   computed exact clause coverage.

Use the same public CLI for the complete v5 lifecycle:

```sh
python3 ~/.agents/skills/icp/scripts/icp_flow_job_v1.py \
  prepare --job /absolute/flow-job.json
python3 ~/.agents/skills/icp/scripts/icp_flow_job_v1.py \
  next-node --job /absolute/flow-job.json
python3 ~/.agents/skills/icp/scripts/icp_flow_job_v1.py \
  record-contract --job /absolute/flow-job.json \
  --contract /absolute/job-state/implementation-contract.json
python3 ~/.agents/skills/icp/scripts/icp_flow_job_v1.py \
  record-node --job /absolute/flow-job.json \
  --result /absolute/node-state/worker-result.json
python3 ~/.agents/skills/icp/scripts/icp_flow_job_v1.py \
  finalize --job /absolute/flow-job.json \
  --handoff /absolute/job-state/handoff-v2.json \
  --result /absolute/job-state/result.json
```

Before `finalize`, write four distinct non-empty full-flow artifacts under the
job-state directory and bind them with this exact manifest shape. Artifact paths
are job-state-relative and every SHA-256 is live:

```json
{
  "kind": "icp.flow-evidence-manifest.v1",
  "schema_version": 1,
  "job_id": "exact v5 job ID",
  "job_digest": "exact job_digest returned by prepare",
  "artifacts": {
    "node_tests": {
      "status": "passed",
      "path": "flow-node-tests.txt",
      "sha256": "64 lowercase hex"
    },
    "runtime_capture": {
      "status": "passed",
      "path": "flow-runtime.png",
      "sha256": "64 lowercase hex",
      "actual_source": "emulator_screenshot"
    },
    "visual": {
      "status": "passed",
      "path": "flow-visual.json",
      "sha256": "64 lowercase hex"
    },
    "e2e": {
      "status": "passed",
      "path": "flow-e2e.txt",
      "sha256": "64 lowercase hex"
    }
  }
}
```

`actual_source` is `emulator_screenshot` for Android,
`simulator_screenshot` for Flutter/iOS, and `browser_screenshot` for Next.js/Vue.
The handoff file has exactly this v2 shape; `evidence_manifest` is absolute and
the changed files are the exact ordered union from passed workers:

```json
{
  "kind": "icp.flow-handoff-input.v2",
  "schema_version": 2,
  "status": "ready-for-pr",
  "changed_files": ["project/relative/file"],
  "verification": {
    "node_tests": "passed",
    "runtime_capture": "passed",
    "visual": "passed",
    "e2e": "passed"
  },
  "evidence_manifest": "/absolute/job-state/evidence-manifest.json",
  "implementation_contract_sha256": "exact frozen contract sha256"
}
```

These artifacts are full-flow proof in addition to, not a replacement for, each
worker's clause-bound evidence. `finalize` reloads every persisted worker result
and live artifact before computing the v2 result.

Persisted v3 and v4 jobs retain their original progress, worker-result, and handoff
contracts. Never migrate their state in place. New lossless IOLE jobs publish v5.
