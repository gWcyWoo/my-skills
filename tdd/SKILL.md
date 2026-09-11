---
name: tdd
description: Apply integration-contract-first TDD when the user selects TDD or test-first development, or an applicable workflow requires it.
---

# Integration-Contract-First TDD

This skill defines the TDD execution procedure once the task's TDD choice is established. General test-quality standards and bug-reproduction requirements in the applicable project and global instructions remain in force.

## Required Outcome

Treat the implementation as a replaceable black box. Required integration tests are the executable acceptance contract and the primary acceptance evidence within the verified scope.

For every required behavior, define and verify:

- preconditions and starting state
- input through a public interface
- observable output or error
- observable state change or outbound interaction
- forbidden output or side effect when relevant

Assert exact contract-significant values. Do not couple tests to incidental values, private methods, internal collaborators, or internal data layout.

Exercise the real owned code path. Replace only dependencies outside the system's ownership boundary. Prefer an isolated real test database when persistence is owned, and verify persisted behavior through a public interface.

Read [tests.md](tests.md) before designing the first case; it contains the case template, coverage choices, and assertion examples. Read [mocking.md](mocking.md) when introducing a boundary substitute.

## Test-Layer Policy

- **Integration tests are required.** They define acceptance and determine completion.
- **Unit tests are optional.** Do not require or create them by default. Add them only when complex pure logic, many combinatorial cases, or faster fault localization provides value not supplied by the integration contract.
- Unit tests never replace, relax, or count as completion of a required integration contract.
- Browser, device, or deployed E2E tests are optional unless their runtime wiring or user interaction is itself part of the approved contract. They complement rather than replace integration tests.

## Contract Gate

Before changing production code:

1. Consult domain terms or ADRs when they affect the contract.
2. Identify the public entry point and the system ownership boundary. When the interface must change, keep it small and testable; see [interface-design.md](interface-design.md) and [deep-modules.md](deep-modules.md).
3. Map every agreed requirement, business workflow, behavioral boundary, and prohibited behavior to acceptance cases. For each case, record its requirement source, explicit starting state and input, independently derived expected results, forbidden effects, and the concrete defect it must detect. Use the compact case template in [tests.md](tests.md); existing task notes and tests are sufficient, without a separate mandatory document.
4. Inspect existing integration tests and reuse cases that already provide the required evidence. Select relevant normal, boundary, failure, state-transition, and order/timing cases using the coverage guide in [tests.md](tests.md). Do not enumerate unrelated combinations or add duplicate tests.
5. Reuse the user's requirements and approved contract. Ask only about unresolved observable behavior or a material contract change; do not require another approval for an unambiguous request. Never infer the expected result solely from current implementation behavior.
6. Before the first test or production edit, write the case map in existing task notes or a concise progress update. Do not leave it only in private reasoning or reconstruct it in the final report. Then encode the cases one vertical slice at a time.

Ask only for missing contract decisions: "For this public input and starting state, what exact observable result should define success?"

## Strict Vertical Workflow

Follow the gates in order for each case. A failed gate means repair the test or environment, resolve the contract, or investigate the implementation as directed below; it is not permission to skip the gate. Continue independent authorized work if a case is blocked, and keep its missing evidence explicit.

Keep only one active case: **record case → write/reuse its test → run and classify → implement only after valid RED → verify GREEN → record actual result → select next case**. `EXISTING_GREEN` skips implementation, not the run or result record. Do not add the next test until the current case's result is recorded, even when both cases are expected to pass. Parameterize equivalent inputs for the same behavior when useful; do not batch distinct behaviors into one cycle.

### 1. RED: Encode One Integration Case

Write one integration test for the highest-priority uncovered behavior that requires implementation. The test must detect the corresponding defect or contract violation, not merely execute the code path.

Before running it, check all five items:

1. **Independent expectation:** expected values follow from the recorded contract and explicit fixture data, not from the production calculation or copied runtime output.
2. **Real execution:** the test enters through a public interface and exercises real owned code; substitutes do not implement or bypass the behavior under test.
3. **Complete assertions:** assert required outputs, observable state and external effects, including what must not happen. An error response alone does not prove that side effects were prevented.
4. **Reliable execution:** isolate test data, control relevant time/randomness, await asynchronous work and assertions, and avoid order dependence. Reset fixtures between independent parameterized cases; share state only when the operation sequence itself is under test. Observe a defined completion point before asserting that an effect did not occur; do not use an arbitrary sleep as proof.
5. **Defect detection:** for each critical case, name a plausible defect, determine its observable result with the chosen fixture, and confirm that the expected assertion distinguishes it from the contract result. If both results coincide, change the fixture or add the missing interaction case before claiming coverage. Use the fixture-selection guide in [tests.md](tests.md). Assertions on later effects still need review even if an earlier assertion produces RED.

Run the selected test, confirm that the runner discovered and executed it, and inspect the failure:

| Observed result | Required next action |
| --- | --- |
| The intended assertion fails because the required behavior is wrong or missing | Record the test command, assertion, and actual failure; proceed to GREEN. |
| Syntax, import, fixture, environment, unrelated failure, or zero tests executed | Fix the cause and rerun. For a new interface, add only the minimal importable scaffold needed to reach the behavioral assertion. Do not label setup failures as RED or implement the feature to fix them. |
| The test passes before implementation | Check discovery, reached assertions, the real code path, and defect sensitivity. If the behavior already exists, record `EXISTING_GREEN` and reuse it; do not manufacture RED or change production code for that case. Otherwise repair the test. |
| A required prerequisite remains unavailable | Record `BLOCKED`, attempts, and the missing prerequisite. Do not claim RED or verified acceptance. |

For a bug regression, valid RED must reproduce the original defect under the identified conditions. Never change expected results merely to obtain a failure.

### 2. GREEN: Implement Only That Case

Write the minimum production code that implements the contract rule demonstrated by the case. Do not hard-code fixture-specific answers or weaken the assertion to accommodate the implementation. A complete fix may naturally satisfy later cases; verify them rather than artificially restricting the fix.

Run the new integration test and all previously passing integration cases affected by the change. They must be GREEN before continuing.

If a critical assertion's ability to detect its named defect remains uncertain, verify it with a small reversible fault in an isolated test environment. The test must fail at the intended assertion. Remove only that fault and rerun to confirm GREEN. If the faulty code still passes, repair the test before accepting the case. Reuse valid original-defect or RED evidence; do not inject faults into every case by default.

### 3. Repeat

Select the next approved behavior and repeat RED → GREEN:

```
contract case 1 → integration RED → minimal GREEN
contract case 2 → integration RED → minimal GREEN
contract case 3 → integration RED → minimal GREEN
```

Use discoveries from each slice to improve later test design and the coverage map, but never silently change an approved observable contract. Surface contradictions and request a contract decision. Record already verified behavior as `EXISTING_GREEN`; a preceding implementation may satisfy a later case without another production change.

### 4. Refactor While GREEN

Refactor only duplication or complexity introduced by the current change when it materially improves the implementation. Rerun affected tests after a refactor; do not start a general cleanup pass.

Never refactor while RED.

## Prohibited Shortcuts

- Writing all tests first and then all implementation
- Treating a unit test as acceptance evidence
- Mocking owned internal collaborators
- Testing private methods or internal call counts
- Loosening assertions or changing expected output only to make GREEN
- Adding unrelated future behavior before its integration test is RED
- Claiming RED when the failure comes from test setup or environment
- Deriving expected results from the implementation under test, or accepting an error response without checking required side-effect guarantees
- Treating skipped tests, zero discovered tests, or a substituted business operation as acceptance evidence

## Definition of Done

- Review the coverage map: every agreed requirement, business workflow, behavioral boundary, and prohibited behavior must link to a named passing integration test. Record any remaining required gap as `BLOCKED`; do not mark the task complete. Test counts, coverage percentages, and a green suite alone do not establish complete coverage.
- Tests enter through public interfaces and exercise the real owned code path.
- Exact contract-significant outputs, errors, state changes, and outbound interactions are asserted.
- Each implemented slice has valid RED evidence followed by GREEN. Reused or already implemented behavior has verified `EXISTING_GREEN` evidence; never invent a RED run.
- All relevant integration tests pass after implementation and refactoring.
- All five RED quality checks hold for the final tests; every temporary fault is removed. Complete required project checks and expand or repeat verification only for a new change, failure, or unresolved risk.
- No required test is skipped, weakened, or replaced by a unit test.
- Unit tests may be absent.

Report a compact mapping: requirement/case → test → defect detected → actual RED/GREEN or EXISTING_GREEN evidence. Include the final commands and results, plus any untested boundary or blocked prerequisite. Use actual execution evidence, not predicted outcomes; report the verification scope without claiming that all possible defects are excluded.
