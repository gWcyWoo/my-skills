# Extract stage

## Outcome

Convert every expected Lanhu design into trustworthy structured data under `<project>/.icp/extract/<design-name>/`. Each result combines an image-first semantic hierarchy, lossless source facts, exact source bindings, targeted repair evidence, and a binary semantic review.

There is no score or tolerance in this stage:

```text
all_source_nodes = mapped ⊎ absorbed ⊎ non_rendering
unresolved = ∅
duplicate_bindings = ∅
synthetic_source_ids = ∅
every semantic leaf is source-reachable
every exported source field resolves to one hashed local asset
reference pixels = logical artboard × one exact uniform scale
every expected design is complete
```

The model owns semantic interpretation and classification. The scripts own Lanhu acquisition, exact source facts, hashes, inventories, state transitions, coverage, and completion proofs. Never copy a model-authored number into source facts or treat source-layer grouping as semantic truth.

## Runtime layout

```text
.icp/extract/
├── run-manifest.json
├── index.json
├── run-result.json
└── <design-name>/
    ├── source/design.json
    ├── source/reference.png
    ├── source/assets/...
    ├── source-manifest.json
    ├── source-facts.json
    ├── asset-index.json
    ├── state.json
    ├── semantic-draft.input.json
    ├── semantic-draft.json
    ├── bindings.input.json
    ├── bindings.json
    ├── coverage.json
    ├── repair-packets/revision-NNNN/*.json
    ├── semantic-review.input.json
    ├── semantic-review.json
    ├── semantic-repair.json
    ├── revisions/*.json
    └── stage-result.json
```

Files ending in `.input.json` are model work products. Canonical files without `.input` have passed their corresponding gate. A sanitized design-name collision between different design identities fails visibly; never append an implicit suffix.

## 1. Freeze the full design set

Create a run input containing every requested URL, exactly once and in the requested order:

```json
{
  "schema": "icp.extract.run-input.v1",
  "design_urls": ["<lanhu-url-1>", "<lanhu-url-2>"]
}
```

Begin the run:

```bash
python3 <icp-skill>/extract/scripts/extract.py begin-run \
  --project-root "<project>" \
  --urls-file "<run-input.json>"
```

This freezes the exact batch. A later URL-set change is input drift, not a resume.

## 2. Acquire and freeze each design

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

Use the returned `design_name` for all remaining commands. `prepare` revalidates every acquisition byte and identity, then copies immutable evidence to `.icp/extract/<design-name>/`. It also creates `asset-index.json`, where every export URL is joined to its exact source node field, local path, size, and hash. `source-manifest.json.reference` freezes the reference PNG size, logical artboard size, and exact uniform scale. Byte-identical input resumes; drift never overwrites evidence.

These are hard referential-integrity rules, not convenience metadata:

```text
source node + source field → remote export URL → asset_id → local file + hash
logical source coordinate × logical_scale → reference image pixel coordinate
```

No exported source field, local asset, semantic block, source node, or reference mapping may be dangling or inferred from a filename.

## 3. Author the image-first semantic draft

Inspect only `<design-dir>/source/reference.png` first. Do not read `source-facts.json` until the semantic draft is frozen; source-layer grouping must not anchor semantic interpretation.

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

Whether authored directly or expanded, every assignment selects exactly one status:

- `mapped`: the node independently represents the block.
- `absorbed`: the node contributes to a larger block.
- `non_rendering`: the node has no rendered semantic contribution; use `block_id: null`.
- `unresolved`: evidence is insufficient; use `block_id: null` and enter repair.

For rendering nodes choose `frame`, `real_frame`, or `combined`; these refer exactly to source payload fields `frame`, `realFrame`, and `combinedFrame`. A basis whose field is absent fails. Rotated nodes with `realFrame` require `real_frame` or `combined`. Non-rendering and unresolved nodes use `not_applicable`. Every semantic leaf must receive at least one mapped or absorbed source node; parent containers may be reachable through their children.

```bash
python3 <icp-skill>/extract/scripts/extract.py record-bindings \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --bindings "<design-dir>/bindings.input.json"
```

When state becomes `repair_required`, read `coverage.json` and only its referenced repair packets first. Correct a classification directly, or revise the semantic draft if a block must split, merge, or be added. Re-record the full bindings until state is `awaiting_semantic_review`; never replace exact coverage with a percentage.

## 5. Perform the binary semantic review

Reopen the rendered reference and edit `semantic-review.input.json`. The script supplies every block's exact mapped/absorbed source IDs plus every non-rendering node and rationale. Review role, hierarchy, appearance, grouping, source binding, relations, reading order, omissions, and non-rendering classifications. Replace every `TODO`; placeholders cannot pass.

`decision: pass` is valid only when every boolean is true and every issue array is empty.

```bash
python3 <icp-skill>/extract/scripts/extract.py record-review \
  --project-root "<project>" \
  --design-name "<design-name>" \
  --review "<design-dir>/semantic-review.input.json"
```

A `revise` decision returns to `repair_required` with `semantic-repair.json`. Revise the draft, regenerate complete bindings, and review again.

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

`stage-result.json` must expose `source_asset_relations_resolvable` and `reference_coordinate_mapping_exact` as passing gates, and must link directly to the frozen asset index and reference mapping. The second stage may materialize a joined view, but it must not repair or guess any first-stage relation.

## Fail closed

- `batch_input_drift`, `input_drift`, or `acquisition_drift`: preserve the existing run; do not overwrite it.
- `source_drift` or `stage_drift`: identify the changed artifact; never repair hashes manually.
- `asset_download_failed` or `acquisition_incomplete`: the design was not acquired.
- `asset_relation_missing` or `invalid_asset_relation`: at least one source export and local asset cannot be joined exactly.
- `reference_size_mismatch` or `invalid_reference`: source coordinates and the full reference image do not share one valid exact scale.
- `unbound_semantic_leaf`: the semantic structure contains a block with no source reachability.
- `repair_required`: continue the bounded repair loop; it is not completion.
- `batch_incomplete`: at least one frozen URL lacks a verified complete design.
