# Android Kotlin implementation prior

This file is advisory only. Same-page UI, interaction, API, UT, IT, and E2E
descriptions are the authority for business behavior. The verified design Blocks
are the authority for visual hierarchy, geometry, treatment, and assets. Use the
rules below only for platform mechanics that those sources leave unspecified.

## Architecture

- Give each page one page DTO and one explicit UI-state model. Rendering consumes
  the DTO/UI state, never transport response objects directly.
- Adapt both remote responses and local mock fixtures into the same page DTO.
  When no endpoint exists, keep the transport adapter replaceable; do not invent
  an endpoint, request field, validation rule, or success result.
- Keep navigation, modal, drawer, and component presentation relations exactly as
  frozen by Component Design. A relation from page A does not add a rule to page B.
- Keep reusable structure in shared composables. Keep page-specific facts, data,
  actions, validation, and state in the page instance or its state holder.

## Compose selection

- Prefer Material 3 primitives whose semantics match the frozen component shape:
  `NavigationBar`, `NavigationDrawer`, `ModalBottomSheet`, `AlertDialog`,
  `Scaffold`, `LazyColumn`, `TextField`, and `Button`. Style them to the verified
  design; familiarity alone does not create behavior.
- Use a container composable with slots when only the outside frame is shared.
  Use a complete shared composable when structure and behavior are invariant and
  business data/actions can be supplied as parameters.
- Preserve system bars and IME insets. Keep touch targets accessible without
  changing the visible design footprint when the artwork is smaller.

## Responsive layout

- Derive layout from available constraints and insets. Prefer `Modifier` chains,
  weights, intrinsic wrapping, `BoxWithConstraints`, window-size classes, and
  lazy/scroll containers over screen-specific absolute coordinates.
- Exact source dimensions may define local element size and aspect ratio, but not
  fixed text, card, section, page, or whole-screen geometry. Every component must
  be constraint-driven and content-adaptive. Text must wrap or reflow without
  clipping at the supported compact and expanded widths. Never branch layout by
  locale, copy ID, sample text, or screenshot state.
- Treat each ordered design state as evidence for the same page or an explicit
  state transition. Do not combine screenshots into one impossible layout.

## Tests and evidence

- Create every frozen integration case from its declared source: exact `IT`, exact
  interaction description, or model inference over one component's complete
  semantic contract. Keep documented sources separate and add one inferred
  component-contract scenario per component instance. Every case must fail before
  implementation and pass afterward using the same test command.
- Test page DTO mapping with mock data, state transitions, validation, back/edit
  behavior, navigation, modal/drawer visibility, and API adapter boundaries when
  their same-page facts exist.
- Build/lint success proves executability, not visual fidelity. Compact and
  expanded runtime evidence proves natural text reflow, no clipping, overlap, or
  horizontal overflow, reachable content, operable controls, correct system bars,
  and safe insets. At the exact reference viewport, color, component structure,
  spacing, and font-size checks own pass/fail. Whole-image MAE is diagnostic only;
  interaction tests own behavior-driven state when a static artboard differs.
