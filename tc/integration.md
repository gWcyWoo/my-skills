# Test rules — integration

Loaded by the `test-writer` subagent in the integration plan phase, together with `general.md`.

## Definition

Integration tests are defined by WHAT they exercise — interfaces, flows, functionality — never by how real their boundaries are: drive a flow node through its provided interface with controlled inputs (neighbors mocked or faked) and assert outputs plus observable effects (files written, frames sent, exit codes, logs); never inspect a unit's internals.

## Mandatory coverage — every relevant interface

- user input/output interfaces (CLI commands, flags, output, logs, exit codes);
- function/method call interfaces (the confirmed contracts);
- command/API/UI/event/runtime entry points;
- flow cases (happy path and variants);
- data and validation boundaries;
- error/failure paths, injected at the same interfaces.

## Consistency rules

- One contract, one source: a neighbor's mock is derived from the same confirmed design contract (gate 1 of `~/.claude/CLAUDE.md` `<tdd-flow>`) the neighbor's own tests verify — never from assumption. Two suites green against two private understandings is how a broken flow hides. Prefer behavioral fakes whose script IS the contracted sequence.
- Fidelity stays real until a hard boundary: use real components (stores, registries, temp files, child processes) wherever they run in-process; stand-ins only at process and network boundaries. Every non-trivial adjacent boundary keeps at least one seam case where the two REAL nodes meet (e.g. real server handler + real client function).
- Assertions target the contract — outputs and observable effects. Never assert call counts or internal sequencing, unless that ordering is itself a confirmed contract invariant.
- Every enumerated forbidden flow or boundary becomes an outcome case asserting that the outcome does NOT happen; the enumeration source is the confirmed design's boundary analysis (gate 1 of `~/.claude/CLAUDE.md` `<tdd-flow>`).
