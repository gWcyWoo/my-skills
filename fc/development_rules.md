# FC Development Rules

These rules are project/developer rules for `fc`. They override `flutter-widget.md` when there is a conflict.

## DEV-RESPONSIVE-PAGE

- Generated pages must be adaptive.
- Do not fix page/root width or height from the UI artboard.
- Do not set a fixed max width from the design artboard; page width follows runtime parent constraints.
- Do not cap page height from the design artboard; body content scrolls when taller than the viewport.
- Use the artboard as design evidence only; runtime layout must follow parent constraints, viewport, and scroll model.

## DEV-PAGE-SCAFFOLD

- Page root must use `Scaffold`.
- Put the main page content in `Scaffold.body`.
- Do not generate design mock status-bar elements such as date/time, network signal, carrier, Wi-Fi, or battery indicators.

## DEV-PAGE-APPBAR

- If the design has a top navigation area with a page title, back button, close button, or top actions, prefer `Scaffold.appBar`.
- Do not implement a normal page navigation bar as a body-local header only for coordinate fidelity.
- Use a body-local custom header only when the spec shows custom overlap, transparent/immersive header, collapsing behavior, or visual structure that `AppBar` cannot express.
- If not using `Scaffold.appBar` for a title/back navigation area, record `DEV 例外` with reason, risk, mitigation, and user confirmation.

## DEV-PAGE-SCROLL-BODY

- Page body height is not fixed to the design artboard height.
- Use `SingleChildScrollView` for the generated page body scroll layout.
- Inside `SingleChildScrollView`, use a finite `Column` for static/spec-derived page sections.
- Do not use independent absolute heights to force the body to match the design artboard.

## DEV-BOTTOM-PERSISTENT

- If bottom content must remain visible while the body scrolls, place it in `Scaffold.bottomNavigationBar`.
- Do not place persistent bottom content as the last child of the scroll body.
- Keep scroll body bottom padding large enough to avoid visual collision with `bottomNavigationBar` when needed.

## DEV-COMPONENT-PAGE-LOCAL

- Similar or repeated elements within one page should be extracted as page-local components.
- Keep page-local components in the same Dart file as private widgets/classes.
- Do not split page-local repeated elements into separate files.

## DEV-COMPONENT-COMMON

- Components that provide the same function and are used broadly across the project should be separately encapsulated as common widgets.
- Use this only when project usage or user confirmation shows the component is project-level, not page-specific.
- In the plan review, classify broadly reused functional components as `new-common` and state that they need separate common-widget encapsulation.

## DEV-LAYOUT-LINEAR-FIRST

- Prefer linear layout with `Row` and `Column` for non-overlapping sibling groups.
- Use `Stack` / `Positioned` only for real overlap, decorative overlays, badges, or fixed-artboard evidence.

## DEV-LAYOUT-STACK-ADAPTIVE

- Any `Stack` / `Positioned` design must explain how it adapts across screen sizes.
- Avoid raw absolute positions that drift on different resolutions.
- Prefer parent constraints, `Align`, `Padding`, `FractionallySizedBox`, or calculated insets when they preserve the relationship.

## DEV-UNITS-IOS-PT

- Treat numeric geometry from `spec.md` as design px.
- Flutter code uses iOS pt / Flutter logical pixels.
- Infer `{{PT_SCALE}}`: use `1` if artboard width already matches common iOS pt widths (`320/375/390/393/402/414/428/430`); otherwise choose `2` or `3` so `artboard_width / scale` is closest to those widths.
- Convert text size, spacing, radius, border width, icon size, image size, and explicit visual sizes with `pt = design_px / {{PT_SCALE}}`.
- Run `check_static.py` with `--font-scale {{PT_SCALE}}`.

## DEV-ASSETS-WEBP-2X

- Page background images, icons, and logos should use WebP 2x assets.
- Prefer existing or generated `webp` assets that represent the design at 2x scale.
- Preserve image, icon, and logo aspect ratio unless the spec explicitly indicates stretch.
- If the required WebP 2x asset is missing, report it as a missing slice/asset instead of substituting a different format silently.
