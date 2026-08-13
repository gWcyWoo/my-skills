# ICP worker node contract v2

Use this contract only for one `icp.worker-node-job.v2` emitted from a frozen
`icp.implementation-contract.v1`. The implementation contract, not the worker's
summary or preference, owns the public target, path boundary, observable clauses,
acceptance cases, TDD slice order, design states, and evidence obligations.

1. Invoke `$icp`; read the current Skill, this contract, the node job, and the
   exact bound implementation contract before editing tests or production files.
2. Verify the contract SHA-256 and implement only `owned_clause_ids` under the
   node's unchanged `allowed_paths`. Never omit, weaken, rewrite, or add product
   behavior outside the frozen contract.
3. Run `owned_tdd_slice_ids` serially. For each slice, produce a valid integration
   RED for missing or wrong observable behavior, apply only its minimum GREEN,
   and refactor only while every completed slice remains green. Unit tests do not
   replace a required integration case.
4. For a page node, reach every `owned_design_state_id` using its frozen setup and
   calibration. Compare against the frozen reference artifact; use the frozen
   viewport, density, font scale, locale, theme, system bars, geometry anchors,
   regional thresholds, typography, colors, and assets. Follow
   `visual-verification-contract-v1.md` and seal two independent reset/capture
   runs for every state. Do not select a different reference or loosen a threshold.
5. Write real evidence below the node state. Test bindings use a non-empty JUnit
   XML report whose named testcase passed. Visual bindings use the canonical
   `visual-verification.json`. Runtime bindings use
   `icp.runtime-provenance.v1`. Static contract/design bindings point to their
   frozen artifacts. Every artifact is SHA-256 bound.
6. Do not access Sheet/Excel state, leases, Git, commits, branches, pushes, or PRs.
   Return after exactly this node.

For `status=passed`, write `icp.acceptance-evidence.v1` with exactly one binding
for every `(owned clause ID, required evidence kind)` pair, then write:

```json
{
  "kind": "icp.worker-node-result.v2",
  "schema_version": 2,
  "node_id": "page:PAGE-002",
  "status": "passed",
  "changed_files": ["app/src/main/Page.kt"],
  "verification": {
    "focused_tests": "passed",
    "scope": "passed",
    "self_check": "passed"
  },
  "evidence": [
    "node-tests.txt",
    "junit.xml",
    "visual-verification.json",
    "acceptance-evidence.json"
  ],
  "loaded_contracts": {
    "icp_skill_sha256": "64-lowercase-sha256",
    "worker_contract_sha256": "64-lowercase-sha256"
  },
  "implementation_contract": {
    "path": "/absolute/job-state/implementation-contract.json",
    "sha256": "64-lowercase-sha256",
    "source_clauses_digest": "64-lowercase-sha256",
    "owned_clause_ids": [],
    "owned_acceptance_case_ids": [],
    "owned_tdd_slice_ids": [],
    "owned_design_state_ids": []
  },
  "acceptance_evidence": "acceptance-evidence.json",
  "error_code": null
}
```

Each acceptance binding contains `clause_id`, `evidence_kind`, absolute
`artifact_path`, live `artifact_sha256`, `case_bindings`, and `state_bindings`.
Test case bindings map exact acceptance case IDs to passed JUnit testcase names;
visual state bindings map exact design state IDs to canonical visual state names.

```json
{
  "kind": "icp.acceptance-evidence.v1",
  "schema_version": 1,
  "node_id": "exact node ID",
  "implementation_contract_sha256": "frozen contract sha256",
  "bindings": [{
    "clause_id": "owned clause ID",
    "evidence_kind": "integration",
    "artifact_path": "/absolute/node-state/junit.xml",
    "artifact_sha256": "live artifact sha256",
    "case_bindings": [{
      "acceptance_case_id": "owned case ID",
      "test_id": "exact passed JUnit testcase name"
    }],
    "state_bindings": []
  }]
}
```

`contract` and `design` bindings have empty case/state bindings and point to their
frozen artifacts. `visual` bindings point to `visual-verification.json` and map
design state IDs to visual state names. `runtime` bindings point to a canonical
runtime provenance JSON whose `actual_path` names a real node-state capture with a
matching `actual_sha256`; they have empty case/state bindings.

For a real external/contract blocker or the visual contract's two consecutive
no-progress condition, return `status=failed` with one controlled printable
`error_code`. Do not claim coverage for unproved clauses. A first visual mismatch
is never terminal.
