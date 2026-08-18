# Implementation stage

## Outcome

Implement production code from the frozen Stage 1 Blocks and Stage 2 component
lock. This stage may choose target-platform primitives and file layout, but it may
not change component boundaries, page scope, semantic facts, Block ownership,
presentation relations, or source authority.

The implementation stage is a prompt plus deterministic scripts:

- the model reads one page `codegen-packet` and writes the planned production and
  test files;
- `begin` freezes the skill-owned implementation prompt; the model queries the
  current codebase while implementing and reuses suitable public components;
- scripts freeze the complete obligation universe, validate the plan, enforce
  case-local RED before its implementation and GREEN afterward, check every code anchor, execute
  lint/build/integration commands, require compact and expanded runtime evidence,
  and calculate diagnostic PNG MAE.

Whole-image MAE on 0–255 RGB channels is diagnostic only. It never controls stage
completion because authoritative interaction state and natural platform text flow
may intentionally differ from a static artboard. At the exact reference viewport,
completion requires color, component-structure, spacing, and font-size checks.
Compact, expanded, and other sizes require adaptive-behavior checks. All gates are
exact identities, complete sets, command exit status, or boolean runtime checks.

## Authority order

1. Same-page IOLE UI, interaction, API, UT, IT, and E2E descriptions own business
   copy, values, validation, behavior, state, navigation outcomes, and APIs.
2. The target project's root `common-rules.md` supplies project-wide policy only
   where the same page is silent or ambiguous. It never overrides an explicit
   same-page clause.
3. Verified Stage 1 Blocks/source facts own hierarchy, visual treatment, geometry,
   assets, and the static/dynamic/platform content classification.
4. Frozen Stage 2 definitions, instances, facts, compositions, and presentation
   usages own component boundaries and behavior/data contracts.
5. [Android Kotlin best practices](references/platform-best-practices/android-kotlin.md)
   fill only platform mechanics left unspecified by 1–4.

A screenshot input value is `dynamic_content`, not a validation rule. A rule from
page A never constrains page B. Platform practices cannot invent endpoints,
limits, success copy, navigation targets, or business states.

## Runtime layout

```text
.icp/implementation/
├── coverage-universe.json
├── common-rules.md
├── platform-best-practices.md
├── implementation-prompt.md
├── implementation-plan.input.json
├── implementation-plan.json
├── codegen-packets/<page-key>.json
├── tdd-evidence.json
├── implementation-manifest.json
├── runtime-evidence.json
├── visual-difference-report.json
├── stage-result.json
└── state.json
```

Do not edit computed artifacts. If a gate identifies a Stage 1 or Stage 2 defect,
stop and repair that owning stage; do not compensate in generated code.

## 1. Freeze the implementation universe

```bash
python3 <icp-skill>/implementation/scripts/implementation.py begin \
  --project-root "<project>" \
  --platform android-kotlin
```

`begin` reruns live Component Design verification and freezes only `modify`
pages. It derives every component instance, Block, rendering source node, semantic
fact, interaction obligation, presentation usage, and design reference. A source
node without a reviewed Stage 1 `content_role` fails. It also requires and freezes
the project's UTF-8 `common-rules.md`; later changes fail as stage drift. Every
codegen packet contains the exact common-rule content and hash before the advisory
platform practices. It also freezes `implementation-prompt.md`. Codebase search is
performed live by the implementing model so it can understand current symbols,
call sites, behavior, and reuse opportunities.

## 2. Author and record the implementation plan

Copy `implementation-plan.input.json` to a separate authoring file. For every
page declare:

- one page root and source file;
- one page DTO and UI-state model;
- one mock fixture that maps into the DTO;
- an API adapter symbol whenever the page has an `api_dependency` fact;
- constraint-driven responsive strategy;
- the complete set of frozen component instance IDs. This list is coverage only;
  rendering order comes exclusively from the composition's parent, slot, and order.

Also declare a topological execution DAG with exactly one `foundation` node, one
`page` node per modify page, and one final `flow-integration` node. Assign every
planned production, test, asset, manifest, and navigation-entry file to exactly one
node in `file_owners`. Shared components, shared assets, and app-wide configuration
belong to `foundation`; page-local code and a distinct page-local test file belong
to that page node; cross-page navigation and final entry wiring belong to
`flow-integration`. Dependencies may read an owner's files but never write them.
This is single-writer/multi-reader ownership; do not split one page across workers
merely because its files have different types.

Map every component instance, Block, design element, semantic fact, interaction
test, and presentation usage exactly once. Component selection must follow the
whole page composition and platform morphology. Keep the generated `ICP:*`
anchors beside the code that implements their obligations; anchors are the
auditable join, while build/runtime/visual evidence proves they are not enough by
themselves.

Before mapping code, query the live codebase once per frozen component definition
using its responsibility, owned/excluded scope, capabilities, slots, data roles,
action roles, and visible variations. Reuse a suitable public component when it
satisfies the required boundary and behavior; otherwise implement the frozen
Stage 2 component. This is a model implementation decision, not another approval
or diagnosis protocol.

For every design element with exported assets, select at least one frozen source
asset in its `asset_mappings` and name the project-relative target resource. The
selected source asset ID and SHA-256 must remain exact. Copy the original bytes;
do not redraw, approximate, or substitute an icon. Final verification requires
`source asset SHA-256 = target resource SHA-256`.

Declare one `visual_capture_case` per design state: package, locale, page key, the
exact collision-resistant `visual_state_id`, environment/data-only
`precondition_commands`, a same-page `interaction_trace`, and one
`production_render` containing the frozen component instance, source file, symbol,
and unique root tag. Never use a transliterated display title as state identity.
Never put a terminal state selector such as `icp_state` in preconditions or cold
start. A non-primary state must be reached by clicking the real production controls
named in its frozen integration cases. Test-only code may prepare data or navigate;
it may not render a duplicate terminal UI.

Each design-element mapping also carries its frozen `runtime_probe_tag` when Stage
1 contains measurable reference facts. Attach it to the actual production element,
not a preview or debug renderer. The production hierarchy publishes runtime bounds,
color, font size, and line height for those tags in the app-private
`files/icp-runtime-probes.json` snapshot consumed through `run-as`. ICP derives the
expected values from Stage 1; the authored implementation plan cannot choose them.

```bash
python3 <icp-skill>/implementation/scripts/implementation.py record-plan \
  --project-root "<project>" \
  --plan "<authored-plan.json>"
```

Read each generated page packet completely before writing its code. Do not read a
different page's facts as authority. Each packet contains the frozen prompt and
the complete `Block -> design instance -> semantic component instance -> final
component -> parent/slot` join. Follow the prompt in order: codebase reuse search,
interaction tests, production implementation, complete design-element audit, then
visual comparison and correction.

## 3. Strict interaction TDD

Freeze every planned integration obligation before production implementation. The
obligation set is the exact union of three sources:

1. atomic facts backed by the same page's `IT` description;
2. atomic condition/state/trigger/behavior facts backed by `交互描述`;
3. one model-inferred scenario for every frozen component instance, derived from
   that instance's complete Stage 2 fact bindings, component contract, and page
   composition.

Every obligation records `source_kind`, exact component instance, and its complete
fact basis. Documented IT and interaction obligations remain separate even when
their meanings overlap. Model inference fills component-contract coverage but may
not replace, weaken, or invent a conflict with documented behavior. The test
command is frozen in the plan and is executed without a shell.

```bash
python3 <icp-skill>/implementation/scripts/implementation.py run-case \
  --project-root "<project>" --case-id "<case-id>" --phase red
```

The current case must return nonzero. Materialize only that case's page-scoped test;
future page tests remain unmaterialized so the platform build cannot compile or
block on them. Implement the smallest vertical slice owned by the current page
node, then run the exact same command:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py run-case \
  --project-root "<project>" --case-id "<case-id>" --phase green
```

Observe GREEN before materializing the next case. A passing pre-implementation test
or failing post-implementation test stops the current slice. There is no global or
page-wide all-RED prerequisite: one case may complete RED→GREEN before its sibling
starts. Final verification still requires one RED and one GREEN result for every
frozen obligation.

## 4. Code and runtime verification

Each page must render through its DTO/UI state. Remote responses and mocks adapt
to that DTO; UI code does not render transport response types. Use the frozen
component composition to choose Compose primitives and responsive placement.

Create runtime evidence with exactly two boolean-responsive runs per page
(`compact` and `expanded`) and one actual screenshot per design state:

```json
{
  "schema": "icp.implementation.runtime-evidence.v1",
  "implementation_plan_sha256": "<frozen hash>",
  "adaptive_components": [
    {
      "component_instance_id": "<component-instance-id>",
      "constraint_driven": true,
      "content_adaptive": true,
      "no_content_specific_geometry": true
    }
  ],
  "responsive_runs": [
    {
      "page_key": "<page-key>",
      "viewport": "compact",
      "evaluation_scope": "responsive_behavior",
      "width": 360,
      "height": 800,
      "renders": true,
      "natural_text_reflow": true,
      "no_clip": true,
      "no_overlap": true,
      "no_horizontal_overflow": true,
      "content_reachable": true,
      "controls_operable": true,
      "system_bars_correct": true,
      "insets_safe": true
    }
  ],
  "visual_runs": [
    {
      "design_name": "<design>",
      "actual_screenshot": ".icp/implementation/runtime/<design>.png",
      "capture_evidence": ".icp/implementation/runtime/<design>.capture.json"
    }
  ]
}
```

Generate each screenshot through the reversible capture command:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py capture-visual \
  --project-root "<project>" \
  --design-name "<design>" \
  --driver <icp-skill>/implementation/scripts/android_visual_driver.py
```

The driver snapshots effective size/density plus whether each is an override,
locale, font scale, and navigation mode. In a `finally` path it restores the exact
snapshot. ICP converts the emulator to the reference pixel size at
`160 × logical_scale` density and applies the declared locale. It cold-starts the
normal launcher with no terminal-state extra, proves the Activity/process/runtime
are healthy, executes the frozen production interaction trace, then attests the
exact `visual_state_id` and production root tag in the real UI. It reads the
runtime-probe payload from that same production hierarchy and compares exact-mode
values with the immutable Stage 1-derived assertion. Intrinsic/container bounds,
colors, and font metrics are exact at the reference viewport; text and dynamic
content bounds are measured in adaptive mode so natural wrapping is not forced.
Missing probes, duplicate identities, invalid adaptive geometry, or exact-value
mismatches fail before screenshot comparison. Only after those gates does it capture the
full long artboard through an extended viewport, converts the PNG back to the
frozen reference dimensions, and records exact restoration evidence. If capture
or restore fails, or the cold-start gate fails, the design has no valid visual run.

This conversion is only the reference-viewport visual-fidelity run. It checks the
reference's color, component structure/bounds, spacing, font sizes, and line height
from deterministic runtime measurements. Runtime evidence contains only the
screenshot and generated capture-evidence path; human-authored fidelity booleans
are invalid.
It is not a runtime geometry template. Responsive runs use their own compact and
expanded sizes and must prove natural text reflow, no clipping or overlap, no
horizontal overflow, reachable scroll content, operable controls, correct system
bars, and safe insets. Every frozen component instance must independently report
constraint-driven, content-adaptive measurement with no locale/copy/sample-specific
geometry. MAE is recorded only as a diagnostic for the reference capture.

Actual screenshots and generated capture evidence must be project-relative. Then
run:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py verify \
  --project-root "<project>" \
  --evidence "<runtime-evidence.json>"
```

Verification requires all code symbols and anchors, valid DTO mock fixtures,
exact original-asset hashes at target resources, complete TDD evidence, successful
planned lint/build/integration commands, both responsive runs, exact device
conversion/restoration evidence, the production-path interaction/root attestation,
complete adaptive-component evidence, and passing Stage 1-bound reference-viewport
measurements.

Reference geometry may fix intrinsically sized visuals and controls, but must not
be copied into text, card, section, or page heights merely to match one screenshot.
Do not force wrapping with inserted line breaks or locale/copy-ID-specific font,
letter-spacing, padding, offset, or geometry branches. Text wrapping must follow
the selected project typography and available component width. A visual repair is
valid only if compact and expanded behavior remains correct; never trade responsive
behavior for a lower diagnostic MAE. Interaction tests own checked, enabled,
disabled, selected, and other behavior-driven states; a static design state cannot
override them.

Visual comparison evaluates every design and writes `visual-difference-report.json`
with diagnostic MAE, exact RGB difference bounds, and complete
Block/design-element/code joins. Natural wrapping and resulting downstream flow
are not visual failures. The model fixes code only when a source-bound measurement
fails. If the report proves Stage 1 data or grouping is wrong, stop code
changes, return to Stage 1 with the exact design/Block/source-node/field, repair
the owning data, rerun Stage 2, then resume Stage 3. No separate diagnosis command,
approval, repair packet, or state lock is required.

## Experiment discipline

For prompt/contract testing in an existing project, use an isolated worktree from
the intended baseline. Before each new experiment, discard only that experiment's
tracked edits with `git checkout`/`git restore` and remove only run-owned untracked
files. Preserve project-owned `common-rules.md` and project memory. Preserve
`.icp/extract` and `.icp/component-design` unless the user explicitly asks to
regenerate their owning stages. On the first real
failure, stop and report the exact failed gate and evidence; do not patch the
generated application and continue in the same experiment.
