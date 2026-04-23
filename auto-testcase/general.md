# General Test Rules

Rules that apply to ALL test types (unit, integration, e2e). Loaded before any test code is written.

## 1. No Test-Only Identifier Dependency

Test cases MUST NOT depend on framework-specific test-only identifiers such as React Native `testID` or web `data-testid` when a stable semantic query is available. These identifiers couple the test to implementation details and can pressure the implementation to add test hooks solely to satisfy tests. Prefer semantic queries (`getByText`, `getByRole`, `getByLabelText`) or other stable, user-facing selectors first.

## 2. Verify Test Framework API Before Writing Tests

Before writing the first test in a project, or when encountering unfamiliar test failures, create a minimal debug test to verify:

- What the render helper returns (`render()` or framework equivalent)
- How the interaction helper works (`fireEvent`, `userEvent`, or framework equivalent)
- How the rendered tree is structured (mock wrapper layers, parent/child depth)
- Whether manual event or prop calls (e.g., `onLayout`, `onScroll`, or framework equivalents) trigger state updates

Do NOT assume APIs exist based on documentation or older version experience. The actual behavior depends on the specific combination of test-library version, framework version, and test environment.

### Quick verification pattern

Adapt the exact component syntax to your framework. The point is to inspect the real render helpers and tree shape in the current test environment before writing the real tests.

```tsx
it("verify render API", () => {
  const result = render(
    <div>
      <span>Hi</span>
    </div>
  );
  // Force-fail to inspect: expect(Object.keys(result).join(", ")).toBe("SHOW");
  // Check tree depth: expect(screen.getByText("Hi").parentElement?.tagName).toBe("SHOW");
});
```

Run once, inspect output, then delete. This takes 30 seconds and prevents hours of debugging.
