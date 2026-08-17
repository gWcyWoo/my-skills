---
name: icp
description: Build a source-bound, staged design-to-code contract. Use when a user invokes ICP, asks to extract one or many Lanhu designs into trustworthy structured data, or wants to turn verified designs plus IOLE UI and interaction requirements into a locked business-component system. The current implementation covers extract and component-design.
---

# ICP

Turn rendered designs and their machine-readable sources into reviewable contracts. Keep model interpretation separate from deterministic facts and block every transition unless its exact gate passes.

## Route the request

- For design acquisition, semantic Blocks, exact source bindings, or extract
  verification, read [extract/STAGE.md](extract/STAGE.md) completely before acting.
- For business-component boundaries, cross-design merging, shared component
  extraction, props/slots/variants/states/events, or the implementation component
  lock, read [component-design/STAGE.md](component-design/STAGE.md) completely
  before acting.

Run `component-design` only after the same project's complete extract batch passes
live verification and with IOLE's exact `iole.flow-source-bundle.v2`. The bundle
declares `row_data_columns`, derived only from the selected role mapping's ICP
source fields. Every member must carry exactly those columns in `row_data`: every
non-empty value remains exact and every empty value is JSON `null`. Reject a
missing declared column, an empty-string placeholder, or mapped source data absent
from `row_data`. Connector columns not declared as ICP inputs stay outside the
handoff and do not participate in its hashes or semantic reverse audit. The bundle
must also contain a valid `source_closure`: complete title catalog, all-declared-
business-column analysis, field and cross-row review, and hashes that still match
every member's `row_data` and relation graph. Reject legacy analysis, a missing
member/declared field, stale evidence, false review pass, or an unbound relation.
One source member may own multiple ordered design states. Do not create
placeholder directories or pretend to run later stages. Implementation, fidelity
acceptance, and interaction/final inspection remain pending until their own
contracts exist.

## Project-owned artifacts

Write process artifacts under the target project:

```text
<project>/.icp/extract/<design-name>/
<project>/.icp/component-design/
```

The extract batch manifest, index, and result live directly in `.icp/extract/`.
Component design owns one cross-design contract in `.icp/component-design/`.
Preserve both directories on failure because their hashes, revisions, and repair
packets are evidence.

## Self-contained boundary

ICP owns its Lanhu acquisition path: URL parsing, configured-cookie resolution, HTTP and gzip handling, metadata and design JSON retrieval, complete cover validation, exported-slice discovery, downloads, and hashes. Do not call, import, or locate another skill at runtime.

The model may interpret semantics, roles, hierarchy, relationships, and source-node classifications. It may not invent source IDs, dimensions, colors, spacing values, or other exact facts. Scripts own source normalization, hashes, exact partitions, source-node-to-local-asset references, reference-pixel-to-logical-coordinate mapping, repair packets, state transitions, and completion verification.

Exact source-node coverage is necessary but never sufficient for extract. After
binding, traverse the complete JSON inventory again in source order. For every
source node, compare its complete payload, complete parent and children, current
assignment, and complete assigned Block; independently verify semantic fit,
whether it needs its own semantic group, and whether source containment survives
in the Block hierarchy. A present node swallowed by the wrong Block is an
omission. Any failed node must return to the model as a reverse repair packet;
no design may enter component design until every JSON-node review passes.
Treat this as a fixed-point loop, not a one-time audit:
`semantic draft -> complete bindings -> full JSON reverse review -> repair`.
Each review round is read-only and exhaustive: freeze the current draft and
bindings, traverse from the first source node through the last, and collect as
many problems as possible before changing anything. Do not fail fast, repair
mid-scan, or submit a partial review. Only after the entire inventory has been
reviewed may the model receive the complete round's repair batch.
After any failure, rebuild the affected semantic draft and complete bindings,
then regenerate and review the entire ordered JSON inventory from the beginning.
Never review only the previously failed nodes, carry forward an earlier pass, or
stop because node-count coverage is complete. Exit only when one fresh review has
all Block checks, all source-node checks, and all cross-Block checks true with no
issues.

Do not detect unresolved model work by scanning arbitrary source strings for words
such as `TODO` or angle-bracket syntax. Exact business text may legitimately use
those strings. Reject only structural sentinels and incomplete schema states.

In component design, use two closed passes. First, derive every IOLE page independently:
produce page-local component candidates plus source-bound responsibility, behavior,
state, data, API-dependency, and component-relation facts. One fact represents one
independently required or observable semantic proposition; one exact source span
may support several typed facts. Preserve an exact source coverage partition and
one candidate composition for every design state. `record-page-facts` writes only
a hash-bound draft and a deterministic segment-by-segment review projection. The
page remains unavailable to group abstraction until `record-page-review` confirms
that every independent meaning is present, facts are atomic and correctly typed,
page scope is correct, the page/candidate/implementation boundaries are clean,
and a pairwise Block comparison has converted every visible candidate variation
into an atomic `design_visible/data` fact. A shared complete component must bind
every such fact to a declared `data_role`; an instance-only visible prop is not a
finished component contract.
Page analysis may fan out, but every component-design CLI command is one serialized
stage transaction. The CLI holds the same OS-backed write lock from live-state
read through artifact writes, state commit, and last-page registry materialization.
Concurrent commands wait up to their bounded lock timeout; `stage_busy` means the
command made no state change and may be retried. Never bypass the lock by editing
runtime artifacts directly.
Do not merge candidates during this pass. Second, after every page review passes
and every page is sealed, decide the complete group abstraction against a read-only
historical component catalog. Keep
shared definitions invariant and retain all page-specific facts on component
instances. A designless member with non-empty UI, interaction, API, or acceptance
data gets an independent source-only semantic work item: it may create
business-source facts and component candidates, but no visual facts, Blocks, or
design composition. A truly description-empty designless member remains source
context only. Design-bearing
`context` and `navigate-only` members may supply component-semantic evidence but
remain read-only targets. The lock keeps one ordered source-context manifest with
the exact member scope and relation graph; instances join it by page key instead
of copying scope. Historical reuse must
resolve a project-relative file whose actual hash and semantic definition match
the catalog. A verified shared historical component may have one current instance;
its reuse evidence comes from the verified lock, not current-flow multiplicity.
Scripts own source partitions, page scope, Block coverage,
composition trees and final parent-slot joins, exact candidate disposition,
typed fact bindings, shared-definition intersection, append-only supersession
events, replacement projection, hashes, and the immutable component lock. A
component used by more than one page is shared by topology even if a plan labels it
local; reject that mismatch instead of trusting the label. Composition edges must
also follow the verified Block hierarchy, and final slots must respect declared
cardinality. Definition kind must match candidate kind, and every container
instance must exercise a declared slot rather than appearing as an unsupported
leaf. A shared capability/data/action meaning must exactly match a bound
canonical fact meaning on every instance; kind-only bindings do not prove a shared
invariant. Visual similarity and numeric scores never authorize reuse.

Component design owns one advisory mobile morphology knowledge file at
`component-design/references/mobile-component-patterns.md`. At stage start, freeze
its complete UTF-8 bytes and SHA-256 into `.icp/component-design/`, then inject the
exact content into every page-facts authoring input, page-review input, and group
abstraction input. Use it
to recognize Android/iOS shapes such as bottom navigation, bottom sheets/drawers,
side drawers, modal dialogs, cards, forms, inputs, upload controls, and feedback
messages, and to consider appropriate boundaries, slots, and sourced states. It
does not override the description or design and is never evidence for a business
fact, behavior, state, API, navigation target, or reuse decision. A familiar shape
without source/Block evidence must remain local or unresolved. Any missing,
changed, or omitted knowledge snapshot/input fails closed.
The final component lock keeps one hash-bound advisory reference and strips the
repeated Markdown body from locked page data, so stage 3 receives component
semantics rather than duplicated inference instructions.

New shared extraction normally needs at least two independent current candidates.
One candidate is sufficient only when its exact page-reviewed
`business_source/component_relation` fact has closed `shared_candidate` intent and
targets that candidate itself. `local_boundary` never authorizes reuse. A
`shared_usage` fact must target an exact member already connected by IOLE's source
relation graph and must bind to that member's final shared component through a
`component_ref`; it cannot remain a generic instance fact. This exception may
apply inside one design or to a source-only shared component row; mobile-pattern
familiarity alone never triggers it.

Every page fact must declare `business_source` or `design_visible` and cite Blocks
owned by its own page candidate. Business-source facts additionally require exact
source spans, and their coverage ledger must close in both directions.
Design-visible facts have no source spans, require a visible-basis explanation,
and cannot assert behavior or API dependencies. `local` always means one candidate
and one instance; repeated use within the same page is still `shared`. Exact or
contained source restatement is a generated review signal, never an automatic
semantic pass or failure. A short authoritative sentence may already be the best
atomic meaning; a paraphrased compound fact may still be wrong.

After the initial page component model exists, split the same page's complete
`交互描述` into a closed four-field audit ledger: `condition`, `state`, `trigger`,
and `behavior`. Every atomic item contains all four keys, at most one non-null
value, and the exact same-page source span. A non-null value names the matching
source-backed fact; a segment with no meaning in these four types remains all-null. An
empty interaction description is represented by one all-null item; null is valid
absence and never requires a fabricated fact or binding. Review all items in one
full pass, batch every omission into one revision, then rerun the full review.

Every non-relation business-source fact owned by a local component must enter that
component's semantic contract as a capability, data role, or action role. A generic
`instance_fact` is not a valid terminal sink for local source semantics. Shared
definitions may keep page-specific differences on their own instances so that one
page's conditions, states, triggers, and behavior never constrain another page.

## Source authority

The description document is the sole authority for business meaning. Treat the
exact IOLE source contract—including title/route, `UI补充描述`, `交互描述`,
`接口描述`, UT, IT, and E2E clauses—as authoritative for copy, values, data rules,
validation, enabled/disabled behavior, state transitions, actions, and acceptance.

Treat every IOLE member/physical row as an independent page scope. Multiple
designs may be states of that page, but a rule from page A cannot constrain page
B merely because both instantiate one shared component. Shared components reuse
structure and boundaries, not page behavior. Every rule application must name a
design owned by its source member and an exact instance in that design composition.
An A-to-B navigation sentence remains an outcome of A's event; it is not a
constraint on B. A destination-page constraint needs its own authoritative clause
and rule under B. Never infer cross-page scope from shared component definitions,
matching targets, similar screenshots, or another page's normalization evidence.

The design supplies verified hierarchy, layout, visual treatment, assets, and
semantic grouping. Its visible copy, sample data, and captured control state are
placeholders unless the description document confirms them. Whenever design and
description conflict, use the description without treating the design placeholder
as an unresolved blocker. If a description field is empty, preserve the absence:
use the design for structure and visuals, but do not invent business behavior from
the screenshot.

Do not use a title/substring/score heuristic to decide fact scope or atomicity.
Page isolation is structural: page key, design ownership, candidate-owned Blocks,
and exact source membership. Semantic atomicity is decided by the required
hash-bound page review before sealing, not inferred by the script. If an over-coarse
fact is found later, return the affected page to draft, split it, pass a new review,
and rebuild the registry; never weaken the shared-evidence gate.

This rule does not discard exact visual evidence. Dimensions, positions, colors,
spacing, hierarchy, and asset bindings remain source-bound design facts unless the
description explicitly requires a different result. Component design must preserve
the generated `source_authority` object exactly. Its source-coverage spine maps
every exact description segment to page semantic facts without compiling prose
into an executable rule AST. The final lock freezes page facts, component
definitions and instances, abstraction decisions, final design compositions,
append-only cache events, candidate replacements, and the exact source member
scope/relation topology needed by the next stage.

An individual design is complete only when this exits zero:

```bash
python3 <icp-skill>/extract/scripts/extract.py verify \
  --project-root <project> \
  --design-name <design-name>
```

A multi-design run is deliverable only when `verify-run` exits zero. Stop after reporting the verified extract result; do not begin component design implicitly.

A component-design run is complete only when this exits zero:

```bash
python3 <icp-skill>/component-design/scripts/component_design.py verify \
  --project-root <project>
```

Stop after reporting the component lock and stage result; do not begin production
implementation implicitly.
