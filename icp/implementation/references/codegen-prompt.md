# ICP implementation prompt

You are implementing production code. Stage 1 and Stage 2 are already verified;
this stage writes code and tests only. Treat this packet as a closed, page-local
contract. Never request, read, or reconstruct the IOLE source bundle, raw rows,
original UI/interaction/API/UT/IT/E2E prose, quotes, or source spans. Never borrow
a rule from another page and never reinterpret business semantics in this stage.

Business authority order is: the closed same-page Stage 2 contract, then project
`common_rules` only where that page is silent, then frozen Stage 1 visual data,
then frozen Stage 2 component semantics. `platform_best_practices` fills only
remaining platform mechanics and must not invent or override business behavior.

## Required sequence

1. Read the entire packet before editing. Reconstruct the full join for the page:
   `Block -> design_instance_id -> component_instance_id -> component_id`,
   including parent/slot composition, design elements, semantic facts, the complete
   component-bound `interaction_graph`, API contracts, and every interaction
   obligation. Implement from the bound component data; do not code
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
   that planned `runtime_test` mapping from `integration_obligations`: declare the
   launcher entry tag, ordered preconditions, real UI actions, and observable UI
   assertions; bind every step to its exact frozen facts. Do not write or edit the
   Android test body—ICP deterministically generates and freezes it. Obtain a
   valid RED caused by missing production behavior, implement only that behavior,
   and obtain GREEN with the exact same command before starting its sibling case.
   Generated lookups are restricted to the production package and require exactly
   one live accessibility node. `production UI tag is not unique` is a hard
   failure; never rely on the first hierarchy match.
   For a case with actions, each declared result predicate must be unsatisfied
   before the first action and satisfied after the last action. Do not choose an
   assertion that is already true in the initial state.
   Other generated tests are not executed by this case's exact selector, so there
   is no global all-RED prerequisite. The frozen
   complete set has three explicit `source_kind` values:
   exact Stage 2-frozen `IT` obligations, complete Stage 2 `interaction_description` graph items, and one model-inferred
   component-contract scenario per frozen component instance. Read each inferred
   component's complete fact basis and composition before choosing its scenario;
   do not use inference to replace or weaken either documented source. Across the
   node's successive RED/GREEN slices, implement all states, conditions, triggers,
   behaviors, validation, navigation outcomes, DTO/mock/API adaptation, and
   presentation usages. Treat one graph interaction as one causal unit. When its
   `condition` and current `state` facts exist, put them only in preconditions;
   put `trigger` facts only in actions and `behavior`/`result` facts only in
   assertions. In any visual trace step, reference that generated case and let ICP
   derive its complete ordered input/click/back action sequence; do not duplicate
   or truncate it. Follow the selected edge target exactly before adding another
   step. When its behavior is `api_call`, call the exact mapped adapter
   method in that same slice,
   assert the contract-significant outbound request, map response/error shapes to
   the page DTO/UI state, and continue through its success/failure graph edges or
   preserve an explicitly reasoned terminal outcome. Put transport code in the
   mapped `api_adapter_file`, not in the DTO file. A declared, commented, string-
   mentioned, or uncalled adapter method is incomplete.
   Give that case a `network_expectation` matching its frozen API method/path,
   significant request headers/body, and an allowed response status/body. On
   Android, the ICP-generated instrumentation test starts a device-local recorder
   and passes its base URL as `icp_api_base_url`. The production debug entry must
   inject that URL into the same mapped adapter used by normal execution; release
   builds must ignore the override. Do not mock the adapter or publish request
   claims from app code: GREEN requires the independent recorder to receive the
   request before the final production UI assertion.
   The recorder deliberately withholds its response first. The declared result
   must remain absent/false until the response is released. Its body contains one
   `__ICP_RUNTIME_CANARY__` replaced by a fresh runtime UUID; map the response
   through the normal production DTO/UI-state path and render that exact value at
   `response_probe.target_tag`. A hard-coded or request-triggered result cannot
   pass. For a failure edge, ICP instead holds the matched request, proves the
   error result is absent, then disconnects without a response; render the real
   production error state only after that transport failure. For each page's one `mock_expectation`, route the debug-only
   `icp_mock_payload` through the same normal DTO/UI-state path and render its
   runtime canary at the declared probe. The source mock fixture must remain
   JSON-semantically equal to the frozen mock body. Release builds ignore both test
   extras.
4. Implement every bound `design_element.design_facts` and exact source asset
   through its mapping. `design_facts` is the sole visual projection: geometry,
   backgrounds, borders, radii, typography, and asset relations. Use the frozen
   page `layout_contracts` for component topology, parent/slot/order, local
   geometry, dimension policy, gaps, overflow scopes, and responsive assertions;
   never reopen or reconstruct Stage 1 data. Make the
   page constraint-driven, inset-safe, and responsive at compact and expanded
   sizes. Attach each frozen `runtime_probe_tag` to the actual production element
   that renders the mapped design node and publish its runtime bounds, color,
   font size, and line height from that same hierarchy to the app-private
   `files/icp-runtime-probes.json` payload consumed by the skill driver. For each
   mapped design node, construct the actual renderer through exactly one production element binding:
   `IcpBoundElement(obligationId = ..., componentInstanceId = ..., ownerSymbol = ...,
   probeTag = ..., fontSizeRes = ..., lineHeightRes = ..., assetRefs = ...) { ... }`.
   The frozen identities, exact `R.dimen` resources, and every mapped Android
   `R.<type>.<name>` target asset belong in that same executable call; its content
   block is the real production element. A declaration, no-op
   marker, comment, detached probe, or resource reference elsewhere does not
   satisfy the mapping.
   One production accessibility node may own only one obligation probe. Never put
   multiple frozen `runtime_probe_tag` values on one node; ICP audits the complete
   expected probe set against the live hierarchy in one pass.
   For each
   responsive design state also publish unique component occurrences with exact
   topology/bounds, viewport-space coordinates, safe insets, system-bar bounds,
   and raw scroll viewport/content extents plus observed offsets. Do not publish
   `no_clip`, `operable`, or any other self-certified verdict. Before capture, audit the
   complete design-element obligation set against the code; an anchor is a join
   key, not proof of rendering. Do not create a debug-only duplicate renderer,
   preview screen, dialog, or composable for screenshots. Test-only code may seed
   data or navigate through the declared production entry, but it may not render the
   terminal UI.
   Implement the plan's foundation-owned `runtime_probe_provider` in production
   source and call its frozen `publish_method_symbol` from every production page
   renderer after layout/state changes. Publish the exact shape in
   `runtime-probe-contract.md`. Attach every responsive `occurrence_id` to the corresponding live UI
   node; its published bounds must be the same bounds exposed by the device UI
   hierarchy. Static tags, comments, copied reference values, and a JSON file not
   attached to the currently resumed hierarchy are traceability data, not runtime
   evidence.
5. Capture every design state through its deterministic `visual_state_id`. The
   runtime entry file/symbol must be the real launcher, deep-link handler, or
   navigation coordinator found in the codebase; its initial page/design is
   declared separately and must not be replaced by a screenshot-only page
   renderer. The driver must cold start the installed app through its normal launcher. Never inject a terminal `icp_state`
   or another debug selector into that launch. Environment/data preconditions may
   run before launch but may not invoke adb, install an app, or start another
   Android surface; ICP rechecks the applied device configuration afterward. Then execute the frozen entry-rooted production interaction trace
   by selecting the exact Stage 2 result edge at every step, including real
   cross-page navigation or presentation. Attest both the state ID and the
   production renderer's unique root tag, and read the runtime probes from that
   hierarchy. The target Activity must be resumed, the process alive, and logcat
   free of fatal Android runtime exceptions and ANRs. Then capture at the exact
   frozen reference viewport and compare it with the frozen reference. At that
   viewport only, automatically compare Stage 1-derived intrinsic/container
   bounds with the live hierarchy. For every `font_size` and `line_height`
   assertion, declare the exact `apk_resource_name` as an Android `dimen` with a
   literal `sp` value and make the mapped production text consume that exact
   `R.dimen` resource (Compose converts `dimensionResource` to `TextUnit` through
   the current `Density`; Views use the compiled resource). ICP reads the value from the current clean-build APK and binds the
   result to that APK's SHA-256; app-published typography values are ignored. For opaque
   color, use the hierarchy-bound region of the actual production screenshot;
   the app's claimed color cannot pass the gate. For exact-geometry nodes, the
   production pixels must cover the complete source-derived reference color footprint;
   one matching decoy pixel is insufficient. Adaptive text and dynamic-content
   nodes retain natural flow and require the expected color in their bound live region. Text
   and dynamic-content bounds are measured for structure and flow but remain
   adaptive, so natural wrapping is not forced to the design tool's line breaks.
   Human-authored fidelity booleans are forbidden. Record
   whole-image MAE and regional differences as diagnostics only; neither is a
   completion threshold and neither may override correct interaction state or
   adaptive flow.
   Scroll reachability is also driver-owned: expose the frozen occurrence tags,
   but do not publish a pass flag or a trusted content extent. The driver follows
   each frozen scroll obligation to the physical end, observes every required
   occurrence, and restores the initial position.
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
IT/interaction-graph/model-inference integration obligation has RED/GREEN evidence,
verification commands succeed,
every component has adaptive-layout evidence, both responsive-behavior runs pass,
and reference-viewport color, component structure, spacing, and font-size checks
pass. MAE remains diagnostic.
