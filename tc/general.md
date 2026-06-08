# Test rules — general (all test types)

Loaded by the `test-writer` subagent in every phase. Single source of truth for the test-design detail of `~/.claude/CLAUDE.md` `<tdd-flow>` gates `2-test-case-design` and `3-all-red`.

## Division of duties

Unit and integration cases are EQUALLY important with distinct duties, and only together do they guarantee correctness: unit tests prove each leaf's internal logic; integration tests prove the nodes' interfaces, flows, and functionality. Neither replaces the other. Hazards nobody enumerated surface only when the real assembly runs — see `e2e.md`.

## Shared discipline

- Isolation and determinism: temp dirs and path hooks for persistence, injected clocks, no randomness; real child processes are reaped asynchronously; waits poll with deadlines, never bare sleeps.
- Case names state the contract, not the implementation; guards that pin existing behavior are labeled as such.

## Red phase rules

- New features → ALL new tests MUST fail for missing functionality — not compile or environment errors. Interfaces were confirmed at design time, so minimal signature stubs (empty bodies returning not-implemented) MAY be introduced to make compilation pass.
- Bug fixes → the bug-reproducing tests MUST fail; existing tests may pass.
- Guard cases that pin existing behavior stay green and MUST be labeled as such in both the plan and the summary.
- Never manufacture a red/green result with `xit`, `.skip`, `todo`, `pending`, or commented-out assertions.
- No business-logic production code is written during the red phase.
