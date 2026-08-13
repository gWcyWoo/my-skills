# iFF shared-worker supervisor self-check

Rules path: `~/.agents/skills/iff/test_rules.md`

Reviewed artifacts: `SKILL.md`, `scripts/make_worker_prompt.py`, `scripts/shared_worker_supervisor.py`, `scripts/selftest_shared_worker_supervisor.py`, `scripts/verify_pipeline_scripts.py`.

## Scope and preserved ownership

| Check | Evidence | Result |
|---|---|---|
| Generic skill only | All reviewed artifacts are under `~/.agents/skills/iff`; no business-project fixture was used. | ✅ |
| Shared-only launch change | `SKILL.md:438` makes `*.shared_invocation.json` plus `shared_worker_supervisor.py run` the sole shared launch path. | ✅ |
| Assembly preserved | Existing `selftest_assembly_worker_supervisor.py` passed in the full standalone sweep. | ✅ |
| Pipeline inventory | `verify_pipeline_scripts.py:84` and `:88` require the new supervisor and its focused regression. | ✅ |

## Fail-closed liveness and evidence

| Check | Evidence | Result |
|---|---|---|
| Current invocation sidecar | `make_worker_prompt.py:147` requires invocation/prompt/compliance bindings; `:164` emits `iff_shared_component_invocation`. | ✅ |
| Conservative configurable defaults | `make_worker_prompt.py:190` sets total timeout to 1200 seconds; the adjacent contract sets idle timeout to 300 seconds and CLI overrides are accepted by the supervisor. | ✅ |
| Stale evidence cleared | `shared_worker_supervisor.py:278` removes result, compliance, state, log, and failure evidence before launch. | ✅ |
| Complete process group | `shared_worker_supervisor.py:308` creates a new session/process group; `:131` sends group termination. | ✅ |
| Output stream and capture | `shared_worker_supervisor.py:176` forwards worker chunks while the same loop writes `shared_worker.log`. | ✅ |
| Idle/total stop | `shared_worker_supervisor.py:184` classifies idle timeout; the preceding branch classifies total timeout. | ✅ |
| Exit 0 is insufficient | `shared_worker_supervisor.py:212` binds result invocation; subsequent gates bind prompt/result/compliance paths and compliance hash before running the current compliance checker at `:227`. | ✅ |
| Machine-readable failure | Every rejected path emits `iff_shared_worker_failure` JSON and, after contract validation, writes `shared_failure.json`. | ✅ |

## Test discipline and regressions

| Check | Evidence | Result |
|---|---|---|
| Hung descendant rejected | `selftest_shared_worker_supervisor.py:189` requires `idle_timeout` and the test verifies the descendant received process-group termination. | ✅ |
| Exit 0 without result rejected | `selftest_shared_worker_supervisor.py:199` requires `missing_result`. | ✅ |
| Stale result rejected | `selftest_shared_worker_supervisor.py:216` requires the pre-launch stale result to be removed and rejected. | ✅ |
| Fresh result/compliance accepted | `selftest_shared_worker_supervisor.py:223` requires supervised success and fresh result/compliance files. | ✅ |
| Deterministic isolation | Tests use temporary directories and deadline polling; no business project, network, Flutter device, or mutable external service is involved. | ✅ |

## Commands

| Command | Result |
|---|---|
| `python3 scripts/selftest_shared_worker_supervisor.py` | PASS: hung process groups, missing/stale results, and fresh shared evidence are supervised. |
| Full standalone `scripts/selftest_*.py` sweep | 36/36 passed; `selftest_canvas.py` excluded because it requires an external Flutter project fixture. |
| `python3 scripts/selftest_shared_worker_compliance_writer.py` | PASS: current loaded-file evidence accepted and post-prompt drift rejected. |
| `python3 scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff` | `ok 77 scripts`. |
| `python3 -m py_compile scripts/*.py` | exit 0. |
| `git diff --check` | exit 0. |

No findings remain.

STATUS: PASS
