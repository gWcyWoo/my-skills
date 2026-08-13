# iFF trace-schema and visual-repair order self-check

Rules: `~/.agents/skills/iff/SKILL.md`

Reviewed artifacts:

- `SKILL.md`
- `test_rules.md`
- `scripts/layout_trace_contract.py`
- `scripts/assembly_tdd_guard.py`
- `scripts/check_done_gate.py`
- `scripts/check_render_fidelity.py`
- `scripts/make_repair_plan.py`
- `scripts/make_worker_prompt.py`
- `scripts/verify_pipeline_scripts.py`
- `scripts/selftest_assembly_tdd_guard.py`
- `scripts/selftest_assembly_completion_evidence.py`
- `scripts/selftest_assembly_worker_supervisor.py`
- `scripts/selftest_render_fidelity_trace_gate.py`
- `scripts/selftest_repair_plan_trace_gate.py`

| Invariant | Artifact evidence | Verification evidence | Result |
|---|---|---|---|
| Generic skill scope only | All repairs are under `~/.agents/skills/iff`; no business project was inspected or modified. | Final status and diff checks were restricted to the iFF workspace. | PASS |
| Canonical trace schema | `layout_trace_contract.py` requires a non-empty string `pageType` and a non-empty top-level `nodes` object whose non-empty node ids map to objects. | `selftest_render_fidelity_trace_gate.py` accepts canonical `pageType+nodes`. | PASS |
| Empty and legacy traces fail closed | The shared trace contract rejects missing/empty `nodes`; render fidelity, repair planning, GREEN, and done/completion consume that shared contract. No consumer falls back to legacy `widgets`. | `selftest_render_fidelity_trace_gate.py` and `selftest_repair_plan_trace_gate.py` reject empty/legacy inputs before success outputs. | PASS |
| Stale traces fail before repair | `assembly_tdd_guard.py` loads every board trace with `min_mtime_ns=GREEN started_at_ns` before recording GREEN success. A canonical trace created before GREEN is rejected as stale. | `selftest_assembly_tdd_guard.py` proves stale rejection, then proves a trace freshly written by GREEN passes. | PASS |
| Completion repeats trace freshness | `check_done_gate.py` revalidates every board trace with the same schema and the recorded GREEN start timestamp; `assembly_completion.py` and the supervisor cannot turn worker exit 0 into success without this gate. | `selftest_assembly_completion_evidence.py` rejects legacy and canonical-but-stale traces; `selftest_assembly_worker_supervisor.py` rejects absent/stale completion evidence. | PASS |
| Repair budget is not consumed by trace failure | Assembly requires GREEN trace validation before capture and invokes `make_repair_plan.py --require-actual-trace`; missing/empty/legacy/stale trace failures stop before model-owned repair. | `selftest_assembly_visual_repair_contract.py` and `selftest_repair_plan_trace_gate.py` pass. | PASS |
| One repair and test budget remain bounded | The prompt retains one model-owned repair, no second repair, and the three feature-scoped RED/GREEN/audit test calls. | `selftest_assembly_visual_repair_contract.py` and `selftest_assembly_tdd_guard.py` pass. | PASS |
| Assembly context remains bounded | `make_worker_prompt.py` rejects assembly prompts over the 18,000-byte encoded limit before writing output; canonical trace wording remains board-count independent. | `selftest_assembly_bounded_context.py`: 16,794 bytes, 0-byte growth for seven additional boards; an oversized row is rejected without an output file. | PASS |
| Pipeline dependency is preflighted | `verify_pipeline_scripts.py` includes `layout_trace_contract.py`, so deleting the shared schema gate fails preflight. | `verify_pipeline_scripts.py`: `ok 81 scripts`. | PASS |
| Python and disposable Flutter integration are clean | All scripts compile; the disposable canvas project exercises generated Dart, trace tests, analysis, and fidelity. | `python3 -m py_compile scripts/*.py` passes; `selftest_canvas.py` passes both corpus cases with clean analyze and fidelity. | PASS |
| Diff and whitespace are clean | Tracked diff and all untracked iFF Python/Markdown artifacts were checked. | `git diff --check HEAD -- .` passes; 95 untracked text artifacts report zero whitespace issues. | PASS |

Resolved during audit:

- Reduced the assembly prompt from 18,114 bytes to 16,794 bytes without removing its exact runtime-fixture or canonical-trace contracts.
- Updated the synthetic complete-feature fixture to emit a canonical trace during GREEN instead of relying on a pre-existing trace.
- Added runtime trace freshness enforcement to GREEN and done/completion gates; canonical-but-stale traces now fail closed.
- Added `layout_trace_contract.py` to deterministic pipeline preflight.
- Restored the exact runtime-fixture-to-GREEN phrase required by the existing prompt contract while staying below the bounded-context cap.
- Added fail-closed 18,000-byte enforcement to assembly prompt generation and a regression case that proves oversized output is not written.

Final verification:

- 39/39 project-independent `selftest_*.py` scripts pass; `selftest_canvas.py` is the separately recorded disposable Flutter integration.
- `python3 scripts/verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff` passes with 81 required scripts.
- `python3 -m py_compile scripts/*.py` passes.
- Disposable Flutter canvas integration passes both regression corpus cases.
- Tracked diff check and untracked Python/Markdown whitespace checks pass.

STATUS: PASS
