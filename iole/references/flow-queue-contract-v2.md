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
- `context`: its exact mapped business/design data is required to understand the
  flow, but this run does not change or claim the row.
- `navigate-only`: navigation targets an already-satisfied page; exclude it from
  claim, status changes, worker nodes, and terminal writeback.

Only `modify` rows must have the selected role status `ready`. Preserve an empty or
otherwise non-applicable selected-role status on `context` and `navigate-only`
rows; queue state is not business evidence and must not block read-only context.

If a `review` or `done` page must change, return `needs-reopen` and require a user
to set it to `ready`. Never reopen it silently. If any member is already `doing`,
block without mutation. Non-empty member PRs must be empty or all identical;
different PRs are `blocked/pr-conflict`.

`mr` is a closed delivery mode: `0` leaves verified changes uncommitted, `1`
commits and pushes the current branch directly, and `2` creates or updates one MR.
It defaults to `0`. This choice does not change the terminal queue outcome: after
ICP and all tests pass, all claimed modify members move atomically to `review`.
Modes `0|1` preserve PR cells; mode `2` writes the common MR URL.

## ICP source bundle

Persist the exact connector rows as the raw-rows object described below. Create a
separate analysis document with no project, component, path, queue, requirement,
or acceptance decisions:

First call `inspect_title_catalog`. The analysis envelope is
`iole.source-analysis-input.v2`: for every included row it lists every
mapping-declared ICP business column in original order with the SHA-256 of the exact cell
string, exact-span `references`, exact-span `dismissals`, and `change_scope`.
References use unique IDs and one closed kind from
`navigation|modal|component|data|reference`. The accompanying
`iole.source-closure-review.v1` binds the analysis hash and title-catalog digest,
reviews every field, and passes the cross-row closure gate. An exact catalog-title
occurrence without a covering reference or dismissal is invalid. Semantic
references that do not quote a title still require an exact evidence span and a
unique catalog target. Legacy source-analysis v1 is not accepted.

Run:

```sh
python3 ~/.agents/skills/iole/scripts/iole_flow_contract_v2.py \
  build-source-bundle --raw-rows /absolute/raw-rows.json \
  --title-catalog /absolute/title-catalog.json \
  --analysis /absolute/source-analysis.json \
  --closure-review /absolute/source-closure-review.json \
  --mapping /absolute/role-mapping-v2.json > /absolute/source-bundle.json
```

Require `iole.flow-source-bundle.v2`. The complete inspected row remains in the
raw input evidence. The bundle declares one ordered `row_data_columns` set derived
from the selected mapping's ICP source fields; every member carries exactly that
set in `row_data`, one deterministic `iole.sheet-member-contract.v2` projection,
and the hash-bound `source_closure` used to prove membership completeness. For
every declared column, copy a non-empty string exactly and represent an exactly
empty value as JSON `null`. Missing declared columns and `""` placeholders are
invalid. Connector columns not declared as ICP inputs remain outside the handoff,
its digest, and its semantic reverse audit. Queue/PR/lease/error columns remain
IOLE orchestration evidence only. `design_refs` is an ordered,
deterministic projection of every URL in the exact design cell; the original cell
remains authoritative in `source_contract.design_ref`. `relations` contains the
closed directed title graph derived from the normalized interaction copies. Cycles
are valid source relationships. The bundle contains no component decisions,
project inventory, ownership paths, claim guards, leases, PRs, or error cells.

Pass the bundle unchanged to ICP. IOLE must not infer visual Blocks, components,
props, slots, variants, states, or events. Empty mapped business cells are valid:
ICP may infer visible semantics from verified designs or omit unsupported behavior,
but neither stage may invent an API or invisible interaction.

## Legacy execution input envelopes

The following `flow-analysis-input.v1`/`flow-plan-input.v3` envelope remains only
for existing execution/recovery paths. A new ICP component-design handoff uses the
source bundle above. Component decisions and ownership paths for a future new
execution path must come from ICP's verified component/implementation contracts,
not from IOLE source analysis.

`build-input` has two separate JSON inputs. Do not wrap the raw rows in a
`kind`/`rows` document. The raw-rows file is a JSON object whose keys are the
exact normalized member titles returned by the connector and whose values are
the complete, unchanged row objects returned for those titles:

```json
{
  "反馈": {
    "标题": "反馈",
    "Route": "feedback",
    "设计稿地址": "https://design.example/feedback",
    "UI补充描述": "",
    "交互描述": "",
    "接口描述": "",
    "UT": "",
    "IT": "",
    "E2E": "",
    "frontend status": "ready",
    "frontend pr": "",
    "frontend reviews": "",
    "frontend lease_token": "",
    "frontend lease_until": "",
    "frontend last_error": ""
  }
}
```

The field names above come from the selected `iole.role-mapping.v2`; a different
mapping means using that mapping's exact field names. The raw inspection file still
preserves every connector-returned column and value. `build-source-bundle` filters
that evidence to the mapping-declared `row_data_columns`, then changes only exact
`""` to JSON `null`. Additional unowned columns do not enter ICP or block closure.
For an aliased source such as
`页面路由`/`Route`, include
exactly the one alias that existed in the inspected row. The top-level key must
equal the row's mapped title after Unicode NFC and surrounding-whitespace
normalization; never repair the row by changing either value.

Generate `source_id` from the connector-returned spreadsheet identity and exact
sheet name; do not invent its digest:

```sh
python3 ~/.agents/skills/iole/scripts/iole_contract_v1.py \
  source-id --provider google-sheets \
  --spreadsheet-id '<connector spreadsheet identity>' \
  --sheet-name '<exact sheet name>'
```

The separate analysis file has this exact public shape:

```json
{
  "kind": "iole.flow-analysis-input.v1",
  "schema_version": 1,
  "source_id": "google-sheets:<64 lowercase hex characters from source-id>",
  "role": "client",
  "root_title": "反馈",
  "rows": [
    {
      "title": "反馈",
      "normalized_interaction": "",
      "change_scope": "modify",
      "allowed_paths": ["app/src/main/FeedbackScreen.kt"]
    }
  ],
  "component_analysis": {
    "inventory_source": "project-scan",
    "searched_paths": ["app/src/main"],
    "summary": "Inspected existing shared and feature-local components."
  },
  "component_plan": []
}
```

Every `rows` item has exactly `title`, `normalized_interaction`, `change_scope`,
and `allowed_paths`. `change_scope` is `modify` or `navigate-only`; paths are
non-empty, project-relative ownership scopes. `component_analysis` has exactly
the three fields shown, with at least one searched project-relative path. An
empty `component_plan` is valid. Each non-empty component decision has exactly:

```json
{
  "component_id": "shared-form-card",
  "name": "FormCard",
  "decision": "extend",
  "code_path": "app/src/main/ui/FormCard.kt",
  "allowed_paths": ["app/src/main/ui/FormCard.kt"],
  "consumers": ["反馈"],
  "evidence": "Existing shared component is the closest semantic match."
}
```

`decision` is one of `reuse`, `extend`, `create-shared`, or `create-local`.
Consumers are exact selected titles; `create-local` has exactly one consumer.
All paths are project-relative, `code_path` is included in `allowed_paths`, and
execution-node ownership scopes may not overlap. The analysis file contains no
Sheet-derived requirement, acceptance, design, status, PR, or review prose.

Run the lossless pair from absolute file paths:

```sh
python3 ~/.agents/skills/iole/scripts/iole_flow_contract_v2.py \
  build-input --raw-rows /absolute/raw-rows.json \
  --analysis /absolute/analysis.json \
  --mapping /absolute/role-mapping-v2.json > /absolute/flow-input.json
python3 ~/.agents/skills/iole/scripts/iole_flow_contract_v2.py \
  build-plan --input /absolute/flow-input.json \
  --raw-rows /absolute/raw-rows.json \
  --mapping /absolute/role-mapping-v2.json > /absolute/flow-plan.json
```

## Claim and expansion

Before `build-plan`, pass the exact raw inspected member rows and a separate
analysis document to `build-input` with the fixed role mapping. The analysis may
contain only page identity, normalized reference prose, change scope, allowed
paths, and component decisions; it must not author `requirement`, acceptance copy,
or other Sheet-derived job values. `build-input` copies every mapping-declared job
cell into `iole.sheet-member-contract.v1` without trimming or rewriting, preserves
empty sections, and produces `iole.flow-plan-input.v3`. Normalized interaction is
used only to construct the graph and never replaces the exact Sheet interaction.

`build-plan` requires those same raw rows and mapping again, then publishes
`iole.flow-plan.v3`; `build-job` publishes
`icp.external-flow-job.v5`. Both member and source-contract digests cover exact
values. ICP independently reconstructs derived fields and recomputes those digests
before compiling an immutable implementation contract. The main ICP session binds
every source clause to public behavior, acceptance cases, strict TDD slices, and
frozen design states before any worker dispatch. Missing, summarized, inconsistent,
or unbound content fails before implementation. V2 plan input and v3/v4 ICP jobs
are legacy recovery formats only.

Losslessness covers mapping-declared title, route, design reference, interaction,
requirement sections, and UT/IT/E2E sections. Queue status, PR, reviews, lease,
error, ignored columns, unrelated business cells, and other-role fields stay
outside ICP.

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

## User-directed release and restart

`release_flow_claim` is the only supported connector restart boundary for one v2
flow. IOLE may call it only after the user explicitly says `重新开始` for the exact
persisted flow. Pass its original flow ID, shared lease token, and complete bound
immutable guard snapshot.

Under the host-wide lock, require every member identity and guard to match the
locator. A member may still be `doing` under the exact old lease or may be partially
or fully reset toward `ready`, but it must not carry a different lease or a terminal
status. Restore all members in one batch to `ready`, clear only the selected role's
lease token, lease expiry, and error, and preserve its PR plus all business and
other-role columns. Then atomically move the active locator to a durable release
archive. Repeated calls for the same released lease reconstruct success; the next
claim for that flow must create a fresh lease.

On identity, guard, PR, terminal-state, or foreign-lease drift, mutate neither the
Sheet nor locator. An unattended tick never releases a claim. After release, IOLE
archives the failed ICP execution evidence and starts a fresh execution instead of
resuming a terminal failed DAG.

## Terminal transitions

Keep every member `doing` throughout implementation. Partial node success never
writes `review`. On a controlled failure, call `record_flow_error` so every active
member retains `doing` and the shared lease while receiving the same bounded error.

After ICP returns `icp.flow-handoff-result.v2`, run
`build-review-writeback --mr MR --icp-result` first, passing `--pr-url` only for
`mr=2`. It rejects wrong flow/member identity,
generic pass claims, invalid digests, and any required/covered clause difference.
After that gate and the delivery action required by `mr` succeeds, call
`complete_flow_rows` with every member's immutable guards. Under one lock, require
every row to remain `doing` with the shared lease and unchanged guards, then set
`review` on every member and clear all leases/errors in one batch. With `mr=0|1`,
pass a null PR intent and preserve each current PR cell; with `mr=2`, set the same
MR URL on every member. One mismatch produces zero terminal mutation.

Reconstruct a lost completion response only when every member has `review`,
cleared lease/error fields, matching immutable guards, and either the preserved PR
for `mr=0|1` or intended MR for `mr=2`. IOLE never
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
