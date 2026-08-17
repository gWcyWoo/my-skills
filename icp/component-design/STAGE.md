# Component-design stage

## Outcome

Convert one verified extract batch plus IOLE's exact source bundle into a locked
component-semantic system for stage 3. Collect component responsibilities,
boundaries, page-specific facts, states, behaviors, data and API dependencies,
reuse decisions, component instances, and final design compositions.

Do not implement components in this stage. Do not emit production code, framework
types, class names, widget trees, rendering algorithms, validators, reducers,
network clients, file ownership paths, or execution plans.

There is no score or tolerance. Completion requires every exact gate:

```text
every verified design = exactly one IOLE page member and ordered design state
every semantic Block = exactly one page-local candidate and composition instance
every semantic Block = one explicit final Block-to-component binding with complete extract evidence
every final component = one or more Block-backed instances or one declared source-only instance
every non-empty source clause = an exact contiguous source partition
every non-whitespace source clause = at least one exact semantic fact segment
every normative source segment = one or more source-bound semantic facts
every semantic fact = one closed evidence class plus same-page candidate-owned Blocks
every business-source fact = exact source spans closed by the coverage ledger
every design-visible fact = visible-only semantics with no business source span
every source fact segment = one passing atomic semantic review with concrete evidence
every page review = hash-bound to the exact draft and candidate projection
every page = sealed before any group abstraction is recorded
every candidate = exactly one group disposition and one final component instance
every local definition = instances from exactly one page scope
every shared definition capability = evidenced by every page instance that uses it
every page-specific behavior/value/API fact = retained only on that page instance
every historical reuse = verified semantic contract evidence, never a score
every replacement = append-only supersession event with an acyclic materialized map
every final composition slot = a declared slot on its final parent definition
every source member = one ordered lock manifest entry with exact change scope
every source relation = preserved in order with member-closed endpoints
component lock = exact hashes plus complete stage-3 semantic input
```

## Authority and page isolation

The description document is the sole authority for business meaning. Preserve
IOLE's exact title, route, `UI补充描述`, `交互描述`, `接口描述`, UT, IT, and E2E
values. A design supplies verified hierarchy, layout, visual treatment, assets,
and semantic grouping. Its copy, sample data, and captured control state are
placeholders unless the same page's description confirms them.

Treat every IOLE member/physical row as an independent page scope. Multiple
designs may be ordered states of one page. A behavior, state, value, validation,
API dependency, or interaction from page A cannot constrain page B merely because
both pages use one shared definition. An A-to-B navigation sentence remains an
outcome of A's event; it is not a B-page constraint.

`change_scope` remains authoritative even when a `context` or `navigate-only`
member has verified designs. Such a member participates in component-semantic
analysis so its visible structure can inform the flow, but it never becomes a
modify target. The final lock preserves the ordered source-member graph and joins
it to pages by stable `page_key`; component instances and compositions do not copy
scope into a second authority.

Shared definitions contain only cross-instance invariants. Page instances retain
the exact page facts and bindings. If one proposed shared capability is not
evidenced by every instance, keep it instance-specific or reject the abstraction.

An empty description field adds no invisible behavior. Preserve the absence and
use the design only for visible structure and visuals. Do not fill empty fields
from another page or from a screenshot.

Use [references/mobile-component-patterns.md](references/mobile-component-patterns.md)
as an advisory morphology prior while finding candidates and deciding their
boundaries. It distinguishes common Android/iOS shapes such as bottom navigation,
tabs, bottom sheets/drawers, side drawers, modal dialogs, cards, forms, inputs,
uploads, and feedback messages. The script freezes the complete Markdown and its
SHA-256 into the stage, then injects that exact context into every page-facts
authoring input, page-review input, and the final group-abstraction input. The
author and reviewer must read the injected context;
omission, substitution, or mutation fails closed. This knowledge may suggest a
`page|section|component` boundary, `container|complete` mode, slots, and state
questions. It is never business-source or design evidence and cannot invent a
behavior, state, rule, API, copy, navigation target, or reuse claim.

Facts make that authority split explicit. A `business_source` fact is authoritative
business meaning and requires exact same-page source spans plus candidate-owned
Blocks. A `design_visible` fact is limited to directly visible structure, grouping,
visual state, placeholder data, or component relationship; it has no source span,
requires candidate-owned same-page Blocks and a non-empty `visible_basis`, and may
use only `responsibility|state|data|component_relation`. It cannot assert behavior
or an API dependency. When both sources support one meaning, record
`business_source`; do not create a hybrid fact.

## Inputs

Require both:

1. A complete `.icp/extract/run-result.json` whose live `verify-run` succeeds.
2. The exact unchanged `iole.flow-source-bundle.v2` from IOLE's closed related-row
   graph. `row_data_columns` declares the mapping-owned ICP inputs and every member
   includes exactly that ordered set in `row_data`; non-empty values are exact
   strings and exactly empty values are JSON `null`. Missing declared columns and
   empty-string placeholders fail. Unowned Sheet columns are not ICP inputs and do
   not enter the handoff, its hashes, or its semantic reverse audit. Its hash-bound
   `source_closure` must cover every member's declared business columns and relation
   evidence against the complete Sheet title catalog. A missing/stale closure,
   legacy analysis, failed review, or relation projection mismatch fails.

Optionally accept one read-only project component catalog:

```json
{
  "schema": "icp.component-design.project-catalog.v1",
  "components": [
    {
      "component_id": "existing-form-shell",
      "evidence_class": "verified-component-lock",
      "provenance": {
        "path": ".icp/component-design/component-lock.json",
        "sha256": "<64 lowercase hex>"
      },
      "semantic_contract": {
        "component_id": "existing-form-shell",
        "name": "Existing form shell",
        "kind": "component",
        "scope": "shared",
        "reuse_mode": "container",
        "responsibility": "Own the stable form shell.",
        "owns": ["The shared shell boundary."],
        "excludes": ["Page-specific form behavior."],
        "capabilities": [],
        "slots": [
          {"slot_id": "content", "role": "Place business content.", "cardinality": "one"}
        ],
        "data_roles": [],
        "action_roles": []
      }
    }
  ]
}
```

The provenance path must be project-relative, exist, and match its declared SHA-256.
Use `verified-component-lock` only when that file is an
`icp.component-design.lock.v4`, `icp.component-design.lock.v5`, or
`icp.component-design.lock.v6` containing the
exact declared semantic definition.
Use `code-derived` for model analysis of existing implementation. A code-derived
entry cannot be `reuse-existing`; it may only support `adapt-existing`, which must
create a new complete semantic definition with a new ID.

## Runtime layout

```text
.icp/component-design/
├── .write.lock
├── iole-source-bundle.json
├── source-catalog.json
├── business-context.json
├── mobile-component-patterns.md
├── project-component-catalog.snapshot.json
├── page-component-facts/
│   ├── <page-key>.input.json
│   ├── <page-key>.draft.json
│   ├── <page-key>.review.input.json
│   ├── <page-key>.review.json
│   ├── <page-key>.review-repair.json  # only after revise
│   └── <page-key>.json
├── revisions/
│   ├── page-facts.<page-key>.<revision>.json
│   └── page-review.<page-key>.<revision>.json
├── group-candidate-registry.json
├── abstraction-plan.input.json
├── abstraction-decisions.json
├── component-system.json
├── component-cache-events.json
├── replacement-map.json
├── block-component-bindings.json
├── component-lock.json
├── stage-result.json
└── state.json
```

The snapshot, draft, review projection, canonical, and revision files are computed
or validated artifacts. Never edit them after their producing command succeeds.
Repair only a separate page-facts input or the generated review input before its
recording command. A revised page produces a new hash-bound revision.

Every CLI subcommand acquires `.write.lock` before reading live stage state and
holds it through all artifact writes and the final `state.json` commit. Page
analysis and input authoring may run concurrently, but recording commands are
serialized stage transactions. The default bounded wait is 30 seconds and can be
changed with `--lock-timeout-seconds`. On timeout the command returns `stage_busy`
without mutating the stage; retry the same command after the current writer exits.
The lock is OS-backed, so process exit releases ownership and a leftover lock file
is not a stale owner. The same transaction boundary covers last-page registry
materialization and group abstraction check-then-write operations.

## Pass 1 — draft, review, and seal each page independently

Start only after the complete extract batch exists:

```bash
python3 <icp-skill>/component-design/scripts/component_design.py begin \
  --project-root "<project>" \
  --source-bundle "<iole-flow-source-bundle-v1.json>" \
  [--project-catalog "<project-component-catalog.json>"]
```

`begin` freezes exact inputs and creates one stable semantic work item for every
IOLE member with one or more design states or any non-empty UI, interaction, API,
or acceptance source clause. A designless member with such data is a source-only
work item: it may define candidates and exact-span `business_source` facts, but it
must have no Block refs, `design_visible` facts, or design compositions. A
designless member with no such data remains losslessly preserved in
`business-context.json` and the final lock's `context_members`; it cannot
manufacture semantics. Read a
page work item's business context, its ordered design states, and the joined
source catalog. Do not read another page as authority for this page.

### Page candidates

For one page, identify candidates from semantic responsibilities and Block
boundaries. A page may contain several reusable candidates, and multiple instances
inside one design may justify sharing; cross-design repetition is not required.

Each candidate declares only:

- stable ID, name, `page|section|component` kind;
- responsibility, `owns`, and `excludes` boundary;
- exact design/Block references;
- semantic facts.

The final definition kind must equal every governed candidate kind. A `page`,
`section`, or `component` boundary cannot silently change kind during reuse.

Each semantic fact declares:

- stable fact ID;
- `responsibility|condition|state|trigger|behavior|data|api_dependency|component_relation` kind;
- semantic meaning, without implementation algorithms;
- exactly one `business_source|design_visible` evidence class;
- exact same-page source spans for `business_source`, or no source spans plus a
  non-empty visible-basis explanation for `design_visible`;
- exact design/Block evidence owned by the same candidate.

A `component_relation` fact also declares one closed intent and target:

- `local_boundary` targets `{kind: self_candidate, id: <this candidate>}` and
  records a page-local component boundary only;
- `shared_candidate` targets that same self candidate and is the only single-
  candidate source declaration that may authorize a new shared extraction;
- `shared_usage` targets `{kind: source_member, id: <exact related member title>}`.
  The target member must exist and the current member-to-target edge must already
  be closed by IOLE's source relation graph.

Design-visible evidence may only declare `local_boundary`; appearance never
authorizes sharing. Do not encode a vague “component relation” and defer its
direction or reuse meaning to the group pass.

Create one fact for every independently required or observable responsibility,
condition, state, trigger, behavior, data rule, API dependency, or component relationship. Do not use
one clause as one fact merely because the source coverage template has clause
boundaries. Several facts may cite the same exact span, and that span's `fact_ids`
must list all of them.

For example, this one span:

```text
visa/mastercard可点击，默认选中visa显示visa的信息，点击mastercard，显示“如何支付-mastercard”页面信息
```

requires at least separate facts for selectable payment choices (`behavior`),
Visa as the default selection (`state`), Visa content as the initial visible state
(`state`), selecting Mastercard (`behavior`), and Mastercard content as the
resulting visible state (`state`). All may cite the same exact source span. Do not
collapse them into one `state` fact and do not invent implementation mechanics.

For example, a phone input candidate may contain page-instance facts for editable
input, backtracking modification, validation outcome, enabled/invalid/submitting
states, required data, and API dependency. Record what the component must mean and
do; do not specify how code performs it.

### Source coverage spine

Partition every non-empty clause from offset 0 through its full Unicode length.
Preserve the exact quote. Each segment is exactly one of:

- `fact`: lists one or more fact IDs that cite this exact span;
- `context`: whitespace only, with rationale;
- `unresolved`: a semantic gap with rationale; recording must fail.

Keep punctuation with its adjacent fact. A slash, decimal point, currency symbol,
arrow, or other punctuation-like character may carry business meaning, so the
stage never asks the model to decide whether it is safe to discard.
Whitespace-only clauses remain exact `context` and require no fabricated fact.

Only `business_source` facts may appear in this coverage ledger. A
`design_visible` fact cannot consume or hide a description span. The ledger
replaces the old executable rule AST. It proves no UI,
interaction, API, or acceptance source disappeared without compiling prose into an
implementation language. Reconciliation is bidirectional: every fact segment must
match a business-source fact ref, and every business-source fact ref must appear in
exactly the coverage ledger rather than riding into the lock as undeclared evidence.

### Atomic interaction check

After the first page component model exists, independently split only the exact
same-page `交互描述` into atomic `condition|state|trigger|behavior` items. These
four fields are the closed interaction-check vocabulary:

- `condition`: an applicability guard or prerequisite;
- `state`: a current observable business or component state;
- `trigger`: a user or system event that starts an interaction;
- `behavior`: the externally observable business outcome after a trigger.

Every item always contains all four keys and at most one non-null value; the other
values are JSON `null`. A non-empty source segment that contains only supporting
data, structure, or context still gets one same-span all-null item rather than a
fabricated interaction meaning. Several items may cite the same exact source segment.
Each non-null value names exactly one same-page `business_source` fact of the same
kind and meaning. That fact must cite the identical source span. A non-empty
interaction description must have at least one atomic item for every fact segment,
and the interaction item/fact sets must be bidirectionally equal. Do not manufacture
a missing condition, state, trigger, or behavior merely to populate the structure.

When the complete interaction description is empty, preserve one explicit item
whose source ref and all four fields are `null`. This item is evidence of absence,
not an error and not a component binding requirement. Empty strings and missing
keys are not substitutes for `null`.

The generated page review includes these items beside the exact segment and linked
facts. Review the entire page, collect every missing or wrongly typed item in one
pass, revise them together, then rerun the complete page review from the first
segment. Do not repair one phrase by adding a phrase-specific validator.

### Page composition

For every design state, create one root-reachable acyclic candidate-instance tree.
Every semantic Block appears exactly once. The root instance owns the verified
root Block. When a child Block and its verified semantic parent belong to different
instances, the child instance must be an immediate child of the parent Block's
instance; Blocks collapsed into one candidate instance may keep internal parent
edges. The instance records candidate ID, parent, semantic slot role, and Block IDs
only; it is not a framework widget tree.

Record one page-facts draft:

```bash
python3 <icp-skill>/component-design/scripts/component_design.py record-page-facts \
  --project-root "<project>" \
  --page-key "<page-key>" \
  --facts "<page-key>.input.json"
```

This command validates structural integrity but never seals. It writes
`<page-key>.draft.json` plus a deterministic `<page-key>.review.input.json`. The
review projection groups every exact business-source fact segment with all linked
fact IDs, kinds, meanings, candidate IDs, and same-page Blocks. It also exposes
candidate boundaries and design-visible facts. A deterministic verbatim-
restatement signal focuses review attention but never decides correctness.

Read that generated review input against the authoritative same-page source and
the verified Blocks. For every segment, decide all five booleans:

- `all_normative_meanings_extracted`;
- `facts_atomic`;
- `fact_kinds_correct`;
- `component_relation_intents_correct`;
- `same_page_scope_correct`.

Then decide the page-level candidate-boundary, design-visible, cross-page leak, and
implementation-boundary checks. Every segment and the page-level review need
concrete non-placeholder evidence. `pass` requires every boolean true and every
issues array empty. `revise` requires at least one failed check or concrete issue.

Record the review:

```bash
python3 <icp-skill>/component-design/scripts/component_design.py record-page-review \
  --project-root "<project>" \
  --page-key "<page-key>" \
  --review "<project>/.icp/component-design/page-component-facts/<page-key>.review.input.json"
```

Only a passing, hash-matched review promotes the draft to `<page-key>.json` and
marks the page sealed. A revise result writes a repair artifact and requires a new
draft/review cycle. A stale or edited projection cannot seal another draft.

The stage remains `collecting_page_facts` until every page is sealed. Do not merge,
reuse, or cache candidates during this pass. When the last review passes, the
script deterministically writes one sorted `group-candidate-registry.json`, binds
every page-review hash into it, and writes the group abstraction input.

Before authoring candidates, read the complete injected
`mobile_component_pattern_context`. Use it to ask the relevant boundary/state
questions, then answer only with same-page source clauses and verified Blocks.
A recognized pattern without supporting page evidence remains a consideration,
not a fact.

Before a page review may pass, compare repeated candidate Blocks pairwise and
enumerate every visible value that can vary while the candidate responsibility
stays the same: icon/asset, title/copy, displayed value, selected item, and any
other caller-supplied content. Record each axis as an atomic `design_visible/data`
fact with the same semantic meaning on every applicable candidate. Set
`all_visible_variation_roles_extracted` true only after this full comparison; an
unlisted visible variation is a review failure, even when candidate boundaries
and source-node coverage are otherwise complete.

For large groups, models may analyze deterministic content-derived shards as
read-only proposals only. Do not commit a shard result. Reconcile all proposals
against the complete registry and record exactly one final group abstraction, so
page processing order cannot change the result.

## Pass 2 — decide the final component system

Read the complete candidate registry plus the frozen historical catalog. Decide
every candidate exactly once with one closed disposition:

- `keep-local`: retain one local boundary;
- `keep-separate`: explicitly reject a proposed merge;
- `reuse-existing`: use a verified historical semantic contract unchanged;
- `adapt-existing`: use a historical contract as evidence and create a new
  definition;
- `extract-container`: share the external framework and inject page-specific
  business content through declared slots;
- `extract-complete`: share the complete responsibility and vary only declared
  data/action roles and page-instance facts.

Never use a similarity score or threshold. Cite all governed candidate IDs,
explain the semantic boundary, and record rejected alternatives. Evidence
insufficiency means `keep-separate`, not a guessed merge.

Fact atomicity is a semantic modeling obligation enforced by the pre-seal page
review, not a text heuristic. When one source span contains both a cross-instance
invariant and an instance-specific state/value, record separate minimal facts that
may cite the same exact span. The validator never guesses a split. If a later
abstraction still exposes an over-coarse fact, `record-abstraction` writes nothing;
return to Pass 1, record a new split draft and passing review, rebuild the registry,
and retry. Never inspect titles, substrings, word counts, scores, or thresholds to
pretend atomicity is mechanically decidable.

A verified historical component may be reused by one current instance. Its
`shared` scope records the proven reusable contract, not a requirement that every
new flow must instantiate it twice. New extraction decisions normally require at
least two governed candidates. One current candidate may establish shared intent
only when an exact, page-reviewed `business_source/component_relation` fact
explicitly declares that candidate reusable; a familiar mobile shape or visual
similarity cannot do so. Historical provenance supplies prior evidence for
`reuse-existing` and `adapt-existing`.

Historical evidence does not make a role-less container fit every candidate. Every
final container instance must actually parent at least one child through one of its
declared slots. A container attached as an unused leaf has no closed candidate-side
evidence and is rejected.

### Definition and instance split

A component definition contains only:

- stable identity, kind, `local|shared` scope, and `local|container|complete` mode;
- invariant responsibility, owns, and excludes;
- invariant capability names and meanings;
- structural slots for a container;
- semantic data and action roles for a complete component.

It contains no source quote, page value, validation limit, API endpoint, page ID,
or state captured from only one page.

A component instance contains page key/title, governed candidate IDs, and every
page fact binding. A fact may bind to an invariant capability/data/action role only
when the target exists and the fact kind matches that target kind. Page-specific
facts on a shared definition may remain `instance_fact`. A local definition is
different: every non-relation `business_source` fact is part of that component's
semantic contract and must bind to a declared capability, data role, or action
role; using `instance_fact` as a generic sink fails with
`local_semantic_binding_missing`. Null interaction fields produce no fact and need
no binding. A shared `complete` component is stricter: every
`design_visible/data` fact is an explicit caller-supplied variation and must bind
to a declared `data_role`; leaving it as an `instance_fact` fails with
`visible_variation_role_missing`. The exception for relationships is
`shared_usage`: it must bind as
`component_ref` to the exact final shared component produced by its declared target
source member. That target may not be guessed from shape, name, or another page,
and a `shared_usage` relation may not remain an unbound `instance_fact`. Every
shared capability/data/action role must have evidence
on every instance, and its `meaning` must exactly equal at least one bound fact
meaning on every instance. This rule applies equally to business-source and
design-visible facts; their evidence class remains attached in the lock. Page-local
models may independently canonicalize truly
equal semantics to the same fact meaning; differing meanings remain instance
facts. The script also rejects a shared definition whose semantic text copies a
value or literal evidenced by only some of its instances; definitions are the
deterministic intersection, while instance-only meaning remains on instances.
It also rejects a source literal copied from an unrelated candidate, even when none
of the component's own instances supports that literal. A `local` definition
governs exactly one candidate and one instance. Reuse across two candidates or
instances—even inside one page—must be declared and validated as `shared`.
`keep-local` and `keep-separate` are therefore unary dispositions and cannot hide a
merge behind a non-merge label.

Record the complete group once:

```bash
python3 <icp-skill>/component-design/scripts/component_design.py record-abstraction \
  --project-root "<project>" \
  --plan "<project>/.icp/component-design/abstraction-plan.input.json"
```

## Append-only component cache

`component-cache-events.json` is the sole cache authority. It records candidates,
new component definitions, and `superseded` edges. Never physically delete an old
candidate or rewrite earlier events. `replacement-map.json` and the lock's
`cache_view` are deterministic projections.

Every candidate has one replacement head. New component IDs cannot reuse candidate
IDs, and the one-way supersession graph cannot contain a cycle or two competing
replacements. Stage 3 consumes the materialized final component IDs and uses them
instead of every replaced candidate.

## Freeze stage-3 input

```bash
python3 <icp-skill>/component-design/scripts/component_design.py verify \
  --project-root "<project>"
```

`verify` re-runs live extract/source checks, page hashes, full candidate coverage,
the abstraction contract, cache fold, replacement projection, and structural
completion gates. It never treats words such as `TODO` or angle-bracketed text in
the exact business source as a model placeholder. Success writes
`icp.component-design.lock.v6` with:

- one `inference_context` reference and hash for the advisory mobile morphology
  snapshot; its full Markdown remains in the stage and is not duplicated into
  every locked page;
- one compact `source_context` manifest containing source identity, root member,
  ordered member title/page/scope/design/digest joins, and the exact ordered
  relation graph;
- complete page semantic facts and exact evidence;
- final component definitions and page instances;
- abstraction decisions;
- final per-design composition trees with candidate-to-component replacement;
- one hash-bound `block-component-bindings.json` projection that embeds every
  verified extract Block with its complete source nodes/assets and binds it to the
  owning design instance, page candidate, semantic component instance, final
  component, parent design instance, and slot;
- description-empty designless members preserved as exact source context;
- source-only designless members locked as independent business-semantic pages;
- append-only cache projection and all frozen hashes.

`source_context` is the single authority for member `change_scope`. A designless
member has `page_key: null` only when it has no semantic work item; a source-only
member has a page key and component instances but no design composition. Every
design-bearing member joins exactly one locked page, and every component
instance/composition joins that member through the same page key and title.
Relation endpoints must be declared members, and all members
must remain reachable from `root_title`. The manifest contains no allowed paths,
implementation hints, code, or framework decisions.

Every non-root final composition instance must use a slot declared by its final
parent component definition. The root alone uses the reserved `root` slot. A slot
with `cardinality: one` accepts at most one child per parent instance; `many`
accepts multiple children. Every container instance exercises at least one slot.

The Block binding projection is the completion boundary between component design
and implementation. One component instance may own several Blocks, and several
independent Block groups may bind the same shared component definition, but every
verified `(design_name, block_id)` appears exactly once. Do not edit extract
Blocks. The projection overlays final component ownership on their complete frozen
evidence so stage 3 never has to reconstruct visual grouping or guess exact design
data. Source-only semantic instances have no fabricated Block binding.

Stage 3 may implement this lock but may not rename, split, merge, add, or remove
component boundaries without reopening component design.

## Fail closed

- `invalid_iole_input`, `source_context_join_mismatch`,
  `page_identity_collision`: the source member graph, scope, relation endpoints,
  or stable page joins are invalid.
- `extract_incomplete`, `extract_drift`, `iole_extract_mismatch`, `input_drift`:
  frozen source evidence or injected mobile-pattern context is missing or changed.
- `missing_mobile_component_patterns`, `invalid_mobile_component_patterns`:
  the Skill-owned Android/iOS morphology knowledge cannot be frozen as non-empty
  UTF-8 input.
- `source_coverage`, `semantic_fact_coverage`, `unresolved_semantic`: source spans
  or semantic facts are incomplete.
- `cross_page_semantic_leak`: one page supplied evidence, a literal, or a
  capability to another.
- `semantic_block_coverage`, `semantic_hierarchy_mismatch`,
  `composition_coverage`, `composition_not_tree`: candidate ownership or design
  composition contradicts verified Block structure.
- `block_component_binding_coverage`: a verified Block is missing, duplicated,
  assigned to an unknown candidate/component, or disagrees with the final page
  composition or semantic component instance.
- `page_facts_incomplete`, `candidate_disposition`,
  `candidate_instance_coverage`: two-pass coverage is incomplete.
- `unsupported_abstraction`, `invalid_reuse_mode`,
  `historical_component_evidence`, `historical_component_collision`: a reuse or
  adaptation decision lacks exact semantic evidence or overwrites an existing ID.
- `invalid_fact_binding`, `unknown_component_slot`, `invalid_slot_cardinality`,
  `unexercised_component_slot`: a fact target type or final parent-slot
  join/cardinality/evidence channel is invalid.
- `cache_fold_mismatch`, `replacement_coverage`: append-only cache state is
  inconsistent.
- `stage_busy`: another component-design transaction held the stage write lock
  through the bounded wait; this command made no state change and is retryable.
- `component_design_locked`: the accepted stage-3 boundary changed.
