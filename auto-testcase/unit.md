# Unit Testcase Planning Protocol — Attention Optimized

## 0. Prime Directive

Unit tests prove **pure logic only**.

A unit case is valid only if it asserts one of:

```text
return value | next state | validation result | thrown error | domain decision | pure transformation
```

Everything else moves out.

---

## 1. Mode

```text
Supplementary mode: classify and plan only forwarded unit-scope gaps.
Explicit mode: classify every AC; only unit-testable AC fragments get unit cases.
```

---

## 2. Decision Tree

For each in-scope AC or behavior, decide in this order:

```text
1. Pure logical outcome?
   no -> not unit scope.

2. Requires module collaboration, DB, API, UI, routing, framework lifecycle, or real I/O?
   yes -> integration/api/e2e-owned.

3. Callable pure artifact exists?
   no -> refactor-required.

4. Needs more than 1 mock or more than 3 setup dependencies?
   yes -> refactor-required.

5. Expected outcome can be derived from AC/HLD/schema/business rule?
   no -> insufficient contract; do not invent.

6. Plan the smallest case set.
```

---

## 3. Classification

| Classification | Meaning | Action |
|---|---|---|
| `unit-testable` | Pure logic, no real I/O | Plan unit cases |
| `integration-owned` | Module/service/store/DB collaboration | Move out |
| `api-owned` | HTTP/API contract | Move out |
| `e2e-owned` | Real UI/user journey | Move out |
| `refactor-required` | Pure logic is coupled or uncallable | Propose extraction |
| `not-testable` | No meaningful logical outcome | Skip |

A skipped AC is not a gap when it has an owner.

---

## 4. Minimum Evidence

Before planning a unit case, know only:

```text
artifact signature
input/output types
logic rule
expected outcome source
mock count
```

Stop exploring once these are known.

When HLD exists:

```text
Use HLD signatures, types, rules, states, errors.
Do not read implementation bodies unless HLD explicitly allows it.
```

When HLD does not exist:

```text
Use exported/public contracts only.
Do not plan private implementation tests.
```

Never invent APIs, states, errors, types, or domain values.

---

## 5. Valid Artifacts

Good:

```text
pure function
reducer
validator
mapper
state machine
permission rule
calculation
domain decision
normalizer
```

Bad:

```text
component interaction
API handler
DB/network call
routing
framework lifecycle
service orchestration
hook effect lifecycle
```

A function calling a pure helper can still be unit scope.

---

## 6. Case Selection

Generate the smallest useful set.

Include only:

```text
representative valid case
distinct business rule
distinct validation error
meaningful state transition
forbidden transition
boundary that changes behavior
observable error path
invariant
```

Exclude always:

```text
duplicate equivalence class
branch with same outcome
private helper behavior
internal variable
dependency-call assertion
type-impossible input
```

Case budget:

```text
branch-free mapper: exactly 1
simple logic: 1-3
validator: 2-6
state machine/reducer: 3-8
complex rule: 4-10
```

More than 10 cases for one artifact means split or refactor.

---

## 7. Boundary and Expected Value Rules

Boundary tests only when the boundary changes behavior.

Do not test `null`, `undefined`, `{}` for strictly typed internal functions.

Malformed input tests only when input type allows:

```text
unknown | nullable | optional | external payload | runtime validation input
```

No `any` or `as any`.

Expected values must come from:

```text
AC | HLD | schema/type contract | business rule | precondition
```

Never from implementation body.

Never mirror implementation logic to compute expected output.

---

## 8. Required Output

```md
## Unit Test Plan

**Test Type:** unit
**Strategy:** pure logic only
**Mode:** Supplementary | Explicit
**API Source:** HLD | Source Code
**Test File:** `__tests__/unit/[feature]/[name].test.ts`

### Test Cases

| # | Priority | Test Name | AC | Artifact | Logic Rule | Input Class | Expected Outcome | Mock Count |
|---|---|---|---|---|---|---|---|---:|

### Non-Unit Items

| AC | Classification | Reason | Owner |
|---|---|---|---|

### Refactor-Required Items

| AC | Current Coupling | Extract To | Suggested Signature | Cases Unlocked |
|---|---|---|---|---|
```

Write `None.` for empty sections.

---

## 9. Reject Plan If

Reject the plan if any row:

```text
lacks artifact
lacks logic rule
lacks concrete expected outcome
has mock count > 1
tests dependency call only
uses impossible typed input
tests private implementation
duplicates an equivalent case
belongs to integration/API/E2E
```

---

## 10. Final Rule

```text
Unit = pure logic.
Integration = collaboration.
API = HTTP contract.
E2E = real user journey.
Coupled logic = refactor first.
```
