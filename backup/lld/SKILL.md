---
name: lld
description: Use when HLD is confirmed and internal logic, data transformations, or complex branching within a module need detailing. Produces logic contracts for unit tests and implementation.
---

# Detailed Level Design (LLD)

Produces a logic contract that `testcase unit` and `code` consume directly. Every element in the output must be actionable: a path becomes an `it()` block, a boundary row becomes a test fixture, an implementation note becomes code.

## 1. Input Constraint

**The sole inputs are the confirmed `understand` output (Micro Analysis + AC IDs) and the confirmed `hld` output (signatures + interfaces).** All logic design must be scoped strictly to these.

- Architectural gap (interface mismatch) → return to `hld`.
- Requirement gap (missing logic) → return to `understand`.

## 2. Process

### Step 1: Identify Logic Units

For each HLD function signature, classify it:

| Classification | Definition | Implication |
|---|---|---|
| **Branching Logic** | Has if/else, switch, ternary, or error handling | Full path enumeration required |
| **Pure Mapper** | Zero conditional branches, only field assignment/formatting | Exactly 1 test case (per `testcase unit` §4 Branch-Free Pure Mapper rule) |
| **State Transition** | Manages state changes based on events/inputs | State transition table required |

Skip functions that are pure delegation (call another function, return result) — these are tested at integration level, not unit.

### Step 2: Design Each Logic Unit

For each logic unit identified in Step 1, produce the sections below. **NO implementation code.** Define ONLY: logic flow descriptions, data mapping, error conditions, boundary values. Do NOT write loops, variable assignments, or code bodies.

#### 2a. Logic Path Table

Every row = one testable path = one future `it()` block.

```
| Path ID | AC ID | Type | Condition | Expected Outcome | Mock |
|---------|-------|------|-----------|------------------|------|
| LU1-P1 | AC-01 | Success | valid input with all fields | returns transformed result | none |
| LU1-P2 | AC-01 | Exception | API returns error code 4xx | throws ValidationError | fetch (1) |
| LU1-P3 | AC-02 | Boundary | input array is empty | returns empty array | none |
```

Rules:
- **AC ID**: Every path MUST trace to an AC ID from `understand`. No orphan paths.
- **Type**: Success / Exception / Boundary — one of three, no other types.
- **Mock**: `none` or the single dependency name. If >1 mock needed → STOP, return to HLD to decouple.
- **Path ID format**: `LU{n}-P{m}` where n = logic unit number, m = path number.

#### 2b. Data Mapping Table (for mappers/transformers only)

```
| Source (Input) | Target (Output) | Transform | Conditional? |
|---|---|---|---|
| `user_id` | `author.id` | direct assignment | N |
| `created_at` | `date` | timestamp → ISO 8601 string | N |
| `status` | `badge` | map: 1→"active", 2→"inactive", _→"unknown" | Y |
```

- **Conditional? = N** for all rows → this is a Pure Mapper → 1 test case total.
- **Conditional? = Y** for any row → each conditional mapping needs its own path in §2a.

#### 2c. Boundary Value Matrix (for branching logic)

Per-parameter specification. Each row = one test fixture.

```
| Path ID | Parameter | Boundary Type | Input Value | Expected |
|---------|-----------|---------------|-------------|----------|
| LU1-P3 | items | empty | [] | returns [] |
| LU1-P4 | items | null | null | throws TypeError |
| LU1-P5 | count | min | 0 | returns empty result |
| LU1-P6 | count | min-1 | -1 | throws RangeError |
| LU1-P7 | name | empty string | "" | uses fallback "Anonymous" |
```

Boundary types: `null` / `undefined` / `empty` / `min` / `max` / `min-1` / `max+1` / `malformed`.
Only include boundaries that trigger **different behavior** (different branch). Do not test boundaries that follow the same path.

#### 2d. State Transition Table (for state logic only)

```
| Current State | Event/Input | Next State | Side Effect | Path ID |
|---|---|---|---|---|
| idle | submit | loading | call API | LU2-P1 |
| loading | success | done | update store | LU2-P2 |
| loading | error | failed | set error msg | LU2-P3 |
```

### Step 3: Present Output

```
---
## Detailed Level Design (LLD)

### Logic Units Summary
| # | Function (from HLD) | Classification | Branch Count | Purity | Path Count |
|---|---|---|---|---|---|
| LU1 | `transformUser(raw: RawUser): User` | Pure Mapper | 0 | Pure (0 mock) | 1 |
| LU2 | `validateOrder(order: Order): Result` | Branching Logic | 4 | 1-Dep: orderRepo | 5 |

### LU1: transformUser
#### Logic Paths
| Path ID | AC ID | Type | Condition | Expected Outcome | Mock |
|---|---|---|---|---|---|
| LU1-P1 | AC-01 | Success | fully populated RawUser | returns complete User object | none |

#### Data Mapping
| Source | Target | Transform | Conditional? |
|---|---|---|---|
| ... | ... | ... | N |

### LU2: validateOrder
#### Logic Paths
| Path ID | AC ID | Type | Condition | Expected Outcome | Mock |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

#### Boundary Values
| Path ID | Parameter | Boundary Type | Input Value | Expected |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

**Is this logic design correct? Please confirm before proceeding.**
---
```

## 3. STOP Condition

**STOP HERE.** Do NOT proceed to test code or implementation. Wait for user confirmation.

After confirmation, this LLD serves as direct input for:
- **`testcase unit`**: Each Logic Path row → one `it()` block. Boundary Value rows → test fixtures. Purity column → mock strategy.
- **`code`**: Each Logic Path → one code branch to implement. Data Mapping → transformation implementation. State Transition → state machine implementation.
