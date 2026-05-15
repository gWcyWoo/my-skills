# My Explore Protocol

Wire format between a caller and the `my-explore` child agent.

## Request

```text
Intent: <one sentence>

Directions:
  1. <specific question / location to find / fact to verify>
  2. <optional>
  3. <optional>

Anchors: <known file paths or symbols, comma-separated; optional>
Budget: <integer; optional; default 6>
```

Rules:
- Maximum 3 directions.
- Each direction must resolve through code evidence.
- Each direction should fit in at most 2 tool calls.
- `Anchors` are required when the caller already knows relevant files, symbols, or directories.
- Invalid directions include design judgment, broad architecture explanation, and implementation advice.

## Response

JSON only. No markdown fence, prose, heading, or recommendation.

```json
{
  "results": [
    {
      "direction": 1,
      "file": "src/example.ts",
      "lines": "12-34",
      "signature": "export function example(...)",
      "body": "export function example() {\n  return true;\n}"
    }
  ],
  "budget_used": 2,
  "skipped": []
}
```

Rules:
- `body` is verbatim code returned by `extract_code` or the verbatim content of an allowed non-source read.
- `signature` is a declaration line or compact symbol identifier, not interpretation.
- One direction may produce multiple result entries.
- A no-match direction must be represented as:

```json
{"direction": 1, "file": null, "lines": null, "signature": null, "body": null}
```

- Budget exhaustion must list unfetched direction numbers in `skipped`.
- The child never explains, recommends, or appends commentary.
