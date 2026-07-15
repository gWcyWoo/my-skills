# iFF Visual Task Self-Check

- Rules: `/Users/Woo/.claude/skills/iFF/SKILL.md`
- Scope: visual correctness, shared-component abstraction and cross-file reuse, incremental feature states/revisions, and model-token efficiency.
- Reviewed implementation: `SCRIPTS_INDEX.md`, `SKILL.md`, `scripts/capture_runtime_screenshot.py`, `scripts/check_done_gate.py`, `scripts/check_component_contract.py`, `scripts/check_feature_manifest.py`, `scripts/check_render_fidelity.py`, `scripts/check_shared_component_consumers.py`, `scripts/check_state_change_scope.py`, `scripts/check_visual_board.py`, `scripts/check_visual_feature.py`, `scripts/check_visual_manifest.py`, `scripts/detect_shared_components.py`, `scripts/gen_layout_trace_test.py`, `scripts/generate_canvas.py`, `scripts/make_component_model_packet.py`, `scripts/make_render_plan.py`, `scripts/make_visual_gate_report.py`, `scripts/make_visual_model_packet.py`, `scripts/make_worker_prompt.py`, `scripts/reconcile_feature.py`, `scripts/register_shared_component.py`, `scripts/verify_pipeline_scripts.py`, and `scripts/visual_diff.py`.
- Reviewed evidence: all files under `iFF/tests/`, the full Python test suite, pipeline preflight, diff check, and the real Flutter canvas self-test.

## Visual correctness

| Boundary | Result | Evidence |
|---|---|---|
| Every board has independent, current evidence | ✅ | `check_visual_board.py` requires and hashes reference, actual, fidelity, diff, and manifest; missing/stale inputs fail. |
| A hand-edited report cannot hide current defects | ✅ | The checker recomputes hard failures from the five current inputs through the same `classify_hard_failures` function used by the report generator. |
| Hard visual categories are explicit | ✅ | Viewport, structured runtime fidelity, asset-shape channel, shape regions, asset/text real defects, provenance, and reference-derived actual are hard failures. |
| SSIM is token-cheap diagnosis, not a false cross-engine blocker | ✅ | SSIM remains in diagnostics; hard categories are independently classified and documented consistently in `SKILL.md`. |
| Every feature state is visually proved | ✅ | `check_visual_feature.py` maps each manifest state to its own board and runs the board gate. |

## Shared components

| Boundary | Result | Evidence |
|---|---|---|
| Common skeleton is separated from business variation | ✅ | Contracts require invariants, variants, business inputs, UI state, events, and controlled slots. |
| Raw style parameters cannot turn a component into a shell | ✅ | Color, spacing, size, typography, border, decoration, gradient, shadow, opacity, and alignment-style inputs are rejected. |
| Slots preserve structure | ✅ | Every slot must declare non-empty semantic `allowedRoles`. |
| Shared UI stays out of feature data/routing | ✅ | Contract source validation rejects configured repository/router/DTO dependencies, including during registration. |
| Structural similarity is not mistaken for semantic identity | ✅ | Structure-only matches remain unresolved candidates; the output contains only differing variation positions for model judgment. |
| Cross-file optional nodes map safely | ✅ | Confirmed aliases use role-to-canonical-node plus role-to-index maps; invalid mappings fail visibly. |
| Component edits invalidate all consumers | ✅ | Registry v2 binds widget and contract hashes; consumer gates must pass, contain both hashes, and have current five-input board evidence. |

## Incremental states and revisions

| Boundary | Result | Evidence |
|---|---|---|
| Existing route + new state becomes a variant | ✅ | `reconcile_feature.py` emits `variant:<feature>`. |
| Existing state design becomes a revision | ✅ | Reconciliation emits `revision:<feature>:<state>`. |
| State B cannot overwrite state A or shared page files | ✅ | Feature manifests require state canvas/generated ownership, reject overlap/protected writes, and `check_state_change_scope.py` validates the actual changed-file list. |
| Ownership cannot be skipped at done time | ✅ | `check_done_gate.py` requires a feature manifest plus current state/changed-file evidence, validates ownership, and validates all state boards. |

## Token efficiency

| Boundary | Result | Evidence |
|---|---|---|
| Deterministic work stays in scripts | ✅ | Parsing, signatures, variation diffs, hashes, thresholds, stale detection, ownership, and action selection are script outputs. |
| Model receives one bounded current action | ✅ | `make_component_model_packet.py` exposes one component candidate; `make_visual_model_packet.py` exposes one candidate/model field/hard failure/top repair. Both have an 8KB hard limit. |
| Large visual artifacts are not model inputs | ✅ | Board prompt generates and reads only `visual_model_packet.json`; full scene/render/diff/repair files stay script-consumed. |

## Verification

| Check | Result | Evidence |
|---|---|---|
| Strict red → green regressions | ✅ | 231 Python tests pass; the visual hardening behaviors were each observed failing before their minimal implementation. |
| Pipeline availability | ✅ | `verify_pipeline_scripts.py` reports all 75 required scripts present. |
| Real Flutter visible-layer path | ✅ | Temporary Flutter app ran both bundled corpus cases through generate canvas → analyze → widget test → trace → fidelity; 11 nodes rendered and passed. |
| Android target runtime | ✅ | Pixel 8 API 35 ran the generated Flutter app at 750x1200; screenshot, bound manifest, and app-process log were inspected and passed. |
| Patch hygiene | ✅ | `git diff --check` passes; the temporary Flutter project is isolated under `/tmp`; unrelated pre-existing worktree changes were preserved. |

## Legacy work / production proof still missing

These items do not invalidate the implemented visual gates above. They are the remaining
evidence and hardening work required before claiming 10/10 production accuracy:

1. Run one real, complex Lanhu feature end to end (multiple states, shared components, runtime
   data, and one repair) and record measured accuracy, elapsed time, and model-token usage.
2. Expand the current synthetic Flutter self-test corpus with production-like complex layouts;
   the bundled 11-node corpus proves the path, not broad real-page coverage.
3. Add independent required viewport/device-profile gates when a requirement targets more than
   one viewport; the current proof is independent per board/state, not per viewport matrix.
4. Keep semantic shared-component identity and business-role mapping as explicit model decisions,
   but benchmark their false-reuse/false-split rate on real cross-file designs.

## Current hardening result

- Runtime screenshots now bind current Dart, assets/pubspec, launch route, device and viewport;
  changing those inputs makes old evidence stale.
- Generated trace tests fail on unexpected Flutter exceptions instead of clearing them.
- Unknown square vectors fail generation instead of becoming transparent placeholders.
- Font family/style/weight/letter-spacing/line-height survive scene → render plan → canvas →
  expected → trace → fidelity.
- Significant non-AA pixels outside expected widget coverage are `unexpected_region` hard failures.
- Optional-leaf structural relatives are model candidates only; they are never auto-reused.
- Component contracts are checked against public source inputs and raw visual Dart types.
- The bundled Flutter render/analyze/trace/fidelity corpus passes both cases (11 nodes total).

Client runtime evidence is complete for the bundled self-test: a Pixel 8 API 35 Android emulator
ran the generated Flutter app at 750x1200, produced a real screenshot and a validated manifest,
and the app process log contained no Flutter or unhandled exception. Xcode still rejected the
available iOS runtimes because its iOS 26.5 platform component is unavailable; no iOS evidence was
fabricated. The real complex production feature and viewport matrix items below therefore remain
required before a production-level claim.

STATUS: PASS

Scope note: automated gates and the client self-test pass; production-feature proof remains pending.
