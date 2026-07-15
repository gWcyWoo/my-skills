# Data accuracy task self-check

Reviewed current paths:

- `normalize_api_contract.py`, `check_data_bindings.py`, `make_data_model_packet.py`
- `check_data_runtime.py`, `check_api_integration.py`, `check_data_coverage.py`
- `run_feature_tests.py`, `check_data_evidence.py`
- `run_data_device_tests.py`, `check_data_device_evidence.py`
- `run_live_api_tests.py`, `check_live_api_evidence.py`
- `check_data_feature.py`, `check_done_gate.py`
- `SKILL.md`, `SCRIPTS_INDEX.md`, generated assembly worker contract

## Accuracy and completion audit

| Boundary | Current evidence | Result |
|---|---|---|
| OAS is canonical transport truth | Normalizer resolves local schema/response/parameter/requestBody/pathItem refs, rejects external refs and non-HTTP path items, and supports `--check`; feature/done recompute rather than trusting source SHA | ✅ |
| Every dynamic binding has semantic confirmation | All field bindings and static dispositions require `confirmedByModel=true`; deterministic candidate/type checks remain script-owned | ✅ |
| Model context is monotonic and bounded | Data packet is one action and ≤8192 bytes; large choices advance operation → field group → field; deterministic gate repair is marked `requiresJudgment=false` | ✅ |
| Runtime scope is the current feature, not the whole project OAS | Required operations derive from confirmed binding fields; non-slot operations require explicit model confirmation; each operation has stable `id/publicMethod` | ✅ |
| DTO/mapper/repository wiring is current | Runtime checker verifies real/mock shared interface, DTO and mapper plus entry reachability; API checker limits method/path call checks to the feature runtime closure | ✅ |
| SLOT behavior is public and data-driven | Coverage requires exact `(state,node,field)`, public app/widget surface, two distinct bound inputs and two visible outputs | ✅ |
| REPO behavior crosses a real HTTP boundary | Coverage requires `HttpServer.bind`, the public repository method, exact method/path, HTTP 200 and a mapped DTO field assertion | ✅ |
| STATE behavior is a visible public state | Runtime `stateTargets` supplies exact key/text; widget/integration coverage must enter the public runtime and assert both | ✅ |
| Hand-written device observations cannot pass | Feature gate accepts only `run_data_device_tests.py` evidence; checker rejects Browser/Web, recomputes bindings/runtime/app/test/pubspec/assets and validates PNG bytes/source linkage | ✅ |
| Android runtime result is current | Pixel 8 API 35 / `emulator-5554`: `DATA-SLOT:amount-node` passed from `app.main()`; automated captures were 750×1200 with SHA-256 `ddfe859f…0101c` and `316e0beb…b4cb`, proving two visibly different bound values; checker passed | ✅ |
| Live API cannot be asserted by editing JSON | Runner uses actual HTTP and validates expected status plus canonical response fields; checker reissues current HTTP requests. Local functional run observed `GET /loan/42`, status 200 and typed `$.amount`; wrong type was rejected | ✅ |
| External test/staging environment is explicit | No external environment URL/credentials were supplied, so external live verification remains conditional; `--require-live-api` fails unless current runner evidence can be rechecked | ✅ |
| Old reports fail after relevant input changes | Canonical contract, feature reports, TDD evidence, device captures and live request config all carry recomputed fingerprints; stale source/capture/request tests pass | ✅ |
| Regression impact is covered | Data-focused suites, local HTTP functional tests, pipeline inventory, Python compile and `git diff --check` passed; full suite: 297 tests passed | ✅ |

STATUS: PASS
