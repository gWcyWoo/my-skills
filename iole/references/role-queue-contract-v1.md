# IOLE role queue contract v1

## Ownership

IOLE owns document routing, recurring polling, role selection, atomic claim and
lease, canonical row mapping, isolated Git worktrees, PR reuse or creation, and
role-specific terminal writeback. A role worker owns implementation and verification
only; it never reads workbook columns or mutates queue state.

## Role mapping

Use [role-mapping-v1.json](role-mapping-v1.json) as the only source of role columns.
The current mapping is:

| role | status | PR | reviews | lease token | lease expiry | error |
|---|---|---|---|---|---|---|
| client | `frontend status` | `frontend pr` | `frontend reviews` | `frontend lease_token` | `frontend lease_until` | `frontend last_error` |
| backend | `backend status` | `backend pr` | `backend reviews` | `backend lease_token` | `backend lease_until` | `backend last_error` |

Each status column uses `ready`, `doing`, `review`, and `done`. Empty means the role
is not applicable. Role fields cannot alias one another. Common implementation
columns remain shared because they describe the same product requirement.

## Atomic role claim

Select at most one row whose selected role status is exactly `ready`. In one atomic
connector operation, require that value, set only the selected role status to
`doing`, and set only that role's fresh lease token and expiry. Never use another
role's queue columns as claim evidence.

Locate the first eligible physical row by reading only the selected role's status
column. After locating it, read and validate only that physical row. Canonicalize
only the selected row identity to a trimmed, non-empty, control-character-free
string. Unrelated row content and identities are outside the current tick and must
not be read or globally validated.

Bind the selected physical row number to its fresh lease in the connector's local
claim locator before mutation. Completion and controlled-error writeback resolve
the row only through that lease-bound locator, then read and validate only the same
physical row. A missing or mismatched locator stops without scanning the sheet.

The raw claimed row is normalized to `iole.claimed-row.v1`. Its immutable digest
includes the `source-id` command's connector-family/spreadsheet/sheet identity, row
identity, role, design input, page data, and the selected latest review. It excludes
status, leases, errors, and PR URLs. Callers must not hand-build `source_id`; the
command's canonical hashing prevents equal row numbers and content from separate
documents from sharing a job, branch, or recovery state.

Use `branch-name` to derive
`codex/iole-<source-digest-12>-<role>-<row-id-digest-12>`. Review number is
deliberately absent so initial implementation, retries, and every numbered review
reuse one branch and PR.

An initial implementation has both an empty reviews cell and an empty role PR
column. A revision has both a latest numbered review and an existing role PR URL.
Reject either half-populated combination before worker dispatch.

Before building a worker job or terminal intent, recompute that digest from the
claim content and reject any mismatch. A persisted claim is evidence only when its
canonical immutable content still matches its frozen digest.

## Numbered review cell

The selected role reviews cell is append-only. Each non-empty physical line must
match a positive number, `.`, `)`, or `、`, and one non-empty opinion. Numbers must
be strictly increasing in physical order. The greatest number is the latest review.

Examples:

```text
1. 首页卡片圆角错误
2) 按钮点击没有跳转
3、空状态缺少提示
```

An empty cell maps to `latest_review=null` and `mode=implement`. A non-empty cell
maps only its greatest numbered opinion and `mode=revise`. The status transition
acts as the review cursor: after a worker returns the role to `review`, the reviewer
must append exactly one new authoritative opinion before setting the role to
`ready` again.

## Worker routing

IOLE never passes raw workbook status or column names to a worker. Bind `client`
only to `worker_skill_name=icp` and its fixed home-relative ICP path. Resolve every other role
from its external `worker_skill_name` and home-expanded `worker_skill` path; require both
or neither. Reject scheduling and stop before claim when the selected role has no
configured worker. `role=client` produces `icp.external-page-job.v2`. Non-client
roles load only their mapped Skill and require that Skill's declared job adapter;
they never fall back to ICP.

## PR and terminal writeback

The role PR column is the only PR source and destination for that role. A populated
HTTP or HTTPS URL must resolve to the current repository and is reused for review
repair only while its MR is open and its source branch exists. A merged or closed
MR, or a missing source branch, requires `pr-recovery-plan`: inspect the original
task and latest review from its exact fetched `origin/dev` revision. Create a
replacement PR only when verified changes exist; otherwise retain the old PR URL
and return to `review`. The deterministic recovery branch binds the old PR URL and
latest review number so retries cannot create duplicate replacement PRs.
`build-review-writeback` returns immutable `guard_columns` and the expected
row digest. Select those column values from the persisted raw claimed row and pass
them as `expected_values` to the connector. After verified push and PR creation or
reuse, one connector lock must require every expected value plus the same role
`doing` status and lease, then set only its PR column and status `review`. Any
immutable value drift stops without writeback. Successful completion also clears
that role's lease fields and `last_error`.

Completion is replay-safe after a lost connector response: reconstruct the same
ack only when all non-output guard values still match, status and PR already equal
the intended terminal values, and lease/error fields are clear.

On a controlled failure, `build-error-writeback` produces a bounded
`machine-code: controlled detail` intent. The detail is one printable line and the
combined value is at most 129 characters. `record_claim_error` requires the same
immutable values, `doing` status, and lease, then updates only the selected role's
`last_error`; it retains the active claim for recovery. A new successful claim
clears a stale role error. Error intents also require the orchestrator to notify
the user immediately and stop the current run after recording the error; recovery
resumes only on a later run. A visual or worker failure must never remain silent
while more repair work continues.

IOLE never marks a role `done`. Review approval and merge own `review -> done`.
Client and backend role transitions may proceed independently on the same physical
row because their queue and lease columns are independent.
