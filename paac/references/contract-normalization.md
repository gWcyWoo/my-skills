# Contract Normalization

Use this reference when an Apifox response is tool-specific, large, nested, or ambiguous.

## Tool Discovery

Discover Apifox tools from the current environment instead of assuming names. Prefer tools whose name or description mentions Apifox, API detail, interface detail, endpoint, schema, project, folder, or collection.

If multiple tools are relevant:

1. Use search/list tools to locate the requested interface.
2. Use detail/schema tools to fetch the full interface.
3. Use project/folder tools only to disambiguate.

If the user-provided Apifox identifier matches multiple interfaces, stop and ask for the exact interface.

## Required Fields

Normalize into this shape before touching code:

```text
ApiContract
- source: Apifox project/interface identifier or URL
- method: GET|POST|PUT|PATCH|DELETE|...
- endpoint: path without host unless host matters
- title/name:
- description:
- auth: none|required|unknown, plus scheme when present
- request:
  - path params: name, type, required, description/example
  - query params: name, type, required, description/example
  - headers: name, type, required, description/example
  - body: content type, object schema, required fields, examples
- response:
  - success status and schema
  - error statuses and schemas
- field notes: enum values, formats, defaults, nullability, constraints
```

## Interpretation Rules

- Treat `description` as business intent, not executable truth.
- Treat field descriptions, examples, enums, and error schemas as contract constraints.
- Record missing or ambiguous auth, validation, status code, pagination, and error behavior.
- Infer only when the codebase has a consistent matching convention.
- Ask the user when contract ambiguity would change behavior or data shape.

## Output

Keep the checkpoint concise. Include only fields needed to decide route mapping, implementation behavior, and tests.
