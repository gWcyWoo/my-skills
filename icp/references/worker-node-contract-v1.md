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
   comparison, and measured root-cause repair. Before production edits, define the
   public target, path ownership, and exact observable state matrix. Do not replace
   that loop with a worker-specific one.
5. Run focused tests for the node. For a page node, follow
   `visual-verification-contract-v1.md`: an intermediate mismatch stays internal;
   classify and repair one target at a time while its score improves. Seal two
   independent clean final runs per state with `visual_evidence_v1.py`, then seal
   calibration, state contracts, anchors, regions, and history with
   `visual_verification_v1.py` as `visual-verification.json` below the node state.
   Write non-empty evidence files below that directory and exactly one
   `icp.worker-node-result.v1` to the supplied result path.
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
  "evidence": ["node-tests.txt", "visual-verification.json"],
  "loaded_contracts": {
    "icp_skill_sha256": "64-lowercase-sha256",
    "worker_contract_sha256": "64-lowercase-sha256"
  },
  "error_code": null
}
```

For `status=failed`, set one controlled printable `error_code`; do not claim that
the node passed and do not start another node. Use failure only for inaccessible
design/runtime, an incomplete or contradictory approved observable contract, or
two consecutive no-progress targeted repairs for the same material mismatch.
Never publish the first visual mismatch as terminal and never hide a remaining
mismatch inside passing evidence.
