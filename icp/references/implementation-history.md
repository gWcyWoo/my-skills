---
name: icp-implementation-history
description: "ICP = Client Project. Invoke when a user wants to preflight or implement a client project from a structured CSV task source plus Lanhu/Figma design source for Flutter, Vue, Next.js, iOS, or Android. ICP resolves a strict run-config, checks all unattended-run prerequisites before claim, freezes deterministic evidence, and resumes one requirement at a time; platform packages remain fail-closed until their activation audit passes."
---

# ICP — Client Project

`ICP = Client Project`. This skill turns a structured task source plus a design
source into a deterministic, machine-checked implementation pipeline. The
current implementation includes the frozen selection/claim foundation,
platform-neutral readiness and resumability contracts, Flutter compatibility
components, and inactive fixed PlatformPackages for Flutter and Vue. All
production platforms remain inactive until their separate activation audits.

## When to invoke

Use `$icp` when the user provides a JSON run-config (or asks you to build one)
for a client project implementation run that targets one of the registered
platforms (`flutter`, `vue`, `nextjs`, `ios-swift`, `ios-objc`, `android-java`,
`android-kotlin`) with the registered task source `csv` and the registered
design source `lanhu-figma`. In P1a the skill resolves the config and tells you
precisely why a platform cannot yet proceed (it is registered but not
activated); it never silently starts code generation, packaging, or claims.

## P1a contract (executable)

The pipeline order is hard:

1. **Resolve** the strict JSON run-config.
2. **Support gate** (platform / profile / capability).
3. **Read-only preflight** of task source, design locator, and project root.

Until a platform is activated (none are in P1b), the support gate returns
`unsupported_platform` *before* any task source is opened or stat-ed. P1b adds
manifest freeze + CAS claim + export only behind an activated platform gate;
in production every platform is still inert, so the production CLI returns
`unsupported_platform` first.

### Strict JSON run-config

`icp/scripts/resolve_run_config.py --config CONFIG.json --cwd DIR`

The input is exactly one JSON object. Required keys: `task_source`, `task_ref`,
`design_source`, `platform`, `project_root`. The only optional key is
`profile`. The resolver rejects, with code `invalid_input`:

- non-object roots (arrays, scalars),
- missing required keys, unknown keys (including `command`, `script`, `env`,
  `prompt`, `registry`, operation IDs, or any execution option),
- non-string values, empty strings,
- duplicate JSON keys,
- non-UTF-8 bytes or malformed JSON.

`task_source` must be `csv`; `design_source` must be `lanhu-figma`; `platform`
must be one of the seven registered IDs; `profile` (if given) must be an exact
registered profile for the chosen platform. Defaults exist only for Flutter
(`flutter-standard`) and Vue (`vue-vite`); other platforms have no default and
any explicit profile fails with `unsupported_profile`.

`task_ref` and `project_root` are **path locators only**: relative paths are
resolved against the explicit `--cwd` and canonicalized; shell-looking
characters inside a legitimate path remain inert and are never executed.

On success the resolver prints canonical JSON (sorted keys, two-space indent)
to stdout. On failure it prints exactly one JSON object to stderr with
`ok=false`, a public `code`, and a `message` — never a traceback.

### Read-only preflight

`icp/scripts/preflight_selection.py --config RESOLVED.json`

Consumes a resolved config plus only the internal registries. The hard order
guarantees the support gate runs first; for every one of the seven registered
platforms it returns `unsupported_platform` before any TaskSource access.

Direct reusable functions (independently testable, used by P1b/P2):

- `preflight_csv_task_source(path)` — `.csv` only (`.xlsx` →
  `unsupported_task_format`); existing ordinary non-symlink file; parseable CSV
  with exact P1 canonical headers `status` and `design_url` (P2 owns aliases);
  every status is one of empty/`doing`/`done`/`error`; acquires and releases a
  `fcntl.flock` shared lock; a same-directory create/write/fsync/rename/delete
  probe proves atomic-replace directory access; never mutates task bytes, row
  state, or leaves a probe.
- `preflight_design_locator(locator)` — `lanhu-figma` **syntax-only** check
  (no network, no auth): empty or malformed candidates return
  `design_preflight_failed`.
- `preflight_project_root(path)` — existing ordinary non-symlink directory;
  no platform tools or subprocesses.

### Public error codes (P1a + P1b)

```
invalid_input
unsupported_task_source
unsupported_task_format
unsupported_design_source
unsupported_platform
unsupported_profile
missing_mandatory_capability
task_preflight_failed
design_preflight_failed
project_preflight_failed
selection_manifest_conflict   # P1b
```

## P1b contract (executable)

P1b adds the hard-ordered selection orchestrator on top of P1a. The pipeline
order is hard:

1. strict-decode and validate the resolved config;
2. load only internal registries;
3. support gate first;
4. read-only `preflight_csv_task_source` (symlink/non-regular gate, parse
   probe, atomic-replace directory access) — before manifest/run-root
   creation and before any mutation;
5. TaskSource wrapper probe/select;
6. candidate design-locator syntax checks and generic project-root preflight;
7. generate an internal batch id and freeze the manifest;
8. only after a successful freeze, claim candidates sequentially with CAS;
9. export inputs only for successful claims.

`icp/scripts/prepare_selection.py --config RESOLVED.json --limit N` is the
production entry surface. It exposes **no** registry, batch-id, root, script,
command, or env override. It returns exactly one canonical JSON object and
never a traceback. A manifest conflict leaves every candidate row blank. A
failed claim is reported as failed and is excluded from successful claims;
the orchestrator never fakes success.

### Frozen CSV primitive

`icp/scripts/task_sources/csv_row_status_v1.py` is a byte-for-byte copy of
the proven `iff/scripts/csv_row_status.py`, pinned by SHA-256:

```
d5a1f418694d002335671694c8fa419368b36919f168cfd93a33b3c2479105ae
```

ICP runtime code imports only this local copy and has no runtime dependency
on any `iff` path. The copy is never rewritten: its parser, CAS update,
exclusive `flock`, and same-directory atomic replace are the proven mutation
primitive.

### CSV TaskSource wrapper (`icp/scripts/csv_task_source.py`)

Five versioned/kinded operations:

- `probe(task_ref)` -> `task_source_probe.v1`
- `select_candidates(task_ref, limit)` -> candidate row dicts
- `claim(task_ref, row_identity, expected_status='')` -> `icp.claim.v1`
- `export_inputs(task_ref, claim_ack, run_root)` -> `icp.export_inputs.v1`
- `writeback(task_ref, claim_ack, *, outcome, expected_status='doing')` -> `icp.writeback.v1`

Rules:

- `row_identity` is the semantic unique `title`; `rowIndex` is evidence, not
  the CAS key.
- The wrapper accepts the frozen primitive's semantic headers/aliases.
  Selection candidates are rows whose status is exactly empty; duplicate
  active titles are rejected before freeze.
- `limit` is a positive integer and selection preserves CSV order.
- `probe`, `select_candidates`, `claim`, and `writeback` reject symlink and
  non-regular task paths before any read or mutation (mirroring the read-only
  `preflight_csv_task_source` gate).
- `claim` is exactly CAS `empty -> doing`, under the frozen primitive's
  exclusive `flock` + same-directory atomic replace. A losing concurrent
  claimant fails visibly and is not counted as claimed.
- `writeback` supports only `done` or `error` and never performs an
  unconditional write.
- `export_inputs` validates the task path (symlink/non-regular rejection)
  before creating `run_root`, a row directory, or any output file, so a
  symlink/non-regular failure leaves the supplied run root absent/unchanged.
  It writes canonical `row.json`, `interaction.txt`, `ui_notes.txt`,
  `api.txt` under a row-specific directory beneath the batch run root. The row
  directory name is derived from a SHA-256 of the NFC-normalized title, so no
  path traversal from a title is possible.
- Every emitted `code` belongs to `icp_common.ALL_ERROR_CODES`;
  `task_preflight_failed` normalizes all TaskSource path/parse/primitive
  failures. A failed CAS claim is reported as failed and never as success.

### Frozen selection manifest (`icp/scripts/freeze_selection_manifest.py`)

`freeze_selection_manifest` builds schema `icp.selection_manifest.v1`
containing exactly the frozen evidence:

- schema/version/kind, `batch_id`;
- resolved IDs and absolute paths;
- internal registry digest, selected profile digest, rules digest,
  runtime-script digests;
- capability set, actual batch size, candidate identities/evidence;
- `state_root` and `run_root`.

`rules_digest` is exactly the SHA-256 of the fixed `icp/SKILL.md` file bytes.
`runtime_script_digests` covers the complete P1 execution set (eight files):
`icp_common.py`, `resolve_run_config.py`, `preflight_selection.py`,
`csv_task_source.py`, `freeze_selection_manifest.py`, `prepare_selection.py`,
`task_sources/__init__.py`, and `task_sources/csv_row_status_v1.py`. Both
digests are computed internally from the fixed `icp/scripts` / `icp` tree;
no public or lower-level manifest API accepts an externally supplied scripts
directory or path.

Roots are derived internally — never from run-config:

- Flutter: state root `<project>/.iff`, run root `<project>/.iff/icp_runs/<batch_id>`;
- Vue: state root `<project>/.icp`, run root `<project>/.icp/runs/<batch_id>`.

The freezer never follows a symlinked project root, state root (`.iff` /
`.icp`), or derived run-parent (`icp_runs` / `runs`), and never creates a
manifest outside the ordinary resolved project directory. A missing project
root is not created by the freezer; the project root must already exist as an
ordinary directory. Derived-directory creation is stepwise (project root ->
state root -> run parent -> batch run root), each re-checked for
ordinary-directory status so a pre-existing symlink cannot be treated as a
directory. The batch run root is created exclusively without `parents=True`.

`batch_id` is restricted to `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; `.`, `..`,
slashes, backslashes, whitespace, and overlong forms are rejected with
`invalid_input` and can never collapse or escape the run directory.

The freezer never accepts `state_root`, `run_root`, registry paths, script
paths, commands, env, or executable data from run-config, and never accepts an
external digest/path or scripts-directory override. The batch run directory is
created exclusively; an existing run root or manifest is
`selection_manifest_conflict` and is never overwritten or reused. Manifest
publication is atomic and no-clobber under a race: a same-directory temp file
is written and fsynced, then atomically `os.link`-ed to the absent
destination (`os.replace` is never used for the final manifest, so a
destination created after the explicit existence check survives
byte-for-byte and surfaces `selection_manifest_conflict`); the owned temp is
unlinked and then the directory is fsynced (in that observable order). On a
failed freeze only invocation-owned temporary artifacts are cleaned and every
task row status is left untouched. Identical explicit inputs produce
byte-identical manifests (no timestamp); `batch_id` is generated internally by
the orchestrator and never read from run-config.

## Immutable registries

Production registries live in `icp/references/registries.json` and have no
external override. They pin, exactly:

- **Task sources:** `csv`.
- **Design sources:** `lanhu-figma`.
- **Platform IDs (7):** `flutter`, `vue`, `nextjs`, `ios-swift`, `ios-objc`,
  `android-java`, `android-kotlin`. Defaults: `flutter-standard`, `vue-vite`;
  the other five have none. None are `activated` in P1a.
- **Trusted operations (9 inert port IDs, no shell/command/script fields):**
  `project_preflight`, `visible_codegen`, `fixture_codegen`, `trace_harness`,
  `packaging`, `test_runner`, `runtime_capture`, `project_gates`, `fan_in`.
- **Capability states:** `required`, `optional-with-shared-policy`,
  `unsupported`.

Registry values are pure data; the runtime never `import`s, `exec`s, or
`subprocess`s them.

## P1a files

- `icp/scripts/icp_common.py` — error codes, strict JSON decode, canonical
  encoding, SHA-256, versioned registry loader.
- `icp/scripts/resolve_run_config.py` — strict resolver + CLI.
- `icp/scripts/preflight_selection.py` — read-only preflight surfaces + CLI.
- `icp/scripts/selftest_p1a.py` — focused RED→GREEN self-test (run directly).
- `icp/references/registries.json` — versioned immutable registries.

## P1b files

- `icp/scripts/task_sources/__init__.py` — local task-source primitives
  package marker.
- `icp/scripts/task_sources/csv_row_status_v1.py` — byte-frozen copy of the
  proven CSV row-status primitive (SHA-256 pinned).
- `icp/scripts/csv_task_source.py` — wrapper contract (probe/select/claim/
  export/writeback).
- `icp/scripts/freeze_selection_manifest.py` — manifest freezer.
- `icp/scripts/prepare_selection.py` — hard-ordered selection orchestrator +
  production CLI.
- `icp/scripts/selftest_p1b.py` — focused RED→GREEN self-test (run directly).

P0 baseline freezer (`icp/scripts/freeze_iff_baseline.py`,
`icp/scripts/selftest_freeze_iff_baseline.py`,
`icp/references/baselines/iff-v1.json`) is preserved and immutable in this
slice; it is unrelated to the P1a runtime.

## P2a — frozen iFF v1 compatibility capsule (executable)

P2a is a **frozen compatibility bootstrap**: a self-contained, immutable copy
of every iFF v1 script the P2 compatibility wrappers will need to execute
later. The capsule is the only iFF-derived material the ICP runtime ever
imports, executes, or reads at runtime; **normal runtime uses only the
verified local capsule** under `icp/vendor/iff_v1/scripts/`, and **`iff/**`
is never a runtime dependency** of ICP. The installed ICP runtime never
imports, executes, symlinks to, or reads `iff/**` to satisfy a runtime need.

The capsule is integrity-bound to the immutable P0 baseline
(`icp/references/baselines/iff-v1.json`) via the manifest
(`icp/references/baselines/iff-v1-vendor.json`). The manifest records the
versioned schema, the exact 165-file set, per-file SHA-256 (P0 values),
required/non-required membership (111/54), the capsule root relative to the
ICP skill (`vendor/iff_v1`), and the P0 baseline SHA-256 binding. It is
deterministic canonical UTF-8 JSON and contains no absolute paths,
timestamps, hostnames, run IDs, or other nondeterminism.

### Runtime integrity gate

`icp/scripts/verify_vendor_iff_v1.py` is the installed runtime gate. It
resolves its own skill root from its fixed file location and accepts no
root, manifest, registry, or scripts-directory override. It works when
`iff/` is absent and never imports, reads, executes, or follows a symlink
into `iff/**`. It fails closed on any integrity violation: missing, extra,
mutated, symlinked, non-regular, or unreadable capsule files; duplicate JSON
keys; wrong schema; unsafe relative paths; manifest/baseline binding
mismatch; and file-set/count mismatch. The exact capsule set is exactly the
165 manifest entries and no other file, directory, or symlink (there is no
`__pycache__` or any other exemption). It never follows a symlink anywhere
from the skill root through a target capsule file; every path component in
the caller-supplied skill-root chain is inspected and a symlink at any
level is rejected before traversal. Success emits one canonical JSON object
on stdout (exit 0); any failure emits one canonical JSON object on stderr
(exit 2) and never a traceback.

### Maintenance tool (not part of normal ICP execution)

`icp/scripts/vendor_iff_v1.py` is a maintenance-only refresh/check tool. It
rebuilds the capsule from a read-only `--iff-root` source into the output
`--capsule-root`, deriving the copy set and expected SHA-256 values only
from the fixed P0 baseline. Live source bytes are never used to generate
expectations; unknown source files are ignored, and missing or mismatched
listed files fail.

Write mode stages a complete sibling temporary tree, fsyncs files and
directories, and publishes without exposing a partial capsule. Publication
is failure-preserving: if this process newly publishes the capsule and a
later manifest publication/fsync step fails, the newly published capsule is
rolled back (removed), the manifest remains absent, and no staging residue
is left; a pre-existing identical capsule is never deleted or rolled back.
It must not overwrite an existing non-identical capsule or manifest; an
identical check/re-run is allowed. Any other failure preserves the previous
capsule byte-for-byte and leaves no temporary tree. Every caller-controlled
path component (not only the leaf) rejects symlinks and non-regular files;
path identity is inspected component-by-component and never erased via
whole-path `.resolve()`.

### P2a files

- `icp/vendor/iff_v1/scripts/**` — 165 byte-frozen scripts (regular
  non-symlink files; bytes and SHA-256 equal the P0 baseline entry).
- `icp/references/baselines/iff-v1-vendor.json` — deterministic capsule
  manifest, bound to the P0 baseline SHA-256.
- `icp/scripts/vendor_iff_v1.py` — maintenance-only refresh/check tool.
- `icp/scripts/verify_vendor_iff_v1.py` — installed runtime integrity gate.
- `icp/scripts/selftest_p2a_vendor.py` — focused RED→GREEN self-test.

P2a deliberately stops at the capsule and its integrity gate. It does not
implement the Lanhu facade, Flutter operation ports, parity runner, P2.5
contracts, Vue adapter, or the orchestrator.

## P2b — lanhu-figma DesignSource wrapper (executable)

P2b is the first compatibility adapter over the immutable P2a capsule: a
self-contained `lanhu-figma` DesignSource wrapper at
`icp/scripts/design_sources/lanhu_figma_v1.py`. It exposes the four settled
DesignSource operations (`resolve`, `probe`, `fetch_normalize`,
`verify_bundle`) and a CLI surface (`resolve`, `probe`, `fetch-normalize`,
`verify-bundle`), and it publishes a deterministic canonical design bundle
v1 atomically. It depends only on the verified local capsule and never
imports, reads, executes, or follows a symlink into `iff/**`. **No platform
is activated by P2b**: it is DesignSource extraction only, and the seven
production platforms remain inert (`unsupported_platform` at the support
gate). No SharedCore, Flutter operation, capture v2, parity normalization,
Vue adapter, or end-to-end claiming is implemented in this slice.

### Public operations

- `resolve(locator) -> board_ref` — strict parse of an HTTP(S) Lanhu
  locator with exactly one non-empty `image_id` query value, preserving
  the locator as data and emitting the deterministic board ref
  `lanhu-figma:v1:<sha256(locator-utf8)>`. Rejects non-HTTP schemes,
  missing network location, fragments, userinfo (credentials), missing /
  duplicate / blank `image_id`, and any malformed input.
- `probe(locator) -> design_source_probe.v1` — verifies the installed
  capsule first, then runs only the fixed capsule primitives `fetch.py`
  and `download_cover.py` using a private temporary directory under
  `tempfile.gettempdir()`. Never mutates the task CSV, the project root,
  or any final bundle root. Removes all temporary artifacts on success and
  failure. The probe payload carries capsule verification evidence, the
  resolved board ref, and the reference PNG width/height.
- `fetch_normalize(locator, bundle_root) -> design_bundle_report.v1` —
  verifies the capsule, runs the exact fixed seven-step capsule sequence
  into a sibling staging directory, finalizes canonical
  `design_provenance.json` and `reference_manifest.json`, fully validates
  the staged bundle, and publishes with one atomic `os.replace` only when
  `bundle_root` is absent.
- `verify_bundle(bundle_root) -> design_bundle_report.v1` — verifies the
  capsule, then fails closed on any structural / digest / PNG / scene /
  provenance / asset-inventory violation.

### Fixed seven-step capsule sequence

`fetch_normalize` runs exactly this sequence from
`icp/vendor/iff_v1/scripts`, using `sys.executable` and no shell:

1. `fetch.py --url <locator> --output <stage>/raw.json`
2. `write.py --input <stage>/raw.json --output <stage>/spec.md`
3. `download_cover.py --url <locator> --out <stage>/reference.png`
4. `export_figma_scene.py --raw <stage>/raw.json --assets <stage>/assets/manifest.json --out <stage>/scene.json`
5. `export_tokens.py --scene <stage>/scene.json --out <stage>/tokens.json`
6. `export_assets_manifest.py --scene <stage>/scene.json --out <stage>/assets_manifest.json`
7. `classify_design.py --raw <stage>/raw.json --reference <stage>/reference.png --out <stage>/design_classification.json`

The argv is the exact per-step contract; there is no arbitrary
pass-through and no credential is ever placed in argv.

### Canonical bundle layout

A published bundle contains exactly:

- `raw.json`, `spec.md`, `reference.png`, `reference_manifest.json`,
  `scene.json`, `tokens.json`, `assets_manifest.json`,
  `design_classification.json`, `design_provenance.json` (top-level
  regular files).
- `assets/` directory, including the legacy `assets/manifest.json`
  (normalized to `[]` when `fetch.py` produced no slices) plus any
  extracted slice files.

`design_provenance.json` is canonical UTF-8 JSON (`sort_keys=True`,
two-space indent, trailing newline) and binds `kind`
(`icp.lanhu-figma.design-provenance.v1`), `schema_version=1`,
`source_id=lanhu-figma`, the resolved `board_ref`, the original
`locator`, `ir_schema=lanhu_figma_json`, the SHA-256 of every required
top-level artifact other than provenance itself, and a sorted
relative-path/SHA-256 inventory of every regular file under `assets/`.
`reference_manifest.json` binds the reference PNG SHA-256 and its PNG
width/height.

### Publication discipline

Publication is non-clobber and atomic. `fetch_normalize` creates a
sibling staging directory (`.lanhu_figma_v1_stage.*`) under the bundle
parent, writes and fully validates the bundle in place, then publishes via
a native same-filesystem no-replace exclusive rename (`renamex_np` with
`RENAME_EXCL` on Darwin, `renameat2` with `RENAME_NOREPLACE` on Linux)
only when `bundle_root` is absent. There is no check-then-rename,
`os.rename`, or `os.replace` fallback; the native exclusive rename is the
decisive publication gate. If a subsequent parent fsync or report
finalization fails, the published bundle is rolled back, the parent is
re-fsynced, and all staging residue is removed. It rejects any final path
or path-chain component that is a symlink (inspected component-by-
component; whole-path `.resolve()` is never used so caller-supplied
symlink identity is preserved). A pre-existing final bundle is never
overwritten, even if identical.

### Locked boundaries (P2b)

- Production code derives ICP root, capsule root, and script paths only
  from this module's installed file location. No public override is
  exposed for skill root, capsule root, script path, command,
  interpreter, runner, environment, or registry.
- No cookie/token/secret is accepted as an argument, placed in argv,
  persisted, inspected, logged, copied, or serialized. The subprocess
  environment is inherited as-is because the legacy capsule scripts own
  their existing credential lookup. `_run_step` error messages report
  only the fixed script name and stable exit status — never child
  stdout/stderr content or arbitrary exception text. Locators carrying
  sensitive query keys (`token`, `access_token`, `api_key`, `apikey`,
  `password`, `passwd`, `secret`, `cookie`, `authorization`, `auth`,
  `bearer`) are rejected before a board ref is returned and never emitted
  or persisted on rejection.
- Reference PNGs are validated by a deterministic structural parser
  (signature, IHDR, chunk boundaries + CRCs, at least one IDAT, terminal
  empty IEND, no trailing bytes). Reference PNG dimensions must match the
  raw artboard bbox within 1.0 (using the frozen legacy bbox semantics
  from `common.py:67-93` and the `close()` tolerance from
  `check_design_artifacts.py:42-43`). This check is applied in `probe`,
  staged finalization, and `verify_bundle`.
- Only the Python standard library is used. CLI output is exactly one
  canonical JSON object on stdout (exit 0) for success or one canonical
  JSON object on stderr (exit 2) for failure. No traceback.
- Local error code is `design_source_failed`, scoped to this
  DesignSource; it never extends `icp_common.ALL_ERROR_CODES`.

### P2b files

- `icp/scripts/design_sources/__init__.py` — DesignSource wrappers
  package marker.
- `icp/scripts/design_sources/lanhu_figma_v1.py` — Lanhu/Figma
  DesignSource wrapper (resolve/probe/fetch_normalize/verify_bundle + CLI).
- `icp/scripts/selftest_p2b_lanhu.py` — focused RED→GREEN self-test
  (run directly).

## P2c — Flutter platform-adapter descriptor (non-executable)

P2c is a **descriptor-only** slice over the immutable P2a capsule. It
structures the existing vendored iFF Flutter-specific script families
under the nine settled platform operation ports, binds every mapped
primitive to the immutable capsule manifest SHA-256, and remains
fail-closed / inactive until later executable builders and parity gates
are complete. It depends only on the verified local capsule and never
imports, reads, executes, or follows a symlink into `iff/**`.

The descriptor is **not runnable**. Root `executable` is `false`;
`activation_state` is `inactive`. No operation may carry an
executable / command / argv / shell / script-runner field. No executable
builder, Dart generation, packaging, capture, parity gate, claim, or
registry mutation runs in P2c. The seven production platforms remain
inert (`unsupported_platform` at the support gate); P1a preflight and
P1b selection / claim still **fail closed**.

### Public operations

- `describe() -> dict` — verify the installed vendored capsule first
  (via the P2a runtime gate), then return the canonical descriptor of
  kind `icp.platform-adapter-descriptor.v1`.
- `verify_descriptor() -> dict` — verify the capsule, build the
  descriptor, fail-closed validate every invariant against the fixed
  mapping and the installed manifest, cross-check operation IDs and
  capability states against the settled registry, and return a
  verification report of kind
  `icp.platform-adapter-descriptor-verify.v1` carrying the descriptor
  digest and primitive totals.

The CLI exposes only `describe` and `verify`; it accepts no path,
registry, command, executable, script, interpreter, environment, argv,
or activation override. CLI output is exactly one canonical JSON object
on stdout for success (exit 0) or one canonical JSON object on stderr
for failure (exit 2). No traceback. `describe()` and `verify_descriptor()`
are deterministic byte-for-byte across processes and working
directories. Local error code is `platform_adapter_descriptor_failed`,
scoped to this descriptor; it never extends
`icp_common.ALL_ERROR_CODES`.

### Canonical descriptor shape

```
kind                = "icp.platform-adapter-descriptor.v1"
schema_version      = 1
platform_id         = "flutter"
profile_id          = "flutter-standard"
activation_state    = "inactive"
executable          = false
operations[]        = {
  id, capability_state, implementation_state,
  legacy_primitives[] = { script: "<basename>.py", sha256: "<64 hex>" }
}
```

### Fixed nine-port ownership mapping

`project_rules` is **not** a platform port; `sync_project_rules.py` is
explicitly not mapped. SharedCore scripts (render fidelity, responsive
comparison, visual diff, expected/slots, contract parsing, prompt /
supervisor orchestration) do not belong in this platform descriptor.

| # | Operation port          | Capability state                 | Implementation state   | Legacy primitives (vendored capsule scripts)                                                              |
|---|-------------------------|----------------------------------|------------------------|-----------------------------------------------------------------------------------------------------------|
| 1 | `project_preflight`     | `required`                       | `new-port-required`    | *(none — new port)*                                                                                       |
| 2 | `visible_codegen`       | `required`                       | `legacy-mapped`        | `generate_canvas.py`, `make_implementation_map.py`, `make_status_bar_policy.py`                           |
| 3 | `fixture_codegen`       | `required`                       | `legacy-mapped`        | `make_visual_fixture.py`                                                                                  |
| 4 | `trace_harness`         | `optional-with-shared-policy`    | `legacy-mapped`        | `gen_layout_trace_test.py`                                                                                |
| 5 | `packaging`             | `required`                       | `legacy-mapped`        | `prepare_assembly_packaging.py`, `update_pubspec_assets.py`, `copy_assets.py`                             |
| 6 | `test_runner`           | `required`                       | `legacy-mapped`        | `assembly_tdd_guard.py`, `retire_stale_flutter_template_tests.py`                                         |
| 7 | `runtime_capture`       | `optional-with-shared-policy`    | `legacy-mapped`        | `select_runtime_device.py`, `device_lock.py`, `capture_runtime_screenshot.py`, `physical_device_preview.py` |
| 8 | `project_gates`         | `required`                       | `legacy-mapped`        | `check_interaction_wiring.py`, `check_api_integration.py`, `check_fixture_source.py`, `check_capture_readiness.py` |
| 9 | `fan_in`                | `required`                       | `legacy-mapped`        | `assembly_plan_batch.py`, `assembly_worker_supervisor.py`, `check_done_gate.py`, `assembly_completion.py` |

Totals: 9 operation ports; 22 legacy primitives (one per script, no
duplicate ownership). The mapping is a fixed private code constant;
SHA values are resolved from the installed `iff-v1-vendor.json` only
after capsule verification.

### Fail-closed invariants

`verify_descriptor()` rejects: wrong `kind` / `schema_version` /
`platform_id` / `profile_id` / `activation_state` / `executable`;
unexpected top-level keys; missing / extra operations; wrong operation
order; duplicate operation IDs; wrong `capability_state`; wrong
`implementation_state`; missing / extra primitives per operation; wrong
primitive order; non-basename script names; missing / extra / malformed
SHA-256; manifest SHA mismatch; duplicate primitive ownership across
operations; any executable / command / argv / shell field anywhere
except the root `executable=false` key; mapping `sync_project_rules.py`
under any port; and any divergence from the settled registry's
operation IDs, order, or capability states.

### P2c files

- `icp/scripts/platforms/__init__.py` — platform-adapter descriptor
  package marker.
- `icp/scripts/platforms/flutter_standard_v1.py` — Flutter
  `flutter-standard` platform-adapter descriptor
  (`describe` + `verify_descriptor` + CLI).
- `icp/scripts/selftest_p2c_flutter_descriptor.py` — focused RED→GREEN
  self-test (run directly).

P2c deliberately stops at the descriptor. It does not implement the
executable operation builders, parity runner, P2.5 contracts, Vue
adapter, or end-to-end claiming.

## P2d1 — Flutter `project_preflight` operation (executable, read-only)

P2d1 is the first executable platform operation for the otherwise
inactive `flutter-standard` adapter. It is a fail-closed, read-only
project preflight that proves the selected root is a usable Flutter
project and resolves the Flutter toolchain from the trusted process
environment. The P2c descriptor remains `new-port-required` for
`project_preflight`; this operation is **not** the descriptor
activation (P2e owns that state transition), does not register the
adapter as activated, and does not implement the other eight operation
builders.

### Public API

- `preflight(project_root: str | os.PathLike[str]) -> dict[str, Any]`
  — verify the installed P2a vendored capsule first (via the fixed ICP
  path), validate the project root, inspect the project artifacts,
  resolve and probe the Flutter toolchain from the trusted process PATH,
  and return the canonical report of kind
  `icp.project-preflight.v1`. `profile_id` is fixed to
  `flutter-standard`; no executable, env, argv, command, interpreter,
  runner, registry, or activation override is accepted.

CLI:

- `python3 flutter_project_preflight_v1.py --project-root ABSOLUTE_PATH`
  — emits exactly one canonical JSON object on stdout (exit 0) for
  success, or one canonical JSON object on stderr (exit 2) for failure.
  No traceback, no secret, no child stderr, no arbitrary exception
  text.

### Canonical success report

```
kind                = "icp.project-preflight.v1"
schema_version      = 1
operation_id        = "flutter.project_preflight.v1"
platform_id         = "flutter"
profile_id          = "flutter-standard"
project_root        = "<canonical absolute root>"
project             = {
  lib_directory:    "lib",
  package_config:   ".dart_tool/package_config.json",
  pubspec:          "pubspec.yaml",
  pubspec_sha256:   "<64 lower-hex>"
}
toolchain           = {
  flutter_executable:          "<canonical absolute flutter>",
  flutter_executable_sha256:   "<64 lower-hex>",
  flutter_version:             "<frameworkVersion>",
  dart_sdk_version:            "<dartSdkVersion>",
  version_payload_sha256:      "<64 lower-hex of stdout bytes>"
}
```

Canonical JSON means UTF-8, sorted keys, two-space indentation, one
final newline.

### Project-root validation

- The input must be an absolute, lexically normalized path. Relative
  paths, any `..` component, and roots whose supplied path differs from
  `resolve(strict=True)` are rejected; this rejects a symlinked root or
  symlinked ancestor rather than silently changing ownership.
- The root must be a real non-symlink directory.
- `pubspec.yaml` must be a non-symlink regular file, UTF-8, at most
  2 MiB.
- `lib/` must be a non-symlink directory.
- `.dart_tool/package_config.json` must be a non-symlink regular file,
  UTF-8, at most 8 MiB, strict JSON with duplicate-key rejection.
- The package config must be an object with `configVersion == 2`, a
  list `packages`, and at least one package object whose `name` equals
  the exact top-level `name` from `pubspec.yaml`.
- Only the top-level `name` is parsed. The parser is a small
  deterministic restricted-scalar parser (no YAML dependency) that
  fails closed on ambiguous, duplicated, missing, empty,
  quoted-with-invalid-escape, or malformed values.
- Every path inspected below the root is containment-checked after
  resolution; symlink/path escape is rejected.

### Trusted toolchain resolution

- No executable path, argv fragment, env-var name, command, shell
  string, or profile may be supplied by the caller.
- `flutter` is resolved only via `shutil.which("flutter")` against the
  current trusted process environment, then `resolve(strict=True)` and
  required to be a regular executable file. A symlink returned by PATH
  is allowed only after canonicalization; the report records the final
  target.
- The exact subprocess invocation is
  `[resolved_flutter, "--version", "--machine"]` via `subprocess.run`
  with `shell=False`, `cwd=project_root`, captured stdout/stderr, text
  mode, a fixed 30 second timeout, and no user-controlled environment
  overlay.
- The operation requires exit 0, empty-or-ignored child stderr (never
  echoed), stdout UTF-8/text no larger than 1 MiB, strict JSON with
  duplicate-key rejection, and a root object. The version comes from
  exact machine keys `frameworkVersion` and `dartSdkVersion` (both
  non-empty strings). `version_payload_sha256` is the SHA-256 of the
  exact stdout bytes used for parsing.

### Integrity and inactive-adapter rules

- Before project or toolchain inspection, the operation calls the
  existing P2a capsule verifier via the fixed ICP path. Known capsule
  failures convert to stable `project_preflight_failed` errors;
  generic failures expose type only.
- The operation never imports or reads sibling `iff/`, never edits
  `icp/references/registries.json`, never writes to the project,
  capsule, registry, or `iff/`, and never mutates the P2c descriptor's
  settled non-executable fields or `project_preflight`'s
  `new-port-required` state.
- Only the Python standard library is used.

### Error contract

- The module defines a local typed exception (`PreflightError`).
- CLI error JSON is exactly top-level keys `ok`, `code`, `message`
  with `ok=false`, `code="project_preflight_failed"` (the established
  ICP public error code from `icp_common`).
- No traceback, secret, child stderr, raw arbitrary exception message,
  or environment content is ever emitted.

### P2d1 files

- `icp/scripts/platforms/flutter_project_preflight_v1.py` — Flutter
  `project_preflight` executable operation (`preflight` + CLI).
- `icp/scripts/selftest_p2d1_flutter_preflight.py` — focused RED→GREEN
  self-test (run directly).

P2d1 deliberately stops at one executable operation. It does not
activate the adapter, does not change the P2c descriptor's
`project_preflight` state, and does not implement the other eight
operation builders, parity runner, P2.5 contracts, Vue adapter, or
end-to-end claiming.

## P2d2a — trusted Flutter argv plan registry (visible/fixture/trace)

P2d2a is the static trusted-operation plan registry and the first three
legacy-backed Flutter argv builders:

- `flutter.visible_codegen.v1`
- `flutter.fixture_codegen.v1`
- `flutter.trace_harness.v1`

It validates typed requests and returns deterministic argv plans. It
**must not** execute subprocesses, write outputs, activate the adapter,
modify the P2c descriptor, or implement the remaining legacy-backed
operation builders (the packaging/test_runner extensions are added by
the append-only P2d2b phase below). It depends only on the verified
local capsule and never imports, reads, executes, or follows a symlink
into `iff/**`.

### Public Python API

Expose only:

```python
list_operation_ids() -> tuple[str, ...]
build(operation_id: str, request: dict[str, Any]) -> dict[str, Any]
verify_plan(plan: dict[str, Any]) -> dict[str, Any]
```

No CLI. No public root/manifest/capsule/registry/executable override. No
executor.

`list_operation_ids()` returns exactly, in order (extended append-only
by P2d2b and P2d2c — see the P2d2b/P2d2c sections below):

```
flutter.visible_codegen.v1
flutter.fixture_codegen.v1
flutter.trace_harness.v1
flutter.packaging.v1
flutter.test_runner.v1
flutter.runtime_capture.v1
flutter.project_gates.v1
flutter.fan_in.v1
```

`build()` must verify the immutable P2a capsule first through the fixed
verifier, strict-load the fixed vendor manifest with duplicate-key
rejection, validate the exact request schema, build a canonical plan,
call `verify_plan()`, and return the plan. Generic failures expose type
only through a module-local typed exception (`OperationPlanError`); no
arbitrary exception text is leaked.

### Canonical plan schema

Every plan has exactly:

```
kind             = "icp.trusted-operation-plan.v1"
schema_version   = 1
operation_id     = "flutter.<port>.v1"
platform_id      = "flutter"
profile_id       = "flutter-standard"
request_digest   = "<sha256 of canonical normalized request>"
steps[]          = {
  step_id, primitive, primitive_sha256,
  argv:    ["<sys.executable>", "<fixed absolute capsule script>", ...],
  cwd:     "<canonical project_root>",
  timeout_seconds: 120
}
```

Canonical JSON for digests/tests is UTF-8, sorted keys, two-space
indentation, one final newline. Plans are byte-for-byte deterministic
for fixed filesystem roots and request data. `steps` order and argv flag
order are fixed by code, never by map iteration or caller order.

`verify_plan()` returns exactly:

```
ok              = true
kind            = "icp.trusted-operation-plan-verify.v1"
schema_version  = 1
operation_id    = "..."
steps_total     = <int>
plan_digest     = "<sha256 canonical plan bytes>"
```

It independently re-verifies the capsule/manifest binding, exact
top-level/step keys, operation id, step count/order, primitive
ownership, primitive SHA, fixed interpreter/script/cwd/timeout/argv
structure, and rejects command/shell/env/prompt or unknown executable
fields anywhere. It validates fixed step schemas and recomputes all
invariant argv structure that does not require the original request
values (the normalized request is never embedded in the plan).
Request-derived argv positions still pass their strict
type/path/value validators; a tampered `cwd` is detected by requiring at
least one project-rooted absolute path in each step's argv to be
lexically contained under `cwd`.

### Common request/path rules

Every request has exact operation-specific keys; unknown/missing keys
fail. Recursively reject any key named `command`, `shell`, `env`,
`environment`, `argv`, `args`, `executable`, `interpreter`, `runner`,
`prompt`, `script`, `script_path`, or `operation_id` inside caller
data.

Common required fields:

- `project_root`: absolute, lexically normalized, `resolve(strict=True)`-
  identical, existing non-symlink real directory.
- `run_root`: same constraints, and must be different from and not
  nested inside `project_root`; `project_root` also must not be nested
  inside `run_root`.
- `package_name`: Dart package identifier matching `^[a-z][a-z0-9_]*$`.

Request paths are POSIX relative strings only: no absolute paths, empty
components, `.`/`..`, backslashes, NUL, URI schemes, or repeated
separators. Run-input paths resolve below `run_root`, must already exist
as non-symlink regular files, and every component must be non-symlink.
Project-output paths resolve below `project_root`; they must end in the
required extension. Existing outputs may be non-symlink regular files;
absent outputs are allowed only when the nearest existing ancestor is a
non-symlink directory and the full lexical path remains contained. Run-
output paths use the same output rule below `run_root`. Directories,
symlinks, path escape, and any symlinked component are rejected. The
builder never creates parents or files.

Identifier fields (`feature_id`, state ids, Dart class names) use fixed
regexes: feature/state `^[a-z][a-z0-9_]*$`; Dart class
`^[A-Z][A-Za-z0-9]*$`. No request may supply executable path, capsule
path, script name, command, argv fragment, shell string, environment
key/value, prompt text, arbitrary Dart expression, or raw import string.

### Operation 1: visible_codegen

Exact request keys: `project_root`, `run_root`, `package_name`,
`feature_id`, `render_plan`, `scene`, `classification`,
`component_manifest`, `canvas_out`, `colors_out`, `colors_import_path`,
`implementation_map_out`, `status_bar_out`, `canvas_class_name`,
`status_bar_class_name`.

- `render_plan`, `scene`, `classification`, `component_manifest`:
  required run-input `.json` files.
- `canvas_out`, `colors_out`, `status_bar_out`: project-output `.dart`
  paths.
- `implementation_map_out`: run-output `.json` path.
- `colors_import_path`: project-relative `.dart` path and must exactly
  equal `colors_out`; builder constructs
  `package:<package_name>/<colors_import_path with a leading lib/
  removed>`.
- `feature_id` constructs fixed asset prefix `assets/icp/<feature_id>`.

Fixed steps/argv order:

1. `generate_canvas` / `generate_canvas.py`:
   `--render-plan ABS --out ABS --colors-out ABS --colors-import CONSTRUCTED
   --asset-prefix FIXED --classification ABS --component-manifest ABS
   --class-name IDENTIFIER`
2. `make_implementation_map` / `make_implementation_map.py`:
   `--render-plan ABS --canvas ABS --out ABS`
3. `make_status_bar_policy` / `make_status_bar_policy.py`:
   `--scene ABS --class-name IDENTIFIER --out ABS`

Does not expose `--artboard-width` or `--artboard-height`;
classification is the authoritative dimension source.

### Operation 2: fixture_codegen

Exact request keys: `project_root`, `run_root`, `package_name`,
`feature_id`, `slots`, `out`.

- `slots` is a non-empty dict of state id -> required run-input `.json`
  path, maximum 32 entries. Duplicate normalized state ids are rejected.
  Sort by state id before argv emission regardless of caller insertion
  order.
- `out` is a project-output `.dart` path.

Fixed one step `make_visual_fixture` / `make_visual_fixture.py` argv:

```
--feature FEATURE_ID
--slots STATE=ABS   (repeat, sorted by state)
--out ABS
```

### Operation 3: trace_harness

Exact request keys: `project_root`, `run_root`, `package_name`,
`expected`, `page_import_path`, `page_type`, `trace_out`,
`responsive_out`, `responsive_contract_out`, `viewports_file`,
`safe_area_policy`, `out`.

- `expected`, `viewports_file`: required run-input `.json` files.
- `page_import_path`: project-relative `.dart` path, must begin `lib/`;
  builder constructs `package:<package_name>/<path after lib/>`.
- `page_type`: Dart class identifier.
- `trace_out`, `responsive_out`, `responsive_contract_out`: run-output
  `.json`.
- `safe_area_policy`: exactly `edge_to_edge` or `inset_content`.
- `out`: project-output path ending `_layout_trace_test.dart`.

Fixed one step `gen_layout_trace_test` / `gen_layout_trace_test.py` argv:

```
--expected ABS
--page-import CONSTRUCTED
--page-type IDENTIFIER
--trace-out ABS
--responsive-out ABS
--responsive-contract-out ABS
--viewports-file ABS
--safe-area-policy ENUM
--out ABS
```

P2d2a deliberately does **not** support or emit `--page-expr`,
`--extra-imports`, or raw `--viewports`. Those require a later
structured/trusted producer and are not accepted as arbitrary
Dart/import/argv text.

### Security/integrity boundary

- Stdlib only. No `subprocess` import; the module never invokes a
  shell-enabled subprocess.
- Fixed `sys.executable`, fixed capsule path, fixed script basenames,
  fixed flags, fixed timeouts. No subprocess execution anywhere.
- Each primitive SHA comes from the immutable manifest after capsule
  verification.
- Reject duplicate JSON keys, missing/extra/tampered capsule entries,
  symlinks, manifest drift, duplicate primitive ownership, wrong
  operation/primitive order, and any argv/script/interpreter/timeout
  mutation in `verify_plan()`.
- Do not import/read/execute sibling `iff/`. Do not edit registry or P2c
  descriptor. Adapter stays inactive.
- No project/run/capsule writes, including during self-tests; tests use
  temporary projects/run roots and never tamper the production capsule.

### P2d2a files

- `icp/scripts/platforms/flutter_operations_v1.py` — static trusted-
  operation plan registry (`list_operation_ids` + `build` +
  `verify_plan`).
- `icp/scripts/selftest_p2d2a_flutter_operations.py` — focused
  RED→GREEN self-test (run directly).

P2d2a deliberately stops at the plan registry and the first three
legacy-backed builders. It does not execute the plans, does not activate
the adapter, does not change the P2c descriptor, and does not implement
the remaining legacy-backed operation builders, parity runner, P2.5
contracts, Vue adapter, or end-to-end claiming. The remaining
unsupported trace options (`--page-expr`, `--extra-imports`, raw
`--viewports`) require a later structured/trusted producer.

## P2d2b — trusted Flutter argv plan registry extension (packaging/test_runner)

P2d2b is the append-only extension of the P2d2a static trusted-operation
plan registry with two new single-step-variant operations:

- `flutter.packaging.v1`
- `flutter.test_runner.v1`

The public Python API, the canonical plan schema (`kind` stays
`icp.trusted-operation-plan.v1`, no top-level action/phase field), the
capsule-first ordering, the two-stage trusted-exception classification,
the recursive forbidden-key rejection, the canonical JSON/digest
behavior, strict duplicate-key rejection, generic-error type-only
redaction, path containment/symlink rules, and the no-`iff/**` rule all
remain exactly as in P2d2a. The module remains a static plan
builder/verifier only — no CLI, no executor, no writes, no subprocess
import/call, no shell/env surface.

`list_operation_ids()` now returns a fresh tuple with exactly this
append-only order (further extended by P2d2c below):

```
flutter.visible_codegen.v1
flutter.fixture_codegen.v1
flutter.trace_harness.v1
flutter.packaging.v1
flutter.test_runner.v1
```

### Append-only primitive ownership

All primitive paths and SHA-256 values come only from the verified fixed
`iff-v1-vendor.json` manifest. P2d2b adds no new primitive files; it
binds five already-vendored legacy primitives to the two new operations.

`flutter.packaging.v1` owns exactly:

- `prepare_assembly_packaging.py`
- `update_pubspec_assets.py`
- `copy_assets.py`

`flutter.test_runner.v1` owns exactly:

- `assembly_tdd_guard.py`
- `retire_stale_flutter_template_tests.py`

P2d2b does not implement or claim the runtime_capture, project_gates,
or fan_in primitives.

### Common request/path rules (unchanged from P2d2a)

`project_root`, `run_root`, and `package_name` keep the accepted P2d2a
constraints and remain part of the normalized request even when a
variant does not emit `package_name`. Exact keys are enforced per
variant; unknown/missing keys fail. Relative paths remain canonical
POSIX paths with no absolute form, empty component, `.`, `..`,
backslash, NUL, URI scheme, or repeated separator. Existing input paths
remain lexically and physically contained, every existing component
non-symlink, with the required type. Output paths may be absent only
when every existing ancestor is a non-symlink real directory and
lexical containment is preserved. `build()` and `verify_plan()` remain
read-only even for variants whose future execution will mutate project
files. Where a legacy CLI requires a project-relative value persisted
into `pubspec.yaml`, the canonical relative value is emitted, not an
absolute filesystem path; the resolved target is validated separately.

### Operation 4: packaging.v1

The request carries the common fields plus `action` and only the fields
for that action. `action` is exactly one of `copy_assets`,
`update_pubspec_asset`, `prepare`, `verify`.

#### action `copy_assets`

Additional keys: `asset_manifest_path` (run-root-relative existing
non-symlink regular `.json` file) and `asset_target_path`
(project-root-relative target directory; may be an existing non-symlink
real directory or an absent directory whose existing ancestors are safe;
an existing regular file is rejected).

Emits one step `copy_assets` / `copy_assets.py`:

```
[sys.executable, FIXED_SCRIPT, "--manifest", ABS_MANIFEST, "--target", ABS_TARGET]
```

cwd = canonical `project_root`; timeout 120s.

#### action `update_pubspec_asset`

Additional key: `asset_path` (canonical project-relative existing
non-symlink regular file or real directory strictly below `assets/`;
`pubspec.yaml` itself and any path outside `assets/` are rejected,
including the prefix lookalikes `assets` and `assets_evil/...`). The
argv value remains this relative POSIX string.

The pubspec is not caller-selectable: `${project_root}/pubspec.yaml`
must be an existing non-symlink regular file with safe components.

Emits one step `update_pubspec_asset` / `update_pubspec_assets.py`:

```
[sys.executable, FIXED_SCRIPT, "--pubspec", ABS_PROJECT_PUBSPEC, "--asset", REL_ASSET_PATH]
```

cwd = canonical `project_root`; timeout 120s.

#### action `prepare`

Additional keys: `spec_root_path` (run-root-relative existing
non-symlink real directory) and `packaging_out_path` (run-root-relative
`.json` output path using the safe output-file rule). The pubspec is
fixed to `${project_root}/pubspec.yaml` and must be an existing safe
regular file. No caller-provided `font_source` is accepted or emitted;
`--font-source` is omitted so the immutable primitive owns its
fixed/default font mapping.

Emits one step `prepare_assembly_packaging` / `prepare_assembly_packaging.py`:

```
[sys.executable, FIXED_SCRIPT, "prepare", "--spec-root", ABS_SPEC_ROOT,
 "--project-root", ABS_PROJECT_ROOT, "--pubspec", ABS_PROJECT_PUBSPEC,
 "--out", ABS_OUT]
```

cwd = canonical `project_root`; timeout 120s.

The primitive, when later executed, remains the authority for valid
RED -> packaging chronology and for atomic pubspec mutation. The plan
builder does not simulate, bypass, or pre-issue that evidence.

#### action `verify`

Additional key: `packaging_evidence_path` (run-root-relative existing
non-symlink regular `.json` file).

Emits one step `verify_assembly_packaging` / `prepare_assembly_packaging.py`:

```
[sys.executable, FIXED_SCRIPT, "verify", "--evidence", ABS_EVIDENCE]
```

cwd = lexical parent directory of `ABS_EVIDENCE`; timeout 120s.
`verify_plan()` requires exact equality `cwd == Path(evidence).parent`
after lexical normalization.

### Operation 5: test_runner.v1

The request carries the common fields plus `phase` and only the fields
for that phase. `phase` is exactly one of `red`, `green`, `adopt`,
`verify`, `retire_stale_template_tests`.

P2d2b never accepts or emits `--flutter`. P2d2b does not trust a
caller-selected executable. The later P2e executor must bind the
primitive's inherited Flutter resolution to a successful current
`project_preflight` result; P2d2b only builds the immutable outer
Python argv.

#### phases `red`, `green`, `adopt`

Additional keys: `spec_root_path` (run-root-relative existing
non-symlink real directory) and `test_target` (canonical
project-relative existing non-symlink regular file or real directory
strictly below `test/`; `test` itself and any non-`test/` target are
rejected, including the prefix lookalike `test_evil/...`).

Emits one `assembly_tdd_guard.py` step, timeout 600s:

- red — `step_id = assembly_tdd_red`:

  ```
  [sys.executable, FIXED_SCRIPT, "red", "--spec-root", ABS_SPEC_ROOT,
   "--project-root", ABS_PROJECT_ROOT, "--test-target", REL_TEST_TARGET,
   "--failure-kind", "missing_feature_behavior"]
  ```

- green — `step_id = assembly_tdd_green`: the same fixed prefix through
  `REL_TEST_TARGET`, with no trailing caller options.
- adopt — `step_id = assembly_tdd_adopt`: the same fixed prefix through
  `REL_TEST_TARGET`, followed by `["--authorization", "preexisting-green"]`.

cwd = canonical `project_root` for all three.

#### phase `verify`

Additional key: `spec_root_path` (run-root-relative existing
non-symlink real directory).

Emits one step `verify_assembly_tdd` / `assembly_tdd_guard.py`:

```
[sys.executable, FIXED_SCRIPT, "verify", "--spec-root", ABS_SPEC_ROOT]
```

cwd = `ABS_SPEC_ROOT`; timeout 120s. `verify_plan()` requires exact
equality `cwd == Path(spec_root)`.

#### phase `retire_stale_template_tests`

Additional key: `retirement_out_path` (run-root-relative `.json` safe
output-file path).

Emits one step `retire_stale_template_tests` /
`retire_stale_flutter_template_tests.py`:

```
[sys.executable, FIXED_SCRIPT, "--project-root", ABS_PROJECT_ROOT, "--out", ABS_OUT]
```

cwd = canonical `project_root`; timeout 120s. This variant only
constructs the trusted plan; actual retirement stays in later serial
fan-in execution.

### cwd-binding rules

`verify_plan()` re-proves the cwd of every step from the validated argv
path values themselves (the plan carries no separate `project_root`
field). Each variant declares one fixed cwd-binding rule:

- `project_root_or_descendant` — cwd is the canonical `project_root`,
  and at least one validated absolute argv path must equal cwd OR be a
  strict descendant of cwd. Covers every P2d2a step and every
  project-bound P2d2b step (packaging copy/update/prepare, test_runner
  red/green/adopt/retire). Equality covers variants whose only
  project-rooted argv value is `--project-root <cwd>` itself.
- `evidence_parent` — cwd must equal the lexical parent directory of
  the validated `--evidence` argv value (packaging verify).
- `spec_root` — cwd must equal the validated `--spec-root` argv value
  (test_runner verify).

No variant can bypass cwd validation merely because it has no
project-rooted argv path; the two evidence-only verify variants use a
deterministic exact-equality rule instead.

### Plan verification requirements

`verify_plan()` extends the P2d2a verification without weakening it:

- infer the exact known variant from `(operation_id, step_id)` and
  reject every other combination;
- exact one-step count for each new variant;
- fixed primitive ownership/SHA/interpreter/script/subcommand/flag
  order/cwd/timeout, including the per-variant cwd-binding rule above;
- variant-specific path/value rules, including relative `--asset` and
  `--test-target` values;
- reject cross-variant step swapping, primitive reuse outside its owned
  variants, duplicated steps, extra argv, omitted flags, `--flutter`,
  `--font-source`, arbitrary authorization/failure kind, and any extra
  executable field;
- continue to state the evidence boundary accurately: without the
  original normalized request, `verify_plan()` proves
  schema/invariants/manifest binding and request-derived value shapes,
  not equality to an unavailable original request.

### P2d2b files

- `icp/scripts/platforms/flutter_operations_v1.py` — extended static
  trusted-operation plan registry (append-only five IDs).
- `icp/scripts/selftest_p2d2b_flutter_operations.py` — focused
  RED→GREEN self-test for the packaging/test_runner extension (run
  directly).
- `icp/scripts/selftest_p2d2a_flutter_operations.py` — updated
  append-only operation-list and unknown-operation expectations.

P2d2b deliberately stops at the plan registry extension. It does not
execute the plans, does not activate the adapter, does not change the
P2c descriptor, does not bind a Flutter executable, and does not
implement the runtime_capture, project_gates, or fan_in primitives
(added as static plans by the append-only P2d2c phase below), parity
runner, P2.5 contracts, Vue adapter, or end-to-end claiming.

## P2d2c — trusted Flutter argv plan registry extension (runtime_capture/project_gates/fan_in)

P2d2c is the append-only extension of the P2d2a/P2d2b static
trusted-operation plan registry with the final three single-step-
variant operations:

- `flutter.runtime_capture.v1`
- `flutter.project_gates.v1`
- `flutter.fan_in.v1`

The public Python API, the canonical plan schema (`kind` stays
`icp.trusted-operation-plan.v1`, no top-level `action`/`phase` field),
the capsule-first ordering, the recursive forbidden-key rejection,
strict duplicate-key rejection, generic-error type-only redaction, and
the no-`iff/**` rule all remain exactly as in P2d2a/P2d2b. The module
remains a static plan builder/verifier only — no CLI, no executor, no
writes, no subprocess import/call, no shell/env surface. **No plan is
executed yet.**

`list_operation_ids()` now returns the full append-only eight-ID tuple
shown in the P2d2a section above.

### Normalized-request digest coupling

For the P2d2c operations the plan carries no separate `project_root`
field. `verify_plan()` reconstructs the action's exact normalized
request from the validated plan's `(operation_id, step_id)`, `cwd`,
and validated argv values, canonical-JSON hashes that reconstructed
mapping, and requires exact equality with `request_digest`. This
couples `cwd` (the canonical `project_root`) to the digest so a
cwd-only substitution is detected even for actions whose argv contains
only spec-root paths (`select_device`, `capture`).

`build()` computes `request_digest` over the validated normalized
request mapping, not over any unvalidated raw request object. The
mapping is a small, unambiguous per-action structure (see below);
canonical key ordering comes from the module's canonical JSON helper.

This proves internal schema/invariants/current capsule binding and
normalized-request self-consistency, **not** equality to an
unavailable historical caller request. A fully coordinated
unauthenticated rewrite of every plan value plus a freshly recomputed
digest is outside what static verification can distinguish from a
different valid caller request; **P2e must bind the accepted
plan/digest to the current successful `project_preflight` and frozen
capsule/descriptor digests plus applicable shared policy before
executing any plan.**

### Append-only primitive ownership

All primitive paths and SHA-256 values come only from the verified
fixed `iff-v1-vendor.json` manifest. P2d2c adds no new primitive
files; it binds twelve already-vendored legacy primitives to the three
new operations.

`flutter.runtime_capture.v1` owns exactly:
`select_runtime_device.py`, `device_lock.py`,
`capture_runtime_screenshot.py`, `physical_device_preview.py`.

`flutter.project_gates.v1` owns exactly:
`check_interaction_wiring.py`, `check_api_integration.py`,
`check_fixture_source.py`, `check_capture_readiness.py`.

`flutter.fan_in.v1` owns exactly:
`assembly_plan_batch.py`, `assembly_worker_supervisor.py`,
`check_done_gate.py`, `assembly_completion.py`.

### Common request/path rules

Each request carries `project_root` (absolute canonical existing
non-symlink real directory; the cwd for every P2d2c action), `action`,
and (for most actions) `spec_root`. `spec_root` is an absolute
canonical existing non-symlink real directory that **may be outside**
`project_root`; all fixed spec artifacts below must be exact
descendants of that declared `spec_root`. The spec artifact basenames
are fixed in code, never caller-selectable. Exact request keys are
enforced per action; unknown/missing/extra keys fail. Recursively
reject any forbidden executable/command/shell/env/argv/script key.

No arbitrary caller-provided argv fragments, environment, stdin,
device IDs, labels, device pools, routes, references, dimensions,
densities, timeout overrides, APK paths, `dart-define`, or worker
commands are accepted.

### Operation 6: runtime_capture.v1 (optional-with-shared-policy)

Capability state remains `optional-with-shared-policy`. Actions:

- `select_device` / `select_runtime_device.py`:
  `--platform auto --command-timeout 10 --boot-timeout 120
  --out <spec_root>/runtime_device.json`; cwd `project_root`; timeout 180.
- `lock_acquire` / `device_lock.py`:
  `acquire --lock <project_root>/.icp/device.lock --timeout 900`;
  cwd `project_root`; timeout 960. No `spec_root` (lock actions reject it).
- `lock_release` / `device_lock.py`:
  `release --lock <project_root>/.icp/device.lock`; cwd `project_root`; timeout 120.
- `lock_status` / `device_lock.py`:
  `status --lock <project_root>/.icp/device.lock`; cwd `project_root`; timeout 120.
- `capture` / `capture_runtime_screenshot.py`:
  `--selection <spec_root>/runtime_device.json --command-timeout 15
  --launch-timeout 300 --out <spec_root>/actual.png
  --manifest <spec_root>/visual_manifest.json`; cwd `project_root`; timeout 600.
- `physical_preview` / `physical_device_preview.py`:
  `--project-root <project_root> --out <spec_root>/physical_device_preview.json`;
  cwd `project_root`; timeout 180.

Normalized request: `{action, project_root, spec_root}` for
`select_device`/`capture`/`physical_preview`; `{action, project_root}`
for the three lock actions (which reject `spec_root`).

`physical_preview` may only invoke that capsule script later; it does
not authorize execution of any `runCommand` contained in the script's
future output. Physical preview never substitutes for standard
`actual_source=simulator_screenshot` evidence.

### Operation 7: project_gates.v1 (required)

Capability state remains `required`. Actions (all timeout 120,
cwd `project_root`):

- `interaction_wiring` / `check_interaction_wiring.py`:
  `--lib-root <project_root>/lib --test-root <project_root>/test
  --entry <project_root>/lib/main.dart --pubspec <project_root>/pubspec.yaml
  --contract <spec_root>/interaction_contract.json
  --out <spec_root>/wiring_report.json`.
- `api_integration` / `check_api_integration.py`:
  `--api-contract <spec_root>/api_contract.json --lib-root <project_root>/lib
  --out <spec_root>/api_integration_report.json`.
- `fixture_source` / `check_fixture_source.py`:
  `--root <project_root>`. No `spec_root` (rejects it).
- `capture_readiness` / `check_capture_readiness.py`:
  `--project-root <project_root> --entry <project_root>/lib/main.dart
  --scene <spec_root>/scene.json --page-source <page_source>
  --policy-source <policy_source> --startup-policy-source <startup_policy_source>
  --out <spec_root>/capture_readiness.json`. Each of the three sources
  is an absolute canonical existing regular file strictly within
  `project_root` (no symlink traversal).

`--safe-area-source` and any optional CLI flags are not exposed in this
phase. The three capture-readiness source keys are rejected for the
other three project-gate actions; missing or extra keys fail for every
action.

Normalized request: `{action, project_root, spec_root}` for
`interaction_wiring`/`api_integration`; `{action, project_root}` for
`fixture_source`; `{action, project_root, spec_root, page_source,
policy_source, startup_policy_source}` for `capture_readiness`.

### Operation 8: fan_in.v1 (required)

Capability state remains `required`. Actions (all timeout 120,
cwd `project_root`, request `{project_root, spec_root, action}`,
normalized `{action, project_root, spec_root}`):

- `plan_prepare` / `assembly_plan_batch.py`:
  `prepare --spec-root <spec_root> --project-root <project_root>
  --context <spec_root>/assembly_context.json
  --decisions <spec_root>/assembly_decisions.json`.
- `plan_apply` / `assembly_plan_batch.py`:
  `apply --context <spec_root>/assembly_context.json
  --decisions <spec_root>/assembly_decisions.json`.
- `supervisor_prepare` / `assembly_worker_supervisor.py`:
  `prepare --contract <spec_root>/assembly_invocation.json`.
- `supervisor_verify` / `assembly_worker_supervisor.py`:
  `verify --contract <spec_root>/assembly_invocation.json`.
- `done_gate` / `check_done_gate.py`:
  `--spec-root <spec_root> --out <spec_root>/done_gate.json`.
- `completion_issue` / `assembly_completion.py`:
  `issue --spec-root <spec_root> --evidence <spec_root>/assembly_completion.json`.
- `completion_verify` / `assembly_completion.py`:
  `verify --spec-root <spec_root> --evidence <spec_root>/assembly_completion.json`.

`assembly_worker_supervisor.py run ... command` is **deliberately
unsupported** because it accepts an arbitrary trailing command. `run`
is not a selectable action and no returned plan contains a free
command tail. Commands emitted by physical-preview output are likewise
deferred to a later fixed trusted executor.

### Plan verification requirements

`verify_plan()` extends the P2d2a/P2d2b verification without weakening
it. For P2d2c operations it additionally: derives the exact spec root
from each fixed artifact path; requires all spec paths for an action to
share that parent/root and fixed basename; binds the fixed project
paths (`lib`, `test`, `lib/main.dart`, `pubspec.yaml`) to `cwd`;
requires `capture_readiness` sources to be strictly within `cwd`;
reconstructs the normalized request mapping; and requires
`request_digest` to equal the canonical-JSON SHA-256 of that
reconstructed mapping. A cwd-only substitution, an argv-path-only
substitution, or a request-digest-only substitution is therefore
rejected.

### P2d2c files

- `icp/scripts/platforms/flutter_operations_v1.py` — extended static
  trusted-operation plan registry (append-only eight IDs).
- `icp/scripts/selftest_p2d2c_flutter_operations.py` — focused
  RED→GREEN self-test for the runtime_capture/project_gates/fan_in
  extension (run directly).
- `icp/scripts/selftest_p2d2a_flutter_operations.py` and
  `icp/scripts/selftest_p2d2b_flutter_operations.py` — updated
  append-only operation-list and unknown-operation expectations.

P2d2c deliberately stops at the static plan registry. It does not
execute the plans, does not activate the adapter, does not change the
P2c descriptor, does not bind a Flutter executable, and does not
implement the supervisor `run` command or commands emitted by
physical-preview output. **P2e must bind execution to the current
successful project preflight, frozen capsule/descriptor digests, and
applicable shared policy before running any plan.**

## P2e1 — frozen selection verifier + non-executable Flutter execution binding

P2e1 is the first P2e safety slice: a shared read-only verifier for
the existing frozen selection manifest, and a Flutter-specific
deterministic execution binding that re-attests the current manifest,
descriptor, capsule, project preflight, exact operation request,
rebuilt plan, and source digests. **This slice remains
non-executable.** It prepares the proof boundary for the later P2e2
fixed executor; it does not run any trusted operation plan, does not
activate Flutter, does not claim/writeback rows, and does not modify
iFF/capsule/registries/descriptors.

### Shared frozen selection verifier

`icp/scripts/verify_selection_manifest_v1.py` exposes:

* `verify(manifest_path) -> dict` — re-attests the current
  `selection-manifest.json` by recomputing the canonical payload
  through `freeze_selection_manifest.build_manifest_payload` with the
  current `icp_common.load_registries()` and requiring byte-identical
  canonical bytes against the file bytes. Requires the supplied path to
  equal the recomputed `<run_root>/selection-manifest.json` with
  canonical no-symlink roots. Returns
  `icp.selection-manifest-verify.v1` with exact keys: `kind`,
  `schema_version`, `batch_id`, `platform_id`, `profile_id`,
  `project_root`, `state_root`, `run_root`, `manifest_path`,
  `manifest_sha256`, `registry_digest`, `selected_profile_digest`,
  `rules_digest`, `actual_batch_size`.

The verifier requires `resolved.profile` to equal the current registry's
selected `default_profile` for `resolved.platform`, and rejects an
unknown platform. It reuses the existing syntax-only design-locator
validation (no network). It is read-only: no write, no mkdir, no temp
file, no subprocess, no shell, no symlink create, no claim, no writeback.

**Unsigned-manifest candidate-value boundary:** the verifier performs
structural candidate validation (exact keys/types, empty status,
nonempty/unique title, positive/unique row index, valid locator, count)
and current-registry binding, but it cannot independently distinguish an
arbitrary valid candidate-value rewrite that produces another
structurally valid frozen manifest. Detecting that requires the trusted
orchestrator to retain the expected manifest SHA-256 out of band. The
Flutter binding records the exact `selection_manifest_sha256`; the P2e2
executor/orchestrator must compare it against the expected value before
running any plan.

### Internal manifest run-root rule (P2d2a alignment)

P2e1 resolved an upstream contradiction: `freeze_selection_manifest`
derives the Flutter run root as `<project>/.iff/icp_runs/<batch_id>`
(nested inside the project), while the P2d2a plan builder previously
rejected every run root nested inside `project_root`.
`flutter_operations_v1._check_root_nesting` now accepts a project-
internal `run_root` **only** when its project-relative path is exactly
`.iff/icp_runs/<batch_id>` (the frozen manifest's canonical internal run
root), where `<batch_id>` matches the freezer's safe grammar
`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`. Every other project-internal path
(`lib`, `test`, `.dart_tool`, `.iff`, `.iff/icp_runs`, extra segments,
prefix lookalikes) remains rejected. A disjoint project-external
`run_root` remains accepted for compatibility. Symlinked `.iff`,
`icp_runs`, or batch are rejected by the existing root validator before
this rule runs.

### Flutter non-executable execution binding

`icp/scripts/platforms/flutter_execution_binding_v1.py` exposes:

* `prepare_binding(manifest_path, operation_id, request) -> dict` —
  hard order: (1) call the shared selection verifier; (2) require frozen
  platform/profile exactly `flutter`/`flutter-standard`; (3) verify the
  current capsule + descriptor; (4) require descriptor
  inactive/non-executable and `operation_id` is one of the current eight
  plan IDs; (5) map the operation to exactly one descriptor port and
  require the frozen and descriptor capability states match and are not
  `unsupported`; (6) validate the request (canonical-JSON-suitable,
  contains `project_root` equal to the frozen manifest project root;
  when `run_root` is present it must equal the frozen manifest
  `run_root` exactly; when absolute `spec_root` is present it must equal
  or be a strict no-symlink descendant of the frozen Flutter
  `state_root`); (7) run fresh fixed Flutter project preflight; (8) call
  `flutter_operations_v1.build` then `verify_plan` (never accept a
  caller-supplied plan); (9) produce a deterministic binding.
* `verify_binding(binding) -> dict` — minimum safe type/literal/digest
  checks, then re-runs the complete current preparation chain using only
  `selection_manifest_path`, `operation_id`, and a detached `request`
  copy, and requires exact equality with the candidate binding. Returns
  `icp.flutter-execution-binding-verify.v1`.

The binding carries `activation_state = inactive` and
`executable = false` always. It never imports `subprocess`; the only
subprocess in the chain is the fixed preflight's
`flutter --version --machine` probe. The embedded request, plan, and
reports are detached canonical-data copies.

**Remaining unsigned-binding boundary:** a fully coordinated rewrite of
an entire binding to another valid current run (manifest + request +
plan + all digests recomputed) remains outside static authentication.
The trusted orchestrator must retain the expected selection-manifest
 path/digest out of band. P2e2 must enforce that comparison before
 execution.

### P2e1.1 producer hardening: whole-string batch-id grammar

The documented `batch_id` grammar
`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$` is a *whole-string* contract.
Python's `re.match(r'...$')` accepts a value ending in a single
newline (`$` may match before the final newline); macOS permits a
directory name containing a newline, so a trailing-newline `batch_id`
was a real on-disk attack surface. P2e1.1 closes that gap at the shared
producer (`freeze_selection_manifest`) in addition to the independent
verifier and Flutter operation root rule, which already fail closed via
`re.Pattern.fullmatch`.

The producer now rejects a trailing-newline (and any
whitespace-containing) `batch_id` at the input boundary in
`derive_roots`, before any state/run directory or manifest is created.
The documented regex pattern itself is unchanged; only the matching call
changed from `.match` to `.fullmatch`. The verifier's independent
`_BATCH_ID_RE.fullmatch` check is retained unchanged as defence-in-depth
so a tampered manifest whose canonical bytes were rewritten by an
attacker is still rejected even if the producer's enforcement were ever
weakened.

Validation truth: the producer, the shared verifier, and the Flutter
operation root rule now all enforce the same whole-string grammar with
`fullmatch`. A manifest whose `batch_id` ends in a newline cannot be
produced through `freeze_selection_manifest`; if it reaches the verifier
through canonical tampering, the verifier rejects it independently.

### Files added/changed by P2e1

* `icp/scripts/verify_selection_manifest_v1.py` — shared read-only
  verifier (independent `fullmatch` defence-in-depth, unchanged in
  P2e1.1 beyond comment accuracy).
* `icp/scripts/platforms/flutter_execution_binding_v1.py` — Flutter
  non-executable binding.
* `icp/scripts/selftest_p2e1_selection_manifest.py`,
  `icp/scripts/selftest_p2e1_flutter_binding.py` — selftests.
* `icp/scripts/platforms/flutter_operations_v1.py` — narrow
  `_check_root_nesting` extension (internal manifest run root).
* `icp/scripts/selftest_p2d2a_flutter_operations.py` — focused tests
  for the internal run-root rule.
* `icp/scripts/freeze_selection_manifest.py` — P2e1.1 producer
  hardening: `batch_id` grammar enforced with `.fullmatch` (pattern
  unchanged).
* `icp/scripts/selftest_p1b.py` — P2e1.1 producer tests:
  trailing-newline rejection before any disk change; exact max-length
  (128-char) acceptance.

## P2e2a — non-executable Flutter execution authorization candidate

P2e2a is the second P2e safety slice: a deterministic, **non-
executable**, unsigned `icp.flutter-execution-authorization-candidate`
envelope produced from an existing verified
`icp.flutter-execution-binding.v1` binding. The candidate is **not**
self-authorizing authority. It records exactly one prepared request and
plan, binds every plan step's interpreter / primitive script / argv /
cwd / timeout to the current bytes, and names its own
`authorization_digest` — but it carries no execution authority of its
own. The trusted supervisor must retain these expected values out of
band before authorizing any spawn:

* the canonical selection-manifest path;
* the selection-manifest SHA-256;
* the verified binding digest;
* the prepared authorization digest.

`icp/scripts/platforms/flutter_execution_authorization_v1.py` exposes:

* `prepare_authorization(binding, *, expected_manifest_path,
  expected_manifest_sha256, expected_binding_digest, execution_nonce)
  -> dict` — requires all four trusted expected values and the caller-
  supplied nonce (exactly 32 lowercase hex chars, `fullmatch`-enforced;
  never generated). Re-attests the binding through the shared
  `flutter_execution_binding_v1.verify_binding` rather than duplicating
  or weakening it; cross-checks each expected value against the verified
  binding/report (each comparison independent, any mismatch fails
  closed); embeds a deep, JSON-safe snapshot of the complete verified
  binding so one candidate names one exact request and plan; and binds
  every plan step's `argv[0]` executable canonical path + current
  SHA-256, `argv[1]` primitive script canonical path + current SHA-256
  (hash-equal to the step's `primitive_sha256`), argv digest over the
  full argv list, canonical cwd, timeout, plus a deterministic step-
  authorization digest over all those fields. Produces a top-level
  `authorization_digest` over a canonical compact-separator JSON
  payload that excludes only that self-referential field.
* `verify_authorization(authorization, *, expected_manifest_path,
  expected_manifest_sha256, expected_binding_digest,
  expected_authorization_digest) -> dict` — requires all four trusted
  expected values; none may default, be inferred from the untrusted
  document, or be optional. Strict shape/literal/digest validation;
  cross-checks every expected value against the authorization;
  recomputes the top-level authorization digest; re-attests the
  embedded verified binding through `verify_binding`; and recomputes
  every per-step authorization from the embedded binding's plan steps
  (re-hashing current interpreter and primitive script bytes,
  re-validating argv[0]/argv[1] canonical/regular/non-symlink).
  Requires exact equality at every stage. Returns
  `icp.flutter-execution-authorization-verify.v1`.

The candidate carries `schema_version = 1`,
`kind = "icp.flutter-execution-authorization-candidate"`,
`platform_id = "flutter"`, exact profile/operation/port/capability
identity copied from the verified binding, `activation_state =
"inactive"` and `executable = false` always. Per-step snapshots are
strict, ordered, and reject unknown fields, malformed hashes/paths,
bool-as-int timeouts, non-JSON values, NaN/Infinity, addition,
deletion, reordering, duplicates, and any digest mismatch. Canonical
JSON for the authorization is UTF-8, sorted keys, compact separators
`(",", ":")`, `allow_nan=False`, deterministic across repeated calls;
digests hash those bytes with SHA-256. No timestamps, environment
snapshots, hostnames, random values, or nondeterministic ordering.

The module has no CLI, never imports `subprocess`/`socket`/`urllib`/
`http.client`, never uses `shell=True`, never writes a file, never
creates a symlink, never directly spawns a process, and performs no
import-time I/O (the installed binding-module path is derived purely
lexically via `Path(os.path.abspath(__file__)).parent`; every
resolve/lstat/read runs lazily inside `_load_binding_module` or the
per-step binders). Ordinary file reads/stat/hash operations are
allowed at call time. The selftest's AST/static guard proves only the
*direct* imports/calls of this module have no subprocess/shell/network/
write surface; it does not (and cannot) prove the entire transitive
call graph has no subprocess.

### Process / I/O boundary (truthful)

* **No operation-plan command is executed.** This slice never spawns
  the per-step argv plans recorded in the binding.
* **No direct subprocess, shell, network, or filesystem-write surface
  exists in the new module.**
* **The shared binding verifier is intentionally re-entered on every
  prepare and verify call**, and that verifier re-runs the fixed
  read-only Flutter project preflight
  `subprocess.run([resolved_flutter, "--version", "--machine"],
  shell=False, ...)`. Therefore `prepare_authorization` and
  `verify_authorization` CAN cause that one fixed, read-only child
  process to run, and CAN fail if that fixed preflight fails (no
  Flutter on PATH, wrong version, etc.). This is the only process
  surface in the transitive call chain, and it is owned by
  `flutter_project_preflight_v1.preflight`, not by this module.
* No receipt is written; the project/state/run roots are not mutated
  by this module; no platform adapter is activated; the execution
  nonce is only recorded (never consumed).

### Trust and TOCTOU boundary

* The authorization candidate and the embedded manifest/binding are
  **unsigned candidate values**. The supervisor-held expected digest
  tuple — `(expected_manifest_path, expected_manifest_sha256,
  expected_binding_digest, expected_authorization_digest)` — is the
  trust anchor. An attacker who can rewrite workspace files cannot
  authorize a different valid binding merely by recomputing in-document
  digests: `verify_authorization` requires all four expected values.
* This slice executes no operation-plan command and consumes no nonce.
  (Re-attesting the embedded binding re-runs the fixed read-only
  Flutter version preflight subprocess described above.)
* P2e2b must call `verify_authorization` **immediately before each
  spawn**, atomically claim the recorded nonce (single-writer
  compare-and-swap keyed on the supervisor-held expected authorization
  digest), and re-check executable and primitive-script bytes/paths
  immediately before each exact argv spawn.
* A normal path-based `subprocess` spawn still retains a small
  check-to-exec race after these checks. This slice alone does **not**
  eliminate that verify-to-spawn TOCTOU window. P2e2b must report that
  residual unless a separately implemented and tested OS-specific
  fd-bound execution mechanism actually closes it.

### Files added/changed by P2e2a

* `icp/scripts/platforms/flutter_execution_authorization_v1.py` —
  non-executable authorization candidate producer/verifier.
* `icp/scripts/selftest_p2e2a_flutter_authorization.py` — vertical
  RED -> GREEN selftest through the real freezer / selection verifier /
  Flutter binding builder (Flutter preflight stubbed in-process); 81
  cases covering the public contract, every out-of-band expected-value
  mismatch, authorization-digest tamper and coordinated-recompute
  attack, embedded binding tampering, step reorder/add/delete/duplicate,
  per-step argv[0]/argv[1]/argv-digest/cwd/timeout/primitive
  id/path/hash tampering, executable/script digest drift, the
  per-step-authorization's own fail-closed branches for
  non-canonical/symlink/missing/non-file executable and script
  (exercised directly via the module's `_bind_current_executable` /
  `_bind_primitive_script` helpers so the tests do not modify the real
  interpreter), no project/state/run-root writes during prepare/verify,
  a strengthened AST/static guard proving no import-time I/O and no
  *direct* subprocess/shell/network/write surface in this module, a
  contract test that the module and SKILL truthfully state the
  transitive preflight process boundary, NaN/Infinity and bool-as-int
  rejection, and continued producer/verifier rejection of
  trailing-newline `batch_id`.
* `icp/SKILL.md` — this section.

## P2e2b — fixed-argv Flutter activation executor

P2e2b is the first activation slice. Given an authorization produced
and verified by P2e2a
(`icp.flutter-execution-authorization-candidate`), `execute_authorization`
executes only the exact ordered operation-plan steps already bound by
that candidate, consumes the authorization nonce exactly once, and
leaves durable receipts that make every success, failure, timeout,
launch error, or uncertain/crashed attempt non-replayable.

`icp/scripts/platforms/flutter_execution_executor_v1.py` exposes:

* `execute_authorization(authorization, *, expected_manifest_path,
  expected_manifest_sha256, expected_binding_digest,
  expected_authorization_digest) -> dict` — requires all four trusted
  expected values; none may default, be inferred from the untrusted
  document, or be optional. Calls
  `flutter_execution_authorization_v1.verify_authorization` with all
  four values (which transitively re-runs the fixed read-only Flutter
  project preflight
  `[resolved_flutter, "--version", "--machine"]` with `shell=False`,
  owned by `flutter_project_preflight_v1.preflight`), derives the run
  root from the freshly verified candidate's embedded
  `selection_verification.run_root` (cross-checked against
  `Path(selection_manifest_path).parent`; no caller override), opens
  the run root as a directory fd with `O_NOFOLLOW | O_CLOEXEC` where
  supported, and opens/creates the fixed receipt directory
  `<run_root>/.icp-execution-receipts-v1/` relative to that fd. A
  freshly created receipt directory is forced to exactly `0700` via
  `fchmod` and verified with `fstat`; an existing one must be owned by
  the current uid with permissions no broader than `0700` (it may be
  stricter). The nonce is atomically claimed with
  `O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC` and mode exactly `0600`
  (`fchmod`-forced and `fstat`-verified), canonical UTF-8 JSON,
  `fsync(file)` and `fsync(dir)`.

The claim binds schema/kind, execution nonce, expected authorization
digest, binding digest, selection manifest path/SHA, platform/profile/
operation/port IDs, and the ordered step-authorization digests. The
terminal result binds the claim digest and the expected authorization
digest and contains only sanitized execution metadata; raw stdout/stderr
is never persisted.

After the claim, the embedded binding plan is executed serially and the
loop stops at the first non-success. Immediately before every
operation-plan spawn: `verify_authorization` is re-run with the same
four expected values (re-running the fixed transitive Flutter version
preflight); the plan step is required to equal its same-index step
authorization (step id, primitive, primitive path/SHA, argv digest,
cwd, timeout, executable path/SHA, step-authorization digest); the
bound argv is copied to an immutable local tuple (every element a
string, `argv[0] == sys.executable` exactly with the lexical Homebrew
symlink valid, `argv[1]` equal to the bound primitive path exactly, no
NULs); `sys.executable` canonical realpath target, regular-file
status, and SHA-256 are re-checked; the primitive script is
`lstat`-checked (existing, regular, leaf non-symlink) and strict-
canonical-resolved (a symlinked ancestor like macOS `/var` is
rejected); the cwd is `lstat`-checked (existing directory, leaf
non-symlink) and strict-canonical-resolved; the primitive and cwd
SHA-256 are re-hashed. The tuple is then spawned with `shell=False`,
the exact cwd, the exact timeout, `stdin=DEVNULL`, `close_fds=True`,
and `start_new_session=True`.

### Output and timeout

stdout/stderr are fully drained without unbounded memory growth or
pipe deadlock. SHA-256 and total byte count are computed over the
complete streams; a reader `OSError` is recorded as a sanitized
`read_error` rather than silently treated as clean EOF. After process
reap both reader threads are joined with a bounded timeout; if either
is still alive the spawned process session/group is killed
(`SIGKILL` via `killpg`), pipe handles are closed, and the threads are
joined again. Any reader `OSError`, incomplete drain, or stuck reader
classifies the step as `output_drain_failure` (a fatal step failure):
later steps do not run, a sanitized terminal result is persisted by
the claim owner, raw output is never persisted, and no live process or
reader thread is leaked on any normal error path. At most 16 KiB tail
per stream is retained in memory for the returned report
(base64-encoded); truncation is marked. On timeout the whole spawned
process session/group is killed, reaped, pipes drained/closed, the
terminal result is persisted, and later steps do not run.

### One claim owner, one terminal-result owner

Only the call that successfully creates `<nonce>.claim.json` owns the
right to create `<nonce>.result.json`. Any caller that loses `O_EXCL`
rejects immediately before any operation-plan spawn and never creates,
replaces, deletes, truncates, or otherwise mutates either receipt.
`claim present + result absent` is itself the durable
`indeterminate/consumed` state and needs no materialized result file
(a hard crash can leave claim-only forever). `claim present +
result present` is terminal/consumed. The original claim owner writes
the terminal result for success, nonzero exit, timeout, launch error,
post-claim verification/integrity/output-drain/internal failure, and
cancellation (re-raised after the result is persisted).

### Honest boundaries

* Pre-claim and per-spawn authorization verification transitively run
  the fixed read-only `[resolved_flutter, "--version", "--machine"]`
  preflight with `shell=False`, owned by
  `flutter_project_preflight_v1.preflight` — not by this module's
  spawn surface. Only operation-plan steps are activated by this
  module; the transitive preflight is not an operation-plan command.
* The caller cannot inject argv, cwd, timeout, environment, shell, or
  receipt root. There is no caller-provided environment: the executor
  builds an environment from the trusted supervisor process
  environment, strips Python/dynamic-loader/shell startup injection
  variables (`PYTHON*`, `LD_*`, `DYLD_*`, `BASH_ENV`, `ENV`, `CDPATH`),
  and sets at least `PYTHONDONTWRITEBYTECODE=1` and
  `PYTHONNOUSERSITE=1`. Ordinary toolchain variables such as
  `PATH`/`HOME`/Flutter/Android variables are preserved. **This
  environment is executor policy derived from trusted supervisor input
  and is not bound by P2e2a.** The supervisor process environment
  remains trusted input.
* The fd-relative `O_EXCL` claim closes the nonce filename
  symlink/replay race; it does not close executable/script path
  replacement races. Normal path-based executable/script spawn still
  has a small check-to-exec TOCTOU residual; this module does not
  implement a separate OS-specific fd-bound execution mechanism that
  would close that residual.
* Claim-only means indeterminate/consumed and replayers never write a
  terminal result. Only the successful claimant owns terminal-result
  creation.

The returned report is a versioned strict-schema
`icp.flutter-execution-report.v1` object with overall status,
authorization/claim/result digests, execution nonce, and ordered per-
step results (including the capped transient tails). Canonical JSON
for receipts is UTF-8, sorted keys, compact separators `(",", ":")`,
`allow_nan=False`. No timestamps, PIDs, random values, hostnames, or
absolute environment dumps are written into receipts.

### Files added/changed by P2e2b

* `icp/scripts/platforms/flutter_execution_executor_v1.py` — the
  fixed-argv activation executor.
* `icp/scripts/selftest_p2e2b_flutter_executor.py` — vertical RED ->
  GREEN selftest through the real freezer / verifier / binding /
  authorization chain (Flutter preflight stubbed in-process; primitive
  scripts substituted with safe test scripts in realpath-canonical
  temp directories); 80+ cases covering the public contract, every
  out-of-band expected-value mismatch, real safe happy-path single
  and multi-step execution, ordered argv/cwd/timeout with no shell or
  caller override, per-spawn verification count/order on a real
  three-step fixture, every bound-field table-driven tampering plus
  step add/delete/reorder, executable/canonical/SHA drift, primitive
  symlink/path/SHA drift including ancestor-symlink rejection, cwd
  symlink/path drift including ancestor-symlink rejection, atomic
  claim/result permissions/content/digest (exact 0600 files, exact
  0700 newly created receipt dir, fsync evidence), raw output absent
  from disk, replay after success/nonzero/timeout/launch failure/
  post-claim verification/integrity failure and claim-only crash state
  (no spawn on replay, no result written by the replay loser),
  concurrent atomic claim contention (exactly one claim owner, one
  spawn, one terminal result), receipt-directory defenses (symlink,
  non-directory, broad perms, wrong owner via a fake-stat seam,
  symlink at claim/result paths), multi-megabyte bounded tails and
  full-stream hashes with no deadlock, timeout process-group kill/reap
  with later steps skipped, non-zero/signal/launch errors sanitized,
  output-drain failure on reader `OSError` and on stuck reader, run-
  root/manifest-parent cross-check, cancellation after claim, internal
  error after claim, a strengthened AST/static guard proving
  import-time zero I/O and no `shell=True`/`os.system`/arbitrary
  command API/claim overwrite/delete/raw output persistence, and
  contract tests that prove the truthful transitive-preflight,
  environment-trust, and TOCTOU statements in both module and this
  SKILL section.
* `icp/SKILL.md` — this section.

## P2.5a1 — SharedCore expected/slots projection contract (non-executable)

P2.5a1 is a **contract + proof only** slice. It introduces the first
platform-neutral SharedCore contract for the deplatformization track: the
expected/slots projection v1. SharedCore owns only (a) strict validation of a
platform-neutral projection, (b) deterministic construction of the legacy
`*.expected.json` and `*.slots.json` documents, and (c) byte serialization
exactly matching the frozen legacy JSON sidecars emitted by the iFF v1
compatibility capsule. **No consumer has switched yet.** The projection is
the only new SharedCore contract in this slice.

### What is implemented

`icp/scripts/shared_core/expected_slots_projection_v1.py` is a pure
standard-library-only module. It exposes no CLI, performs no filesystem or
network I/O, makes no process calls, accepts no path/root override, and never
imports a platform module or the iFF v1 compatibility capsule. Its public API
is exactly:

- `build_documents(projection) -> (expected_doc, slots_doc)` — deterministic
  reconstruction of the legacy documents;
- `build_legacy_bytes(projection) -> (expected_bytes, slots_bytes)` — bytes
  are exactly `json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")`
  with no sorted keys and no trailing newline;
- `ProjectionValidationError(ValueError)` — the dedicated validation
  exception type.

The v1 projection shape is strictly validated. The validation rejects missing
or unknown top-level/node keys, wrong `kind`/`schemaVersion`, non-finite or
non-positive dimensions/scale, booleans where numbers are expected, NaN or
infinity anywhere a number is required, `nodes` not a list, node not an
object, non-string/empty/duplicate ids, bbox not a 4-list of finite numbers,
non-object or empty `horizontalAnchor`, wrong types for `impl`/`text`/
`sourceText`/`textRuns`/`fontSize`/`weight`/`colorHex`/`radius`, `slot` not a
boolean, and `slot: true` on a node whose `impl != "text"` or whose `text` is
not a string. Node/list insertion order is contractual and preserved.

The legacy expected document key order is contractual: `artboardWidth`,
`artboardHeight`, `designPixelScale`, `logicalDesignWidth`, `nodes`. Each
expected node key order is contractual: `bbox`, `logicalBbox` (each bbox
number divided by scale and rounded with Python `round(..., 2)`),
`horizontalAnchor`, `impl`, `text`, `sourceText`, `textRuns`, `fontSize`,
`weight`, `colorHex`, `radius`. The slots document maps each `slot: true`
node id to its display text in projection list order.

### Why a strict ordered projection, not independent regeneration

The frozen capsule derives expected/slots from internal state produced by its
own `emit_node()` over already-normalized nodes. `placed[nid]` is written only
after normalization/filtering; `anchors[nid]` is derived from that final bbox;
`emit_node()` returning `None` causes the caller to remove `placed[nid]`.
Expected/slots emission consumes `nodes`, `placed`, `anchors`, `slot_ids`,
artboard dimensions, and design pixel scale. SharedCore therefore MUST NOT
independently regenerate this state from a render plan — that would duplicate
platform-bound layout/codegen logic and create a second truth source. The v1
projection is a strict, ordered, platform-neutral view of the *final*
intermediate state; a future platform adapter produces it from its own
already-computed state, and SharedCore only validates and re-serializes.

### Differential parity proof

`icp/scripts/selftest_p25a1_expected_slots_projection.py` is a focused
RED -> GREEN selftest. The differential parity proof verifies the capsule
through the existing fixed verifier before touching it; refuses to weaken
capsule hashing (it asserts the capsule `generate_canvas.py` SHA-256 equals
the manifest entry); imports the capsule in-process by file path; wraps
`emit_node` (without modifying the capsule) to retain references to the final
`nodes`/`placed`/`anchors`/`slot_ids` state; uses the capsule's own helper
functions as the test-only oracle to derive display text/runs, color, and
radius; builds the neutral projection; and then requires byte-for-byte
equality between `build_legacy_bytes(projection)` and the actual sidecars the
capsule writes. The corpus covers Unicode text (CJK + emoji + accents), a
dynamic text slot, multi-color styled text runs, a non-text shape, a
non-default scale (`scale = 2`), and deterministic insertion order. A second
direct projection case covers radius-as-array and weight-as-string forms the
frozen input schema cannot represent, without weakening the parity test.
Mutation proofs change a projected bbox and a projected slot text and prove
the byte equality breaks.

Production SharedCore never imports the capsule. A static AST guard verifies
the production module imports only the standard library; a forbidden-token
guard verifies the P2.5 deplatformization forbidden literals (process /
network / filesystem execution surface, capsule import paths, CLI helpers)
appear in the TEST only, never in the production source. No path/root
override is accepted by the production API.

### P2.5a1 files

- `icp/scripts/shared_core/__init__.py` — SharedCore package marker.
- `icp/scripts/shared_core/expected_slots_projection_v1.py` — pure
  standard-library-only projection validator + legacy byte reconstructor.
- `icp/scripts/selftest_p25a1_expected_slots_projection.py` — focused
  RED -> GREEN selftest with differential parity proof.
- `icp/SKILL.md` — this section.

P2.5a1 deliberately stops at the contract and its differential proof. **No
execution authority or platform support changed.** No platform adapter, no
selection binding, no operation registry, no authorization, no executor, and
no activation gate is touched. No consumer has switched to the projection
yet. P2.5a2 must make a platform adapter produce this projection from its own
already-computed intermediate state before any consumer cutover; until then
the projection has no producer. P3 remains forbidden.

## P2.5a2 — Flutter expected/slots adapter (digest-bound platform post-step)

P2.5a2 adds exactly one explicit, digest-bound post-step to
`flutter.visible_codegen.v1`, immediately after `generate_canvas` and before
`make_implementation_map`: the `adapt_expected_slots` step. The visible-codegen
operation now has exactly four ordered steps: `generate_canvas`,
`adapt_expected_slots`, `make_implementation_map`, `make_status_bar_policy`.
No registry entry is added, no operation ID is added, and the request shape is
unchanged. The step is covered end-to-end by the existing
binding -> authorization -> executor SHA/path/nonce/receipt chain.

### What is implemented

`icp/scripts/platforms/flutter_expected_slots_adapter_v1.py` is a fixed
project-local platform primitive (never copied into or registered inside the
frozen vendor capsule). CLI arguments are exactly
`--project-root <absolute dir>` and `--canvas <absolute .dart path>`; argparse
uses exact `parse_args` semantics (any unknown flag or extra positional is
rejected before any sidecar is touched). The operation cwd remains the
validated project root.

The adapter:

1. derives the sidecar paths exactly as `<canvas>.expected.json` and
   `<canvas>.slots.json`; both must be existing non-symlink regular files
   owned by the current user (where portable) and strictly contained under
   the project root;
2. bounded-reads each sidecar (16 MiB maximum per sidecar), strict-decodes
   as UTF-8 JSON with duplicate-key rejection, and reconstructs the
   platform-neutral `icp.shared.expected-slots-projection.v1` losslessly
   (preserving node insertion order, ignoring the derived `logicalBbox` and
   `logicalDesignWidth`, mapping `slot = (id in slots_doc)`);
3. loads SharedCore (`shared_core/expected_slots_projection_v1`) only from
   the fixed installed sibling path derived from `__file__` (no caller
   override is accepted), sets `sys.dont_write_bytecode = True` so no
   `__pycache__` appears under `shared_core/`, and calls
   `build_legacy_bytes(projection)`;
4. requires byte-for-byte equality between both rebuilt sidecars and the
   original raw bytes — a failure in either prevents the first replace;
5. atomically persists the byte-identical SharedCore output: prepare both
   temp files in the sidecar directory, `fsync` both, re-lstat both
   originals and require exact identity equality
   (`st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, `st_mode`, `st_uid`)
   in addition to byte equality, then `os.replace` each (preserving each
   original regular file's mode, rejecting symlinks and non-current-owner
   files). A crash between the two replaces is semantically safe because
   old and new bytes are identical.

### Trust / path / data flow

The trust root for the platform primitive is the fixed step specification
inside `flutter_operations_v1.py` (whose current bytes are already bound as
`operations_module_sha256`). No adapter manifest exists. The internal step
spec carries a closed `script_origin` field with exactly two values:
`capsule` (the default, used by the three legacy primitives, resolved through
`CAPSULE_SCRIPTS_DIR` and the frozen vendor manifest) and `platform` (used
only by `adapt_expected_slots`, resolved through the fixed
`PLATFORM_SCRIPTS_DIR = ICP_ROOT / "scripts" / "platforms"`). The platform
basename must not collide by basename with any capsule-manifest primitive;
its SHA-256 is recomputed from the regular non-symlink file on every
build/verify. The plan schema carries no caller-controlled origin field;
build and verify use the same origin-aware resolver. The frozen generator
remains the compatibility source for layout and still writes its sidecars
first; the adapter never imports it, intercepts it, reads render-plan
inputs, or reproduces placement/layout/text algorithms. SharedCore remains
import-only/non-executable and byte-unchanged.

### Fail-closed boundary

Missing, malformed, noncanonical (e.g. trailing newline), duplicate-key,
oversized, symlinked, out-of-root, changed-during-read, or parity-divergent
inputs raise the module-local typed `ExpectedSlotsAdapterError` and write
nothing. A same-bytes-different-inode substitution between read and replace
is detected via the lstat-identity revalidation. CLI failures surface only
the exception type name and a short, fixed message — no traceback, raw file
content, or supplied path is leaked. The module is standard-library-only and
never imports `subprocess`/`socket`/`urllib`/`http.client`/`requests`, the
frozen capsule, or any platform/operations module.

### P2.5a2 files

- `icp/scripts/platforms/flutter_expected_slots_adapter_v1.py` — adapter
  with `main()` only, plus the module-local typed
  `ExpectedSlotsAdapterError`. No public helper functions.
- `icp/scripts/platforms/flutter_operations_v1.py` — adds the fixed
  `PLATFORM_SCRIPTS_DIR` constant, the closed `_ORIGIN_CAPSULE` /
  `_ORIGIN_PLATFORM` origin constants, the `script_origin` field on every
  visible-codegen step spec, the `adapt_expected_slots` step spec, the
  `_lookup_platform_script_sha` and `_resolve_script_path_and_sha`
  helpers, and origin-aware SHA/path binding in `_build_visible_steps` and
  `verify_plan`. No new operation ID, no request-shape change, no registry
  change.
- `icp/scripts/selftest_p25a2_flutter_expected_slots_adapter.py` — focused
  RED -> GREEN selftest (50 cases) covering the adapter surface, exact
  CLI boundary, real frozen-capsule byte parity, mutation/parity divergence
  on both sidecars, missing/malformed/oversize/noncanonical/duplicate-key/
  wrong-shape rejection, path validation (symlink leaf and ancestor,
  directory, FIFO, outside-root, non-`.dart`), real source-identity TOCTOU
  (same-bytes-different-inode and different-bytes hooks), mode preservation,
  no `__pycache__` under `shared_core/`, and the operations-module
  four-step platform-origin integration.
- `icp/SKILL.md` — this section.

## P2.5b — first projection consumer cutover (fixture operation)

P2.5b makes the platform-neutral expected/slots projection a persistent,
canonical artifact and makes `flutter.fixture_codegen.v1` the first
operation gated by that projection, while preserving the frozen iFF
consumer and exact Flutter parity.

### What is implemented

#### A. SharedCore canonical projection bytes

`icp/scripts/shared_core/expected_slots_projection_v1.py` gains one
public pure API: `build_projection_bytes(projection) -> bytes`. It
validates the projection through the existing contract and emits a
detached strict-JSON document in the contract's fixed top-level key order
(`kind`, `schemaVersion`, `artboardWidth`, `artboardHeight`,
`designPixelScale`, `nodes`) and fixed per-node key order, preserving
the contractual node-list insertion order and nested JSON insertion
order. Exact encoding is
`json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")`
with no sorted keys and no trailing newline. It is deterministic for
custom `Mapping` inputs after validation; caller-side `Mapping`
subclasses are never serialized directly. Standard-library-only; no
CLI/filesystem/network/process/path/root surface.

#### B. Existing Flutter adapter publishes the projection

`icp/scripts/platforms/flutter_expected_slots_adapter_v1.py` (the same
fixed project-local platform primitive introduced in P2.5a2) gains the
optional CLI pair `--run-root <abs dir>` and `--feature-id <id>` which
must appear together or both be absent. The two-argument compatibility
mode still performs the P2.5a2 byte-identical rewrite and returns the
existing summary unchanged. The trusted `flutter.visible_codegen.v1`
operation always passes both new args.

In projection mode the adapter additionally:

* validates `run_root` as an absolute normalized, existing, current-
  owner, non-symlink directory that is either disjoint from
  `project_root` or exactly `project_root/.iff/icp_runs/<batch_id>`
  with a safe batch id, under the existing root-boundary policy;
* validates `feature_id` against `^[a-z][a-z0-9_]*$`;
* derives the canonical projection bytes from the same sidecar-
  reconstructed projection via SharedCore `build_projection_bytes`;
* publishes those bytes exactly once to the fixed derived artifact path
  `<run_root>/expected_slots_projections/<feature_id>.json` (maximum
  16 MiB) using an atomic create-if-absent strategy with a current-
  owner, mode-0600, fsynced temp in the target directory and a
  directory fsync. Pre-existing output (file, directory, or symlink)
  fails closed and is never overwritten.

Projection-output preconditions and canonical bytes are fully validated
BEFORE the first legacy-sidecar replace. If final publication fails
after the legacy sidecars were replaced, those sidecars remain
semantically unchanged because their old/new bytes are identical; the
adapter reports failure and never fabricates success. In projection mode
the adapter's stdout summary carries the existing stable fields plus only
a stable run-relative projection artifact path
(`expected_slots_projections/<feature_id>.json`); the absolute supplied
`run_root` and raw projection content are never emitted.

#### C. First consumer guard

`icp/scripts/platforms/flutter_fixture_projection_guard_v1.py` is a new
Flutter compatibility-boundary primitive (not SharedCore). It is
standard-library-only, sets `sys.dont_write_bytecode = True` before
loading SharedCore, loads SharedCore only from the fixed installed
sibling path derived from `__file__` (no import/root override), and
exposes only `main()` and one module-local typed exception
(`FixtureProjectionGuardError`) as public callables/classes.

Exact CLI: `--run-root <abs dir>` (once), `--projection STATE=<abs json>`
(repeated 1..32 times), `--slots STATE=<abs json>` (repeated 1..32
times). It uses exact `parse_args`; unknown/extra args reject before
file reads. State ids must be unique, match `^[a-z][a-z0-9_]*$`, and the
projection/slots state sets must be exactly equal. Every input must be
an existing current-owner non-symlink regular file strictly under
`run_root` with no symlinked ancestor; each file is bounded to 16 MiB.
Strict-decode UTF-8 JSON with duplicate-key rejection. For each
projection: require `build_projection_bytes(doc) == raw_projection_bytes`
(canonical projection bytes), then require
`build_legacy_bytes(doc)[1] == raw_slots_bytes` byte-for-byte.

The guard is completely READ-ONLY: no mkdir/temp/output/write/rename/
delete/unlink, no subprocess/socket/urllib/http/client/requests/shell/
dynamic import override. On success it emits only a stable sanitized
JSON summary (`kind`, `schema_version`, `states_verified`); no paths or
content. On failure it returns nonzero and emits only the exception type
plus fixed role/state-safe text; no traceback, absolute path, raw
content, arbitrary exception text, or environment.

#### D. Operation plan changes

`flutter.visible_codegen.v1` keeps exactly four ordered steps
(`generate_canvas`, `adapt_expected_slots`,
`make_implementation_map`, `make_status_bar_policy`). Only
`adapt_expected_slots` argv changes: after the existing `--project-root`
and `--canvas` arguments, the fixed argv now includes `--run-root
<validated abs run_root>` and `--feature-id <validated feature_id>` in
that exact order. The validated `run_root` is carried internally; public
visible request keys remain unchanged. No new visible step, operation
ID, registry entry, or caller-controlled output path.

`flutter.fixture_codegen.v1` request schema is extended with the
required key `projections` (same type/count/path rules and exact same
state-id set as `slots`; values are relative existing `.json` paths
under `run_root`). The `_FIXTURE_STEPS_SPEC` becomes exactly two ordered
steps:

1. `verify_fixture_projections` → `flutter_fixture_projection_guard_v1.py`,
   platform origin.
2. `make_visual_fixture` → frozen capsule consumer, unchanged.

Guard argv is fixed and deterministic: interpreter + fixed platform
primitive + `--run-root <validated run_root>` + all
`--projection STATE=<abs>` entries in sorted state order + all
`--slots STATE=<abs>` entries in sorted state order. Guard cwd remains
the validated `project_root`; the consumer cwd remains unchanged.

`verify_plan` re-attests the exact guard ordering, the new
`projection_pair` argument grammar (parallel to `slots_pair`), the
platform path and the recomputed file SHA, and rejects reorder,
duplicates, path/SHA tamper, wrong origin, and capsule-basename
collisions. A dedicated cwd_binding rule
(`_CWD_PROJECT_ROOT_WITH_RUN_ROOT`) requires the guard cwd to equal the
immediately-following consumer step's cwd (which is itself anchored by
its project-rooted `--out` argv path), closing the guard cwd provenance
gap without adding `--project-root` to the guard CLI or changing the
accepted guard argv contract; the run-root nesting check is retained as
defense in depth. Building the fixture before the projection artifacts
exist fails at request validation (producer-before-consumer gate).

No new operation ID or registry entry. No arbitrary
script/root/command/output/projection-path override beyond the already-
digest-bound relative run-root artifact map.

### Trust / data flow

The producer is the `adapt_expected_slots` post-step, which runs after
the frozen `generate_canvas` and proves byte parity before publishing
the canonical projection artifact. The consumer is the new
`verify_fixture_projections` guard step, which reads the projection
artifact and the slots file for each state, re-derives both via
SharedCore, and requires byte equality. Only after the guard succeeds
may the existing frozen `make_visual_fixture.py` capsule consumer run.
The frozen `make_visual_fixture.py` remains unchanged.

### Security boundaries

* Maximum artifact size: 16 MiB.
* `feature_id` matches `^[a-z][a-z0-9_]*$`.
* `run_root` is absolute normalized, existing, current-owner,
  non-symlink, and either disjoint from `project_root` or exactly
  `project_root/.iff/icp_runs/<batch_id>` with a safe batch id, under
  the existing root-boundary policy.
* Publish once only: existing output (file, dir, or symlink) fails
  closed and is never overwritten.
* Atomic no-overwrite publish from a current-owner, mode-0600, fsynced
  temp in the target directory; same-filesystem hard-link create-if-
  absent publication; directory fsync. Temp files cleaned on every
  failure.
* Projection-output preconditions and canonical bytes validated before
  the first legacy-sidecar replace.
* Failures surface only the type name plus a short, fixed message — no
  traceback, raw file content, or supplied path is leaked.
* Guard is standard-library-only and completely read-only.

### P2.5b files

- `icp/scripts/shared_core/expected_slots_projection_v1.py` — adds the
  pure public `build_projection_bytes(projection) -> bytes` API. No
  other behavior change.
- `icp/scripts/platforms/flutter_expected_slots_adapter_v1.py` — adds
  optional `--run-root` / `--feature-id` pair, run_root/feature_id
  validation, projection artifact publication, and the projected
  summary field. Compatibility mode unchanged.
- `icp/scripts/platforms/flutter_fixture_projection_guard_v1.py` (new) —
  read-only Flutter compatibility-boundary primitive exposing only
  `main()` and `FixtureProjectionGuardError`.
- `icp/scripts/platforms/flutter_operations_v1.py` — extends
  `adapt_expected_slots` argv with `--run-root` / `--feature-id`; makes
  `_FIXTURE_STEPS_SPEC` two ordered steps; adds the `projections`
  request key, the `projection_pair` argv kind, the
  `_CWD_PROJECT_ROOT_WITH_RUN_ROOT` cwd_binding rule, and the guard
  step builder. No new operation ID or registry entry.
- `icp/scripts/selftest_p25b_fixture_projection_consumer.py` (new) —
  focused RED -> GREEN selftest (94 cases) covering SharedCore
  canonical projection serialization, real frozen-corpus adapter
  projection publication, adapter compatibility mode, fixed artifact
  path / CLI pair / feature id / run-root validation / no-overwrite /
  temp cleanup / mode 0600 / 16 MiB bound / sanitized failures, guard
  happy path / canonical-projection / projection->slots / read-only,
  guard rejections (states, malformed/invalid UTF-8/duplicate-key/
  noncanonical/oversized/mutated/symlink/out-of-root/non-file/unknown
  args / no leak), visible-operation argv, fixture-operation two-step
  plan / deterministic argv / SHA binding / tamper rejection / cwd-tamper
  rejection (guard-only and coordinated), binding/authorization/executor
  end-to-end propagation, and protected-hash/IFF/registry/no-pycache
  invariants.
- `icp/SKILL.md` — this section.

P2.5b does not activate any platform, does not change any registry
entry, does not change any vendor/baseline/IFF file, does not change any
protected binding/authorization/executor/preflight/standard production
module, and does not edit the frozen capsule or the frozen
`make_visual_fixture.py` consumer. At the P2.5b checkpoint P2.5d and P3
remained forbidden; the later P2.5d section supersedes only the P2.5d
restriction for the trusted trace-harness binding scope, and P3 remains
pending. P2.5c is allowed for the contract-only scope documented in its
own section below; it does not cut over the trace consumer.

## P2.5c — merged-expectation provenance contract (non-executable)

P2.5c adds exactly one new platform-neutral contract to SharedCore: the
**merged-expectation provenance v1** document. P2.5b's persistent
expected/slots projection reconstructs one raw canvas sidecar; the real
iFF trace flow first creates `merged_expected.json` from the raw canvas
expectation, `shared_components.local.json`, and `scene.json`, and
`gen_layout_trace_test.py` can silently adopt an adjacent merged file.
Directly gating trace on the raw projection would therefore prove file A
while the frozen consumer uses effective document B. P2.5c records the
digest/provenance chain so a future consumer gate can prove file B.

### What is implemented

`icp/scripts/shared_core/merged_expectation_provenance_v1.py` is a pure
standard-library-only, non-executable module. It exposes no CLI, performs
no filesystem/network/process I/O, accepts no path/root override, sets no
bytecode flag, and never imports a platform module, the iFF v1 capsule,
or the P2.5a1 projection module. Its public API is exactly:

- `build_provenance(*, producerKind, producerSha256,
  pageCanvasProjectionSha256, sharedComponentsLocalSha256, sceneSha256,
  mergedExpectedSha256, pageCanvasNodeIds, sharedComponentNodeIds,
  mergedNodeIds) -> dict[str, object]` — keyword-only construction then
  validation;
- `validate_provenance(value: Mapping[str, object]) -> dict[str, object]`
  — returns a detached plain-built-in clone in canonical key order;
- `build_provenance_bytes(value: Mapping[str, object]) -> bytes` —
  validates first, then serializes only the detached validated document;
- `MergedExpectationProvenanceError(ValueError)` — the only exception
  raised on validation failure.

Canonical encoding is exactly
`json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")`
with fixed insertion order, no key sorting, and no trailing newline.

The contract records the digest chain (raw projection, local, scene,
merged) plus the page/shared/merged node-id order. It does NOT claim the
raw projection v1 can represent merged shared-component nodes, and does
NOT reproduce iFF merge behavior in SharedCore. P2.5d binds the
producer/adapter/consumer; P2.5c is the schema and its proof only.

### When to read the reference

Read `icp/references/p25c-merged-expectation-provenance.md` for the
detailed schema, edge cases, trust/data flow, producer/consumer
responsibilities deferred to P2.5d (including the required
`--expected`-binding and raw-sidecar + adjacent-merged auto-adoption
rejection invariants the future gate must enforce), explicit non-goals,
and the protected-files list. Do not duplicate the detailed schema here.

### P2.5c files

- `icp/scripts/shared_core/merged_expectation_provenance_v1.py` — pure
  standard-library-only provenance validator + canonical byte serializer.
- `icp/scripts/selftest_p25c_merged_expectation_provenance.py` — focused
  RED -> GREEN selftest (104 cases).
- `icp/references/p25c-merged-expectation-provenance.md` — detailed
  operational contract.
- `icp/SKILL.md` — this section.

P2.5c does not activate any platform, does not change any registry entry,
operation ID, request schema, or step spec, does not change any
binding/authorization/executor/preflight/standard/adapter/guard production
module, does not change P2.5a1/a2/b production modules, does not change
either baseline manifest or any `iff/` file, does not edit or copy the
frozen `merge_shared_expected.py` producer, and does not cut over the
trace consumer (no `flutter.trace_harness.v1` change). **P3 remains
pending; P2.5d is allowed for the binding scope documented in its own
section below.**

## P2.5d — merged expectation provenance binding (trusted three-step trace chain)

P2.5d replaces the one-step `flutter.trace_harness.v1` plan with one
trusted three-step chain:

1. frozen capsule `merge_shared_expected.py` consumes the real legacy
   page `.expected.json` and produces `merged_expected.json`;
2. one new fixed platform-origin provenance gate proves the P2.5a
   projection reconstructs that legacy input, attests every actual
   chain file, atomically publishes and re-verifies P2.5c provenance;
3. frozen capsule `gen_layout_trace_test.py --expected` receives
   exactly the attested `merged_expected.json`.

The trusted plan makes the frozen consumer's raw-sidecar +
adjacent-merged auto-adoption branch structurally unreachable.

### What is implemented

`flutter.trace_harness.v1` now has a 17-key request schema carrying
both `page_canvas_expected` (the legacy file the merge consumes) and
`page_canvas_projection` (the canonical projection the gate attests)
as distinct identities, plus `shared_components_local` (a safe leaf
that may be absent), `scene`, `merged_expected_out`, and
`provenance_out`. The plan's three steps are wired with full
cross-step identity coupling enforced by `verify_plan`:
`step[0] --out == step[1] --merged-expected == step[2] --expected`
(also `--expected`/`--page-canvas-expected`, `--local`/
`--shared-components-local`, `--scene` across steps 0 and 1).

The new platform gate
`icp/scripts/platforms/flutter_merged_expectation_provenance_gate_v1.py`
is the only new production file. It accepts exactly seven flags (no
producer-path/SHA/manifest/capsule/command/executable/env/shell/URL
override), performs the two-stage fixed capsule verifier load +
manifest-bound producer SHA + capsule file recompute + equality
check, validates every absolute path (canonical, strictly under
`run_root`, current-owner, no symlink at any component, bounded
regular input; permits only the absent `shared_components_local`
leaf), strict-decodes JSON with duplicate-key rejection, fixed-loads
both SharedCore modules from sibling paths, requires projection
canonicality and legacy byte parity, requires frozen-merge canonical
output bytes, requires page top-level fields and every page node
value to be unchanged in the merged document and page node IDs to
form the exact prefix of merged node IDs, handles the missing-local
pass-through null-digest case, computes SHA-256 over actual raw
bytes, builds + validates P2.5c provenance with the manifest-bound
producer SHA, atomically publishes via a current-owner mode-0600
temp with fsync+atomic replace, re-opens and re-validates the
published artifact, and emits one sanitized JSON summary. No
subprocess, no path/content/env/traceback leak. Standard library
only.

### When to read the reference

Read `icp/references/p25d-trace-harness-provenance-binding.md` for
the exact 17-key schema, path rules, topology invariants, cross-step
identity contracts, the 16-point gate specification, the descriptor
consistency rule, the controlled-executor trust boundary, and the
full validation list. Do not duplicate the detailed contract here.

### P2.5d files

- `icp/scripts/platforms/flutter_merged_expectation_provenance_gate_v1.py`
  — new fixed platform-origin provenance gate.
- `icp/scripts/selftest_p25d_trace_harness_provenance_binding.py` —
  focused RED -> GREEN selftest (80 cases).
- `icp/references/p25d-trace-harness-provenance-binding.md` —
  detailed operational contract.
- `icp/scripts/platforms/flutter_operations_v1.py` — 17-key trace
  schema, three-step plan, trace-specific verify_plan cross-step
  identity coupling, `trace_harness_chain` cwd_binding (trace only).
- `icp/scripts/platforms/flutter_standard_v1.py` — trace_harness
  legacy primitive tuple now mirrors the trusted plan's capsule
  legacy primitives in execution order.
- `icp/SKILL.md` — this section.

P2.5d does not activate any platform, does not change any registry
entry, baseline manifest, vendor capsule file, `iff/**` file,
SharedCore production module, expected-slots adapter, fixture guard,
binding, authorization, executor, preflight, or
`shared_components.local.json` schema, does not edit or copy the
frozen `merge_shared_expected.py` or `gen_layout_trace_test.py`
primitives, and does not add a second provenance script/step. **P3
remains pending.**

## P3a — PlatformPackage contract（inactive）

P3a 已冻结平台中立的 descriptor 验证器与 Flutter 六组件 conformance wrapper；
所有平台仍为 `inactive`、`executable=false`，生产入口尚未接线。
完整方案与阶段边界见 `icp/references/p3-platform-package-architecture.md`；
P3b1 readiness/resolver、Vue 与 activation 均尚未实现。

## P3b1a — Entry readiness + active-first gate（inactive, pure in-memory contract）

P3b1a 是 P3b1 的前半切片：只冻结纯内存的入口 readiness 聚合与 active-first
gate 契约，不实现 P3b1b 包解析/选择，不接入生产入口，不执行 P3d 任何文件系统
I/O。新增文件为 `icp/scripts/entry_readiness_v1.py`、
`icp/scripts/selftest_p3b1_entry_readiness.py` 与
`icp/references/entry-readiness-v1.md`。模块只暴露
`EntryReadinessError`、`document_digest`、`verify_observation`、
`verify_readiness_report`、`verify_entry_gate_decision`、`aggregate_readiness`
与 `decide_entry`；平台中立、零 I/O、无私有以外的常量，仅按私有别名惰性加载
P3a descriptor 校验器与 P3a2 `decide_resume` 状态机。P3b1b 包 resolver/selection、
生产 EntryReadinessGate 接线与 probe 执行，以及 P3d 文件系统发布/lock/CAS/
writeback/scratch 清理仍均未实现。

聚焦 selftest：

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3b1_entry_readiness.py
```

## P3b1b — fixed package index/resolver/selection + inactive entry seam

P3b1b 在 P3b1a 之上落地固定（frozen）的包索引、resolver 与 selection，并在
生产入口之前加入 inactive package-aware entry seam：先验证 readiness ->
active-first entry decision -> package-aware support gate，再允许任何
TaskSource / manifest freeze / claim 访问。当前 v1 每个包均为
`activation_state=inactive`、`executable=false`，因此 seam 对任何有效 v1
输入始终在 `platform_package_inactive`（或更早的确定性 stop）停下，永不进入
`route=prepare`；生产 CLI（`prepare_selection.py --config ... --limit ...` 与
`preflight_selection.py --config ...`）未改，仍走既有 `support_gate` /
`prepare_selection`。详细方案与阶段边界见
`icp/references/p3-platform-package-architecture.md`；P3b2 activation 与
P3d（filesystem publish/lock/CAS/claim/writeback/scratch 清理/平台绑定/
authorization/executor wiring）仍均未实现。

聚焦 selftest：

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3b1_platform_package_selection.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3b1_entry_seam.py
```

## P3b2 — Vue descriptor/preflight/plans（inactive）

P3b2 增加固定 `vue-vite` PlatformPackage：Vue adapter descriptor、只读
Vite/Node/npm project preflight、八个无命令/无 argv/不执行/不写文件的确定性
operation plan builder/verifier，以及六角色 package conformance。固定 package
index 现在按 `(flutter, flutter-standard)`、`(vue, vue-vite)` 排序并绑定 live
module SHA 与 descriptor digest。Vue 仍为 `activation_state=inactive`、
`executable=false`；binding/authorization/executor 角色明确指向 unavailable
placeholder，生产 registry 与 CLI 均未激活，不开放 claim 或执行。

聚焦 selftest：

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3b2_vue_package.py
```

## P3c — Vue execution chain（inactive direct-test surface）

P3c 用 Vue 自有组件替换 P3b2 的 unavailable roles：binding 每次从当前
selection manifest、固定 package index、live package/module SHA、Node/npm
preflight 与重新构建的 plan 生成；authorization 必须由 supervisor 提供
manifest/path、manifest SHA、binding digest、authorization digest 与 32-hex
nonce；executor 以 `O_EXCL` 一次性 claim/result receipts 执行固定 action，
当前已实现 `render_vue_feature` 的无覆盖 SFC/CSS 原子发布和 replay 拒绝。
registry 仍为 inactive，生产入口仍不开放执行。

`icp/fixtures/vue_vite_v1` 是真实 Vite/Vue fixture，固定包含 Vitest unit 与
Playwright Chrome e2e；e2e 的 `actual.png` 由真实浏览器截图产生。依赖只在
临时 smoke 目录安装，不把 `node_modules`/lockfile 纳入 skill。

聚焦 selftest：

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3c_vue_execution_chain.py
```

## Validation

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p3a_platform_package_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25c_merged_expectation_provenance.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25b_fixture_projection_consumer.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25a2_flutter_expected_slots_adapter.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25a1_expected_slots_projection.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e2b_flutter_executor.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e2a_flutter_authorization.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e1_selection_manifest.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2e1_flutter_binding.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2c_flutter_operations.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2b_flutter_operations.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2a_flutter_operations.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d1_flutter_preflight.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2c_flutter_descriptor.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2b_lanhu.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2a_vendor.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p1b.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p1a.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_freeze_iff_baseline.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/verify_vendor_iff_v1.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/freeze_iff_baseline.py --iff-root iff --check icp/references/baselines/iff-v1.json
PYTHONDONTWRITEBYTECODE=1 python3 iff/scripts/validate_skill_structure.py iff
PYTHONDONTWRITEBYTECODE=1 python3 iff/scripts/selftest_validate_skill_structure.py
git diff --exit-code -- iff
find icp/vendor/iff_v1 -name __pycache__ -print
find icp/scripts/shared_core -name __pycache__ -print
find icp/scripts/platforms -name __pycache__ -print
```

The `iff` skill is read-only reference; ICP runtime code never imports, copies,
executes, or symlinks it. The byte-frozen copy under
`icp/scripts/task_sources/csv_row_status_v1.py` is the only provenance link
for the P1 CSV primitive, pinned by SHA-256; the P2a capsule under
`icp/vendor/iff_v1/scripts/**` is the only provenance link for the iFF v1
compatibility scripts, bound to the P0 baseline by the verified manifest.

## Boundaries (do not cross in P1b/P2a/P2b/P2c/P2d1/P2d2a/P2d2b/P2d2c/P2e1/P2e2a/P2e2b/P2.5a1/P2.5a2/P2.5b/P2.5c)

- No platform is activated; all seven return `unsupported_platform` at the gate.
  P2b adds the `lanhu-figma` DesignSource adapter but does not activate any
  platform, Flutter/Vue operation, capture v2, parity normalization, or
  end-to-end claiming. P2d1 adds one read-only Flutter `project_preflight`
  operation and P2d2a/P2d2b/P2d2c add the static trusted-operation plan
  registry (visible/fixture/trace/packaging/test_runner/runtime_capture/
  project_gates/fan_in argv builders); **no plan is executed yet** and none
  activates the adapter or executes the generated plans.
- The production CLI exposes no registry, batch-id, root, script, command, or
  env override. The P2b DesignSource CLI likewise exposes no override for
  skill root, capsule root, script path, command, interpreter, runner,
  environment, or registry. The P2d2a/P2d2b/P2d2c plan registry exposes no CLI
  at all and no root/manifest/capsule/registry/executable override.
- No `import`/`exec`/`subprocess` of registry values; no platform tools, no
  code generation, no runtime capture. The P1b/P2a runtime makes no network
  calls of its own; the P2b DesignSource wrapper drives the fixed capsule
  primitives `fetch.py` / `download_cover.py` (which make Lanhu network
  calls) via `sys.executable`, with no shell and no arbitrary argv
  pass-through, and it never inspects, logs, copies, or serializes
  credential values. The P2d2a/P2d2b/P2d2c registry never imports `subprocess`
  and never executes a subprocess; it only builds and verifies deterministic
  argv plans against the immutable capsule manifest. The P2d2b packaging
  and test_runner variants never accept or emit `--flutter` or
  `--font-source`; the later P2e executor must bind the primitive's
  inherited Flutter resolution to a successful current `project_preflight`
  result, and the immutable primitive owns its fixed/default font mapping.
  The P2d2c runtime_capture/project_gates/fan_in variants never accept or
  emit device IDs, labels, device pools, routes, `--safe-area-source`,
  `--dart-define`, APK paths, or the supervisor `run` command. The P2e2a
  authorization candidate module exposes no CLI, never imports
  `subprocess`/`socket`/`urllib`/`http.client`, never uses `shell=True`,
  never writes a file, never creates a symlink, never directly spawns
  a process, and performs no import-time I/O; it never consumes the
  nonce, never activates the adapter, and never executes an operation-
  plan command. (Its prepare/verify calls do re-enter the shared binding
  verifier, which re-runs the fixed read-only
  `[flutter, "--version", "--machine"]` preflight subprocess with
  `shell=False`; that is the one transitive child process, owned by the
  preflight module.)
- The P2e2b executor activates only the operation-plan steps already
  bound by a verified P2e2a authorization candidate. It exposes no CLI,
  never imports `socket`/`urllib`/`http.client`/`requests`, never uses
  `shell=True`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`,
  `os.fork`, or any `subprocess.call`/`check_call`/`check_output`/
  `getoutput`/`getstatusoutput` arbitrary-command API, never deletes/
  truncates/renames/overwrites a claim or result file, and never
  persists raw stdout/stderr. The caller cannot inject argv, cwd,
  timeout, environment, shell, or receipt root. Pre-claim and per-spawn
  authorization verification transitively re-run the fixed read-only
  `[flutter, "--version", "--machine"]` preflight subprocess with
  `shell=False` (owned by the preflight module); the executor's own
  spawn surface is the operation-plan steps. The executor-owned
  environment strips Python/dynamic-loader/shell startup injection
  variables and is **executor policy derived from trusted supervisor
  input, not bound by P2e2a**. The fd-relative `O_EXCL` claim closes
  the nonce filename symlink/replay race; only the successful claimant
  owns terminal-result creation; a claim-only state is durable
  indeterminate/consumed and replayers never write a terminal result.
  A normal path-based executable/script spawn still retains a small
  check-to-exec TOCTOU residual.
- The selection manifest is frozen exactly once per batch id; existing run
  roots or manifests are never overwritten or reused. The P2b canonical
  design bundle is published exactly once per `bundle_root`; a pre-existing
  bundle is never overwritten, even if identical.
- P2.5a1 adds only a non-executable platform-neutral SharedCore contract
  (expected/slots projection v1) and its differential parity proof. It does
  not activate any platform, does not switch any consumer to the projection,
  does not add a projection producer, does not change any execution plan,
  operation registry, authorization, executor, platform activation gate, or
  platform adapter. The SharedCore production module is standard-library-only
  with no CLI, no filesystem/network/process surface, no path/root override,
  and no capsule/platform import; the differential parity proof instruments
  the frozen capsule in the TEST only, without modifying the capsule or
  weakening its hashing. At the P2.5a1 checkpoint P2.5d and P3 remained
  forbidden; the later P2.5d section supersedes only the P2.5d
  restriction for the trusted trace-harness binding scope, and P3
  remains pending. P2.5c is allowed for the contract-only scope
  documented in its own section above.
- P2.5a2 adds exactly one explicit post-step (`adapt_expected_slots`) to
  `flutter.visible_codegen.v1` between `generate_canvas` and
  `make_implementation_map`. The four-step chain is fully bound, authorized,
  reverified, executed, and receipt-recorded through the existing
  binding -> authorization -> executor SHA/path/nonce/receipt chain; no
  adapter manifest exists and the trust root remains the fixed step
  specification inside `flutter_operations_v1.py` (already bound as
  `operations_module_sha256`). No operation ID, request key, request-digest
  input shape, registry entry, binding/authorization/executor production
  module, Flutter standard/preflight module, SharedCore production module,
  P2.5a1 producer, vendor capsule, vendor manifest/baseline, or `iff/` file
  changes. The platform adapter is a fixed project-local primitive resolved
  only through the fixed `PLATFORM_SCRIPTS_DIR`; its basename never collides
  with any capsule-manifest primitive, never imports the frozen capsule or
  any platform/operations module, never accepts a caller-provided script
  root or projection path override, and sets `sys.dont_write_bytecode` so
  loading SharedCore does not litter `__pycache__`. CLI parsing is exact
  (any unknown flag fails before any sidecar is touched). Inputs are
  bounded (16 MiB per sidecar), strict UTF-8/JSON with duplicate-key
  rejection, and exact-derived sidecar paths; the adapter only reads the
  sidecars emitted by the immediately preceding `generate_canvas` step,
  reconstructs the projection losslessly, requires byte-for-byte parity
  with both original raw bytes, and atomically persists the byte-identical
  SharedCore output (prepare+fsync both temps, revalidate both lstat
  identities AND raw bytes, then replace, preserving each original file's
  mode and rejecting symlinks/non-current-owner files). Missing, malformed,
  noncanonical, duplicate-key, oversized, symlinked, out-of-root,
  changed-during-read, or parity-divergent inputs fail closed without
  fabricating output and without leaking file contents, supplied paths, or
  traceback details. At the P2.5a2 checkpoint P2.5d and P3 remained
  forbidden; the later P2.5d section supersedes only the P2.5d
  restriction for the trusted trace-harness binding scope, and P3
  remains pending. P2.5c is allowed for the contract-only scope
  documented in its own section above.
