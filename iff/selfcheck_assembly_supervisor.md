# iFF assembly supervisor self-check

Rules path: `~/.agents/skills/iff/test_rules.md`

Reviewed artifacts: `SKILL.md`, `scripts/make_worker_prompt.py`, `scripts/assembly_worker_supervisor.py`, `scripts/selftest_assembly_worker_supervisor.py`, `scripts/verify_pipeline_scripts.py`, `STATUS.md`.

## Fail-closed handoff

| Check | Evidence | Result |
|---|---|---|
| Earliest reusable boundary | `make_worker_prompt.py:405` emits `"workerExitIsSuccess": False` in a generated invocation contract. | ✅ |
| Stale evidence invalidation | `assembly_worker_supervisor.py:102` removes any prior `assembly_completion.json` before launch. | ✅ |
| Freshness | `assembly_worker_supervisor.py:157` rejects evidence issued before the supervised run. | ✅ |
| Certificate verification | `assembly_worker_supervisor.py:162` invokes the fixed skill-local `assembly_completion.py`; `run` returns only its supervised verify result at line 199. | ✅ |
| Main handoff | `SKILL.md:65` requires `invocationContract.verifyCommand` regardless of worker/agent exit status. | ✅ |

## Preserved workflow contracts

| Check | Evidence | Result |
|---|---|---|
| Missing certificate regression | `selftest_assembly_worker_supervisor.py:81` requires a zero-exit no-op worker to be rejected. | ✅ |
| Fresh certificate success | `selftest_assembly_worker_supervisor.py:102` requires newly issued, verified evidence to succeed. | ✅ |
| RED → packaging → GREEN | `selftest_assembly_packaging_prompt_order.py` passed. | ✅ |
| Three-call budget, trace, one repair | Assembly fixture, visual-repair, completion, and board-audit regressions passed. | ✅ |
| Board/shared ownership | Four board and six shared-component ownership regressions passed. | ✅ |
| Required inventory | `verify_pipeline_scripts.py:85` includes the supervisor regression; pipeline verification reports 74 scripts. | ✅ |
| Status handoff | `STATUS.md` records the repaired boundary, 21/21 regression result, inventory result, scope, and `STATUS: PASS`. | ✅ |

## Commands

| Command | Result |
|---|---|
| `python3 scripts/selftest_assembly_worker_supervisor.py` | PASS: zero-exit without fresh evidence rejected; fresh verified evidence accepted. |
| 21 focused/relevant `selftest_assembly_*`, `selftest_board_worker_*`, and shared-component regressions | 21/21 passed. |
| `python3 scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff` | `ok 74 scripts`. |
| `python3 -m py_compile scripts/assembly_worker_supervisor.py scripts/selftest_assembly_worker_supervisor.py scripts/make_worker_prompt.py` | exit 0. |
| `git diff --check` | exit 0. |

No findings remain.

STATUS: PASS
