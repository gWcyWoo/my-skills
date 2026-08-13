# IOLE flow queue contract v2

## Identity and discovery

Use the mapped `标题` as the only external page identity. Treat `交互描述` as natural
language, not as a punctuation-sensitive authoring API. The model must identify
semantically clear page, modal, and navigation targets, then write the deterministic
`→「职业信息页」` representation only into its normalized copy before calling
`extract-refs`. `按“客服弹窗”实现` and `跳转到反馈页面，按“反馈”实现` therefore resolve to
candidate titles `客服弹窗` and `反馈`; ordinary quoted labels, messages, and protocol
names do not become dependencies without matching action semantics. Never require
the Sheet author to change quotation marks or add parser syntax. Do not require,
read, compare, or validate a page number. Keep the design URL in the referenced
row; do not copy it into interaction prose.

Start with `inspect_ready_flow_root`, semantically normalize the root outside the
repository, then run `extract-refs` on that normalized copy. Read only the inferred
exact candidate titles with `inspect_flow_rows`. Continue only when each candidate
resolves to exactly one normalized Sheet title, and use those exact returned titles
in every deterministic input. Repeat semantic normalization and extraction until
the reachable graph closes. Normalize titles with Unicode NFC plus surrounding-
whitespace trimming. Ambiguous, missing, or duplicate titles fail before claim;
punctuation differences alone never fail. Scanning the title column to locate
candidate titles is allowed; validating unrelated row contents is not.

After discovery, derive deterministic opaque page keys from normalized titles for
ICP state, DAG nodes, and member digests. These keys are internal output only: the
document author never supplies or sees them as a required input.

Classify each reachable page before claim:

- `modify`: code or design work is required; include it in the flow.
- `navigate-only`: navigation targets an already-satisfied page; exclude it from
  claim, status changes, worker nodes, and terminal writeback.

If a `review` or `done` page must change, return `needs-reopen` and require a user
to set it to `ready`. Never reopen it silently. If any member is already `doing`,
block without mutation. Non-empty member PRs must be empty or all identical;
different PRs are `blocked/pr-conflict`.

## Claim and expansion

Call `claim_flow_rows` once with every `modify` identity, one raw guard snapshot, one
deterministic `flow_id`, and one lease duration. Under the connector's host-wide
lock, require every row to remain `ready`; then update every member to `doing` with
the same lease token and expiry in one Google Sheets `values.batchUpdate`. If any
member is missing, duplicated, changed, or not ready, mutate no member.

The guard snapshot must cover every member, include its inspected PR value, and
exclude status, lease, and error fields. Persist its per-member digests in the
locator and require the exact same values on retries. Expansion binds the new
members' inspected guards and appends them to the flow snapshot. Controlled errors
and completion require the resulting complete snapshot. During lost terminal-
response reconstruction, only the PR guard is replaced by the intended terminal
PR; every other guard must still match.

Persist the returned flow locator and raw rows outside the repository. The locator
binds member identities, immutable-guard digests, lease token, lease expiry, and a
prepared/claimed phase. If the locator was prepared but the remote batch did not
mutate any row, a retry replays the same batch. If the remote batch succeeded but
its response was lost, a retry reconstructs only when every located row is
`doing` under that exact lease and the supplied guards match the persisted digests.
Mixed remote states fail closed.

If analysis later discovers another changed child, stop before editing it and call
`expand_flow_claim`. Require all current members to retain the shared lease and all
new members to be `ready`. Persist them and their guard digests as a pending
expansion before the batch update, then commit them to locator membership only
after a successful acknowledgement or a fully matching lost-response read. A
pre-write failure is safely replayable; partial state fails closed.

## Terminal transitions

Keep every member `doing` throughout implementation. Partial node success never
writes `review`. On a controlled failure, call `record_flow_error` so every active
member retains `doing` and the shared lease while receiving the same bounded error.

After ICP verification and one PR succeed, call `complete_flow_rows` with every
member's immutable guards. Under one lock, require every row to remain `doing` with
the shared lease and unchanged guards, then set the same PR URL and `review` status
on every member and clear all leases/errors in one batch. One mismatch produces
zero terminal mutation.

Reconstruct a lost completion response only when every member has the intended PR,
`review`, cleared lease/error fields, and matching immutable guards. IOLE never
writes `done`; review and merge own that transition.

## Atomicity boundary

Google Sheets flow operations are all-or-none relative to schedulers using this
connector on the same Mac: one host-wide lock covers read, guard, and batch write.
Google Sheets does not provide server-side compare-and-set against external editors.
Therefore always perform guarded reads and post-write acknowledgement, block on
drift, and never run another host against the same queue. Microsoft Excel flow mode
is blocked until an adapter provides the same operations and guarantees; do not
silently downgrade to single-row processing.

Preserve every v1 locator and claim. Resume v1 work with v1 tools; create only new
flows through v2.
