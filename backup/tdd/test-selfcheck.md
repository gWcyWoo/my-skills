# Step 6: Test Self-Check Table

Output this table for ALL tests before proceeding. Every cell must have a concrete answer. Any ❌ must be fixed and the row re-filled before moving on.

| # | Test Name | Hollow? | Assertion specific? | Mock-as-SUT? | Outcome verified? | Independent? | Requirement scenario proved? |
|---|---|---|---|---|---|---|---|
| 1 | [name] | No — fails without impl / ❌ Yes | Asserts [specific value] / ❌ toBeTruthy only | No — SUT is real / ❌ SUT mocked | [what state/output is checked] / ❌ call count only | No shared state / ❌ depends on test N | "When X happens, user sees Y" / ❌ vague or none |

**Column definitions:**
- **Hollow?** — If implementation is deleted, does this test fail? Must be NO.
- **Assertion specific?** — Asserts a concrete value, not just truthiness/existence. Must pass.
- **Mock-as-SUT?** — Is the code under test itself mocked? Must be NO. Only external boundaries (DB, HTTP, time) may be mocked.
- **Outcome verified?** — At least one `expect` checks a state/output/side-effect, not just a mock call count. Must pass.
- **Independent?** — Test passes or fails regardless of execution order and shared state. Must be YES.
- **Requirement scenario proved?** — Quote or reference the specific requirement sentence from Step 3 that this test proves. "Covers auth" is not acceptable — must name the exact user-visible outcome. If you cannot point to a requirement sentence, the test is testing implementation details, not requirements.

**After the table — Requirement Coverage Check (MANDATORY):**

List every requirement scenario identified in Step 3. For each, confirm at least one test in the table maps to it:

```
Requirement scenario 1: [quote from Step 3] → covered by test #N
Requirement scenario 2: [quote from Step 3] → covered by test #N, #M
Requirement scenario 3: [quote from Step 3] → ❌ NO TEST — must add
```

Any scenario with ❌ NO TEST = a missing test case. Add it, re-run Step 5, update the table. **This check cannot be skipped or answered vaguely. Every requirement scenario must have at least one concrete test.**

**Also verify (not per-test, but before proceeding):**
- No CSS class, inline style, or snapshot assertions anywhere in the test file
- Non-deterministic values (UUID, timestamp, random) use `mockImplementation`, not fixed `mockResolvedValue`
- All tests from Step 2 impact analysis have been migrated

The table and coverage check must both be fully green before proceeding to review.
