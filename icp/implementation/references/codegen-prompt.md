# ICP implementation prompt

You are implementing production code. Stage 1 and Stage 2 are already verified;
this stage writes code and tests only. Treat this packet as a closed, page-local
contract and follow `source_authority` exactly. Never borrow a rule from another
page.

Business authority order is: same-page IOLE descriptions, then project
`common_rules` only where that page is silent, then frozen Stage 1 visual data,
then frozen Stage 2 component semantics. `platform_best_practices` fills only
remaining platform mechanics and must not invent or override business behavior.

## Required sequence

1. Read the entire packet before editing. Reconstruct the full join for the page:
   `Block -> design_instance_id -> component_instance_id -> component_id`,
   including parent/slot composition, design elements, semantic facts, and every
   interaction obligation. Implement from the bound component data; do not code
   from a screenshot alone. Respect the frozen execution node and `file_owners`:
   write only files owned by the current node, while reading completed dependency
   nodes as needed. A shared or app-level file has one owner; never copy or edit it
   from a consuming page node.
2. Query the live codebase for every `component_id` using its responsibility,
   `owns`, `excludes`, capabilities, slots, data roles, action roles, and visible
   variation. Reuse an existing public component when it satisfies the required
   boundary and behavior; otherwise implement the frozen Stage 2 component. Make
   this decision from the current codebase, not from a frozen search catalog.
3. Work one strict vertical case at a time for only the current page node. Create
   that planned integration test from `integration_obligations`, obtain a valid
   RED caused by missing behavior, implement only that behavior, and obtain GREEN
   with the exact same command before starting its sibling case. Future page-node
   test files remain unmaterialized until their node runs, so module compilation
   cannot make one page depend on unfinished tests from another page. The frozen
   complete set has three explicit `source_kind` values:
   exact `IT` description facts, exact `交互描述` facts, and one model-inferred
   component-contract scenario per frozen component instance. Read each inferred
   component's complete fact basis and composition before choosing its scenario;
   do not use inference to replace or weaken either documented source. Across the
   node's successive RED/GREEN slices, implement all states, conditions, triggers,
   behaviors, validation, navigation outcomes, DTO/mock/API adaptation, and
   presentation usages.
4. Implement every Stage 1 `design_element` and exact source asset through its
   mapping. Use the Block hierarchy, geometry, relationships, background, border,
   spacing, typography, content role, and component parent/slot layout. Make the
   page constraint-driven, inset-safe, and responsive at compact and expanded
   sizes. Attach each frozen `runtime_probe_tag` to the actual production element
   that renders the mapped design node and publish its runtime bounds, color,
   font size, and line height from that same hierarchy to the app-private
   `files/icp-runtime-probes.json` payload consumed by the skill driver. Before capture, audit the
   complete design-element obligation set against the code; an anchor is a join
   key, not proof of rendering. Do not create a debug-only duplicate renderer,
   preview screen, dialog, or composable for screenshots. Test-only code may seed
   data or navigate through the production entry, but it may not render the
   terminal UI.
5. Capture every design state through its deterministic `visual_state_id`. The
   driver must cold start the installed app through its normal launcher. Never inject a terminal `icp_state`
   or another debug selector into that launch. Environment/data preconditions may
   run before launch; then execute the frozen production interaction trace for
   the same page, attest both the state ID and the
   production renderer's unique root tag, and read the runtime probes from that
   hierarchy. The target Activity must be resumed, the process alive, and logcat
   free of fatal Android runtime exceptions and ANRs. Then capture at the exact
   frozen reference viewport and compare it with the frozen reference. At that
   viewport only, automatically compare Stage 1-derived intrinsic/container
   bounds, color, font size, and line height with the runtime probe values. Text
   and dynamic-content bounds are measured for structure and flow but remain
   adaptive, so natural wrapping is not forced to the design tool's line breaks.
   Human-authored fidelity booleans are forbidden. Record
   whole-image MAE and regional differences as diagnostics only; neither is a
   completion threshold and neither may override correct interaction state or
   adaptive flow.
6. For each visual failure, use the generated difference report to trace the
   affected design-element obligation through `source_node_id`, `block_id`, and
   its code mapping. If the frozen data is correct, fix the implementation and
   rerun coverage, interaction, responsive, and visual verification. If Stage 1
   grouping or design data is wrong or incomplete, stop changing code, return to
   the Stage 1 process with the exact design, Block, source node, and bad field,
   then rerun Stage 2 before resuming implementation. Analyze and handle the
   errors yourself; do not wait for a separate diagnosis protocol.

## Reference fidelity versus responsive behavior

The reference artboard is one calibration viewport, not a fixed runtime layout
contract. Never apply screenshot MAE as a pass/fail rule. At non-reference sizes
verify natural text reflow, no clipping, no overlap,
no horizontal overflow, reachable scroll content, operable controls, correct
system-bar behavior, and safe insets.

Use parent constraints and content-driven measurement. A fixed dimension is valid
only when the frozen design describes an intrinsically fixed element such as an
icon, touch target, or control. Do not copy text, card, content-section, or page
heights from one screenshot merely to align pixels. Do not insert line breaks or
branch padding, offsets, letter spacing, font width, or geometry by locale, copy
ID, sample text, or design state to force the reference wrapping. Text must wrap
naturally from the selected project typography and available component width.

Repair a failed source-bound reference assertion only when the change remains valid
for the responsive contract. Do not move naturally wrapped downstream content to
match fixed screenshot coordinates. If reducing diagnostic MAE would require a
content-specific or viewport-specific layout exception, keep the responsive
implementation and report the remaining difference; never optimize the score by
weakening natural layout behavior. Interaction tests, not screenshot state, own
checked, enabled, disabled, selected, loading, and other behavior-driven states.

Completion means all frozen design elements are implemented, every Stage 2
IT/interaction/model-inference integration obligation has RED/GREEN evidence,
verification commands succeed,
every component has adaptive-layout evidence, both responsive-behavior runs pass,
and reference-viewport color, component structure, spacing, and font-size checks
pass. MAE remains diagnostic.
