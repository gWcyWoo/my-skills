# Integration Test Planning Rules — Attention-Optimized

## 0. Purpose

Integration test plans prove **real internal module collaboration** with the fewest stable cases.

They do **not** prove pure logic alone, HTTP contracts alone, or full E2E user journeys.

---

## 1. Hard Boundary

An integration case is valid only if it verifies:

```text
real internal modules collaborate
external boundary contract is correct
observable outcome is correct
state/error propagation is correct
```

Meaningful integration boundaries include:

```text
component -> child/hook/store
container -> service -> mapper
API handler -> service -> repository
service -> adapter/client
state update -> consumers
producer -> consumer
```

Not integration scope:

```text
pure function -> pure helper
branch-free passthrough with no contract risk
single-module validation before collaboration
static UI layout
full browser journey with real backend
```

A function calling another file is **not** automatically integration scope.

---

## 2. Required Planning Protocol

For each in-scope AC or behavior, do this in order:

```text
1. Classify it.
2. If integration-testable, choose the test slice.
3. Name real internal modules.
4. Name mocked/faked external boundaries.
5. Extract edge contracts.
6. Select the minimum case set.
7. Move unit/API/E2E items out.
8. Mark untestable coupling as refactor-required.
```

Use these exact classifications:

| Classification         | Meaning                                      | Action                 |
| ---------------------- | -------------------------------------------- | ---------------------- |
| `integration-testable` | Real internal modules/layers collaborate     | Plan integration cases |
| `unit-owned`           | Pure logic only                              | Move to unit           |
| `api-owned`            | HTTP/API contract is main risk               | Move to API            |
| `e2e-owned`            | Full UI/user journey is main risk            | Move to E2E            |
| `refactor-required`    | Requires mocking internals or private access | Propose boundary fix   |
| `not-testable`         | No meaningful behavior/contract              | Skip                   |

Do **not** integration test every AC. Test only collaboration risk.

---

## 3. Test Slice Rule

Every case must define:

```text
Real Modules = internal modules that run for real
Mocked Boundaries = external systems outside the slice
```

Hard rules:

```text
Do not mock internal modules under test.
Mock only external boundaries.
If internal mocking is required, mark refactor-required.
```

External boundaries may include:

```text
network
third-party API
system clock
browser/native API
payment/email provider
parent callback
```

DB rule:

```text
If persistence is the risk, include repository/DB in the slice.
If persistence is not the risk, DB may be mocked/faked.
```

---

## 4. Contract Source

With HLD:

```text
Use HLD module flow, interfaces, states, events, API/error contracts.
Do not read implementation bodies unless HLD explicitly allows it.
```

Without HLD:

```text
Use public components, service signatures, routes, types, imports/exports.
Do not plan around private implementation details.
```

Never invent:

```text
modules
routes
props
parameters
return types
states
error codes
```

---

## 5. Edge Contract Rule

For each meaningful edge, extract the crossing contract:

```text
props/callback
state/action
method args
endpoint + method + payload
query/write contract
event payload
```

Rules:

```text
expected contract comes from AC/HLD/types/routes/schema
every edge contract is asserted in at least one case
mocked boundary assertions include connecting value + action/method + payload/options
dynamic values are asserted concretely
```

---

## 6. Direction Rule

Each case must have one risk direction:

```text
[ModuleA -> ModuleB] Risk — specific failure mode
```

Use risks such as:

```text
Contract Mismatch
Data Transform Mismatch
Error Propagation
State Propagation
Conditional Flow
Async Failure
Rollback
Permission/Auth Propagation
Cache/Store Desync
Event Payload Mismatch
```

User directions have priority. If absent, derive from AC/HLD/source boundaries.

---

## 7. Case Selection

Generate the smallest useful set.

Include only:

```text
primary success path
distinct cross-module error path
required edge contract
state propagation to consumers
toggle forward/reverse
rollback after failure
data transform across boundary
conditional flow changing output
```

Exclude:

```text
pure logic branch
duplicate equivalence class
static layout only
mock echo behavior
private helper behavior
implementation-only branch
same behavior repeated for many API responses
```

Case budget:

```text
simple collaboration: 1-3
form/container + service: 2-5
state propagation: 2-6
API handler + service + repository: 2-6
complex workflow: 4-10
```

More than 10 cases for one slice means split the slice or mark `refactor-required`.

---

## 8. Trigger and Outcome Rule

Each case must specify:

```text
Preconditions
Trigger
Expected Outcome
```

The trigger must be the immediate cause of the asserted outcome.

Do **not** collapse:

```text
A -> B -> C -> D
```

into:

```text
A -> D
```

Allowed outcomes:

```text
visible DOM result
returned result
error code/message
persisted record
emitted event
state visible through consumer
external boundary contract
loading/final/rollback state
```

Forbidden primary outcomes:

```text
toHaveBeenCalled only
props inspection
private state inspection
render-tree internals
mock value echoed unchanged
branch entered
```

Call assertions are allowed only for external boundary contract verification.

---

## 9. Mock Echo and Expected Value Rule

Mocks drive behavior. They are not the result.

Before accepting a case, ask:

```text
What real collaboration, transform, route, render, persistence, or state change did the mock trigger?
```

If output equals mocked input unchanged:

```text
allow only explicit passthrough contract verification
otherwise remove the case
```

Expected values must come from AC/HLD/schema/route/business rule/preconditions, not implementation body.

For calculated values, include derivation.

---

## 10. Refactor Trigger

Mark `refactor-required` when:

```text
internal module must be mocked
collaboration cannot be triggered publicly
only possible assertion is a mock call
test needs private state or render-tree inspection
boundaries are too coupled to isolate external systems
```

Output current coupling, required boundary change, and tests unlocked.

---

## 11. Output Format

```md
## Integration Test Plan

**Test Type:** integration
**Strategy:** real internal modules; mock external boundaries only
**API Source:** HLD | Source Code
**Test File:** `__tests__/integration/[feature]/[name].test.ts`

### Edge Contracts

| Edge | Contract | Expected Value | Source |
| ---- | -------- | -------------- | ------ |

### Test Cases

| #   | Priority | Test Name | Direction | AC  | Real Modules | Mocked Boundaries | Preconditions | Trigger | Contract Assertions | Expected Outcome |
| --- | -------- | --------- | --------- | --- | ------------ | ----------------- | ------------- | ------- | ------------------- | ---------------- |

### Non-Integration Items

| AC  | Classification | Reason | Owner |
| --- | -------------- | ------ | ----- |

### Refactor-Required Items

| AC  | Current Coupling | Required Change | Tests Unlocked |
| --- | ---------------- | --------------- | -------------- |
```

Write `None.` for empty sections.

---

## 12. Reject Plan If

Reject the plan when any item is true:

```text
AC is neither covered nor classified
case does not test real internal collaboration
real modules are unnamed
mocked boundaries are unnamed
internal module is mocked
mocked boundary lacks exact contract assertion
edge contract is not covered by any case
case lacks preconditions, trigger, or outcome
case only asserts toHaveBeenCalled
case merely echoes mocked input
unit/API/E2E concern remains in integration plan
refactor item lacks boundary-fix proposal
duplicate equivalent case exists
```

---

## 13. Final Rule

```text
Integration tests prove collaboration.
Everything else moves out.
Untestable coupling must be refactored first.
```
