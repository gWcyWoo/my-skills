# Boundary Substitutes

Run real code inside the owned system. Substitute only dependencies outside its ownership boundary:

- External APIs (payment, email, etc.)
- Time/randomness
- File system (sometimes)
- Databases only when they are outside the owned system; otherwise prefer an isolated real test database

Don't mock:

- Your own classes/modules
- Internal collaborators
- Anything you control

When an outbound interaction is part of the contract, use a recording substitute and assert the exact contract-significant request. Do not assert internal calls merely because they are convenient to observe.

## Designing Boundary Interfaces

At system boundaries, design interfaces that are easy to mock:

**1. Use dependency injection**

Pass external dependencies in rather than creating them internally:

```typescript
// Easy to mock
function processPayment(order, paymentClient) {
  return paymentClient.charge(order.total);
}

// Hard to mock
function processPayment(order) {
  const client = new StripeClient(process.env.STRIPE_KEY);
  return client.charge(order.total);
}
```

**2. Prefer SDK-style interfaces over generic fetchers**

Create specific functions for each external operation instead of one generic function with conditional logic:

```typescript
// GOOD: Each function is independently mockable
const api = {
  getUser: (id) => fetch(`/users/${id}`),
  getOrders: (userId) => fetch(`/users/${userId}/orders`),
  createOrder: (data) => fetch('/orders', { method: 'POST', body: data }),
};

// BAD: Mocking requires conditional logic inside the mock
const api = {
  fetch: (endpoint, options) => fetch(endpoint, options),
};
```

The SDK approach means:
- Each mock returns one specific shape
- No conditional logic in test setup
- Easier to see which endpoints a test exercises
- Type safety per endpoint

Boundary substitutes must not recreate owned business logic. Keep them deterministic, return only the external result needed by the case, and expose recorded requests for contract assertions.
