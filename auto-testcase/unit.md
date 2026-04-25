# Unit Test Planning Rules — Attention-Optimized

## 0. Purpose

Unit test plans prove **pure logic** with the fewest stable cases.

They do **not** prove full feature behavior, module collaboration, API contracts, or user journeys.

---

## 1. Hard Boundary

A unit case is valid only if it verifies one of:

```text
return value
next state
validation result
thrown error
domain decision
pure transformation
```

Do **not** create unit cases for:

```text
UI interaction
component collaboration
API wiring
DB/network I/O
message publishing
routing
framework lifecycle
service orchestration
```

If the only useful assertion is `dependency was called`, it is **not** a unit test.

---

## 2. Required Planning Protocol

For each in-scope AC or behavior, do this in order:

```text
1. Classify it.
2. If unit-testable, name the pure artifact.
3. Extract one logic rule.
4. Select the minimum case set.
5. Define input class and exact expected outcome.
6. Move non-unit items out.
7. Mark coupled logic as refactor-required.
```

Use these exact classifications:

| Classification | Meaning | Action |
|---|---|---|
| `unit-testable` | Pure logic, no real I/O | Plan unit cases |
| `integration-owned` | Requires module/service/store/DB collaboration | Move out |
| `api-owned` | Requires HTTP/API contract | Move out |
| `e2e-owned` | Requires real UI/user journey | Move out |
| `refactor-required` | Pure logic exists but is coupled | Propose extraction |
| `not-testable` | No meaningful logic outcome | Skip |

Do **not** unit test every AC. Unit test only pure logic.

---

## 3. Contract Source

With HLD:

```text
Use HLD signatures, types, states, rules, and errors.
Do not read implementation bodies unless HLD explicitly allows it.
```

Without HLD:

```text
Use exported/public functions and types only.
Do not test private implementation details.
```

Never invent:

```text
APIs
parameters
return types
states
error codes
domain values
```

---

## 4. Unit Gate

A behavior enters the unit plan only if all are true:

```text
observable logic outcome
no real I/O
0 mocks preferred
1 mock maximum
not implementation-step testing
stable under refactoring
inputs valid under type contract
```

If any check fails, classify it outside unit scope or mark `refactor-required`.

---

## 5. Case Selection

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

Exclude:

```text
duplicate equivalence class
branch with same outcome
private helper behavior
internal variable
mock-call verification
type-impossible input
```

Case budget:

```text
branch-free mapper: exactly 1
simple pure logic: 1-3
validator: 2-6
state machine/reducer: 3-8
complex rule: 4-10
```

More than 10 cases for one artifact means split the artifact or mark `refactor-required`.

---

## 6. Boundary, Type, and Mapper Rules

Boundary tests are allowed only when the boundary changes behavior.

Do **not** test `null`, `undefined`, `{}`, or malformed input for strictly typed internal functions.

Malformed input tests are allowed only when input type is:

```text
unknown | nullable | optional | external payload | runtime validation input
```

Do **not** use `any` or `as any`.

Branch-free mapper rule:

```text
exactly one fully populated input -> one complete expected output
```

Do **not** create one case per mapped field.

---

## 7. Expected Outcome Rule

Every case must have one exact expected outcome.

Allowed:

```text
exact value
next state
error code/message
thrown error
domain decision
complete mapped object
```

Forbidden:

```text
dependency was called
function exists
branch entered
variable assigned
private method called
component rendered
```

Expected values must come from AC/HLD/schema/business rule/preconditions, not implementation body.

Do **not** mirror implementation logic to compute expected output.

---

## 8. Output Format

```md
## Unit Test Plan

**Test Type:** unit
**Strategy:** pure logic only
**Mode:** Supplementary | Explicit
**API Source:** HLD | Source Code
**Test File:** `__tests__/unit/[feature]/[name].test.ts`

### Test Cases

| # | Priority | Test Name | AC | Logic Rule | Artifact | Input Class | Expected Outcome | Mock Count |
|---|---|---|---|---|---|---|---|---:|

### Non-Unit Items

| AC | Classification | Reason | Owner |
|---|---|---|---|

### Refactor-Required Items

| AC | Current Coupling | Extract Logic To | Suggested Signature | Tests Unlocked |
|---|---|---|---|---|
```

Write `None.` for empty sections.

---

## 9. Reject Plan If

Reject the plan when any item is true:

```text
AC is neither covered nor classified
unit case has no concrete artifact
unit case has no logic rule
unit case has no exact expected outcome
mock count > 1
case only asserts dependency calls
case uses impossible typed input
case tests private implementation
case duplicates an equivalent path
non-unit concern remains in unit plan
refactor item lacks extraction proposal
```

---

## 10. Final Rule

```text
Unit tests prove pure logic.
Everything else moves out.
Coupled logic must be extracted before unit testing.
```
