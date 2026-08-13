# P2.5c — Merged-Expectation Provenance Contract (platform-neutral, non-executable)

## Contents

- [Why raw projection cannot gate trace](#why-raw-projection-cannot-gate-trace)
- [What is implemented](#what-is-implemented)
- [Trust / data flow](#trust--data-flow)
- [Producer/consumer responsibilities — deferred to P2.5d](#producerconsumer-responsibilities--deferred-to-p25d)
- [Non-goals](#non-goals)
- [Protected files (P2.5c must not touch)](#protected-files-p25c-must-not-touch)
- [Files](#files)
- [Validation](#validation)

---

P2.5c adds exactly one new platform-neutral contract to SharedCore: the
**merged-expectation provenance v1** document. This contract records the
digest chain by which the frozen trace consumer's *effective* expected
document was assembled, so a future consumer gate can prove file B (the
merged document the consumer actually uses) rather than file A (the raw
canvas projection P2.5a1/a2/b materializes).

P2.5c is **contract + proof only**. It does not change any platform
adapter, execution plan/registry, authorization, executor, platform
activation gate, or the frozen iFF capsule. It does not cut over the
trace consumer. At the P2.5c checkpoint P2.5d and P3 remained pending;
P2.5d is now implemented only for the trusted trace-harness
provenance-binding scope (see
[`p25d-trace-harness-provenance-binding.md`](p25d-trace-harness-provenance-binding.md)),
and P3 remains pending.

## Why raw projection cannot gate trace

`gen_layout_trace_test.py` (frozen capsule primitive) takes `--expected
merged_expected.json`. When the caller supplies a raw canvas sidecar
instead, the primitive silently adopts an adjacent `merged_expected.json`
beside `--trace-out` and re-bases the canvas-sidecar nodes onto the merged
document (`_load_expected_contract`). The frozen consumer therefore
verifies the merged document, not the raw projection.

The merged document is produced by `merge_shared_expected.py` (also a
frozen capsule primitive) from three inputs:

1. the page canvas `*.expected.json` (whose canonical projection P2.5a1/a2/b
   materializes);
2. `shared_components.local.json` (the per-page shared-component registry;
   absent on a pass-through page);
3. the page `scene.json` (bbox source for shared-component reuse).

Gating the trace directly on the raw projection (P2.5a1/a2/b) would
therefore prove file A while the frozen consumer uses effective document B.
P2.5c closes that gap by defining the platform-neutral provenance chain
that records every input digest plus the produced merged document digest.
At the P2.5c checkpoint the anticipation was that a future consumer
gate (P2.5d) could require this provenance before the trace test runs;
P2.5d is now implemented for exactly that scope (see
[`p25d-trace-harness-provenance-binding.md`](p25d-trace-harness-provenance-binding.md)).

## What is implemented

`icp/scripts/shared_core/merged_expectation_provenance_v1.py` is a pure
standard-library-only module. It exposes no CLI, performs no filesystem or
network I/O, makes no process calls, accepts no path/root override, sets
no bytecode flag, and never imports a platform module, the iFF v1
compatibility capsule, or the P2.5a1 projection module. Its public API is
exactly:

- `build_provenance(*, producerKind, producerSha256,
  pageCanvasProjectionSha256, sharedComponentsLocalSha256, sceneSha256,
  mergedExpectedSha256, pageCanvasNodeIds, sharedComponentNodeIds,
  mergedNodeIds) -> dict[str, object]` — constructs the exact document
  (with the fixed `kind`/`schemaVersion`) and validates it. Every variable
  field is keyword-only so callers cannot transpose positional digest
  arguments;
- `validate_provenance(value: Mapping[str, object]) -> dict[str, object]`
  — validates any Mapping and returns a detached plain-built-in clone in
  canonical top-level key order;
- `build_provenance_bytes(value: Mapping[str, object]) -> bytes` —
  validates first, then serializes only the detached validated document;
- `MergedExpectationProvenanceError(ValueError)` — the dedicated validation
  exception type. All validation failures raise only this exception.

### Exact document shape and key order

The canonical top-level key order is contractual:

```json
{
  "kind": "icp.shared.merged-expectation-provenance.v1",
  "schemaVersion": 1,
  "producerKind": "<safe identifier>",
  "producerSha256": "<64 lowercase hex>",
  "pageCanvasProjectionSha256": "<64 lowercase hex>",
  "sharedComponentsLocalSha256": "<64 lowercase hex or null>",
  "sceneSha256": "<64 lowercase hex>",
  "mergedExpectedSha256": "<64 lowercase hex>",
  "pageCanvasNodeIds": ["..."],
  "sharedComponentNodeIds": ["..."],
  "mergedNodeIds": ["..."]
}
```

### Field semantics

| Field | Meaning |
| --- | --- |
| `kind` | Exact literal `icp.shared.merged-expectation-provenance.v1`. |
| `schemaVersion` | Exact literal integer `1`. Bool is not int. |
| `producerKind` | Safe identifier matching `^[a-z][a-z0-9._-]{0,127}$`. The grammar is ASCII-only, so UTF-8 byte length is bounded by 128. Identifies which frozen producer produced this attestation (e.g., `iff-v1.merge_shared_expected`). |
| `producerSha256` | SHA-256 of the producer primitive's exact bytes (e.g., the `merge_shared_expected.py` file). P2.5d binds this to the trusted capsule manifest entry. |
| `pageCanvasProjectionSha256` | SHA-256 of the raw page-canvas projection document — the file P2.5a1/a2/b materializes and publishes. |
| `sharedComponentsLocalSha256` | SHA-256 of `shared_components.local.json`, **or `null`** when the frozen merge producer's missing-local pass-through path was taken (page has no shared components). `null` is the only allowed non-digest value for this field. |
| `sceneSha256` | SHA-256 of the page `scene.json` consumed by the merge. |
| `mergedExpectedSha256` | SHA-256 of the produced `merged_expected.json`. This is the *effective* expected document the frozen trace consumer verifies. |
| `pageCanvasNodeIds` | Page-canvas node-id list in insertion order (0..100000 unique strings). |
| `sharedComponentNodeIds` | Shared-component source-row node-id list the merge added (0..100000 unique strings, insertion order). Empty when the page is pass-through. |
| `mergedNodeIds` | Must equal exactly `pageCanvasNodeIds + sharedComponentNodeIds`, including order. This matches the `merged_expected.json` node key insertion order the frozen merge producer emits. |

### Validation rules

- Exact keys only. Missing, unknown-string, or non-string keys reject.
- `kind` and `schemaVersion` are exact; bool is not an integer.
- `producerKind` matches `^[a-z][a-z0-9._-]{0,127}$`.
- Every digest is exactly 64 lowercase hexadecimal characters.
  `sharedComponentsLocalSha256` alone may be `null` to attest the frozen
  merge producer's missing-local pass-through case.
- Each node-id list contains 0..100000 unique strings in insertion order.
  Node ids are non-empty, valid strings, at most 512 UTF-8 bytes, contain
  no ASCII control characters (`U+0000`..`U+001F` or `U+007F`), and are
  **not** normalized or reordered.
- `pageCanvasNodeIds` and `sharedComponentNodeIds` sets are disjoint.
- `mergedNodeIds` must equal exactly `pageCanvasNodeIds +
  sharedComponentNodeIds`, including order.
- Canonical encoded output is at most 32 MiB.

### Detachment guarantees

`validate_provenance` returns detached plain built-in objects. The
caller's `Mapping` subclass is never serialized directly; the caller's
sequence subclass is never serialized directly; the caller's input is
never mutated. Mutating the caller's input after `validate_provenance` or
`build_provenance_bytes` does not change the returned document or bytes.

### Canonical encoding

The canonical byte form is exactly:

```python
json.dumps(detached_document, ensure_ascii=False, indent=2,
           allow_nan=False).encode("utf-8")
```

with fixed insertion order (the contract's top-level key order), no key
sorting, `allow_nan=False`, and no trailing newline. `allow_nan=False`
is defensive: the schema has only `str`/`int`/`None`/`list[str]` values,
so NaN/Infinity can never appear, but using `allow_nan=False` keeps the
contract honest if a future field ever carries a float.

## Trust / data flow

```
                  P2.5a1/a2/b produces                merge_shared_expected.py
                  the raw page-canvas                 (frozen capsule primitive)
                  projection artifact.
                              │                                       │
                              │                                       │ inputs:
                              │                                       │  • page canvas expected.json
                              │                                       │  • shared_components.local.json
                              │                                       │  • scene.json
                              │                                       ▼
                              │                              merged_expected.json
                              │                                       │
                              └───────────────┬───────────────────────┘
                                              ▼
                              P2.5c provenance document records every
                              input digest + the merged output digest +
                              the page/shared/merged node order.
                                              │
                                              ▼
                              P2.5d consumer gate (DEFERRED at P2.5c;
                              now implemented — see P2.5d reference)
                              requires this provenance before trace
                              test runs.
```

The producer is responsible for computing every digest over the exact
input/output bytes that flowed through the frozen merge primitive (or an
equivalent trusted producer). The producer is also responsible for
recording the producer SHA-256 (e.g., the `merge_shared_expected.py` file
bytes) so a downstream gate can re-attest it against the trusted capsule
manifest entry.

The consumer is responsible for re-validating this provenance document
through SharedCore and for re-deriving every digest from the actual
input/output files it can read, then requiring byte equality. Only after
that may the consumer accept the merged document as the effective
expected input.

## Producer/consumer responsibilities — deferred to P2.5d

The following responsibilities were identified as P2.5d scope at the
P2.5c checkpoint and are now implemented in the trusted trace-harness
binding (see
[`p25d-trace-harness-provenance-binding.md`](p25d-trace-harness-provenance-binding.md)).
They are recorded here as the contract-level requirements P2.5c
hand-off language and are out of scope for the P2.5c contract itself:

- **Producer binding**: write a platform producer that computes the
  provenance document from real input/output files, including the
  producer SHA-256 attestation against the trusted capsule manifest.
- **Adapter binding**: extend the Flutter adapter (or a sibling platform
  primitive) to publish the provenance artifact alongside the merged
  document.
- **Consumer gate — `--expected` binding**: bind the frozen trace
  consumer's `--expected` argument directly to the exact verified
  `merged_expected.json` whose bytes hash to `mergedExpectedSha256`. The
  v1 `mergedExpectedSha256` field attests exactly one
  `merged_expected.json` byte file; it does not attest any synthesized
  two-file overlay.
- **Consumer gate — reject raw-sidecar + adjacent-merged auto-adoption**:
  the frozen `gen_layout_trace_test.py` silently adopts an adjacent
  `merged_expected.json` and re-bases a raw canvas sidecar onto it when
  the caller passes the raw sidecar as `--expected`
  (`_load_expected_contract`). The trusted plan/guard MUST reject this
  alternate path and require `--expected` to be the verified merged
  file, so the digest the gate attests is the digest the consumer
  actually reads.
- **No overlay claim**: never claim the existing v1
  `mergedExpectedSha256` attests a synthesized two-file overlay. A
  future overlay-preserving design would need a separate canonical
  effective-document digest contract (a v2 schema); v1 does not provide
  one.

### P2.5d required invariant

> Bind the frozen trace consumer's `--expected` argument directly to the
> exact verified `merged_expected.json` whose bytes hash to
> `mergedExpectedSha256`, and reject the raw-sidecar + adjacent-merged
> auto-adoption path in the trusted plan/guard. The v1
> `mergedExpectedSha256` attests exactly one `merged_expected.json` byte
> file; it cannot attest a synthesized two-file overlay, and a future
> overlay-preserving design would require a separate canonical
> effective-document digest contract.

P2.5c's contract records the digest chain; at the P2.5c checkpoint the
consumer enforcement was deferred to P2.5d, which is now implemented for
the trusted trace-harness binding scope (see
[`p25d-trace-harness-provenance-binding.md`](p25d-trace-harness-provenance-binding.md)).

## Non-goals

P2.5c intentionally does **not**:

- activate any platform;
- change any registry entry, operation ID, or request schema;
- change any binding/authorization/executor/preflight/standard production
  module;
- change the frozen capsule, either baseline manifest, or any `iff/` file;
- change P2.5a1/a2/b production modules;
- import the P2.5a1 projection module;
- claim that the raw projection v1 can represent merged shared-component
  nodes (it cannot — the merge introduces new source-row node ids not
  present in the raw page canvas);
- reproduce iFF merge behavior in SharedCore;
- cut over the trace consumer (no `flutter.trace_harness.v1` change);
- add a new executable operation or producer artifact (the producer is
  not part of P2.5c);
- weaken or replace any existing test.

## Protected files (P2.5c must not touch)

The P2.5c selftest asserts the SHA-256 of each of these files matches
the live RED fixture constant recorded before P2.5c production changes.
Drift in any of these hashes fails the selftest.

- `icp/scripts/shared_core/expected_slots_projection_v1.py`
- `icp/scripts/shared_core/__init__.py` (left byte-identical)
- `icp/scripts/platforms/flutter_expected_slots_adapter_v1.py`
- `icp/scripts/platforms/flutter_fixture_projection_guard_v1.py`
- `icp/scripts/platforms/flutter_operations_v1.py`
- `icp/scripts/platforms/flutter_execution_binding_v1.py`
- `icp/scripts/platforms/flutter_execution_authorization_v1.py`
- `icp/scripts/platforms/flutter_execution_executor_v1.py`
- `icp/scripts/platforms/flutter_project_preflight_v1.py`
- `icp/scripts/platforms/flutter_standard_v1.py`
- `icp/references/registries.json`
- `icp/references/baselines/iff-v1-vendor.json`
- `icp/references/baselines/iff-v1.json`
- `iff/scripts/merge_shared_expected.py`
- `icp/vendor/iff_v1/scripts/merge_shared_expected.py`
- every other file under `iff/**`

## Files

- `icp/scripts/shared_core/merged_expectation_provenance_v1.py` — pure
  standard-library-only provenance validator + canonical byte serializer.
- `icp/scripts/selftest_p25c_merged_expectation_provenance.py` — focused
  RED -> GREEN selftest (104 cases) covering happy path / detachment /
  null-and-present local digest / empty-and-large node sets / missing-
  unknown-non-string top-level keys / wrong kind-version-bool / producerKind
  grammar boundaries / digest failures for every field / node-id type/
  empty/control/byte-bound/duplicates/page-shared-overlap/merged-order/
  missing/extra failures / 32 MiB bound / NaN/Inf/custom-object rejection /
  typed-exception-only / no forbidden imports or literals / no `__pycache__`
  under `icp/` / differential evidence against the frozen
  `merge_shared_expected.py` (pass-through, shared-reuse, unresolved,
  collision, end-to-end digest chain) / protected-hash assertions /
  capsule verifier / baseline / live `iff/` no-drift.
- `icp/references/p25c-merged-expectation-provenance.md` — this document.
- `icp/SKILL.md` — concise P2.5c gate/pointer to this reference.

## Validation

```
PYTHONDONTWRITEBYTECODE=1 python3 icp/scripts/selftest_p25c_merged_expectation_provenance.py
```

P2.5c does not activate any platform, does not change any registry entry,
does not change any vendor/baseline/IFF file, does not change any
protected binding/authorization/executor/preflight/standard production
module, does not edit the frozen capsule or the frozen
`merge_shared_expected.py` producer, and does not cut over the trace
consumer. At the P2.5c checkpoint P2.5d and P3 remained pending; P2.5d
is now implemented only for the trusted trace-harness provenance-binding
scope (see
[`p25d-trace-harness-provenance-binding.md`](p25d-trace-harness-provenance-binding.md)),
and P3 remains pending.
