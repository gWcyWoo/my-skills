# Integration Testcase Planning Protocol — Attention Optimized

## 0. Prime Directive

Integration tests prove **real internal module collaboration**.

A valid integration case proves:

```text
real modules collaborate | external boundary contract is correct | observable outcome is correct
```

Pure logic, HTTP-only contracts, and full user journeys move out.

---

## 1. Decision Tree

For each in-scope AC or behavior, decide in this order:

```text
1. Meaningful collaboration across module/layer/state/contract boundary?
   no -> unit/not-testable.

2. Main risk is HTTP status/body/auth/header contract?
   yes -> api-owned.

3. Main risk is full browser/UI journey with real backend?
   yes -> e2e-owned.

4. Can internal modules run for real through a public trigger?
   no -> refactor-required.

5. Can only external boundaries be mocked/faked?
   no -> refactor-required.

6. Edge contracts and observable outcomes are known?
   no -> insufficient contract; do not invent.

7. Plan the smallest case set.
```

---

## 2. Classification

| Classification | Meaning | Action |
|---|---|---|
| `integration-testable` | Real internal modules must collaborate | Plan integration cases |
| `unit-owned` | Pure logic only | Move out |
| `api-owned` | HTTP/API contract | Move out |
| `e2e-owned` | Real UI/user journey | Move out |
| `refactor-required` | Requires mocking internals or private trigger | Propose boundary fix |
| `not-testable` | No meaningful collaboration/contract | Skip |

A skipped AC is not a gap when it has an owner.

---

## 3. Minimum Evidence

Before planning an integration case, know only:

```text
test slice
real modules
mocked external boundaries
edge contracts
public trigger
observable outcome
```

Stop exploring once these are known.

When HLD exists:

```text
Use HLD module flow, interfaces, states, events, API/error contracts.
Do not read implementation bodies unless HLD explicitly allows it.
```

When HLD does not exist:

```text
Use public components, service signatures, routes, types, imports/exports.
Do not plan around private implementation details.
```

Never invent modules, routes, props, states, errors, or contract values.

---

## 4. Test Slice Rule

For every case:

```text
Real Modules = internal modules that run for real.
Mocked Boundaries = external systems outside the slice.
```

Hard rules:

```text
Do not mock internal modules under test.
Mock only external boundaries.
If internal mocking is required, mark refactor-required.
```

External boundaries may include:

```text
network | third-party API | clock | browser/native API | payment/email provider | parent callback
```

DB rule:

```text
If persistence is the risk, include repository/DB in the slice.
If persistence is not the risk, DB may be mocked/faked.
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
contract expected value comes from AC/HLD/types/routes/schema
every edge contract appears in at least one case
mocked boundary assertions include connecting value + action/method + payload/options
dynamic values use concrete expected values
```

---

## 6. Direction Rule

Each case needs one direction:

```text
[ModuleA -> ModuleB] Risk — specific failure mode
```

Risk vocabulary:

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

User directions have priority. Otherwise derive directions from AC/HLD/source boundaries. Do not stop to ask unless workflow requires selection.

---

## 7. Case Selection

Generate the smallest useful set.

Include only:

```text
primary success collaboration
distinct cross-module error path
required edge contract
state propagation to consumers
toggle forward/reverse
rollback after failure
data transformation across boundary
conditional flow changing output
```

Exclude always:

```text
pure logic branch
duplicate equivalence class
static layout only
mock echo behavior
private helper behavior
implementation-only branch
same behavior for many API responses
```

Case budget:

```text
simple collaboration: 1-3
form/container + service: 2-5
state propagation: 2-6
API handler + service + repository: 2-6
complex workflow: 4-10
```

More than 10 cases for one slice means split or refactor.

---

## 8. Trigger and Outcome Rules

Each case must have:

```text
preconditions
trigger
expected observable outcome
```

Trigger must be the immediate cause of the asserted outcome.

Do not collapse:

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

## 9. Mock Echo and Expected Value Rules

Mocks drive behavior. They are not the result.

Reject a case when mocked input becomes expected output unchanged, unless it verifies an explicit passthrough contract.

Expected values must come from:

```text
AC | HLD | schema/type contract | route contract | business rule | precondition
```

Never from implementation body.

For calculated values, show the derivation.

---

## 10. Required Output

```md
## Integration Test Plan

**Test Type:** integration
**Strategy:** real internal modules; mock external boundaries only
**API Source:** HLD | Source Code
**Test File:** `__tests__/integration/[feature]/[name].test.ts`

### Edge Contracts

| Edge | Contract | Expected Value | Source |
|---|---|---|---|

### Test Cases

| # | Priority | Test Name | Direction | AC | Real Modules | Mocked Boundaries | Preconditions | Trigger | Contract Assertions | Expected Outcome |
|---|---|---|---|---|---|---|---|---|---|---|

### Non-Integration Items

| AC | Classification | Reason | Owner |
|---|---|---|---|

### Refactor-Required Items

| AC | Current Coupling | Required Change | Cases Unlocked |
|---|---|---|---|
```

Write `None.` for empty sections.

---

## 11. Reject Plan If

Reject the plan if any row:

```text
does not test real collaboration
mocks an internal module
lacks real modules or mocked boundaries
lacks trigger
lacks observable outcome
lacks required contract assertion
only asserts toHaveBeenCalled
echoes mocked input as expected output
belongs to unit/API/E2E
uses private state, props, or render-tree internals
duplicates an equivalent case
```

---

## 12. Final Rule

```text
Integration = collaboration.
Unit = pure logic.
API = HTTP contract.
E2E = real user journey.
Untestable coupling = refactor first.
```
