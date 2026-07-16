# iFF assembly pipeline self-check

- Rules: `/Users/oklik/.codex/AGENTS.md`
- Scope: `SKILL.md`, `scripts/make_worker_prompt.py`, `scripts/verify_pipeline_scripts.py`, `scripts/assembly_plan_batch.py`, `scripts/assembly_completion.py`, and assembly focused selftests.
- Boundary: no business-project file was read, written, built, tested, or formatted.

## Requirement audit

| Requirement | Artifact evidence | Result |
| --- | --- | --- |
| Assembly context is bounded | Generated prompt says `Do NOT read ... SKILL.md ... in full`; isolated 1-board/8-board prompts are both 13,213 bytes, growth 0 bytes | PASS |
| Large plans are not model-patched | Prompt says `Edit ONLY the compact assembly_decisions.json` and `Do not patch any implementation_plan.json` | PASS |
| Deterministic fields are batched | `assembly_plan_batch.py prepare` runs board audits/digests/prefill/map checks; `apply` copies one feature judgment set into every plan and runs each plan checker | PASS |
| Necessary model judgment remains | Compact decisions retain `projectAlignment`, one `fixtureSource`, and `stateDataByBoard`; region rationale and inventory fields remain deterministic | PASS |
| Worker success is evidence-gated | Final prompt command is `assembly_completion.py issue`; it removes stale evidence, runs `check_done_gate.py`, requires non-empty `actual.png` beside `actual_source=simulator_screenshot`, then writes evidence | PASS |
| Main rejects false success | `SKILL.md` requires `assembly_completion.py verify` regardless of worker exit status; verifier returns nonzero when evidence is absent and reruns `check_done_gate.py` when present | PASS |
| Complete evidence stays bound to artifacts | Completion evidence records hashes for gate-critical artifacts and the done-gate report; verifier rejects missing or changed files | PASS |
| Surgical scope | All authored paths are under `/Users/oklik/.agents/skills/iff` | PASS |

## TDD evidence

| Cycle | RED | GREEN |
| --- | --- | --- |
| Bounded prompt | Exit 1: generated prompt still contained `Read .../SKILL.md completely` | `PASS: assembly prompt is 13213 bytes and grows 0 bytes for +7 boards` |
| Completion contract | Exit 1: `assembly_completion.py` did not exist, so missing completion evidence could not be classified | `PASS: exit 0 without evidence is rejected; complete evidence is accepted` |
| Legacy assembly CLI contract | Exit 1: old selftest expected a direct per-board plan checker command | `PASS: assembly uses exact batch plan commands and rejects invalid inputs visibly` |

## Final verification

| Check | Evidence | Result |
| --- | --- | --- |
| Assembly focused selftests | 7/7 exit 0, including bounded prompt, completion evidence, batch apply, CLI contract, board audits, fixture gate order, runtime fixture target | PASS |
| Pipeline preflight | `ok 71 scripts in /Users/oklik/.agents/skills/iff/scripts` | PASS |
| Python syntax | `python3 -m py_compile` on all changed Python files, exit 0 | PASS |
| Tracked whitespace | `git diff --check`, exit 0 | PASS |
| New-file whitespace | `git diff --no-index --check` emitted no warnings for all new/updated untracked focused files | PASS |

## Findings fixed during audit

1. Completion verification initially did not compare the saved done-gate report hash. Added report existence/hash validation and reran the completion selftest.
2. A legacy assembly prompt line still told the worker to record schema mismatches in `implementation_plan.json`. Replaced it with compact-summary reporting and an explicit no-direct-plan-patch rule.

STATUS: PASS
