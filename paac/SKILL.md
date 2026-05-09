---
name: paac
description: Apifox-contract-driven PHP API development for ThinkPHP 6 projects. Use when Codex needs to implement, verify, or reuse a ThinkPHP 6 API endpoint from an Apifox interface contract, including Apifox MCP discovery, route/controller/action resolution, existing implementation comparison, logic/model reuse decisions, user-reviewed TDD test design, red-first tests, implementation, and green verification.
---

# PAAC

PAAC turns one Apifox API contract into a ThinkPHP 6 implementation decision: reuse an existing endpoint, stop for user direction when existing logic conflicts, or implement the missing behavior with TDD.

## Workflow

Run this workflow for one Apifox interface at a time. Do not batch multiple endpoints unless the user explicitly asks.

1. Discover and read the Apifox interface.
2. Normalize it into an `ApiContract`.
3. Resolve the ThinkPHP 6 route, controller, and action.
4. Compare any existing implementation against the Apifox description and schema.
5. Decide reuse, conflict, or new implementation.
6. Design tests and stop for user review.
7. Write tests and prove they are red for the target behavior.
8. Implement the smallest code change.
9. Run relevant tests until green.
10. Report the controller/action, reused or added logic/model code, and test results.

## Required Checkpoints

### Contract Checkpoint

Use available MCP/tool discovery to find Apifox tools. Do not hard-code a tool name.

If no Apifox tool is available, stop and tell the user the current session cannot read Apifox. Do not invent endpoint data.

After reading the interface, produce a concise normalized contract:

```text
ApiContract
- method:
- endpoint:
- title/name:
- description:
- auth:
- request:
  - path:
  - query:
  - headers:
  - body:
- response:
  - success:
  - errors:
- field notes:
```

Load [contract-normalization.md](references/contract-normalization.md) when the Apifox payload is large, nested, ambiguous, or tool-specific.

### Routing Checkpoint

Resolve the endpoint in the ThinkPHP 6 codebase before designing code changes.

Priority:

1. Inspect explicit routes in `route/*.php`.
2. Resolve `Route::group`, prefixes, middleware, domains, variables, patterns, and chain calls.
3. Use `php think route:list` only when it is available and useful.
4. Fall back to ThinkPHP 6 default routing only when explicit routes do not resolve the endpoint.
5. Treat endpoint-derived controller/action names as a hypothesis until code or route evidence confirms them.

Load [php-route-resolution.md](references/php-route-resolution.md) before resolving routes in an unfamiliar project or when route groups/resource routes are involved.

### Reuse Decision Checkpoint

If the route/controller/action already exists, read the related controller, logic, model, validate, middleware, and tests needed to judge behavior.

Classify the result:

- `reuse`: Existing implementation satisfies the Apifox description and request/response contract. Stop implementation and tell the user exactly which controller/action is reused and why.
- `conflict`: Existing implementation exists but the behavior, side effects, validation, or response shape differs from Apifox. Stop and ask the user whether to create a new action/route, rename/split behavior, or explicitly modify the existing behavior.
- `new`: No matching implementation exists. Continue to test design.

Do not modify existing `logic` behavior to satisfy a new contract unless the user explicitly approves that behavior change. Prefer full reuse, a new logic method/class, or a wrapper that preserves old semantics.

Load [implementation-decision-tree.md](references/implementation-decision-tree.md) for the exact reuse/conflict/new decision rules.

### Test Design Checkpoint

Before writing test code, present the proposed tests and stop for user review.

Include:

- Integration tests for the controller/action contract.
- Unit tests for any new logic, model, validator, transformer, or response mapper.
- Fixtures or database setup needed for meaningful behavior.
- At least one negative or validation case when the contract includes validation, auth, or error behavior.

Ask the user to confirm, add, remove, or revise the test cases. Do not write tests before this confirmation.

Load [tdd-gates.md](references/tdd-gates.md) before presenting the test design.

### Red Checkpoint

After user approval, write only the confirmed tests first. Run the smallest relevant test command and prove the new tests are red.

The red failure must show the target behavior is missing or wrong. If tests pass before implementation, stop and explain whether the behavior already exists, the test is ineffective, or the wrong code path was tested.

### Green Checkpoint

Implement the minimum code needed to satisfy the confirmed tests while respecting existing project conventions.

Run:

- the new/changed integration tests,
- the new/changed unit tests,
- and the smallest relevant existing regression tests.

A PAAC task is complete only when the confirmed tests are green or when a concrete environment blocker is reported with exact reproduction details.

## ThinkPHP 6 Defaults

Treat these as discovery starting points, not fixed project truth:

- routes: `route/*.php`
- controllers: `app/controller`, `app/api/controller`, `app/<module>/controller`
- logic: `app/logic`, `app/common/logic`, `app/<module>/logic`
- models: `app/model`, `app/common/model`, `app/<module>/model`
- validators: `app/validate`, `app/<module>/validate`
- tests: project-defined PHPUnit/Pest directories such as `tests/Feature`, `tests/Unit`, `tests/api`, or existing local equivalents

Follow the repository's own naming, dependency injection, response, exception, auth, and testing patterns over these defaults.

## Boundaries

- Implement exactly one active Apifox requirement unless the user expands scope.
- Never fabricate Apifox contract fields.
- Never skip route/controller/action resolution.
- Never silently change existing behavior.
- Never convert a conflict into an implementation task without user approval.
- Never write implementation before approved tests.
- Never accept green pre-implementation tests as valid red-first TDD evidence.
- Respect active repo instructions for source-code reading, subagents, MCP usage, and validation commands.
