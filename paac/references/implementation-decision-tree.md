# Implementation Decision Tree

Use this reference after route/controller/action resolution.

## Read Enough Code

Inspect the controller action and only the related collaborators needed to judge behavior:

- request validation or validator classes
- auth/middleware used by the route
- logic/service classes called by the action
- model/query code used by the logic
- response helpers/transformers/resources
- existing tests for the endpoint or reused logic

Stop reading once the reuse/conflict/new decision is justified.

## Decision Rules

### Reuse

Choose `reuse` when all are true:

- the route accepts the Apifox method and endpoint,
- the controller/action executes the described business behavior,
- required input fields are accepted and validated consistently,
- response shape and status/error behavior match the contract or project-standard equivalent,
- side effects match the description,
- existing dependencies are appropriate for the same domain concept.

Return the reused controller/action and key supporting logic. Do not edit code unless the user separately requests added tests.

### Conflict

Choose `conflict` when a matching route/action exists but any material behavior differs:

- different business meaning,
- incompatible validation,
- incompatible response schema,
- different persistence side effects,
- different auth/permission semantics,
- shared logic would need a semantic change,
- changing it could affect existing callers.

Stop and ask the user to choose a direction. Do not implement while conflicted.

### New

Choose `new` when no route/action satisfies the contract.

Implementation constraints:

- Add the route/action using local TP6 conventions.
- Reuse existing logic only when it fully satisfies the needed behavior.
- Add a new logic method/class when existing logic is close but not semantically identical.
- Add models/validators/transformers only when required by the contract or local pattern.
- Keep controllers thin; put business rules in logic/application classes according to the project style.
- Preserve existing public behavior unless the user explicitly approves a change.

## User Question For Conflicts

Use a direct question:

```text
The endpoint resolves to <Controller>::<action>, but the existing behavior is <observed>. Apifox requires <required>. This would change existing behavior. Should I create a new route/action, split the logic under a new method, or modify the existing behavior?
```
