# iFF contract artifact fix self-check

Rules: `~/.agents/skills/iff/SKILL.md`

Reviewed artifacts:

- `SKILL.md`
- `scripts/make_worker_prompt.py`
- `scripts/check_contract_artifacts.py`
- `scripts/verify_pipeline_scripts.py`
- `scripts/selftest_contract_worker_anchor_gate.py`
- `scripts/selftest_contract_artifacts_gate.py`
- `scripts/selftest_interaction_contract_convergence.py`

| Check | Result | Evidence |
| --- | --- | --- |
| Contract generates anchors | PASS | Generated prompt contains the exact resolver command with `--contract`, `--index`, and `--out`. |
| Contract validates anchors | PASS | Generated prompt reruns the exact resolver command with `--check`. |
| Contract fails closed | PASS | Final prompt command is `check_contract_artifacts.py`; success is forbidden on nonzero exit. |
| Main rejects false-positive worker success | PASS | Main reruns the same gate after contract return and must not spawn assembly on nonzero exit. |
| Assembly consumes the same gate | PASS | Assembly prompt runs `check_contract_artifacts.py` before any assembly write. |
| Required artifacts are explicit | PASS | Gate requires eight contract JSON artifacts and a valid board index. |
| Missing or invalid artifact exits nonzero | PASS | Gate returns 1 for missing or invalid JSON and propagates anchor-check failure. |
| Regression tests | PASS | Five focused contract and assembly selftests passed. |
| Isolated scenarios | PASS | Missing anchors failed; complete no-reference and pending-route specs passed. |
| Script inventory | PASS | `verify_pipeline_scripts.py` reported 64 scripts. |
| Python syntax | PASS | `python3 -m py_compile scripts/*.py` exited 0 with cache redirected outside the skill. |
| Diff and whitespace | PASS | Scoped `git diff --check` exited 0; trailing-whitespace scans found no matches. |
| Scope | PASS | Edits are confined to `~/.agents/skills/iff`; no business project path was used. |

STATUS: PASS
