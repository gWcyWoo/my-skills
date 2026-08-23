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

Run `component-design` only after Stage 1 has frozen a complete extract
`run-result.json`. Stage 2 reads that sealed result and must not invoke any Stage-1
command or rerun Stage-1 verification. IOLE's exact `iole.flow-source-bundle.v2` must be passed once
to Stage 1, which freezes it at `.icp/source/source-bundle.json`; Stage 2 reads
that single project artifact and accepts no second source-bundle input. The bundle
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

## Non-negotiable stage data flow

1. IOLE reads the complete related-row closure once. Every mapping-owned column
   is present; a present value is exact and an empty value is JSON `null`.
2. Stage 1 authors visual-semantic Blocks first, using same-row `UI补充描述` only
   to assist grouping. It then binds every design JSON fact, relation, asset, and
   source node into those Blocks and runs exhaustive JSON-semantic reverse review
   until the frozen Blocks reconstruct the design data completely.
3. Stage 2 is the only business-semantic interpretation stage. It binds every
   Block to exactly one component instance, may bind several Blocks to one
   component, closes every atomic interaction as
   `condition -> state -> trigger -> behavior -> result`, binds every interaction,
   API call/result, and documented acceptance obligation to components, and emits
   one self-contained `implementation_contract`.
4. Stage 3 reads only Stage 2's component-bound Stage 1 projection and closed
   `implementation_contract`. It must not rejoin extract data or read or receive the IOLE bundle, raw
   rows, raw UI/interaction/API/UT/IT/E2E prose, quotes, or source spans, and must
   not invoke Stage 2 verification or perform a second semantic interpretation.
   It verifies Stage 2 only through the sealed result/artifact hashes, chooses codebase reuse and
   platform primitives, writes code/tests, and verifies runtime/visual results.
5. IOLE remains orchestration authority for claim, execution, Git/MR, and Sheet
   writeback. It joins artifacts by stable `source_id`, `page_key`, member
   `contract_digest`, component-lock hash, and canonical `bundle_digest`; byte
   equality between duplicate JSON serializations is never a business contract.

If Stage 3 finds incorrect design data, return to Stage 1. If it finds an
incorrect component, interaction, API, or acceptance contract, return to Stage 2.
Stage 3 must never compensate by rereading original prose.

## Project-owned artifacts

Write process artifacts under the target project:

```text
<project>/.icp/extract/<design-name>/
<project>/.icp/source/source-bundle.json
<project>/.icp/component-design/
<project>/.icp/implementation/
```

The extract batch manifest, index, and result live directly in `.icp/extract/`.
Component design owns one cross-design contract in `.icp/component-design/`.
Implementation owns plans, page codegen packets, TDD evidence, runtime evidence,
and its final result in `.icp/implementation/`. Preserve all three directories on
failure because their hashes, revisions, and repair packets are evidence.

Every stage owns one deterministic `checklist.json`. Its ordered node definition
is derived by the stage script from that run's frozen input before model work
starts; the model never authors or marks it. This is an execution control for the
ICP model and its commands, not protection against a person editing files. It
prevents the model from omitting work, running work out of order, reporting an
unexecuted step as complete, or retaining stale downstream results. Each
successful CLI transaction records its exact node and evidence hash. A changed
upstream evidence hash resets that node and every transitive dependent node to
`pending` while preserving the execution history. A stage verifier reports the
earliest unfinished node as `resume_from_node` plus the complete
`revalidate_nodes` suffix; the model must execute that node and then revalidate
its dependents in dependency order. Only after every node is `completed` may the
final verify node complete or the next stage begin.

Stage state and hash-bound artifacts are the transaction authority; the checklist
is their derived execution receipt, never a second business-state machine. Every
recording command must hold its stage's OS-backed write lock from live-state read
through artifact publication, state commit, and checklist receipt. Retrying the
same committed input is idempotent: if state and artifact hashes are committed but
the receipt is missing, revalidate those exact artifacts and write only the
receipt; if artifacts exist without committed state, deterministically publish the
same transaction again; a receipt without matching committed state is invalid.
Never decrement a revision or infer current state from conversation history.

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
For every JSON node with children, also reconcile the source grouping explicitly
against the already-frozen visual Block hypothesis as `matches_block`,
`contains_blocks`, `part_of_block`, or `technical_group`. Cite separate rendered
and JSON evidence. JSON hierarchy is meaningful counter-evidence, but it never
authors the first visual grouping or mechanically overrides it.
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
One candidate is sufficient when either its exact page-reviewed
`business_source/component_relation` fact has closed `shared_candidate` intent and
targets that candidate itself, or an independently reviewed `shared_usage` fact
targets that candidate's exact source member and that member owns exactly one
candidate. `local_boundary` never authorizes reuse. A `shared_usage` fact must
target an exact member already connected by IOLE's source relation graph and must
bind to that member's final shared component through a `component_ref`; it cannot
remain a generic instance fact. These exceptions may apply inside one design or
to a source-only shared component row; mobile-pattern familiarity alone never
triggers them.

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
`交互描述` into a closed five-field audit ledger: `condition`, `state`, `trigger`,
`behavior`, and `result`. Every atomic item contains all five keys, at most one non-null
value, and the exact same-page source span. A non-null value names the matching
source-backed fact; a segment with no meaning in these five types remains all-null. An
empty interaction description is represented by one all-null item; null is valid
absence and never requires a fabricated fact or binding. Review all items in one
full pass, batch every omission into one revision, then rerun the full review.

Then assemble those atomic facts into an interaction graph owned by that page.
Every graph interaction keeps the same five nullable fields—`condition`, `state`,
`trigger`, `behavior`, and `result`—and binds every non-null field to its owning
page candidate. `result` records the observable consequence of the behavior; it
is not inferred later from a missing edge. A trigger, its behavior, and its result
stay in the same causal interaction. An edge resolves one named result either to
a next same-page interaction or, when backed by an exact IOLE `navigation|modal`
reference, to the referenced page/design state. The edge remains owned by the
source page and never imports its facts into the target page. A click that calls
an API is one interaction whose trigger is the click and whose behavior is
`api_call`; both `success` and `failure` must resolve to separate render,
navigation, error, retry, or state results. A truly terminal result is declared
in graph-level `terminal_outcomes` with a non-empty inference basis; an absent
edge never silently means terminal. Every frozen
interaction fact appears exactly once, and the final lock projects candidate
bindings to exact component instance IDs.

Every exact IOLE `navigation|modal` reference is transition evidence and must be
consumed exactly once by an external result edge. Its reference span must be
contained by a source-backed `result` fact on the emitting interaction. Freeze
those exact requirements with the locked graph; an omitted, duplicated, uncited,
or wrong-result relation is incomplete even when its target title matches.

Stage 2 also projects every non-empty same-page `接口描述` and every exact
technical `API:xxxx`/`API：xxxx` directive in `交互描述` as an API requirement.
Accepted locators are an uppercase HTTP method plus path/URL, a path/URL, an
endpoint ID, or `project_id/endpoint_id`; prose after `API:` is not a directive.
Resolve each requirement read-only through Apifox, use `record-api-contract` to
seal the acquisition artifact before page authoring, freeze the raw endpoint contract and hash,
normalize its transport shape, and bind it to an `api_call` interaction. The
description owns business meaning; Apifox owns the technical transport shape.
Empty sources create no API contract. An unresolved, duplicated, unused, or
component-unbound API contract fails Stage 2; Stage 3 never guesses it.

Every non-relation business-source fact owned by a local component must enter that
component's semantic contract as a capability, data role, or action role. A generic
`instance_fact` is not a valid terminal sink for local source semantics. Shared
definitions may keep page-specific differences on their own instances so that one
page's conditions, states, triggers, behavior, and results never constrain another page.

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
integration test from three preserved sources—same-page `IT`, the same-page
interaction graph derived from `交互描述`, and model inference over each frozen component's complete semantic
contract. Freeze the complete obligation universe first, then execute one strict
vertical case at a time: map its frozen fact basis to a closed production-UI
scenario, let ICP deterministically materialize and freeze that Android test,
observe RED,
implement its smallest production slice, and observe GREEN before starting the
next case. The implementation model may author the scenario mapping but never the
executable test body. Do not require every case to become RED before the first
case can reach GREEN. Final verification still requires RED and GREEN for
every frozen obligation. Every executable interaction contract keeps `condition`
and current `state` facts in preconditions,
`trigger` facts in actions, and `behavior` plus `result` facts in post-action
assertions. A visual trace step must reuse the complete ordered action sequence
from that interaction's frozen integration case. A case-driven step names only the case,
interaction, and selected outcome; ICP derives and freezes its complete ordered
action sequence, including input, click, and back operations. When its selected graph edge targets
another interaction, any following step must start at that exact target; sharing a
page does not make two interactions adjacent.
For every case with actions, the generated device test proves each declared result
predicate is false before the trigger and true afterward. For `api_call`, its
runtime contract also freezes method/path/significant headers and request body plus
an allowed response. An instrumentation-owned HTTP recorder must observe that real
production-adapter request and return the frozen response before the final UI
result may pass; app-authored network claims are never evidence.
The recorder first withholds the response and proves the result is still false,
then releases a response containing a fresh runtime-only canary and requires that
same value on the live production UI. A failure edge instead closes the matched
request without a response and accepts only the resulting production error state.
Every page likewise has one runtime Mock
input carrying a fresh canary through its normal DTO/UI-state render path. A valid
JSON file, DTO class name, source anchor, or syntactic method call is coverage only
and never completes either behavior without these device observations.

Audit every Stage 1 design element/asset and compare every
design state with its reference at the exact frozen reference viewport. Derive
immutable bounds, color, font-size, and line-height assertions from Stage 1 and
bind them to production elements through `runtime_probe_tag`; authored pass/fail
booleans are not evidence. Bounds come from the live hierarchy, opaque color from
captured pixels, and font size/line height from deterministic `R.dimen` resources
read from the uniquely matched clean-build APK; app-published typography is not
evidence. Intrinsic/container bounds and visual tokens are exact;
text and dynamic-content bounds are measured but adaptive so natural wrapping is
not forced. At that viewport check those runtime values;
whole-image MAE is diagnostic only. Compact, expanded,
and other sizes instead check
natural text reflow, clipping, overlap, horizontal overflow, scroll reachability,
control operation, system bars, and safe insets. Every component must be
constraint-driven and content-adaptive; they never use screenshot MAE as a gate.
Scroll reachability is proven by real driver swipes to a stable hierarchy end,
complete occurrence coverage, and restoration to the starting hierarchy; app
content extents and offsets are ignored.
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

Implement one connected interaction slice as one production unit: bound component
UI, state, trigger handling, behavior, observable result, API adapter call when
present, response-to-page-DTO mapping, render/navigation/error continuation, and
its integration test.
Every interaction needs one production mapping. Every API contract needs one
adapter file and method mapping, and an `api_call` interaction must execute that
method; a declaration, comment, string, or unused adapter is incomplete. Its
integration case must observe the exact outbound request and continuation.

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
description explicitly requires a different result. Component design's internal
source-coverage spine maps every exact description segment to page semantic facts
without compiling prose into an executable rule AST. That audit material remains
inside Stage 2; Stage 3 receives only the sanitized closed contract. The final lock freezes page facts, component
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
from the frozen composition's parent, slot, and order fields. The same
identity-vs-order rule governs the other coverage collections: global
`component_instances` storage order in the component lock, per-component
`block_obligation_ids`, per-interaction `component_instance_ids`, and integration
`basis_fact_ids` are each compared as an exact identity set (duplicates rejected,
sorted missing/unexpected diffs reported) and normalized to the authoritative
expected order when the plan is frozen.

Stage 3 must also prove that it consumed exact source-bound assets. These include
exported assets and deterministic reference crops created for small, unexported
icon components. For every rendered design element with source assets, its plan selects at least one frozen asset ID and
SHA-256 plus one project-relative target resource. Verification requires identical
source and target bytes by SHA-256; code anchors alone do not prove the asset was
used, and redrawing or approximating a source-bound icon is forbidden.
An asset-internal element is joined to that owner only by Stage 1's frozen
`parent_id` chain. Never infer ownership from punctuation, prefixes, or hierarchy
encoded in a design-tool node ID. Every element has exactly one evidence channel:
its own live production node or one exact source ancestor that owns the verified
asset bytes.

Visual evidence must be produced by ICP's reversible device-capture process. For
each design state, derive one collision-resistant `visual_state_id` from its exact
page key and design identity; never derive it from a transliterated display title.
Freeze the production runtime entry, package, locale, environment/data
preconditions, an entry-rooted production interaction trace, and one production
renderer identity; snapshot
the emulator's size/density override modes, locale, font scale, and navigation
mode; convert it to the reference pixel size and logical scale; perform a normal
cold start without a terminal debug-state extra; prove the target activity is
resumed and its process remains alive; execute the frozen trace by following the
exact Stage 2 result edges, including cross-page navigation and presentation;
attest the exact state ID plus unique production root; and prove no fatal exception
or ANR occurred. A debug/preview duplicate renderer is forbidden. Only then measure
the production element probes and capture the full
long artboard; normalize the PNG to the reference dimensions; and restore the exact
snapshot in a `finally` path. Verification rejects missing conversion/restoration
or production-path evidence before recording diagnostic MAE and applying
source-bound runtime checks.
Opaque color completion comes only from a concrete pixel coordinate in the real
production screenshot inside the hierarchy-bound element region. The app's probe
may locate the element but its claimed color is not a pass/fail value. Preserve the
observed coordinate and RGBA value in the visual result.

The implementation plan declares one foundation-owned production runtime-probe
publisher at `files/icp-runtime-probes.json`, its exact publish method, and the
production render call sites. Its payload follows
`implementation/references/runtime-probe-contract.md`. Reference and responsive
capture accept only ICP's own Android driver and run only after the selected
page's GREEN cases plus page-scoped production code/asset coverage pass. Final
verification still requires every page and the global manifest. Compact and expanded runs are generated by
`capture-responsive`, not authored in the final evidence: every published
component occurrence must be observed on the live UI hierarchy, including by
scrolling lazy content when necessary, and its payload bounds must agree with the
observed geometry. Static anchors and copied probe JSON are never runtime evidence.

The runtime entry file/symbol identifies the real launcher, deep-link handler, or
navigation coordinator found in the codebase. Its initial page/design identity is
separate. Do not replace the application entry with a page renderer merely to make
a capture route validate; they may share a file/symbol only when the codebase does.

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

## Run-local incident recovery

An unexpected ICP/IOLE script, schema, validator, or orchestration failure is not
an instruction to abandon the user's business task. Expected RED, a normal
semantic revision, a documented stage gate, or failing application behavior stays
inside its owning stage and is not an incident. Use
[references/incident-recovery.md](references/incident-recovery.md) only when the
normal stage transition cannot continue because the ICP/IOLE tooling or contract
itself rejected otherwise equivalent run data.

The main session stops the failed command, records the incident under the target
project's `.icp/incidents/`, and dispatches one recovery subagent. That subagent
records facts and prepares only an append-only run-local recovery; it does not
analyze root cause, change Skills, edit production code, mutate Sheet/Git/PR, alter
frozen evidence, or declare the incident fixed. After recovery verification it
returns the exact resume command to the main session. The main session reloads
the live ICP instructions and resumes from the last successful checkpoint. Before
the final user report, always list pending incidents and disclose every temporary
recovery plus the still-unresolved ICP defect.
