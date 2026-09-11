# Integration Contract Tests

## Case Record

Use one compact record per distinct behavior in existing task notes or a concise progress update. Record the source, Given/When/Then, Must not, and Catches before writing the test; fill in Evidence immediately after its actual run and before starting another case. The final report may reuse these records, but must not be their first occurrence. No separate document is required just for this template.

```text
Case / source: <requirement, public contract, or confirmed business rule>
Given: <explicit fixture values, starting state, and relevant environment>
When: <public entry point and exact input or operation sequence>
Then: <independently derived output, observable state, and external effects>
Must not: <forbidden outputs or side effects; omit only if none apply>
Catches: <concrete faulty behavior> -> <different observable result for this fixture> -> <detecting assertion>
Evidence: <test path/name; actual RED -> GREEN, EXISTING_GREEN, or BLOCKED>
```

Expected results come from the source and fixture facts. For example, a confirmed unit price of 1250 minor units and quantity 2 establish an expected charge of 2500. Do not call the production total calculator to compute this expectation.

Specify contract-significant values exactly. For opaque generated IDs, assert the required shape and use the returned ID only to correlate later observations. Do not require a particular ID unless its value is part of the contract or explicitly controlled by the fixture.

## Choose Coverage From the Contract

For each applicable row below, map the obligation to an existing or new test. If a listed category does not apply, omit it; do not invent requirements to fill the table.

| Contract characteristic | Cases to consider |
| --- | --- |
| Ordinary valid operation | Representative inputs and the complete observable outcome |
| Input constraints | Relevant valid/invalid equivalence classes; just below, at, and just above a specified threshold |
| State-dependent behavior | Allowed and forbidden transitions from relevant starting states |
| Dependency failure | The specified error, recovery/rollback behavior, and effects that must not occur |
| Repetition, ordering, concurrency, or timing | Required guarantees under the relevant sequence or interleaving, controlled by synchronization or a test clock |
| Bug repair | Every identified reproduction scenario and relevant triggering combination, with the original defect producing the expected failure |

Test one representative per equivalent behavior unless evidence shows that inputs follow different paths. Add combinations when conditions interact or reproduction evidence requires them; do not exhaustively multiply independent dimensions. A normal-case test does not cover a rejection or rollback guarantee.

## Select Fixtures That Separate Correct and Faulty Behavior

For a critical rule, write the contract result and one plausible faulty result for the actual fixture. If they are the same, that fixture does not demonstrate detection of that fault. Choose different values or interacting conditions; a descriptive test name or another assertion on the same result does not close the gap.

- **Calculation order:** when correctness depends on normalization, aggregation, rounding, caps, or thresholds, choose values where doing these operations in the wrong order changes the result. Include interacting inputs when a single input makes both algorithms equivalent. For example, a 10% discount rounded half up on a combined total of `15 + 15` is `3`; rounding each item's discount first gives `2 + 2 = 4`. A case where both methods produce `3` cannot detect that ordering defect. Use the actual task's rules, not these example business values.
- **State and identity interactions:** choose starting states and actors that distinguish the named fault, such as a deadline crossed during an external operation or the same key used by different owners. Separate happy-path tests for the individual rules do not establish their interaction guarantee.

Keep this comparison concise in the existing `Catches` record. Do not invent new requirements or enumerate every conceivable faulty implementation. If executing the chosen fault is needed to resolve uncertainty, use the targeted procedure below.

Parameterized iterations do not necessarily reset fixtures. Give independent cases fresh application state, database, provider records and clock as applicable, so a failed case cannot create misleading failures in later cases. For an intentional sequence, establish and assert the prior state and the outcome of each operation instead of treating its steps as independent cases.

## Worked Contract

This illustrative checkout contract requires:

- Each test starts with its own empty order store and a product priced at 1250 USD minor units. Stock is explicitly set by the case. No tax, discount, or shipping applies.
- A valid quantity is a positive integer. Requesting exactly the available stock is allowed. Success returns `201` and `confirmed`, creates one durable order, decrements stock, and sends exactly one payment request for the total.
- Requesting more than available stock returns `409` with `insufficient_stock`; it creates no order, changes no stock, and sends no payment request.
- The operation's completion signal covers all work that could create these effects. An opaque order ID has no fixed value.

| Case | Given / When | Then / Must not | Concrete defect and detecting assertion |
| --- | --- | --- | --- |
| Exact stock accepted | Stock 2; request 2 | Confirmed; charge 2500 once; one durable order; stock 0 | Rejecting equality fails the success assertion; charging the unit price fails the amount assertion |
| Insufficient stock rejected | Stock 1; request 2 | `409`; no order or payment; stock stays 1 | Returning an error after charging fails the empty payment-record assertion |

These examples demonstrate acceptance and side-effect assertions, not complete coverage of every input rule. The positive-integer constraint still needs its applicable boundary cases before declaring the whole contract covered.

## Integration Examples

The TypeScript below is illustrative, not a runnable test suite. Adapt helpers to the project's real public interfaces and test runner. Their required semantics are explicit:

- `startTestApplication` seeds an isolated real test database with the supplied product and starts the real owned application. It replaces only the external payment service with a recording substitute.
- Each request executes the real public handler. `waitForOperationCompletion` observes a defined completion barrier for request-related work, without an arbitrary sleep.
- `restartWithSameStorage` restarts the application, clears in-memory state, and reconnects to the same isolated database. It retains the external payment recorder. This extra observation is needed here because this example explicitly promises durability.
- Public reads observe orders and stock; `close` releases the application and test resources. These are test-harness capabilities, not requirements to add production endpoints.

```typescript
test("exact stock is accepted, charged once, and persisted", async () => {
  const payment = recordingPaymentBoundary({
    result: { transactionId: "txn-1" },
  });
  const app = await startTestApplication({
    products: [{ id: "product-1", priceMinor: 1250, currency: "USD", stock: 2 }],
    paymentBoundary: payment,
  });

  try {
    const response = await app.client.post("/checkouts", {
      productId: "product-1",
      quantity: 2,
    });
    await app.waitForOperationCompletion();

    expect(response).toEqual({
      status: 201,
      body: { checkoutId: expect.stringMatching(/\S/), status: "confirmed" },
    });
    const checkoutId = response.body.checkoutId;
    expect(payment.requests).toEqual([{ amountMinor: 2500, currency: "USD" }]);

    await app.restartWithSameStorage();
    await expect(app.client.get(`/checkouts/${checkoutId}`)).resolves.toEqual({
      status: 200,
      body: { checkoutId, status: "confirmed" },
    });
    await expect(app.client.get("/checkouts")).resolves.toEqual({
      status: 200,
      body: [{ checkoutId, status: "confirmed" }],
    });
    await expect(app.client.get("/products/product-1/stock")).resolves.toEqual({
      status: 200,
      body: { stock: 0 },
    });
  } finally {
    await app.close();
  }
});

test("insufficient stock rejects without any order, stock, or payment effect", async () => {
  const payment = recordingPaymentBoundary({
    result: { transactionId: "txn-1" },
  });
  const app = await startTestApplication({
    products: [{ id: "product-1", priceMinor: 1250, currency: "USD", stock: 1 }],
    paymentBoundary: payment,
  });

  try {
    const response = await app.client.post("/checkouts", {
      productId: "product-1",
      quantity: 2,
    });
    await app.waitForOperationCompletion();

    expect(response).toEqual({
      status: 409,
      body: { error: "insufficient_stock" },
    });
    expect(payment.requests).toEqual([]);
    await expect(app.client.get("/checkouts")).resolves.toEqual({
      status: 200,
      body: [],
    });
    await expect(app.client.get("/products/product-1/stock")).resolves.toEqual({
      status: 200,
      body: { stock: 1 },
    });
  } finally {
    await app.close();
  }
});
```

## Verify Defect Sensitivity

For the rejection case, name the possible defect: "returns `409` but still sends a payment request." The status assertion cannot detect it; the empty payment-record assertion can.

When this detection is uncertain and existing RED or regression evidence does not resolve it:

1. In an isolated test environment, temporarily make the real rejection path send a payment request while preserving the `409` response.
2. Run the rejection test. It must fail on the payment assertion, not on setup or the status code. A passing test means the guarantee remains unverified.
3. Remove only the injected fault, preserve unrelated work, and rerun the test to confirm GREEN. If it still fails, investigate rather than weakening the assertion.

Do not apply mutation testing to every case by default. This targeted check closes a specific uncertainty. A fault that never reaches the tested path provides no detection evidence.

## Weak Tests and Repairs

| Weak test | Why it can mislead | Repair |
| --- | --- | --- |
| Expected total comes from the production calculator | The same error can appear in actual and expected values | Derive the expected total from contract and fixture facts |
| Only asserts an error response | Forbidden writes or outbound requests can still occur | Assert the required absence of state and external effects after completion |
| Mocks the owned checkout service | The business behavior is never exercised | Call the real public entry point and replace only the external payment boundary |
| Checks only that a result or stored record exists | Wrong values or duplicate operations can pass | Assert contract-significant values and required multiplicity |
| Hard-codes an incidental ID or asserts private helper calls | Correct behavior can fail after an internal refactor | Assert ID constraints and public behavior; correlate observations with the returned ID |
| Uses unawaited assertions, swallowed errors, or conditional early returns | The runner can report success without evaluating the requirement | Await completion and assertions; let unexpected failures fail the test |
| Reads immediately or sleeps before asserting no effect | Delayed work may escape the assertion | Observe the defined completion barrier or controlled scheduling point |
| Claims durability from an immediate read in the same process | A cache can hide missing persistence | When durability is required, read through a fresh context backed by the real store |

External request counts or ordering may be asserted when the contract requires them, such as exactly one charge. Incidental internal call counts and private implementation structure are not acceptance criteria.

Unit tests remain optional under the test-layer policy in `SKILL.md`; they do not replace a required integration contract.
