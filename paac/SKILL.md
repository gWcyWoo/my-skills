---
name: paac
description: Use when implementing, verifying, or reusing one ThinkPHP 6 API endpoint from the latest Apifox MCP interface contract.
---

# PAAC

## Workflow

Scope: handle exactly one Apifox interface unless the user explicitly expands scope.

1. Read Apifox.
   - Load [apifox-mcp-guideline.md](references/apifox-mcp-guideline.md).
   - Refresh OAS before every Apifox data read.
   - Read the OpenAPI root file.
   - Read the endpoint `$ref` resource.
   - Read nested `$ref` resources required to resolve request and response schemas.
   - Stop if Apifox MCP is unavailable, refresh fails, read fails, or more than one interface matches the requested endpoint.
   - Do not use cached, remembered, or inferred Apifox data.

2. Extract the implementation contract.
   - `endpoint`
   - HTTP `method`
   - path, query, header, body, and `requestBody` parameters
   - success response schema
   - error response schemas
   - `description`

3. Interpret the contract.
   - Implement `endpoint` with HTTP `method`.
   - Accept only externally supplied path, query, header, body, and `requestBody` fields defined by the contract.
   - Use framework-provided context, such as authenticated user or request object, only when existing project conventions require it; do not expose those fields as additional API inputs.
   - Return data matching the contract response schemas.
   - Use `description` as the required business logic, algorithm, constraints, and process notes.
   - Stop if required behavior, input, or response data is missing or ambiguous.

4. Inspect existing code.
   - Use `my-explore-0` before reading target-repository code.
   - Derive the target controller/action from `endpoint`: trim leading/trailing `/`, split by `/`, set controller keyword to `array[-2]`, and set action keyword to `array[-1]`.
   - Convert the controller keyword to StudlyCase and append `Controller`; keep the action keyword as the method name unless the project has a conflicting established naming rule.
   - Example: `api/sms/send` -> `SmsController::send()`.
   - Stop if the endpoint has fewer than two path segments.

5. Decide implementation action.
   - If the endpoint is implemented and HTTP method, inputs, response schemas, and `description` behavior all match Apifox, reuse it and report the controller/action.
   - If the endpoint is implemented and any of HTTP method, inputs, response schemas, or `description` behavior differs, update the existing implementation to match Apifox.
   - If the endpoint is not implemented, create the controller when absent, create the action when absent, and implement the contract.
   - For every reused, updated, or added action, put the full Apifox `description` content in the method header comment immediately above the action method. Normalize only comment syntax required for valid PHP.
   - If the implementation matches Apifox but the action method header comment is absent or stale, update only the comment and report the endpoint as reused with a comment update.
   - Follow existing project conventions for routes, controllers, validation, auth, responses, exceptions, models, services, dependency injection, and tests.

6. Use TDD.
   - Load [tdd-gates.md](references/tdd-gates.md).
   - Present the test plan and stop for user confirmation.
   - Write only confirmed tests.
   - Run the smallest relevant test command and require a valid red result.
   - Implement the minimum code required by the confirmed tests.
   - Run the red tests again, related tests, and the smallest relevant regression suite.

7. Report.
   - Controller/action.
   - Reused, updated, or added endpoint.
   - Files changed.
   - Test commands and results.
   - Concrete blocker details if tests cannot run or cannot pass.

## Boundaries

- Do not implement more than one Apifox interface unless the user expands scope.
- Do not fabricate Apifox fields.
- Do not skip Apifox refresh before reading data.
- Do not read target-repository code before `my-explore-0`.
- Do not write tests before user confirms the test plan.
- Do not claim completion without green confirmed tests or a concrete environment blocker.
