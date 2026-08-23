# Extract stage

## Outcome

Convert every expected Lanhu design into trustworthy structured data under `<project>/.icp/extract/<design-name>/`. Each result combines an image-first semantic hierarchy, lossless source facts, exact source bindings, targeted repair evidence, and a binary semantic review.

`UI补充描述` has one role in this stage: help the model understand the rendered
design and choose correct visual-semantic Block boundaries, names, and grouping.
It cannot add, delete, replace, or override design data. A missing value is exact
JSON `null`. The Lanhu JSON remains the sole authority for every exact design fact.

There is no score or tolerance in this stage:

```text
all_source_nodes = mapped ⊎ absorbed ⊎ non_rendering
unresolved = ∅
duplicate_bindings = ∅
synthetic_source_ids = ∅
every semantic leaf is source-reachable
every JSON source node is reverse-reviewed against its exact assigned Block
all Block members plus the non-rendering set reconstruct the complete design JSON
every independent source subtree remains an independent semantic group when required
source parent-child relations agree with the semantic hierarchy
every exported source field resolves to one hashed local asset
every small unexported icon component with no nested export resolves to one exact hashed reference crop
reference pixels = logical artboard × one exact uniform scale
every expected design is complete
```

The model owns semantic interpretation and classification. The scripts own Lanhu acquisition, exact source facts, hashes, inventories, state transitions, coverage, and completion proofs. Never copy a model-authored number into source facts or treat source-layer grouping as semantic truth.

## Runtime layout

```text
.icp/extract/
├── run-manifest.json
├── checklist.json
├── index.json
├── run-result.json
└── <design-name>/
    ├── source/design.json
    ├── source/reference.png
    ├── source/assets/...
    ├── source-manifest.json
    ├── source-facts.json
    ├── asset-index.json
    ├── semantic-context.json
    ├── semantic-authoring.input.json
    ├── state.json
    ├── semantic-draft.input.json
    ├── semantic-draft.json
    ├── bindings.input.json
    ├── bindings.json
    ├── coverage.json
    ├── repair-packets/revision-NNNN/*.json
    ├── semantic-review.input.json
    ├── semantic-review.json
    ├── semantic-blocks.json
    ├── semantic-repair.json
    ├── revisions/*.json
    └── stage-result.json
```

For an IOLE run, the complete source bundle is frozen once at
`.icp/source/source-bundle.json`; the extract manifest binds each design to its
member title, component contract digest, change scope, and exact same-row
`UI补充描述`. Later stages must reuse this artifact rather than make another copy.

Files ending in `.input.json` are model work products. Canonical files without `.input` have passed their corresponding gate. A sanitized design-name collision between different design identities fails visibly; never append an implicit suffix.

## 1. Freeze the full design set

Create a run input containing every requested URL, exactly once and in the
requested order. Copy the exact same-row `UI补充描述`; use `null` when absent:

```json
{
  "schema": "icp.extract.run-input.v2",
  "designs": [
    {"design_url": "<lanhu-url-1>", "ui_supplement": "<exact text or null>"},
    {"design_url": "<lanhu-url-2>", "ui_supplement": null}
  ]
}
```

Begin the run:

```bash
python3 <icp-skill>/extract/scripts/extract.py begin-run \
  --project-root "<project>" \
  --urls-file "<run-input.json>"
```

This freezes the exact batch. A later URL-set change is input drift, not a resume.
It also creates the complete input-derived Stage-1 checklist and records only
`run.freeze` as completed. Each design has dependent `prepare`, `semantic-draft`,
`bindings`, `semantic-review`, and `verify` nodes; `run.verify` depends on every
design verify node.

Every Stage-1 command is one serialized transaction. A retry with the same
committed draft, complete bindings, or passing review repairs a missing checklist
receipt without creating another revision. Incomplete bindings remain
`repair_required` and never complete the bindings receipt. The stage lock has no
artifact representation and therefore cannot create `.icp` output for rejected
input.

For IOLE, do not create a second run-input projection. Pass its complete bundle
directly to Stage 1 once:

```bash
python3 <icp-skill>/extract/scripts/extract.py begin-run \
  --project-root "<project>" \
  --source-bundle "<iole-flow-source-bundle-v2.json>"
```

## 2. Acquire and freeze each design

Stage 1 requires Pillow for exact reference-image dimensions and source-frame
crop derivation. Run acquisition, preparation, and verification with an
environment that can import Pillow; a missing dependency is a hard
`missing_dependency` failure, never permission to skip crop evidence. The
stage regression command is CWD-independent and pins the runtime dependency:

```bash
ICP_SKILL="${HOME}/.agents/skills/icp"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${HOME}/.agents/skills" \
uv run --with 'pillow>=10,<13' python -m unittest discover -v \
  -s "${ICP_SKILL}/extract/tests"
```

For every URL in `run-manifest.json`, acquire complete materials into a temporary directory:

```bash
python3 <icp-skill>/extract/scripts/acquire.py \
  --url "<lanhu-url>" \
  --output-dir "<temporary-acquisition-dir>"
```

The acquisition script resolves the already configured Lanhu cookie before reporting `missing_cookie`. It retrieves metadata, the machine-readable design, the full cover, and every discovered exported PNG/SVG slice. Any missing slice, identity mismatch, invalid cover size, or incomplete hash set fails the whole acquisition atomically.

Freeze only the acquisition contract, never loose paths:

```bash
python3 <icp-skill>/extract/scripts/extract.py prepare \
  --project-root "<project>" \
  --acquisition-dir "<temporary-acquisition-dir>" \
  --design-url "<lanhu-url>"
```

Use the returned `design_name` for all remaining commands. `prepare` revalidates every acquisition byte and identity, then copies immutable evidence to `.icp/extract/<design-name>/`. It also creates `asset-index.json`, where every export URL is joined to its exact source node field, local path, size, and hash. `source-manifest.json.reference` freezes the reference PNG size, logical artboard size, and exact uniform scale. For a small icon-sized symbol instance with no text or nested exported asset, `prepare` deterministically crops its exact source frame from the frozen reference and records the crop coordinates, reference hash, bytes, and source-node relation in the same asset index. Byte-identical input resumes; drift never overwrites evidence.

These are hard referential-integrity rules, not convenience metadata:

```text
source node + source field → remote export URL → asset_id → local file + hash
logical source coordinate × logical_scale → reference image pixel coordinate
```

`logical_scale` is the exact rational value frozen by acquisition (for example,
`2` or `3/2`). Crop derivation must parse that rational exactly and apply outward
floor/ceiling rounding; decimal-only or floating-point parsing is not valid.

No exported source field, local asset, semantic block, source node, or reference mapping may be dangling or inferred from a filename.

## 3. Author the image-first semantic draft

Inspect `<design-dir>/source/reference.png` together with the generated
`semantic-authoring.input.json`. Use its `ui_supplement` only to assist visual
grouping. Do not read `source-facts.json` until the semantic draft is frozen;
source-layer grouping must not anchor semantic interpretation, and description
text must not manufacture design facts.

Copy [templates/semantic-draft.input.json](templates/semantic-draft.input.json) to `<design-dir>/semantic-draft.input.json` and replace every placeholder. Every block needs a stable local ID, role and basis, hierarchy, qualitative background/border/spacing, content/composition, and evidenced relations. Do not include source IDs, frames, pixel values, or other numeric source facts.

```bash
python3 <icp-skill>/extract/scripts/extract.py record-draft \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --draft "<design-dir>/semantic-draft.input.json"
```

The script freezes the draft and generates one unresolved assignment for every source node.

## 4. Bind every source node and repair locally

Now read `source-facts.json`. For a small design, edit the generated `bindings.input.json` directly. For a large design, author a compact exact partition plan so the script performs the mechanical node expansion:

```json
{
  "schema": "icp.extract.binding-plan.v1",
  "source_manifest_sha256": "<from-state>",
  "semantic_draft_sha256": "<from-state>",
  "rules": [
    {
      "source_node_ids": ["<individual-node>"],
      "source_subtree_roots": ["<whole-subtree-root>"],
      "status": "mapped",
      "block_id": "<semantic-block>",
      "rationale": "<why this exact source set belongs here>"
    }
  ]
}
```

```bash
python3 <icp-skill>/extract/scripts/extract.py expand-bindings \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --plan "<design-dir>/binding-plan.json"
```

Rules must form an exact partition of all source nodes. Unknown IDs, overlapping explicit nodes/subtrees, or omitted nodes fail; the script preserves source order and derives the required geometry basis. The plan does not infer semantics—the model still chooses every node or subtree boundary and gives its rationale.

Every assignment also freezes one `content_role`. Rendering nodes use exactly one
of `static_visual|static_copy|dynamic_content|platform_element`.
`non_rendering` uses `not_applicable`; `unresolved` uses `unresolved`. This role is
not a business rule: it distinguishes design-owned visuals/copy from runtime data
and platform-owned controls so later stages cannot mistake a screenshot sample
value for validation or other business behavior.

Whether authored directly or expanded, every assignment selects exactly one status:

- `mapped`: the node independently represents the block.
- `absorbed`: the node contributes to a larger block.
- `non_rendering`: the node has no rendered semantic contribution; use `block_id: null`.
- `unresolved`: evidence is insufficient; use `block_id: null` and enter repair.

For rendering nodes choose `frame`, `real_frame`, or `combined`; these refer exactly to source payload fields `frame`, `realFrame`, and `combinedFrame`. A basis whose field is absent fails. Rotated nodes with `realFrame` require `real_frame` or `combined`. Non-rendering and unresolved nodes use `not_applicable`. Every semantic leaf must receive at least one mapped or absorbed source node; parent containers may be reachable through their children.

After exact assignment coverage, the script deterministically projects source
containment into the semantic Block tree before any model-authored review is
accepted. Visual semantics may merge several source nodes into one Block or split
one source group into nested Blocks. Along every rendered source ancestry path,
however, the child assignment must remain in the same Block or descend from the
parent assignment's Block. A child projected back into an ancestor Block or
across sibling Blocks is a structural contradiction, not a review judgment.
Non-rendering source containers are collapsed to the nearest rendered ancestor,
while the complete traversed source path and sibling position remain frozen.

`record-bindings` scans the complete source order and writes every contradiction
to `coverage.json.topology_projection.issues` in one pass. It also writes one
`topology_repair_packets` entry per failed child containing both complete source
nodes, both Blocks, exact paths, and allowed semantic repairs. Any issue keeps the
stage in `repair_required`; `semantic-review.input.json` is not generated. After
the model repairs the draft or bindings, rerun the complete binding projection
from the first source node. Only an issue-free projection may enter semantic
review, and the same projection is frozen in `semantic-blocks.json` for later
stages.

```bash
python3 <icp-skill>/extract/scripts/extract.py record-bindings \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --bindings "<design-dir>/bindings.input.json"
```

When state becomes `repair_required`, read `coverage.json` and only its referenced repair packets first. Correct a classification directly, or revise the semantic draft if a block must split, merge, or be added. Re-record the full bindings until state is `awaiting_semantic_review`; never replace exact coverage with a percentage.

## 5. Perform the binary semantic review

Reopen the rendered reference, reread the exact injected `semantic_context`, and
edit `semantic-review.input.json`. Confirm that the UI supplement improved only
visual-semantic grouping and did not override the source JSON. The script supplies
two mandatory views of the same frozen result:

1. Block-first evidence: every Block's exact mapped/absorbed source IDs plus every non-rendering node and rationale.
2. JSON-first reverse evidence: every complete source node payload, its complete parent and children, its current assignment, and the complete assigned Block.

Review every Block and then traverse every JSON node in exact source order. For each source node, independently decide whether its assigned Block and `content_role` are semantically correct, whether the node or subtree needs its own semantic group, and whether the source parent-child relation is preserved by the Block hierarchy. This is not a node-count check: a node that exists but is swallowed by the wrong Block must fail. Review role, hierarchy, appearance, grouping, source binding, content role, relations, reading order, omissions, and non-rendering classifications. Replace every `TODO`; placeholders cannot pass.

The JSON hierarchy is a second semantic evidence channel, never the first author of
Blocks. Keep the frozen image-first Block hypothesis, then explicitly reconcile
every JSON node with children against that visual result. For each source group,
record exactly one relation:

- `matches_block`: the source group and one visual Block have the same semantic boundary;
- `contains_blocks`: the source group is a broader container for multiple visual Blocks;
- `part_of_block`: the source group is only one part of a larger visual Block;
- `technical_group`: the grouping exists for editing, clipping, export, layout, or another non-semantic design-tool reason.

The review projection freezes the complete source group, parent, children, node
names/types, and ordered subtree Block IDs. The reviewer must cite separate visual
and JSON evidence and explain how they reconcile. JSON grouping may challenge and
repair the visual hypothesis, but it cannot automatically replace it. Missing a
group, accepting an unexplained mismatch, or declaring `contains_blocks` without
multiple subtree Blocks fails. After any mismatch, repair the draft/bindings and
repeat the complete visual/JSON reconciliation from the first source node.

`decision: pass` is valid only when every boolean is true and every issue array is empty.

```bash
python3 <icp-skill>/extract/scripts/extract.py record-review \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --review "<design-dir>/semantic-review.input.json"
```

A `revise` decision returns to `repair_required` with `semantic-repair.json`. Every failed source node is returned as a reverse repair packet containing the original JSON node, parent and children, current binding, complete assigned Block, and allowed repair classes. Give those exact packets back to the semantic model, revise the draft, and regenerate the complete bindings.

Then discard the previous review result and regenerate a fresh reverse projection. Restart the review from the first JSON node and review the complete ordered inventory, including nodes that passed in the preceding revision. Repeat `draft -> bindings -> full reverse review -> repair` until one fresh review has every Block boolean, every source-node boolean, and every cross-Block boolean true with every issue array empty. Exact node-count coverage, partial re-review, or a prior revision's pass cannot terminate this loop.

One reverse-review round is an exhaustive read-only scan. Freeze its semantic draft and bindings, inspect every source node before applying any repair, and report every problem found in the same review. Never stop at the first issue or modify bindings while the scan is still in progress. Apply the complete repair batch only after the last node, then start a new full round against the newly frozen artifacts.

## 6. Verify every design and the batch

For each design:

```bash
python3 <icp-skill>/extract/scripts/extract.py verify \
  --project-root "<project>" \
  --design-name "<design-name>"
```

Then prove no expected URL was omitted:

```bash
python3 <icp-skill>/extract/scripts/extract.py verify-run \
  --project-root "<project>"
```

Only exit code zero from `verify-run` makes a multi-design extract deliverable. Report the absolute `run-result.json` path and per-design `stage-result.json` paths, then stop before component design.

`verify-run` also requires every checklist node before `run.verify`. If a node is
missing or invalidated by changed upstream evidence, it returns the earliest
`resume_from_node` and all causally downstream `revalidate_nodes`. Complete that
node and rerun its dependent commands; never carry forward a prior downstream pass.

On a passing review the script writes `semantic-blocks.json`. Every Block embeds
its complete ordered source-node records, assignments, content roles, and asset
evidence. Non-rendering source nodes remain in one explicit top-level set. The
artifact also preserves the source document outside the artboard; rebuilding the
artboard from the Block members and restoring it into that envelope must reproduce
the complete parsed design JSON exactly. Stage 2 consumes this artifact directly.

`stage-result.json` must expose `source_asset_relations_resolvable` and `reference_coordinate_mapping_exact` as passing gates, and must link directly to the frozen asset index and reference mapping. The second stage may materialize a joined view, but it must not repair or guess any first-stage relation.

## Fail closed

- `batch_input_drift`, `input_drift`, or `acquisition_drift`: preserve the existing run; do not overwrite it.
- `source_drift` or `stage_drift`: identify the changed artifact; never repair hashes manually.
- `asset_download_failed` or `acquisition_incomplete`: the design was not acquired.
- `asset_relation_missing` or `invalid_asset_relation`: at least one source export and local asset cannot be joined exactly.
- `reference_size_mismatch` or `invalid_reference`: source coordinates and the full reference image do not share one valid exact scale.
- `unbound_semantic_leaf`: the semantic structure contains a block with no source reachability.
- `false_semantic_pass`: a pass decision contradicts at least one failed JSON-node or Block review.
- `stage_drift`: the semantic Blocks no longer reconstruct the complete frozen design JSON.
- `repair_required`: continue the bounded repair loop; it is not completion.
- `batch_incomplete`: at least one frozen URL lacks a verified complete design.
