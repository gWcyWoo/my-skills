# ICP external flow-job contract v4

`icp.external-flow-job.v4` is the persisted legacy lossless Sheet-contract
boundary. New IOLE work uses v5. IOLE originally derived v4 only through the deterministic
`build-input -> build-plan -> build-job` CLI path. Hand-written requirement
summaries are not a valid v4 source.
`build-plan` requires the same raw rows and mapping again and rejects a v3 input
whose exact source contracts do not match them.

Each member carries the normalized execution fields plus an exact
`source_contract`:

```json
{
  "kind": "iole.sheet-member-contract.v1",
  "schema_version": 1,
  "title": "exact mapped Sheet cell",
  "route": "exact mapped Sheet cell",
  "design_ref": "exact mapped Sheet cell",
  "interaction": "exact mapped Sheet cell",
  "requirement_sections": [
    {"label": "UI补充描述", "value": "exact mapped Sheet cell"}
  ],
  "acceptance_sections": [
    {"prefix": "UT", "value": "exact mapped Sheet cell, including empty"}
  ],
  "contract_digest": "sha256 of every preceding source-contract field"
}
```

Exact means no trimming, rewriting, translation, summarization, dropped empty
section, list parsing, or newline normalization. Normalized `title`, `route`, and
`design_ref`, composed `requirement`/`acceptance_criteria`, and copied
`interaction` are derived views only. ICP reconstructs every derived view from
`source_contract`, verifies its digest, and recomputes each complete member digest
before persisting or dispatching a node.

Queue status, PR, review, lease, error, ignored, and other-role cells remain IOLE
ownership and never enter ICP. Losslessness applies to every mapping-declared job
field, not scheduler-control or unrelated workbook data.

Every worker node emitted from v4 contains the unchanged member
`source_contract`. The worker prompt makes it authoritative and forbids replacing
it with prose such as `Sheet 给定`, `按给定文案`, or another summary. A missing,
changed, or inconsistent mapped value is `invalid-input` before worker dispatch.

`icp.external-flow-job.v3` and v4 remain readable only for persisted legacy flows.
New IOLE flows publish v5; never migrate a persisted v4 state in place.
