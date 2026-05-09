# TDD Gates

Use this reference before designing or writing tests.

## Test Design Review

Before writing tests, present a compact test plan:

```text
Proposed tests
- Integration: <case name> - <request> -> <expected response/status/side effect>
- Integration: <case name> - <invalid/auth/error request> -> <expected error>
- Unit: <logic/model/validator> - <input/context> -> <expected result>
```

Then stop and ask:

```text
Please confirm, add, remove, or revise these test cases before I write them.
```

## Integration Tests

Controller/action integration tests should cover:

- route method and path,
- request params/body shape,
- auth/middleware behavior when applicable,
- validation failures,
- success response structure,
- persistence or external side effects when applicable,
- project-standard error format.

## Unit Tests

Add unit tests for newly created:

- logic methods/classes,
- models with behavior beyond simple ORM mapping,
- validators,
- transformers/resources/response mappers,
- pure helpers introduced for the endpoint.

Do not add unit tests for trivial framework glue unless the project already does so.

## Red Gate

After approval, write tests before implementation and run the smallest command that executes the new tests.

Acceptable red:

- missing route/action/class/method,
- assertion failure showing missing behavior,
- validation/response mismatch caused by current implementation.

Unacceptable red:

- syntax errors in the test,
- missing fixtures unrelated to the target behavior,
- database/config/test bootstrap failure,
- wrong test namespace or command,
- mocking error that does not prove behavior is missing.

If tests are green before implementation, stop. Explain whether implementation already exists, the test is ineffective, or the wrong path was tested.

## Green Gate

After implementation, run:

- the exact red tests,
- related unit/integration tests,
- the smallest relevant regression suite available in the repo.

Do not claim completion unless all relevant tests are green or a concrete environment blocker is reported.
