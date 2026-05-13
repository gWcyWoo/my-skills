# TDD Gates

## Test Plan

Before writing tests, present:

```text
Proposed tests
- Integration: <case name> - <request> -> <expected response/status/side effect>
- Integration: <invalid/auth/error case> - <request> -> <expected error>
- Unit: <logic/model/validator/helper> - <input/context> -> <expected result>
```

Then stop and ask:

```text
Please confirm, add, remove, or revise these test cases before I write them.
```

## Coverage

Integration tests must cover:

- HTTP method and endpoint path
- request path/query/header/body fields
- auth or middleware behavior when required by the contract or project conventions
- validation failures
- success response schema
- error response schema
- persistence or external side effects when present

Unit tests must cover newly created:

- logic methods/classes
- validators
- models with behavior beyond simple ORM mapping
- transformers/resources/response mappers
- pure helpers

Do not add unit tests for trivial framework glue unless existing project tests do so.

## Red

After user confirmation:

1. Write only confirmed tests.
2. Run the smallest command that executes the new tests.
3. Require red to prove missing or mismatched target behavior.

Acceptable red:

- missing route/action/class/method
- assertion failure for target behavior
- validation mismatch
- response schema mismatch

Unacceptable red:

- test syntax error
- missing unrelated fixture
- database/config/bootstrap failure
- wrong test namespace
- wrong test command
- mock setup error unrelated to target behavior

If tests pass before implementation, stop and report whether the implementation already exists, the test is ineffective, or the wrong path was tested.

## Green

After implementation, run:

- exact red tests
- related unit/integration tests
- smallest relevant regression suite

Do not claim completion unless all required tests pass or a concrete environment blocker is reported.
