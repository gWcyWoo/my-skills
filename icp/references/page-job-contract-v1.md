# ICP external page-job contract v1

This is the active contract for `~/.agents/skills/icp`.

## Ownership

The upstream caller owns Excel polling, atomic row claim/lease, canonical row-to-job
mapping, isolated branch/worktree creation, commit, push, PR creation, retries, and
all status or URL writeback.

ICP owns exactly one page job: design retrieval and normalization, page code and
assets, focused page tests, real runtime capture, visual evidence, resumable local
job state, and a machine-readable ready-for-PR handoff.

## Preparation

`icp_page_job_v1.py prepare --job ABSOLUTE_JSON` accepts exactly one
`icp.external-page-job.v1`. It validates the strict document shape, lowercase
SHA-256 row identity, fixed platform/profile pair, project worktree, and exact Git
HEAD. It persists canonical input below
`<project_root>/.icp/page-jobs/<sha256(job_id)>/input.json`.

Preparation never reads CSV/Excel, selects or claims rows, installs dependencies,
downloads a design, probes a browser/device, performs writeback recovery, or creates
a PR. Identical input resumes; changed input for the same `job_id` is blocked.

`page.route` retains its v1 name but has platform-specific validation. Next.js and
Vue require an absolute route beginning with `/`. Flutter, iOS, and Android accept
any non-empty stable page, screen, or component target identifier. A native target
identifier does not itself require production navigation registration.

## Execution

The agent fetches only the supplied design, implements only the supplied page target,
and checks dependencies or runtime targets when the relevant page step executes.
Reusable component targets use existing preview, host-screen, or test-harness
conventions for runtime capture rather than inventing a production route.
The page must pass focused tests, real runtime capture, and visual verification.
Design images cannot be used as the rendered application or as actual evidence.

## Finalization

`icp_page_job_v1.py finalize --job ABSOLUTE_JSON --handoff ABSOLUTE_JSON --result
ABSOLUTE_JSON` accepts one `icp.page-handoff-input.v1` only after page tests, runtime
capture, and visual verification all report `passed`.

Changed files must be real relative files within the worktree. Evidence must be a
real file within the page-job state root. Successful finalization publishes one
idempotent `icp.page-handoff-result.v1`. It never contains PR or status URLs and it
never changes an upstream row.

## Terminal boundary

`ready-for-pr` means only that the page implementation and page evidence are ready
for the upstream caller. The upstream caller independently reviews the diff, commits,
pushes, creates the PR, and writes PR/status URLs and the terminal row state.

Legacy CSV claim/writeback modules remain installed for compatibility but are not
part of this contract.
