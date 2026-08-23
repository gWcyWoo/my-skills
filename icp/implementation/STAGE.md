# Implementation stage

## Outcome

Implement production code from the frozen Stage 1 Blocks and Stage 2 component
lock's closed `implementation_contract`. Stage 3 must not read the IOLE source
bundle, raw rows, or original UI/interaction/API/UT/IT/E2E prose directly or
indirectly, and must not repeat Stage 2 semantic interpretation. This stage may choose target-platform primitives and file layout, but it may
not change component boundaries, page scope, semantic facts, Block ownership,
interaction graphs, API contracts, presentation relations, or source authority.

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

1. Stage 2's closed same-page contract, derived from IOLE UI, interaction, API,
   UT, IT, and E2E descriptions, owns business copy, values, validation, behavior,
   state, navigation outcomes, APIs, and documented test obligations. Stage 3
   receives the closed result, never the original prose.
2. The target project's root `common-rules.md` supplies project-wide policy only
   where the same page is silent or ambiguous. It never overrides an explicit
   same-page clause.
3. Verified Stage 1 Blocks/source facts own hierarchy, visual treatment, geometry,
   assets, and the static/dynamic/platform content classification.
4. Frozen Stage 2 definitions, instances, facts, compositions, interaction graphs,
   API contracts, and presentation usages own component boundaries and behavior/
   data contracts.
5. [Android Kotlin best practices](references/platform-best-practices/android-kotlin.md)
   fill only platform mechanics left unspecified by 1–4.

A screenshot input value is `dynamic_content`, not a validation rule. A rule from
page A never constrains page B. Platform practices cannot invent endpoints,
limits, success copy, navigation targets, or business states.

## Runtime layout

```text
.icp/implementation/
├── checklist.json
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

`begin` verifies only Stage 2's sealed `state.json`, `stage-result.json`,
`component-lock.json`, and `block-component-bindings.json` identities and hashes;
it does not invoke Stage 2, reopen `.icp/source/source-bundle.json`, or reread
original business prose. Stage 2's full verify already completed before this
boundary. Stage 3 then freezes only `modify` pages. It derives every component instance, Block, rendering source node, semantic
fact, component-bound interaction graph, API contract, interaction obligation,
presentation usage, and design reference. A source
node without a reviewed Stage 1 `content_role` fails. It also requires and freezes
the project's UTF-8 `common-rules.md`; later changes fail as stage drift. Every
codegen packet contains the exact common-rule content and hash before the advisory
platform practices. It also freezes `implementation-prompt.md`. Codebase search is
performed live by the implementing model so it can understand current symbols,
call sites, behavior, and reuse opportunities.

`begin` also freezes the complete Stage-3 checklist from the coverage universe:
plan, every obligation's RED then GREEN, code/asset coverage, compact and expanded
responsive evidence, every production visual capture including runtime probes,
frozen verification commands, and final verify. The script records nodes only
after their deterministic gate succeeds.

Every Stage-3 CLI command holds one OS-backed stage write lock through its state
transaction. A duplicate `begin` with the same platform and frozen inputs resumes
the committed stage; a `begin` interrupted before `state.json` is published
rebuilds only that uncommitted implementation directory. A lock timeout returns
`stage_busy` without publishing Stage-3 artifacts. Checklist receipts never
replace state or artifact hashes as completion authority.

## 2. Author and record the implementation plan

Copy `implementation-plan.input.json` to a separate authoring file. For every
page declare:

- one page root and source file;
- one page DTO and UI-state model;
- one mock fixture that maps into the DTO;
- an API adapter symbol whenever the page has a frozen API contract;
- constraint-driven responsive strategy;
- the complete set of frozen component instance IDs. This list is coverage only;
  rendering order comes exclusively from the composition's parent, slot, and order.

Declare one foundation-owned `runtime_probe_provider` with its production source
file, symbol, `publish_method_symbol`, and the exact app-private output path
`files/icp-runtime-probes.json`. The source must exist before capture; the capture
commands then prove that the installed production process publishes the current
state, and code coverage requires a production renderer to call that exact method,
so the declaration is not itself runtime evidence. Follow
[runtime-probe-contract.md](references/runtime-probe-contract.md) exactly.

`layout_selection_inputs` is a deterministic projection of Stage 2's bound
`layout_inputs`. Author one complete `layout_decisions` set per design state from
its decision obligations and evidence. Do not author `layout_contracts`;
`record-plan` derives them with the position/layout algorithm and freezes the
result into the plan and each page packet. A failed attempt returns the complete
structured problem set for every affected design state, so regenerate each
affected page as a whole. At most three failed whole-page attempts are recorded;
exhaustion means Stage 1 or Stage 2 must be repaired, not bypassed.

Coverage lists in the implementation plan are identity sets, not storage-order
contracts: per-page `component_instance_ids`, the lock's global
`component_instances` storage order, per-component `block_obligation_ids`,
per-interaction `component_instance_ids`, and per-case `basis_fact_ids` each
accept the same complete ID set in any order, reject duplicate/missing/unexpected
IDs with an exact sorted diff, and are normalized to the authoritative expected
order when the plan is frozen. Order-sensitive contracts — `page_keys` business
order, interaction traces, command argv, and append-only event history — stay
strict.

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

Map every frozen interaction exactly once to all bound component instances and one
production owner symbol. Map every API contract exactly once to the page adapter
file and one distinct method symbol. The adapter file is separate from both
`dto_file` and the consuming interaction/component source so a declaration cannot
masquerade as a call. An
`api_call` interaction must contain an executable call form in its production
interaction source; a declaration, comment, string, or unused method does not
complete the interaction. Runtime acceptance still comes from the integration
case observing the exact outbound request.

Before mapping code, query the live codebase once per frozen component definition
using its responsibility, owned/excluded scope, capabilities, slots, data roles,
action roles, and visible variations. Reuse a suitable public component when it
satisfies the required boundary and behavior; otherwise implement the frozen
Stage 2 component. This is a model implementation decision, not another approval
or diagnosis protocol.

For every design element with source-bound assets, including deterministic
reference crops for unexported icon components, select at least one frozen source
asset in its `asset_mappings` and name the project-relative target resource. The
selected source asset ID and SHA-256 must remain exact. Copy the original bytes;
do not redraw, approximate, or substitute an icon. Final verification requires
`source asset SHA-256 = target resource SHA-256`.
Asset-internal ownership follows only the exact Stage 1 `parent_id` chain. Node-ID
punctuation and prefixes are opaque identities, never hierarchy evidence.

Declare the real production runtime entry after querying the codebase, then one
`visual_capture_case` per design state: entry ID, package, locale, page key, the
exact collision-resistant `visual_state_id`, environment/data-only
`precondition_commands`, an entry-rooted `interaction_trace`, and one
`production_render` containing the frozen component instance, source file, symbol,
and unique root tag. Never use a transliterated display title as state identity.
Never put a terminal state selector such as `icp_state` in preconditions or cold
start, and never use a precondition to run adb, install an app, or start another
Android surface. Device configuration is read again after all preconditions and
must still equal the applied capture configuration. Do not assume the IOLE flow root is the application launcher. The trace
starts at its declared runtime entry and every step must select an exact Stage 2
interaction result edge; cross-page navigation and modal presentation are followed
without importing source-page facts into the destination. Only the exact entry
design may use an empty trace. Every other state must be reached by the real
production controls named in its frozen integration cases. Test-only code may prepare data or navigate;
it may not render a duplicate terminal UI.

The entry file/symbol is the actual launcher, deep-link handler, or navigation
coordinator; it is not required to equal the target page renderer. Declare the
initial page/design separately, keep the entry file under one execution-node owner,
and verify that its production symbol exists. A page Composable/View is not a
surrogate entry unless it truly is the codebase entry.

Each design-element mapping also carries its frozen `runtime_probe_tag` when Stage
1 contains measurable reference facts. Attach it to the actual production element,
not a preview or debug renderer. The production hierarchy publishes runtime bounds
and element identity in the app-private `files/icp-runtime-probes.json` snapshot
consumed through `run-as`. ICP derives the expected values from Stage 1; the
authored implementation plan cannot choose them. Font size and line height each
receive a deterministic `apk_resource_name`; the mapped production source must
consume that `R.dimen`, and ICP reads its literal `sp` value from the uniquely
matched clean-build APK. App-published typography cannot satisfy the gate.
Every mapped design node must have exactly one executable
`IcpBoundElement(...)` production element binding in its mapped owner source. The
same call binds the frozen obligation, component instance, owner symbol, probe tag,
font/line-height resources, and mapped Android target assets through `assetRefs` to
the real rendered content; copied files, separate tokens, comments, declarations,
no-op calls, and detached probes are not evidence.
Every live production accessibility node may own only one obligation probe. The
driver resolves the complete expected probe set in one hierarchy pass and rejects
both directions of ambiguity: one tag on multiple nodes or multiple obligation
probe tags on one node.
For opaque colors, the app payload locates the hierarchy-bound element but does
not decide pass/fail. The verifier finds the expected color in the real production
screenshot and records the exact observed pixel coordinate and RGBA value. An
exact-geometry node must cover its complete source-derived reference color footprint;
a single matching decoy pixel cannot satisfy it. Adaptive text and dynamic content
retain natural flow and require the expected color within their hierarchy-bound region.
For responsive evidence, every component occurrence exposes its unique
`occurrence_id` in the live UI hierarchy. The driver compares payload bounds with
hierarchy bounds; a detached or fabricated app-private JSON payload is not
evidence.

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
2. one complete component-bound interaction-graph item assembled from the same
   page's atomic `交互描述` facts and explicit inference bases;
3. one model-inferred scenario for every frozen component instance, derived from
   that instance's complete Stage 2 fact bindings, component contract, and page
   composition.

Every obligation records `source_kind`, exact component instance, and its complete
fact basis. Documented IT and interaction obligations remain separate even when
their meanings overlap. Model inference fills component-contract coverage but may
not replace, weaken, or invent a conflict with documented behavior. The test
command is frozen in the plan and is executed without a shell.

For Android, every case names its exact `app/src/androidTest/` test and runs that
exact case through a Gradle Android-device test task. A JVM `test...UnitTest`, a
host script, or an unfiltered device suite is development feedback, not Stage-3
integration evidence, and cannot be recorded as RED or GREEN. RED and GREEN are
accepted only when the case has a closed `runtime_test` with one launcher
`entry_tag`, ordered `preconditions`, real UI `actions`, and observable UI
`assertions`. Every step uses a closed operator, stable production tag, optional
value, and exact frozen `fact_ids`; every basis fact appears exactly once, trigger
facts stay on actions, condition/current-state facts stay on preconditions, and
behavior/result facts stay on assertions. ICP—not the implementation model—deterministically generates the
test file from that contract. The generated test launches the production package,
finds tags through Android's live accessibility hierarchy, performs the declared
input, and reads the declared result from that hierarchy.
When a case has actions, every result predicate must be false before the first
action and true after the final action; merely observing the same final state, or
observing one unrelated result change, is not transition evidence.
Every lookup is restricted to that production package and collects all matches.
`production UI tag is not unique` fails the case; the generated test never selects
the first hierarchy match.

Evidence is accepted only when this exact immutable generated file declares the selected
`class#method` and a newly generated Android JUnit result reports that exact test
failed or passed consistently with the command exit code.
The command is exactly one committed `./gradlew` wrapper, one
`connected*AndroidTest` task, and the one frozen selector. Unknown flags or tasks
are rejected. ICP asks Gradle for the selected task's live type in the same
invocation and accepts it only when Gradle identifies the exact module task as
AGP's `DeviceProviderInstrumentTestTask`. The new report must be written after
command start, carry a timestamp, and identify the device through consistent AGP
suite metadata or the canonical per-device AGP report name; that same device must
also appear in the Gradle execution output. The wrapper and test source remain
unchanged through final verification.

An interaction obligation also carries the complete five-field interaction,
component-instance bindings, outgoing graph edges, explicit terminal outcomes,
and any bound API contract.
Each visual trace step names its frozen case, interaction, and selected outcome;
ICP derives the complete ordered production action sequence from that case. The
implementation plan does not duplicate or truncate multi-action input/click/back
flows. When an edge targets another interaction, a following step must start from
that exact target; the verifier rejects disconnected same-page lists.
Its integration case drives the real trigger and observes the behavior, result, state
transition, exact outbound request, response-to-DTO mapping, and success/failure
continuation that are contract-significant.
For `api_call`, the `runtime_test` must include a `network_expectation` joined to
the exact frozen API contract: method, path, contract-significant request headers,
semantic JSON request body, allowed response status/headers/body. ICP starts an
independent HTTP recorder inside the instrumentation process before launching the
production Activity and supplies its URL through the test-only
`icp_api_base_url` entry extra. The production debug build must route the mapped
adapter through this override; release code must ignore it. The generated test
accepts the final UI assertion only after that recorder has observed and matched
the real request and returned the frozen response. App-published request JSON,
static adapter anchors, or a mocked owned adapter are not network evidence.
The recorder holds the response after observing the request. Every declared
result must still be false while that response is withheld. Only then does the
test release the response. Its JSON contains exactly one
`__ICP_RUNTIME_CANARY__`, replaced at device-test runtime with a fresh UUID that
production code cannot know beforehand; the frozen `response_probe` must read
that exact value back from the live production UI. This makes request occurrence,
response consumption, and rendered result one causal observation instead of
three unrelated passes.
For an API failure edge, the same recorder must first observe and match the real
request, prove the declared error result is still false, then close that socket
without an HTTP response. Only the resulting production error state may satisfy
the failure case. Source-level error branches and pre-existing error UI are not
evidence.

Every page also has exactly one non-API runtime Mock/DTO probe. Its frozen mock
fixture contains the same single runtime-canary placeholder, is passed through
the production debug entry as `icp_mock_payload`, and must appear at its declared
live UI result tag. The project mock file must be JSON-semantically equal to this
frozen input;
merely parsing as JSON is not evidence. API and Mock probes exercise public page
behavior. DTO class names and static call scans remain architecture/coverage
checks and can never replace these device results.

```bash
python3 <icp-skill>/implementation/scripts/implementation.py run-case \
  --project-root "<project>" --case-id "<case-id>" --phase red
```

The current case must return nonzero. The generated suite may already contain
other syntactically closed cases, but the frozen selector runs only this case and
their unimplemented behavior cannot block it. Implement the smallest vertical
slice owned by the current page node, then run the exact same command:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py run-case \
  --project-root "<project>" --case-id "<case-id>" --phase green
```

Observe GREEN before executing the next case. A passing pre-implementation test
or failing post-implementation test stops the current slice. There is no global or
page-wide all-RED prerequisite: one case may complete RED→GREEN before its sibling
starts. Final verification still requires one RED and one GREEN result for every
frozen obligation.

## 4. Code and runtime verification

Each page must render through its DTO/UI state. Remote responses and mocks adapt
to that DTO; UI code does not render transport response types. Use the frozen
component composition to choose Compose primitives and responsive placement.

Implement every `api_call` while implementing its interaction slice: trigger,
conditions, pending state, adapter method, exact request mapping, response/error
mapping, DTO update, and the next render/navigation/error interaction. Do not
defer interfaces to a separate post-page step. In Android debug builds, read the
generated test's `icp_api_base_url` launcher extra at the production entry and
inject it as the mapped adapter's base URL; do not branch around the adapter or
accept this override in release builds. For the one page Mock/DTO case, the debug
entry must route `icp_mock_payload` through the same production DTO/UI-state path
used by normal page data; release builds must ignore that extra.

Run `capture-responsive` for exactly two measured viewports per page (`compact`
and `expanded`) and reference those generated evidence files. Do not copy their
measurements into the final input. Include one actual screenshot per design state.
Authored pass/fail flags are forbidden:

```json
{
  "schema": "icp.implementation.runtime-evidence.v1",
  "implementation_plan_sha256": "<frozen hash>",
  "responsive_runs": [
    {
      "page_key": "<page-key>",
      "viewport": "compact",
      "capture_evidence": ".icp/implementation/runtime/responsive/<page-key>-compact.capture.json"
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

Generate each responsive run through that same trusted driver, once per page and
viewport:

```bash
python3 <icp-skill>/implementation/scripts/implementation.py capture-responsive \
  --project-root "<project>" \
  --page-key "<page-key>" \
  --viewport compact \
  --driver <icp-skill>/implementation/scripts/android_visual_driver.py
```

Repeat with `--viewport expanded`. Both capture commands run only after every
frozen GREEN and production code/asset preflight passes. A caller-supplied driver
is rejected. Immediately before touching device configuration, each command runs
the same Android execution transaction: inventory prior build APKs, run the
project's Gradle `clean`, prove no APK remains, then rerun one page-bound passing
AGP device test through the attested device-provider task. The transaction hashes
every APK produced after that clean and every APK actually installed for the
production package; each installed hash must resolve to exactly one artifact from
this build. It records the clean receipt, task, test source, wrapper, device
result, build APK inventory, and installed identity in the capture evidence.
Each responsive command then cold-starts the production entry, executes
the frozen interaction trace, reads app-private measurements with `run-as`, binds
every occurrence and its bounds to the live UI hierarchy, captures the real
screenshot, restores the exact device configuration, and completes only its own
checklist node with the generated run hash.

When multiple Android devices are online, pass `--device-serial <adb-serial>` to
every `run-case` invocation and both capture commands. ICP passes the selection to
the AGP device-provider task through its subprocess-only `ANDROID_SERIAL`
environment and passes `--serial` only to the trusted adb driver; `--serial` is
not a Gradle option. The driver verifies that serial against live `adb devices`;
environment variables cannot replace the adb binary or device.

The trusted skill driver snapshots effective size/density plus whether each is an override,
locale, font scale, and navigation mode. In a `finally` path it restores the exact
snapshot. The first snapshot for a capture identity is frozen; a retry whose live
device configuration differs fails before applying any change instead of silently
restoring the device to an older configuration. ICP converts the emulator to the reference pixel size at
`160 × logical_scale` density using the exact frozen rational scale (including
values such as `3/2`) and applies the declared locale. It cold-starts the
normal launcher with no terminal-state extra, proves the Activity/process/runtime
are healthy and the resumed Activity belongs to the frozen package, executes the
frozen production interaction trace, then attests the
exact `visual_state_id` and production root tag in the real UI. It reads the
runtime-probe payload from nodes owned by that same package and production hierarchy and compares exact-mode
values with the immutable Stage 1-derived assertion. Intrinsic/container bounds
come from the live hierarchy, opaque colors from captured pixels, and font metrics
from the clean-build APK at the reference viewport; text and dynamic
content bounds are measured in adaptive mode so natural wrapping is not forced.
Missing probes, payload bounds that disagree with the live hierarchy, duplicate identities, invalid adaptive geometry, or exact-value
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
expanded sizes. For every design state they record unique runtime occurrences,
component topology and bounds, viewport coordinate space, safe insets, actual
system-bar visibility/bounds, device configuration, and screenshot bytes. For
every frozen scroll obligation the driver performs physical swipes until the live
hierarchy stops changing, observes all required component occurrences, and
restores the starting hierarchy. App-reported scroll extents and offsets are not
completion evidence. The shared layout executor
computes clipping, overlap, horizontal overflow, scroll reachability, topology,
and component presence from those measurements, consuming the frozen horizontal
scroll scopes including their descendants. It rejects authored `no_clip`,
`operable`, or similar verdicts. MAE remains diagnostic only for the reference
capture.

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

The final verifier completes checklist nodes only as their real validations pass.
If any node is absent or an upstream evidence hash changed, it stops at the
earliest pending node and requires every dependent node to be revalidated before
Stage 3 can become complete. The final implementation state binds the completed
checklist hash. It remains non-complete until `stage.verify` records the exact
Stage-result hash; IOLE independently requires that completed checklist and hash
before review writeback.

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

`verify` consumes capture-command receipts; it never creates them. Every responsive
run and visual capture must already have a completed checklist node whose evidence
hash equals the exact generated run/capture artifact. A caller-authored JSON object,
a copied reference PNG, or a valid-looking measurement payload cannot complete a
runtime node.

## Experiment discipline

For prompt/contract testing in an existing project, use an isolated worktree from
the intended baseline. Before each new experiment, discard only that experiment's
tracked edits with `git checkout`/`git restore` and remove only run-owned untracked
files. Preserve project-owned `common-rules.md` and project memory. Preserve
`.icp/extract` and `.icp/component-design` unless the user explicitly asks to
regenerate their owning stages. On the first real
failure, stop and report the exact failed gate and evidence; do not patch the
generated application and continue in the same experiment.
