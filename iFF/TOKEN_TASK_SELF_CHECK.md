# Token efficiency task self-check

Quality is the hard boundary; byte savings cannot waive visual, interaction, data, TDD, target-client or done gates.

## Completion audit

| Boundary | Current deterministic evidence | Result |
|---|---|---|
| No model is used for deterministic fetch | `run_fetch_pipeline.py` parses all board URLs in source order, runs every fixed stage, records commands/exits/output hashes and preserves partial failures | ✅ |
| Worker roster and completion are exact | Feature manifest derives N unique board workers + one assembly worker; each has unique v3 contract/prompt/result/receipt paths; v2, missing, extra, stale and out-of-project outputs fail | ✅ |
| Model input stays bounded without losing facts | Every worker prompt and component/visual/interaction/data packet is ≤8,192 UTF-8 bytes; row/component bulk data stays script-side behind path+SHA; each packet exposes one action | ✅ |
| Model decisions cannot write arbitrary state | Packet actions declare allowed decisions and exact per-decision write paths; `apply_model_decision.py` verifies all source SHA values and atomically writes exactly one source document | ✅ |
| Visual evidence is not self-asserted | Done recomputes `visual_diff.py` and `check_render_fidelity.py` from current PNG/layout/trace/expected/tokens and requires exact report equality; malformed PNG and hand-edited results fail | ✅ |
| Interaction and data share expensive runs | RED/GREEN use one `run_feature_tests.py` invocation per phase; final target-client proof uses one `run_client_device_tests.py` invocation and the same stdout for both evidence files, including required automated data captures | ✅ |
| Multi-state ownership is atomic | `state_changes.json` must cover every declared state; unknown/missing states, invalid paths, out-of-scope files and cross-state duplicate ownership fail | ✅ |
| Metrics state their measurement scope | `check_model_context.py` reports current retained input bytes, cumulative generated input bytes/count, controlled baseline/reduction and unmeasured channels; it never labels bytes as tokenizer tokens | ✅ |
| Five-board cardinality is explicit | Test fixture requires 14 current model files = 6 worker prompts + 1 component + 5 visual + 1 interaction + 1 data packet; controlled input reduction must remain ≥90% | ✅ |
| Regression coverage remains intact | Full iFF suite currently passes 313 tests across visual, component, interaction, data, device, done and token-efficiency flows | ✅ |

## Strict TDD evidence

Observed RED → GREEN slices include:

- no deterministic fetch CLI and partial failures being lost;
- v2/self-asserted worker compliance and ambiguous worker cardinality;
- oversized prompts/packets, full-rule reads and stale/multiple packet actions;
- absent implementation map and unrestricted/stale model decision writes;
- separate target-client runs and missing combined-run data captures;
- state changes limited to one state instead of one atomic manifest;
- malformed PNG bytes and hand-edited visual/fidelity reports passing stored hashes;
- done trusting stored model-context evidence instead of current recomputation.

## Measurement boundary

The gate measures reproducible UTF-8 input bytes. Tokenizer-specific counts, tool-call framing, hidden provider context and output tokens remain explicitly unmeasured; no false token estimate is presented as fact.

STATUS: PASS
