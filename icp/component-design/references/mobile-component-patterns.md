# Mobile component morphology knowledge

This document is an advisory inference prior for ICP component design. It helps
recognize common Android and iOS component shapes; it is not a source of product
requirements.

## Authority and use

1. The same page's UI, interaction, interface, acceptance, and other description
   columns define business meaning and behavior. When they conflict with a design,
   the description wins.
2. Verified design Blocks and source nodes define visual structure, containment,
   order, and placeholder geometry.
3. This document may suggest a component boundary, kind, slots, and ordinary state
   questions. It must never invent a business rule, transition, validation limit,
   navigation target, API, persistence rule, copy, or platform implementation.
4. A familiar shape is not proof of reuse. Shared extraction still needs repeated
   candidate evidence, verified history, or an exact same-page business-source
   declaration that the candidate is a shared component.
5. Record the narrowest boundary supported by the sources. If signals are
   ambiguous, keep the candidate local and preserve the ambiguity for review.
6. This stage produces semantic component data only. It does not select UIKit,
   SwiftUI, Jetpack Compose, Android Views, libraries, classes, or code.

## Recognition catalogue

### pattern:screen-shell — Screen or page shell

- Signals: one full viewport root, system-safe top/bottom regions, a main content
  area, and optional persistent navigation or overlay anchors.
- Typical boundary: `page`; usually a container with named content/navigation/
  overlay slots when those children vary by page.
- Ask from sources: which children persist, which scroll, and which overlay the
  page. Never infer navigation or lifecycle behavior from the shell alone.

### pattern:top-app-bar — Android top app bar / iOS navigation bar

- Signals: leading back/menu action, centered or leading title, trailing actions,
  fixed top placement.
- Typical boundary: `component`; complete when only title/actions vary through
  roles, container when page-specific content is embedded.
- Common states: normal, scrolled/elevated, contextual. Only include a state when
  the design or description proves it.

### pattern:bottom-navigation — Android bottom navigation / iOS tab bar

- Signals: persistent bottom row of peer destinations, icon-label items, one
  selected item, and selection emphasis. It switches top-level destinations; it
  is not a row of unrelated page actions.
- Typical boundary: `component`; often complete with item data and selection
  actions. Treat the surrounding screen as a separate page/container.
- Common states: selected, unselected, optional badge, disabled only when sourced.
- Do not infer destination persistence, reselection behavior, or back-stack rules.
  Do not merge a one-off bottom action bar into this pattern.

### pattern:tabs — Tabs / segmented control

- Signals: peer views within one destination, a selected indicator, and content
  switching below or beside the control.
- Typical boundary: control as a complete component; content host as a container
  only when the source proves swappable child content.
- Distinguish from bottom navigation by scope: tabs change local content; bottom
  navigation changes top-level destinations.

### pattern:bottom-sheet — Modal or persistent bottom sheet / bottom drawer

- Signals: surface attached to the bottom edge, rounded upper corners, backdrop or
  drag handle, partial/full expansion, close action, and content above the page.
- Typical boundary: `component`; extract the sheet frame as a shared container
  when business-specific bodies differ, or a complete component when structure and
  behavior are invariant and only declared data/actions vary.
- Common states to look for: hidden, presented, expanded/collapsed, dragging,
  dismissing. Include only sourced states and behavior.
- Android commonly calls this a bottom sheet. iOS commonly calls the analogous
  presentation a sheet. A product description may call it a bottom drawer; retain
  the product term while mapping it to this morphology.
- Do not confuse it with a side navigation drawer or a centered modal dialog.

### pattern:navigation-drawer — Side navigation drawer

- Signals: panel entering from a side edge, navigation destinations, optional
  scrim, and a menu affordance.
- Typical boundary: shared container or complete navigation component depending on
  whether arbitrary business content or declared destination data is supplied.
- Do not infer gesture dismissal, edge-swipe behavior, or destination changes.

### pattern:modal-dialog — Modal dialog / alert

- Signals: centered or platform-positioned bounded surface above a scrim, explicit
  decision or acknowledgement actions, and focus isolated from the underlying page.
- Typical boundary: complete for stable alert semantics; container when an outer
  modal frame receives materially different business content.
- Common states: presented, action pending, dismissed; error/loading only when
  sourced.
- A modal is a presentation relationship, not proof that all modal contents share
  one business component.

### pattern:popover-menu — Popover, contextual menu, action sheet

- Signals: transient choices anchored to an element or presented as a compact
  action surface. iOS action sheets and Android menus may differ visually while
  serving the same semantic choice boundary.
- Typical boundary: complete component with item data/action roles when choices
  share one stable responsibility.
- Do not treat a general bottom sheet containing complex business content as a
  simple action menu.

### pattern:card — Card or grouped surface

- Signals: bounded background, radius/elevation/stroke, internal padding, and a
  coherent group of related content.
- Typical boundary: shared container when the surface frames arbitrary business
  content; complete when internal structure is invariant and values vary as data.
- A rectangle alone is not a card. Confirm semantic grouping and child ownership
  from Blocks and descriptions.

### pattern:list — List / collection and list item

- Signals: repeated sibling rows or tiles with a stable internal layout and data
  variation.
- Typical boundary: list container plus repeated complete item component. Keep
  empty/loading/error/pagination states separate and only when sourced.
- Similar appearance without repeated semantics is not proof of one item type.

### pattern:form — Form and field group

- Signals: labelled inputs, validation/supporting text, ordering, and a submit or
  continuation action.
- Typical boundary: form as a page-local container; independently reusable field
  shapes may be complete components when their behavior contract is stable.
- State questions: empty, focused, populated, invalid, disabled, submitting.
  Never invent validation, formatting, keyboard, or submission rules.

### pattern:text-input — Text, phone, OTP, search, and masked input

- Signals: editable value, label/placeholder, caret/focus affordance, supporting or
  error content, leading/trailing actions.
- Typical boundary: complete only when value, state, validation/action roles, and
  editing behavior are explicitly modeled. A phone mask, OTP field, and generic
  text field are not automatically the same component.
- Android/iOS keyboard and cursor conventions are defaults for implementation,
  not stage-2 business facts unless the description explicitly requires them.

### pattern:selection-control — Picker, dropdown, radio, checkbox, switch

- Signals: a bounded choice set or binary state and a clear selected value.
- Typical boundary: complete component with value data and change action roles.
- Distinguish presentation (dialog, bottom sheet, inline menu) from the selection
  control's business responsibility.

### pattern:file-upload — File/image upload control

- Signals: add/select affordance, file previews or rows, progress, success/error,
  retry, remove, and multiplicity cues.
- Typical boundary: complete upload component when the functional contract is
  stable; keep file purpose, endpoint, limits, and business copy as instance data.
- Never infer allowed types, limits, compression, permissions, or retry behavior.

### pattern:feedback-message — Snackbar, toast, banner, inline message

- Signals: transient or persistent status copy with optional action and severity.
- Typical boundary: complete presentation component if duration, placement, action,
  and dismissal are part of a common sourced contract.
- Distinguish Android snackbar/toast, iOS banner/alert, and inline validation by
  placement, interaction, persistence, and ownership rather than by wording alone.

## Boundary checklist

For every candidate, answer only from available evidence:

1. Is this a page, section, complete component, or outer container?
2. Which design Blocks belong to it, and do parent-child relations support the
   proposed boundary?
3. Which sourced behaviors and states belong to this candidate rather than its
   parent or child?
4. If shared, is it an outer frame with slots or a complete component whose
   business variation fits declared data/action roles?
5. Is the reuse claim proven inside one page, across pages, by verified history,
   or by an exact business-source shared-component declaration?
6. Which familiar-pattern assumptions were considered and rejected because the
   sources did not prove them?
