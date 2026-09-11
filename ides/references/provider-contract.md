# Provider contract

Use this contract when selecting a Google Sheets MCP. Tool names may differ; behavior may not.

## Required read behavior

The provider must return:

- stable spreadsheet and sheet identity;
- exact header values;
- row numbers or another stable row locator;
- all cell values for each candidate row.

Normalize the read result before passing it to `scripts/select_task.py`.

## Required atomic claim behavior

The provider must expose either:

1. a compare-and-set operation for one row's status and claim token; or
2. a server-side `claim_task` operation that selects and updates within one lock or transaction.

The atomic operation must accept the expected status, write `doing`, attach a unique claim token, and return whether this execution won the claim. A Google Apps Script implementation may use `LockService` around re-read, comparison, and update. An MCP server may use an equivalent provider-side lock or transaction.

These are invalid substitutes:

- read status, then unconditionally write `doing`;
- batch multiple writes without an expected-value condition;
- write a token and read it back without a lock or compare-and-set guarantee;
- rely on the model to avoid concurrent access.

On conflict, return a distinct conflict result without mutating the row.

## Required conditional completion behavior

The provider must update the final fields only when both the current status is `doing` and the stored claim token belongs to this execution. The update must write `dev_wait_pr_reviewed` and the PR URL together.

Use an idempotency key for retries. Repeating the same completion request must return the same completed result without changing another row.

## Capability gate

Before reading task data, inspect the MCP schemas and prove the required atomic behavior from the tool contract. If that proof is absent, stop with `google_sheets_atomic_claim_unavailable`. Do not infer atomicity from generic update or batch-update names.
