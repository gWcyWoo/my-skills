---
name: tdd
description: Integration-contract-first test-driven development with strict red-green-refactor vertical slices. Use when the user asks to build or fix behavior with TDD, strict TDD, integration tests, executable acceptance contracts, red-green-refactor, or test-first development.
---

# Integration-Contract-First TDD

## Required Outcome

Treat the implementation as a replaceable black box. Required integration tests are the executable acceptance contract and the primary proof that the feature is correct.

For every required behavior, define and verify:

- preconditions and starting state
- input through a public interface
- observable output or error
- observable state change or outbound interaction
- forbidden output or side effect when relevant

Assert exact contract-significant values. Do not couple tests to incidental values, private methods, internal collaborators, or internal data layout.

Exercise the real owned code path. Replace only dependencies outside the system's ownership boundary. Prefer an isolated real test database when persistence is owned, and verify persisted behavior through a public interface.

See [tests.md](tests.md) for contract examples and [mocking.md](mocking.md) for boundary-substitute rules.

## Test-Layer Policy

- **Integration tests are required.** They define acceptance and determine completion.
- **Unit tests are optional.** Do not require or create them by default. Add them only when complex pure logic, many combinatorial cases, or faster fault localization provides value not supplied by the integration contract.
- Unit tests never replace, relax, or count as completion of a required integration contract.
- Browser, device, or deployed E2E tests are optional unless their runtime wiring or user interaction is itself part of the approved contract. They complement rather than replace integration tests.

## Contract Gate

Before changing production code:

1. Use the project's domain glossary and applicable ADRs.
2. Identify the public entry point and the system ownership boundary. When the interface must change, keep it small and testable; see [interface-design.md](interface-design.md) and [deep-modules.md](deep-modules.md).
3. List the prioritized behavior cases as a compact contract:
   - case name
   - preconditions
   - exact public input
   - expected output or error
   - observable state or outbound effects
   - forbidden effects
4. Confirm the contract with the user. Treat an exact contract already supplied by the user as approval.
5. Do not write all executable tests at once. Encode the approved cases one vertical slice at a time.

Ask only for missing contract decisions: "For this public input and starting state, what exact observable result should define success?"

## Strict Vertical Workflow

### 1. RED: Encode One Integration Case

Write one integration test for the highest-priority unimplemented behavior.

Run it and verify that it fails because the required behavior is absent or wrong. A syntax error, broken fixture, unavailable environment, or unrelated failure is not valid RED evidence. If the test already passes, prove the behavior already exists or correct the test before implementation.

### 2. GREEN: Implement Only That Case

Write the minimum production code needed to satisfy the approved contract. Do not weaken or rewrite the contract assertion to accommodate the implementation.

Run the new integration test and all previously passing integration cases affected by the change. They must be GREEN before continuing.

### 3. Repeat

Select the next approved behavior and repeat RED → GREEN:

```
contract case 1 → integration RED → minimal GREEN
contract case 2 → integration RED → minimal GREEN
contract case 3 → integration RED → minimal GREEN
```

Use discoveries from each slice to improve later test design, but never silently change an approved observable contract. Surface contradictions and request a contract decision.

### 4. Refactor While GREEN

After the required integration cases pass, look for [refactor candidates](refactoring.md):

- [ ] Extract duplication
- [ ] Deepen modules (move complexity behind simple interfaces)
- [ ] Apply SOLID principles where natural
- [ ] Consider what new code reveals about existing code
- [ ] Run tests after each refactor step

Never refactor while RED.

## Prohibited Shortcuts

- Writing all tests first and then all implementation
- Treating a unit test as acceptance evidence
- Mocking owned internal collaborators
- Testing private methods or internal call counts
- Loosening assertions or changing expected output only to make GREEN
- Implementing future cases before their integration test is RED
- Claiming RED when the failure comes from test setup or environment

## Definition of Done

- Every approved required behavior is represented by a passing integration test.
- Tests enter through public interfaces and exercise the real owned code path.
- Exact contract-significant outputs, errors, state changes, and outbound interactions are asserted.
- Each new behavior produced valid RED evidence before its implementation.
- All relevant integration tests pass after implementation and refactoring.
- No required test is skipped, weakened, or replaced by a unit test.
- Unit tests may be absent.

Report the contract cases, the valid RED failure summary, the GREEN command and result, and any explicitly untested boundary.
