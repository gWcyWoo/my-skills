# Integration Contract Tests

## Contract Shape

Define behavior before implementation:

| Case | Preconditions | Public input | Output or error | Observable effects | Forbidden effects |
| --- | --- | --- | --- | --- | --- |
| confirmed checkout | stocked product | checkout request | exact confirmation | exact payment request; checkout retrievable | no duplicate charge |

Assert exact contract-significant values. Ignore incidental timestamps, generated values, or internal storage shape unless the approved contract exposes them.

## Good Integration Test

Enter through the public interface, run real owned code, and observe results through public interfaces or an external-boundary recorder.

```typescript
test("valid checkout returns confirmation and charges the exact amount", async () => {
  const paymentBoundary = recordingPaymentBoundary({
    result: { transactionId: "txn-1" },
  });
  const client = await startTestApplication({ paymentBoundary });

  const response = await client.post("/checkouts", {
    productId: "product-1",
    quantity: 2,
  });

  expect(response).toEqual({
    status: 201,
    body: { checkoutId: "checkout-1", status: "confirmed" },
  });
  expect(paymentBoundary.requests).toEqual([
    { amountMinor: 2500, currency: "USD" },
  ]);

  await expect(client.get("/checkouts/checkout-1")).resolves.toEqual({
    status: 200,
    body: { checkoutId: "checkout-1", status: "confirmed" },
  });
});
```

Characteristics:

- Starts from approved preconditions and exact public input
- Uses the public API
- Runs the real owned code path
- Asserts exact observable output and boundary effects
- Verifies persisted behavior through a public read interface
- Survives internal refactors

## Bad Implementation-Detail Test

Do not couple acceptance to internal structure:

```typescript
test("checkout calls paymentService.process", async () => {
  const mockPayment = jest.mock(paymentService);
  await checkout(cart, payment);
  expect(mockPayment.process).toHaveBeenCalledWith(cart.total);
});
```

Red flags:

- Mocking internal collaborators
- Testing private methods
- Asserting on call counts/order
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT
- Reading internal storage instead of observing behavior through the interface
- Using loose assertions when the contract requires an exact value
- Changing the expected result to match the implementation

```typescript
// BAD: Bypasses interface to verify
test("createUser saves to database", async () => {
  await createUser({ name: "Alice" });
  const row = await db.query("SELECT * FROM users WHERE name = ?", ["Alice"]);
  expect(row).toBeDefined();
});

// GOOD: Verifies through interface
test("createUser makes user retrievable", async () => {
  const user = await createUser({ name: "Alice" });
  const retrieved = await getUser(user.id);
  expect(retrieved.name).toBe("Alice");
});
```

## Unit Tests

Unit tests are optional and are not acceptance evidence. Add them only when they provide distinct value for complex pure logic, large combinatorial input spaces, or faster fault localization. Do not add them merely for coverage, and do not use them instead of a required integration contract.
