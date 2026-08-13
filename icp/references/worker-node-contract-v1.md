# ICP worker node contract v1

Use this contract only for one node emitted by `icp_flow_job_v1.py next-node`.

1. Invoke `$icp`, read the canonical node job and current ICP Skill completely,
   and execute the applicable ICP workflow. Merely reading the Skill or running
   focused behavior tests is not ICP completion.
2. Work only in the supplied `project_root` and only under the node's
   `allowed_paths`. Treat a path ending in `/` as a directory prefix; treat every
   other path as one exact file.
3. Do not access Sheet/Excel queues, leases, statuses, Git, commits, branches,
   pushes, or pull requests. Those effects belong to IOLE.
4. For a shared-component node, implement or extend the single declared component
   before consumers run. For a page node, reuse the declared component decision,
   do not modify another node's owned shared path, and run the full ICP design
   compiler loop: exact design fetch, implementation, real runtime capture, visual
   comparison, and repair. Do not replace that loop with a worker-specific one.
5. Run focused tests for the node. A page node must also use ICP's existing
   `scripts/shared_core/visual_evidence_v1.py` to seal its reference, real runtime
   capture, provenance, and diff as `visual-evidence.json` below the node state
   directory. Write non-empty evidence files below that directory and exactly one
   `icp.worker-node-result.v1` to the result path supplied by the prompt.
6. Include exact changed project-relative files, `passed` verification for
   `focused_tests`, `scope`, and `self_check`, plus SHA-256 values for the current
   ICP Skill and this contract. Return control after this one node.

Use this result shape:

```json
{
  "kind": "icp.worker-node-result.v1",
  "schema_version": 1,
  "node_id": "page:PAGE-002",
  "status": "passed",
  "changed_files": ["app/src/main/Page.kt"],
  "verification": {
    "focused_tests": "passed",
    "scope": "passed",
    "self_check": "passed"
  },
  "evidence": ["node-tests.txt", "visual-evidence.json"],
  "loaded_contracts": {
    "icp_skill_sha256": "64-lowercase-sha256",
    "worker_contract_sha256": "64-lowercase-sha256"
  },
  "error_code": null
}
```

For `status=failed`, set one controlled printable `error_code`; do not claim that
the node passed and do not start another node. In particular, inaccessible design,
missing real runtime capture, a visual mismatch, or incomplete UI must fail; never
hide any of them inside a passing evidence note.
