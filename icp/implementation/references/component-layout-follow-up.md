# Component layout follow-up work

This file records the stage responsibilities deliberately excluded from the pure
position/layout algorithm and how ICP now owns them.

## Implemented design-fact projection

- Stage 3 `design_facts` preserves component-bound color, background, border, radius, typography, and
  asset relations so later code generation never has to rejoin upstream data.
- `design_facts` is the single authoritative projection from bound Stage 1 facts
  into Stage 3; reference assertions and codegen packets consume it.

## Implemented assertion execution and runtime collection

- Each assertion carries a closed evaluation operator executed by one validator.
- Responsive snapshots freeze the viewport coordinate space, required measurements, scroll
  semantics, system-bar/safe-inset measurements, conditional/repeated component
  presence, and device capture responsibilities.
- Runtime collection provides measurements and rejects self-certification
  with authored `clipped`, `operable`, or similar pass/fail booleans.
- The production assertion executor consumes the algorithm's explicit
  horizontal-scroll overflow scopes, including every recorded component
  descendant, instead of rebuilding that relationship from UI framework nodes.

## Implemented stage contract ownership

- Stage 2 validates the complete non-geometric component/page schema and freezes
  component-bound `layout_inputs`. The position algorithm validates only the geometry,
  component topology, Block ownership, and content-role facts it consumes.
- The stage contract and reference documentation use `layout_inputs`,
  `layout_selection_inputs`, `layout_decisions`, and `layout_contracts` directly;
  no compatibility or routing layer was added.

## Implemented execution safety

- Component-tree and overflow-subtree walks are iterative; source-parent,
  semantic-Block, assertion-expression, input nesting, and canonicalization
  traversals are bounded so malformed inputs cannot escape as raw recursion
  failures. This is execution
  safety around the algorithm, not a position-policy decision.

## Resolved standalone boundary work

The standalone module and its focused tests now cover:

- recursive rejection of forbidden upstream/codebase field names before selector
  invocation;
- fail-closed slot, coordinate-space, logical-size, Block membership, and Block
  partition containers;
- rectangle validation for `union` and a deterministic expression-depth bound;
- total contract-error detail rendering for non-JSON selector values;
- finite-number overflow rejection and public verifier contract/snapshot guards.

## Implemented model retry orchestration

- The algorithm returns deterministic structured contract errors. Stage 3
  aggregates the complete cross-page problem set, records at most three failed
  whole-page attempts, and then requires an owning-stage repair. The pure
  algorithm never schedules a model.
