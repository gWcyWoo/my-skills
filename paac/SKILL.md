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
   - If `description` exists and its trimmed value is non-empty, use it as the required business logic, algorithm, constraints, and process notes.
   - If `description` is absent, null, or empty after trimming, use controller-only mock mode: validate contract inputs in the controller action and return mock data matching the success response schema. Do not create, modify, or call logic/service/model code for business behavior.
   - Stop if required input or response data is missing or ambiguous.

4. Inspect existing code.
   - Use `my-explore-0` for every target-repository evidence read.
   - Load `my-explore-0` rules at most once per conversation. If already loaded, reuse those rules for later exploration passes; do not reread `my-explore-0/SKILL.md`.
   - Do not inspect target-repository files for PAAC evidence outside a `my-explore-0` exploration pass.
   - Required repository evidence is mode-dependent:
     - Controller-only mock mode: routes, target controller/action, contract input validation, response helper, auth/header middleware or config conventions, and minimal integration-test convention/config/command evidence. Do not inspect logic, service, model, or migration files unless the existing target action calls them or route/controller evidence is ambiguous.
     - Non-empty `description` mode: routes, target controller/action, validation, middleware/auth/config, response helpers, behavior-touched logic/service/model/migration files, and minimal test convention/config/command evidence.
   - Maintain a PAAC exploration ledger across passes for the same endpoint:
     - `search_used`: per evidence category
     - `known_candidate_files`: per evidence category
     - `current_evidence_category`
   - A file returned by `search_code`, including files listed under `skipped_files`, is a known candidate file.
   - Once `known_candidate_files` contains a file for `current_evidence_category`, do not use `search_code`, `ast_grep`, native grep, native `rg`, or any pattern search again for that category. Use `extract_code` on candidate files, line windows, or symbols.
   - Never use another search only to reveal a line inside a known candidate file.
   - If a route file is known but the exact route line is unknown, extract likely route-group windows and adjacent windows; do not re-search with different keywords.
   - A new exploration pass does not reset `search_used` for the same endpoint and same evidence category.
   - A later search is allowed only for a genuinely new evidence category with no known candidate file, and the visible hypothesis plan must name the still-unknown category.
   - If the next visible step would be `next: search_code` after a prior search already found candidates for the category, stop and change the next step to `extract_code`.
   - If additional target-repository context is needed, start a new bounded exploration pass under the already-loaded `my-explore-0` rules and carry forward the ledger. Do not reset search permission for the same endpoint or evidence category. Prefer `extract_code` from known candidate files before any new search.
   - If `my-explore-0` cannot obtain required evidence, stop and report the missing evidence. Do not fall back to direct shell reads.
   - Derive the target controller/action from `endpoint`: trim leading/trailing `/`, split by `/`, set controller keyword to `array[-2]`, and set action keyword to `array[-1]`.
   - Convert the controller keyword to StudlyCase and append `Controller`; keep the action keyword as the method name unless the project has a conflicting established naming rule.
   - Example: `api/sms/send` -> `SmsController::send()`.
   - Stop if the endpoint has fewer than two path segments.

5. Decide implementation action.
   - If the endpoint is implemented, reuse it only when HTTP method, inputs, response schemas, and the selected implementation mode match Apifox.
   - In non-empty `description` mode, implementation mode matches only when existing behavior implements the `description`.
   - In controller-only mock mode, implementation mode matches only when the action validates contract inputs and returns mock success data matching the success response schema without business logic/service/model side effects.
   - If any HTTP method, input, response schema, or implementation mode detail differs, update the existing implementation to match Apifox.
   - If the endpoint is not implemented, create the controller when absent, create the action when absent, and implement the contract.
   - In controller-only mock mode, keep implementation inside the controller action except project-required validation helpers or response helpers. Do not add business logic classes, service methods, model queries, persistence side effects, or external side effects.
   - For every reused, updated, or added action with a non-empty Apifox `description`, put the full `description` content in the method header comment immediately above the action method. Normalize only comment syntax required for valid PHP.
   - For controller-only mock mode, do not fabricate method header comment content from an empty `description`; keep only project-required docblock tags if the project requires them, and remove stale business-description comments not present in Apifox.
   - If the implementation matches Apifox but the non-empty `description` method header comment is absent or stale, update only the comment and report the endpoint as reused with a comment update.
   - Edit only files identified by `my-explore-0` or files whose paths are derived directly from the Apifox endpoint and existing project conventions returned by `my-explore-0`.
   - If patch context is insufficient, run another exploration pass under the already-loaded `my-explore-0` rules. Do not reread `my-explore-0/SKILL.md`; do not read the target file directly to obtain patch context.
   - Follow existing project conventions for routes, controllers, validation, auth, responses, exceptions, models, services, dependency injection, and tests.

6. Test.
   - If Step 5 selects reuse with no behavior change and no code change except an optional method-header comment update, skip TDD and report the reuse.
   - Load [tdd-gates.md](references/tdd-gates.md).
   - In controller-only mock mode, write only minimal integration contract tests. Do not write E2E tests, unit tests, or logic/service/model tests.
   - Use `my-explore-0` for test style, fixture, bootstrap, PHPUnit/Pest configuration, helper, middleware, and command-discovery evidence.
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
- Do not read target-repository evidence outside `my-explore-0`.
- Do not write tests before user confirms the test plan.
- Do not claim completion without green confirmed tests, verified reuse with no behavior change, or a concrete environment blocker.
