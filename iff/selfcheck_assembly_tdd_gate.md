# Assembly TDD Gate Self-Check

Rules: `~/.agents/skills/iff/test_rules.md`

Reviewed artifacts:

- `SKILL.md`
- `test_rules.md`
- `scripts/assembly_tdd_guard.py`
- `scripts/prepare_assembly_packaging.py`
- `scripts/check_done_gate.py`
- `scripts/make_worker_prompt.py`
- `scripts/verify_pipeline_scripts.py`
- `scripts/selftest_assembly_tdd_guard.py`
- `scripts/selftest_assembly_packaging_gate.py`
- `scripts/selftest_assembly_packaging_prompt_order.py`
- `scripts/selftest_assembly_completion_evidence.py`

## Contract audit

| Rule | Result | Evidence |
|---|---|---|
| RED is a real nonzero feature test with `missing_feature_behavior` | ✅ | `assembly_tdd_guard.py red` executes `flutter test`, records `runner`, `run_id`, command, exit code, failure kind, start/end nanoseconds, and output hash; it emits `phase=red_verified` only for the required failure. |
| Packaging is after and tied to RED | ✅ | `prepare_assembly_packaging.py` records `redEvidence.recordSha256`, `tddRunId`, and `preparedAtNs`; prepare and verify reject `preparedAtNs <= red.completedAtNs`, changed RED records, or unmatched run provenance. |
| GREEN cannot start through the prescribed command before valid packaging | ✅ | `assembly_tdd_guard.py green` calls `validate_evidence` before `run_test`; missing/invalid/stale packaging raises before the Flutter subprocess is launched. |
| GREEN evidence proves chronology and provenance | ✅ | `validate_tdd_chronology` requires `red.completedAtNs < packaging.preparedAtNs < green.startedAtNs`, matching run id, RED record hash, packaging file hash, packaging timestamp, guarded runner, and exit code 0. |
| Completion rejects direct or out-of-order GREEN | ✅ | `check_done_gate.py` appends every `validate_tdd_chronology` failure under `assembly TDD chronology`; `assembly_completion.py issue/verify` therefore cannot sign direct, legacy, stale, or forged GREEN evidence. |
| Generated assembly prompt prescribes only guarded RED/GREEN | ✅ | `make_worker_prompt.py` emits absolute `guarded_red` and `guarded_green` commands and explicitly forbids direct `flutter test` and handwritten evidence for those phases. |
| Existing assembly supervisor behavior remains intact | ✅ | `selftest_assembly_worker_supervisor.py` passes unchanged supervisor prepare/run/verify behavior with the strengthened completion gate. |
| Regression is executable | ✅ | `selftest_assembly_tdd_guard.py` proves legacy evidence fails, premature GREEN does not increment the fake-Flutter invocation count, and guarded RED → packaging → GREEN passes. `selftest_assembly_completion_evidence.py` proves direct GREEN fails at issue while guarded GREEN is accepted. |

## Verification

| Command | Result |
|---|---|
| 35 standalone `scripts/selftest_*.py` tests with required `--skill-dir` arguments | ✅ 35/35 passed |
| `python3 scripts/selftest_canvas.py --project /tmp/iff-gate-selftest.ZuJ7tl/app` | ✅ 2/2 corpus cases passed; analyze clean; fidelity pass |
| `python3 scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff` | ✅ `ok 75 scripts` |
| `python3 -m py_compile scripts/*.py` | ✅ exit 0 |
| `python3 scripts/check_worker_compliance.py --manifest /tmp/iff-gate-selftest.ZuJ7tl/worker_compliance.json --skill-dir ~/.agents/skills/iff` | ✅ `ok worker compliance` |

STATUS: PASS
