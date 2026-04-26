# General Test Writing Rules — Attention Optimized

## 0. Scope

These rules apply **only when writing test code**.

They do not replace unit, integration, API, or E2E test planning rules.

Use them as a final writing gate after the test plan is approved.

---

## 1. Selector Rule

For UI-facing tests, prefer stable user-facing selectors:

```text
getByRole
getByLabelText
getByText
getByPlaceholderText
getByDisplayValue
```

Do not use test-only identifiers when a semantic selector exists:

```text
testID
data-testid
custom test-only hook
```

Allowed only when:

```text
no stable semantic selector exists
the element has no user-facing semantic representation
the platform lacks reliable role/label support
the identifier already exists as a stable project convention
```

Never add test-only identifiers solely to satisfy tests.

---

## 2. Framework Probe Rule

Do not create debug/probe tests by default.

Create one temporary framework probe only when:

```text
test helper behavior is unknown
render/fireEvent/userEvent behavior is unclear
manual event behavior is unclear
tree wrapper behavior blocks a correct test
an unfamiliar test failure suggests framework API mismatch
```

Probe rules:

```text
one probe maximum
delete before final output
do not include in test plan
do not keep tree-inspection assertions in real tests
do not use it to discover business behavior
```

---

## 3. Assertion Rule

Prefer assertions on user-observable or contract-observable outcomes.

Allowed:

```text
visible text/role/label/value
returned result
state visible through public consumer
error message/code
persisted or emitted contract
external boundary arguments when boundary is mocked
```

Forbidden as primary assertions:

```text
props inspection
private state inspection
render-tree internals
implementation-only class names
test helper internals
toHaveBeenCalled only
```

---

## 4. Expected Value Rule

Expected values must come from:

```text
AC
HLD
schema/type contract
route/API contract
business rule
test preconditions
```

Never derive expected values from implementation bodies.

Never weaken assertions to fit implementation.

Use exact values when known.

---

## 5. Reject Test Code If

Reject final test code if it:

```text
uses testID/data-testid while a semantic selector exists
adds test-only identifiers to implementation
keeps temporary debug probes
asserts render-tree internals
asserts props/private state
depends on framework quirks instead of observable behavior
uses fallback assertions for multiple possible implementations
weakens expected values to make the implementation pass
```

---

## 6. Final Rule

```text
Write tests against observable behavior and stable contracts.
Do not write tests against implementation details or test-only hooks.
Probe the framework only when blocked, then delete the probe.
```
