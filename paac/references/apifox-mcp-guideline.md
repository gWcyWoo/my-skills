# Apifox MCP Guideline

Use Apifox MCP tools by capability. Do not hard-code session-generated suffixes such as `_f9hi2e` or `_pkg6eb`.

Required tool families:

1. `refresh_project_oas_*`: refresh the OAS cache from Apifox server data.
2. `read_project_oas_*`: read the OpenAPI root file.
3. `read_project_oas_ref_resources_*`: read `$ref` resources.

Required call pattern:

```text
refresh_project_oas_*
read_project_oas_*
refresh_project_oas_*
read_project_oas_ref_resources_* for the endpoint path resource
refresh_project_oas_*
read_project_oas_ref_resources_* for nested component/schema/response resources
```

Root OAS usage:

- Locate the requested `endpoint`.
- Identify the HTTP `method`.
- Identify the endpoint operation `$ref`.
- Identify component `$ref` entries needed by the endpoint.

Referenced resource usage:

- Read `description`.
- Read path, query, header, body, and `requestBody` parameters.
- Read success and error `responses`.
- Read `security`.
- Read examples if present.

Rules:

- Refresh before any Apifox read.
- Do not rely on top-level `paths` data when an operation `$ref` exists.
- Stop if the requested endpoint is absent.
- Stop if multiple interfaces match the request.
- Stop if a required `$ref` cannot be read.
