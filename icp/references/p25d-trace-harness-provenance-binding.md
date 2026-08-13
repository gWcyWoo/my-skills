# P2.5d — Trace-Harness Provenance Binding (trusted three-step chain)

This reference documents the ICP P2.5d trace-harness provenance binding.
P2.5d replaces the one-step `flutter.trace_harness.v1` plan with one
trusted three-step chain whose every cross-step identity is enforced by
`verify_plan`. The frozen consumer's raw-sidecar + adjacent-merged
auto-adoption branch is structurally unreachable.

## Table of Contents

- [Outcome](#outcome)
- [Trusted three-step chain](#trusted-three-step-chain)
- [Exact 17-key trace request schema](#exact-17-key-trace-request-schema)
- [Path rules and topology](#path-rules-and-topology)
- [Cross-step identity invariants](#cross-step-identity-invariants)
- [New platform gate primitive](#new-platform-gate-primitive)
- [Descriptor consistency](#descriptor-consistency)
- [Boundaries and non-goals](#boundaries-and-non-goals)
- [Files added or modified](#files-added-or-modified)
- [Validation](#validation)
- [Controlled-executor trust boundary](#controlled-executor-trust-boundary)

## Outcome

The frozen capsule primitive `merge_shared_expected.py` consumes the
real legacy page `.expected.json` and produces `merged_expected.json`.
The new fixed platform-origin provenance gate proves the P2.5a
projection reconstructs that legacy input, attests every actual chain
file, atomically publishes P2.5c provenance, then re-opens and
re-verifies the published bytes. The frozen capsule consumer
`gen_layout_trace_test.py --expected` receives exactly the attested
`merged_expected.json`. Because `--expected` resolves to the same
path as the adjacent merged file, the consumer's auto-adoption branch
is unreachable: the path-equality early return in
`gen_layout_trace_test._load_expected_contract` fires before any
adoption message is printed.

## Trusted three-step chain

```
step 0  merge_shared_expected.py            (capsule origin)
        --expected <page_canvas_expected_abs>
        --local    <shared_components_local_abs>      (may be absent)
        --scene    <scene_abs>
        --out      <merged_expected_out_abs>

step 1  flutter_merged_expectation_provenance_gate_v1.py   (platform origin)
        --run-root                <run_root_abs>
        --page-canvas-expected    <page_canvas_expected_abs>
        --page-canvas-projection  <page_canvas_projection_abs>
        --shared-components-local <shared_components_local_abs>
        --scene                   <scene_abs>
        --merged-expected         <merged_expected_out_abs>
        --provenance-out          <provenance_out_abs>

step 2  gen_layout_trace_test.py            (capsule origin)
        --expected <merged_expected_out_abs>
        ... (existing argv retained verbatim) ...
```

The step order is exact and immutable. `verify_plan` rejects
reordering, origin/path/hash drift, any argv divergence, and any break
in the cross-step identity relationships. The platform gate is NOT a
legacy primitive and is not added to the descriptor's trace_harness
tuple.

## Exact 17-key trace request schema

```
project_root
run_root
package_name
page_canvas_expected
page_canvas_projection
shared_components_local
scene
merged_expected_out
provenance_out
page_import_path
page_type
trace_out
responsive_out
responsive_contract_out
viewports_file
safe_area_policy
out
```

The old ambiguous `expected` key is removed. Old requests fail closed
with exact-key mismatch.

## Path rules and topology

Roots are absolute existing directories. Artifact path values are
strict POSIX-relative paths resolved by the existing validators under
`run_root` (or under `project_root` for Dart `out`). Plan argv
contains validated absolute paths.

- `page_canvas_expected`, `page_canvas_projection`, `scene`,
  `viewports_file`: existing current-owner non-symlink regular JSON
  files under `run_root`.
- `page_canvas_expected` must end `.expected.json`.
- `shared_components_local`: strict relative `.json` path under
  `run_root`; the safe leaf may be absent. An existing leaf must be a
  non-symlink regular file.
- `merged_expected_out`, `provenance_out`, `trace_out`,
  `responsive_out`, `responsive_contract_out`: safe JSON outputs
  under `run_root`.
- `merged_expected_out` basename must be exactly `merged_expected.json`.
- `provenance_out` must equal
  `Path(merged_expected_out).parent / "merged_expected.provenance.json"`.
- `merged_expected_out` must equal
  `Path(trace_out).parent / "merged_expected.json"`.
- Every input and output identity must be distinct; the only
  intentional cross-step reuse is `merged_expected_out`.

The validators reject symlink aliases, `..`, backslashes, URI-looking
values, NULs, non-normal forms, and path escape using the existing
helpers.

## Cross-step identity invariants

For a plan supplied directly to `verify_plan` (not only one built by
`build()`), the trace-specific verifier reconstructs the canonical
absolute path strings from the validated flat argv pairs and requires:

- `step[0].argv --expected` == `step[1].argv --page-canvas-expected`
- `step[0].argv --local` == `step[1].argv --shared-components-local`
- `step[0].argv --scene` == `step[1].argv --scene`
- `step[0].argv --out` == `step[1].argv --merged-expected`
                       == `step[2].argv --expected`

plus the fixed output topology (basenames, shared parents). The
verifier rejects any tampering that breaks these equalities.

## New platform gate primitive

`icp/scripts/platforms/flutter_merged_expectation_provenance_gate_v1.py`
accepts exactly the seven flags shown above, once each. There is no
producer-path, SHA, manifest, capsule, command, executable, import,
env, shell, URL, or root override. It:

1. derives `ICP_ROOT`, SharedCore paths, capsule scripts path, manifest
   path, and `verify_vendor_iff_v1.py` only from its fixed installed
   `__file__`;
2. performs the established two-stage fixed verifier load +
   `verify_skill(ICP_ROOT)` pattern before trusting the capsule;
3. strict-loads the fixed vendor manifest with duplicate-key
   rejection, finds exactly one `merge_shared_expected.py` record,
   recomputes the installed capsule file SHA-256, and requires equality
   with the manifest digest;
4. validates `run_root` and every supplied absolute path: canonical,
   strictly below `run_root`, current-owner, no symlink at any
   component, bounded regular input; permits only the absent
   `shared_components_local` leaf; validates output target safely;
5. strict-decodes JSON with duplicate-key rejection and bounded UTF-8;
6. fixed-loads both existing SharedCore modules from sibling paths
   with no `sys.path` mutation and no bytecode emission;
7. requires raw projection bytes equal
   `build_projection_bytes(projection_doc)`;
8. requires `build_legacy_bytes(projection_doc)[0]` byte-for-byte
   equals raw `page_canvas_expected` bytes;
9. requires frozen-merge canonical output bytes equal
   `json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n"`;
10. requires merged top-level fields other than `nodes` equal the
    page legacy expected document, page node IDs form the exact prefix
    of merged node IDs, and every page node value is unchanged;
    derives shared node IDs as only the suffix;
11. when local is absent, additionally requires the merged document
    equals the page expected document and shared node IDs are empty;
12. computes SHA-256 over the actual raw bytes of projection, present
    local (or null), scene, and merged output;
13. calls existing P2.5c `build_provenance(...)`,
    `validate_provenance(...)`, and `build_provenance_bytes(...)`
    with `producerKind="iff-v1.merge_shared_expected"`, the
    manifest-bound installed producer SHA, and the ordered
    page/shared/merged node IDs derived from the actual documents;
14. atomically publishes canonical provenance bytes to
    `provenance_out` using a current-owner mode-0600 temp in the same
    safe directory, fsync file + directory, and atomic replace; safe
    reruns may replace a safe existing regular output;
15. re-opens the published artifact, requires exact byte equality with
    what was written, strict-decodes, validates again, and requires
    canonical byte equality before success;
16. emits only one deterministic sanitized JSON success summary;
    errors use one typed local exception and sanitized fixed-role/type
    output, no traceback, absolute path, raw bytes/content, arbitrary
    child error, environment, or secret.

No subprocess inside the gate. Standard library only. The gate does
not reimplement iFF merge behavior in SharedCore.

## Descriptor consistency

`flutter_standard_v1.py` declares the `trace_harness` capability's
legacy primitive tuple in execution order:

```python
("merge_shared_expected.py", "gen_layout_trace_test.py")
```

The platform gate is NOT a legacy primitive and must not appear in
that tuple. The activation state, capability state, and every other
operation's mapping remain unchanged. The legacy primitive total
increases by exactly one (22 -> 23).

## Boundaries and non-goals

- P2.5d does not activate any platform; `flutter_standard_v1.py`
  remains `executable=false` and `activation_state=inactive`.
- P2.5d does not change any registry entry, baseline manifest, vendor
  capsule file, `iff/**` file, SharedCore production module, expected-
  slots adapter, fixture guard, binding, authorization, executor,
  preflight, or `shared_components.local.json` schema.
- P2.5d does not add a second provenance script/step.
- P2.5d does not loosen any current test.
- P2.5d does not edit or copy the frozen
  `merge_shared_expected.py` or `gen_layout_trace_test.py` capsule
  primitives; both files remain byte-identical and bound to their
  manifest SHAs.

## Files added or modified

Added:

- `icp/scripts/platforms/flutter_merged_expectation_provenance_gate_v1.py`
- `icp/scripts/selftest_p25d_trace_harness_provenance_binding.py`
- `icp/references/p25d-trace-harness-provenance-binding.md`

Modified only as required:

- `icp/scripts/platforms/flutter_operations_v1.py`
  (17-key schema; three-step plan; trace-specific verify_plan
  cross-step identity coupling; `trace_harness_chain` cwd_binding).
- `icp/scripts/platforms/flutter_standard_v1.py`
  (trace_harness legacy primitive tuple only).
- `icp/scripts/selftest_p2d2a_flutter_operations.py`
  (trace-only assumptions/schema/plan).
- `icp/scripts/selftest_p2c_flutter_descriptor.py`
  (trace primitive/count expectations only).
- `icp/scripts/selftest_p25b_fixture_projection_consumer.py`
  (refreshed protected hashes for the two authorized P2.5d files).
- `icp/scripts/selftest_p25c_merged_expectation_provenance.py`
  (refreshed protected hashes for the two authorized P2.5d files).
- `icp/SKILL.md` (concise P2.5d gate + pointer).

## Validation

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25d_trace_harness_provenance_binding.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25c_merged_expectation_provenance.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2d2a_flutter_operations.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p2c_flutter_descriptor.py
all icp/scripts/selftest*.py individually
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/verify_vendor_iff_v1.py
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/freeze_iff_baseline.py --iff-root iff --check icp/references/baselines/iff-v1.json
PYTHONDONTWRITEBYTECODE=1 python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py icp
git diff --exit-code -- iff
find icp -name __pycache__ -print -o -name '*.pyc' -print
```

## Controlled-executor trust boundary

The gate does not claim a cryptographic proof that a particular prior
process wrote any input file, nor that it can detect a file swap that
occurs before its own first read of that file. That trust boundary is
inherited from the already-controlled executor (P2e2b) which:

- accepts only plans whose every step is bound by a verified P2e2a
  authorization candidate,
- spawns each step with a fixed `sys.executable`, fixed script path,
  fixed argv, fixed cwd, fixed timeout, and an executor-policy
  environment stripped of Python/dynamic-loader/shell startup
  injection variables,
- records per-step SHA-256 receipts,
- re-validates the plan before each spawn.

The gate's own guarantees therefore hold against any swap that the
controlled executor would itself have to detect (e.g. an attacker
with write access to `run_root` between trusted steps); the gate
closes the in-process gap between its read of each input and its
atomic publish of the provenance artifact.
