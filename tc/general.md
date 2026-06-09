# Test rules — general (all test types)

Loaded by the `test-writer` subagent in every phase. Single source of truth for the test-design detail of `~/.claude/CLAUDE.md` `<tdd-flow>` gates `2-test-case-design` and `3-all-red`.

## Division of duties

Unit and integration cases are EQUALLY important with distinct duties, and only together do they guarantee correctness: unit tests prove each leaf's internal logic; integration tests prove the nodes' interfaces, flows, and functionality. Neither replaces the other. Hazards nobody enumerated surface only when the real assembly runs — see `e2e.md`.

## Shared discipline

- Isolation and determinism: temp dirs and path hooks for persistence, injected clocks, no randomness; real child processes are reaped asynchronously; waits poll with deadlines, never bare sleeps.
- Case names state the contract, not the implementation; guards that pin existing behavior are labeled as such.

## Plan presentation (every phase)

The plan returned at a STOP is for the user to APPROVE cases, not a compliance log. Per case state ONLY: `name → behavior/contract under test → expected observable result`. Add a `Decisions to approve` line for scope-changing choices (behavior deletions, migrations, the one mocked boundary). The mechanics these rules made you choose — real-vs-stand-in seams, one-contract-one-source mapping, file:line targets, fidelity boundaries, red-phase/gate-4 hazards — are your internal implementation notes: keep them for the implementation phase, NEVER dump them in the plan. No `Files under test`, no `[target: file:line]`, no per-case seam/red/hazard prose. If the user won't read it, the STOP is wasted.

## Red phase rules

- New features → ALL new tests MUST fail for missing functionality — not compile or environment errors. Interfaces were confirmed at design time, so minimal EMPTY signature stubs for genuinely-NEW symbols (empty bodies returning not-implemented / a zero value) MAY be added ONLY to make the package compile. A stub MUST stay empty: putting working logic in it, or editing/rewriting/removing/renaming any EXISTING production symbol, is IMPLEMENTATION — forbidden here, gate-4 only. The red comes from the empty stub / unchanged existing behavior, never from tc implementing anything.
- Bug fixes → the bug-reproducing tests MUST fail; existing tests may pass.
- Guard cases that pin existing behavior stay green and MUST be labeled as such in both the plan and the summary.
- Never manufacture a red/green result with `xit`, `.skip`, `todo`, `pending`, or commented-out assertions.
- tc writes TEST CODE + EMPTY new-symbol compile stubs ONLY — never production logic. No real function bodies, no rewriting existing functions to their target behavior, no removing/renaming existing symbols, no feature completion: all of that is the caller's gate-4 step. If a red test could only go green by writing production code, STOP and report it; do NOT implement it.
