---
name: paac
description: Use when implementing, verifying, or reusing a ThinkPHP 6 API endpoint from an Apifox interface contract.
---

# PAAC

PAAC maps one Apifox interface to one ThinkPHP 6 outcome: reuse an existing endpoint, stop on conflict, or implement missing behavior through reviewed TDD gates.

## Non-Negotiable Code Exploration Rule

Before reading, searching, listing, extracting, or reasoning from project code for route, controller, logic, model, validator, middleware, response, test, or config evidence, use `my-explore-0` first and follow its constraints. This rule overrides every workflow step and reference file in this skill.

Skill docs and Apifox payloads are not project code; PAAC may read those directly. Everything in the target ThinkPHP repository is project code.

## Workflow

Handle one Apifox interface at a time unless the user explicitly expands scope.

1. Read Apifox, normalize `ApiContract`, resolve route/controller/action.
2. Compare existing behavior against Apifox.
3. Decide `reuse`, `conflict`, or `new`.
4. For `new`, design tests and stop for user review.
5. After approval, write tests, prove red, implement minimally, prove green.
6. Report controller/action, reused or added logic/model code, and test results.

## Gates

### Contract Checkpoint

Use available MCP/tool discovery to find Apifox tools; never hard-code tool names. If no Apifox tool is available, stop and say the session cannot read Apifox. Do not invent endpoint data or continue from memory.

Before touching code, output a concise `ApiContract`: source, method, endpoint, title/name, description, auth, request path/query/headers/body, success/errors, field notes.

Load [contract-normalization.md](references/contract-normalization.md) for large, nested, ambiguous, or tool-specific payloads.

### Routing Checkpoint

Use `my-explore-0` before reading route files or running codebase discovery.

Resolve the endpoint in the ThinkPHP 6 codebase before designing code changes.

Priority: explicit `route/*.php`, route groups/prefixes/middleware/domains/variables/patterns/chains, `php think route:list` when useful, then TP6 default routing only after explicit routes fail. Treat endpoint-derived controller/action names as hypotheses until evidence confirms them.

Output the resolved route, controller, action, middleware/auth, params, confidence, and evidence. If confidence is low and implementation would create or change behavior, stop and ask the user.

Load [php-route-resolution.md](references/php-route-resolution.md) before resolving routes in an unfamiliar project or when route groups/resource routes are involved.

### Reuse Decision Checkpoint

Use `my-explore-0` before reading controller, logic, model, validator, middleware, response helper, or test code.

If the route/controller/action exists, read only related controller, logic, model, validator, middleware, response helpers, and tests needed to judge behavior.

Classify the result:

- `reuse`: Existing implementation satisfies Apifox. Stop implementation and report the reused controller/action and why.
- `conflict`: Existing behavior, side effects, validation, auth, or response shape differs from Apifox. Stop and ask whether to create/split/modify.
- `new`: No matching implementation exists. Continue to test design.

Do not modify existing `logic` behavior unless the user approves that behavior change. Prefer full reuse, a new logic method/class, or a wrapper that preserves old semantics.

Load [implementation-decision-tree.md](references/implementation-decision-tree.md) for the exact reuse/conflict/new decision rules.

### Test Design Checkpoint

Before writing tests, present integration tests, unit tests for new collaborators, fixtures/database setup, and negative cases for validation/auth/errors. Ask the user to confirm, add, remove, or revise. Do not write tests before confirmation.

Load [tdd-gates.md](references/tdd-gates.md) before presenting the test design.

### Red Checkpoint

After approval, write only confirmed tests first and run the smallest relevant test command. Red must prove target behavior is missing or wrong. If tests pass before implementation, stop and explain why.

### Green Checkpoint

Implement the minimum code needed to satisfy the confirmed tests while respecting existing project conventions.

Run the new/changed integration tests, new/changed unit tests, and smallest relevant existing regression suite.

A PAAC task is complete only when the confirmed tests are green or when a concrete environment blocker is reported with exact reproduction details.

## Stop Points

Stop and ask the user when:

- Apifox is unavailable or the interface is ambiguous.
- Contract ambiguity affects behavior, validation, auth, persistence, or response shape.
- Route confidence is low, existing behavior conflicts, test design is unconfirmed, or pre-implementation tests pass.

## ThinkPHP 6 Defaults

Treat these as discovery starting points, not fixed project truth:

`route/*.php`; controllers in `app/controller`, `app/api/controller`, `app/<module>/controller`; logic in `app/logic`, `app/common/logic`, `app/<module>/logic`; models in `app/model`, `app/common/model`, `app/<module>/model`; validators in `app/validate`, `app/<module>/validate`; project-defined PHPUnit/Pest test dirs.

Follow the repository's own naming, dependency injection, response, exception, auth, and testing patterns over these defaults.

## Boundaries

- Implement exactly one active Apifox requirement unless the user expands scope.
- Never fabricate Apifox contract fields.
- Never skip route/controller/action resolution.
- Never silently change existing behavior.
- Never convert a conflict into an implementation task without user approval.
- Never explore project code outside `my-explore-0`.
- Never write implementation before approved tests.
- Never accept green pre-implementation tests as valid red-first TDD evidence.
- Respect active repo instructions for source-code reading, subagents, MCP usage, and validation commands.
