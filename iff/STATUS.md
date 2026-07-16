# iFF assembly supervisor repair

Rules: `/Users/oklik/.codex/AGENTS.md`, `SKILL.md`, `test_rules.md`, and the task acceptance criteria.

Reviewed artifacts: `SKILL.md`, `test_rules.md`, `scripts/make_worker_prompt.py`, `scripts/assembly_worker_supervisor.py`, `scripts/assembly_completion.py`, `scripts/selftest_assembly_worker_supervisor.py`, `scripts/verify_pipeline_scripts.py`, `selfcheck_assembly_supervisor.md`.

| Check | Evidence | Result |
|---|---|---|
| Earliest mechanism | The generated assembly prompt previously had no executable outer acceptance boundary; raw process/agent completion could be consumed before certificate verification. | PASS |
| Fail-closed repair | Assembly prompt generation now emits `*.assembly_invocation.json`; supervisor `prepare` removes stale evidence, `run` wraps process execution, and `verify` alone accepts fresh evidence after `assembly_completion.py verify`. | PASS |
| Regression | Zero-exit no-op with a previously valid certificate is rejected; a worker issuing valid fresh evidence is accepted. | PASS |
| Pipeline invariants | RED → packaging → GREEN order, three-call budget, trace provenance, one-repair limit, and board/shared ownership regressions remain green. | PASS |
| Inventory | `verify_pipeline_scripts.py` requires the supervisor and its regression; verification reports 74 scripts. | PASS |
| Scope | Only `/Users/oklik/.agents/skills/iff` was edited; `/Users/oklik/Documents/projects/test` was not touched. | PASS |
| Self-check | `selfcheck_assembly_supervisor.md` records all audit rows clean. | PASS |

Verification: 21/21 focused/relevant regressions passed; Python compile passed; `verify_pipeline_scripts.py` reported `ok 74 scripts`; `git diff --check` passed.

STATUS: PASS
