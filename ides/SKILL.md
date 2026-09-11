---
name: ides
description: 用 iDES 从 Google Sheets 按状态和优先级原子领取一条开发任务，TDD 实现、提 PR 并条件写回。
---

# iDES

Accept three inputs:

1. `source_url`: spreadsheet link.
2. `target_status`: status eligible for claiming.
3. `priority_order`: comma-separated priority values from highest to lowest.

Run the workflow below without processing more than one row.

## 1. Detect the provider

Run:

```bash
python3 scripts/detect_source.py "$source_url"
```

Continue only when `provider` is `google_sheets`. Stop on every unsupported or malformed source.

## 2. Establish the Google Sheets contract

Read [provider-contract.md](references/provider-contract.md). Inspect the available Google Sheets MCP tool schemas before reading or writing data.

Require an atomic conditional status update or a server-side atomic claim operation. Ordinary read followed by unconditional cell update is invalid. Stop and report the missing capability when the MCP cannot guarantee that only one claimant changes the row from `target_status` to `doing`.

## 3. Map only the relevant columns

Inspect the header row and map these semantic roles to exact sheet headers:

- `status`
- `priority`
- `developer_requirement`
- `design`
- `ut`
- `it`
- `pr_url` for final writeback

Do not require any other fixed headers. Preserve and return the entire selected row. Stop and ask for a mapping only when a required role is missing or ambiguous.

## 4. Select and atomically claim one row

Read the sheet through its MCP and normalize the returned rows to:

```json
{"rows":[{"row_number":2,"values":{"exact header":"cell value"}}]}
```

Run `scripts/select_task.py` with the exact mapped status and priority headers. Treat `priority_order` as highest-to-lowest; use ascending row number as the deterministic tie-breaker.

Attempt one conditional transition on the selected row:

```text
expected status = target_status
new status      = doing
claim token     = unique stable token for this execution
```

The provider must apply the comparison and update atomically. If the comparison fails, re-read, re-select, and retry another candidate. Do not inspect source code or start implementation until the provider confirms the claim and returns the complete claimed row plus its stable locator and claim token.

## 5. Establish the implementation target

Treat `developer_requirement` and `design` as the goal. Treat the listed `ut` and `it` cases as mandatory minimum behavior, not a complete test plan.

Use repository information from the row when present; otherwise use the current repository. Read its project instructions before source work. Stop if the repository or base branch cannot be identified safely.

Add tests only for uncovered required behavior or a concrete regression risk. Preserve every listed UT/IT case and keep scope limited to the claimed row.

## 6. Implement with TDD

Work in vertical slices:

1. Write one observable behavior test.
2. Run it and record the expected RED result.
3. Add the smallest implementation that makes it GREEN.
4. Run the focused test.
5. Repeat for every mandatory UT/IT case and every required supplemental case.
6. Refactor only while GREEN, rerunning tests after each refactor.

Use public interfaces in tests. Do not replace real integration boundaries with mocks unless the repository's own test policy requires it.

## 7. Verify and create the PR

Run the mandatory UT/IT cases and the repository's required checks. Reuse current passing results when the same code and environment are covered; do not rerun overlapping suites just to produce another green result. Do not create a PR while any required test is failing.

Review the diff for claimed-row scope, create a branch, commit, push, and create a pull request against the identified base branch. Include the requirement summary and exact test commands/results in the PR body. Capture the canonical PR URL.

## 8. Complete the row conditionally

After the PR exists, use the stable row locator and claim token to perform one conditional writeback:

```text
expected status = doing
expected token  = this execution's claim token
new status      = dev_wait_pr_reviewed
pr_url          = canonical PR URL
```

If writeback fails, keep the row at `doing`, return the existing PR URL and the writeback error, and retry only the same idempotent writeback. Never create a second PR.

Return the PR URL only after reporting the final row status. On any post-claim failure, leave `doing` intact and report the row locator, claim token, failed gate, and recovery action.
