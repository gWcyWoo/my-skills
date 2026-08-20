# Component-bound position and layout derivation algorithm

Status: implemented, reviewed, tested, and connected to the Stage 2 → Stage 3
boundary. Stage 2 freezes `layout_inputs`; Stage 3 exposes the exact model
selection input, validates authored decisions, and freezes this output as
`layout_contracts` in the plan and page packets.

## Scope

The algorithm consumes one Stage 2 page whose Stage 1 semantic Blocks are already
bound to component instances. It produces the position and layout contract needed
to reason about responsive component code.

It owns only:

- source-coordinate normalization;
- component topology and explicit sibling order;
- Block-to-component geometry joins;
- artboard and component-local geometry;
- same-slot and cross-slot spatial evidence;
- layout-axis selection boundaries;
- adaptive size and downstream-position propagation;
- closed, evidence-derived geometric constraints;
- geometric reference and responsive assertions.

It does not own:

- color, background, border, radius, typography, or asset projection;
- original UI, interaction, API, Sheet, or business-description parsing;
- component regrouping or component-boundary changes;
- codebase reuse selection;
- production runtime-probe collection;
- model retry scheduling;
- ICP stage schema compatibility or version routing.

The surrounding stage responsibilities and their verification evidence are
recorded in `component-layout-follow-up.md`.

## Closed geometry input

```text
BoundComponentPage
  page_key
  design_state_id
  root_instance_id
  reference
    root_source_node_id
    logical_artboard_size { width, height }
    coordinate_contract
      supported_frame_spaces = [canvas, artboard, parent]
  instances[]
    instance_id
    component_id
    parent_instance_id | null
    slot
    order
    source_block_ids[]
  blocks_by_id
    block_id
    semantic_parent_block_id | null
    ordered_source_node_ids[]
    rendering_source_node_ids[]
    non_rendering_source_node_ids[]
    content_roles_by_source_node_id
  source_nodes_by_id
    source_node_id
    source_parent_node_id | null
    source_order
    frame | null
    real_frame | null
    geometry_basis = frame | real_frame | combined | not_applicable
    frame_space = canvas | artboard | parent
  component_definitions_by_id
    component_id
    kind
    slots[] { slot_id, role, cardinality }
  platform_context
    platform
    project_common_rules
    platform_best_practices
```

The content-role vocabulary used by the position policy is closed:

```text
static_visual | static_copy | dynamic_content | platform_element
```

The algorithm validates only the fields it consumes. The Stage 2 owner remains
responsible for the complete non-geometric component contract.

## Output

```text
ComponentLayoutContract
  page_key
  design_state_id
  root_instance_id
  component_tree
    nodes_by_instance_id
    children_by_parent_and_slot
  artboard_frames_by_source_node_id
  source_geometry_provenance_by_source_node_id
  block_geometry_by_block_id
  component_geometry_by_instance_id
    instance_id
    boundary_block_ids[]
    boundary_regions[]
    owned_regions[]
    artboard_envelope
    local_regions[]
    local_envelope
    geometry_source = root_artboard | bound_blocks | descendant_union | none
    dimension_policy
  layout_evidence[]
  decision_obligations[]
  authored_layout_decisions[]
  reference_assertions[]
  responsive_assertions[]
  audit_joins[]
```

No production UI interprets this JSON at runtime. It is a code-generation and
verification contract.

## Main procedure

```text
FUNCTION DERIVE_COMPONENT_LAYOUT(page, layout_selector):
    tree = VALIDATE_AND_BUILD_COMPONENT_TREE(page)
    block_owner = VALIDATE_EXACT_BLOCK_OWNERSHIP(page, tree)
    artboard_frames = RESOLVE_SOURCE_FRAMES(page.reference, page.source_nodes)
    block_geometry = BUILD_BLOCK_GEOMETRY(page.blocks, artboard_frames)
    component_geometry = BUILD_COMPONENT_GEOMETRY(
        tree,
        block_owner,
        block_geometry,
    )
    evidence = DERIVE_SPATIAL_EVIDENCE(tree, component_geometry)
    initial_policy = DERIVE_INITIAL_DIMENSION_POLICY(tree, page.blocks)
    obligations = BUILD_LAYOUT_DECISION_OBLIGATIONS(tree, evidence)

    selector_input = {
        page_key,
        design_state_id,
        component_tree: tree,
        component_geometry_by_instance_id: component_geometry,
        layout_evidence: evidence,
        initial_dimension_policy_by_instance_id: initial_policy,
        component_definitions_by_id: component_definitions,
        platform_context,
        decision_obligations: obligations,
    }
    decisions = layout_selector(selector_input)

    VALIDATE_DECISIONS(decisions, obligations, evidence, initial_policy)
    final_policy = PROPAGATE_AFTER_AXIS_SELECTION(tree, initial_policy, decisions)
    assertions = BUILD_GEOMETRIC_ASSERTIONS(
        tree,
        component_geometry,
        evidence,
        decisions,
        final_policy,
    )

    RETURN closed layout contract
```

The selector cannot change component identity, parent, slot, order, or Block
ownership.

## Coordinate conversion

The source frame is first selected deterministically:

```text
frame       -> frame
real_frame  -> real_frame
combined    -> union(frame, real_frame)
not_applicable -> no geometry
```

It is then resolved into artboard coordinates exactly once:

```text
root:
  (0, 0, root.width, root.height)

artboard node:
  copy selected frame

canvas node:
  selected.left - raw_root.left
  selected.top  - raw_root.top

parent node:
  resolved_parent.left + selected.left
  resolved_parent.top  + selected.top
```

The root source size must equal the logical artboard size. Negative resolved
positions remain legal because they may represent decorations or overflow.
If any framed source node uses canvas space, the root must also use canvas space;
otherwise the canvas origin is undefined and derivation fails closed.

## Component topology

`instances[]` array order has no meaning.

For each `(parent_instance_id, slot)` group:

```text
order is a non-negative integer
orders are unique
sorted orders equal [0 .. group_size - 1]
slot cardinality is satisfied
children are sorted only by explicit order
```

Every instance must be reachable from the single root and the graph must be
acyclic. Every Block must have exactly one component owner.

## Block and component geometry

A Block boundary region is a framed rendering source node whose source parent is
not another rendering node in that Block. The Block also retains every framed
rendering region. Boundaries preserve multiple disjoint outer regions; the full
rendering set prevents an internal renderer that protrudes past its ancestor
from being lost.

A visual component's boundary Blocks are those whose semantic parent is absent or
owned by a different component. Boundary regions describe the component edge;
its visual envelope is the union of every region in every Block owned by that
component, so an internal Block that protrudes outside a boundary Block is not
lost.

The root follows the same boundary-Block rule. Its synthetic artboard region is
joined specifically to the Block that owns the root source node, rather than the
first Block in storage order.

A component with no visual Block is a legal structural wrapper. Its artboard
envelope is the bottom-up union of its visual descendants. This supports scroll,
tab, conditional, and other structural containers without fabricating a design
Block.

Component-local geometry is calculated only after every artboard envelope is
known:

```text
local.left = child.artboard.left - parent.artboard.left
local.top  = child.artboard.top  - parent.artboard.top
```

## Spatial evidence

The algorithm emits deterministic evidence for:

- parent-child local position and insets;
- containment, overflow, overlay, or detached decoration;
- consecutive same-slot sibling gaps and alignments;
- cross-slot gaps, alignments, and overlap;
- source paint order for pairs that actually overlap;
- exact Block and source-node provenance.

These are observations. A negative gap alone does not decide whether code should
use an overlay, a decoration, or another platform mechanism.

Responsive non-overlap is one group assertion per component parent. It records
the overlap pairs present in the reference design and rejects any additional
runtime overlap. Pair evidence is emitted only for actual reference overlaps, so
a large non-overlapping list does not create a quadratic contract. Consecutive
same-slot members still own exact gap assertions. Across slots, only the boundary
members of adjacent slots in the selected slot order own an exact gap assertion.
Overlap discovery estimates interval concurrency on both axes and sweeps the
axis with lower concurrency. A vertical stack therefore scans by Y and a
horizontal row by X; non-overlapping lists do not fall back to all-pairs checks.

Each component also receives a horizontal overflow allowance equal to its
reference protrusion beyond the artboard's left and right edges. Responsive
verification permits that measured amount, not an unlimited exemption for the
whole component. Horizontal scroll scopes remain explicit exceptions.

## Layout decision obligations

There is one decision for every occupied `(parent, slot)`. A parent with multiple
occupied slots also has one cross-slot decision.

Evidence is indexed once by `parent_instance_id` before obligations are built.
Each obligation filters only its parent's evidence slice; it never rescans the
page-wide evidence collection.

Each decision contains:

```text
decision_id
scope = slot | slots
parent_instance_id
slot | null
ordered_member_ids[]
layout_kind = flow | overlay | grid | scroll | intrinsic | platform | constraint
main_axis = vertical | horizontal | none
sizing_policy { width, height }
alignment_policy
constraints[]
overflow_policy
evidence_ids[]
rationale
```

Same-slot member order must exactly equal the frozen component order. A cross-slot
decision must contain exactly the occupied slots. Overlay selection requires
cited overlap evidence from the bound design state and must use `main_axis=none`.
Every other decision with multiple component members must choose a horizontal or
vertical axis.

## Dimension and position policy

Each axis separates reference behavior from responsive runtime behavior:

```text
x/y
  reference = exact_origin | exact | flow_relative
  runtime   = viewport_origin | reference_relation | flow_relative

width/height
  reference = exact | viewport | measured_only
  runtime   = intrinsic | constraint_driven | content_driven |
              viewport_constraint | viewport_and_scroll_content
```

Natural or dynamic text produces `height.runtime = content_driven`; its reference
height is measured but is not forced to match a particular design-tool line wrap.
Intrinsic visual-only components remain exact at the reference viewport.

Propagation occurs only after the selector chooses an axis:

```text
vertical group:
  after a runtime-variable height, later y becomes flow_relative
  structural parent height becomes content_driven

horizontal group:
  after a runtime-variable width, later x becomes flow_relative
  structural parent width becomes content_driven

none/overlay:
  no flow axis is invented
```

A selector cannot declare a content-driven dimension as fixed, intrinsic, or
constraint-only.

## Closed geometric constraint targets

Every exact value comes from the closed evidence expression grammar:

```text
copy | add | subtract | min | max | nearest_gap | union
```

There is no literal-number operation.

Targets are also closed:

```text
position { instance_id, axis }
size     { instance_id, axis }
gap      { previous_instance_id, current_instance_id, axis }
inset    { instance_id, edge }
overlap  { first_instance_id, second_instance_id }
```

Target instances must belong to the decision. `flow`, `grid`, `scroll`,
`intrinsic`, and `platform` decisions cannot pin member positions absolutely;
they must use gap, inset, alignment, and flow relations.

Expression values are typed and bound to the target identity:

- gap reads the matching component pair and axis gap;
- inset reads the matching parent-child inset;
- size reads the matching component width or height;
- position reads the matching component-local coordinate;
- overlap reads the matching component-pair overlap rectangle.

An evidence field such as `order`, `overlap`, or another component's inset cannot
substitute for a numeric gap.

## Geometric assertions

At the original design viewport the contract includes:

- root origin and viewport size;
- exact component topology;
- policy-gated reference position and dimensions;
- sourced same-slot and cross-slot gaps measured after natural layout.

At responsive viewports the contract includes:

- exact component topology;
- positive measured geometry;
- no unintended overlap for relations that did not overlap in the design state;
- no unintended horizontal viewport overflow;
- explicit horizontal-scroll overflow scopes containing the scroll member and
  all of its component descendants;
- scroll reachability only when a scroll decision exists.

The included verifier is an algorithm test oracle. Production probe collection
and the single ICP assertion executor remain follow-up work.

## Completion gate before ICP integration

The algorithm may be considered for integration only when tests prove:

- exactly-once coordinate conversion for all supported frame spaces;
- storage-order independence and explicit sibling order;
- component and semantic Block graph closure;
- exact Block and source-node ownership;
- multi-region and descendant-union component geometry;
- same-slot and cross-slot evidence;
- axis-specific adaptive propagation;
- rejection of fixed adaptive dimensions;
- rejection of absolute flow positions;
- closed constraint targets and evidence expressions;
- fail-closed malformed containers, forbidden nested stage fields, expression
  depth, and verifier inputs;
- reference gap preservation after natural content growth;
- responsive overlap and horizontal-overflow detection;
- deterministic output and input immutability.
