# General Test Rules

Rules that apply to ALL test types (unit, integration, e2e). Loaded before any test code is written.

## 1. No testID Dependency

Test cases MUST NOT depend on `testID` props. Using `testID` in tests couples the test to implementation details and forces implementation code to add testIDs just to satisfy tests. Instead, use semantic queries (`getByText`, `getByRole`), rendered tree structure analysis, or style/prop inspection.

## 2. Verify Test Framework API Before Writing Tests

Before writing the first test in a project (or when encountering unfamiliar test failures), create a minimal debug test to verify:

- What `render()` returns (available methods and properties)
- How `fireEvent` works (callable function vs object with named methods)
- How the rendered tree is structured (mock wrapper layers, parent/child depth)
- Whether manual prop calls (e.g., `onLayout`, `onScroll`) trigger state updates

Do NOT assume APIs exist based on documentation or older version experience. The actual behavior depends on the specific combination of test library version, React version, and test environment.

### Quick verification pattern

```tsx
it("verify render API", () => {
  const result = render(<View><Text>Hi</Text></View>);
  // Force-fail to inspect: expect(Object.keys(result).join(", ")).toBe("SHOW");
  // Check tree depth: expect(screen.getByText("Hi").parent?.type).toBe("SHOW");
});
```

Run once, inspect output, then delete. This takes 30 seconds and prevents hours of debugging.
