---
name: icp
description: Build a source-bound, staged design-to-code contract. Use when a user invokes ICP, asks to extract one or many Lanhu designs into trustworthy structured data, turns verified designs plus IOLE requirements into a locked business-component system, or implements that lock with strict interaction TDD and visual verification.
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
- For target-platform planning, DTOs/mocks/adapters, code generation, interaction
  TDD, responsive runtime evidence, or visual fidelity, read
  [implementation/STAGE.md](implementation/STAGE.md) completely before acting.
- Stage 4 is reserved but inactive. Read
  [references/reserved-stage-4.md](references/reserved-stage-4.md) only when the
  user asks to discuss or activate it. Do not create Stage-4 runtime artifacts,
  run a fourth gate, or delay completion on its behalf.

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
placeholder directories or pretend to run later stages. Start implementation only
from a live-verified component lock and its deterministic implementation universe.

## Project-owned artifacts

Write process artifacts under the target project:

```text
<project>/.icp/extract/<design-name>/
<project>/.icp/component-design/
<project>/.icp/implementation/
```

The extract batch manifest, index, and result live directly in `.icp/extract/`.
Component design owns one cross-design contract in `.icp/component-design/`.
Implementation owns plans, page codegen packets, TDD evidence, runtime evidence,
and its final result in `.icp/implementation/`. Preserve all three directories on
failure because their hashes, revisions, and repair packets are evidence.

## Self-contained boundary

ICP owns its Lanhu acquisition path: URL parsing, configured-cookie resolution, HTTP and gzip handling, metadata and design JSON retrieval, complete cover validation, exported-slice discovery, downloads, and hashes. Do not call, import, or locate another skill at runtime.

The model may interpret semantics, roles, hierarchy, relationships, and source-node classifications. It may not invent source IDs, dimensions, colors, spacing values, or other exact facts. Scripts own source normalization, hashes, exact partitions, source-node-to-local-asset references, reference-pixel-to-logical-coordinate mapping, repair packets, state transitions, and completion verification.

Stage 1 receives the exact same-row `UI补充描述` as a string or JSON `null`.
Use it only to help interpret the rendered design and choose visual-semantic Block
boundaries, names, and grouping. It is not design-data authority and cannot add,
delete, replace, or override any Lanhu JSON fact. Stage 1 is complete only when
its self-contained `semantic-blocks.json` retains every ordered source node,
relationship, payload field, content role, and asset relation, and those Block
members plus the explicit non-rendering set reconstruct the complete parsed
design JSON exactly.

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

Component design consumes the verified Stage-1 `semantic-blocks.json` directly.
It binds those immutable Blocks to page candidates, component instances, and
final component definitions; it must not rebuild, reinterpret, or repair Stage-1
design grouping from separate source facts and bindings. Before using a design,
require its frozen Stage-1 `ui_supplement` to equal the owning IOLE member's exact
current `UI补充描述`, including `null`.

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

At implementation start, require the target project's root `common-rules.md` and
freeze its exact UTF-8 bytes, content, and SHA-256 into the implementation stage.
When the same-page description is silent or ambiguous about a project-wide policy,
consult this frozen public rule before platform best practices. An explicit
same-page clause always wins. Inject the complete frozen common rules into every
page codegen packet; a later file change is stage drift.

Also freeze the skill-owned Stage 3 implementation prompt. The page packet must preserve the complete
Stage 1 Block binding through design instance, semantic component instance, final
component, parent instance, and slot. Before coding, query the live codebase once
per Stage 2 component definition using the complete semantic contract, and let the
implementing model reuse a suitable public component or create the required one.

Stage 3 does only implementation and implementation verification: create every
integration test from three preserved sources—same-page `IT`, same-page
`交互描述`, and model inference over each frozen component's complete semantic
contract. Freeze the complete obligation universe first, then execute one strict
vertical case at a time: materialize that case's page-scoped test, observe RED,
implement its smallest production slice, and observe GREEN before starting the
next case. Do not require every page's tests to compile or become RED before the
first page can reach GREEN. Final verification still requires RED and GREEN for
every frozen obligation. Audit every Stage 1 design element/asset and compare every
design state with its reference at the exact frozen reference viewport. Derive
immutable bounds, color, font-size, and line-height assertions from Stage 1 and
bind them to production elements through `runtime_probe_tag`; authored pass/fail
booleans are not evidence. Intrinsic/container bounds and visual tokens are exact;
text and dynamic-content bounds are measured but adaptive so natural wrapping is
not forced. At that viewport check those runtime values;
whole-image MAE is diagnostic only. Compact, expanded,
and other sizes instead check
natural text reflow, clipping, overlap, horizontal overflow, scroll reachability,
control operation, system bars, and safe insets. Every component must be
constraint-driven and content-adaptive; they never use screenshot MAE as a gate.
The reference artboard is not a fixed runtime geometry template: do not hard-code
text/card/section/page heights or use locale/copy-specific line breaks, font
metrics, spacing, offsets, or geometry merely to reduce diagnostic MAE. Interaction
tests own behavior-driven visual state even when the static artboard differs. On
source-bound measurement failure,
collect all failed designs in one
regional difference report and trace each affected obligation back through its
code mapping and frozen Stage 1 source node. Repair code when the frozen data is
correct and the repair preserves the responsive contract. If Stage 1 data/grouping is wrong, stop changing code, return to Stage 1
with the exact design/Block/source-node/field, repair the owning data, rerun Stage
2, and then resume implementation. The model handles this correction loop itself;
Stage 3 adds no diagnosis protocol or state lock.

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

Stage 1 freezes every rendering source node as
`static_visual|static_copy|dynamic_content|platform_element` and reverse-reviews
that role with the Block assignment. Later stages must preserve it. In particular,
`dynamic_content` may require DTO/mock/API data plumbing, but its captured sample
value is never itself a rule.

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

Component design is not complete until it also writes one deterministic,
hash-bound `block-component-bindings.json`. This is an overlay on the immutable
extract artifacts, not an edit to them. It embeds every verified design Block with
its complete source-node/asset evidence and binds that Block exactly once to its
owning design instance, page candidate, semantic component instance, final
component, parent design instance, and slot. One instance may own multiple Blocks,
and multiple independent Block groups may use one shared definition; source-only
instances have no fabricated Block. Stage 3 must consume this projection instead
of reconstructing visual groups or reading a component definition without its
Block evidence.

Component coverage is an identity set, not a rendering-order contract. Stage 3
accepts the same complete `component_instance_ids` in any order, rejects duplicate,
missing, and unexpected IDs with an exact diff, and derives rendering order only
from the frozen composition's parent, slot, and order fields.

Stage 3 must also prove that it consumed exact exported assets. For every rendered
design element with source assets, its plan selects at least one frozen asset ID and
SHA-256 plus one project-relative target resource. Verification requires identical
source and target bytes by SHA-256; code anchors alone do not prove the asset was
used, and redrawing or approximating an exported icon is forbidden.

Visual evidence must be produced by ICP's reversible device-capture process. For
each design state, derive one collision-resistant `visual_state_id` from its exact
page key and design identity; never derive it from a transliterated display title.
Freeze package, locale, environment/data preconditions, the same-page production
interaction trace, and one production renderer identity; snapshot
the emulator's size/density override modes, locale, font scale, and navigation
mode; convert it to the reference pixel size and logical scale; perform a normal
cold start without a terminal debug-state extra; prove the target activity is
resumed and its process remains alive; execute the production interaction trace;
attest the exact state ID plus unique production root; and prove no fatal exception
or ANR occurred. A debug/preview duplicate renderer is forbidden. Only then measure
the production element probes and capture the full
long artboard; normalize the PNG to the reference dimensions; and restore the exact
snapshot in a `finally` path. Verification rejects missing conversion/restoration
or production-path evidence before recording diagnostic MAE and applying
source-bound runtime checks.

Every IOLE `modal|component` reference must also terminate in one Stage 2
`presentation_usage`: exact source page/facts/host instance to exact referenced
member/root instance/final component. Navigation edges do not create component
usage. Stage 3 may implement this binding but cannot infer, remove, or retarget it.

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

An implementation run is complete only when this exits zero:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py verify \
  --project-root <project> \
  --evidence <runtime-evidence.json>
```

This requires exact code coverage and asset hashes, strict interaction RED/GREEN
evidence, successful lint/build/integration commands, adaptive evidence for every
component, compact and expanded runtime checks, exact visual device
conversion/restoration evidence, production-path and renderer identity, and
passing Stage 1-derived runtime measurements for reference-viewport bounds, color,
and font metrics. PNG MAE is diagnostic only.

ICP currently has exactly three active stages. A zero exit from the Stage-3
implementation verifier is the final ICP completion condition. The reserved Stage
4 is future work only: it is not an implicit follow-up, completion gate, directory,
script, or IOLE delivery requirement.
