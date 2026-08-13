# ICP external page-job contract v2

## Ownership

IOLE owns Sheet routing, role state, atomic claim and lease, canonical row mapping,
worktree and branch selection, commit, push, PR reuse or creation, retries, and all
writeback. ICP owns one canonical client page implementation or review repair plus
page-level verification and a machine-readable handoff.

## Input

`icp_page_job_v1.py prepare --job ABSOLUTE_JSON` accepts
`icp.external-page-job.v2` with the existing page-job identity, platform, design,
and page fields plus:

```json
{
  "role": "client",
  "mode": "revise",
  "review": {
    "number": 3,
    "text": "按钮点击没有跳转"
  }
}
```

Only `role=client` is valid. `mode=implement` requires `review=null`.
`mode=revise` requires exactly one positive integer review number and one non-empty
review text. Workbook status, column names, PR URLs, leases, commands, and runtime
overrides remain invalid inputs.

Require non-empty string identity, design, platform, profile, title, requirement,
and route fields; a route without control characters; an absolute project root; a
lowercase Git revision; a lowercase SHA-256 row digest; and an acceptance list
whose present items are non-empty strings. The list itself may be empty. Malformed field types
must return controlled `invalid-input/job_schema_invalid` without project changes.
Require a real project directory and reject a symlinked project or any symlink in
the `.icp/page-jobs/<job-id-digest>` state-root chain before publishing state and
again before finalization.

IOLE derives a new deterministic job ID from source identity, role, row identity,
latest review number, and immutable row digest. Identical canonical input resumes;
changed input under the same job ID is blocked as input drift. Existing v1 jobs
remain accepted for compatibility.

## Execution

For `implement`, implement the supplied page from the design and page contract. For
`revise`, inspect the existing PR-head worktree, preserve correct existing behavior,
and make the smallest change that satisfies the supplied latest review. Use the
design and original page contract as constraints; the review does not authorize
unrelated redesign or repository-wide changes.

Both modes require focused tests, the minimum build/type gate, real runtime capture,
and visual verification. A review repair updates the same upstream branch and PR;
ICP never operates PR tooling itself.

## Handoff

Before finalization, publish this exact manifest below the current job state root:

```json
{
  "kind": "icp.page-evidence-manifest.v1",
  "schema_version": 1,
  "job_id": "the prepared job ID",
  "job_digest": "the prepared job digest",
  "artifacts": {
    "page_tests": {
      "status": "passed",
      "path": "page-tests.txt",
      "sha256": "64-lowercase-sha256"
    },
    "runtime_capture": {
      "status": "passed",
      "path": "actual.png",
      "actual_source": "browser_screenshot",
      "sha256": "64-lowercase-sha256"
    },
    "visual": {
      "status": "passed",
      "path": "visual-comparison.json",
      "sha256": "64-lowercase-sha256"
    }
  }
}
```

Artifact paths are relative to the job state root. They must identify three
distinct, non-empty, regular non-symlink files without parent traversal or a
symlinked directory, and every declared SHA-256 must match its artifact.
`actual_source` is `browser_screenshot` for Next.js/Vue,
`simulator_screenshot` for Flutter/iOS, and `emulator_screenshot` for Android.
Finalization rejects an empty, malformed, identity-mismatched, or incomplete
manifest.

The handoff input uses exactly the six documented keys: `kind`, `schema_version`,
`status`, `changed_files`, `verification`, and `evidence_manifest`. Reject unknown
fields, including PR, Sheet, lease, command, and runtime override data.

Successful finalization publishes `icp.page-handoff-result.v1`. The job ID and row
digest identify the IOLE review attempt. The result contains changed files,
verification evidence, and the evidence-manifest SHA-256, but no Sheet state or PR
URL.
